package com.factupos.sms;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Telephony;
import android.telephony.SmsMessage;
import android.telephony.SubscriptionInfo;
import android.telephony.SubscriptionManager;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Recibe los SMS entrantes (SMS_RECEIVED), arma el mensaje y lo reenvía al servidor. */
public class SmsReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(final Context context, Intent intent) {
        if (intent == null || !Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction())) {
            return;
        }

        SmsMessage[] msgs = Telephony.Sms.Intents.getMessagesFromIntent(intent);
        if (msgs == null || msgs.length == 0) return;

        String origen = msgs[0].getOriginatingAddress();
        StringBuilder texto = new StringBuilder();
        long ts = msgs[0].getTimestampMillis();
        for (SmsMessage m : msgs) {
            if (m != null && m.getMessageBody() != null) texto.append(m.getMessageBody());
        }

        // sub_id de la SIM (dual-SIM). El extra "subscription" trae el subscriptionId.
        int subId = -1;
        Bundle extras = intent.getExtras();
        if (extras != null) subId = extras.getInt("subscription", -1);

        final String fOrigen = origen == null ? "" : origen;
        final String fTexto = texto.toString();
        final int fSubId = subId;
        final String fSim = describeSim(context, subId);
        final String fFecha = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
                .format(new Date(ts > 0 ? ts : System.currentTimeMillis()));

        // Si el servicio está detenido, no reenviar.
        if (!Config.isServicioActivo(context)) return;

        // Empresa según el SIM por el que entró el SMS (config por slot de SIM).
        int slot = slotForSubId(context, subId);
        final String empresa = Config.getEmpresaForSlot(context, slot);

        final String endpoint = Config.getEndpoint(context);
        final String token = Config.getToken(context);

        // Enviar en hilo de fondo manteniendo vivo el receiver hasta terminar.
        final PendingResult pr = goAsync();
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    Poster.post(endpoint, token, empresa, fFecha, fOrigen, fTexto, fSubId, fSim);
                } finally {
                    pr.finish();
                }
            }
        }).start();
    }

    /** Slot (0-based) de la SIM para un subId; -1 si no se puede determinar. */
    private int slotForSubId(Context ctx, int subId) {
        try {
            SubscriptionManager sm = (SubscriptionManager) ctx.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE);
            if (sm != null && subId >= 0) {
                SubscriptionInfo info = sm.getActiveSubscriptionInfo(subId);
                if (info != null) return info.getSimSlotIndex();
            }
        } catch (Exception e) {
            // sin permiso o info no disponible
        }
        return -1;
    }

    /** Describe la SIM por la que entró el SMS: "SIM1 (Kolbi ICE)". Requiere READ_PHONE_STATE. */
    private String describeSim(Context ctx, int subId) {
        try {
            SubscriptionManager sm = (SubscriptionManager) ctx.getSystemService(Context.TELEPHONY_SUBSCRIPTION_SERVICE);
            if (sm != null && subId >= 0) {
                SubscriptionInfo info = sm.getActiveSubscriptionInfo(subId);
                if (info != null) {
                    int slot = info.getSimSlotIndex() + 1; // 0-based -> SIM1/SIM2
                    CharSequence carrier = info.getCarrierName();
                    String s = "SIM" + slot;
                    if (carrier != null && carrier.length() > 0) s += " (" + carrier + ")";
                    return s;
                }
            }
        } catch (Exception e) {
            // sin permiso o info no disponible
        }
        return subId >= 0 ? ("sub" + subId) : "";
    }
}
