package local.vertex.pocket;
import android.app.*;
import android.content.*;
import android.os.*;
import java.io.*;

public class GatewayService extends Service {
    public static volatile boolean running=false;
    public static volatile String status="服务未启动";
    Gateway gateway;
    PowerManager.WakeLock wake;
    @Override public void onCreate(){
        super.onCreate();
        NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel("gateway","本机网关运行状态",NotificationManager.IMPORTANCE_LOW));
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop=PendingIntent.getService(this,1,new Intent(this,GatewayService.class).setAction("stop"),PendingIntent.FLAG_IMMUTABLE);
        Notification n=new Notification.Builder(this,"gateway").setContentTitle("Vertex 口袋网关运行中").setContentText("127.0.0.1:3425 · 点击打开设置")
            .setSmallIcon(android.R.drawable.stat_notify_sync).setContentIntent(open).setOngoing(true).addAction(android.R.drawable.ic_delete,"停止",stop).build();
        startForeground(1,n);
    }
    @Override public int onStartCommand(Intent i,int flags,int id){
        if(i!=null&&"stop".equals(i.getAction())){stopSelf();return START_NOT_STICKY;}
        if(gateway!=null)return START_NOT_STICKY;
        try {
            android.content.SharedPreferences p=getSharedPreferences("config",0);
            gateway=new Gateway(p.getString("project",""),p.getString("region","global"),p.getString("key",""),p.getString("models",""),new GoogleAuth(new File(getFilesDir(),"credentials.json")));
            gateway.start();running=true;status="已启动 · 127.0.0.1:3425";
            wake=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"vertex:gateway");wake.acquire();
        }catch(Exception e){status="启动失败："+e.getMessage();stopSelf();}
        return START_NOT_STICKY;
    }
    @Override public void onDestroy(){if(gateway!=null)gateway.close();if(wake!=null&&wake.isHeld())wake.release();running=false;if(!status.startsWith("启动失败"))status="服务已停止";stopForeground(true);super.onDestroy();}
    @Override public IBinder onBind(Intent i){return null;}
}
