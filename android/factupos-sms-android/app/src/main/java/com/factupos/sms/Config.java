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
    public static final String ENDPOINT = "https://soportereal.com/api_sinpe_inbound.php";
    public static final String TOKEN = "FpSmS_2026_a9X2k7Qv3mZt8Lw5Bn";

    private static SharedPreferences p(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static String getEndpoint(Context c) { return ENDPOINT; }
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
}
