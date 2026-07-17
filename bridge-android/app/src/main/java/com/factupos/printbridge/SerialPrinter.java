package com.factupos.printbridge;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbManager;
import android.os.Build;
import android.util.Log;

import com.hoho.android.usbserial.driver.UsbSerialDriver;
import com.hoho.android.usbserial.driver.UsbSerialPort;
import com.hoho.android.usbserial.driver.UsbSerialProber;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.util.List;
import java.util.Locale;

/**
 * SerialPrinter - Transporte serial genérico y configurable.
 *
 * Soporta DOS caminos, elegidos por la forma del "address":
 *
 *   1. USB-Serial (address = VID:PID "vvvv:pppp"): adaptadores/chips
 *      FTDI, CH340/CH34x, CP210x, PL2303 y CDC-ACM, resueltos por la
 *      librería usb-serial-for-android (mik3y). Requiere permiso USB.
 *
 *   2. Serial nativo (address = ruta "/dev/ttyS0", "/dev/ttyMT1", etc.):
 *      puerto físico del equipo. Best-effort: configura baudrate con
 *      `stty` (si está disponible) y escribe por FileOutputStream. En
 *      equipos sin root/permisos puede fallar (fragilidad conocida).
 *
 * Parámetros: baudrate configurable (default 9600), 8 data bits, 1 stop
 * bit, sin paridad (8N1). Reutiliza los renderers de {@link BluetoothPrinter}.
 */
public class SerialPrinter {

    private static final String TAG = "SerialPrinter";
    public static final int DEFAULT_BAUD = 9600;

    // Rutas típicas de puertos serial nativos en tablets/POS Android.
    private static final String[] NATIVE_PORT_GLOB = {
        "/dev/ttyS", "/dev/ttyMT", "/dev/ttyHSL", "/dev/ttyHS", "/dev/ttyGS", "/dev/ttysWK"
    };

    private final Context context;
    private final UsbManager usbManager;
    private String lastError = "";

    public SerialPrinter(Context context) {
        this.context = context.getApplicationContext();
        this.usbManager = (UsbManager) this.context.getSystemService(Context.USB_SERVICE);
    }

    public String getLastError() { return lastError; }

    /** ¿Es una clave USB-serial VID:PID ("vvvv:pppp")? Si no, se trata como ruta nativa. */
    public static boolean isUsbKey(String address) {
        return address != null && address.matches("(?i)^[0-9a-f]{4}:[0-9a-f]{4}$");
    }

    private static String keyFor(UsbDevice d) {
        return String.format(Locale.US, "%04x:%04x", d.getVendorId(), d.getProductId());
    }

    /** ¿La app ya tiene permiso USB para este device (solo USB-serial)? */
    public boolean hasPermission(String address) {
        if (!isUsbKey(address) || usbManager == null) return true; // nativo no usa permiso USB
        UsbDevice d = findUsbDevice(address);
        return d != null && usbManager.hasPermission(d);
    }

    public void requestPermission(String address) {
        if (!isUsbKey(address) || usbManager == null) return;
        UsbDevice d = findUsbDevice(address);
        if (d == null || usbManager.hasPermission(d)) return;
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) flags |= PendingIntent.FLAG_MUTABLE;
        Intent intent = new Intent(UsbPrinter.ACTION_USB_PERMISSION);
        intent.setPackage(context.getPackageName());
        PendingIntent pi = PendingIntent.getBroadcast(context, 0, intent, flags);
        usbManager.requestPermission(d, pi);
    }

    private UsbDevice findUsbDevice(String key) {
        if (usbManager == null) return null;
        try {
            for (UsbDevice d : usbManager.getDeviceList().values()) {
                if (keyFor(d).equalsIgnoreCase(key)) return d;
            }
        } catch (Exception ignored) {}
        return null;
    }

    public String getDeviceName(String address) {
        if (!isUsbKey(address)) return "Serial " + address;
        UsbDevice d = findUsbDevice(address);
        if (d == null) return "Serial USB (desconectado)";
        String name = null;
        try { name = d.getProductName(); } catch (Exception ignored) {}
        return (name != null && !name.trim().isEmpty()) ? name + " (serial)" : "Serial USB " + address;
    }

    /**
     * Lista puertos serial disponibles como JSON:
     *   USB-serial: {type:"serial", subtype:"usb", name, address:"vvvv:pppp", status}
     *   nativo:     {type:"serial", subtype:"native", name, address:"/dev/ttyS0", status:"ready"}
     */
    public JSONArray getDevices() {
        JSONArray arr = new JSONArray();

        // 1. USB-serial (librería mik3y)
        if (usbManager != null) {
            try {
                List<UsbSerialDriver> drivers =
                    UsbSerialProber.getDefaultProber().findAllDrivers(usbManager);
                for (UsbSerialDriver drv : drivers) {
                    UsbDevice d = drv.getDevice();
                    String key = keyFor(d);
                    JSONObject o = new JSONObject();
                    o.put("type", "serial");
                    o.put("subtype", "usb");
                    o.put("name", getDeviceName(key));
                    o.put("address", key);
                    o.put("driver", drv.getClass().getSimpleName());
                    o.put("status", usbManager.hasPermission(d) ? "ready" : "need_permission");
                    arr.put(o);
                }
            } catch (Exception e) {
                Log.w(TAG, "Error listando USB-serial", e);
            }
        }

        // 2. Serial nativo (rutas /dev/tty*)
        try {
            File dev = new File("/dev");
            File[] nodes = dev.listFiles();
            if (nodes != null) {
                for (File f : nodes) {
                    String path = f.getAbsolutePath();
                    boolean match = false;
                    for (String pref : NATIVE_PORT_GLOB) {
                        if (path.startsWith(pref)) { match = true; break; }
                    }
                    if (!match) continue;
                    JSONObject o = new JSONObject();
                    o.put("type", "serial");
                    o.put("subtype", "native");
                    o.put("name", "Serial " + f.getName());
                    o.put("address", path);
                    o.put("status", f.canWrite() ? "ready" : "need_permission");
                    arr.put(o);
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "Error listando serial nativo", e);
        }

        return arr;
    }

    /** Arma el payload según protocolo (reusa renderers de BluetoothPrinter). */
    private byte[] buildPayload(String text, String proto, String devName) throws Exception {
        String p = proto;
        if (p == null || p.isEmpty() || "auto".equals(p)) {
            p = BluetoothPrinter.isZebraPrinter(devName) ? "cpcl" : "escpos";
        }
        if ("cpcl".equals(p)) return BluetoothPrinter.renderTextoComoCpcl(text, devName);
        if ("zpl".equals(p))  return BluetoothPrinter.renderTextoComoZpl(text);
        // ESC/POS: reset + texto + feed + cut
        byte[] body = text.getBytes("UTF-8");
        byte[] head = new byte[]{0x1B, 0x40};
        byte[] tail = new byte[]{0x0A, 0x0A, 0x0A, 0x0A, 0x1D, 0x56, 0x00};
        byte[] out = new byte[head.length + body.length + tail.length];
        System.arraycopy(head, 0, out, 0, head.length);
        System.arraycopy(body, 0, out, head.length, body.length);
        System.arraycopy(tail, 0, out, head.length + body.length, tail.length);
        return out;
    }

    /**
     * Imprime por serial.
     *
     * @param address VID:PID (USB-serial) o ruta /dev/tty* (nativo)
     * @param text    contenido
     * @param proto   auto|escpos|cpcl|zpl
     * @param baud    baudrate (<=0 usa DEFAULT_BAUD)
     */
    public boolean printText(String address, String text, String proto, int baud) {
        lastError = "";
        if (baud <= 0) baud = DEFAULT_BAUD;
        return isUsbKey(address)
            ? printUsbSerial(address, text, proto, baud)
            : printNative(address, text, proto, baud);
    }

    // ── USB-Serial via librería mik3y ────────────────────────────────
    private boolean printUsbSerial(String key, String text, String proto, int baud) {
        if (usbManager == null) { lastError = "USB no soportado"; return false; }

        UsbSerialDriver driver = null;
        try {
            List<UsbSerialDriver> drivers =
                UsbSerialProber.getDefaultProber().findAllDrivers(usbManager);
            for (UsbSerialDriver drv : drivers) {
                if (keyFor(drv.getDevice()).equalsIgnoreCase(key)) { driver = drv; break; }
            }
        } catch (Exception e) {
            lastError = "Error detectando driver serial: " + e.getMessage();
            return false;
        }
        if (driver == null) { lastError = "Serial USB desconectado o sin driver: " + key; return false; }

        UsbDevice device = driver.getDevice();
        if (!usbManager.hasPermission(device)) {
            lastError = "Sin permiso USB — abrí la app y tocá Permitir";
            requestPermission(key);
            return false;
        }

        UsbDeviceConnection conn = usbManager.openDevice(device);
        if (conn == null) { lastError = "No se pudo abrir el device USB-serial"; return false; }

        UsbSerialPort port = driver.getPorts().get(0);
        try {
            byte[] payload = buildPayload(text, proto, getDeviceName(key));
            port.open(conn);
            port.setParameters(baud, 8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE);
            PrintService.logEvent("Serial USB " + key + " @" + baud + " 8N1, " + payload.length + " bytes");
            port.write(payload, 8000);
            PrintService.logEvent("Serial USB enviado OK");
            Log.i(TAG, "Impreso serial USB " + key + " " + payload.length + " bytes @" + baud);
            return true;
        } catch (Exception e) {
            lastError = "Error serial USB: " + e.getClass().getSimpleName() + " - " + e.getMessage();
            Log.e(TAG, lastError, e);
            return false;
        } finally {
            try { port.close(); } catch (Exception ignored) {}
            try { conn.close(); } catch (Exception ignored) {}
        }
    }

    // ── Serial nativo /dev/tty* (best-effort) ────────────────────────
    private boolean printNative(String path, String text, String proto, int baud) {
        File f = new File(path);
        if (!f.exists()) { lastError = "Puerto no existe: " + path; return false; }
        if (!f.canWrite()) {
            lastError = "Sin permiso de escritura en " + path + " (requiere root/SDK del fabricante)";
            return false;
        }

        // Configurar baudrate 8N1 con stty (best-effort; toybox/coreutils)
        try {
            Process p = Runtime.getRuntime().exec(new String[]{
                "stty", "-F", path, String.valueOf(baud),
                "cs8", "-cstopb", "-parenb", "raw", "-echo"
            });
            p.waitFor();
            PrintService.logEvent("stty " + path + " " + baud + " 8N1 rc=" + p.exitValue());
        } catch (Exception e) {
            PrintService.logEvent("stty no disponible (" + e.getMessage() + "), escribo con baud actual");
        }

        FileOutputStream fos = null;
        try {
            byte[] payload = buildPayload(text, proto, "Serial " + f.getName());
            fos = new FileOutputStream(f);
            fos.write(payload);
            fos.flush();
            PrintService.logEvent("Serial nativo " + path + " enviado " + payload.length + " bytes");
            Log.i(TAG, "Impreso serial nativo " + path + " " + payload.length + " bytes");
            return true;
        } catch (Exception e) {
            lastError = "Error serial nativo: " + e.getClass().getSimpleName() + " - " + e.getMessage();
            Log.e(TAG, lastError, e);
            return false;
        } finally {
            if (fos != null) try { fos.close(); } catch (Exception ignored) {}
        }
    }
}
