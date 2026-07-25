package com.factupos.sms;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Arranca el servicio foreground al encender el teléfono. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) return;
        String a = intent.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(a) || "android.intent.action.QUICKBOOT_POWERON".equals(a)) {
            if (Config.isServicioActivo(context)) {
                ForwardService.start(context);
            }
        }
    }
}
