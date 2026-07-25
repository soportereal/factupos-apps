package com.factupos.kiosk;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.Map;

/**
 * Auto-actualización del kiosko (igual idea que el servicio Python):
 * lee un manifiesto JSON publicado en descargas; si hay versión mayor baja el .jar
 * nuevo a una carpeta del USUARIO (~/.local/share, sin root) y reinicia. El lanzador
 * run.sh corre el .jar más nuevo entre /opt (del .deb) y el local.
 * Chequeo automático a los 20 s de abrir y luego cada 1 hora + botón manual.
 */
public final class Updater {

    static final String BASE = "https://soportereal.com/software/factupos-app/linux";
    static final String MANIFEST = BASE + "/factupos-fingerprint-kiosko_version.json";
    static final String JAR_FALLBACK = BASE + "/FactuposKioskoHuella.jar";
    static final long INTERVAL_MS = 60L * 60L * 1000L;   // 1 hora

    static final Path LOCAL_DIR = Paths.get(System.getProperty("user.home"),
            ".local", "share", "factupos-fingerprint-kiosko");
    static final Path LOCAL_JAR = LOCAL_DIR.resolve("FactuposKioskoHuella.jar");
    static final Path LOCAL_VER = LOCAL_DIR.resolve("version");

    public static final class R {
        public final boolean updated; public final String latest; public final String msg;
        R(boolean u, String l, String m) { updated = u; latest = l; msg = m; }
    }

    /** Arranca el chequeo automático en segundo plano (20 s + cada 1 h). */
    public static void startAuto() {
        Thread t = new Thread(() -> {
            try { Thread.sleep(20_000); } catch (InterruptedException ignored) {}
            while (true) {
                try {
                    R r = check(true);
                    if (r.updated) { restart(); return; }
                } catch (Exception e) {
                    Log.i("update auto: " + e.getMessage());
                }
                try { Thread.sleep(INTERVAL_MS); } catch (InterruptedException ignored) {}
            }
        }, "updater");
        t.setDaemon(true);
        t.start();
    }

    /** Consulta el manifiesto; si apply y hay versión nueva, baja el .jar y lo deja listo. */
    public static R check(boolean apply) {
        Http.Resp resp = Http.get(MANIFEST, null, 8);
        if (resp.body == null || !resp.body.containsKey("version")) {
            return new R(false, null, "No se pudo verificar (sin conexión o manifiesto ausente).");
        }
        String latest = Json.str(resp.body, "version");
        if (latest == null || latest.isEmpty()) return new R(false, null, "Manifiesto inválido.");
        if (cmp(latest, Main.APP_VERSION) <= 0) {
            return new R(false, latest, "El kiosko ya está actualizado (v" + Main.APP_VERSION + ").");
        }
        if (!apply) return new R(false, latest, "Hay una versión nueva disponible: " + latest);

        String jarUrl = Json.str(resp.body, "jar");
        if (jarUrl == null || jarUrl.isEmpty()) jarUrl = JAR_FALLBACK;
        byte[] data = Http.getBytes(jarUrl, 60);
        if (data == null || data.length < 20_000) {
            return new R(false, latest, "Descarga inválida del .jar.");
        }
        try {
            Files.createDirectories(LOCAL_DIR);
            Path tmp = LOCAL_DIR.resolve("FactuposKioskoHuella.jar.new");
            Files.write(tmp, data);
            Files.move(tmp, LOCAL_JAR, StandardCopyOption.REPLACE_EXISTING);
            Files.write(LOCAL_VER, latest.getBytes("UTF-8"));
        } catch (Exception e) {
            return new R(false, latest, "No se pudo guardar la actualización: " + e.getMessage());
        }
        Log.i("Kiosko actualizado " + Main.APP_VERSION + " -> " + latest);
        return new R(true, latest, "Actualizado a v" + latest + ". Reiniciando...");
    }

    /** Relanza el kiosko (el lanzador corre el .jar más nuevo) y cierra esta instancia. */
    public static void restart() {
        try {
            Main.releaseSingleLock();   // soltar el lock para que la nueva instancia arranque
            String launcher = "/usr/bin/factupos-fingerprint-kiosko";
            ProcessBuilder pb;
            if (new File(launcher).canExecute()) {
                pb = new ProcessBuilder("setsid", launcher);
            } else {
                // dev / sin instalar: relanzar el jar que esté más nuevo
                String jar = Files.exists(LOCAL_JAR) ? LOCAL_JAR.toString()
                        : new File(Updater.class.getProtectionDomain().getCodeSource()
                            .getLocation().toURI()).getAbsolutePath();
                pb = new ProcessBuilder("java", "-jar", jar);
            }
            pb.inheritIO();
            pb.start();
        } catch (Exception e) {
            Log.i("update restart: " + e.getMessage());
        }
        System.exit(0);
    }

    /** Compara versiones tipo 1.7.10 numéricamente. >0 si a>b. */
    static int cmp(String a, String b) {
        String[] pa = a.trim().split("\\."), pb = b.trim().split("\\.");
        int n = Math.max(pa.length, pb.length);
        for (int i = 0; i < n; i++) {
            int x = i < pa.length ? parse(pa[i]) : 0;
            int y = i < pb.length ? parse(pb[i]) : 0;
            if (x != y) return Integer.compare(x, y);
        }
        return 0;
    }
    static int parse(String s) { try { return Integer.parseInt(s.replaceAll("\\D", "")); } catch (Exception e) { return 0; } }

    private Updater() {}
}
