package com.factupos.kiosk;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Cliente del servicio local fingerprint_service.py (https://127.0.0.1:52181).
 * Sin failover (siempre 127.0.0.1).
 */
public final class FpClient {

    private final String base;

    public FpClient(String fpServiceUrl) {
        this.base = fpServiceUrl;
    }

    public Http.Resp status(int timeoutSec) {
        return Http.request("GET", base + "/status", null, timeoutSec);
    }

    public Http.Resp getConnection(int timeoutSec) {
        return Http.request("GET", base + "/get_connection", null, timeoutSec);
    }

    public Http.Resp identify(int deviceTimeoutMs, int httpTimeoutSec) {
        Map<String,Object> b = new LinkedHashMap<>();
        b.put("timeout", deviceTimeoutMs);
        return Http.request("POST", base + "/fingerprint/identify", b, httpTimeoutSec);
    }

    /** Bloquea hasta completar el enroll (o cancelacion). Timeout largo. */
    public Http.Resp enroll(String userId, String finger, int timeoutSec) {
        Map<String,Object> b = new LinkedHashMap<>();
        b.put("user_id", userId);
        b.put("finger", finger);
        return Http.request("POST", base + "/fingerprint/enroll", b, timeoutSec);
    }

    public Http.Resp enrollProgress(int timeoutSec) {
        return Http.request("GET", base + "/fingerprint/enroll/progress", null, timeoutSec);
    }

    public Http.Resp enrollCancel(int timeoutSec) {
        return Http.request("POST", base + "/fingerprint/enroll/cancel", new LinkedHashMap<>(), timeoutSec);
    }

    public Http.Resp printsClear(boolean wipeDisk, int timeoutSec) {
        Map<String,Object> b = new LinkedHashMap<>();
        b.put("wipe_disk", wipeDisk);
        return Http.request("POST", base + "/prints/clear", b, timeoutSec);
    }

    /** huellas: lista de {usuario_codigo, dedo, template_b64}. */
    public Http.Resp printsImport(List<Map<String,Object>> huellas, boolean writeDisk, int timeoutSec) {
        Map<String,Object> b = new LinkedHashMap<>();
        b.put("huellas", new ArrayList<Object>(huellas));
        b.put("write_disk", writeDisk);
        return Http.request("POST", base + "/prints/import", b, timeoutSec);
    }

    private FpClient() { this.base = null; }
}
