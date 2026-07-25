package com.factupos.printbridge;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.hardware.usb.UsbConstants;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbInterface;
import android.hardware.usb.UsbManager;
import android.os.Build;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Locale;

/**
 * UsbPrinter - Impresora USB (host mode) genérica.
 *
 * Enumera los dispositivos USB conectados al puerto del equipo (tablet/POS
 * Android con soporte USB host/OTG), pide permiso al usuario y envía los
 * bytes al endpoint BULK OUT via {@link UsbDeviceConnection#bulkTransfer}.
 *
 * No es exclusivo de ninguna marca: sirve para cualquier impresora térmica
 * USB. Reutiliza los renderers de {@link BluetoothPrinter} para CPCL/ZPL y
 * arma ESC/POS (reset + texto + feed + cut) igual que la ruta Bluetooth.
 *
 * El dispositivo se identifica/persiste por su clave VID:PID ("vvvv:pppp"
 * hex), ya que USB no tiene MAC estable.
 */
public class UsbPrinter {

    private static final String TAG = "UsbPrinter";
    public static final String ACTION_USB_PERMISSION = "com.factupos.printbridge.USB_PERMISSION";

    private final Context context;
    private final UsbManager usbManager;
    private String lastError = "";

    public UsbPrinter(Context context) {
        this.context = context.getApplicationContext();
        this.usbManager = (UsbManager) this.context.getSystemService(Context.USB_SERVICE);
    }

    public String getLastError() { return lastError; }

    /** USB host disponible en este equipo. */
    public boolean isAvailable() { return usbManager != null; }

    /** Clave estable de un device: "vvvv:pppp" (VID:PID en hex, 4 dígitos). */
    public static String keyFor(UsbDevice d) {
        return String.format(Locale.US, "%04x:%04x", d.getVendorId(), d.getProductId());
    }

    /** Busca un device conectado por su clave VID:PID (case-insensitive). */
    public UsbDevice findByKey(String key) {
        if (usbManager == null || key == null || key.isEmpty()) return null;
        try {
            for (UsbDevice d : usbManager.getDeviceList().values()) {
                if (keyFor(d).equalsIgnoreCase(key)) return d;
            }
        } catch (Exception e) {
            Log.w(TAG, "Error buscando device USB", e);
        }
        return null;
    }

    /** ¿El device tiene al menos un endpoint BULK OUT (puede recibir datos)? */
    private boolean hasBulkOut(UsbDevice d) {
        for (int i = 0; i < d.getInterfaceCount(); i++) {
            UsbInterface intf = d.getInterface(i);
            for (int e = 0; e < intf.getEndpointCount(); e++) {
                UsbEndpoint ep = intf.getEndpoint(e);
                if (ep.getType() == UsbConstants.USB_ENDPOINT_XFER_BULK
                        && ep.getDirection() == UsbConstants.USB_DIR_OUT) return true;
            }
        }
        return false;
    }

    /** ¿La app ya tiene permiso concedido para este device? */
    public boolean hasPermission(String key) {
        UsbDevice d = findByKey(key);
        return d != null && usbManager != null && usbManager.hasPermission(d);
    }

    /** Nombre legible del device (productName si existe, si no "USB vvvv:pppp"). */
    public String getDeviceName(String key) {
        UsbDevice d = findByKey(key);
        if (d == null) return "USB (desconectada)";
        String name = null;
        try { name = d.getProductName(); } catch (Exception ignored) {}
        if (name == null || name.trim().isEmpty()) name = "USB " + key;
        return name;
    }

    /**
     * Lista los dispositivos USB candidatos (con endpoint BULK OUT) como JSON.
     * Cada entrada: {type:"usb", name, address:"vvvv:pppp", vendorId, productId,
     * status:"ready"|"need_permission"}.
     */
    public JSONArray getDevices() {
        JSONArray arr = new JSONArray();
        if (usbManager == null) return arr;
        try {
            for (UsbDevice d : usbManager.getDeviceList().values()) {
                if (!hasBulkOut(d)) continue; // ignorar hubs/teclados/etc.
                String key = keyFor(d);
                JSONObject o = new JSONObject();
                o.put("type", "usb");
                o.put("name", getDeviceName(key));
                o.put("address", key);
                o.put("vendorId", d.getVendorId());
                o.put("productId", d.getProductId());
                o.put("status", usbManager.hasPermission(d) ? "ready" : "need_permission");
                arr.put(o);
            }
        } catch (Exception e) {
            Log.w(TAG, "Error listando USB", e);
        }
        return arr;
    }

    /**
     * Solicita al usuario permiso para acceder al device (diálogo del sistema).
     * Si el usuario marca "usar siempre", el permiso persiste entre reconexiones.
     */
    public void requestPermission(String key) {
        UsbDevice d = findByKey(key);
        if (d == null || usbManager == null) { lastError = "USB no encontrada: " + key; return; }
        if (usbManager.hasPermission(d)) return;
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) flags |= PendingIntent.FLAG_MUTABLE;
        Intent intent = new Intent(ACTION_USB_PERMISSION);
        intent.setPackage(context.getPackageName());
        PendingIntent pi = PendingIntent.getBroadcast(context, 0, intent, flags);
        usbManager.requestPermission(d, pi);
    }

    /**
     * Imprime texto en la impresora USB indicada por su clave VID:PID.
     *
     * @param key   "vvvv:pppp"
     * @param text  contenido (puede traer ESC/POS embebido del PHP)
     * @param proto "auto" | "escpos" | "cpcl" | "zpl" (null = auto)
     * @return true si se envió correctamente
     */
    public boolean printText(String key, String text, String proto) {
        lastError = "";
        if (usbManager == null) { lastError = "USB no soportado en este equipo"; return false; }

        UsbDevice device = findByKey(key);
        if (device == null) { lastError = "USB desconectada: " + key; return false; }

        if (!usbManager.hasPermission(device)) {
            lastError = "Sin permiso USB — abrí la app y tocá Permitir";
            requestPermission(key);
            return false;
        }

        // Resolver protocolo efectivo (auto -> por nombre; casi siempre ESC/POS)
        String devName = getDeviceName(key);
        String p = proto;
        if (p == null || p.isEmpty() || "auto".equals(p)) {
            p = BluetoothPrinter.isZebraPrinter(devName) ? "cpcl" : "escpos";
        }

        // Buscar interface con endpoint BULK OUT
        UsbInterface intf = null;
        UsbEndpoint epOut = null;
        for (int i = 0; i < device.getInterfaceCount() && epOut == null; i++) {
            UsbInterface cand = device.getInterface(i);
            for (int e = 0; e < cand.getEndpointCount(); e++) {
                UsbEndpoint ep = cand.getEndpoint(e);
                if (ep.getType() == UsbConstants.USB_ENDPOINT_XFER_BULK
                        && ep.getDirection() == UsbConstants.USB_DIR_OUT) {
                    intf = cand; epOut = ep; break;
                }
            }
        }
        if (intf == null || epOut == null) { lastError = "Sin endpoint BULK OUT"; return false; }

        UsbDeviceConnection conn = null;
        try {
            conn = usbManager.openDevice(device);
            if (conn == null) { lastError = "No se pudo abrir el device USB"; return false; }
            if (!conn.claimInterface(intf, true)) { lastError = "No se pudo reclamar la interface"; return false; }

            byte[] payload;
            if ("cpcl".equals(p)) {
                payload = BluetoothPrinter.renderTextoComoCpcl(text, devName);
            } else if ("zpl".equals(p)) {
                payload = BluetoothPrinter.renderTextoComoZpl(text);
            } else {
                // ESC/POS: reset (ESC @) + texto + feed + cut (GS V 0), igual que la ruta BT
                byte[] body = text.getBytes("UTF-8");
                byte[] head = new byte[]{0x1B, 0x40};
                byte[] tail = new byte[]{0x0A, 0x0A, 0x0A, 0x0A, 0x1D, 0x56, 0x00};
                payload = new byte[head.length + body.length + tail.length];
                System.arraycopy(head, 0, payload, 0, head.length);
                System.arraycopy(body, 0, payload, head.length, body.length);
                System.arraycopy(tail, 0, payload, head.length + body.length, tail.length);
            }

            PrintService.logEvent("USB proto=" + p + ", " + payload.length + " bytes, ep=0x"
                + Integer.toHexString(epOut.getAddress()));

            // Enviar en chunks al endpoint BULK OUT
            final int CHUNK = 4096;
            int offset = 0;
            while (offset < payload.length) {
                int len = Math.min(CHUNK, payload.length - offset);
                byte[] buf = new byte[len];
                System.arraycopy(payload, offset, buf, 0, len);
                int sent = conn.bulkTransfer(epOut, buf, len, 5000);
                if (sent < 0) { lastError = "bulkTransfer falló en offset " + offset; return false; }
                offset += (sent > 0 ? sent : len);
            }

            PrintService.logEvent("USB enviado " + payload.length + " bytes OK");
            Log.i(TAG, "Impreso USB " + key + " (" + devName + ") " + payload.length + " bytes [" + p + "]");
            return true;

        } catch (Exception e) {
            lastError = "Error USB: " + e.getClass().getSimpleName() + " - " + e.getMessage();
            Log.e(TAG, lastError, e);
            return false;
        } finally {
            if (conn != null) {
                try { conn.releaseInterface(intf); } catch (Exception ignored) {}
                try { conn.close(); } catch (Exception ignored) {}
            }
        }
    }

    /**
     * Envia bytes ya armados al endpoint BULK OUT, sin interpretarlos.
     * Ruta de la cola: el contenido lo formatea EscPos y no debe pasar por ninguna
     * conversion de texto (UTF-8 corromperia todo byte > 0x7F).
     */
    public boolean printBytes(String key, byte[] payload) {
        lastError = "";
        if (usbManager == null) { lastError = "USB no soportado en este equipo"; return false; }
        if (payload == null || payload.length == 0) { lastError = "Contenido vacio"; return false; }

        UsbDevice device = findByKey(key);
        if (device == null) { lastError = "USB desconectada: " + key; return false; }

        if (!usbManager.hasPermission(device)) {
            lastError = "Sin permiso USB - abri la app y toca Permitir";
            requestPermission(key);
            return false;
        }

        UsbInterface intf = null;
        UsbEndpoint epOut = null;
        for (int i = 0; i < device.getInterfaceCount() && epOut == null; i++) {
            UsbInterface cand = device.getInterface(i);
            for (int e = 0; e < cand.getEndpointCount(); e++) {
                UsbEndpoint ep = cand.getEndpoint(e);
                if (ep.getType() == UsbConstants.USB_ENDPOINT_XFER_BULK
                        && ep.getDirection() == UsbConstants.USB_DIR_OUT) {
                    intf = cand; epOut = ep; break;
                }
            }
        }
        if (intf == null || epOut == null) { lastError = "Sin endpoint BULK OUT"; return false; }

        UsbDeviceConnection conn = null;
        try {
            conn = usbManager.openDevice(device);
            if (conn == null) { lastError = "No se pudo abrir el device USB"; return false; }
            if (!conn.claimInterface(intf, true)) { lastError = "No se pudo reclamar la interface"; return false; }

            final int CHUNK = 4096;
            int offset = 0;
            while (offset < payload.length) {
                int len = Math.min(CHUNK, payload.length - offset);
                byte[] buf = new byte[len];
                System.arraycopy(payload, offset, buf, 0, len);
                int sent = conn.bulkTransfer(epOut, buf, len, 5000);
                if (sent < 0) { lastError = "bulkTransfer fallo en offset " + offset; return false; }
                offset += (sent > 0 ? sent : len);
            }
            PrintService.logEvent("USB bytes enviados: " + payload.length);
            Log.i(TAG, "Impreso USB (bytes) " + key + " " + payload.length + " bytes");
            return true;

        } catch (Exception e) {
            lastError = "Error USB: " + e.getClass().getSimpleName() + " - " + e.getMessage();
            Log.e(TAG, lastError, e);
            return false;
        } finally {
            if (conn != null) {
                try { conn.releaseInterface(intf); } catch (Exception ignored) {}
                try { conn.close(); } catch (Exception ignored) {}
            }
        }
    }
}
