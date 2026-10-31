package local.vertex.pocket;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import org.json.*;

public class GatewayTest {
    static KeyPair pair;
    static int tokens,chats,checks;
    static boolean unauthorizedOnce,forbidden;
    static JSONObject last;
    static void check(boolean b,String name){if(!b)throw new AssertionError(name);checks++;System.out.println("PASS "+name);}
    static class Fake extends HttpURLConnection {
        ByteArrayOutputStream request=new ByteArrayOutputStream();int code=200;byte[] response;
        Fake(URL u){super(u);}
        public void connect(){}public void disconnect(){}public boolean usingProxy(){return false;}
        public OutputStream getOutputStream(){return request;}
        void prepare()throws IOException {
            if(response!=null)return;
            try {
                if(url.getHost().equals("oauth2.googleapis.com")){
                    tokens++;
                    String body=request.toString("UTF-8");String jwt=URLDecoder.decode(body.substring(body.indexOf("&assertion=")+11),"UTF-8");String[] pieces=jwt.split("\\.");
                    Signature verify=Signature.getInstance("SHA256withRSA");verify.initVerify(pair.getPublic());verify.update((pieces[0]+"."+pieces[1]).getBytes(StandardCharsets.US_ASCII));
                    if(!verify.verify(Base64.getUrlDecoder().decode(pieces[2])))throw new AssertionError("JWT signature");
                    JSONObject claims=new JSONObject(new String(Base64.getUrlDecoder().decode(pieces[1]),StandardCharsets.UTF_8));
                    if(!claims.getString("aud").equals("https://oauth2.googleapis.com/token"))throw new AssertionError("JWT audience");
                    response="{\"access_token\":\"synthetic-token\",\"expires_in\":3600}".getBytes(StandardCharsets.UTF_8);
                }else{
                    chats++;last=new JSONObject(request.toString("UTF-8"));
                    if(!"Bearer synthetic-token".equals(getRequestProperty("Authorization")))throw new AssertionError("upstream authorization");
                    if(!url.toString().equals("https://aiplatform.googleapis.com/v1/projects/test-project/locations/global/endpoints/openapi/chat/completions"))throw new AssertionError("upstream URL");
                    if(unauthorizedOnce){unauthorizedOnce=false;code=401;response="{}".getBytes();}
                    else if(forbidden){code=403;response="{\"error\":{\"message\":\"permission denied\"}}".getBytes();}
                    else response=(last.optBoolean("stream")?"data: {\"choices\":[{\"delta\":{\"content\":\"你好\"}}]}\n\ndata: [DONE]\n\n":"{\"choices\":[{\"message\":{\"content\":\"你好\"}}]}").getBytes(StandardCharsets.UTF_8);
                }
            }catch(Exception e){throw new IOException(e);}
        }
        public int getResponseCode()throws IOException{prepare();return code;}
        public InputStream getInputStream()throws IOException{prepare();return new ByteArrayInputStream(response);}
        public InputStream getErrorStream(){try{return getInputStream();}catch(Exception e){throw new RuntimeException(e);}}
    }
    static String request(String method,String path,String key,String body)throws Exception{
        try(Socket s=new Socket("127.0.0.1",3425)){
            s.setSoTimeout(5000);byte[] bytes=body.getBytes(StandardCharsets.UTF_8);
            String h=method+" "+path+" HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer "+key+"\r\nContent-Length: "+bytes.length+"\r\n\r\n";
            s.getOutputStream().write(h.getBytes(StandardCharsets.US_ASCII));s.getOutputStream().write(bytes);s.getOutputStream().flush();
            return new String(GoogleAuth.read(s.getInputStream(),1048576),StandardCharsets.UTF_8);
        }
    }
    public static void main(String[] args)throws Exception{
        URL.setURLStreamHandlerFactory(protocol->protocol.equals("https")?new URLStreamHandler(){protected URLConnection openConnection(URL u){return new Fake(u);}}:null);
        KeyPairGenerator gen=KeyPairGenerator.getInstance("RSA");gen.initialize(2048);pair=gen.generateKeyPair();
        String pem="-----BEGIN PRIVATE KEY-----\n"+Base64.getEncoder().encodeToString(pair.getPrivate().getEncoded())+"\n-----END PRIVATE KEY-----";
        File file=Files.createTempFile("synthetic-credentials",".json").toFile();
        try {
            Files.write(file.toPath(),new JSONObject().put("type","service_account").put("project_id","test-project").put("client_email","test@example.invalid").put("private_key",pem).toString().getBytes(StandardCharsets.UTF_8));
            GoogleAuth auth=new GoogleAuth(file);Gateway g=new Gateway("test-project","global","test-secret","gemini-2.5-flash",auth);
            try {
                g.start();check(g.server.getInetAddress().isLoopbackAddress(),"only loopback listener");
                check(request("GET","/v1/models","wrong","").startsWith("HTTP/1.1 401"),"reject wrong key");
                check(tokens==0,"unauthorized requests do not reach Google");
                check(request("OPTIONS","/v1/chat/completions","","").startsWith("HTTP/1.1 204"),"browser CORS preflight");
                check(request("GET","/v1/models","test-secret","").contains("gemini-2.5-flash"),"configured model list");
                String body="{\"model\":\"gemini-2.5-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"你好\"}]}";
                check(request("POST","/v1/chat/completions","test-secret",body).contains("你好"),"UTF-8 chat response and signed JWT authentication");
                check(last.getString("model").equals("google/gemini-2.5-flash"),"Google model prefix");
                check(request("POST","/v1/chat/completions","test-secret",new JSONObject(body).put("stream",true).toString()).contains("data: [DONE]"),"SSE forwarding");
                check(tokens==1,"cached Google token reused");
                unauthorizedOnce=true;request("POST","/v1/chat/completions","test-secret",body);check(tokens==2,"Google 401 refresh and retry");
                forbidden=true;check(request("POST","/v1/chat/completions","test-secret",body).startsWith("HTTP/1.1 403"),"upstream permission errors preserved");forbidden=false;
                check(request("POST","/v1/chat/completions","test-secret","{").startsWith("HTTP/1.1 400"),"malformed JSON rejected");
                check(request("POST","/v1/responses","test-secret",body).startsWith("HTTP/1.1 404"),"unsupported endpoint rejected");
            } finally{g.close();}
            try(Socket s=new Socket("127.0.0.1",3425)){throw new AssertionError("port still open");}catch(ConnectException expected){checks++;System.out.println("PASS stop closes listener");}
            System.out.println(checks+" checks passed. Synthetic credentials only; no real Google requests.");
        }finally{file.delete();}
    }
}
