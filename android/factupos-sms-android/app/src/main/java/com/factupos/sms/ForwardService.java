package com.factupos.sms;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * Servicio foreground: no hace el envío (eso lo hace SmsReceiver), pero mantiene el
 * proceso "vivo" y visible para que Android no lo suspenda (optimización de batería).
 */
public class ForwardService extends Service {

    private static final String CH = "factupossms";

    @Override
    public void onCreate() {
        super.onCreate();
        Notification n = buildNotification();
        startForeground(1, n);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    private Notification buildNotification() {
        NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CH, "FactuposSMS", NotificationManager.IMPORTANCE_LOW);
            nm.createNotificationChannel(ch);
        }
        Notification.Builder b = (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                ? new Notification.Builder(this, CH)
                : new Notification.Builder(this);
        return b.setContentTitle("FactuposSMS activo")
                .setContentText("Capturando SMS de SINPE")
                .setSmallIcon(android.R.drawable.sym_def_app_icon)
                .setOngoing(true)
                .build();
    }

    public static void start(Context ctx) {
        Intent i = new Intent(ctx, ForwardService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            ctx.startForegroundService(i);
        } else {
            ctx.startService(i);
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
