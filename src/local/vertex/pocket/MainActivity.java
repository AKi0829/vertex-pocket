package local.vertex.pocket;

import android.app.*;
import android.os.*;
import android.content.*;
import android.graphics.Color;
import android.view.*;
import android.widget.*;
import android.text.InputType;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;

public class MainActivity extends Activity {
    EditText project, region, models, key;
    TextView status, imported;
    final Handler handler = new Handler();
    final Runnable refresh = new Runnable() { public void run() {
        if(status != null) status.setText(GatewayService.status);
        handler.postDelayed(this, 1000);
    }};
    void note(String s) { Toast.makeText(this,s,Toast.LENGTH_LONG).show(); }
    TextView text(LinearLayout root,String s,int size) {
        TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(Color.rgb(35,49,64));
        t.setPadding(0,16,0,8);root.addView(t);return t;
    }
    EditText field(LinearLayout root,String label,String value) {
        text(root,label,14);EditText e=new EditText(this);e.setSingleLine(true);e.setText(value);root.addView(e);return e;
    }
    void button(LinearLayout root,String title,View.OnClickListener l) {
        Button b=new Button(this);b.setText(title);root.addView(b);b.setOnClickListener(l);
    }
    android.content.SharedPreferences prefs() {return getSharedPreferences("config",0);}
    @Override public void onCreate(Bundle b) {
        super.onCreate(b);
        if(Build.VERSION.SDK_INT>=33 && checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=0)
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},1);
        ScrollView sc=new ScrollView(this);LinearLayout root=new LinearLayout(this);root.setOrientation(1);
        int p=(int)(20*getResources().getDisplayMetrics().density);root.setPadding(p,p,p,p);sc.addView(root);setContentView(sc);
        sc.setOnApplyWindowInsetsListener((view,insets)->{root.setPadding(p,p+insets.getSystemWindowInsetTop(),p,p+insets.getSystemWindowInsetBottom());return insets;});
        text(root,"Vertex 口袋网关",26);
        text(root,"导入密钥 · 点击启动 · 聊天软件直接连接\n独立运行，无需 Termux。仅本机可连接。",15);
        imported=text(root,new File(getFilesDir(),"credentials.json").exists()?"已导入服务账号密钥":"尚未导入 Google 服务账号 JSON",14);
        button(root,"① 选择 Google JSON 密钥",v->{
            Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT);i.setType("*/*");i.addCategory(Intent.CATEGORY_OPENABLE);startActivityForResult(i,10);
        });
        project=field(root,"项目 ID（导入后自动填写，可修改）",prefs().getString("project",""));
        region=field(root,"Vertex 区域（默认 global）",prefs().getString("region","global"));
        models=field(root,"模型列表（英文逗号分隔，需有访问权限）",prefs().getString("models","gemini-2.5-flash,gemini-2.5-pro"));
        key=field(root,"本地访问 Key（随机生成，也可自定义）",prefs().getString("key",randomKey()));
        key.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);
        button(root,"复制访问 Key",v->copy("访问 Key",key.getText().toString()));
        button(root,"② 保存并启动",v->{try {
            if(GatewayService.running) throw new Exception("请先停止服务，再修改配置");
            save();startForegroundService(new Intent(this,GatewayService.class));
        }catch(Exception e){note(e.getMessage());}});
        button(root,"停止服务",v->stopService(new Intent(this,GatewayService.class)));
        status=text(root,GatewayService.status,16);
        text(root,"聊天软件连接信息",20);
        text(root,"类型：OpenAI 兼容 / 自定义\n地址：http://127.0.0.1:3425/v1\nAPI Key：填写上面的访问 Key\n模型：填写上方列表中的一个模型",15);
        button(root,"复制 API 地址",v->copy("API 地址","http://127.0.0.1:3425/v1"));
        button(root,"检测 Google 凭据（不生成回复）",v->{
            try {if(GatewayService.running)throw new Exception("请先停止服务再检测凭据");save();}
            catch(Exception e){note(e.getMessage());return;}
            new Thread(()->{String result;try{new GoogleAuth(new File(getFilesDir(),"credentials.json")).token();result="凭据可用，成功取得 Google 访问令牌。模型权限和计费仍需实际聊天确认。";}
            catch(Exception e){result="检测失败："+e.getMessage();}final String msg=result;runOnUiThread(()->new AlertDialog.Builder(this).setMessage(msg).setPositiveButton("知道了",null).show());}).start();
        });
        text(root,"使用提示\n• 先在 Google Cloud 开启 Vertex AI API、计费，并授予服务账号模型调用权限。\n• 模型列表由你配置，并非实时查询可用模型。区域须支持该模型。\n• 支持 /v1/models 和 /v1/chat/completions，含流式回复。\n• 后台运行时保留通知，并在系统电池设置中允许本应用后台运行。强制停止或重启手机后需重新点击启动。\n• JSON 密钥仅保存在本应用私有目录；卸载即删除。不会上传到第三方服务器。Google 调用按你的项目计费。",13);
    }
    void save() throws Exception {
        if(!new File(getFilesDir(),"credentials.json").exists())throw new Exception("请先导入 JSON 密钥");
        String p=project.getText().toString().trim(),r=region.getText().toString().trim(),k=key.getText().toString();
        if(!p.matches("[a-z][a-z0-9-]{3,61}[a-z0-9]")||!r.matches("[a-z][a-z0-9-]{1,40}"))throw new Exception("请检查项目 ID 和区域");
        if(k.length()<8||k.contains("\n")||k.contains("\r")||!k.equals(k.trim()))throw new Exception("访问 Key 至少 8 位，不能含换行或首尾空格");
        if(models.getText().toString().trim().isEmpty())throw new Exception("请填写模型名");
        prefs().edit().putString("project",p).putString("region",r).putString("key",k).putString("models",models.getText().toString().trim()).commit();
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);if(request!=10||result!=RESULT_OK||data==null)return;
        try {
            if(GatewayService.running)throw new Exception("请先停止服务再导入密钥");
            byte[] raw;try(InputStream in=getContentResolver().openInputStream(data.getData())){raw=GoogleAuth.read(in,131072);}
            JSONObject j=new JSONObject(new String(raw,StandardCharsets.UTF_8));GoogleAuth.validate(j);
            File f=new File(getFilesDir(),"credentials.json");try(FileOutputStream out=new FileOutputStream(f)){out.write(raw);}
            project.setText(j.getString("project_id"));imported.setText("已导入服务账号密钥");note("导入成功");
        }catch(Exception e){note("导入失败："+e.getMessage());}
    }
    void copy(String label,String value){((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText(label,value));note("已复制");}
    static String randomKey(){byte[] b=new byte[24];new SecureRandom().nextBytes(b);return android.util.Base64.encodeToString(b,11);}
    @Override protected void onResume(){super.onResume();handler.post(refresh);}
    @Override protected void onPause(){handler.removeCallbacks(refresh);super.onPause();}
}
