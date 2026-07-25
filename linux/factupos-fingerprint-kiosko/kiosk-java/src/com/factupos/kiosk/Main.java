package com.factupos.kiosk;

import java.net.InetAddress;
import java.net.ServerSocket;
import javax.swing.JOptionPane;
import javax.swing.SwingUtilities;
import javax.swing.UIManager;

/**
 * FactuPOS - Kiosko de Marcaje por Huella Digital (Linux, Java/Swing).
 * Port del kiosk.py: identifica con el servicio local fingerprint_service.py y
 * registra la marca consumiendo las APIs /apis/biometria/kiosko/*.php (sin login web).
 */
public final class Main {

    public static final String APP_VERSION = "1.8.6";
    public static final String BUILD_DATE  = "2026-07-24 23:30";

    // Lock de INSTANCIA ÚNICA: se mantiene abierto mientras viva la app. Si otro
    // proceso ya tiene el puerto, es que el kiosko ya está abierto -> en vez de abrir
    // otro, le AVISA al que ya corre para que se muestre al frente (puede estar oculto/
    // minimizado sin icono de bandeja en FactuPOS OS) y este sale.
    private static ServerSocket SINGLE_LOCK;
    // Puerto del lock FUERA del rango efímero de Linux (32768-60999): si estuviera
    // dentro, VS Code/navegadores podrían robárselo al pedir "un puerto libre" y el
    // kiosko creería que ya hay otra instancia -> "no abre nada". 18181 < 32768.
    private static final int SINGLE_PORT = 18181;
    private static volatile KioskFrame INSTANCE;   // la ventana viva (para traerla al frente)

    public static void main(String[] args) {
        // Evitar múltiples instancias (abrir 2 veces desde el Escritorio abría varias).
        try {
            SINGLE_LOCK = new ServerSocket(SINGLE_PORT, 1, InetAddress.getByName("127.0.0.1"));
        } catch (Exception e) {
            // Ya hay un kiosko corriendo: conectarse al puerto le pide que se muestre, y salir.
            try (java.net.Socket s = new java.net.Socket()) {
                s.connect(new java.net.InetSocketAddress("127.0.0.1", SINGLE_PORT), 1500);
            } catch (Exception ignored) {}
            System.exit(0);
            return;
        }

        Config cfg = new Config();
        Log.init(cfg.logsDir);
        try {
            cfg.load();
        } catch (Exception e) {
            // config.json roto: igual seguimos para ABRIR LA VENTANA; el token se
            // configura como segundo paso adentro (botón Config / diálogo inicial).
            Log.i("config.json invalido (se usa default): " + e.getMessage());
        }
        // NOTA: aunque NO haya token todavía (cfg.recienCreado), PRIMERO se abre la
        // ventana; el pedido del token es un SEGUNDO paso dentro (start() -> openTokenConfig).

        Log.i("============================================================");
        Log.i("FactuPOS Biometria - Kiosko Linux v" + APP_VERSION + " (build " + BUILD_DATE + ")");
        Log.i("  " + (cfg.token.isEmpty() ? ("db:" + (cfg.db.isEmpty() ? "(vacio)" : cfg.db))
                                          : ("token:" + cfg.token.substring(0, Math.min(24, cfg.token.length())) + "..."))
              + " | api_bases=" + cfg.apiBases + " | fp=" + cfg.fpServiceUrl);

        // L&F multiplataforma (Metal), NO el del sistema: el L&F GTK de Linux IGNORA
        // setBackground/setForeground en botones, campos de texto y combos, y los pinta
        // con el tema del sistema (oscuro en FactuPOS OS) => texto invisible / negro
        // sobre negro. El kiosko usa su propia paleta blanca, que Metal sí respeta.
        try { UIManager.setLookAndFeel(UIManager.getCrossPlatformLookAndFeelClassName()); }
        catch (Exception ignored) {}

        boolean minimized = false;
        for (String a : args) {
            if ("--minimized".equals(a) || "--tray".equals(a) || "--oculto".equals(a)) minimized = true;
        }
        final boolean startMin = minimized;
        SwingUtilities.invokeLater(() -> {
            KioskFrame kf = new KioskFrame(cfg, startMin);
            INSTANCE = kf;
            kf.start();
        });

        // Escuchar a otras instancias: si alguien abre el kiosko de nuevo, traemos
        // esta ventana al frente (puede estar oculta sin icono de bandeja).
        startSingleInstanceListener();

        // Auto-actualización del kiosko (chequea a los 20 s y cada 1 h).
        Updater.startAuto();
    }

    private static void startSingleInstanceListener() {
        Thread t = new Thread(() -> {
            while (true) {
                try {
                    java.net.Socket s = SINGLE_LOCK.accept();
                    try { s.close(); } catch (Exception ignored) {}
                    KioskFrame kf = INSTANCE;
                    if (kf != null) SwingUtilities.invokeLater(kf::showToFront);
                } catch (Exception e) {
                    break;   // socket cerrado (p.ej. al auto-actualizar) -> terminar el hilo
                }
            }
        }, "single-instance-listener");
        t.setDaemon(true);
        t.start();
    }

    /** Libera el lock de instancia única (para que la nueva instancia pueda arrancar al auto-actualizar). */
    public static void releaseSingleLock() {
        try { if (SINGLE_LOCK != null) SINGLE_LOCK.close(); } catch (Exception ignored) {}
    }

    private static void showAndExit(String title, String msg) {
        try {
            JOptionPane.showMessageDialog(null, msg, title, JOptionPane.INFORMATION_MESSAGE);
        } catch (Exception e) {
            System.out.println(title + ": " + msg);
        }
    }

    private Main() {}
}
