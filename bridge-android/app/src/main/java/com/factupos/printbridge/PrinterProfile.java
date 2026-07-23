package com.factupos.printbridge;

import org.json.JSONObject;

import java.util.UUID;

/**
 * PrinterProfile - Perfil de una impresora configurada.
 *
 * Cada perfil representa UNA impresora y UNA cola del servidor de impresión.
 * Reemplaza al modelo escalar anterior (active_type / active_address), que solo
 * permitía una impresora activa a la vez.
 *
 * Los nombres de campo siguen los del config.json del cliente Python
 * (Windows/Linux) para que las tres plataformas se lean igual; transport/address
 * reemplazan a windowsPrinter/virtualPort.
 */
public class PrinterProfile {

    // Transportes soportados
    public static final String TRANSPORT_BLUETOOTH = "bluetooth";
    public static final String TRANSPORT_USB       = "usb";
    public static final String TRANSPORT_IP        = "ip";
    public static final String TRANSPORT_SERIAL    = "serial";
    public static final String TRANSPORT_SUNMI     = "sunmi";

    // Modo Bluetooth (solo si transport == bluetooth)
    public static final String BT_MODE_AUTO    = "auto";
    public static final String BT_MODE_CLASSIC = "classic";
    public static final String BT_MODE_BLE     = "ble";

    // Qué hacer con el contenido que llega de la cola
    public static final String PRINT_MODE_AUTO = "auto";
    public static final String PRINT_MODE_RAW  = "raw";
    public static final String PRINT_MODE_POS  = "pos";

    public static final int DEFAULT_IP_PORT = 9100;

    /** Identificador interno estable del perfil (no se muestra al usuario). */
    public String id = UUID.randomUUID().toString();

    /** Etiqueta libre: "Caja 1", "Cocina". */
    public String nombre = "";

    /** Cola del servidor que atiende este perfil. SIEMPRE normalizada (sin ceros a la izquierda). */
    public String queueCode = "";

    /** Empresa (tenant) de la que recibe trabajos. */
    public String empresa = "";

    /** bluetooth | usb | ip | serial | sunmi */
    public String transport = TRANSPORT_BLUETOOTH;

    /**
     * Dirección según transporte:
     *   bluetooth -> MAC
     *   usb       -> "VID:PID"
     *   serial    -> "/dev/ttyS*" o "VID:PID"
     *   ip        -> no se usa (ver host/port)
     *   sunmi     -> no se usa
     */
    public String address = "";

    /** Solo transport == ip */
    public String host = "";
    public int port = DEFAULT_IP_PORT;

    /** Solo transport == bluetooth: auto | classic | ble */
    public String btMode = BT_MODE_AUTO;

    /** Solo transport == serial */
    public int baud = SerialPrinter.DEFAULT_BAUD;

    /** Lenguaje del hardware: auto | escpos | cpcl | zpl */
    public String protocol = PrinterManager.PROTOCOL_AUTO;

    /** Qué hacer con el contenido: auto | raw | pos */
    public String printMode = PRINT_MODE_AUTO;

    /** Fuente ESC/POS: "A" (normal) o "B" (condensada) */
    public String escposFont = "A";

    public boolean cutPaper   = true;
    public boolean openDrawer = false;
    public boolean isThermal  = true;

    public PrinterProfile() {
    }

    /**
     * Normaliza el código de cola igual que el servidor (server.js normalizeQueue):
     * quita ceros a la izquierda, dejando al menos un dígito. "00301" -> "301", "000" -> "0".
     *
     * CRÍTICO: el servidor envía el job con la cola ya normalizada. Si el perfil se
     * guarda con ceros a la izquierda, el job entrante nunca matchea.
     */
    public static String normalizeQueue(String queue) {
        if (queue == null) return "";
        String q = queue.trim();
        if (q.isEmpty()) return "";
        int i = 0;
        while (i < q.length() - 1 && q.charAt(i) == '0') {
            i++;
        }
        return q.substring(i);
    }

    /** Aplica la normalización al campo queueCode. */
    public void normalize() {
        this.queueCode = normalizeQueue(this.queueCode);
        this.empresa   = this.empresa != null ? this.empresa.trim().toLowerCase() : "";
        if (this.port <= 0) this.port = DEFAULT_IP_PORT;
    }

    /** Nombre a mostrar: la etiqueta del usuario, o un fallback derivado del transporte. */
    public String getDisplayName() {
        if (nombre != null && !nombre.trim().isEmpty()) return nombre.trim();
        if (TRANSPORT_IP.equals(transport)) return host + ":" + port;
        if (TRANSPORT_SUNMI.equals(transport)) return "SUNMI Interna";
        return address != null && !address.isEmpty() ? address : transport;
    }

    /**
     * Clave de dispositivo usada para resolver protocolo/baud.
     * Para IP no hay dirección de hardware, así que se usa host:port.
     */
    public String getDeviceKey() {
        if (TRANSPORT_IP.equals(transport)) return host + ":" + port;
        return address != null ? address : "";
    }

    /** ¿Tiene lo mínimo para poder imprimir? */
    public boolean isComplete() {
        if (queueCode == null || queueCode.isEmpty()) return false;
        if (transport == null || transport.isEmpty()) return false;
        if (TRANSPORT_IP.equals(transport)) {
            return host != null && !host.trim().isEmpty() && port > 0;
        }
        if (TRANSPORT_SUNMI.equals(transport)) {
            return true;
        }
        return address != null && !address.trim().isEmpty();
    }

    public JSONObject toJson() throws Exception {
        JSONObject o = new JSONObject();
        o.put("id", id);
        o.put("nombre", nombre);
        o.put("queueCode", queueCode);
        o.put("empresa", empresa);
        o.put("transport", transport);
        o.put("address", address);
        o.put("host", host);
        o.put("port", port);
        o.put("btMode", btMode);
        o.put("baud", baud);
        o.put("protocol", protocol);
        o.put("printMode", printMode);
        o.put("escposFont", escposFont);
        o.put("cutPaper", cutPaper);
        o.put("openDrawer", openDrawer);
        o.put("isThermal", isThermal);
        return o;
    }

    public static PrinterProfile fromJson(JSONObject o) {
        PrinterProfile p = new PrinterProfile();
        if (o == null) return p;
        p.id         = o.optString("id", p.id);
        p.nombre     = o.optString("nombre", "");
        p.queueCode  = o.optString("queueCode", "");
        p.empresa    = o.optString("empresa", "");
        p.transport  = o.optString("transport", TRANSPORT_BLUETOOTH);
        p.address    = o.optString("address", "");
        p.host       = o.optString("host", "");
        p.port       = o.optInt("port", DEFAULT_IP_PORT);
        p.btMode     = o.optString("btMode", BT_MODE_AUTO);
        p.baud       = o.optInt("baud", SerialPrinter.DEFAULT_BAUD);
        p.protocol   = o.optString("protocol", PrinterManager.PROTOCOL_AUTO);
        p.printMode  = o.optString("printMode", PRINT_MODE_AUTO);
        p.escposFont = o.optString("escposFont", "A");
        p.cutPaper   = o.optBoolean("cutPaper", true);
        p.openDrawer = o.optBoolean("openDrawer", false);
        p.isThermal  = o.optBoolean("isThermal", true);
        p.normalize();
        return p;
    }
}
