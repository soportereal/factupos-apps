package com.factupos.printbridge;

import android.Manifest;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.content.BroadcastReceiver;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.widget.ScrollView;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Set;

/**
 * FactuPOS Print Bridge - MainActivity
 *
 * Muestra el estado del servicio HTTP, la impresora activa,
 * y permite seleccionar entre SUNMI interna y impresoras BT pareadas.
 */
public class MainActivity extends AppCompatActivity {

    private static final String TAG = "PrintBridge";
    private static final int NOTIFICATION_PERMISSION_CODE = 100;
    private static final int BLUETOOTH_PERMISSION_CODE = 101;

    private TextView txtEstado;
    private TextView txtImpresora;
    private TextView txtPuerto;
    private Button btnIniciar;
    private Button btnDetener;
    private Button btnPrueba;
    private Button btnLimpiarLog;
    private Button btnRefrescar;
    private Button btnColas;
    private TextView txtColasResumen;
    private RadioGroup radioGroupPrinters;
    private TextView txtPrinterLabel;
    private TextView txtVersion;
    private TextView txtPrintLog;
    private ScrollView scrollLog;
    // Refresca la lista de impresoras cuando el usuario concede/rechaza permiso USB
    private final BroadcastReceiver usbPermissionReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context ctx, Intent intent) {
            if (UsbPrinter.ACTION_USB_PERMISSION.equals(intent.getAction())) {
                runOnUiThread(() -> cargarImpresoras());
            }
        }
    };

    /** dp -> px según densidad de pantalla. */
    private int dp(float v) {
        return (int) (v * getResources().getDisplayMetrics().density + 0.5f);
    }

    private final Handler logHandler = new Handler(Looper.getMainLooper());
    private final Runnable logRefreshRunnable = new Runnable() {
        @Override
        public void run() {
            if (txtPrintLog != null) {
                String log = PrintService.logRender();
                if (!log.equals(txtPrintLog.getText().toString())) {
                    txtPrintLog.setText(log);
                    if (scrollLog != null) {
                        scrollLog.post(() -> scrollLog.fullScroll(View.FOCUS_DOWN));
                    }
                }
            }
            logHandler.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        txtEstado = findViewById(R.id.txtEstado);
        txtImpresora = findViewById(R.id.txtImpresora);
        txtPuerto = findViewById(R.id.txtPuerto);
        btnIniciar = findViewById(R.id.btnIniciar);
        btnDetener = findViewById(R.id.btnDetener);
        btnPrueba = findViewById(R.id.btnPrueba);
        radioGroupPrinters = findViewById(R.id.radioGroupPrinters);
        txtPrinterLabel = findViewById(R.id.txtPrinterLabel);
        txtVersion = findViewById(R.id.txtVersion);
        txtPrintLog = findViewById(R.id.txtPrintLog);
        scrollLog = findViewById(R.id.scrollLog);
        btnLimpiarLog = findViewById(R.id.btnLimpiarLog);
        btnRefrescar = findViewById(R.id.btnRefrescar);
        btnColas = findViewById(R.id.btnColas);
        txtColasResumen = findViewById(R.id.txtColasResumen);

        // Mostrar versión (chip compacto)
        txtVersion.setText("v" + BuildConfig.VERSION_NAME);

        btnIniciar.setOnClickListener(v -> iniciarServicio());
        btnDetener.setOnClickListener(v -> detenerServicio());
        btnPrueba.setOnClickListener(v -> imprimirPrueba());
        if (btnColas != null) {
            btnColas.setOnClickListener(v ->
                startActivity(new Intent(this, PrinterProfilesActivity.class)));
        }
        if (btnRefrescar != null) {
            btnRefrescar.setOnClickListener(v -> {
                cargarImpresoras();
                Toast.makeText(this, "Lista actualizada", Toast.LENGTH_SHORT).show();
            });
        }
        if (btnLimpiarLog != null) {
            btnLimpiarLog.setOnClickListener(v -> {
                PrintService.logClear();
                if (txtPrintLog != null) txtPrintLog.setText("(log limpiado)\n");
            });
        }

        // Pedir permisos
        solicitarPermisos();

        // Pedir whitelist de optimizacion de bateria (CRITICO en Xiaomi/MIUI/Huawei
        // para que el foreground service no sea matado y el puerto 8765 quede vivo)
        solicitarWhitelistBateria();

        // Auto-iniciar el servicio
        iniciarServicio();

        // Arrancar refresh del log
        logHandler.post(logRefreshRunnable);
    }

    @Override
    protected void onPause() {
        super.onPause();
        logHandler.removeCallbacks(logRefreshRunnable);
        try { unregisterReceiver(usbPermissionReceiver); } catch (Exception ignored) {}
    }

    /**
     * Solicita al usuario que la app sea ignorada del battery optimization.
     * Sin esto, Android (sobre todo MIUI/EMUI/OneUI) mata el foreground service
     * tras unos minutos y el puerto 8765 deja de responder.
     */
    private void solicitarWhitelistBateria() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return;
        PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (pm == null) return;
        String pkg = getPackageName();
        if (pm.isIgnoringBatteryOptimizations(pkg)) return; // ya esta whitelist
        try {
            Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
            intent.setData(Uri.parse("package:" + pkg));
            startActivity(intent);
        } catch (Exception e) {
            Log.w(TAG, "No se pudo pedir whitelist de bateria", e);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        actualizarUI();
        cargarImpresoras();
        actualizarResumenColas();
        // Escuchar resultado del diálogo de permiso USB
        IntentFilter filter = new IntentFilter(UsbPrinter.ACTION_USB_PERMISSION);
        ContextCompat.registerReceiver(this, usbPermissionReceiver, filter,
            ContextCompat.RECEIVER_NOT_EXPORTED);
        // Re-arrancar refresh del log
        logHandler.removeCallbacks(logRefreshRunnable);
        logHandler.post(logRefreshRunnable);
    }

    private void solicitarPermisos() {
        // Notificaciones Android 13+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED) {
                ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.POST_NOTIFICATIONS},
                        NOTIFICATION_PERMISSION_CODE);
            }
        }

        // Bluetooth Android 12+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            String[] btPermisos = {
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.BLUETOOTH_SCAN
            };
            boolean necesita = false;
            for (String perm : btPermisos) {
                if (ContextCompat.checkSelfPermission(this, perm) != PackageManager.PERMISSION_GRANTED) {
                    necesita = true;
                    break;
                }
            }
            if (necesita) {
                ActivityCompat.requestPermissions(this, btPermisos, BLUETOOTH_PERMISSION_CODE);
            }
        }

        // Location (necesario para BLE scan)
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                != PackageManager.PERMISSION_GRANTED) {
            ActivityCompat.requestPermissions(this,
                new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, 102);
        }
    }

    private void iniciarServicio() {
        Intent intent = new Intent(this, PrintService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
        // Esperar un momento para que el servicio inicie
        txtEstado.postDelayed(this::actualizarUI, 500);
    }

    private void detenerServicio() {
        Intent intent = new Intent(this, PrintService.class);
        stopService(intent);
        actualizarUI();
    }

    private void actualizarUI() {
        boolean activo = PrintService.isRunning();

        txtEstado.setText(activo ? "Activo" : "Detenido");
        txtEstado.setTextColor(activo ? 0xFF22C55E : 0xFFEF4444);

        txtPuerto.setText(activo ? "localhost:8765" : "-");

        // Mostrar impresora activa
        PrinterManager pm = PrintService.getStaticPrinterManager();
        if (pm != null) {
            String activeName = pm.getActiveName();
            String activeType = pm.getActiveType();
            txtImpresora.setText(activeName);
            if ("sunmi".equals(activeType)) {
                txtImpresora.setTextColor(0xFF4ADE80);
            } else if ("bluetooth".equals(activeType)) {
                txtImpresora.setTextColor(0xFF38BDF8);
            } else if ("usb".equals(activeType)) {
                txtImpresora.setTextColor(0xFFA78BFA);
            } else if ("serial".equals(activeType)) {
                txtImpresora.setTextColor(0xFFFB923C);
            } else {
                txtImpresora.setTextColor(0xFFCBD5E1);
            }
        } else {
            String modelo = Build.MODEL;
            boolean esSunmi = modelo.toLowerCase().contains("sunmi") ||
                              Build.MANUFACTURER.toLowerCase().contains("sunmi");
            txtImpresora.setText(esSunmi ? "SUNMI " + modelo : modelo);
            txtImpresora.setTextColor(0xFFFFFFFF);
        }

        btnIniciar.setEnabled(!activo);
        btnDetener.setEnabled(activo);
        btnPrueba.setEnabled(activo);
    }

    /**
     * Resumen de las impresoras configuradas (perfiles = colas).
     * Un perfil sin cola no puede recibir trabajos, asi que se marca aparte:
     * en pantalla debe verse que esta a medio configurar.
     */
    private void actualizarResumenColas() {
        if (txtColasResumen == null) return;
        try {
            java.util.List<PrinterProfile> perfiles =
                new PrinterProfileStore(this).getAll();
            if (perfiles.isEmpty()) {
                txtColasResumen.setText("Sin impresoras configuradas");
                txtColasResumen.setTextColor(0xFF94A3B8);
                return;
            }
            StringBuilder sb = new StringBuilder();
            int incompletas = 0;
            for (int i = 0; i < perfiles.size(); i++) {
                PrinterProfile p = perfiles.get(i);
                if (sb.length() > 0) sb.append("\n");
                if (p.queueCode == null || p.queueCode.isEmpty()) {
                    incompletas++;
                    sb.append("\u26A0 ").append(p.getDisplayName()).append(" - sin cola");
                } else {
                    sb.append("Cola ").append(p.queueCode).append("  ").append(p.getDisplayName());
                }
            }
            txtColasResumen.setText(sb.toString());
            txtColasResumen.setTextColor(incompletas > 0 ? 0xFFDC2626 : 0xFF475569);
        } catch (Exception e) {
            Log.w(TAG, "No se pudo leer los perfiles", e);
        }
    }

    /**
     * Cargar lista de impresoras disponibles en RadioGroup
     */
    private void cargarImpresoras() {
        radioGroupPrinters.removeAllViews();

        SharedPreferences prefs = getSharedPreferences("printer_prefs", MODE_PRIVATE);
        String activeType = prefs.getString("active_type", "");
        String activeAddress = prefs.getString("active_address", "");

        boolean esSunmi = Build.MODEL.toLowerCase().contains("sunmi") ||
                          Build.MANUFACTURER.toLowerCase().contains("sunmi");
        if (activeType.isEmpty() && esSunmi) activeType = "sunmi";

        int count = 0;

        // ── SUNMI interna ────────────────────────────────────────────
        if (esSunmi) {
            addPrinterRow("SUNMI Interna", "Impresora integrada", "sunmi", "",
                "#16a34a", "SUNMI", false, false, false, "auto", 9600,
                "sunmi".equals(activeType));
            count++;
        }

        // ── Bluetooth pareados ───────────────────────────────────────
        BluetoothAdapter btAdapter = BluetoothAdapter.getDefaultAdapter();
        if (btAdapter != null && btAdapter.isEnabled()) {
            try {
                Set<BluetoothDevice> paired = btAdapter.getBondedDevices();
                if (paired != null) {
                    for (BluetoothDevice device : paired) {
                        String nombre = device.getName() != null ? device.getName() : "Desconocido";
                        String addr = device.getAddress();
                        String proto = prefs.getString("protocol_" + addr.toUpperCase(), "auto");
                        boolean checked = "bluetooth".equals(activeType) && addr.equalsIgnoreCase(activeAddress);
                        addPrinterRow(nombre, addr, "bluetooth", addr,
                            "#0284c7", "BT", true, false, false, proto, 9600, checked);
                        count++;
                    }
                }
            } catch (SecurityException e) {
                Log.w(TAG, "Sin permiso BT para listar", e);
                addInfoLine("Sin permiso Bluetooth", 0xFFEF4444);
            }
        }

        // ── USB (host, bulk) + Serial ────────────────────────────────
        // Usa el PrinterManager del servicio si corre; si no, instancias temporales.
        PrinterManager pm = PrintService.getStaticPrinterManager();
        UsbPrinter usb = pm != null ? pm.getUsbPrinter() : new UsbPrinter(this);
        SerialPrinter serial = pm != null ? pm.getSerialPrinter() : new SerialPrinter(this);

        try {
            JSONArray usbDevs = usb.getDevices();
            for (int i = 0; i < usbDevs.length(); i++) {
                JSONObject o = usbDevs.getJSONObject(i);
                String addr = o.getString("address");
                String nombre = o.optString("name", "USB " + addr);
                boolean needPerm = "need_permission".equals(o.optString("status", ""));
                String proto = prefs.getString("protocol_" + addr.toUpperCase(), "auto");
                boolean checked = "usb".equals(activeType) && addr.equalsIgnoreCase(activeAddress);
                addPrinterRow(nombre, "USB · " + addr, "usb", addr,
                    "#7c3aed", "USB", true, false, needPerm, proto, 9600, checked);
                count++;
            }
        } catch (Exception e) {
            Log.w(TAG, "Error listando USB", e);
        }

        try {
            JSONArray serDevs = serial.getDevices();
            for (int i = 0; i < serDevs.length(); i++) {
                JSONObject o = serDevs.getJSONObject(i);
                String addr = o.getString("address");
                String subtype = o.optString("subtype", "usb");
                String nombre = o.optString("name", "Serial " + addr);
                boolean isUsbSerial = "usb".equals(subtype);
                boolean needPerm = isUsbSerial && "need_permission".equals(o.optString("status", ""));
                String proto = prefs.getString("protocol_" + addr.toUpperCase(), "auto");
                int baud = prefs.getInt("serial_baud_" + addr.toUpperCase(), 9600);
                boolean checked = "serial".equals(activeType) && addr.equalsIgnoreCase(activeAddress);
                addPrinterRow(nombre, (isUsbSerial ? "USB-Serial · " : "Serial nativo · ") + addr,
                    "serial", addr, "#ea580c", "SERIAL", true, true, needPerm, proto, baud, checked);
                count++;
            }
        } catch (Exception e) {
            Log.w(TAG, "Error listando serial", e);
        }

        if (count == 0) {
            addInfoLine("No hay impresoras. Encendé Bluetooth o conectá una USB/Serial y tocá Refrescar.",
                0xFF94A3B8);
        }

        txtPrinterLabel.setText("Impresoras disponibles (" + count + ")");
    }

    /** Línea informativa simple en el listado. */
    private void addInfoLine(String text, int color) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextColor(color);
        tv.setTextSize(12);
        tv.setPadding(dp(4), dp(8), dp(4), dp(8));
        radioGroupPrinters.addView(tv);
    }

    /** Chip de color con el nombre del transporte (BT/USB/SERIAL/SUNMI). */
    private TextView makeChip(String text, String colorHex) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(9);
        t.setTextColor(Color.WHITE);
        t.setPadding(dp(8), dp(3), dp(8), dp(3));
        GradientDrawable g = new GradientDrawable();
        g.setColor(Color.parseColor(colorHex));
        g.setCornerRadius(dp(10));
        t.setBackground(g);
        return t;
    }

    /**
     * Construye una fila de impresora unificada (cualquier transporte):
     *  línea 1: RadioButton + chip de transporte
     *  línea 2 (config): [Protocolo spinner] [Baud spinner] [botón Permitir]
     */
    private void addPrinterRow(String nombre, String sub, String type, String address,
                               String chipColor, String chipText,
                               boolean hasProtocol, boolean hasBaud, boolean needsPermission,
                               String proto, int baud, boolean checked) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setBackground(ContextCompat.getDrawable(this, R.drawable.row_bg));
        card.setPadding(dp(12), dp(8), dp(12), dp(10));
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        clp.topMargin = dp(8);
        card.setLayoutParams(clp);

        // Línea 1: radio + chip
        LinearLayout line1 = new LinearLayout(this);
        line1.setOrientation(LinearLayout.HORIZONTAL);
        line1.setGravity(Gravity.CENTER_VERTICAL);

        RadioButton rb = crearRadioButton(nombre + "\n" + sub, 0);
        rb.setTag(type + "|" + address);
        rb.setChecked(checked);
        rb.setLayoutParams(new LinearLayout.LayoutParams(0,
            LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        final String fType = type, fAddress = address, fName = nombre;
        final boolean fNeedsPerm = needsPermission;
        rb.setOnClickListener(v -> {
            uncheckRadiosHermanos(rb);
            rb.setChecked(true);
            guardarSeleccionImpresora(fType, fAddress, fName);
            if (fNeedsPerm) solicitarPermisoUsb(fAddress);
        });

        line1.addView(rb);
        line1.addView(makeChip(chipText, chipColor));
        card.addView(line1);

        // Línea 2: config (protocolo / baud / permiso)
        if (hasProtocol || hasBaud || needsPermission) {
            LinearLayout line2 = new LinearLayout(this);
            line2.setOrientation(LinearLayout.HORIZONTAL);
            line2.setGravity(Gravity.CENTER_VERTICAL);
            LinearLayout.LayoutParams l2 = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            l2.topMargin = dp(6);
            line2.setLayoutParams(l2);

            if (hasProtocol) {
                line2.addView(makeSmallLabel("Protocolo"));
                line2.addView(makeProtocolSpinner(address, nombre, proto));
            }
            if (hasBaud) {
                line2.addView(makeSmallLabel("Baud"));
                line2.addView(makeBaudSpinner(address, baud));
            }
            if (needsPermission) {
                Button bp = new Button(this);
                bp.setText("Permitir");
                bp.setTextSize(10);
                bp.setTextColor(0xFFFFFFFF);
                bp.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xFFF59E0B));
                bp.setMinWidth(0);
                bp.setMinimumWidth(0);
                bp.setPadding(dp(14), 0, dp(14), 0);
                LinearLayout.LayoutParams bplp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT, dp(34));
                bplp.setMarginStart(dp(8));
                bp.setLayoutParams(bplp);
                bp.setOnClickListener(v -> solicitarPermisoUsb(address));
                line2.addView(bp);
            }
            card.addView(line2);
        }

        radioGroupPrinters.addView(card);
    }

    private TextView makeSmallLabel(String text) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(11);
        t.setTextColor(0xFF64748B);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.setMarginStart(dp(4));
        lp.setMarginEnd(dp(4));
        t.setLayoutParams(lp);
        return t;
    }

    private Spinner makeProtocolSpinner(String address, String nombre, String proto) {
        Spinner spn = new Spinner(this);
        final String[] labels = {"Auto", "ESC/POS", "CPCL", "ZPL"};
        final String[] vals = {"auto", "escpos", "cpcl", "zpl"};
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
            android.R.layout.simple_spinner_item, labels);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spn.setAdapter(adapter);
        int idx = 0;
        for (int i = 0; i < vals.length; i++) if (vals[i].equals(proto)) { idx = i; break; }
        spn.setSelection(idx, false);
        spn.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                String nuevo = vals[position];
                getSharedPreferences("printer_prefs", MODE_PRIVATE).edit()
                    .putString("protocol_" + address.toUpperCase(), nuevo).apply();
                PrinterManager pm = PrintService.getStaticPrinterManager();
                if (pm != null) pm.setProtocol(address, nuevo);
                Log.i(TAG, "Protocolo " + nombre + " -> " + nuevo);
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        return spn;
    }

    private Spinner makeBaudSpinner(String address, int baud) {
        Spinner spn = new Spinner(this);
        final int[] bauds = {9600, 19200, 38400, 57600, 115200};
        final String[] labels = {"9600", "19200", "38400", "57600", "115200"};
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this,
            android.R.layout.simple_spinner_item, labels);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spn.setAdapter(adapter);
        int idx = 0;
        for (int i = 0; i < bauds.length; i++) if (bauds[i] == baud) { idx = i; break; }
        spn.setSelection(idx, false);
        spn.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                int nuevo = bauds[position];
                getSharedPreferences("printer_prefs", MODE_PRIVATE).edit()
                    .putInt("serial_baud_" + address.toUpperCase(), nuevo).apply();
                PrinterManager pm = PrintService.getStaticPrinterManager();
                if (pm != null) pm.setBaud(address, nuevo);
                Log.i(TAG, "Baud " + address + " -> " + nuevo);
            }
            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        return spn;
    }

    /** Pide permiso USB para el device (usb o serial-usb) via el servicio o instancias locales. */
    private void solicitarPermisoUsb(String address) {
        PrinterManager pm = PrintService.getStaticPrinterManager();
        if (pm != null) {
            pm.getUsbPrinter().requestPermission(address);
            pm.getSerialPrinter().requestPermission(address);
        } else {
            new UsbPrinter(this).requestPermission(address);
            new SerialPrinter(this).requestPermission(address);
        }
    }

    /**
     * Desmarca todos los RadioButtons hermanos (en el RadioGroup o anidados en
     * filas LinearLayout) excepto el que se pasa como excepción.
     */
    private void uncheckRadiosHermanos(RadioButton mantener) {
        uncheckRecursivo(radioGroupPrinters, mantener);
    }

    private void uncheckRecursivo(ViewGroup group, RadioButton mantener) {
        for (int i = 0; i < group.getChildCount(); i++) {
            View child = group.getChildAt(i);
            if (child instanceof RadioButton && child != mantener) {
                ((RadioButton) child).setChecked(false);
            } else if (child instanceof ViewGroup) {
                uncheckRecursivo((ViewGroup) child, mantener);
            }
        }
    }

    /**
     * Persiste la impresora activa y notifica al PrinterManager (si el servicio corre).
     */
    private void guardarSeleccionImpresora(String type, String address, String labelToast) {
        SharedPreferences.Editor editor = getSharedPreferences("printer_prefs", MODE_PRIVATE).edit();
        editor.putString("active_type", type);
        editor.putString("active_address", address);
        editor.apply();

        PrinterManager pm = PrintService.getStaticPrinterManager();
        if (pm != null) pm.setActive(type, address);

        actualizarUI();
        Toast.makeText(this, "Impresora: " + labelToast, Toast.LENGTH_SHORT).show();
    }

    /**
     * Crear RadioButton con estilo consistente
     */
    private RadioButton crearRadioButton(String text, int id) {
        RadioButton rb = new RadioButton(this);
        rb.setId(id);
        rb.setText(text);
        rb.setTextSize(14);
        rb.setTextColor(0xFF1E293B);
        rb.setPadding(8, 12, 8, 12);
        return rb;
    }

    /**
     * Imprimir tiquete de prueba
     */
    private void imprimirPrueba() {
        PrinterManager pm = PrintService.getStaticPrinterManager();
        if (pm == null) {
            Toast.makeText(this, "Servicio no iniciado", Toast.LENGTH_SHORT).show();
            return;
        }

        String prueba = "================================\n"
                       + "   FACTUPOS PRINT BRIDGE v" + BuildConfig.VERSION_NAME + "\n"
                       + "       Prueba de impresion\n"
                       + "================================\n"
                       + "Impresora: " + pm.getActiveName() + "\n"
                       + "Tipo: " + pm.getActiveType() + "\n"
                       + "Modelo: " + Build.MODEL + "\n"
                       + "Android: " + Build.VERSION.RELEASE + " (SDK " + Build.VERSION.SDK_INT + ")\n"
                       + "--------------------------------\n"
                       + "Si puede leer esto, la impresora\n"
                       + "esta funcionando correctamente.\n"
                       + "================================\n\n\n";

        btnPrueba.setEnabled(false);
        btnPrueba.setText("Imprimiendo...");

        // Ejecutar en hilo separado (BT no puede correr en UI thread)
        new Thread(() -> {
            boolean ok = pm.printText(prueba);
            String errorDetail = "";
            if (!ok) {
                try {
                    String sppErr = pm.getBluetoothPrinter().getLastError();
                    String bleErr = pm.getBlePrinter().getLastError();
                    errorDetail = "SPP:" + (sppErr.isEmpty() ? "?" : sppErr);
                    if (!bleErr.isEmpty()) errorDetail += " | BLE:" + bleErr;
                } catch (Exception ignored) {}
            }
            final String msg = ok
                ? "Prueba enviada a " + pm.getActiveName()
                : "ERROR: " + (errorDetail.isEmpty() ? "Desconocido" : errorDetail);
            final String errForEmail = errorDetail;
            runOnUiThread(() -> {
                btnPrueba.setEnabled(true);
                btnPrueba.setText("Prueba");
                if (!ok) {
                    // Mostrar error completo en txtEstado (seleccionable)
                    txtEstado.setText(msg);
                    txtEstado.setTextIsSelectable(true);
                    txtEstado.setTextColor(Color.parseColor("#dc2626"));
                    // Copiar al portapapeles
                    ClipboardManager clipboard = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                    if (clipboard != null) {
                        clipboard.setPrimaryClip(ClipData.newPlainText("PrintBridge Error", msg));
                        Toast.makeText(this, "Error copiado al portapapeles", Toast.LENGTH_SHORT).show();
                    }
                    // Enviar error por email
                    enviarErrorPorEmail(errForEmail);
                } else {
                    txtEstado.setText(msg);
                    txtEstado.setTextColor(Color.parseColor("#059669"));
                    Toast.makeText(this, msg, Toast.LENGTH_SHORT).show();
                }
            });
        }).start();
    }

    private void enviarErrorPorEmail(String errorDetail) {
        try {
            PrinterManager pm = PrintService.getStaticPrinterManager();
            String body = "=== FactuPOS Print Bridge Error ===\n\n"
                + "Versión: " + BuildConfig.VERSION_NAME + "\n"
                + "Build: " + BuildConfig.BUILD_DATE + "\n"
                + "Modelo: " + Build.MODEL + "\n"
                + "Fabricante: " + Build.MANUFACTURER + "\n"
                + "Android: " + Build.VERSION.RELEASE + " (SDK " + Build.VERSION.SDK_INT + ")\n"
                + "Impresora: " + (pm != null ? pm.getActiveName() : "N/A") + "\n"
                + "Tipo: " + (pm != null ? pm.getActiveType() : "N/A") + "\n"
                + "Dirección: " + (pm != null ? pm.getActiveAddress() : "N/A") + "\n\n"
                + "Error detalle:\n" + errorDetail + "\n\n"
                + "SPP error: " + (pm != null ? pm.getBluetoothPrinter().getLastError() : "N/A") + "\n"
                + "BLE error: " + (pm != null ? pm.getBlePrinter().getLastError() : "N/A") + "\n"
                + "BLE scan dispositivos: " + (pm != null ? pm.getBlePrinter().getLastScanDevices() : "N/A") + "\n";

            Intent emailIntent = new Intent(Intent.ACTION_SEND);
            emailIntent.setType("text/plain");
            emailIntent.putExtra(Intent.EXTRA_EMAIL, new String[]{"info@soportereal.com"});
            emailIntent.putExtra(Intent.EXTRA_SUBJECT, "PrintBridge Error v" + BuildConfig.VERSION_NAME + " - " + Build.MODEL);
            emailIntent.putExtra(Intent.EXTRA_TEXT, body);
            startActivity(Intent.createChooser(emailIntent, "Enviar error"));
        } catch (Exception e) {
            Toast.makeText(this, "No se pudo abrir email", Toast.LENGTH_SHORT).show();
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == BLUETOOTH_PERMISSION_CODE) {
            // Recargar lista de impresoras después de obtener permisos BT
            cargarImpresoras();
        }
    }
}
