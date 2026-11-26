package com.factupos.sms;

import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.telephony.SubscriptionInfo;
import android.telephony.SubscriptionManager;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

/**
 * UI de FactuposSMS. El usuario define el nombre de la BD/empresa POR CADA SIM,
 * y arranca/detiene el servicio de captura. Endpoint y token son internos.
 */
public class MainActivity extends Activity {

    private LinearLayout col;
    private Button btnServicio;
    private TextView status;
    private int pad;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        pad = (int) (16 * getResources().getDisplayMetrics().density);

        col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(pad, pad, pad, pad);

        ScrollView sv = new ScrollView(this);
        sv.addView(col);
        setContentView(sv);

        pedirPermisos();
        construirUI();
    }

    private void pedirPermisos() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            requestPermissions(new String[]{
                    "android.permission.RECEIVE_SMS",
                    "android.permission.READ_SMS",
                    "android.permission.READ_PHONE_STATE",
                    "android.permission.POST_NOTIFICATIONS"
            }, 100);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        construirUI(); // reconstruir: ya con permiso podemos listar las SIM
    }

    private void construirUI() {
        col.removeAllViews();

        TextView title = new TextView(this);
        title.setText("Factupos Sms");
        title.setTextSize(26);
        title.setTypeface(title.getTypeface(), android.graphics.Typeface.BOLD);
        title.setTextColor(Color.parseColor("#0047AB"));
        col.addView(title);

        TextView ver = new TextView(this);
        ver.setText("Versión 1.0");
        ver.setTextSize(14);
        ver.setTextColor(Color.parseColor("#64748b"));
        ver.setPadding(0, 0, 0, pad);
        col.addView(ver);

        // ---- Una config por cada SIM ----
        List<SubscriptionInfo> sims = null;
        try {
            SubscriptionManager sm = (SubscriptionManager) getSystemService(TELEPHONY_SUBSCRIPTION_SERVICE);
            if (sm != null) sims = sm.getActiveSubscriptionInfoList();
        } catch (SecurityException e) {
            // sin permiso aún
        }

        if (sims == null || sims.isEmpty()) {
            TextView aviso = new TextView(this);
            aviso.setText("Conceda los permisos de Teléfono y SMS y reabra la app para ver las SIM.");
            aviso.setTextColor(Color.parseColor("#b91c1c"));
            aviso.setPadding(0, 0, 0, pad);
            col.addView(aviso);
        } else {
            for (SubscriptionInfo info : sims) {
                int slot = info.getSimSlotIndex();
                CharSequence carrier = info.getCarrierName();
                String numero = info.getNumber() != null ? info.getNumber() : "";
                String etiqueta = "SIM " + (slot + 1)
                        + (carrier != null && carrier.length() > 0 ? " — " + carrier : "")
                        + (!numero.isEmpty() ? " (" + numero + ")" : "");
                agregarFichaSim(slot, etiqueta);
            }
        }

        // ---- Iniciar / Detener servicio ----
        View sep = new View(this);
        sep.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 2));
        sep.setBackgroundColor(Color.parseColor("#cbd5e1"));
        sep.setPadding(0, pad, 0, pad);
        col.addView(sep);

        btnServicio = new Button(this);
        btnServicio.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { toggleServicio(); }
        });
        col.addView(btnServicio);
        refrescarBotonServicio();

        status = new TextView(this);
        status.setPadding(0, pad, 0, 0);
        status.setText(Config.isServicioActivo(this) ? "Servicio en marcha" : "Servicio detenido");
        col.addView(status);

        Button btnSalir = new Button(this);
        btnSalir.setText("Salir");
        btnSalir.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { finishAndRemoveTask(); }
        });
        col.addView(btnSalir);
    }

    /** Ficha de un SIM: etiqueta + input del nombre de BD/empresa + botón Guardar. */
    private void agregarFichaSim(final int slot, String etiqueta) {
        TextView lbl = new TextView(this);
        lbl.setText(etiqueta);
        lbl.setTextSize(15);
        lbl.setTypeface(lbl.getTypeface(), android.graphics.Typeface.BOLD);
        lbl.setPadding(0, pad / 2, 0, 0);
        col.addView(lbl);

        TextView sub = new TextView(this);
        sub.setText("Nombre de la BD / empresa para este SIM:");
        sub.setTextSize(12);
        sub.setTextColor(Color.parseColor("#64748b"));
        col.addView(sub);

        final EditText et = new EditText(this);
        et.setSingleLine(true);
        et.setText(Config.getEmpresaForSlot(this, slot));
        col.addView(et);

        Button guardar = new Button(this);
        guardar.setText("Guardar SIM " + (slot + 1));
        guardar.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                Config.setEmpresaForSlot(MainActivity.this, slot, et.getText().toString().trim());
                Toast.makeText(MainActivity.this, "Guardado SIM " + (slot + 1), Toast.LENGTH_SHORT).show();
                if (status != null) {
                    status.setTextColor(Color.parseColor("#16a34a"));
                    status.setText("✓ Configuración del SIM " + (slot + 1) + " guardada");
                }
            }
        });
        col.addView(guardar);
    }

    private void toggleServicio() {
        boolean activo = Config.isServicioActivo(this);
        if (activo) {
            Config.setServicioActivo(this, false);
            stopService(new android.content.Intent(this, ForwardService.class));
            status.setTextColor(Color.parseColor("#b91c1c"));
            status.setText("Servicio detenido");
        } else {
            Config.setServicioActivo(this, true);
            ForwardService.start(this);
            status.setTextColor(Color.parseColor("#16a34a"));
            status.setText("✓ Servicio en marcha");
        }
        refrescarBotonServicio();
    }

    private void refrescarBotonServicio() {
        btnServicio.setText(Config.isServicioActivo(this) ? "Detener servicio" : "Iniciar servicio");
    }
}
