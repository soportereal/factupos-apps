package com.factupos.sms;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

/** Envía un SMS al API del servidor por HTTP POST (x-www-form-urlencoded). */
public class Poster {

    /** Lo que contestó el servidor. Desde la v1.1 (#1307) se lee: antes se ignoraba. */
    public static class Resultado {
        public boolean ok;               // el servidor lo guardó
        public long id;                  // Id en PagosSinpe
        public double monto = -1;        // -1 = el servidor no sacó monto del texto
        public String nombre = "";       // quién pagó, si el servidor lo sacó del texto
        public boolean empresaOk = true; // false = la empresa escrita no existe
        public boolean duplicado;        // ese SMS ya estaba cargado
        public String ruta = "";         // qué API lo atendió: "navy" o "legacy"
        public String error = "";
        boolean contesto;                // contestó un API de verdad (JSON), bien o con un error suyo
    }

    public static Resultado post(String token, String empresa,
                                 String fecha, String origen, String mensaje, int subId, String sim) {
        StringBuilder body = new StringBuilder();
        body.append("token=").append(enc(token));
        body.append("&empresa=").append(enc(empresa));
        body.append("&fecha=").append(enc(fecha));
        body.append("&origen=").append(enc(origen));
        body.append("&mensaje=").append(enc(mensaje));
        body.append("&sub_id=").append(subId);
        body.append("&sim=").append(enc(sim));
        return enviar(token, body.toString());
    }

    /** ¿Existe una empresa con ese nombre de BD? null = no se pudo preguntar. */
    public static Boolean verificarEmpresa(String token, String empresa) {
        Resultado r = enviar(token, "token=" + enc(token) + "&accion=verificar&empresa=" + enc(empresa));
        return r.ok ? r.empresaOk : null;
    }

    /**
     * Prueba las rutas de Config.ENDPOINTS en orden y se queda con la primera que conteste como API.
     * Si una ruta no existe en el servidor (404) o no hay conexión, sigue con la siguiente; si el API
     * contestó —aunque sea con un error suyo— no prueba otra, para no mandar dos veces lo mismo.
     */
    private static Resultado enviar(String token, String body) {
        Resultado r = null;
        for (String url : Config.ENDPOINTS) {
            r = intentar(url, token, body);
            if (r.contesto) break;
        }
        return r;
    }

    private static Resultado intentar(String endpoint, String token, String body) {
        Resultado r = new Resultado();
        r.ruta = endpoint.contains("/apis/") ? "navy" : "legacy";
        HttpURLConnection conn = null;
        try {
            byte[] data = body.getBytes("UTF-8");

            URL url = new URL(endpoint);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(20000);
            conn.setDoOutput(true);
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
            conn.setRequestProperty("X-Factupos-Token", token == null ? "" : token);
            try (OutputStream os = conn.getOutputStream()) {
                os.write(data);
            }
            int code = conn.getResponseCode();
            JSONObject j = null;
            try {
                j = new JSONObject(leer(code >= 400 ? conn.getErrorStream() : conn.getInputStream()));
            } catch (Exception ignored) {
                // no vino JSON: la ruta no existe (página 404) o es la página de un WiFi con portal
            }
            r.contesto = j != null && j.has("ok");
            if (code >= 200 && code < 300 && r.contesto && j.optBoolean("ok", false)) {
                r.ok = true;
                r.id = j.optLong("id", 0);
                if (!j.isNull("monto")) r.monto = j.optDouble("monto", -1);
                if (!j.isNull("nombre")) r.nombre = j.optString("nombre", "");
                r.empresaOk = j.optBoolean("empresa_ok", true);
                r.duplicado = j.optBoolean("duplicado", false);
            } else {
                r.error = (j != null && !j.isNull("error")) ? j.optString("error") : "El servidor no lo recibió (" + code + ")";
            }
        } catch (Exception e) {
            r.error = "Sin conexión con el servidor";
        } finally {
            if (conn != null) conn.disconnect();
        }
        return r;
    }

    private static String leer(InputStream is) throws Exception {
        if (is == null) return "";
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        try {
            while ((n = is.read(buf)) > 0) out.write(buf, 0, n);
        } finally {
            is.close();
        }
        return out.toString("UTF-8");
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s == null ? "" : s, "UTF-8");
        } catch (Exception e) {
            return "";
        }
    }
}
