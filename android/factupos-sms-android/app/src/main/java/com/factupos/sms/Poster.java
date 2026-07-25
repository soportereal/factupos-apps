package com.factupos.sms;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

/** Envía un SMS al endpoint del servidor por HTTP POST (x-www-form-urlencoded). */
public class Poster {

    /** Devuelve true si el servidor respondió 2xx. */
    public static boolean post(String endpoint, String token, String empresa,
                               String fecha, String origen, String mensaje, int subId, String sim) {
        if (endpoint == null || endpoint.trim().isEmpty()) return false;
        HttpURLConnection conn = null;
        try {
            StringBuilder body = new StringBuilder();
            body.append("token=").append(enc(token));
            body.append("&empresa=").append(enc(empresa));
            body.append("&fecha=").append(enc(fecha));
            body.append("&origen=").append(enc(origen));
            body.append("&mensaje=").append(enc(mensaje));
            body.append("&sub_id=").append(subId);
            body.append("&sim=").append(enc(sim));
            byte[] data = body.toString().getBytes("UTF-8");

            URL url = new URL(endpoint);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(20000);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
            conn.setRequestProperty("X-Factupos-Token", token == null ? "" : token);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(data);
            }
            int code = conn.getResponseCode();
            return code >= 200 && code < 300;
        } catch (Exception e) {
            return false;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s == null ? "" : s, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }
}
