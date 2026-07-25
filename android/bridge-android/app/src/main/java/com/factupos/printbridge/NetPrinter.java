package com.factupos.printbridge;

import android.util.Log;

import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;

/**
 * NetPrinter - Impresión por red (JetDirect / RAW socket, puerto 9100).
 *
 * Es el transporte de las impresoras conectadas por cable de red, que no dependen
 * de ninguna tablet en particular: cualquier equipo con acceso a la LAN puede
 * imprimir en ellas.
 *
 * A diferencia de BT/USB no hay emparejado ni permisos: se abre un socket TCP,
 * se escriben los bytes y se cierra.
 */
public class NetPrinter {

    private static final String TAG = "NetPrinter";

    public static final int DEFAULT_PORT = 9100;

    /** Timeout para establecer la conexión TCP. */
    private static final int CONNECT_TIMEOUT_MS = 5000;
    /** Timeout de escritura del socket. */
    private static final int SO_TIMEOUT_MS = 10000;
    /**
     * Tope duro de toda la operación. Una impresora de red puede aceptar la conexión
     * y después quedarse colgada; sin este tope el trabajo bloquearía al hilo que
     * lo despacha, y con la cola eso significa frenar todos los demás trabajos.
     */
    private static final int OVERALL_TIMEOUT_MS = 20000;

    private volatile String lastError = "";

    public String getLastError() { return lastError; }

    /**
     * Imprime en una impresora de red.
     *
     * @param host    IP o nombre del equipo
     * @param port    puerto (<=0 usa DEFAULT_PORT)
     * @param text    contenido
     * @param proto   auto|escpos|cpcl|zpl
     * @param devName nombre para la detección "auto" del protocolo (puede ir vacío)
     */
    public boolean printText(String host, int port, String text, String proto, String devName) {
        final byte[] payload;
        try {
            payload = buildPayload(text, proto, devName);
        } catch (Exception e) {
            lastError = "No se pudo armar el payload: " + e.getMessage();
            Log.e(TAG, lastError);
            return false;
        }
        return printBytes(host, port, payload);
    }

    /**
     * Envía bytes ya armados, sin interpretarlos.
     * Es la ruta que usa la cola: el contenido viene formateado por EscPos y no debe
     * pasar por ninguna conversión de texto.
     */
    public boolean printBytes(String host, int port, byte[] payloadIn) {
        lastError = "";

        if (host == null || host.trim().isEmpty()) {
            lastError = "Host vacío";
            Log.e(TAG, lastError);
            return false;
        }
        if (payloadIn == null || payloadIn.length == 0) {
            lastError = "Contenido vacío";
            return false;
        }
        final String h = host.trim();
        final int p = port > 0 ? port : DEFAULT_PORT;
        final byte[] payload = payloadIn;

        // Se ejecuta en un hilo propio para poder imponer OVERALL_TIMEOUT_MS y para
        // no depender de que el llamador ya esté fuera del hilo de UI.
        final boolean[] ok = new boolean[]{false};
        Thread worker = new Thread(new Runnable() {
            @Override
            public void run() {
                Socket socket = null;
                try {
                    socket = new Socket();
                    socket.connect(new InetSocketAddress(h, p), CONNECT_TIMEOUT_MS);
                    socket.setSoTimeout(SO_TIMEOUT_MS);
                    OutputStream out = socket.getOutputStream();
                    out.write(payload);
                    out.flush();
                    ok[0] = true;
                    Log.i(TAG, "Impreso en " + h + ":" + p + " (" + payload.length + " bytes)");
                } catch (Exception e) {
                    lastError = e.getClass().getSimpleName()
                              + (e.getMessage() != null ? ": " + e.getMessage() : "");
                    Log.e(TAG, "Error imprimiendo en " + h + ":" + p + " → " + lastError);
                } finally {
                    if (socket != null) {
                        try { socket.close(); } catch (Exception ignored) {}
                    }
                }
            }
        }, "NetPrinter-" + h);

        worker.start();
        try {
            worker.join(OVERALL_TIMEOUT_MS);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            lastError = "Interrumpido";
            return false;
        }

        if (worker.isAlive()) {
            // El hilo quedó colgado en el socket; se lo abandona (el timeout del socket
            // lo terminará) y se reporta el fallo para que la cola pueda reintentar.
            worker.interrupt();
            lastError = "Timeout de " + (OVERALL_TIMEOUT_MS / 1000) + "s contra " + h + ":" + p;
            Log.e(TAG, lastError);
            return false;
        }

        return ok[0];
    }

    /**
     * Prueba si la impresora responde en el puerto, sin imprimir nada.
     * Se usa desde la pantalla de configuración para validar antes de guardar.
     */
    public boolean testConnection(String host, int port) {
        lastError = "";
        if (host == null || host.trim().isEmpty()) {
            lastError = "Host vacío";
            return false;
        }
        Socket socket = null;
        try {
            socket = new Socket();
            socket.connect(new InetSocketAddress(host.trim(), port > 0 ? port : DEFAULT_PORT),
                           CONNECT_TIMEOUT_MS);
            return true;
        } catch (Exception e) {
            lastError = e.getClass().getSimpleName()
                      + (e.getMessage() != null ? ": " + e.getMessage() : "");
            return false;
        } finally {
            if (socket != null) {
                try { socket.close(); } catch (Exception ignored) {}
            }
        }
    }

    /**
     * Arma el payload según protocolo (reusa los renderers de BluetoothPrinter).
     *
     * NOTA: es la misma lógica que SerialPrinter.buildPayload y la de UsbPrinter.
     * Son tres copias; la fase 4 (formateo ESC/POS) las unifica al portar el
     * formateo del cliente Python.
     */
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
}
