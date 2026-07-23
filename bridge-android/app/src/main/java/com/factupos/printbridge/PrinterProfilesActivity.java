package com.factupos.printbridge;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * PrinterProfilesActivity - Gestión de las impresoras configuradas.
 *
 * Cada perfil es una impresora Y una cola del servidor. Reemplaza al modelo de
 * "una sola impresora activa": una tablet puede atender su USB propia y a la vez
 * una impresora de red.
 *
 * La lista de dispositivos detectados (BT pareados, USB, serial) se usa solo dentro
 * del diálogo de edición, para elegir la dirección sin escribirla a mano.
 */
public class PrinterProfilesActivity extends AppCompatActivity {

    private PrinterProfileStore store;
    private LinearLayout listContainer;
    private TextView txtVacio;
    private TextView txtEstadoCola;

    private int dp(float v) {
        return (int) (v * getResources().getDisplayMetrics().density + 0.5f);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setTitle("Impresoras configuradas");
        store = new PrinterProfileStore(this);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(0xFFF1F5F9);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(16), dp(16), dp(24));

        Button btnAgregar = new Button(this);
        btnAgregar.setText("+  Agregar impresora");
        btnAgregar.setTextColor(Color.WHITE);
        btnAgregar.setBackgroundTintList(
            android.content.res.ColorStateList.valueOf(0xFF2563EB));
        btnAgregar.setOnClickListener(v -> mostrarDialogo(null));
        root.addView(btnAgregar);

        Button btnServidor = new Button(this);
        btnServidor.setText("Servidor de cola");
        btnServidor.setTextColor(Color.WHITE);
        btnServidor.setBackgroundTintList(
            android.content.res.ColorStateList.valueOf(0xFF475569));
        btnServidor.setOnClickListener(v -> mostrarDialogoServidor());
        root.addView(btnServidor);

        txtEstadoCola = new TextView(this);
        txtEstadoCola.setTextSize(12);
        txtEstadoCola.setPadding(dp(4), dp(10), dp(4), 0);
        root.addView(txtEstadoCola);

        txtVacio = new TextView(this);
        txtVacio.setText("Todavía no hay impresoras configuradas.\n\n"
                       + "Agregá una por cada impresora que esta tablet deba atender. "
                       + "El código de cola y la empresa los define el servidor.");
        txtVacio.setTextSize(13);
        txtVacio.setTextColor(0xFF64748B);
        txtVacio.setPadding(dp(4), dp(24), dp(4), dp(8));
        root.addView(txtVacio);

        listContainer = new LinearLayout(this);
        listContainer.setOrientation(LinearLayout.VERTICAL);
        root.addView(listContainer);

        scroll.addView(root);
        setContentView(scroll);
    }

    @Override
    protected void onResume() {
        super.onResume();
        redibujar();
    }

    // ------------------------------------------------------------------
    // Listado
    // ------------------------------------------------------------------

    private void redibujar() {
        listContainer.removeAllViews();
        List<PrinterProfile> perfiles = store.getAll();
        txtVacio.setVisibility(perfiles.isEmpty() ? View.VISIBLE : View.GONE);

        for (int i = 0; i < perfiles.size(); i++) {
            listContainer.addView(construirFila(perfiles.get(i)));
        }
        actualizarEstadoCola();
    }

    /** Estado del cliente de cola, para que se vea si está conectado o no. */
    private void actualizarEstadoCola() {
        if (txtEstadoCola == null) return;
        PrintQueueClient qc = PrintService.getStaticQueueClient();
        if (qc == null) {
            txtEstadoCola.setText("Cola: servicio no iniciado");
            txtEstadoCola.setTextColor(0xFF94A3B8);
            return;
        }
        if (!qc.isEnabled()) {
            txtEstadoCola.setText("Cola: desactivada (esta estación todavía usa el modo local)");
            txtEstadoCola.setTextColor(0xFF94A3B8);
            return;
        }
        int pendientes = qc.getQueue().size();
        String txt = "Cola: " + qc.getEstado()
                   + (pendientes > 0 ? "  ·  " + pendientes + " pendiente(s)" : "");
        txtEstadoCola.setText(txt);
        txtEstadoCola.setTextColor(qc.isConnected() ? 0xFF059669 : 0xFFDC2626);
    }

    /**
     * Ajustes de conexión al servidor de colas. Acá es donde se pasa una estación
     * del modo local al modo WebSocket.
     */
    private void mostrarDialogoServidor() {
        final PrintQueueClient qc = PrintService.getStaticQueueClient();
        if (qc == null) {
            Toast.makeText(this, "El servicio no está iniciado", Toast.LENGTH_SHORT).show();
            return;
        }

        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(20), dp(12), dp(20), dp(8));

        final CheckBox chkActivo = new CheckBox(this);
        chkActivo.setText("Recibir trabajos por WebSocket");
        chkActivo.setChecked(qc.isEnabled());
        form.addView(chkActivo);

        TextView nota = new TextView(this);
        nota.setText("Al activarlo, esta tablet jala los trabajos de la cola central. "
                   + "Dejalo apagado si la estación todavía imprime por el modo local.");
        nota.setTextSize(11);
        nota.setTextColor(0xFF64748B);
        nota.setPadding(0, dp(4), 0, dp(4));
        form.addView(nota);

        form.addView(etiqueta("Servidores (separados por coma)"));
        StringBuilder sb = new StringBuilder();
        List<String> srv = qc.getServers();
        for (int i = 0; i < srv.size(); i++) {
            if (i > 0) sb.append(", ");
            sb.append(srv.get(i));
        }
        final EditText inServers = campoTexto("ws://host:9300", sb.toString());
        inServers.setSingleLine(false);
        form.addView(inServers);

        form.addView(etiqueta("Identificador de esta tablet"));
        final EditText inClientId = campoTexto("clientId", qc.getClientId());
        form.addView(inClientId);

        TextView estado = new TextView(this);
        estado.setText("Estado: " + qc.getEstado()
                     + "\nPendientes en cola local: " + qc.getQueue().size()
                     + (qc.getUltimoError().isEmpty() ? "" : "\nÚltimo error: " + qc.getUltimoError()));
        estado.setTextSize(11);
        estado.setTextColor(0xFF475569);
        estado.setPadding(0, dp(14), 0, 0);
        form.addView(estado);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(form);

        new AlertDialog.Builder(this)
            .setTitle("Servidor de cola")
            .setView(scroll)
            .setPositiveButton("Guardar", (d, w) -> {
                qc.setServers(inServers.getText().toString());
                qc.setClientId(inClientId.getText().toString());
                boolean activar = chkActivo.isChecked();
                qc.setEnabled(activar);
                if (activar) {
                    if (!store.hasUsableProfile()) {
                        Toast.makeText(this,
                            "Configurá al menos una impresora con su cola antes de activar",
                            Toast.LENGTH_LONG).show();
                    } else {
                        qc.stop();
                        qc.start();
                    }
                } else {
                    qc.stop();
                }
                actualizarEstadoCola();
            })
            .setNegativeButton("Cancelar", null)
            .setNeutralButton("Vaciar cola local", (d, w) -> {
                int n = qc.getQueue().clear();
                Toast.makeText(this, "Cola local vaciada (" + n + ")", Toast.LENGTH_SHORT).show();
                actualizarEstadoCola();
            })
            .show();
    }

    private View construirFila(final PrinterProfile p) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackgroundColor(Color.WHITE);
        card.setPadding(dp(14), dp(12), dp(14), dp(12));
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        clp.topMargin = dp(10);
        card.setLayoutParams(clp);

        // Línea 1: nombre + chip de transporte
        LinearLayout l1 = new LinearLayout(this);
        l1.setOrientation(LinearLayout.HORIZONTAL);
        l1.setGravity(Gravity.CENTER_VERTICAL);

        TextView nombre = new TextView(this);
        nombre.setText(p.getDisplayName());
        nombre.setTextSize(15);
        nombre.setTextColor(0xFF1E293B);
        nombre.setLayoutParams(new LinearLayout.LayoutParams(0,
            LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        l1.addView(nombre);
        l1.addView(chip(transporteLabel(p.transport), transporteColor(p.transport)));
        card.addView(l1);

        // Línea 2: cola / empresa
        TextView sub = new TextView(this);
        String colaTxt = (p.queueCode == null || p.queueCode.isEmpty())
            ? "⚠ sin cola asignada"
            : "Cola " + p.queueCode;
        if (p.empresa != null && !p.empresa.isEmpty()) colaTxt += " · " + p.empresa;
        sub.setText(colaTxt);
        sub.setTextSize(12);
        sub.setTextColor((p.queueCode == null || p.queueCode.isEmpty())
            ? 0xFFDC2626 : 0xFF475569);
        sub.setPadding(0, dp(3), 0, 0);
        card.addView(sub);

        // Línea 3: destino concreto
        TextView dest = new TextView(this);
        dest.setText(destinoLabel(p));
        dest.setTextSize(11);
        dest.setTextColor(0xFF94A3B8);
        dest.setPadding(0, dp(2), 0, 0);
        card.addView(dest);

        // Línea 4: acciones
        LinearLayout acciones = new LinearLayout(this);
        acciones.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams alp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        alp.topMargin = dp(8);
        acciones.setLayoutParams(alp);

        acciones.addView(accionBtn("Editar", 0xFF3730A3, v -> mostrarDialogo(p)));
        acciones.addView(accionBtn("Probar", 0xFF059669, v -> probar(p)));
        acciones.addView(accionBtn("Quitar", 0xFFDC2626, v -> confirmarBorrado(p)));
        card.addView(acciones);

        return card;
    }

    private Button accionBtn(String texto, int color, View.OnClickListener onClick) {
        Button b = new Button(this);
        b.setText(texto);
        b.setTextSize(11);
        b.setTextColor(Color.WHITE);
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(color));
        b.setMinWidth(0);
        b.setMinimumWidth(0);
        b.setPadding(dp(12), 0, dp(12), 0);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, dp(34));
        lp.setMarginEnd(dp(8));
        b.setLayoutParams(lp);
        b.setOnClickListener(onClick);
        return b;
    }

    private TextView chip(String text, int color) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(9);
        t.setTextColor(Color.WHITE);
        t.setPadding(dp(8), dp(3), dp(8), dp(3));
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(dp(10));
        t.setBackground(g);
        return t;
    }

    private String transporteLabel(String t) {
        if (PrinterProfile.TRANSPORT_BLUETOOTH.equals(t)) return "BT";
        if (PrinterProfile.TRANSPORT_USB.equals(t))       return "USB";
        if (PrinterProfile.TRANSPORT_IP.equals(t))        return "RED";
        if (PrinterProfile.TRANSPORT_SERIAL.equals(t))    return "SERIAL";
        if (PrinterProfile.TRANSPORT_SUNMI.equals(t))     return "SUNMI";
        return "?";
    }

    private int transporteColor(String t) {
        if (PrinterProfile.TRANSPORT_BLUETOOTH.equals(t)) return 0xFF0284C7;
        if (PrinterProfile.TRANSPORT_USB.equals(t))       return 0xFF7C3AED;
        if (PrinterProfile.TRANSPORT_IP.equals(t))        return 0xFF0891B2;
        if (PrinterProfile.TRANSPORT_SERIAL.equals(t))    return 0xFFEA580C;
        if (PrinterProfile.TRANSPORT_SUNMI.equals(t))     return 0xFF16A34A;
        return 0xFF64748B;
    }

    private String destinoLabel(PrinterProfile p) {
        if (PrinterProfile.TRANSPORT_IP.equals(p.transport)) {
            return p.host + ":" + p.port;
        }
        if (PrinterProfile.TRANSPORT_SUNMI.equals(p.transport)) {
            return "Impresora interna del equipo";
        }
        if (PrinterProfile.TRANSPORT_SERIAL.equals(p.transport)) {
            return p.address + " · " + p.baud + " baud";
        }
        if (PrinterProfile.TRANSPORT_BLUETOOTH.equals(p.transport)) {
            String modo = PrinterProfile.BT_MODE_CLASSIC.equals(p.btMode) ? "clásico"
                        : PrinterProfile.BT_MODE_BLE.equals(p.btMode) ? "BLE" : "auto";
            return p.address + " · " + modo;
        }
        return p.address;
    }

    // ------------------------------------------------------------------
    // Alta / edición
    // ------------------------------------------------------------------

    /** @param existente null = alta nueva */
    private void mostrarDialogo(final PrinterProfile existente) {
        final PrinterProfile p = existente != null ? existente : new PrinterProfile();
        final boolean esNuevo = existente == null;

        ScrollView scroll = new ScrollView(this);
        final LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(20), dp(12), dp(20), dp(8));

        // --- Datos de la cola ---
        form.addView(seccion("Cola del servidor"));

        final EditText inNombre = campoTexto("Nombre (ej. Caja 1)", p.nombre);
        form.addView(inNombre);

        final EditText inCola = campoTexto("Código de cola (ej. 301)", p.queueCode);
        inCola.setInputType(InputType.TYPE_CLASS_TEXT);
        form.addView(inCola);

        final EditText inEmpresa = campoTexto("Empresa", p.empresa);
        form.addView(inEmpresa);

        // --- Transporte ---
        form.addView(seccion("Conexión"));

        final String[] transVals = {
            PrinterProfile.TRANSPORT_BLUETOOTH, PrinterProfile.TRANSPORT_USB,
            PrinterProfile.TRANSPORT_IP, PrinterProfile.TRANSPORT_SERIAL,
            PrinterProfile.TRANSPORT_SUNMI
        };
        final String[] transLabels = {"Bluetooth", "USB", "Red (IP)", "Serial", "SUNMI interna"};
        final Spinner spnTrans = spinner(transLabels, indiceDe(transVals, p.transport));
        form.addView(etiqueta("Transporte"));
        form.addView(spnTrans);

        // Contenedor que cambia según el transporte elegido
        final LinearLayout camposTransporte = new LinearLayout(this);
        camposTransporte.setOrientation(LinearLayout.VERTICAL);
        form.addView(camposTransporte);

        // --- Opciones de impresión ---
        form.addView(seccion("Impresión"));

        final String[] protoVals = {"auto", "escpos", "cpcl", "zpl"};
        final Spinner spnProto = spinner(new String[]{"Auto", "ESC/POS", "CPCL", "ZPL"},
                                         indiceDe(protoVals, p.protocol));
        form.addView(etiqueta("Protocolo (lenguaje de la impresora)"));
        form.addView(spnProto);

        final String[] modeVals = {
            PrinterProfile.PRINT_MODE_AUTO, PrinterProfile.PRINT_MODE_RAW,
            PrinterProfile.PRINT_MODE_POS
        };
        final Spinner spnMode = spinner(new String[]{"Auto", "RAW (bytes tal cual)", "Comandos POS"},
                                        indiceDe(modeVals, p.printMode));
        form.addView(etiqueta("Modo de contenido"));
        form.addView(spnMode);

        final String[] fontVals = {"A", "B"};
        final Spinner spnFont = spinner(new String[]{"Fuente A (normal)", "Fuente B (condensada)"},
                                        indiceDe(fontVals, p.escposFont));
        form.addView(etiqueta("Fuente ESC/POS"));
        form.addView(spnFont);

        final CheckBox chkCortar = new CheckBox(this);
        chkCortar.setText("Cortar papel");
        chkCortar.setChecked(p.cutPaper);
        form.addView(chkCortar);

        final CheckBox chkCajon = new CheckBox(this);
        chkCajon.setText("Abrir cajón");
        chkCajon.setChecked(p.openDrawer);
        form.addView(chkCajon);

        final CheckBox chkTermica = new CheckBox(this);
        chkTermica.setText("Impresora térmica");
        chkTermica.setChecked(p.isThermal);
        form.addView(chkTermica);

        // Campos que dependen del transporte: se reconstruyen al cambiar el spinner
        final EditText[] refHost = new EditText[1];
        final EditText[] refPort = new EditText[1];
        final Spinner[] refDispositivo = new Spinner[1];
        final Spinner[] refBtMode = new Spinner[1];
        final Spinner[] refBaud = new Spinner[1];
        final List<String> dispositivoAddrs = new ArrayList<String>();

        spnTrans.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                String t = transVals[position];
                camposTransporte.removeAllViews();
                refHost[0] = null; refPort[0] = null;
                refDispositivo[0] = null; refBtMode[0] = null; refBaud[0] = null;
                dispositivoAddrs.clear();

                if (PrinterProfile.TRANSPORT_IP.equals(t)) {
                    EditText host = campoTexto("Dirección IP (ej. 192.168.1.50)", p.host);
                    EditText port = campoTexto("Puerto", String.valueOf(
                        p.port > 0 ? p.port : PrinterProfile.DEFAULT_IP_PORT));
                    port.setInputType(InputType.TYPE_CLASS_NUMBER);
                    camposTransporte.addView(etiqueta("Dirección de red"));
                    camposTransporte.addView(host);
                    camposTransporte.addView(port);
                    refHost[0] = host;
                    refPort[0] = port;

                    Button probar = new Button(PrinterProfilesActivity.this);
                    probar.setText("Probar conexión");
                    probar.setTextSize(12);
                    probar.setOnClickListener(v -> probarConexionIp(
                        host.getText().toString(), port.getText().toString()));
                    camposTransporte.addView(probar);

                } else if (PrinterProfile.TRANSPORT_SUNMI.equals(t)) {
                    TextView info = new TextView(PrinterProfilesActivity.this);
                    info.setText("Usa la impresora integrada del equipo. No requiere configuración.");
                    info.setTextSize(12);
                    info.setTextColor(0xFF64748B);
                    info.setPadding(0, dp(8), 0, dp(4));
                    camposTransporte.addView(info);

                } else {
                    // bluetooth / usb / serial: elegir de los dispositivos detectados
                    List<String> labels = new ArrayList<String>();
                    listarDispositivos(t, labels, dispositivoAddrs);

                    camposTransporte.addView(etiqueta("Dispositivo"));
                    if (labels.isEmpty()) {
                        TextView vacio = new TextView(PrinterProfilesActivity.this);
                        vacio.setText(PrinterProfile.TRANSPORT_BLUETOOTH.equals(t)
                            ? "No hay dispositivos Bluetooth emparejados. Emparejalo primero desde Ajustes de Android."
                            : "No hay dispositivos detectados. Conectá la impresora y volvé a entrar.");
                        vacio.setTextSize(12);
                        vacio.setTextColor(0xFFDC2626);
                        vacio.setPadding(0, dp(6), 0, dp(6));
                        camposTransporte.addView(vacio);
                    } else {
                        String[] arr = labels.toArray(new String[0]);
                        Spinner spn = spinner(arr, Math.max(0, dispositivoAddrs.indexOf(p.address)));
                        camposTransporte.addView(spn);
                        refDispositivo[0] = spn;
                    }

                    if (PrinterProfile.TRANSPORT_BLUETOOTH.equals(t)) {
                        String[] btVals = {PrinterProfile.BT_MODE_AUTO,
                                           PrinterProfile.BT_MODE_CLASSIC,
                                           PrinterProfile.BT_MODE_BLE};
                        Spinner spnBt = spinner(
                            new String[]{"Auto (recomendado)", "Clásico (SPP)", "BLE"},
                            indiceDe(btVals, p.btMode));
                        camposTransporte.addView(etiqueta("Modo Bluetooth"));
                        camposTransporte.addView(spnBt);
                        refBtMode[0] = spnBt;
                    }

                    if (PrinterProfile.TRANSPORT_SERIAL.equals(t)) {
                        final int[] bauds = {9600, 19200, 38400, 57600, 115200};
                        int idx = 0;
                        for (int i = 0; i < bauds.length; i++) if (bauds[i] == p.baud) idx = i;
                        Spinner spnB = spinner(
                            new String[]{"9600", "19200", "38400", "57600", "115200"}, idx);
                        camposTransporte.addView(etiqueta("Baudios"));
                        camposTransporte.addView(spnB);
                        refBaud[0] = spnB;
                    }
                }
            }

            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });

        // El Spinner fija su selección (arriba) ANTES de tener listener, y el callback
        // inicial de onItemSelected NO dispara de forma confiable al EDITAR: los campos
        // del transporte no se armaban, refHost/refPort quedaban en null y al guardar
        // saltaba "Falta la dirección IP" sin dejar ver ni cambiar la IP. Forzamos acá la
        // construcción de los campos del transporte actual, de forma síncrona.
        AdapterView.OnItemSelectedListener lTrans = spnTrans.getOnItemSelectedListener();
        if (lTrans != null) {
            lTrans.onItemSelected(spnTrans, null, spnTrans.getSelectedItemPosition(), 0);
        }

        scroll.addView(form);

        AlertDialog dlg = new AlertDialog.Builder(this)
            .setTitle(esNuevo ? "Nueva impresora" : "Editar impresora")
            .setView(scroll)
            .setPositiveButton("Guardar", null)   // se cablea abajo para poder validar
            .setNegativeButton("Cancelar", null)
            .create();

        dlg.setOnShowListener(d -> dlg.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            p.nombre  = inNombre.getText().toString().trim();
            p.queueCode = inCola.getText().toString().trim();
            p.empresa = inEmpresa.getText().toString().trim();
            p.transport = transVals[spnTrans.getSelectedItemPosition()];
            p.protocol  = protoVals[spnProto.getSelectedItemPosition()];
            p.printMode = modeVals[spnMode.getSelectedItemPosition()];
            p.escposFont = fontVals[spnFont.getSelectedItemPosition()];
            p.cutPaper   = chkCortar.isChecked();
            p.openDrawer = chkCajon.isChecked();
            p.isThermal  = chkTermica.isChecked();

            if (PrinterProfile.TRANSPORT_IP.equals(p.transport)) {
                // Solo sobrescribir host/puerto si el campo existe. Si por timing no se
                // construyó, se conserva la IP ya guardada en vez de borrarla.
                if (refHost[0] != null) {
                    p.host = refHost[0].getText().toString().trim();
                    p.port = parseIntSeguro(refPort[0] != null ? refPort[0].getText().toString() : "",
                                            PrinterProfile.DEFAULT_IP_PORT);
                }
                p.address = "";
            } else if (PrinterProfile.TRANSPORT_SUNMI.equals(p.transport)) {
                p.address = "";
            } else {
                if (refDispositivo[0] != null) {
                    int idx = refDispositivo[0].getSelectedItemPosition();
                    if (idx >= 0 && idx < dispositivoAddrs.size()) {
                        p.address = dispositivoAddrs.get(idx);
                    }
                }
                if (refBtMode[0] != null) {
                    String[] btVals = {PrinterProfile.BT_MODE_AUTO,
                                       PrinterProfile.BT_MODE_CLASSIC,
                                       PrinterProfile.BT_MODE_BLE};
                    p.btMode = btVals[refBtMode[0].getSelectedItemPosition()];
                }
                if (refBaud[0] != null) {
                    int[] bauds = {9600, 19200, 38400, 57600, 115200};
                    p.baud = bauds[refBaud[0].getSelectedItemPosition()];
                }
            }

            String error = validar(p);
            if (error != null) {
                Toast.makeText(PrinterProfilesActivity.this, error, Toast.LENGTH_LONG).show();
                return;
            }

            store.save(p);
            notificarCambioPerfiles();
            redibujar();
            dlg.dismiss();
            Toast.makeText(PrinterProfilesActivity.this,
                "Guardada: " + p.getDisplayName() + " (cola " + p.queueCode + ")",
                Toast.LENGTH_SHORT).show();
        }));

        dlg.show();
    }

    /**
     * Valida antes de guardar. La cola es obligatoria: sin ella el perfil no puede
     * recibir trabajos, y un perfil mudo es peor que no tenerlo (parece configurado).
     */
    private String validar(PrinterProfile p) {
        if (p.queueCode == null || p.queueCode.trim().isEmpty()) {
            return "Falta el código de cola.";
        }
        if (PrinterProfile.TRANSPORT_IP.equals(p.transport)) {
            if (p.host == null || p.host.trim().isEmpty()) return "Falta la dirección IP.";
            if (p.port <= 0 || p.port > 65535) return "Puerto inválido.";
        } else if (!PrinterProfile.TRANSPORT_SUNMI.equals(p.transport)) {
            if (p.address == null || p.address.trim().isEmpty()) {
                return "Elegí el dispositivo.";
            }
        }
        // Dos perfiles con la misma cola y empresa se pisarían: el servidor manda el
        // trabajo una sola vez y ganaría cualquiera de los dos.
        List<PrinterProfile> otros = store.getAll();
        String q = PrinterProfile.normalizeQueue(p.queueCode);
        String emp = p.empresa != null ? p.empresa.trim().toLowerCase() : "";
        for (int i = 0; i < otros.size(); i++) {
            PrinterProfile o = otros.get(i);
            if (o.id.equals(p.id)) continue;
            String oEmp = o.empresa != null ? o.empresa : "";
            if (q.equals(o.queueCode) && emp.equals(oEmp)) {
                return "Ya hay otra impresora con la cola " + q
                     + (emp.isEmpty() ? "" : " de " + emp) + ".";
            }
        }
        return null;
    }

    /**
     * Avisa al cliente de cola que cambiaron los perfiles, para que reenvíe el
     * register. Sin esto, una impresora recién agregada no recibiría trabajos hasta
     * la próxima reconexión, que puede tardar horas.
     */
    private void notificarCambioPerfiles() {
        PrintQueueClient qc = PrintService.getStaticQueueClient();
        if (qc != null) qc.reregistrar();
    }

    private void confirmarBorrado(final PrinterProfile p) {
        new AlertDialog.Builder(this)
            .setTitle("Quitar impresora")
            .setMessage("¿Quitar \"" + p.getDisplayName() + "\"?\n\n"
                      + "Dejará de recibir los trabajos de la cola " + p.queueCode + ".")
            .setPositiveButton("Quitar", (d, w) -> {
                store.delete(p.id);
                notificarCambioPerfiles();
                redibujar();
            })
            .setNegativeButton("Cancelar", null)
            .show();
    }

    // ------------------------------------------------------------------
    // Pruebas
    // ------------------------------------------------------------------

    private void probar(final PrinterProfile p) {
        final PrinterManager pm = PrintService.getStaticPrinterManager();
        if (pm == null) {
            Toast.makeText(this, "El servicio no está iniciado", Toast.LENGTH_SHORT).show();
            return;
        }
        final String ticket =
              "================================\n"
            + "   FACTUPOS PRINT v" + BuildConfig.VERSION_NAME + "\n"
            + "       Prueba de impresion\n"
            + "================================\n"
            + "Impresora: " + p.getDisplayName() + "\n"
            + "Cola: " + p.queueCode + "\n"
            + "Empresa: " + (p.empresa == null || p.empresa.isEmpty() ? "-" : p.empresa) + "\n"
            + "Destino: " + destinoLabel(p) + "\n"
            + "--------------------------------\n"
            + "Si puede leer esto, la impresora\n"
            + "esta funcionando correctamente.\n"
            + "================================\n\n\n";

        Toast.makeText(this, "Enviando a " + p.getDisplayName() + "...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            final boolean ok = pm.printText(p, ticket);
            runOnUiThread(() -> Toast.makeText(this,
                ok ? "Enviado a " + p.getDisplayName()
                   : "Falló: " + detalleError(pm, p),
                Toast.LENGTH_LONG).show());
        }).start();
    }

    private String detalleError(PrinterManager pm, PrinterProfile p) {
        try {
            if (PrinterProfile.TRANSPORT_IP.equals(p.transport)) {
                return pm.getNetPrinter().getLastError();
            }
            if (PrinterProfile.TRANSPORT_USB.equals(p.transport)) {
                return pm.getUsbPrinter().getLastError();
            }
            if (PrinterProfile.TRANSPORT_SERIAL.equals(p.transport)) {
                return pm.getSerialPrinter().getLastError();
            }
            if (PrinterProfile.TRANSPORT_BLUETOOTH.equals(p.transport)) {
                String spp = pm.getBluetoothPrinter().getLastError();
                String ble = pm.getBlePrinter().getLastError();
                return "SPP:" + (spp.isEmpty() ? "?" : spp)
                     + (ble.isEmpty() ? "" : " | BLE:" + ble);
            }
        } catch (Exception ignored) {}
        return "desconocido";
    }

    private void probarConexionIp(final String host, final String portTxt) {
        final int port = parseIntSeguro(portTxt, PrinterProfile.DEFAULT_IP_PORT);
        Toast.makeText(this, "Probando " + host + ":" + port + "...", Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            final NetPrinter net = new NetPrinter();
            final boolean ok = net.testConnection(host, port);
            runOnUiThread(() -> Toast.makeText(this,
                ok ? "Responde en " + host + ":" + port
                   : "Sin respuesta: " + net.getLastError(),
                Toast.LENGTH_LONG).show());
        }).start();
    }

    // ------------------------------------------------------------------
    // Descubrimiento de dispositivos (para el diálogo)
    // ------------------------------------------------------------------

    private void listarDispositivos(String transporte, List<String> labels, List<String> addrs) {
        PrinterManager pm = PrintService.getStaticPrinterManager();

        if (PrinterProfile.TRANSPORT_BLUETOOTH.equals(transporte)) {
            try {
                BluetoothAdapter adapter = BluetoothAdapter.getDefaultAdapter();
                if (adapter != null && adapter.isEnabled()) {
                    Set<BluetoothDevice> paired = adapter.getBondedDevices();
                    if (paired != null) {
                        for (BluetoothDevice d : paired) {
                            String n = d.getName() != null ? d.getName() : "Desconocido";
                            labels.add(n + "  ·  " + d.getAddress());
                            addrs.add(d.getAddress());
                        }
                    }
                }
            } catch (SecurityException e) {
                labels.add("Sin permiso Bluetooth");
                addrs.add("");
            }
            return;
        }

        if (PrinterProfile.TRANSPORT_USB.equals(transporte)) {
            UsbPrinter usb = pm != null ? pm.getUsbPrinter() : new UsbPrinter(this);
            agregarDesdeJson(usb.getDevices(), labels, addrs, "USB");
            return;
        }

        if (PrinterProfile.TRANSPORT_SERIAL.equals(transporte)) {
            SerialPrinter ser = pm != null ? pm.getSerialPrinter() : new SerialPrinter(this);
            agregarDesdeJson(ser.getDevices(), labels, addrs, "Serial");
        }
    }

    private void agregarDesdeJson(JSONArray arr, List<String> labels, List<String> addrs,
                                  String prefijo) {
        if (arr == null) return;
        for (int i = 0; i < arr.length(); i++) {
            JSONObject o = arr.optJSONObject(i);
            if (o == null) continue;
            String addr = o.optString("address", "");
            if (addr.isEmpty()) continue;
            String nombre = o.optString("name", prefijo + " " + addr);
            String status = o.optString("status", "");
            labels.add(nombre + "  ·  " + addr
                     + ("need_permission".equals(status) ? "  (falta permiso)" : ""));
            addrs.add(addr);
        }
    }

    // ------------------------------------------------------------------
    // Helpers de formulario
    // ------------------------------------------------------------------

    private TextView seccion(String texto) {
        TextView t = new TextView(this);
        t.setText(texto.toUpperCase());
        t.setTextSize(11);
        t.setTextColor(0xFF2563EB);
        t.setPadding(0, dp(16), 0, dp(2));
        return t;
    }

    private TextView etiqueta(String texto) {
        TextView t = new TextView(this);
        t.setText(texto);
        t.setTextSize(11);
        t.setTextColor(0xFF64748B);
        t.setPadding(0, dp(8), 0, 0);
        return t;
    }

    private EditText campoTexto(String hint, String valor) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setText(valor != null ? valor : "");
        e.setTextSize(14);
        e.setSingleLine(true);
        return e;
    }

    private Spinner spinner(String[] labels, int seleccion) {
        Spinner s = new Spinner(this);
        ArrayAdapter<String> a = new ArrayAdapter<String>(this,
            android.R.layout.simple_spinner_item, labels);
        a.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        s.setAdapter(a);
        if (seleccion >= 0 && seleccion < labels.length) s.setSelection(seleccion, false);
        return s;
    }

    private int indiceDe(String[] arr, String valor) {
        if (valor == null) return 0;
        for (int i = 0; i < arr.length; i++) {
            if (arr[i].equals(valor)) return i;
        }
        return 0;
    }

    private int parseIntSeguro(String s, int porDefecto) {
        try {
            int v = Integer.parseInt(s.trim());
            return v > 0 ? v : porDefecto;
        } catch (Exception e) {
            return porDefecto;
        }
    }
}
