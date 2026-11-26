package com.factupos.sms;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Config de FactuposSMS. El usuario define el nombre de la BD/empresa POR CADA SIM.
 * El endpoint y el token son INTERNOS (no se escriben en la app).
 */
public class Config {
    private static final String PREFS = "factupossms";

    // ---- INTERNOS (no editables por el usuario) ----
    // Rutas del API, en el orden en que se prueban (#1307): primero la NAVY (factupos.com/apis/,
    // que en producción sirven invefacon.com y su gemela invefacon.net) y al final la LEGACY de
    // soportereal.com, de respaldo mientras la navy no esté en el servidor. Las dos guardan en la
    // misma tabla y no repiten un SMS, así que pasar de una a otra no duplica pagos.
    public static final String[] ENDPOINTS = {
            "https://invefacon.com/apis/sinpe/sinpe_sms_recibir.php",
            "https://invefacon.net/apis/sinpe/sinpe_sms_recibir.php",
            "https://soportereal.com/api_sinpe_inbound.php",
    };
    public static final String TOKEN = "FpSmS_2026_a9X2k7Qv3mZt8Lw5Bn";

    static SharedPreferences p(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static String getToken(Context c) { return TOKEN; }

    /** Empresa/BD configurada para un slot de SIM (0 = SIM1, 1 = SIM2). */
    public static String getEmpresaForSlot(Context c, int slot) {
        return p(c).getString("empresa_sim_" + slot, "");
    }

    public static void setEmpresaForSlot(Context c, int slot, String empresa) {
        p(c).edit().putString("empresa_sim_" + slot, empresa == null ? "" : empresa.trim()).apply();
    }

    /** Estado del servicio de captura (iniciado/detenido). */
    public static boolean isServicioActivo(Context c) {
        return p(c).getBoolean("servicio_activo", false);
    }

    public static void setServicioActivo(Context c, boolean v) {
        p(c).edit().putBoolean("servicio_activo", v).apply();
    }

    /** Sonar al cargar cada mensaje (#1307). Viene encendido. */
    public static boolean isSonidoActivo(Context c) {
        return p(c).getBoolean("sonido_activo", true);
    }

    public static void setSonidoActivo(Context c, boolean v) {
        p(c).edit().putBoolean("sonido_activo", v).apply();
    }
}
