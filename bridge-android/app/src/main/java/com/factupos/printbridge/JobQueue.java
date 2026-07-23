package com.factupos.printbridge;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * JobQueue - Cola local de trabajos de impresión.
 *
 * POR QUÉ EXISTE: el servidor da 15 segundos para el ACK y no reintenta nunca. Si la
 * app imprimiera de forma sincrónica antes de ackear, cualquier impresora lenta,
 * sin papel o apagada haría perder el trabajo. Entonces se invierte el orden:
 *
 *   llega el trabajo -> se guarda acá -> se ackea de inmediato -> se imprime aparte
 *
 * A partir del ACK, esta cola es la ÚNICA dueña del trabajo: el servidor ya lo borró
 * de su tabla. Por eso los trabajos se persisten en disco y sobreviven a que la app
 * se cierre o el equipo se reinicie.
 *
 * Se guarda como JSON en SharedPreferences en vez de SQLite: el volumen es de unos
 * pocos tiquetes pendientes, se puede probar sin dispositivo, y evita sumar
 * dependencias. El tope de MAX_JOBS protege el caso patológico (impresora muerta
 * durante horas mientras siguen entrando trabajos).
 */
public class JobQueue {

    private static final String TAG = "JobQueue";
    private static final String PREFS_NAME = "print_queue";
    private static final String KEY_JOBS = "jobs";

    /** Tope de trabajos retenidos. Al superarlo se descarta el MÁS VIEJO. */
    public static final int MAX_JOBS = 200;

    /** Reintentos antes de darlo por perdido. */
    public static final int MAX_ATTEMPTS = 5;

    /** Backoff entre reintentos, en milisegundos, por número de intento. */
    private static final long[] BACKOFF_MS = {
        2000L, 5000L, 15000L, 60000L, 180000L
    };

    public static class Job {
        public String jobId = "";
        public String queue = "";
        public String empresa = "";
        /** Contenido en base64, tal cual lo mandó el servidor. */
        public String data = "";
        public String format = "";
        public long createdAt = 0L;
        public int attempts = 0;
        /** Momento a partir del cual se puede volver a intentar. */
        public long nextTryAt = 0L;
        public String lastError = "";

        JSONObject toJson() throws Exception {
            JSONObject o = new JSONObject();
            o.put("jobId", jobId);
            o.put("queue", queue);
            o.put("empresa", empresa);
            o.put("data", data);
            o.put("format", format);
            o.put("createdAt", createdAt);
            o.put("attempts", attempts);
            o.put("nextTryAt", nextTryAt);
            o.put("lastError", lastError);
            return o;
        }

        static Job fromJson(JSONObject o) {
            Job j = new Job();
            j.jobId    = o.optString("jobId", "");
            j.queue    = o.optString("queue", "");
            j.empresa  = o.optString("empresa", "");
            j.data     = o.optString("data", "");
            j.format   = o.optString("format", "");
            j.createdAt = parseLong(o.optString("createdAt", "0"));
            j.attempts  = o.optInt("attempts", 0);
            j.nextTryAt = parseLong(o.optString("nextTryAt", "0"));
            j.lastError = o.optString("lastError", "");
            return j;
        }

        private static long parseLong(String s) {
            try { return Long.parseLong(s); } catch (Exception e) { return 0L; }
        }
    }

    private final Context context;

    public JobQueue(Context context) {
        this.context = context.getApplicationContext();
    }

    private SharedPreferences prefs() {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public synchronized List<Job> getAll() {
        List<Job> out = new ArrayList<Job>();
        String raw = prefs().getString(KEY_JOBS, "");
        if (raw == null || raw.isEmpty()) return out;
        try {
            JSONArray arr = new JSONArray(raw);
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.optJSONObject(i);
                if (o != null) out.add(Job.fromJson(o));
            }
        } catch (Exception e) {
            Log.e(TAG, "No se pudo leer la cola: " + e.getMessage());
        }
        return out;
    }

    private synchronized void persist(List<Job> jobs) {
        JSONArray arr = new JSONArray();
        for (int i = 0; i < jobs.size(); i++) {
            try {
                arr.put(jobs.get(i).toJson());
            } catch (Exception e) {
                Log.e(TAG, "No se pudo serializar un trabajo: " + e.getMessage());
            }
        }
        prefs().edit().putString(KEY_JOBS, arr.toString()).apply();
    }

    /**
     * Encola un trabajo recién recibido. Idempotente por jobId: si el servidor
     * reenvía el mismo trabajo (pasa al reconectar, con flushPendingJobs), no se
     * duplica el tiquete.
     *
     * @return true si se encoló, false si ya estaba
     */
    public synchronized boolean enqueue(Job job, long now) {
        if (job == null || job.jobId == null || job.jobId.isEmpty()) return false;
        List<Job> jobs = getAll();
        for (int i = 0; i < jobs.size(); i++) {
            if (job.jobId.equals(jobs.get(i).jobId)) {
                Log.i(TAG, "Trabajo duplicado, se ignora: " + job.jobId);
                return false;
            }
        }
        job.createdAt = now;
        job.nextTryAt = now;
        job.attempts = 0;
        jobs.add(job);

        while (jobs.size() > MAX_JOBS) {
            Job viejo = jobs.remove(0);
            Log.w(TAG, "Cola llena (" + MAX_JOBS + "), se descarta el mas viejo: " + viejo.jobId);
        }
        persist(jobs);
        return true;
    }

    /**
     * Devuelve el próximo trabajo listo para imprimir (el más viejo cuyo nextTryAt
     * ya pasó), o null si no hay ninguno pendiente todavía.
     */
    public synchronized Job nextReady(long now) {
        List<Job> jobs = getAll();
        for (int i = 0; i < jobs.size(); i++) {
            Job j = jobs.get(i);
            if (j.nextTryAt <= now) return j;
        }
        return null;
    }

    /** Quita un trabajo (impreso con éxito, o descartado). */
    public synchronized void remove(String jobId) {
        if (jobId == null || jobId.isEmpty()) return;
        List<Job> jobs = getAll();
        List<Job> out = new ArrayList<Job>();
        for (int i = 0; i < jobs.size(); i++) {
            if (!jobId.equals(jobs.get(i).jobId)) out.add(jobs.get(i));
        }
        persist(out);
    }

    /**
     * Marca un intento fallido y programa el reintento con backoff.
     *
     * @return true si queda en la cola, false si se agotaron los intentos y se descartó
     */
    public synchronized boolean markFailed(String jobId, String error, long now) {
        List<Job> jobs = getAll();
        List<Job> out = new ArrayList<Job>();
        boolean sigue = true;
        for (int i = 0; i < jobs.size(); i++) {
            Job j = jobs.get(i);
            if (!jobId.equals(j.jobId)) { out.add(j); continue; }
            j.attempts++;
            j.lastError = error != null ? error : "";
            if (j.attempts >= MAX_ATTEMPTS) {
                Log.e(TAG, "Trabajo descartado tras " + j.attempts + " intentos: "
                         + j.jobId + " (" + j.lastError + ")");
                sigue = false;
                continue; // no se re-agrega
            }
            int idx = Math.min(j.attempts - 1, BACKOFF_MS.length - 1);
            j.nextTryAt = now + BACKOFF_MS[idx];
            out.add(j);
        }
        persist(out);
        return sigue;
    }

    public synchronized int size() {
        return getAll().size();
    }

    /** Cantidad de trabajos listos para intentar ahora. */
    public synchronized int readyCount(long now) {
        List<Job> jobs = getAll();
        int n = 0;
        for (int i = 0; i < jobs.size(); i++) {
            if (jobs.get(i).nextTryAt <= now) n++;
        }
        return n;
    }

    /** Vacía la cola (botón "Limpiar cola"). */
    public synchronized int clear() {
        int n = size();
        prefs().edit().putString(KEY_JOBS, "[]").apply();
        Log.i(TAG, "Cola local vaciada (" + n + " trabajos)");
        return n;
    }
}
