package com.factupos.kiosk;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

/**
 * Configuracion del kiosko. Lee config.json (se autocrea con defaults) y token.conf.
 * Equivalente a load_config() del kiosk.py. Plataforma por defecto = "linux".
 */
public final class Config {

    public final Path baseDir;
    public final Path configFile;
    public final Path tokenConfFile;
    public final Path logsDir;

    public List<String> apiBases = new ArrayList<>();
    public String db = "";
    public String token = "";
    public String dispositivoId = "KIOSKO-01";
    public String fpServiceUrl = "https://127.0.0.1:52181";
    public String plataforma = "linux";
    public String dedoDefault = "right-index";
    public int refreshMinutos = 10;
    public boolean fullscreen = false;
    public String ventana = "420x640";
    public String titulo = "Marcaje de Asistencia";
    public boolean autoRegistrarSiNoExiste = true;

    /** true si el config.json se acaba de crear (no estaba). */
    public boolean recienCreado = false;

    public Config() {
        this.baseDir = resolveBaseDir();
        this.configFile = baseDir.resolve("config.json");
        this.tokenConfFile = baseDir.resolve("token.conf");
        this.logsDir = baseDir.resolve("logs");
    }

    private static Path resolveBaseDir() {
        // Modo portable (desarrollo): si hay un config.json escribible junto al jar, usarlo.
        try {
            Path loc = Paths.get(Config.class.getProtectionDomain().getCodeSource()
                    .getLocation().toURI());
            Path dir = Files.isRegularFile(loc) ? loc.getParent() : loc;
            if (dir != null && Files.isRegularFile(dir.resolve("config.json")) && Files.isWritable(dir)) {
                return dir;
            }
        } catch (Exception ignored) { /* fallthrough */ }
        // Modo instalado (.deb en /opt): config en el home del usuario.
        String home = System.getProperty("user.home", ".");
        Path cfgDir = Paths.get(home, ".config", "factupos-fingerprint-kiosko");
        try { Files.createDirectories(cfgDir); } catch (Exception ignored) {}
        return cfgDir;
    }

    public Config load() throws IOException {
        if (!Files.isRegularFile(configFile)) {
            writeDefaultConfig();
            recienCreado = true;
            return this;
        }
        String raw = new String(Files.readAllBytes(configFile), StandardCharsets.UTF_8);
        Map<String,Object> c = Json.parseObj(raw);

        List<String> bases = new ArrayList<>();
        bases.addAll(normBases(c.get("api_base")));
        bases.addAll(normBases(c.get("api_base_fallback")));
        if (bases.isEmpty()) bases = new ArrayList<>(Arrays.asList("https://invefacon.net", "https://invefacon.com"));
        this.apiBases = new ArrayList<>(new LinkedHashSet<>(bases)); // dedup preservando orden

        this.db = Json.str(c, "db", "").trim();
        this.dispositivoId = Json.str(c, "dispositivo_id", "KIOSKO-01");
        this.fpServiceUrl = stripSlash(Json.str(c, "fp_service_url", "https://127.0.0.1:52181"));
        this.plataforma = Json.str(c, "plataforma", "linux");
        this.dedoDefault = Json.str(c, "dedo_default", "right-index");
        this.refreshMinutos = Json.intVal(c, "refresh_minutos", 10);
        this.fullscreen = Json.bool(c, "fullscreen");
        this.ventana = Json.str(c, "ventana", "420x640");
        this.titulo = Json.str(c, "titulo", "Marcaje de Asistencia");
        if (c.containsKey("auto_registrar_si_no_existe"))
            this.autoRegistrarSiNoExiste = Json.bool(c, "auto_registrar_si_no_existe");

        // token: token.conf manda; si no, "token" del config.json
        String tok = "";
        if (Files.isRegularFile(tokenConfFile)) {
            for (String line : Files.readAllLines(tokenConfFile, StandardCharsets.UTF_8)) {
                String t = line.trim();
                if (!t.isEmpty() && !t.startsWith("#")) { tok = t; break; }
            }
        }
        this.token = !tok.isEmpty() ? tok : Json.str(c, "token", "").trim();
        return this;
    }

    public String serverdb() {
        if (token.contains("~")) return token.substring(0, token.indexOf('~'));
        return db;
    }

    public void writeTokenConf(String tok) throws IOException {
        Files.write(tokenConfFile, ((tok == null ? "" : tok.trim()) + "\n").getBytes(StandardCharsets.UTF_8));
    }

    public void updateConfigJson(Map<String,Object> fields) {
        try {
            Map<String,Object> cur = new LinkedHashMap<>();
            if (Files.isRegularFile(configFile)) {
                cur = Json.parseObj(new String(Files.readAllBytes(configFile), StandardCharsets.UTF_8));
            }
            cur.putAll(fields);
            Files.write(configFile, Json.write(cur).getBytes(StandardCharsets.UTF_8));
        } catch (Exception e) {
            Log.e("No se pudo actualizar config.json", e);
        }
    }

    private void writeDefaultConfig() throws IOException {
        Map<String,Object> d = new LinkedHashMap<>();
        d.put("api_base", new ArrayList<>(Arrays.asList("https://invefacon.net", "https://invefacon.com")));
        d.put("db", "");
        d.put("token", "");
        d.put("dispositivo_id", "KIOSKO-01");
        d.put("fp_service_url", "https://127.0.0.1:52181");
        d.put("plataforma", "linux");
        d.put("dedo_default", "right-index");
        d.put("refresh_minutos", 10L);
        d.put("fullscreen", false);
        d.put("ventana", "420x640");
        d.put("titulo", "Marcaje de Asistencia");
        d.put("auto_registrar_si_no_existe", true);
        Files.createDirectories(baseDir);
        Files.write(configFile, prettyish(Json.write(d)).getBytes(StandardCharsets.UTF_8));
    }

    static List<String> normBases(Object val) {
        List<String> out = new ArrayList<>();
        if (val instanceof String) {
            String s = ((String) val).trim();
            if (!s.isEmpty()) out.add(stripSlash(s));
        } else if (val instanceof List) {
            for (Object x : (List<?>) val) {
                String s = String.valueOf(x).trim();
                if (!s.isEmpty()) out.add(stripSlash(s));
            }
        }
        return out;
    }

    static List<String> normBasesCsv(String csv) {
        List<String> out = new ArrayList<>();
        if (csv == null) return out;
        for (String s : csv.split(",")) {
            String t = s.trim();
            if (!t.isEmpty()) out.add(stripSlash(t));
        }
        return out;
    }

    private static String stripSlash(String s) {
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    /** Pequeno "pretty print" con saltos de linea por clave (suficiente para legibilidad). */
    private static String prettyish(String compact) {
        return compact.replace(",\"", ",\n  \"")
                      .replaceFirst("\\{\"", "{\n  \"")
                      .replaceAll("}$", "\n}");
    }
}
