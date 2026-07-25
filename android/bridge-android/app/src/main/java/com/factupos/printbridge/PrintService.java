package com.factupos.printbridge;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import androidx.core.app.NotificationCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.content.pm.ServiceInfo;

import java.io.IOException;
import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.Date;
import java.util.Deque;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

import fi.iki.elonen.NanoHTTPD;

/**
 * PrintService - Foreground Service con servidor HTTP NanoHTTPD
 *
 * Escucha en localhost:8765 y recibe comandos de impresion desde Chrome.
 * Endpoints:
 *   GET  /ping             -> {"ok":true,"printer":"...","activePrinter":{...}}
 *   POST /print            -> {"text":"..."} -> {"ok":true,"message":"Impreso"}
 *   GET  /status           -> {"ok":true,"connected":true,"paper":true}
 *   GET  /printers         -> Lista impresoras disponibles (SUNMI + BT + USB + Serial)
 *   POST /printer/select   -> {"type":"bluetooth|usb|serial","address":"...","baud":9600} seleccionar activa
 *   GET  /printer/active   -> Impresora activa actual
 *   GET/POST /printer/protocol -> protocolo (auto|escpos|cpcl|zpl) por device
 *   GET/POST /printer/baud -> baudrate serial por device
 *   POST /usb/permission   -> {"address":"vvvv:pppp"} pide permiso USB (usb/serial-usb)
 *   GET  /debug            -> Info debug del dispositivo (incluye usbDevices/serialDevices con VID:PID)
 */
public class PrintService extends Service {

    private static final String TAG = "SunmiPrintBridge";
    private static final int PORT = 8765;
    private static final String CHANNEL_ID = "sunmi_print_bridge";
    private static final int NOTIFICATION_ID = 1;

    private static volatile boolean sRunning = false;
    private HttpServer httpServer;
    private PowerManager.WakeLock wakeLock;

    // ──── Print Log ────────────────────────────────────────────
    // Buffer en memoria con los ultimos 3 prints (incluye trace completo
    // de eventos desde POST /print hasta cierre BT). Accesible via GET /log.
    private static final int LOG_BUFFER_SIZE = 2;
    private static final Deque<PrintLogEntry> sLogBuffer = new ArrayDeque<>();
    private static PrintLogEntry sCurrentLog = null;

    static class PrintLogEntry {
        String startedAt;
        long startedAtMs;
        StringBuilder events = new StringBuilder();
        String result = "(en curso)";
    }

    /** Inicia un nuevo bloque de log para un print. */
    public static synchronized void logStart() {
        sCurrentLog = new PrintLogEntry();
        sCurrentLog.startedAtMs = System.currentTimeMillis();
        sCurrentLog.startedAt = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US)
            .format(new Date(sCurrentLog.startedAtMs));
        sLogBuffer.addFirst(sCurrentLog);
        while (sLogBuffer.size() > LOG_BUFFER_SIZE) sLogBuffer.removeLast();
        logEvent("Print start");
    }

    /** Agrega un evento al log del print actual. */
    public static synchronized void logEvent(String msg) {
        if (sCurrentLog == null) return;
        long elapsed = System.currentTimeMillis() - sCurrentLog.startedAtMs;
        sCurrentLog.events.append(String.format(Locale.US, "[+%5dms] %s%n", elapsed, msg));
    }

    /** Cierra el log del print actual con un resultado. */
    public static synchronized void logEnd(String result) {
        if (sCurrentLog == null) return;
        long elapsed = System.currentTimeMillis() - sCurrentLog.startedAtMs;
        sCurrentLog.events.append(String.format(Locale.US, "[+%5dms] FIN: %s%n", elapsed, result));
        sCurrentLog.result = result;
        sCurrentLog = null;
    }

    /** Limpia el buffer de log. */
    public static synchronized void logClear() {
        sLogBuffer.clear();
        sCurrentLog = null;
    }

    /** Renderiza el buffer entero como texto plano. */
    public static synchronized String logRender() {
        if (sLogBuffer.isEmpty()) return "(sin prints todavia)\n";
        StringBuilder sb = new StringBuilder();
        for (PrintLogEntry e : sLogBuffer) {
            sb.append("=== Print at ").append(e.startedAt).append(" — ").append(e.result).append(" ===\n");
            sb.append(e.events);
            sb.append("\n");
        }
        return sb.toString();
    }
    private FactuposPrint sunmiPrinter;
    private PrinterManager printerManager;

    public static boolean isRunning() {
        return sRunning;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        sunmiPrinter = FactuposPrint.getInstance();
        sunmiPrinter.init(this);
        printerManager = new PrinterManager(this, sunmiPrinter);
        sPrinterManager = printerManager;

        queueClient = new PrintQueueClient(this, printerManager);
        sQueueClient = queueClient;

        // WakeLock parcial: mantiene la CPU activa para el foreground service.
        // Sin esto, Android/MIUI/EMUI suspenden el servicio cuando el telefono
        // entra en doze/idle y el puerto 8765 deja de responder.
        try {
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            if (pm != null) {
                wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,
                    "FactuposPrintBridge::ServiceWakeLock");
                wakeLock.setReferenceCounted(false);
                wakeLock.acquire();
                Log.i(TAG, "WakeLock adquirido");
            }
        } catch (Exception e) {
            Log.w(TAG, "No se pudo adquirir WakeLock", e);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        createNotificationChannel();
        startForeground(NOTIFICATION_ID, buildNotification());

        if (httpServer == null) {
            try {
                httpServer = new HttpServer(PORT);
                httpServer.start(NanoHTTPD.SOCKET_READ_TIMEOUT, false);
                sRunning = true;
                Log.i(TAG, "Servidor HTTP iniciado en puerto " + PORT);
            } catch (IOException e) {
                Log.e(TAG, "Error al iniciar servidor HTTP", e);
                sRunning = false;
            }
        }

        // Cliente de cola: solo arranca si la estacion ya fue configurada para
        // WebSocket. Las estaciones sin migrar siguen usando el HTTP local.
        if (queueClient != null && queueClient.isEnabled()) {
            queueClient.start();
        }

        // Re-adquirir WakeLock por si se perdio
        if (wakeLock != null && !wakeLock.isHeld()) {
            try { wakeLock.acquire(); } catch (Exception ignored) {}
        }

        // Si el sistema mata el servicio, reiniciarlo
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (wakeLock != null && wakeLock.isHeld()) {
            try { wakeLock.release(); } catch (Exception ignored) {}
        }
        if (queueClient != null) {
            queueClient.stop();
        }
        if (httpServer != null) {
            httpServer.stop();
            httpServer = null;
        }
        sRunning = false;
        sunmiPrinter.release();
        Log.i(TAG, "Servicio detenido");
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    /** Exponer PrinterManager para que MainActivity pueda usarlo */
    public PrinterManager getPrinterManager() {
        return printerManager;
    }

    /** Singleton para acceder al PrinterManager desde MainActivity */
    private static PrinterManager sPrinterManager;

    /** Cliente del servidor de colas (WebSocket 9300). */
    private PrintQueueClient queueClient;
    private static PrintQueueClient sQueueClient;

    public static PrintQueueClient getStaticQueueClient() {
        return sQueueClient;
    }

    public static PrinterManager getStaticPrinterManager() {
        return sPrinterManager;
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    "FactuPOS Print",
                    NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Servicio de puente de impresion");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }

    private Notification buildNotification() {
        Intent notificationIntent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(this, 0,
                notificationIntent, PendingIntent.FLAG_IMMUTABLE);

        String activeName = printerManager != null ? printerManager.getActiveName() : "Iniciando...";

        return new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("FactuPOS Print")
                .setContentText("Activa: " + activeName + " | localhost:" + PORT)
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentIntent(pendingIntent)
                .setOngoing(true)
                .build();
    }

    // =========================================================================
    // Servidor HTTP embebido (NanoHTTPD)
    // =========================================================================
    private class HttpServer extends NanoHTTPD {

        public HttpServer(int port) {
            super("0.0.0.0", port);
        }

        @Override
        public Response serve(IHTTPSession session) {
            String uri = session.getUri();
            Method method = session.getMethod();

            // CORS headers para todas las respuestas
            Response response;

            // Preflight OPTIONS
            if (Method.OPTIONS.equals(method)) {
                response = newFixedLengthResponse(Response.Status.OK, "text/plain", "");
                addCorsHeaders(response);
                return response;
            }

            try {
                switch (uri) {
                    case "/ping":
                        response = handlePing();
                        break;
                    case "/print":
                        response = handlePrint(session);
                        break;
                    case "/status":
                        response = handleStatus();
                        break;
                    case "/printers":
                        response = handlePrinters();
                        break;
                    case "/printer/select":
                        response = handlePrinterSelect(session);
                        break;
                    case "/printer/active":
                        response = handlePrinterActive();
                        break;
                    case "/printer/protocol":
                        response = (Method.POST.equals(method))
                            ? handleProtocolSet(session)
                            : handleProtocolGet(session);
                        break;
                    case "/printer/baud":
                        response = (Method.POST.equals(method))
                            ? handleBaudSet(session)
                            : handleBaudGet(session);
                        break;
                    case "/usb/permission":
                        response = handleUsbPermission(session);
                        break;
                    case "/log":
                        response = newFixedLengthResponse(Response.Status.OK,
                            "text/plain; charset=utf-8", logRender());
                        break;
                    case "/debug":
                        response = handleDebug();
                        break;
                    default:
                        JSONObject err = new JSONObject();
                        err.put("ok", false);
                        err.put("error", "Ruta no encontrada: " + uri);
                        response = newFixedLengthResponse(
                                Response.Status.NOT_FOUND,
                                "application/json",
                                err.toString()
                        );
                }
            } catch (Exception e) {
                Log.e(TAG, "Error procesando " + uri, e);
                try {
                    JSONObject err = new JSONObject();
                    err.put("ok", false);
                    err.put("error", e.getMessage());
                    response = newFixedLengthResponse(
                            Response.Status.INTERNAL_ERROR,
                            "application/json",
                            err.toString()
                    );
                } catch (Exception ex) {
                    response = newFixedLengthResponse(
                            Response.Status.INTERNAL_ERROR,
                            "text/plain",
                            "Error interno"
                    );
                }
            }

            addCorsHeaders(response);
            return response;
        }

        private void addCorsHeaders(Response response) {
            response.addHeader("Access-Control-Allow-Origin", "*");
            response.addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
            response.addHeader("Access-Control-Allow-Headers", "Content-Type");
            response.addHeader("Access-Control-Max-Age", "86400");
        }

        /**
         * GET /ping - Verificar que el puente esta activo
         */
        private Response handlePing() throws Exception {
            JSONObject json = new JSONObject();
            json.put("ok", true);
            json.put("printer", printerManager.getActiveName());
            json.put("status", printerManager.isActiveReady() ? "ready" : "not_ready");
            json.put("version", BuildConfig.VERSION_NAME);
            json.put("versionCode", BuildConfig.VERSION_CODE);
            json.put("buildDate", BuildConfig.BUILD_DATE);
            json.put("manufacturer", Build.MANUFACTURER);
            json.put("model", Build.MODEL);
            json.put("activePrinter", printerManager.getActiveJSON());

            // Protocolo configurado para la impresora activa (auto/escpos/cpcl/zpl)
            String activeAddr = printerManager.getActiveAddress();
            if (activeAddr != null && !activeAddr.isEmpty()) {
                json.put("protocol", printerManager.getProtocol(activeAddr));
            }

            return newFixedLengthResponse(
                    Response.Status.OK,
                    "application/json",
                    json.toString()
            );
        }

        /**
         * POST /print - Imprimir texto usando la impresora activa
         * Body: {"text": "contenido del tiquete..."}
         */
        private Response handlePrint(IHTTPSession session) throws Exception {
            logStart();
            logEvent("POST /print recibido");

            // Leer body del POST
            Map<String, String> bodyMap = new HashMap<>();
            session.parseBody(bodyMap);

            String bodyStr = bodyMap.get("postData");
            // NanoHTTPD a veces lee el body como ISO-8859-1 aunque el JSON sea UTF-8.
            if (bodyStr != null) {
                try {
                    byte[] raw = bodyStr.getBytes("ISO-8859-1");
                    String fixed = new String(raw, "UTF-8");
                    bodyStr = fixed;
                    logEvent("body re-decodificado UTF-8 (" + raw.length + " bytes)");
                } catch (Exception ignored) {}
            }
            if (bodyStr == null || bodyStr.isEmpty()) {
                JSONObject err = new JSONObject();
                err.put("ok", false);
                err.put("error", "Body vacio");
                return newFixedLengthResponse(
                        Response.Status.BAD_REQUEST,
                        "application/json",
                        err.toString()
                );
            }

            JSONObject body = new JSONObject(bodyStr);
            String texto = body.optString("text", "");

            if (texto.isEmpty()) {
                JSONObject err = new JSONObject();
                err.put("ok", false);
                err.put("error", "Campo 'text' vacio");
                return newFixedLengthResponse(
                        Response.Status.BAD_REQUEST,
                        "application/json",
                        err.toString()
                );
            }

            logEvent("texto extraido: " + texto.length() + " chars, " + (texto.split("\n").length) + " lineas");
            logEvent("impresora activa: " + printerManager.getActiveName() + " (" + printerManager.getActiveType() + ")");

            // Dump del contenido recibido linea por linea — el usuario ve
            // el formato real de la factura que llego al bridge
            logEvent("───── CONTENIDO RECIBIDO ─────");
            String[] lineas = texto.replace("\r\n", "\n").split("\n", -1);
            for (int i = 0; i < lineas.length; i++) {
                // Reemplazar bytes de control no imprimibles por punto para legibilidad
                StringBuilder vis = new StringBuilder();
                for (int j = 0; j < lineas[i].length(); j++) {
                    char c = lineas[i].charAt(j);
                    if (c < 0x20) vis.append('·');
                    else vis.append(c);
                }
                logEvent(String.format("L%02d (%2d): |%s|",
                    i + 1, lineas[i].length(), vis.toString()));
            }
            logEvent("───── FIN CONTENIDO ─────");

            // Imprimir via PrinterManager (usa la impresora activa)
            boolean ok = printerManager.printText(texto);

            logEnd(ok ? "OK" : "ERROR");

            JSONObject json = new JSONObject();
            json.put("ok", ok);
            json.put("message", ok ? "Impreso en " + printerManager.getActiveName() : "Error al imprimir");
            json.put("printer", printerManager.getActiveName());
            json.put("type", printerManager.getActiveType());

            return newFixedLengthResponse(
                    Response.Status.OK,
                    "application/json",
                    json.toString()
            );
        }

        /**
         * GET /status - Estado de la impresora activa
         */
        private Response handleStatus() throws Exception {
            JSONObject json = new JSONObject();
            json.put("ok", true);
            json.put("connected", printerManager.isActiveReady());
            json.put("printer", printerManager.getActiveName());
            json.put("type", printerManager.getActiveType());
            json.put("model", Build.MODEL);

            if ("sunmi".equals(printerManager.getActiveType())) {
                json.put("paper", sunmiPrinter.hasPaper());
            }

            return newFixedLengthResponse(
                    Response.Status.OK,
                    "application/json",
                    json.toString()
            );
        }

        /**
         * GET /printers - Lista todas las impresoras disponibles
         */
        private Response handlePrinters() throws Exception {
            JSONObject json = printerManager.getAvailablePrintersJSON();

            return newFixedLengthResponse(
                    Response.Status.OK,
                    "application/json",
                    json.toString()
            );
        }

        /**
         * POST /printer/select - Seleccionar impresora activa
         * Body: {"type":"bluetooth","address":"AA:BB:CC:DD:EE:FF"}
         *    o: {"type":"sunmi"}
         */
        private Response handlePrinterSelect(IHTTPSession session) throws Exception {
            Map<String, String> bodyMap = new HashMap<>();
            session.parseBody(bodyMap);

            String bodyStr = bodyMap.get("postData");
            if (bodyStr == null || bodyStr.isEmpty()) {
                JSONObject err = new JSONObject();
                err.put("ok", false);
                err.put("error", "Body vacio");
                return newFixedLengthResponse(
                        Response.Status.BAD_REQUEST,
                        "application/json",
                        err.toString()
                );
            }

            JSONObject body = new JSONObject(bodyStr);
            String type = body.optString("type", "");
            String address = body.optString("address", "");
            int baud = body.optInt("baud", 0);

            if (type.isEmpty()) {
                JSONObject err = new JSONObject();
                err.put("ok", false);
                err.put("error", "Campo 'type' requerido");
                return newFixedLengthResponse(
                        Response.Status.BAD_REQUEST,
                        "application/json",
                        err.toString()
                );
            }

            // sunmi no necesita address; el resto (bluetooth/usb/serial) sí
            if (!"sunmi".equals(type) && address.isEmpty()) {
                JSONObject err = new JSONObject();
                err.put("ok", false);
                err.put("error", "Campo 'address' requerido para tipo " + type);
                return newFixedLengthResponse(
                        Response.Status.BAD_REQUEST,
                        "application/json",
                        err.toString()
                );
            }

            // Baudrate opcional para serial
            if ("serial".equals(type) && baud > 0) {
                printerManager.setBaud(address, baud);
            }

            printerManager.setActive(type, address);

            // Actualizar notificación con nuevo nombre
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) {
                nm.notify(NOTIFICATION_ID, buildNotification());
            }

            // Guardar referencia estática
            sPrinterManager = printerManager;

            JSONObject json = new JSONObject();
            json.put("ok", true);
            json.put("message", "Impresora activa: " + printerManager.getActiveName());
            json.put("active", printerManager.getActiveJSON());

            return newFixedLengthResponse(
                    Response.Status.OK,
                    "application/json",
                    json.toString()
            );
        }

        /**
         * GET /printer/protocol?address=AA:BB:CC...
         * Devuelve el protocolo configurado para una MAC.
         */
        private Response handleProtocolGet(IHTTPSession session) throws Exception {
            Map<String, java.util.List<String>> qs = session.getParameters();
            String addr = qs.containsKey("address") && !qs.get("address").isEmpty()
                ? qs.get("address").get(0) : printerManager.getActiveAddress();
            JSONObject json = new JSONObject();
            json.put("ok", true);
            json.put("address", addr);
            json.put("protocol", printerManager.getProtocol(addr));
            return newFixedLengthResponse(Response.Status.OK, "application/json", json.toString());
        }

        /**
         * POST /printer/protocol  body: {"address":"AA:BB:CC...","protocol":"auto|escpos|cpcl|zpl"}
         */
        private Response handleProtocolSet(IHTTPSession session) throws Exception {
            Map<String, String> bodyMap = new HashMap<>();
            session.parseBody(bodyMap);
            String bodyStr = bodyMap.get("postData");
            if (bodyStr == null || bodyStr.isEmpty()) {
                JSONObject err = new JSONObject();
                err.put("ok", false); err.put("error", "Body vacio");
                return newFixedLengthResponse(Response.Status.BAD_REQUEST, "application/json", err.toString());
            }
            JSONObject body = new JSONObject(bodyStr);
            String addr = body.optString("address", printerManager.getActiveAddress());
            String proto = body.optString("protocol", "auto").toLowerCase();
            java.util.Set<String> validos = new java.util.HashSet<>(java.util.Arrays.asList("auto","escpos","cpcl","zpl"));
            if (!validos.contains(proto)) {
                JSONObject err = new JSONObject();
                err.put("ok", false); err.put("error", "protocol inválido: " + proto);
                return newFixedLengthResponse(Response.Status.BAD_REQUEST, "application/json", err.toString());
            }
            printerManager.setProtocol(addr, proto);
            JSONObject json = new JSONObject();
            json.put("ok", true); json.put("address", addr); json.put("protocol", proto);
            return newFixedLengthResponse(Response.Status.OK, "application/json", json.toString());
        }

        /**
         * GET /printer/baud?address=... - Baudrate serial configurado.
         */
        private Response handleBaudGet(IHTTPSession session) throws Exception {
            Map<String, java.util.List<String>> qs = session.getParameters();
            String addr = qs.containsKey("address") && !qs.get("address").isEmpty()
                ? qs.get("address").get(0) : printerManager.getActiveAddress();
            JSONObject json = new JSONObject();
            json.put("ok", true);
            json.put("address", addr);
            json.put("baud", printerManager.getBaud(addr));
            return newFixedLengthResponse(Response.Status.OK, "application/json", json.toString());
        }

        /**
         * POST /printer/baud  body: {"address":"...","baud":9600}
         */
        private Response handleBaudSet(IHTTPSession session) throws Exception {
            Map<String, String> bodyMap = new HashMap<>();
            session.parseBody(bodyMap);
            String bodyStr = bodyMap.get("postData");
            if (bodyStr == null || bodyStr.isEmpty()) {
                JSONObject err = new JSONObject();
                err.put("ok", false); err.put("error", "Body vacio");
                return newFixedLengthResponse(Response.Status.BAD_REQUEST, "application/json", err.toString());
            }
            JSONObject body = new JSONObject(bodyStr);
            String addr = body.optString("address", printerManager.getActiveAddress());
            int baud = body.optInt("baud", 0);
            if (baud <= 0) {
                JSONObject err = new JSONObject();
                err.put("ok", false); err.put("error", "baud inválido: " + baud);
                return newFixedLengthResponse(Response.Status.BAD_REQUEST, "application/json", err.toString());
            }
            printerManager.setBaud(addr, baud);
            JSONObject json = new JSONObject();
            json.put("ok", true); json.put("address", addr); json.put("baud", baud);
            return newFixedLengthResponse(Response.Status.OK, "application/json", json.toString());
        }

        /**
         * POST /usb/permission  body: {"address":"vvvv:pppp"}
         * Dispara el diálogo del sistema para conceder permiso al device USB
         * (sirve tanto para transporte usb como serial-usb).
         */
        private Response handleUsbPermission(IHTTPSession session) throws Exception {
            Map<String, String> bodyMap = new HashMap<>();
            session.parseBody(bodyMap);
            String bodyStr = bodyMap.get("postData");
            String addr = "";
            if (bodyStr != null && !bodyStr.isEmpty()) {
                addr = new JSONObject(bodyStr).optString("address", "");
            }
            if (addr.isEmpty()) addr = printerManager.getActiveAddress();
            if (addr.isEmpty()) {
                JSONObject err = new JSONObject();
                err.put("ok", false); err.put("error", "Campo 'address' requerido");
                return newFixedLengthResponse(Response.Status.BAD_REQUEST, "application/json", err.toString());
            }
            printerManager.getUsbPrinter().requestPermission(addr);
            printerManager.getSerialPrinter().requestPermission(addr);
            JSONObject json = new JSONObject();
            json.put("ok", true);
            json.put("address", addr);
            json.put("granted", printerManager.getUsbPrinter().hasPermission(addr));
            json.put("message", "Solicitud de permiso enviada");
            return newFixedLengthResponse(Response.Status.OK, "application/json", json.toString());
        }

        /**
         * GET /printer/active - Impresora activa actual
         */
        private Response handlePrinterActive() throws Exception {
            JSONObject json = new JSONObject();
            json.put("ok", true);
            json.put("active", printerManager.getActiveJSON());

            return newFixedLengthResponse(
                    Response.Status.OK,
                    "application/json",
                    json.toString()
            );
        }

        /**
         * GET /debug - Listar paquetes sunmi/woyou instalados
         */
        private Response handleDebug() throws Exception {
            JSONObject json = new JSONObject();
            json.put("model", Build.MODEL);
            json.put("manufacturer", Build.MANUFACTURER);
            json.put("product", Build.PRODUCT);
            json.put("brand", Build.BRAND);
            json.put("sdk", Build.VERSION.SDK_INT);
            json.put("serviceInfo", sunmiPrinter.getServiceInfo());
            json.put("activePrinter", printerManager.getActiveJSON());

            // Listar TODOS los paquetes que contengan sunmi, woyou, printer
            JSONArray packages = new JSONArray();
            PackageManager pm = getPackageManager();
            for (PackageInfo pi : pm.getInstalledPackages(0)) {
                String pkg = pi.packageName.toLowerCase();
                if (pkg.contains("sunmi") || pkg.contains("woyou") || pkg.contains("printer")) {
                    packages.put(pi.packageName);
                }
            }
            json.put("packages", packages);

            // Buscar servicios por action
            JSONArray services = new JSONArray();
            String[] actions = {
                "woyou.aidlservice.jiuiv5.IWoyouService",
                "com.sunmi.extprinterservice.PrinterService",
                "com.sunmi.printerservice.IPrinterService"
            };
            for (String action : actions) {
                Intent probe = new Intent(action);
                java.util.List<ResolveInfo> resolved = pm.queryIntentServices(probe, 0);
                for (ResolveInfo ri : resolved) {
                    if (ri.serviceInfo != null) {
                        services.put(action + " -> " + ri.serviceInfo.packageName + "/" + ri.serviceInfo.name);
                    }
                }
            }
            json.put("services", services);

            // BT info
            json.put("bluetoothAvailable", printerManager.getBluetoothPrinter().isAvailable());
            json.put("pairedDevices", printerManager.getBluetoothPrinter().getPairedDevices());

            // USB + Serial (VID:PID reales para configurar el device_filter/auto-grant)
            json.put("usbAvailable", printerManager.getUsbPrinter().isAvailable());
            json.put("usbDevices", printerManager.getUsbPrinter().getDevices());
            json.put("serialDevices", printerManager.getSerialPrinter().getDevices());

            return newFixedLengthResponse(
                    Response.Status.OK,
                    "application/json",
                    json.toString()
            );
        }
    }
}
