package com.factupos.printbridge;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * PrinterProfileStore - Persistencia de la lista de impresoras configuradas.
 *
 * Guarda un JSONArray de PrinterProfile en SharedPreferences. Reemplaza el modelo
 * escalar anterior (active_type / active_address), que solo admitía una impresora.
 *
 * La migración desde el modelo viejo es automática y ocurre una sola vez: al primer
 * acceso, si no existe la lista pero sí hay una impresora activa configurada, se
 * convierte en el primer perfil. Así ninguna instalación en campo pierde su
 * configuración al actualizar.
 */
public class PrinterProfileStore {

    private static final String TAG = "PrinterProfileStore";
    private static final String PREFS_NAME = "printer_prefs";

    private static final String KEY_PROFILES  = "printer_profiles";
    private static final String KEY_MIGRATED  = "profiles_migrated_v1";

    // Claves del modelo escalar viejo (solo lectura, para migrar)
    private static final String LEGACY_KEY_ACTIVE_TYPE    = "active_type";
    private static final String LEGACY_KEY_ACTIVE_ADDRESS = "active_address";
    private static final String LEGACY_KEY_PROTOCOL_PREFIX = "protocol_";
    private static final String LEGACY_KEY_BAUD_PREFIX     = "serial_baud_";

    private final Context context;

    public PrinterProfileStore(Context context) {
        this.context = context.getApplicationContext();
    }

    private SharedPreferences prefs() {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    /**
     * Devuelve todos los perfiles configurados. Dispara la migración del modelo
     * viejo si hace falta.
     */
    public List<PrinterProfile> getAll() {
        migrateIfNeeded();
        List<PrinterProfile> out = new ArrayList<PrinterProfile>();
        String raw = prefs().getString(KEY_PROFILES, "");
        if (raw == null || raw.isEmpty()) return out;
        try {
            JSONArray arr = new JSONArray(raw);
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.optJSONObject(i);
                if (o != null) out.add(PrinterProfile.fromJson(o));
            }
        } catch (Exception e) {
            Log.e(TAG, "No se pudo leer la lista de perfiles: " + e.getMessage());
        }
        return out;
    }

    /** Busca un perfil por su id interno. */
    public PrinterProfile getById(String id) {
        if (id == null || id.isEmpty()) return null;
        List<PrinterProfile> all = getAll();
        for (int i = 0; i < all.size(); i++) {
            if (id.equals(all.get(i).id)) return all.get(i);
        }
        return null;
    }

    /**
     * Busca el perfil que atiende una cola. La cola entrante se normaliza antes de
     * comparar, porque el servidor la envía sin ceros a la izquierda.
     *
     * Si se indica empresa, debe coincidir; un perfil sin empresa configurada
     * acepta cualquiera (compat con configuraciones parciales).
     */
    public PrinterProfile findByQueue(String queueCode, String empresa) {
        String q = PrinterProfile.normalizeQueue(queueCode);
        if (q.isEmpty()) return null;
        String emp = empresa != null ? empresa.trim().toLowerCase() : "";
        List<PrinterProfile> all = getAll();
        PrinterProfile sinEmpresa = null;
        for (int i = 0; i < all.size(); i++) {
            PrinterProfile p = all.get(i);
            if (!q.equals(p.queueCode)) continue;
            if (p.empresa == null || p.empresa.isEmpty()) {
                if (sinEmpresa == null) sinEmpresa = p;
                continue;
            }
            if (emp.isEmpty() || p.empresa.equals(emp)) return p;
        }
        return sinEmpresa;
    }

    /** Agrega o actualiza un perfil (por id). */
    public void save(PrinterProfile profile) {
        if (profile == null) return;
        profile.normalize();
        List<PrinterProfile> all = getAll();
        boolean replaced = false;
        for (int i = 0; i < all.size(); i++) {
            if (all.get(i).id.equals(profile.id)) {
                all.set(i, profile);
                replaced = true;
                break;
            }
        }
        if (!replaced) all.add(profile);
        persist(all);
        Log.i(TAG, (replaced ? "Perfil actualizado: " : "Perfil agregado: ")
                + profile.getDisplayName() + " cola=" + profile.queueCode);
    }

    /** Elimina un perfil por id. */
    public void delete(String id) {
        if (id == null || id.isEmpty()) return;
        List<PrinterProfile> all = getAll();
        List<PrinterProfile> out = new ArrayList<PrinterProfile>();
        for (int i = 0; i < all.size(); i++) {
            if (!id.equals(all.get(i).id)) out.add(all.get(i));
        }
        persist(out);
        Log.i(TAG, "Perfil eliminado: " + id);
    }

    /** Reemplaza toda la lista. */
    public void replaceAll(List<PrinterProfile> profiles) {
        persist(profiles != null ? profiles : new ArrayList<PrinterProfile>());
    }

    private void persist(List<PrinterProfile> profiles) {
        JSONArray arr = new JSONArray();
        for (int i = 0; i < profiles.size(); i++) {
            try {
                PrinterProfile p = profiles.get(i);
                p.normalize();
                arr.put(p.toJson());
            } catch (Exception e) {
                Log.e(TAG, "No se pudo serializar un perfil: " + e.getMessage());
            }
        }
        prefs().edit()
               .putString(KEY_PROFILES, arr.toString())
               .putBoolean(KEY_MIGRATED, true)
               .apply();
    }

    /** Lista de colas a registrar en el WebSocket, en el formato del server. */
    public JSONArray getQueuesJSON() {
        JSONArray arr = new JSONArray();
        List<PrinterProfile> all = getAll();
        for (int i = 0; i < all.size(); i++) {
            PrinterProfile p = all.get(i);
            if (p.queueCode == null || p.queueCode.isEmpty()) continue;
            try {
                JSONObject o = new JSONObject();
                o.put("code", p.queueCode);
                o.put("empresa", p.empresa != null ? p.empresa : "");
                arr.put(o);
            } catch (Exception ignored) {
            }
        }
        return arr;
    }

    /** ¿Hay al menos un perfil utilizable? */
    public boolean hasUsableProfile() {
        List<PrinterProfile> all = getAll();
        for (int i = 0; i < all.size(); i++) {
            if (all.get(i).isComplete()) return true;
        }
        return false;
    }

    /**
     * Migración única desde el modelo escalar. La impresora activa actual pasa a ser
     * el primer perfil, conservando el protocolo y baudrate que ya tenía guardados.
     *
     * El perfil migrado queda SIN cola ni empresa: esos datos no existían en el modelo
     * viejo y los tiene que completar el usuario al configurar la estación para
     * WebSocket. Mientras tanto sigue sirviendo para la ruta HTTP local.
     */
    private void migrateIfNeeded() {
        SharedPreferences p = prefs();
        if (p.getBoolean(KEY_MIGRATED, false)) return;
        if (p.contains(KEY_PROFILES)) {
            p.edit().putBoolean(KEY_MIGRATED, true).apply();
            return;
        }

        String type = p.getString(LEGACY_KEY_ACTIVE_TYPE, "");
        String address = p.getString(LEGACY_KEY_ACTIVE_ADDRESS, "");

        List<PrinterProfile> out = new ArrayList<PrinterProfile>();
        if (type != null && !type.isEmpty()) {
            PrinterProfile prof = new PrinterProfile();
            prof.transport = type;
            prof.address = address != null ? address : "";
            String key = prof.address.toUpperCase();
            if (!key.isEmpty()) {
                prof.protocol = p.getString(LEGACY_KEY_PROTOCOL_PREFIX + key,
                                            PrinterManager.PROTOCOL_AUTO);
                prof.baud = p.getInt(LEGACY_KEY_BAUD_PREFIX + key, SerialPrinter.DEFAULT_BAUD);
            }
            out.add(prof);
            Log.i(TAG, "Migrado el modelo escalar a perfil: type=" + type + " address=" + address);
        } else {
            Log.i(TAG, "Sin impresora activa previa; no hay nada que migrar.");
        }

        persist(out);
    }
}
