package com.factupos.printbridge;

import android.Manifest;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

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
    private LinearLayout listContainer;   // cuerpo de la tabla
    private TextView txtVacio;
    private TextView txtEstadoCola;       // línea de estado con punto
    private TextView txtContadores;       // Impresos/Errores + url
    private TextView txtLog;              // terminal del log
    private ScrollView scrollLog;
    private TextView txtIdVersion;        // "ID · vX.X" del header

    private PrinterProfile seleccionado;  // fila seleccionada (Editar/Quitar/Probar actúan sobre esta)
    private View filaSelView;

    private final Handler poll = new Handler(Looper.getMainLooper());

    private static final int NAVY   = 0xFF1E3A5F;
    private static final int NAVY2  = 0xFF2B4B7E;
    private static final int VERDE  = 0xFF059669;
    private static final int ROJO   = 0xFFDC2626;

    private int dp(float v) {
        return (int) (v * getResources().getDisplayMetrics().density + 0.5f);
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        store = new PrinterProfileStore(this);

        // Esta pantalla ahora es el inicio de la app: arranca el servicio y pide permisos
        // (antes lo hacía MainActivity, que dejó de ser el launcher).
        iniciarServicio();
        solicitarPermisos();
        solicitarWhitelistBateria();

        setContentView(construirPantalla());
    }

    /** Layout completo, a todo el ancho, espejo del cliente de escritorio. */
    private View construirPantalla() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xFFEEF2F7);
        LinearLayout.LayoutParams full = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.MATCH_PARENT);
        root.setLayoutParams(full);

        // ───── Header navy (todo el ancho) ─────
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setBackgroundColor(NAVY);
        header.setPadding(dp(16), dp(14), dp(16), dp(14));

        TextView titulo = new TextView(this);
        titulo.setText("FactuPOS Print");
        titulo.setTextColor(Color.WHITE);
        titulo.setTextSize(20);
        titulo.setTypeface(Typeface.DEFAULT_BOLD);
        titulo.setLayoutParams(new LinearLayout.LayoutParams(0,
            LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        header.addView(titulo);

        txtIdVersion = new TextView(this);
        txtIdVersion.setTextColor(0xFFB8C7DE);
        txtIdVersion.setTextSize(12);
        txtIdVersion.setGravity(Gravity.END);
        header.addView(txtIdVersion);

        Button btnGear = new Button(this);
        btnGear.setText("⚙");
        btnGear.setTextSize(16);
        btnGear.setTextColor(Color.WHITE);
        btnGear.setBackgroundTintList(android.content.res.ColorStateList.valueOf(NAVY2));
        btnGear.setMinWidth(0); btnGear.setMinimumWidth(0);
        LinearLayout.LayoutParams glp = new LinearLayout.LayoutParams(dp(48), dp(42));
        glp.setMarginStart(dp(10));
        btnGear.setLayoutParams(glp);
        btnGear.setOnClickListener(v -> mostrarDialogoServidor());
        header.addView(btnGear);

        root.addView(header);

        // ───── Línea de estado (● Conectado — ws://…) ─────
        txtEstadoCola = new TextView(this);
        txtEstadoCola.setTextSize(13);
        txtEstadoCola.setPadding(dp(16), dp(10), dp(16), dp(6));
        root.addView(txtEstadoCola);

        // ───── Título "Impresoras Registradas" ─────
        TextView tReg = new TextView(this);
        tReg.setText("Impresoras Registradas");
        tReg.setTextColor(NAVY);
        tReg.setTextSize(15);
        tReg.setTypeface(Typeface.DEFAULT_BOLD);
        tReg.setPadding(dp(16), dp(6), dp(16), dp(6));
        root.addView(tReg);

        // ───── Tabla (encabezado + cuerpo) dentro de un scroll vertical con weight ─────
        LinearLayout tabla = new LinearLayout(this);
        tabla.setOrientation(LinearLayout.VERTICAL);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f);
        tlp.setMargins(dp(12), 0, dp(12), 0);
        tabla.setLayoutParams(tlp);
        tabla.setBackgroundColor(Color.WHITE);

        tabla.addView(filaEncabezado());

        txtVacio = new TextView(this);
        txtVacio.setText("Sin impresoras. Tocá «+ Agregar» para configurar una.");
        txtVacio.setTextSize(13);
        txtVacio.setTextColor(0xFF64748B);
        txtVacio.setPadding(dp(14), dp(20), dp(14), dp(20));
        tabla.addView(txtVacio);

        ScrollView bodyScroll = new ScrollView(this);
        bodyScroll.setLayoutParams(new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        listContainer = new LinearLayout(this);
        listContainer.setOrientation(LinearLayout.VERTICAL);
        bodyScroll.addView(listContainer);
        tabla.addView(bodyScroll);

        root.addView(tabla);

        // ───── Botonera (todo el ancho, repartida) ─────
        LinearLayout botonera = new LinearLayout(this);
        botonera.setOrientation(LinearLayout.HORIZONTAL);
        botonera.setPadding(dp(10), dp(8), dp(10), dp(4));
        botonera.addView(botonBarra("+ Agregar", 0xFF2563EB, v -> mostrarDialogo(null)));
        botonera.addView(botonBarra("Editar", NAVY2, v -> conSeleccion(this::mostrarDialogo)));
        botonera.addView(botonBarra("– Quitar", ROJO, v -> conSeleccion(this::confirmarBorrado)));
        botonera.addView(botonBarra("Probar", VERDE, v -> conSeleccion(this::probar)));
        botonera.addView(botonBarra("Limpiar cola", 0xFF64748B, v -> limpiarCola()));
        root.addView(botonera);

        // ───── Contadores ─────
        txtContadores = new TextView(this);
        txtContadores.setTextSize(12);
        txtContadores.setPadding(dp(16), dp(2), dp(16), dp(6));
        root.addView(txtContadores);

        // ───── Log ─────
        TextView tLog = new TextView(this);
        tLog.setText("Log");
        tLog.setTextColor(NAVY);
        tLog.setTypeface(Typeface.DEFAULT_BOLD);
        tLog.setTextSize(13);
        tLog.setPadding(dp(16), dp(2), dp(16), dp(4));
        root.addView(tLog);

        scrollLog = new ScrollView(this);
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(150));
        slp.setMargins(dp(12), 0, dp(12), dp(6));
        scrollLog.setLayoutParams(slp);
        scrollLog.setBackgroundColor(0xFF0F172A);
        txtLog = new TextView(this);
        txtLog.setTextColor(0xFFA3E635);
        txtLog.setTextSize(10);
        txtLog.setTypeface(Typeface.MONOSPACE);
        txtLog.setTextIsSelectable(true);
        txtLog.setPadding(dp(10), dp(8), dp(10), dp(8));
        scrollLog.addView(txtLog);
        root.addView(scrollLog);

        // ───── Botones de abajo ─────
        LinearLayout abajo = new LinearLayout(this);
        abajo.setOrientation(LinearLayout.HORIZONTAL);
        abajo.setPadding(dp(10), dp(2), dp(10), dp(10));
        abajo.addView(botonBarra("Buscar actualización", NAVY2, v -> buscarActualizacion()));
        abajo.addView(botonBarra("Copiar Log", 0xFF64748B, v -> copiarLog()));
        root.addView(abajo);

        // El root ya es scrolleable por su tabla; envolver en ScrollView rompería el weight,
        // así que se deja fijo y la tabla es la que scrollea internamente.
        return root;
    }

    /** Fila de encabezado de la tabla (5 columnas, mismos títulos que el escritorio). */
    private View filaEncabezado() {
        LinearLayout fila = new LinearLayout(this);
        fila.setOrientation(LinearLayout.HORIZONTAL);
        fila.setBackgroundColor(NAVY);
        fila.addView(celda("Cola", 1f, true, Color.WHITE));
        fila.addView(celda("Empresa BD", 1.6f, true, Color.WHITE));
        fila.addView(celda("Impresora", 1.8f, true, Color.WHITE));
        fila.addView(celda("Descripción", 1.6f, true, Color.WHITE));
        fila.addView(celda("Modo/Opciones", 2.2f, true, Color.WHITE));
        return fila;
    }

    private TextView celda(String texto, float peso, boolean negrita, int color) {
        TextView t = new TextView(this);
        t.setText(texto);
        t.setTextSize(12);
        t.setTextColor(color);
        if (negrita) t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setPadding(dp(8), dp(9), dp(8), dp(9));
        t.setLayoutParams(new LinearLayout.LayoutParams(0,
            LinearLayout.LayoutParams.WRAP_CONTENT, peso));
        return t;
    }

    private Button botonBarra(String texto, int color, View.OnClickListener onClick) {
        Button b = new Button(this);
        b.setText(texto);
        b.setTextSize(11);
        b.setAllCaps(false);
        b.setTextColor(Color.WHITE);
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(color));
        b.setMinWidth(0); b.setMinimumWidth(0);
        b.setPadding(dp(4), 0, dp(4), 0);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(46), 1f);
        lp.setMargins(dp(3), 0, dp(3), 0);
        b.setLayoutParams(lp);
        b.setOnClickListener(onClick);
        return b;
    }

    /** Acción sobre un perfil (interfaz propia: java.util.function.Consumer es API 24+, minSdk 21). */
    private interface AccionPerfil { void run(PrinterProfile p); }

    /** Ejecuta la acción sobre la fila seleccionada, o avisa si no hay ninguna. */
    private void conSeleccion(AccionPerfil accion) {
        if (seleccionado == null) {
            Toast.makeText(this, "Seleccioná una impresora de la lista", Toast.LENGTH_SHORT).show();
            return;
        }
        accion.run(seleccionado);
    }

    private void limpiarCola() {
        PrintQueueClient qc = PrintService.getStaticQueueClient();
        if (qc == null) { Toast.makeText(this, "Servicio no iniciado", Toast.LENGTH_SHORT).show(); return; }
        int n = qc.getQueue().clear();
        Toast.makeText(this, "Cola local vaciada (" + n + ")", Toast.LENGTH_SHORT).show();
    }

    @Override
    protected void onResume() {
        super.onResume();
        redibujar();
        poll.removeCallbacks(pollRunnable);
        poll.post(pollRunnable);
    }

    @Override
    protected void onPause() {
        super.onPause();
        poll.removeCallbacks(pollRunnable);
    }

    /** Refresca estado, contadores y log cada segundo (como el cliente de escritorio). */
    private final Runnable pollRunnable = new Runnable() {
        @Override public void run() {
            actualizarEstadoCola();
            actualizarContadoresYLog();
            poll.postDelayed(this, 1000);
        }
    };

    // ------------------------------------------------------------------
    // Listado
    // ------------------------------------------------------------------

    private void redibujar() {
        if (listContainer == null) return;
        listContainer.removeAllViews();
        List<PrinterProfile> perfiles = store.getAll();
        txtVacio.setVisibility(perfiles.isEmpty() ? View.VISIBLE : View.GONE);

        // Si el perfil seleccionado ya no existe, limpiar la selección.
        if (seleccionado != null) {
            boolean existe = false;
            for (PrinterProfile p : perfiles) if (p.id.equals(seleccionado.id)) { existe = true; break; }
            if (!existe) { seleccionado = null; filaSelView = null; }
        }

        for (int i = 0; i < perfiles.size(); i++) {
            listContainer.addView(construirFila(perfiles.get(i), i));
        }
        actualizarEstadoCola();
        actualizarContadoresYLog();
    }

    /** Header: ID de la tablet + versión. */
    private void actualizarIdVersion() {
        if (txtIdVersion == null) return;
        PrintQueueClient qc = PrintService.getStaticQueueClient();
        String id = qc != null ? qc.getClientId() : "";
        txtIdVersion.setText("ID: " + id + "   v" + BuildConfig.VERSION_NAME);
    }

    /** Línea de estado con punto de color (● Conectado — ws://…). */
    private void actualizarEstadoCola() {
        if (txtEstadoCola == null) return;
        actualizarIdVersion();
        PrintQueueClient qc = PrintService.getStaticQueueClient();
        if (qc == null) {
            txtEstadoCola.setText("○  Servicio no iniciado");
            txtEstadoCola.setTextColor(0xFF94A3B8);
            return;
        }
        if (!qc.isEnabled()) {
            txtEstadoCola.setText("○  Desactivado — tocá ⚙ y activá «Recibir trabajos por WebSocket»");
            txtEstadoCola.setTextColor(0xFF94A3B8);
            return;
        }
        boolean conectado = qc.isConnected();
        int pendientes = qc.getQueue().size();
        String txt = (conectado ? "●  Conectado — " : "●  " + qc.getEstado() + " — ") + qc.getServerUrl()
                   + (pendientes > 0 ? "   ·   " + pendientes + " en cola" : "");
        txtEstadoCola.setText(txt);
        txtEstadoCola.setTextColor(conectado ? VERDE : ROJO);
    }

    /** Contadores Impresos/Errores + URL, y el log en vivo. */
    private void actualizarContadoresYLog() {
        PrintQueueClient qc = PrintService.getStaticQueueClient();
        if (txtContadores != null) {
            if (qc == null) {
                txtContadores.setText("Impresos: 0   ·   Errores: 0");
            } else {
                txtContadores.setText("Impresos: " + qc.getImpresos()
                    + "   ·   Errores: " + qc.getErrores()
                    + "        " + qc.getServerUrl());
            }
        }
        if (txtLog != null && qc != null) {
            String log = qc.getLogText();
            if (!log.equals(txtLog.getText().toString())) {
                txtLog.setText(log);
                if (scrollLog != null) scrollLog.post(() -> scrollLog.fullScroll(View.FOCUS_DOWN));
            }
        }
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

    /** Fila de la tabla (5 columnas). Tap = seleccionar; Editar/Quitar/Probar actúan sobre ella. */
    private View construirFila(final PrinterProfile p, int index) {
        boolean sel = seleccionado != null && seleccionado.id.equals(p.id);
        int bg = sel ? NAVY : (index % 2 == 0 ? Color.WHITE : 0xFFF3F6FB);
        int fg = sel ? Color.WHITE : 0xFF1E293B;
        int fg2 = sel ? 0xFFD8E2F0 : 0xFF64748B;
        boolean sinCola = p.queueCode == null || p.queueCode.isEmpty();

        LinearLayout fila = new LinearLayout(this);
        fila.setOrientation(LinearLayout.HORIZONTAL);
        fila.setBackgroundColor(bg);

        fila.addView(celda(sinCola ? "⚠" : p.queueCode, 1f, false, sinCola && !sel ? ROJO : fg));
        fila.addView(celda(vacioSi(p.empresa), 1.6f, false, fg));
        fila.addView(celda(impresoraLabel(p), 1.8f, false, fg));
        fila.addView(celda(vacioSi(p.nombre), 1.6f, false, fg));
        fila.addView(celda(modoOpcionesLabel(p), 2.2f, false, fg2));

        fila.setOnClickListener(v -> {
            seleccionado = p;
            redibujar();
        });
        if (sel) filaSelView = fila;
        return fila;
    }

    private String vacioSi(String s) { return (s == null || s.isEmpty()) ? "—" : s; }

    /** Columna "Impresora": transporte + destino corto (equivale al nombre de impresora del PC). */
    private String impresoraLabel(PrinterProfile p) {
        if (PrinterProfile.TRANSPORT_IP.equals(p.transport))    return "RED " + p.host + ":" + p.port;
        if (PrinterProfile.TRANSPORT_SUNMI.equals(p.transport)) return "SUNMI interna";
        if (PrinterProfile.TRANSPORT_SERIAL.equals(p.transport))return "SERIAL " + p.address;
        if (PrinterProfile.TRANSPORT_USB.equals(p.transport))   return "USB " + p.address;
        if (PrinterProfile.TRANSPORT_BLUETOOTH.equals(p.transport)) return "BT " + p.address;
        return p.address;
    }

    /** Columna "Modo/Opciones": modo + fuente + cajón/corte (como "RAW, Letra B, Cajón"). */
    private String modoOpcionesLabel(PrinterProfile p) {
        StringBuilder sb = new StringBuilder();
        String modo = PrinterProfile.PRINT_MODE_RAW.equals(p.printMode) ? "RAW"
                    : PrinterProfile.PRINT_MODE_POS.equals(p.printMode) ? "POS" : "Auto";
        sb.append(modo);
        sb.append(", Letra ").append("B".equalsIgnoreCase(p.escposFont) ? "B" : "A");
        if (p.cutPaper)   sb.append(", Corte");
        if (p.openDrawer) sb.append(", Cajón");
        return sb.toString();
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

    // ------------------------------------------------------------------
    // Arranque de servicio y permisos (antes vivían en MainActivity, que dejó de
    // ser el launcher). Sin esto el servicio de cola no correría al abrir la app.
    // ------------------------------------------------------------------

    private void iniciarServicio() {
        Intent intent = new Intent(this, PrintService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
    }

    private void solicitarPermisos() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.POST_NOTIFICATIONS}, 101);
            }
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            String[] bt = {Manifest.permission.BLUETOOTH_CONNECT, Manifest.permission.BLUETOOTH_SCAN};
            boolean necesita = false;
            for (String p : bt) {
                if (ContextCompat.checkSelfPermission(this, p) != PackageManager.PERMISSION_GRANTED) {
                    necesita = true; break;
                }
            }
            if (necesita) ActivityCompat.requestPermissions(this, bt, 100);
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, 102);
        }
    }

    private void solicitarWhitelistBateria() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return;
        PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (pm == null) return;
        String pkg = getPackageName();
        if (pm.isIgnoringBatteryOptimizations(pkg)) return;
        try {
            Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
            intent.setData(Uri.parse("package:" + pkg));
            startActivity(intent);
        } catch (Exception ignored) {}
    }

    private void copiarLog() {
        PrintQueueClient qc = PrintService.getStaticQueueClient();
        String log = qc != null ? qc.getLogText() : "";
        ClipboardManager cb = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        if (cb != null) {
            cb.setPrimaryClip(ClipData.newPlainText("FactuPOS Print log", log));
            Toast.makeText(this, "Log copiado", Toast.LENGTH_SHORT).show();
        }
    }

    private void buscarActualizacion() {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(
                "https://soportereal.com/software/index.php?d=factupos-app%2Fandroid")));
        } catch (Exception e) {
            Toast.makeText(this, "No se pudo abrir la página de descargas", Toast.LENGTH_SHORT).show();
        }
    }
}
