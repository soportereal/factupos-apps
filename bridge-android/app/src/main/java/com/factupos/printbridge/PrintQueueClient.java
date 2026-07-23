package com.factupos.printbridge;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;
import android.util.Log;

import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.URI;
import java.util.ArrayList;
import java.util.List;

/**
 * PrintQueueClient - Cliente del servidor de colas (WebSocket, puerto 9300).
 *
 * Reemplaza al modelo del Bridge, donde el navegador de la propia tablet empujaba
 * el trabajo por HTTP local. Acá la app JALA los trabajos de la cola central, así
 * que puede imprimir lo que factura cualquier otro equipo.
 *
 * Flujo:
 *   conectar -> register(colas de los perfiles) -> recibir print -> encolar local
 *   -> ACK inmediato -> imprimir en segundo plano con reintentos
 *
 * El ACK se manda apenas el trabajo queda guardado en la cola local, NO cuando se
 * imprimió. Es deliberado: el servidor da 15 s y no reintenta, así que la app se
 * hace dueña del trabajo lo antes posible y después se ocupa de que salga.
 */
public class PrintQueueClient {

    private static final String TAG = "PrintQueueClient";

    private static final String PREFS_NAME = "queue_prefs";
    private static final String KEY_SERVERS   = "servers";
    private static final String KEY_CLIENT_ID = "client_id";
    private static final String KEY_ENABLED   = "enabled";

    /**
     * Servidores por defecto. La IP interna va PRIMERO: la red de las tablets es interna
     * y estable, y las tablets suelen resolver `print.factupos.com` por DNS público (IP
     * pública con el 9300 cerrado) → no conectaban. Con la IP directa conectan sin depender
     * del DNS. El nombre queda de respaldo por si una tablet sale de la red interna.
     */
    public static final String[] DEFAULT_SERVERS = {
        "ws://192.168.7.17:9300",
        "ws://print.factupos.com:9300"
    };

    private static final long RECONNECT_BASE_MS = 5000L;
    private static final long RECONNECT_MAX_MS  = 60000L;
    /** Cada cuánto revisa la cola local el worker de impresión. */
    private static final long WORKER_POLL_MS = 1000L;

    private final Context context;
    private final PrinterManager printerManager;
    private final PrinterProfileStore profileStore;
    private final JobQueue queue;

    private volatile WebSocketClient ws;
    private volatile boolean running = false;
    private volatile int serverIndex = 0;
    private volatile int reconnectAttempts = 0;
    private volatile String estado = "Detenido";
    private volatile String ultimoError = "";

    // Contadores y log en vivo para la pantalla de inicio (espejo del cliente
    // de escritorio). El log del 8765 (PrintService.sLogBuffer) es del camino
    // viejo; este es el del canal WebSocket.
    private volatile int impresos = 0;
    private volatile int errores = 0;
    private static final int LOG_MAX = 200;
    private final java.util.ArrayDeque<String> logLines = new java.util.ArrayDeque<>();
    private final java.text.SimpleDateFormat logFmt =
        new java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US);

    private synchronized void log(String linea) {
        logLines.addLast(logFmt.format(new java.util.Date()) + " " + linea);
        while (logLines.size() > LOG_MAX) logLines.removeFirst();
    }

    public int getImpresos() { return impresos; }
    public int getErrores()  { return errores; }

    /** URL del servidor actualmente en uso (o el primero configurado). */
    public String getServerUrl() {
        List<String> s = getServers();
        if (s.isEmpty()) return "";
        return s.get(Math.min(serverIndex, s.size() - 1));
    }

    public synchronized String getLogText() {
        if (logLines.isEmpty()) return "(esperando trabajos...)";
        StringBuilder sb = new StringBuilder();
        for (String l : logLines) sb.append(l).append('\n');
        return sb.toString();
    }

    private Thread workerThread;
    private Thread supervisorThread;

    public PrintQueueClient(Context context, PrinterManager printerManager) {
        this.context = context.getApplicationContext();
        this.printerManager = printerManager;
        this.profileStore = printerManager != null
            ? printerManager.getProfileStore()
            : new PrinterProfileStore(context);
        this.queue = new JobQueue(context);
    }

    // ------------------------------------------------------------------
    // Configuración
    // ------------------------------------------------------------------

    private SharedPreferences prefs() {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public List<String> getServers() {
        List<String> out = new ArrayList<String>();
        String raw = prefs().getString(KEY_SERVERS, "");
        if (raw != null && !raw.isEmpty()) {
            String[] parts = raw.split("\\s*,\\s*");
            for (int i = 0; i < parts.length; i++) {
                String s = parts[i].trim();
                if (!s.isEmpty()) out.add(s);
            }
        }
        if (out.isEmpty()) {
            for (int i = 0; i < DEFAULT_SERVERS.length; i++) out.add(DEFAULT_SERVERS[i]);
        }
        return out;
    }

    public void setServers(String csv) {
        prefs().edit().putString(KEY_SERVERS, csv != null ? csv.trim() : "").apply();
    }

    public String getClientId() {
        String id = prefs().getString(KEY_CLIENT_ID, "");
        if (id == null || id.trim().isEmpty()) {
            id = android.os.Build.MODEL != null ? android.os.Build.MODEL : "android";
            id = id.replaceAll("[^A-Za-z0-9_-]", "");
            if (id.isEmpty()) id = "android";
        }
        return id;
    }

    public void setClientId(String id) {
        prefs().edit().putString(KEY_CLIENT_ID, id != null ? id.trim() : "").apply();
    }

    /**
     * Recibir trabajos por WebSocket. Por decisión del dueño arranca PRENDIDO por
     * defecto: una tablet recién configurada recibe sin tener que marcar nada. Igual
     * no hace nada hasta que haya una impresora con cola (start() sale si no hay perfil
     * usable), así que una tablet sin configurar no cambia de comportamiento.
     */
    public boolean isEnabled() {
        return prefs().getBoolean(KEY_ENABLED, true);
    }

    public void setEnabled(boolean enabled) {
        prefs().edit().putBoolean(KEY_ENABLED, enabled).apply();
    }

    public String getEstado()      { return estado; }
    public String getUltimoError() { return ultimoError; }
    public JobQueue getQueue()     { return queue; }
    public boolean isConnected()   { return ws != null && ws.isOpen(); }

    // ------------------------------------------------------------------
    // Ciclo de vida
    // ------------------------------------------------------------------

    public synchronized void start() {
        if (running) return;
        if (!profileStore.hasUsableProfile()) {
            estado = "Sin impresoras configuradas";
            Log.w(TAG, estado + "; no se conecta a la cola.");
            return;
        }
        running = true;
        reconnectAttempts = 0;
        estado = "Conectando...";

        supervisorThread = new Thread(this::supervisorLoop, "PQC-supervisor");
        supervisorThread.setDaemon(true);
        supervisorThread.start();

        workerThread = new Thread(this::workerLoop, "PQC-worker");
        workerThread.setDaemon(true);
        workerThread.start();

        Log.i(TAG, "Cliente de cola iniciado (clientId=" + getClientId() + ")");
    }

    public synchronized void stop() {
        running = false;
        estado = "Detenido";
        cerrarSocket();
        if (supervisorThread != null) supervisorThread.interrupt();
        if (workerThread != null) workerThread.interrupt();
        Log.i(TAG, "Cliente de cola detenido");
    }

    private void cerrarSocket() {
        WebSocketClient c = ws;
        ws = null;
        if (c != null) {
            try { c.close(); } catch (Exception ignored) {}
        }
    }

    /**
     * Reacciona a un cambio de perfiles. Si ya está conectado, reenvía el register con
     * la lista actualizada. Si está PRENDIDO pero aún no corría (típico: recién se agregó
     * la primera impresora y al abrir la app no había ninguna), lo arranca — así no hay
     * que reiniciar la app ni tocar el toggle.
     */
    public void reregistrar() {
        if (running) {
            if (ws != null && ws.isOpen()) enviarRegister();
        } else if (isEnabled() && profileStore.hasUsableProfile()) {
            start();
        }
    }

    // ------------------------------------------------------------------
    // Conexión
    // ------------------------------------------------------------------

    private void supervisorLoop() {
        while (running) {
            try {
                if (ws == null || (!ws.isOpen() && !isConnecting())) {
                    conectar();
                }
                Thread.sleep(2000);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            } catch (Exception e) {
                Log.e(TAG, "Supervisor: " + e.getMessage());
                try { Thread.sleep(2000); } catch (InterruptedException ie) { return; }
            }
        }
    }

    private boolean isConnecting() {
        WebSocketClient c = ws;
        try {
            return c != null && c.getReadyState() == org.java_websocket.enums.ReadyState.NOT_YET_CONNECTED;
        } catch (Exception e) {
            return false;
        }
    }

    private void conectar() {
        List<String> servers = getServers();
        if (servers.isEmpty()) {
            estado = "Sin servidores configurados";
            return;
        }
        // Espera con backoff antes de reintentar, para no martillar el servidor
        // cuando la tablet quedó sin red.
        if (reconnectAttempts > 0) {
            long espera = Math.min(RECONNECT_BASE_MS * reconnectAttempts, RECONNECT_MAX_MS);
            try { Thread.sleep(espera); } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
            if (!running) return;
        }

        final String url = servers.get(serverIndex % servers.size());
        estado = "Conectando a " + url;
        Log.i(TAG, estado);

        try {
            cerrarSocket();
            WebSocketClient c = new WebSocketClient(new URI(url)) {
                @Override public void onOpen(ServerHandshake hs) {
                    reconnectAttempts = 0;
                    estado = "Conectado a " + url;
                    log("Conectado a " + url);
                    Log.i(TAG, estado);
                    enviarRegister();
                }
                @Override public void onMessage(String message) {
                    procesarMensaje(message);
                }
                @Override public void onClose(int code, String reason, boolean remote) {
                    estado = "Desconectado (" + code + ")";
                    log("Desconectado (" + code + ")");
                    Log.w(TAG, estado + " " + reason);
                    // Rotar al siguiente servidor: si este esta caido, probar el otro.
                    serverIndex++;
                    reconnectAttempts++;
                }
                @Override public void onError(Exception ex) {
                    ultimoError = ex != null && ex.getMessage() != null
                        ? ex.getMessage() : "error de conexion";
                    Log.e(TAG, "WS error: " + ultimoError);
                }
            };
            ws = c;
            c.connect();
        } catch (Exception e) {
            ultimoError = e.getMessage() != null ? e.getMessage() : e.toString();
            estado = "Error: " + ultimoError;
            Log.e(TAG, "No se pudo conectar a " + url + ": " + ultimoError);
            serverIndex++;
            reconnectAttempts++;
        }
    }

    private void enviarRegister() {
        try {
            JSONArray colas = profileStore.getQueuesJSON();
            if (colas.length() == 0) {
                Log.w(TAG, "No hay colas para registrar; revisá los perfiles.");
                return;
            }
            JSONObject msg = new JSONObject();
            msg.put("action", "register");
            msg.put("queues", colas);
            msg.put("clientId", getClientId());
            msg.put("clientVersion", BuildConfig.VERSION_NAME);
            msg.put("plataforma", "android");
            msg.put("token", "");
            enviar(msg.toString());
            Log.i(TAG, "register enviado con " + colas.length() + " cola(s)");
        } catch (Exception e) {
            Log.e(TAG, "No se pudo enviar register: " + e.getMessage());
        }
    }

    private void enviar(String texto) {
        WebSocketClient c = ws;
        if (c == null || !c.isOpen()) return;
        try {
            c.send(texto);
        } catch (Exception e) {
            Log.e(TAG, "No se pudo enviar: " + e.getMessage());
        }
    }

    // ------------------------------------------------------------------
    // Mensajes entrantes
    // ------------------------------------------------------------------

    private void procesarMensaje(String message) {
        try {
            JSONObject msg = new JSONObject(message);
            String action = msg.optString("action", "");

            if ("print".equals(action)) {
                recibirTrabajo(msg);
                return;
            }
            if ("registered".equals(action)) {
                String latest = msg.optString("latestVersion", "");
                estado = "Registrado";
                Log.i(TAG, "Registrado en la cola"
                    + (latest.isEmpty() ? "" : " (ultima version publicada: " + latest + ")"));
                return;
            }
            if ("ack_received".equals(action)) {
                return; // informativo
            }
            if (!msg.optBoolean("ok", true)) {
                ultimoError = msg.optString("error", "error del servidor");
                Log.e(TAG, "Servidor: " + ultimoError);
            }
        } catch (Exception e) {
            Log.e(TAG, "Mensaje ilegible: " + e.getMessage());
        }
    }

    /**
     * Recibe un trabajo: lo guarda en la cola local y ACKea de inmediato.
     * A partir del ACK el servidor lo borra, así que la responsabilidad es nuestra.
     */
    private void recibirTrabajo(JSONObject msg) {
        String jobId = msg.optString("jobId", "");
        if (jobId.isEmpty()) {
            Log.e(TAG, "Trabajo sin jobId, se ignora");
            return;
        }
        try {
            JobQueue.Job job = new JobQueue.Job();
            job.jobId   = jobId;
            job.queue   = PrinterProfile.normalizeQueue(msg.optString("queue", ""));
            job.empresa = msg.optString("empresa", "");
            job.data    = msg.optString("data", "");
            job.format  = msg.optString("format", "");

            boolean nuevo = queue.enqueue(job, System.currentTimeMillis());
            ackear(jobId, true, null);

            if (nuevo) {
                log("Job " + jobId.substring(0, Math.min(8, jobId.length()))
                    + " recibido → cola " + job.queue
                    + (job.empresa.isEmpty() ? "" : " [" + job.empresa + "]"));
                Log.i(TAG, "Trabajo encolado " + jobId + " cola=" + job.queue
                         + " (" + queue.size() + " en cola)");
            }
        } catch (Exception e) {
            // Si no se pudo ni encolar, se ackea con error para que quede el rastro
            // del lado del servidor en vez de morir como timeout mudo.
            Log.e(TAG, "No se pudo encolar " + jobId + ": " + e.getMessage());
            ackear(jobId, false, e.getMessage());
        }
    }

    private void ackear(String jobId, boolean ok, String error) {
        try {
            JSONObject ack = new JSONObject();
            ack.put("action", "ack");
            ack.put("jobId", jobId);
            ack.put("status", ok ? "ok" : "error");
            if (!ok && error != null) ack.put("error", error);
            enviar(ack.toString());
        } catch (Exception e) {
            Log.e(TAG, "No se pudo ackear " + jobId + ": " + e.getMessage());
        }
    }

    // ------------------------------------------------------------------
    // Worker de impresión
    // ------------------------------------------------------------------

    private void workerLoop() {
        while (running) {
            try {
                long now = System.currentTimeMillis();
                JobQueue.Job job = queue.nextReady(now);
                if (job == null) {
                    Thread.sleep(WORKER_POLL_MS);
                    continue;
                }
                imprimirTrabajo(job, now);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            } catch (Exception e) {
                Log.e(TAG, "Worker: " + e.getMessage());
                try { Thread.sleep(WORKER_POLL_MS); } catch (InterruptedException ie) { return; }
            }
        }
    }

    private void imprimirTrabajo(JobQueue.Job job, long now) {
        PrinterProfile perfil = profileStore.findByQueue(job.queue, job.empresa);
        if (perfil == null) {
            // No hay perfil para esta cola. Reintentar no sirve de nada hasta que el
            // usuario configure la impresora, pero tampoco se descarta enseguida:
            // puede estar a mitad de configuracion.
            queue.markFailed(job.jobId, "cola " + job.queue + " sin impresora configurada", now);
            Log.e(TAG, "Cola no mapeada: " + job.queue
                     + (job.empresa.isEmpty() ? "" : " / " + job.empresa));
            return;
        }

        byte[] bytes;
        try {
            bytes = Base64.decode(job.data, Base64.DEFAULT);
        } catch (Exception e) {
            queue.remove(job.jobId);   // base64 roto: reintentar no lo va a arreglar
            Log.e(TAG, "Base64 invalido en " + job.jobId + ", se descarta");
            return;
        }

        boolean ok = printerManager.printBytes(perfil, bytes);

        String jobCorto = job.jobId.substring(0, Math.min(8, job.jobId.length()));
        if (ok) {
            queue.remove(job.jobId);
            impresos++;
            log("Job " + jobCorto + " → " + perfil.getDisplayName() + " OK");
            Log.i(TAG, "Impreso " + job.jobId + " en " + perfil.getDisplayName()
                     + " (" + queue.size() + " pendientes)");
        } else {
            String err = detalleError(perfil);
            boolean sigue = queue.markFailed(job.jobId, err, now);
            errores++;
            log("Job " + jobCorto + " → ERROR: " + err + (sigue ? " (reintenta)" : " (descartado)"));
            Log.e(TAG, "Fallo " + job.jobId + " en " + perfil.getDisplayName() + ": " + err
                     + (sigue ? " (se reintenta)" : " (descartado)"));
        }
    }

    private String detalleError(PrinterProfile p) {
        try {
            if (PrinterProfile.TRANSPORT_IP.equals(p.transport)) {
                return printerManager.getNetPrinter().getLastError();
            }
            if (PrinterProfile.TRANSPORT_USB.equals(p.transport)) {
                return printerManager.getUsbPrinter().getLastError();
            }
            if (PrinterProfile.TRANSPORT_SERIAL.equals(p.transport)) {
                return printerManager.getSerialPrinter().getLastError();
            }
            if (PrinterProfile.TRANSPORT_BLUETOOTH.equals(p.transport)) {
                String spp = printerManager.getBluetoothPrinter().getLastError();
                return spp.isEmpty() ? "sin detalle" : spp;
            }
        } catch (Exception ignored) {}
        return "sin detalle";
    }
}
