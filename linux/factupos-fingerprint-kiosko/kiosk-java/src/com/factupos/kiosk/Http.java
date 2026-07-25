package com.factupos.kiosk;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * Wrapper HTTP sobre java.net.http.HttpClient.
 * - Confia en cualquier certificado (el servicio local usa cert autofirmado en 127.0.0.1).
 * - Devuelve Resp{status, body(Map)}. status==0 => no respondio (red/timeout).
 * - En errores que NO son JSON de nuestra API se marca "_neterr" y NO se incluye "ok",
 *   igual que el kiosk.py, para que ApiClient pueda hacer failover.
 */
public final class Http {

    public static final class Resp {
        public final int status;
        public final Map<String,Object> body;
        Resp(int status, Map<String,Object> body) { this.status = status; this.body = body; }
        public boolean isApi() { return body != null && body.containsKey("ok") && !body.containsKey("_neterr"); }
        public boolean ok() { return Json.bool(body, "ok"); }
    }

    private static final HttpClient CLIENT = build();

    private static HttpClient build() {
        try {
            // Necesario para que HttpClient no rechace por hostname en algunos casos.
            System.setProperty("jdk.internal.httpclient.disableHostnameVerification", "true");
            SSLContext ctx = SSLContext.getInstance("TLS");
            TrustManager[] trustAll = new TrustManager[]{ new X509TrustManager() {
                public void checkClientTrusted(X509Certificate[] c, String a) {}
                public void checkServerTrusted(X509Certificate[] c, String a) {}
                public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
            }};
            ctx.init(null, trustAll, new java.security.SecureRandom());
            return HttpClient.newBuilder()
                    .sslContext(ctx)
                    .connectTimeout(Duration.ofSeconds(8))
                    .build();
        } catch (Exception e) {
            return HttpClient.newHttpClient();
        }
    }

    public static Resp request(String method, String url, Map<String,Object> body, int timeoutSec) {
        try {
            HttpRequest.Builder rb = HttpRequest.newBuilder()
                    .uri(URI.create(url))
                    .timeout(Duration.ofSeconds(Math.max(1, timeoutSec)))
                    .header("Accept", "application/json");
            if (body != null) {
                String json = Json.write(body);
                rb.header("Content-Type", "application/json");
                rb.method(method, HttpRequest.BodyPublishers.ofString(json));
            } else {
                rb.method(method, HttpRequest.BodyPublishers.noBody());
            }
            HttpResponse<String> resp = CLIENT.send(rb.build(), HttpResponse.BodyHandlers.ofString());
            String raw = resp.body();
            Object parsed;
            try {
                parsed = Json.parse(raw);
            } catch (Exception e) {
                parsed = null;
            }
            if (parsed instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String,Object> m = (Map<String,Object>) parsed;
                return new Resp(resp.statusCode(), m);
            }
            // Respuesta no-JSON (ej HTML de un server que no es FactuPOS)
            Map<String,Object> m = new LinkedHashMap<>();
            m.put("_neterr", "respuesta no-JSON");
            String snip = raw == null ? "" : raw.substring(0, Math.min(200, raw.length()));
            m.put("error", "respuesta no-JSON: " + snip);
            return new Resp(resp.statusCode(), m);
        } catch (Exception e) {
            Map<String,Object> m = new LinkedHashMap<>();
            m.put("_neterr", "red/timeout");
            m.put("error", String.valueOf(e.getMessage()));
            return new Resp(0, m);
        }
    }

    /** GET pasando params como query string. */
    public static Resp get(String url, Map<String,Object> params, int timeoutSec) {
        if (params != null && !params.isEmpty()) {
            StringBuilder qs = new StringBuilder(url.contains("?") ? "&" : "?");
            boolean first = true;
            for (Map.Entry<String,Object> e : params.entrySet()) {
                if (!first) qs.append('&');
                first = false;
                qs.append(enc(e.getKey())).append('=').append(enc(String.valueOf(e.getValue())));
            }
            url = url + qs;
        }
        return request("GET", url, null, timeoutSec);
    }

    private static String enc(String s) {
        try { return java.net.URLEncoder.encode(s, "UTF-8"); }
        catch (Exception e) { return s; }
    }

    /** GET binario (para descargar el .jar del auto-update). null si no es 200. */
    public static byte[] getBytes(String url, int timeoutSec) {
        try {
            HttpRequest req = HttpRequest.newBuilder().uri(URI.create(url))
                    .timeout(Duration.ofSeconds(Math.max(1, timeoutSec)))
                    .header("Cache-Control", "no-cache")
                    .GET().build();
            HttpResponse<byte[]> r = CLIENT.send(req, HttpResponse.BodyHandlers.ofByteArray());
            return r.statusCode() == 200 ? r.body() : null;
        } catch (Exception e) {
            return null;
        }
    }

    private Http() {}
}
