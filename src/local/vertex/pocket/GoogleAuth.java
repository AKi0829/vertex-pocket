package local.vertex.pocket;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Base64;

final class GoogleAuth {
    final JSONObject credentials;
    String cached; long expires;
    GoogleAuth(File file)throws Exception {try(InputStream in=new FileInputStream(file)){credentials=new JSONObject(new String(read(in,131072),StandardCharsets.UTF_8));}validate(credentials);}
    static void validate(JSONObject j)throws Exception {
        if(!"service_account".equals(j.optString("type"))||j.optString("client_email").isEmpty()||j.optString("project_id").isEmpty())throw new Exception("需要 service_account 类型的 JSON 密钥");
        privateKey(j);
    }
    static PrivateKey privateKey(JSONObject j)throws Exception {
        String pem=j.getString("private_key").replace("-----BEGIN PRIVATE KEY-----","").replace("-----END PRIVATE KEY-----","").replaceAll("\\s","");
        return KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(Base64.getDecoder().decode(pem)));
    }
    static String b64(byte[] b){return Base64.getUrlEncoder().withoutPadding().encodeToString(b);}
    synchronized String token()throws Exception {
        long now=System.currentTimeMillis()/1000;if(cached!=null&&now<expires-120)return cached;
        JSONObject header=new JSONObject().put("alg","RS256").put("typ","JWT");
        JSONObject claim=new JSONObject().put("iss",credentials.getString("client_email")).put("scope","https://www.googleapis.com/auth/cloud-platform").put("aud","https://oauth2.googleapis.com/token").put("iat",now).put("exp",now+3600);
        String input=b64(header.toString().getBytes(StandardCharsets.UTF_8))+"."+b64(claim.toString().getBytes(StandardCharsets.UTF_8));
        Signature sig=Signature.getInstance("SHA256withRSA");sig.initSign(privateKey(credentials));sig.update(input.getBytes(StandardCharsets.US_ASCII));
        String jwt=input+"."+b64(sig.sign());
        HttpURLConnection c=(HttpURLConnection)new URL("https://oauth2.googleapis.com/token").openConnection();
        try {
            c.setConnectTimeout(20000);c.setReadTimeout(30000);c.setInstanceFollowRedirects(false);c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/x-www-form-urlencoded");
            byte[] body=("grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion="+URLEncoder.encode(jwt,"UTF-8")).getBytes(StandardCharsets.UTF_8);
            try(OutputStream out=c.getOutputStream()){out.write(body);}
            int code=c.getResponseCode();InputStream in=code<400?c.getInputStream():c.getErrorStream();
            JSONObject reply;try(InputStream stream=in){reply=new JSONObject(new String(read(stream,1048576),StandardCharsets.UTF_8));}
            if(code!=200)throw new IOException("Google 认证失败 HTTP "+code+"："+reply.optString("error")+"；请检查密钥和手机时间");
            cached=reply.getString("access_token");expires=now+reply.optInt("expires_in",3600);return cached;
        }finally{c.disconnect();}
    }
    synchronized void invalidate(){cached=null;}
    static byte[] read(InputStream in,int limit)throws IOException {
        if(in==null)throw new IOException("空响应");ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;
        while((n=in.read(b))!=-1){if(out.size()+n>limit)throw new IOException("内容过大");out.write(b,0,n);}return out.toByteArray();
    }
}
