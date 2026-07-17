package com.factupos.printbridge;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * PrinterManager - Gestor de impresoras multi-destino
 *
 * Mantiene lista de impresoras disponibles (SUNMI interna + BT pareadas)
 * y permite seleccionar cuál es la impresora activa.
 * La selección se persiste en SharedPreferences.
 */
public class PrinterManager {

    private static final String TAG = "PrinterManager";
    private static final String PREFS_NAME = "printer_prefs";
    private static final String KEY_ACTIVE_TYPE = "active_type";     // "sunmi" | "bluetooth"
    private static final String KEY_ACTIVE_ADDRESS = "active_address"; // MAC address (solo BT)

    // Protocolos seteados por el usuario por MAC/clave: "auto" | "escpos" | "cpcl" | "zpl"
    private static final String KEY_PROTOCOL_PREFIX = "protocol_";
    // Baudrate serial por clave de dispositivo
    private static final String KEY_BAUD_PREFIX = "serial_baud_";
    public static final String PROTOCOL_AUTO   = "auto";
    public static final String PROTOCOL_ESCPOS = "escpos";
    public static final String PROTOCOL_CPCL   = "cpcl";
    public static final String PROTOCOL_ZPL    = "zpl";

    private final Context context;
    private final FactuposPrint sunmiPrinter;
    private final BluetoothPrinter bluetoothPrinter;
    private final boolean isSunmiDevice;

    private final BlePrinter blePrinter;
    private final UsbPrinter usbPrinter;
    private final SerialPrinter serialPrinter;

    public PrinterManager(Context context, FactuposPrint sunmiPrinter) {
        this.context = context.getApplicationContext();
        this.sunmiPrinter = sunmiPrinter;
        this.bluetoothPrinter = new BluetoothPrinter();
        this.blePrinter = new BlePrinter(context);
        this.usbPrinter = new UsbPrinter(context);
        this.serialPrinter = new SerialPrinter(context);

        String model = Build.MODEL.toLowerCase();
        String manufacturer = Build.MANUFACTURER.toLowerCase();
        this.isSunmiDevice = model.contains("sunmi") || manufacturer.contains("sunmi");
    }

    public BlePrinter getBlePrinter() { return blePrinter; }
    public UsbPrinter getUsbPrinter() { return usbPrinter; }
    public SerialPrinter getSerialPrinter() { return serialPrinter; }

    /**
     * Obtener tipo de impresora activa
     */
    public String getActiveType() {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        String type = prefs.getString(KEY_ACTIVE_TYPE, "");
        // Si no hay selección, default a SUNMI si es dispositivo SUNMI
        if (type.isEmpty()) {
            return isSunmiDevice ? "sunmi" : "";
        }
        return type;
    }

    /**
     * Obtener dirección MAC de la impresora BT activa (solo para tipo "bluetooth")
     */
    public String getActiveAddress() {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        return prefs.getString(KEY_ACTIVE_ADDRESS, "");
    }

    /**
     * Seleccionar impresora activa
     *
     * @param type    "sunmi" o "bluetooth"
     * @param address Dirección MAC (solo para bluetooth, puede ser "" para sunmi)
     */
    public void setActive(String type, String address) {
        SharedPreferences.Editor editor = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit();
        editor.putString(KEY_ACTIVE_TYPE, type);
        editor.putString(KEY_ACTIVE_ADDRESS, address != null ? address : "");
        editor.apply();
        Log.i(TAG, "Impresora activa: type=" + type + " address=" + address);
    }

    /**
     * Obtener nombre de la impresora activa
     */
    public String getActiveName() {
        String type = getActiveType();
        if ("sunmi".equals(type)) {
            return "SUNMI Interna";
        } else if ("bluetooth".equals(type)) {
            String address = getActiveAddress();
            if (!address.isEmpty()) {
                return bluetoothPrinter.getDeviceName(address);
            }
            return "Bluetooth (sin seleccionar)";
        } else if ("usb".equals(type)) {
            String address = getActiveAddress();
            return address.isEmpty() ? "USB (sin seleccionar)" : usbPrinter.getDeviceName(address);
        } else if ("serial".equals(type)) {
            String address = getActiveAddress();
            return address.isEmpty() ? "Serial (sin seleccionar)" : serialPrinter.getDeviceName(address);
        }
        return "Ninguna";
    }

    /**
     * Imprimir texto usando la impresora activa
     *
     * @param text Texto a imprimir
     * @return true si se imprimió correctamente
     */
    public boolean printText(String text) {
        String type = getActiveType();

        if ("sunmi".equals(type)) {
            return sunmiPrinter.printText(text);
        } else if ("bluetooth".equals(type)) {
            String address = getActiveAddress();
            if (address.isEmpty()) {
                Log.e(TAG, "No hay impresora BT seleccionada");
                return false;
            }
            // Resolver protocolo configurado por el usuario (auto = detección por nombre)
            String devName = "";
            try {
                BluetoothDevice dev = BluetoothAdapter.getDefaultAdapter().getRemoteDevice(address);
                if (dev != null) devName = dev.getName() != null ? dev.getName() : "";
            } catch (Exception ignored) {}
            String proto = resolveProtocol(address, devName);

            // Intentar SPP clásico primero, con el protocolo elegido
            boolean ok = bluetoothPrinter.printText(address, text, proto);
            if (!ok && shouldTryBle(address)) {
                // Fallback BLE solo si el device no es exclusivamente BT Classic
                Log.i(TAG, "SPP falló (" + bluetoothPrinter.getLastError() + "), intentando BLE...");
                ok = blePrinter.printText(address, text);
                if (!ok) {
                    Log.e(TAG, "BLE también falló: " + blePrinter.getLastError());
                }
            } else if (!ok) {
                Log.w(TAG, "SPP falló y device es BT Classic; no se intenta BLE.");
            }
            return ok;
        } else if ("usb".equals(type)) {
            String address = getActiveAddress();
            if (address.isEmpty()) {
                Log.e(TAG, "No hay impresora USB seleccionada");
                return false;
            }
            String proto = resolveProtocol(address, usbPrinter.getDeviceName(address));
            return usbPrinter.printText(address, text, proto);
        } else if ("serial".equals(type)) {
            String address = getActiveAddress();
            if (address.isEmpty()) {
                Log.e(TAG, "No hay puerto serial seleccionado");
                return false;
            }
            String proto = resolveProtocol(address, serialPrinter.getDeviceName(address));
            return serialPrinter.printText(address, text, proto, getBaud(address));
        }

        // Sin impresora configurada - intentar SUNMI por defecto si es dispositivo SUNMI
        if (isSunmiDevice) {
            return sunmiPrinter.printText(text);
        }

        Log.e(TAG, "No hay impresora configurada");
        return false;
    }

    /**
     * Lee el protocolo configurado por el usuario para una MAC dada.
     * Default: PROTOCOL_AUTO.
     */
    public String getProtocol(String address) {
        if (address == null || address.isEmpty()) return PROTOCOL_AUTO;
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        return prefs.getString(KEY_PROTOCOL_PREFIX + address.toUpperCase(), PROTOCOL_AUTO);
    }

    /**
     * Guarda el protocolo seleccionado por el usuario para una MAC.
     */
    public void setProtocol(String address, String protocol) {
        if (address == null || address.isEmpty() || protocol == null) return;
        SharedPreferences.Editor editor = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit();
        editor.putString(KEY_PROTOCOL_PREFIX + address.toUpperCase(), protocol);
        editor.apply();
        Log.i(TAG, "Protocolo " + address + " → " + protocol);
    }

    /**
     * Lee el baudrate serial configurado para una clave de dispositivo.
     * Default: SerialPrinter.DEFAULT_BAUD (9600).
     */
    public int getBaud(String address) {
        if (address == null || address.isEmpty()) return SerialPrinter.DEFAULT_BAUD;
        SharedPreferences prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
        return prefs.getInt(KEY_BAUD_PREFIX + address.toUpperCase(), SerialPrinter.DEFAULT_BAUD);
    }

    /** Guarda el baudrate serial para una clave de dispositivo. */
    public void setBaud(String address, int baud) {
        if (address == null || address.isEmpty() || baud <= 0) return;
        SharedPreferences.Editor editor = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit();
        editor.putInt(KEY_BAUD_PREFIX + address.toUpperCase(), baud);
        editor.apply();
        Log.i(TAG, "Baudrate " + address + " → " + baud);
    }

    /**
     * Resuelve el protocolo efectivo: si el usuario eligió "auto", usa
     * detección por nombre (isZebraPrinter); si especificó manualmente,
     * respeta esa elección.
     */
    public String resolveProtocol(String address, String deviceName) {
        String configured = getProtocol(address);
        if (!PROTOCOL_AUTO.equals(configured)) return configured;
        // Auto: detectar por nombre
        return BluetoothPrinter.isZebraPrinter(deviceName) ? PROTOCOL_CPCL : PROTOCOL_ESCPOS;
    }

    /**
     * Decide si vale la pena el fallback BLE.
     * BluetoothDevice.getType() devuelve DEVICE_TYPE_CLASSIC (1) para BR/EDR puro
     * (ej. Zebra MZ320), DEVICE_TYPE_LE (2) para BLE puro, DEVICE_TYPE_DUAL (3) para
     * dual-mode (PT-210). Solo intentamos BLE en LE o DUAL.
     */
    private boolean shouldTryBle(String address) {
        try {
            BluetoothAdapter adapter = BluetoothAdapter.getDefaultAdapter();
            if (adapter == null) return false;
            BluetoothDevice device = adapter.getRemoteDevice(address);
            int type = device.getType();
            return type == BluetoothDevice.DEVICE_TYPE_LE
                || type == BluetoothDevice.DEVICE_TYPE_DUAL;
        } catch (Exception e) {
            // En caso de error o permisos, no intentar BLE (más seguro)
            return false;
        }
    }

    /**
     * Obtener JSON con la impresora activa
     */
    public JSONObject getActiveJSON() throws Exception {
        JSONObject json = new JSONObject();
        String type = getActiveType();
        json.put("type", type.isEmpty() ? "none" : type);
        json.put("name", getActiveName());
        if ("bluetooth".equals(type) || "usb".equals(type) || "serial".equals(type)) {
            json.put("address", getActiveAddress());
        }
        if ("serial".equals(type)) {
            json.put("baud", getBaud(getActiveAddress()));
        }
        return json;
    }

    /**
     * Obtener todas las impresoras disponibles como JSON
     */
    public JSONObject getAvailablePrintersJSON() throws Exception {
        JSONObject result = new JSONObject();
        result.put("ok", true);
        result.put("active", getActiveJSON());

        JSONArray printers = new JSONArray();

        // SUNMI interna (siempre listar si es dispositivo SUNMI)
        if (isSunmiDevice) {
            JSONObject sunmi = new JSONObject();
            sunmi.put("type", "sunmi");
            sunmi.put("name", "SUNMI Interna");
            sunmi.put("status", sunmiPrinter.isReady() ? "ready" : "not_ready");
            printers.put(sunmi);
        }

        // Dispositivos Bluetooth pareados
        if (bluetoothPrinter.isAvailable()) {
            JSONArray btDevices = bluetoothPrinter.getPairedDevices();
            for (int i = 0; i < btDevices.length(); i++) {
                printers.put(btDevices.getJSONObject(i));
            }
        }

        // Dispositivos USB (host, bulk)
        JSONArray usbDevices = usbPrinter.getDevices();
        for (int i = 0; i < usbDevices.length(); i++) {
            printers.put(usbDevices.getJSONObject(i));
        }

        // Puertos serial (USB-serial + nativos)
        JSONArray serialDevices = serialPrinter.getDevices();
        for (int i = 0; i < serialDevices.length(); i++) {
            printers.put(serialDevices.getJSONObject(i));
        }

        result.put("printers", printers);
        return result;
    }

    /**
     * Verificar si la impresora activa está lista
     */
    public boolean isActiveReady() {
        String type = getActiveType();
        if ("sunmi".equals(type)) {
            return sunmiPrinter.isReady();
        } else if ("bluetooth".equals(type)) {
            String address = getActiveAddress();
            return !address.isEmpty() && bluetoothPrinter.isPaired(address);
        } else if ("usb".equals(type)) {
            String address = getActiveAddress();
            return !address.isEmpty() && usbPrinter.findByKey(address) != null
                && usbPrinter.hasPermission(address);
        } else if ("serial".equals(type)) {
            String address = getActiveAddress();
            return !address.isEmpty() && serialPrinter.hasPermission(address);
        }
        return false;
    }

    /**
     * Verificar si es dispositivo SUNMI
     */
    public boolean isSunmiDevice() {
        return isSunmiDevice;
    }

    /**
     * Obtener instancia de BluetoothPrinter
     */
    public BluetoothPrinter getBluetoothPrinter() {
        return bluetoothPrinter;
    }
}
