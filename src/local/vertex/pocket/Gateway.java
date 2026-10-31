package local.vertex.pocket;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

final class Gateway implements AutoCloseable {
    final String project,region,key,models;
    final GoogleAuth auth;
    final Set<Socket> sockets=ConcurrentHashMap.newKeySet();
    final Set<HttpURLConnection> upstreams=ConcurrentHashMap.newKeySet();
    final ThreadPoolExecutor pool=new ThreadPoolExecutor(4,4,0,TimeUnit.SECONDS,new ArrayBlockingQueue<Runnable>(16));
    volatile boolean closed;
    ServerSocket server;
    Gateway(String p,String r,String k,String m,GoogleAuth a)throws Exception {
        if(!p.matches("[a-z][a-z0-9-]{3,61}[a-z0-9]")||!r.matches("[a-z][a-z0-9-]{1,40}")||k.length()<8)throw new Exception("请先保存有效配置");
        project=p;region=r;key=k;models=m;auth=a;
    }
    void start()throws IOException {
        server=new ServerSocket();server.setReuseAddress(true);server.bind(new InetSocketAddress("127.0.0.1",3425));
        new Thread(()->{while(!closed)try {
            Socket s=server.accept();s.setSoTimeout(30000);sockets.add(s);
            try {pool.execute(()->handle(s));}catch(RejectedExecutionException e){sockets.remove(s);s.close();}
        }catch(IOException e){if(!closed)close();}},"vertex-listener").start();
    }
    static String line(InputStream in)throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream();int b;
        while((b=in.read())!=-1){if(b==10)break;if(out.size()>=8192)throw new IOException("请求行过长");if(b!=13)out.write(b);}
        if(b==-1&&out.size()==0)return null;return out.toString("US-ASCII");
    }
    static void headers(OutputStream out,int code,String type)throws IOException {
        String reason=code==200?"OK":code==204?"No Content":"Error";
        out.write(("HTTP/1.1 "+code+" "+reason+"\r\nContent-Type: "+type+"\r\nConnection: close\r\nCache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, POST, OPTIONS\r\nAccess-Control-Allow-Headers: Authorization, Content-Type, X-API-Key\r\n\r\n").getBytes(StandardCharsets.US_ASCII));out.flush();
    }
    static void json(OutputStream out,int code,String body)throws IOException {headers(out,code,"application/json; charset=utf-8");out.write(body.getBytes(StandardCharsets.UTF_8));out.flush();}
    static String error(String message){try{return new JSONObject().put("error",new JSONObject().put("message",message).put("type","gateway_error")).toString();}catch(Exception e){return "{}";}}
    void handle(Socket socket) {
        boolean sent=false;HttpURLConnection upstream=null;
        try(Socket s=socket){
            InputStream in=new BufferedInputStream(s.getInputStream());OutputStream out=s.getOutputStream();
            try {
                String first=line(in);if(first==null)return;String[] parts=first.split(" ");
                if(parts.length!=3){json(out,400,error("无效 HTTP 请求"));return;}
                String method=parts[0],path=parts[1].split("\\?",2)[0];Map<String,String> h=new HashMap<>();
                int count=0;String l;while((l=line(in))!=null&&!l.isEmpty()){
                    if(++count>64)throw new IOException("请求头过多");int at=l.indexOf(':');if(at<=0)throw new IOException("无效请求头");
                    String name=l.substring(0,at).trim().toLowerCase(Locale.ROOT);if(h.containsKey(name))throw new IOException("重复请求头");h.put(name,l.substring(at+1).trim());
                }
                if("OPTIONS".equals(method)){headers(out,204,"text/plain");return;}
                String supplied=h.getOrDefault("authorization","");
                if(!supplied.startsWith("Bearer ")||!MessageDigest.isEqual(supplied.substring(7).getBytes(StandardCharsets.UTF_8),key.getBytes(StandardCharsets.UTF_8))){json(out,401,error("访问 Key 不正确，请使用 Authorization: Bearer <Key>"));return;}
                if("GET".equals(method)&&"/v1/models".equals(path)){
                    JSONArray list=new JSONArray();for(String name:models.split(",")){name=name.trim();if(!name.isEmpty())list.put(new JSONObject().put("id",name).put("object","model").put("created",0).put("owned_by","google"));}
                    json(out,200,new JSONObject().put("object","list").put("data",list).toString());return;
                }
                if(!"POST".equals(method)||!"/v1/chat/completions".equals(path)){json(out,404,error("支持 GET /v1/models 和 POST /v1/chat/completions"));return;}
                if(h.containsKey("transfer-encoding")){json(out,411,error("请使用 Content-Length 发送请求"));return;}
                int length;try{length=Integer.parseInt(h.getOrDefault("content-length","-1"));}catch(Exception e){length=-1;}
                if(length<=0||length>8*1024*1024){json(out,413,error("请求体必须为 1 字节至 8 MB"));return;}
                byte[] body=new byte[length];int pos=0,n;while(pos<length&&(n=in.read(body,pos,length-pos))!=-1)pos+=n;if(pos!=length)throw new IOException("请求未接收完整");
                JSONObject payload=new JSONObject(new String(body,StandardCharsets.UTF_8));String model=payload.optString("model").trim();
                if(model.isEmpty()){json(out,400,error("请填写模型名"));return;}if(!model.contains("/"))payload.put("model","google/"+model);
                if(!(payload.opt("messages") instanceof JSONArray)){json(out,400,error("messages 必须为数组"));return;}
                byte[] request=payload.toString().getBytes(StandardCharsets.UTF_8);
                String host="global".equals(region)?"aiplatform.googleapis.com":region+"-aiplatform.googleapis.com";
                URL url=new URL("https://"+host+"/v1/projects/"+project+"/locations/"+region+"/endpoints/openapi/chat/completions");
                for(int attempt=0;attempt<2;attempt++){
                    String token=auth.token();if(closed)return;
                    upstream=(HttpURLConnection)url.openConnection();upstreams.add(upstream);
                    upstream.setConnectTimeout(20000);upstream.setReadTimeout(180000);upstream.setInstanceFollowRedirects(false);
                    upstream.setRequestMethod("POST");upstream.setDoOutput(true);upstream.setFixedLengthStreamingMode(request.length);
                    upstream.setRequestProperty("Authorization","Bearer "+token);upstream.setRequestProperty("Content-Type","application/json");upstream.setRequestProperty("Accept-Encoding","identity");
                    try(OutputStream send=upstream.getOutputStream()){send.write(request);}
                    int code=upstream.getResponseCode();
                    if(code==401&&attempt==0){auth.invalidate();upstreams.remove(upstream);upstream.disconnect();upstream=null;continue;}
                    boolean stream=payload.optBoolean("stream",false)&&code>=200&&code<300;
                    InputStream reply=code>=400?upstream.getErrorStream():upstream.getInputStream();
                    headers(out,code,stream?"text/event-stream; charset=utf-8":"application/json; charset=utf-8");sent=true;
                    if(reply!=null)try(InputStream source=reply){byte[] buffer=new byte[8192];while((n=source.read(buffer))!=-1){out.write(buffer,0,n);out.flush();}}
                    else {out.write(error("Google 返回空响应 HTTP "+code).getBytes(StandardCharsets.UTF_8));out.flush();}
                    return;
                }
            }catch(Exception e){if(!sent&&!closed){try{json(out,e instanceof JSONException?400:502,error(e instanceof JSONException?"JSON 格式错误":"网关连接失败："+safeMessage(e)));}catch(Exception ignored){}}}
        }catch(Exception ignored){}finally{if(upstream!=null){upstreams.remove(upstream);upstream.disconnect();}sockets.remove(socket);}
    }
    static String safeMessage(Exception e){String m=e.getMessage();return m==null?e.getClass().getSimpleName():m;}
    @Override public void close(){closed=true;if(server!=null)try{server.close();}catch(Exception ignored){}for(Socket s:sockets)try{s.close();}catch(Exception ignored){}for(HttpURLConnection c:upstreams)c.disconnect();pool.shutdownNow();}
}
