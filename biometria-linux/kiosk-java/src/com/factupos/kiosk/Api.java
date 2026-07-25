package com.factupos.kiosk;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Cliente del API web de FactuPOS (/apis/biometria/kiosko/*.php, sin sesion) con failover entre api_bases
 * y autenticacion por token o db. Equivalente a KioskApp._api() del kiosk.py.
 * El estado (apiBases/activeApi/token/db) es mutable (se cambia desde Config dialog).
 */
public final class Api {

    public volatile List<String> apiBases;
    public volatile String activeApi;
    public volatile String token;
    public volatile String db;
    public final String plataforma;
    public final String dispositivoId;

    public Api(Config cfg) {
        this.apiBases = new ArrayList<>(cfg.apiBases);
        this.activeApi = apiBases.isEmpty() ? "" : apiBases.get(0);
        this.token = cfg.token;
        this.db = cfg.db;
        this.plataforma = cfg.plataforma;
        this.dispositivoId = cfg.dispositivoId;
    }

    private Map<String,Object> authParams() {
        Map<String,Object> m = new LinkedHashMap<>();
        if (token != null && !token.isEmpty()) m.put("token", token);
        else if (db != null && !db.isEmpty()) m.put("db", db);
        return m;
    }

    /** GET o POST con failover. Devuelve siempre una Resp con body que tiene "ok". */
    public Http.Resp call(String method, String path, Map<String,Object> body, int timeoutSec) {
        Map<String,Object> b = new LinkedHashMap<>();
        if (body != null) b.putAll(body);
        b.putAll(authParams());

        // ordenar bases con activeApi primero
        List<String> bases = new ArrayList<>();
        if (activeApi != null && apiBases.contains(activeApi)) bases.add(activeApi);
        for (String x : apiBases) if (!x.equals(activeApi)) bases.add(x);
        if (bases.isEmpty()) {
            return new Http.Resp(0, err("sin api_base configurada"));
        }

        Http.Resp last = new Http.Resp(0, err("sin respuesta"));
        for (String base : bases) {
            String url = base + path;
            Http.Resp r = "GET".equals(method) ? Http.get(url, b, timeoutSec)
                                                : Http.request(method, url, b, timeoutSec);
            if (r.isApi()) {
                if (!base.equals(activeApi)) Log.i("API activa -> " + base);
                activeApi = base;
                return r;
            }
            Log.i(base + " no parece FactuPOS (HTTP " + r.status + ") — pruebo siguiente api_base");
            if (base.equals(activeApi)) activeApi = "";
            String e = Json.str(r.body, "error", "sin respuesta");
            last = new Http.Resp(r.status, err(e));
        }
        Log.i("Ninguna api_base respondio nuestra API: " + apiBases);
        return last;
    }

    // ---- Endpoints concretos ----
    public Http.Resp huellasListar() {
        Map<String,Object> p = new LinkedHashMap<>();
        p.put("plataforma", plataforma);
        return call("GET", "/apis/biometria/kiosko/huellas_listar.php", p, 20);
    }

    public Http.Resp empleadosListar() {
        return call("GET", "/apis/biometria/kiosko/empleados_listar.php", new LinkedHashMap<>(), 15);
    }

    public Http.Resp marcaRegistrar(String usuarioCodigo) {
        Map<String,Object> p = new LinkedHashMap<>();
        p.put("usuario_codigo", usuarioCodigo);
        p.put("origen", "HUELLA");
        p.put("dispositivo_id", dispositivoId);
        return call("POST", "/apis/biometria/kiosko/marca_registrar.php", p, 20);
    }

    public Http.Resp huellaRegistrar(String usuarioCodigo, String dedo, String templateB64, String serial) {
        Map<String,Object> p = new LinkedHashMap<>();
        p.put("usuario_codigo", usuarioCodigo);
        p.put("dedo", dedo);
        p.put("plataforma", plataforma);
        p.put("template_b64", templateB64);
        p.put("lector_serial", serial);
        p.put("dispositivo_id", dispositivoId);
        return call("POST", "/apis/biometria/kiosko/huella_registrar.php", p, 20);
    }

    private static Map<String,Object> err(String msg) {
        Map<String,Object> m = new LinkedHashMap<>();
        m.put("ok", Boolean.FALSE);
        m.put("error", msg);
        return m;
    }
}
