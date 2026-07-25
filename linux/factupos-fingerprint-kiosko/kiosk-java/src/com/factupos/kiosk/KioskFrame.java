package com.factupos.kiosk;

import java.awt.*;
import java.awt.datatransfer.StringSelection;
import java.awt.event.KeyEvent;
import java.awt.image.BufferedImage;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.swing.*;
import javax.swing.plaf.basic.BasicButtonUI;

/**
 * Ventana principal del kiosko + worker loop + dialogos (enroll, token, error).
 * Port de KioskApp (kiosk.py) a Swing.
 */
public final class KioskFrame {

    // Paleta — TEMA BLANCO (texto oscuro sobre fondo blanco)
    static final Color BG        = hex("#ffffff");   // fondo principal
    static final Color HDR       = hex("#eef2f7");   // header / botones suaves
    static final Color FG_DIM    = hex("#475569");   // texto secundario
    static final Color FG_MUTE   = hex("#94a3b8");   // texto tenue / desconectado
    static final Color FG_LIGHT  = hex("#1e293b");   // texto principal
    static final Color FG_WHITE  = hex("#0f172a");   // texto destacado (nombre)
    static final Color GREEN     = hex("#16a34a");
    static final Color BLUE      = hex("#0284c7");
    static final Color RED       = hex("#dc2626");
    static final Color AMBER     = hex("#d97706");
    static final Color SLATE     = hex("#e2e8f0");   // fondo de botón secundario (claro)
    // Escala global de tipografía (letra grande)
    static final double FSCALE   = 1.40;
    static final DateTimeFormatter HMS = DateTimeFormatter.ofPattern("HH:mm:ss");

    private final Config cfg;
    private final Api api;
    private final FpClient fp;
    private String serverdb;

    private volatile boolean running = true;
    private volatile boolean enrolling = false;
    private volatile boolean hasEnrollDialog = false;
    private volatile long lastSyncMs = 0;
    private volatile boolean fpConnected = false;
    private volatile String fpDevice = "";
    private volatile int usersLoaded = 0;
    /** Ultimo error del servidor al conectarse (token invalido, empresa inexistente, etc).
     *  Vacio = todo bien. Se muestra en la barra de estado y NO lo pisa refreshFpConnection(),
     *  que antes lo borraba a los 3 segundos y dejaba la pantalla muda. */
    private volatile String apiError = "";
    private long disconnectedSince = 0;   // ms desde que el lector quedó no-detectado
    private long lastAutoRestart = 0;     // ms del último reinicio automático

    // UI
    private JFrame frame;
    private JLabel led, lblStatus, lblClock, lblCompany, lblDb, lblFp, lblMsg;
    private JLabel lblResAction, lblResName, lblResTime;
    private boolean isFullscreen;
    private TrayIcon trayIcon;
    private JButton btnReconnect;
    private final boolean startMinimized;

    // Clave para Config y Salir (hardcodeada a pedido)
    private static final String CLAVE = "arp55888";

    public KioskFrame(Config cfg, boolean startMinimized) {
        this.cfg = cfg;
        this.startMinimized = startMinimized;
        this.api = new Api(cfg);
        this.fp = new FpClient(cfg.fpServiceUrl);
        this.serverdb = cfg.serverdb();
        buildUi();
    }

    public void start() {
        setupTray();
        frame.setVisible(true);
        if (startMinimized) frame.setExtendedState(Frame.ICONIFIED);
        startClock();
        Thread t = new Thread(this::worker, "worker");
        t.setDaemon(true);
        t.start();
        if (cfg.token.isEmpty() && cfg.db.isEmpty()) {
            // Primera configuración (aún sin token): se abre directo, SIN pedir clave.
            Timer tm = new Timer(500, e -> openTokenConfig());
            tm.setRepeats(false);
            tm.start();
        }
    }

    /** Restaura y trae la ventana al frente (la llama otra instancia al intentar abrir el kiosko). */
    public void showToFront() {
        if (frame == null) return;
        frame.setVisible(true);
        frame.setExtendedState(frame.getExtendedState() & ~Frame.ICONIFIED);   // des-minimizar
        frame.toFront();
        frame.setAlwaysOnTop(true);
        frame.setAlwaysOnTop(false);   // pulso para forzar el foco en algunos WM
        frame.requestFocus();
    }

    // ---------------- UI ----------------
    private void buildUi() {
        frame = new JFrame("FactuPOS - " + cfg.titulo + " (v" + Main.APP_VERSION + ")");
        setWindowIcon(frame);
        frame.setDefaultCloseOperation(JFrame.DO_NOTHING_ON_CLOSE);
        frame.addWindowListener(new java.awt.event.WindowAdapter() {
            // La X NO cierra: solo minimiza a la barra de tareas (el kiosko sigue corriendo).
            @Override public void windowClosing(java.awt.event.WindowEvent e) {
                ocultarATray();
            }
            // Minimizar tambien la saca de la barra. Sin esto, el boton de
            // minimizar la dejaba ahi abajo igual que antes.
            // Solo si HAY bandeja: si no, ocultarATray() minimizaria otra vez y
            // este mismo evento volveria a dispararse en bucle.
            @Override public void windowIconified(java.awt.event.WindowEvent e) {
                if (trayIcon != null) frame.setVisible(false);
            }
        });
        isFullscreen = cfg.fullscreen;
        if (isFullscreen) frame.setUndecorated(true);
        Dimension dim = parseGeo(cfg.ventana);
        frame.setSize(dim);
        frame.setMinimumSize(new Dimension(360, 520));
        frame.setLocationRelativeTo(null);
        Container root = frame.getContentPane();
        root.setBackground(BG);
        root.setLayout(new BorderLayout());

        // Header (apilado vertical: 1) nombre del lector  2) reloj DEBAJO — sin solaparse)
        JPanel hdr = new JPanel();
        hdr.setBackground(HDR);
        hdr.setLayout(new BoxLayout(hdr, BoxLayout.Y_AXIS));
        hdr.setBorder(BorderFactory.createEmptyBorder(8, 14, 8, 14));
        JPanel hl = new JPanel(new FlowLayout(FlowLayout.LEFT, 8, 0));
        hl.setOpaque(false); hl.setAlignmentX(Component.LEFT_ALIGNMENT);
        led = new JLabel("●"); led.setForeground(FG_MUTE); led.setFont(font(14));
        lblStatus = new JLabel("Conectando..."); lblStatus.setForeground(FG_DIM); lblStatus.setFont(font(12));
        hl.add(led); hl.add(lblStatus);
        hdr.add(hl);
        JPanel cl = new JPanel(new FlowLayout(FlowLayout.LEFT, 8, 0));
        cl.setOpaque(false); cl.setAlignmentX(Component.LEFT_ALIGNMENT);
        lblClock = new JLabel("--:--:--"); lblClock.setForeground(FG_LIGHT); lblClock.setFont(mono(15, true));
        cl.add(lblClock);
        hdr.add(cl);
        root.add(hdr, BorderLayout.NORTH);

        // Centro
        JPanel mid = new JPanel();
        mid.setBackground(BG);
        mid.setLayout(new BoxLayout(mid, BoxLayout.Y_AXIS));
        mid.setBorder(BorderFactory.createEmptyBorder(14, 16, 8, 16));

        JPanel tituloRow = new JPanel(new FlowLayout(FlowLayout.CENTER, 8, 0));
        tituloRow.setOpaque(false);
        lblCompany = new JLabel(cfg.titulo); lblCompany.setForeground(hex("#cbd5e1")); lblCompany.setFont(font(15, true));
        JLabel verPill = new JLabel(" v" + Main.APP_VERSION + " ");
        verPill.setOpaque(true); verPill.setBackground(hex("#ffff00")); verPill.setForeground(Color.BLACK); verPill.setFont(font(10, true));
        tituloRow.add(lblCompany); tituloRow.add(verPill);
        addCentered(mid, tituloRow);

        String ident = !cfg.token.isEmpty() ? ("Token: " + serverdb)
                     : (!cfg.db.isEmpty() ? ("Empresa: " + cfg.db) : "(sin configurar)");
        lblDb = label(ident, FG_MUTE, font(10)); addCentered(mid, lblDb);

        mid.add(Box.createVerticalStrut(10));
        lblFp = new JLabel("🖊"); lblFp.setForeground(FG_MUTE); lblFp.setFont(font(56));
        addCentered(mid, lblFp);
        lblMsg = label("Coloque su dedo en el lector", FG_DIM, font(13));
        lblMsg.setHorizontalAlignment(SwingConstants.CENTER);
        addCentered(mid, lblMsg);

        // Botón que aparece SOLO cuando el lector no está detectado
        btnReconnect = flatButton("↻ Reiniciar servicio del lector", hex("#0284c7"), Color.WHITE);
        btnReconnect.setFont(font(13, true));
        btnReconnect.addActionListener(e -> serviceAction("restart"));
        btnReconnect.setVisible(false);
        mid.add(Box.createVerticalStrut(8));
        addCentered(mid, btnReconnect);

        mid.add(Box.createVerticalStrut(6));
        lblResAction = label("", FG_LIGHT, font(12, true)); addCentered(mid, lblResAction);
        lblResName = label("", FG_WHITE, font(20, true)); addCentered(mid, lblResName);
        lblResTime = label("", FG_DIM, font(10)); addCentered(mid, lblResTime);
        mid.add(Box.createVerticalGlue());
        root.add(mid, BorderLayout.CENTER);

        // Footer
        JPanel ftr = new JPanel();
        ftr.setBackground(BG);
        ftr.setLayout(new BoxLayout(ftr, BoxLayout.Y_AXIS));
        ftr.setBorder(BorderFactory.createEmptyBorder(0, 8, 8, 8));
        JPanel btns = new JPanel(new FlowLayout(FlowLayout.CENTER, 6, 0));
        btns.setOpaque(false);
        JButton btnEnroll = flatButton("✋ Registrar huella", HDR, FG_LIGHT);
        btnEnroll.addActionListener(e -> openEnroll());
        JButton btnCfg = flatButton("⚙ Config", HDR, FG_DIM);
        btnCfg.addActionListener(e -> { if (askPassword()) openTokenConfig(); });
        JButton btnUpd = flatButton("⟳ Actualizar", HDR, FG_DIM);
        btnUpd.addActionListener(e -> checkUpdateManual());
        JButton btnExit = flatButton("⏻ Salir", hex("#fee2e2"), RED);
        btnExit.addActionListener(e -> exitApp());
        btns.add(btnEnroll); btns.add(btnCfg); btns.add(btnUpd); btns.add(btnExit);
        addCentered(ftr, btns);
        JLabel verLine = label("v" + Main.APP_VERSION + "  ·  build " + Main.BUILD_DATE, BLUE, font(10, true));
        addCentered(ftr, verLine);
        JLabel tipLine = label("Esc = pantalla completa   ·   la X minimiza   ·   Salir/F10 = cerrar", FG_MUTE, font(8));
        addCentered(ftr, tipLine);
        root.add(ftr, BorderLayout.SOUTH);

        // Atajos
        // ESCAPE oculta a la bandeja. Antes llamaba a toggleFullscreen(), o sea
        // que al tocarla la ventana se MAXIMIZABA en vez de quitarse de encima,
        // que es lo contrario de lo que espera el usuario del marcador.
        bindKey("ESCAPE", this::ocultarATray);
        bindKey("F10", this::exitApp);

        if (isFullscreen) frame.setExtendedState(Frame.MAXIMIZED_BOTH);
    }

    private void bindKey(String ks, Runnable r) {
        JRootPane rp = frame.getRootPane();
        rp.getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW).put(KeyStroke.getKeyStroke(ks), ks);
        rp.getActionMap().put(ks, new AbstractAction() {
            @Override public void actionPerformed(java.awt.event.ActionEvent e) { r.run(); }
        });
    }

    private void toggleFullscreen() {
        isFullscreen = !isFullscreen;
        frame.setExtendedState(isFullscreen ? Frame.MAXIMIZED_BOTH : Frame.NORMAL);
    }

    /** Botón "⟳ Actualizar": chequea el manifiesto y, si hay versión nueva, baja y reinicia. */
    private void checkUpdateManual() {
        setStatus("Buscando actualizaciones del kiosko...");
        new Thread(() -> {
            Updater.R r = Updater.check(true);
            ui(() -> {
                setStatus("Listo");
                if (r.updated) {
                    JOptionPane.showMessageDialog(frame, r.msg,
                            "FactuPOS FingerPrint Kiosko", JOptionPane.INFORMATION_MESSAGE);
                    Updater.restart();
                } else {
                    boolean hayNueva = r.latest != null && Updater.cmp(r.latest, Main.APP_VERSION) > 0;
                    JOptionPane.showMessageDialog(frame, r.msg, "FactuPOS FingerPrint Kiosko",
                            hayNueva ? JOptionPane.WARNING_MESSAGE : JOptionPane.INFORMATION_MESSAGE);
                }
            });
        }, "update-manual").start();
    }

    private void startClock() {
        Timer t = new Timer(1000, e -> lblClock.setText(LocalTime.now().format(HMS)));
        t.start();
    }

    // helpers UI-thread
    private void ui(Runnable r) { SwingUtilities.invokeLater(r); }
    private void setLed(Color c)     { ui(() -> led.setForeground(c)); }
    private void setStatus(String t) { ui(() -> lblStatus.setText(t)); }
    private void setMsg(String t)    { ui(() -> lblMsg.setText(t)); }
    private void setFpColor(Color c) { ui(() -> lblFp.setForeground(c)); }

    private void showResult(String action, String name, String kind, String subtitle) {
        Color col = kindColor(kind);
        String t = LocalTime.now().format(HMS);
        ui(() -> {
            lblFp.setText(("ok".equals(kind) || "exit".equals(kind)) ? "✓" : "✗");
            lblFp.setForeground(col);
            lblMsg.setText("");
            lblResAction.setText(action); lblResAction.setForeground(col);
            lblResName.setText(name);
            lblResTime.setText(subtitle != null ? (subtitle + "   ·   " + t) : t);
        });
    }

    private void clearResult() {
        ui(() -> {
            lblFp.setText("🖊");
            lblFp.setForeground(fpConnected ? GREEN : FG_MUTE);
            lblResAction.setText(""); lblResName.setText(""); lblResTime.setText("");
            lblMsg.setText(fpConnected ? "Coloque su dedo en el lector" : "Lector no detectado");
        });
    }

    // ---------------- Worker ----------------
    private void worker() {
        boolean warned = false;
        while (running && cfg.token.isEmpty() && cfg.db.isEmpty()) {
            if (!warned) {
                setLed(FG_MUTE); setFpColor(FG_MUTE);
                setStatus("Sin token configurado");
                setMsg("Pulsa «⚙ Config» y pega el token generado en la web (Biometría → Configurar Kiosko)");
                warned = true;
            }
            sleep(1000);
        }
        if (!running) return;
        waitFpService();
        syncTemplates(true);
        while (running) {
            try {
                if (enrolling) { sleep(400); continue; }
                if (System.currentTimeMillis() - lastSyncMs > cfg.refreshMinutos * 60_000L) syncTemplates(false);
                refreshFpConnection();
                if (!fpConnected) {
                    setLed(FG_MUTE); setStatus("Lector no detectado"); setFpColor(FG_MUTE);
                    updateTray(false);                          // tray rojo
                    ui(() -> btnReconnect.setVisible(true));   // mostrar botón Reiniciar servicio
                    long now = System.currentTimeMillis();
                    if (disconnectedSince == 0) disconnectedSince = now;
                    long downSecs = (now - disconnectedSince) / 1000;
                    // Auto-restart si lleva >10s caído (con enfriamiento de 25s entre intentos)
                    if (downSecs > 10 && now - lastAutoRestart > 25000) {
                        Log.i("Lector no detectado >10s -> reinicio automático del servicio");
                        setMsg("Lector no detectado — reiniciando servicio...");
                        serviceAction("restart", true);   // silencioso, sin clave
                        lastAutoRestart = now;
                        disconnectedSince = now;           // reiniciar conteo (dar tiempo al restart)
                    } else {
                        setMsg("Lector no detectado (" + downSecs + "s)");
                    }
                    sleep(3000); continue;
                }
                disconnectedSince = 0;                          // detectado -> resetear conteo
                updateTray(true);                               // tray verde
                ui(() -> btnReconnect.setVisible(false));      // ocultar botón
                Http.Resp r = fp.identify(10000, 15);
                if (r.status == 503) { setMsg("Sensor enfriando..."); sleep(5000); continue; }
                if (r.body == null || !r.ok()) { sleep(1000); continue; }
                if (Json.bool(r.body, "waiting")) { sleep(1200); continue; }
                if (Json.bool(r.body, "matched") && Json.str(r.body, "user_id") != null) {
                    doMarca(Json.str(r.body, "user_id"));
                    sleep(4000); clearResult();
                } else {
                    // Huella NO registrada: solo avisar con un toast (NO abrir la lista sola).
                    // La lista de registro se abre manualmente con «Registrar huella».
                    setLed(RED);
                    showResult("NO REGISTRADA", "Huella no reconocida", "err", null);
                    Sound.err();
                    showToast("✗ Huella no registrada", "No reconocida\nUsá «Registrar huella» para darla de alta", RED);
                    sleep(4000);
                    setLed(fpConnected ? GREEN : FG_MUTE); clearResult();
                }
            } catch (Exception e) {
                Log.e("Worker:", e); sleep(2000);
            }
        }
    }

    private void waitFpService() {
        setStatus("Conectando al servicio de huella...");
        for (int i = 0; i < 60; i++) {
            Http.Resp r = fp.status(3);
            if (r.body != null && r.ok()) return;
            sleep(1000);
        }
        setStatus("No se pudo contactar el servicio local de huella");
    }

    private void refreshFpConnection() {
        Http.Resp r = fp.getConnection(4);
        if (r.body != null && r.ok()) {
            fpConnected = Json.bool(r.body, "connected");
            fpDevice = Json.str(r.body, "device", "");
            if (fpConnected) {
                setLed(GREEN);
                // Si el servidor rechazo la conexion, ese mensaje MANDA sobre "Lector listo":
                // el lector puede estar perfecto y aun asi no haber bajado ninguna huella.
                setStatus(!apiError.isEmpty()
                        ? "✗ " + apiError
                        : ((fpDevice == null || fpDevice.isEmpty()) ? "Lector listo" : fpDevice) + "  ·  " + usersLoaded + " huella(s)");
                setFpColor(GREEN);
            }
        } else {
            fpConnected = false;
        }
    }

    @SuppressWarnings("unchecked")
    private void syncTemplates(boolean initial) {
        Http.Resp r = api.huellasListar();
        if (r.body == null || !r.ok()) {
            // El motivo REAL lo manda el servidor ("Token no registrado", "Empresa no
            // encontrada", ...). Antes solo iba al log y en pantalla salia un texto generico
            // una sola vez -> el usuario no tenia forma de saber que su token estaba malo.
            String err = (r.body != null) ? Json.str(r.body, "error", "sin respuesta") : "sin respuesta";
            Log.i("Sync plantillas FALLO: " + err);
            apiError = err;
            setStatus("✗ " + err);
            setMsg("No se pudo conectar con el servidor.\nRevisá el token en «⚙ Config».");
            return;
        }
        apiError = "";
        if (Json.bool(r.body, "needs_migration")) {
            Log.i("Falta la tabla HuellaUsuario (migracion 20260511104641) en " + serverdb);
            setStatus("Falta migracion HuellaUsuario en " + serverdb);
            return;
        }
        List<Object> huellas = Json.arr(r.body, "huellas");
        fp.printsClear(true, 10);
        if (!huellas.isEmpty()) {
            List<Map<String,Object>> payload = new ArrayList<>();
            for (Object o : huellas) {
                if (!(o instanceof Map)) continue;
                Map<String,Object> h = (Map<String,Object>) o;
                Map<String,Object> e = new LinkedHashMap<>();
                e.put("usuario_codigo", Json.str(h, "usuario_codigo"));
                e.put("dedo", Json.str(h, "dedo", "right-index"));
                e.put("template_b64", Json.str(h, "template_b64"));
                payload.add(e);
            }
            Http.Resp r2 = fp.printsImport(payload, true, 30);
            usersLoaded = (r2.body != null) ? Json.intVal(r2.body, "users", payload.size()) : payload.size();
        } else {
            usersLoaded = 0;
        }
        lastSyncMs = System.currentTimeMillis();
        Log.i("Plantillas sincronizadas: " + huellas.size() + " huella(s), " + usersLoaded + " usuario(s)");
    }

    private void doMarca(String usuarioCodigo) {
        setLed(AMBER); setFpColor(AMBER); setMsg("Registrando marca...");
        Http.Resp r = api.marcaRegistrar(usuarioCodigo);
        if (r.body != null && r.ok()) {
            Map<String,Object> marca = Json.obj(r.body, "marca");
            Map<String,Object> emp = Json.obj(r.body, "empleado");
            Map<String,Object> jor = Json.obj(r.body, "jornada");
            String tipoNombre = Json.str(marca, "tipo_nombre");
            if (tipoNombre == null) tipoNombre = "E".equals(Json.str(marca, "tipo")) ? "Entrada" : "Salida";
            String tipo = tipoNombre.toUpperCase();
            String name = Json.str(emp, "nombre", usuarioCodigo);
            String sub = null;
            String horas = Json.str(jor, "horas_trabajadas");
            if (horas != null && "SALIDA".equals(tipo)) sub = "Jornada: " + horas + " h";
            showResult(tipo, name, "SALIDA".equals(tipo) ? "exit" : "ok", sub);
            Sound.ok(); popupFront();
            showToast(("SALIDA".equals(tipo) ? "✓ " : "✓ ") + tipo, name + (sub != null ? "\n" + sub : ""),
                      "SALIDA".equals(tipo) ? BLUE : GREEN);
            Log.i("Marca OK: " + usuarioCodigo + " " + tipo + " (" + name + ")");
        } else {
            String err = (r.body != null) ? Json.str(r.body, "error", "No se pudo registrar la marca") : "No se pudo registrar la marca";
            boolean warn = err.toLowerCase().contains("esperar") || err.toLowerCase().contains("ultima marca");
            showResult(warn ? "YA MARCADO" : "ERROR", usuarioCodigo, warn ? "warn" : "err",
                    err.substring(0, Math.min(80, err.length())));
            Sound.err(); popupFront();
            showToast(warn ? "⚠ Ya marcado" : "✗ Error", warn ? usuarioCodigo : err.substring(0, Math.min(60, err.length())),
                      warn ? AMBER : RED);
            Log.i("Marca FALLO (" + usuarioCodigo + "): " + err);
        }
    }

    private void popupFront() {
        ui(() -> {
            try {
                if (isMinimized()) return;   // si está minimizado no lo traemos al frente (avisa el tray)
                frame.setAlwaysOnTop(true); frame.toFront();
                Timer t = new Timer(1800, e -> frame.setAlwaysOnTop(false)); t.setRepeats(false); t.start();
            } catch (Exception ignored) {}
        });
    }

    private boolean isMinimized() {
        return !frame.isShowing() || (frame.getExtendedState() & Frame.ICONIFIED) != 0;
    }

    // ---------------- System Tray / salida ----------------
    private void setupTray() {
        if (!SystemTray.isSupported()) { Log.i("SystemTray no soportado en este entorno"); return; }
        try {
            PopupMenu menu = new PopupMenu();
            MenuItem miOpen = new MenuItem("Abrir"); miOpen.addActionListener(e -> showWindow());
            MenuItem miExit = new MenuItem("Salir");  miExit.addActionListener(e -> exitApp());
            menu.add(miOpen); menu.addSeparator(); menu.add(miExit);
            trayIcon = new TrayIcon(makeTrayImage(FG_MUTE), "FactuPOS Kiosko Huella", menu);
            trayIcon.setImageAutoSize(true);
            trayIcon.addActionListener(e -> showWindow());   // click / doble click -> abrir normal
            SystemTray.getSystemTray().add(trayIcon);
        } catch (Exception e) {
            Log.e("No se pudo crear el tray icon", e);
        }
    }

    /** Quita la ventana de en medio: se va a la bandeja y DESAPARECE de la barra
     *  de tareas. Antes se usaba ICONIFIED, que la minimiza pero la DEJA ocupando
     *  un lugar en la lista de ventanas de abajo — el usuario veia "FactuPOS -
     *  Marcaje de Asistencia" ahi todo el dia. setVisible(false) la saca del todo.
     *
     *  Si NO hay bandeja (SystemTray no soportado, o el add() fallo y trayIcon
     *  quedo en null) se minimiza como antes: esconder la ventana sin dejar un
     *  icono para recuperarla la volveria inalcanzable. */
    private void ocultarATray() {
        if (trayIcon != null) {
            frame.setVisible(false);
        } else {
            Log.i("Sin bandeja del sistema: se minimiza en vez de ocultar");
            frame.setExtendedState(Frame.ICONIFIED);
        }
    }

    private void showWindow() {
        ui(() -> {
            frame.setExtendedState(Frame.NORMAL);
            frame.setVisible(true);
            frame.toFront();
            frame.requestFocus();
        });
    }

    private Image makeTrayImage(Color c) {
        int s = 32;
        BufferedImage bi = new BufferedImage(s, s, BufferedImage.TYPE_INT_ARGB);
        Graphics2D g = bi.createGraphics();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.setColor(c); g.fillOval(1, 1, s - 2, s - 2);
        g.setColor(Color.WHITE); g.setFont(new Font("SansSerif", Font.BOLD, 18));
        g.drawString("H", 10, 23);
        g.dispose();
        return bi;
    }

    private Boolean lastTrayConn = null;
    /** Cambia el ícono de la bandeja: verde = lector conectado, rojo = no detectado. */
    private void updateTray(boolean connected) {
        if (trayIcon == null) return;
        if (lastTrayConn != null && lastTrayConn == connected) return;
        lastTrayConn = connected;
        ui(() -> {
            trayIcon.setImage(makeTrayImage(connected ? GREEN : RED));
            trayIcon.setToolTip("FactuPOS Huella — " + (connected ? "lector conectado" : "lector NO detectado"));
        });
    }

    private void notifyMark(String title, String body) {
        if (trayIcon != null && isMinimized()) {
            try { trayIcon.displayMessage(title, body, TrayIcon.MessageType.INFO); } catch (Exception ignored) {}
        }
    }

    /** Toast propio: ventanita en la esquina inferior derecha (cerca del reloj),
     *  visible aunque el kiosko esté minimizado. Desaparece sola a los ~4.5s. */
    private void showToast(String title, String body, Color color) {
        ui(() -> {
            try {
                JWindow w = new JWindow();
                w.setAlwaysOnTop(true);
                JPanel p = new JPanel();
                p.setBackground(color);
                p.setBorder(BorderFactory.createCompoundBorder(
                        BorderFactory.createLineBorder(color.darker(), 2),
                        BorderFactory.createEmptyBorder(14, 22, 14, 22)));
                p.setLayout(new BoxLayout(p, BoxLayout.Y_AXIS));
                JLabel lt = new JLabel(title);
                lt.setForeground(Color.WHITE); lt.setFont(font(18, true));
                lt.setAlignmentX(Component.LEFT_ALIGNMENT);
                p.add(lt);
                for (String line : body.split("\n")) {
                    JLabel lb = new JLabel(line);
                    lb.setForeground(Color.WHITE); lb.setFont(font(14, true));
                    lb.setAlignmentX(Component.LEFT_ALIGNMENT);
                    p.add(lb);
                }
                JLabel lh = new JLabel(LocalTime.now().format(HMS));
                lh.setForeground(new Color(255, 255, 255, 210)); lh.setFont(font(11));
                lh.setAlignmentX(Component.LEFT_ALIGNMENT);
                p.add(lh);
                w.setContentPane(p);
                w.pack();
                Rectangle scr = GraphicsEnvironment.getLocalGraphicsEnvironment().getMaximumWindowBounds();
                int x = scr.x + scr.width - w.getWidth() - 24;
                int y = scr.y + scr.height - w.getHeight() - 24;   // esquina inferior derecha (cerca del reloj)
                w.setLocation(x, y);
                w.setVisible(true);
                w.toFront();
                Timer t = new Timer(4500, e -> w.dispose());
                t.setRepeats(false);
                t.start();
            } catch (Exception e) {
                Log.e("toast", e);
            }
        });
    }

    /** Pide la clave; true si es correcta. */
    private boolean askPassword() {
        JPasswordField pf = new JPasswordField();
        pf.setFont(font(13));
        int r = JOptionPane.showConfirmDialog(frame, pf, "Ingrese la clave",
                JOptionPane.OK_CANCEL_OPTION, JOptionPane.PLAIN_MESSAGE);
        if (r != JOptionPane.OK_OPTION) return false;
        boolean ok = CLAVE.equals(new String(pf.getPassword()));
        if (!ok) JOptionPane.showMessageDialog(frame, "Clave incorrecta", "Acceso denegado", JOptionPane.ERROR_MESSAGE);
        return ok;
    }

    /** Reinicia/detiene/inicia el servicio del lector vía sudo (regla NOPASSWD del .deb).
     *  quiet=true -> sin diálogo (para el reinicio automático). */
    private void serviceAction(String action) { serviceAction(action, false); }

    private void serviceAction(String action, boolean quiet) {
        new Thread(() -> {
            try {
                Process p = new ProcessBuilder("sudo", "-n", "systemctl", action, "factupos-fingerprint-servicio")
                        .redirectErrorStream(true).start();
                String out = new String(p.getInputStream().readAllBytes()).trim();
                int code = p.waitFor();
                Log.i("systemctl " + action + " -> " + code + " " + out);
                if (!quiet) {
                    final String msg = (code == 0)
                            ? "Servicio: " + action + " OK"
                            : ("No se pudo (" + code + ").\n" + (out.isEmpty()
                                ? "Falta el permiso sudo (reinstalá el .deb del kiosko)." : out));
                    ui(() -> JOptionPane.showMessageDialog(frame, msg, "Servicio de huella",
                            code == 0 ? JOptionPane.INFORMATION_MESSAGE : JOptionPane.ERROR_MESSAGE));
                }
            } catch (Exception e) {
                if (!quiet) ui(() -> JOptionPane.showMessageDialog(frame, "Error: " + e.getMessage(),
                        "Servicio de huella", JOptionPane.ERROR_MESSAGE));
                else Log.e("svc " + action, e);
            }
        }, "svc-" + action).start();
    }

    /** Cierra de verdad (pide clave). Lo usan el botón Salir, F10 y el tray. */
    private void exitApp() {
        if (!askPassword()) return;
        running = false;
        try { if (trayIcon != null) SystemTray.getSystemTray().remove(trayIcon); } catch (Exception ignored) {}
        frame.dispose();
        System.exit(0);
    }

    // ---------------- Token / Config ----------------
    private void applyToken(String tok, String dispositivoId, List<String> apiBases) {
        tok = tok == null ? "" : tok.trim();
        cfg.token = tok;
        api.token = tok;
        serverdb = tok.contains("~") ? tok.substring(0, tok.indexOf('~')) : (cfg.db == null ? "" : cfg.db);
        if (dispositivoId != null && !dispositivoId.trim().isEmpty()) cfg.dispositivoId = dispositivoId.trim();
        if (apiBases != null && !apiBases.isEmpty()) { api.apiBases = apiBases; api.activeApi = apiBases.get(0); cfg.apiBases = apiBases; }
        lastSyncMs = 0;
        final String ident = !cfg.token.isEmpty() ? ("Token: " + serverdb)
                : (!cfg.db.isEmpty() ? ("Empresa: " + cfg.db) : "(sin configurar)");
        ui(() -> lblDb.setText(ident));
        setMsg("Token aplicado. Conectando...");
    }

    private void openTokenConfig() {
        JDialog d = baseDialog("Token / Configuracion del kiosko", 620, 620);
        JPanel body = (JPanel) d.getContentPane();

        // OJO: este dialogo tiene fondo BLANCO. Las etiquetas iban en gris claro (FG_DIM) y
        // practicamente no se leian. Todo el texto de aqui va en NEGRO/gris oscuro y mas grande.
        final Color TXT  = Color.BLACK;             // titulos de cada casilla
        final Color HINT = hex("#334155");          // explicaciones (gris oscuro, legible en blanco)

        body.add(title("Configuracion del kiosko"));
        body.add(label("Cada dato va en su casilla. Si te equivocas, al guardar te avisa.",
                HINT, font(12)));
        body.add(Box.createVerticalStrut(12));

        body.add(label("1 · TOKEN  —  dice a que empresa pertenece este kiosko", TXT, font(15, true)));
        body.add(label("Se genera en la web: FactuPOS → Biometria → Configurar Kiosko → «Generar token»",
                HINT, font(12)));
        body.add(label("Se ve asi:   empresa~a1b2c3d4e5f6...   (una sola linea, sin espacios)",
                HINT, font(12)));
        JTextField eTok = darkField(cfg.token); body.add(eTok);
        body.add(Box.createVerticalStrut(12));

        body.add(label("2 · NOMBRE DE ESTE PUESTO", TXT, font(15, true)));
        body.add(label("Solo para saber cual PC es.   Ejemplos:  k1   CAJA1   RECEPCION",
                HINT, font(12)));
        JTextField eDisp = darkField(cfg.dispositivoId); body.add(eDisp);
        body.add(Box.createVerticalStrut(12));

        body.add(label("3 · DIRECCIONES DEL SERVIDOR", TXT, font(15, true)));
        body.add(label("Dejalas como estan. Si se borran, se usan las de fabrica.",
                HINT, font(12)));
        JTextField eApi = darkField(String.join(", ", api.apiBases)); body.add(eApi);
        body.add(Box.createVerticalStrut(12));

        // --- Control del servicio del lector ---
        body.add(label("Servicio del lector:", Color.BLACK, font(13, true)));
        JPanel svcRow = new JPanel(new FlowLayout(FlowLayout.LEFT, 6, 0)); svcRow.setOpaque(false);
        JButton btnRestart = flatButton("↻ Reiniciar servicio", hex("#0284c7"), Color.WHITE);
        JButton btnStop    = flatButton("■ Detener servicio", hex("#fee2e2"), RED);
        JButton btnStart   = flatButton("▶ Iniciar servicio", hex("#dcfce7"), hex("#166534"));
        btnRestart.addActionListener(e -> serviceAction("restart"));
        btnStop.addActionListener(e -> serviceAction("stop"));
        btnStart.addActionListener(e -> serviceAction("start"));
        svcRow.add(btnRestart); svcRow.add(btnStart); svcRow.add(btnStop);
        addCentered(body, svcRow);
        body.add(Box.createVerticalStrut(8));

        JLabel msg = label("", hex("#b91c1c"), font(13, true)); body.add(msg);
        body.add(Box.createVerticalGlue());

        JPanel btns = new JPanel(new FlowLayout(FlowLayout.RIGHT, 8, 0)); btns.setOpaque(false);
        JButton cancel = flatButton("Cancelar", SLATE, FG_LIGHT);
        JButton save = flatButton("Guardar", hex("#16a34a"), Color.WHITE);
        cancel.addActionListener(e -> d.dispose());
        save.addActionListener(e -> {
            String tok = eTok.getText().trim();
            String disp = eDisp.getText().trim();
            List<String> apis = Config.normBasesCsv(eApi.getText());
            if (apis.isEmpty()) apis = new ArrayList<>(java.util.Arrays.asList("https://invefacon.net", "https://invefacon.com"));
            // --- Guardias contra el error mas comun: pegar el dato en la casilla equivocada ---
            if (tok.isEmpty()) { msg.setText("Casilla 1: pega el token, no puede quedar vacia."); return; }
            if (tok.startsWith("http") || tok.contains("/")) {
                msg.setText("Casilla 1: eso es una direccion del servidor. El token va sin http."); return;
            }
            if (!tok.contains("~")) {
                msg.setText("Casilla 1: el token esta incompleto. Debe ser  empresa~aleatorio."); return;
            }
            if (disp.contains("~")) {
                msg.setText("Casilla 2: eso parece el token. El token va en la casilla 1."); return;
            }
            if (eApi.getText().contains("~")) {
                msg.setText("Casilla 3: eso parece el token. El token va en la casilla 1."); return;
            }
            boolean okFile = true;
            try { cfg.writeTokenConf(tok); }
            catch (Exception ex) { okFile = false; msg.setText("No se pudo escribir token.conf: " + ex.getMessage()); }
            Map<String,Object> upd = new LinkedHashMap<>();
            upd.put("dispositivo_id", disp.isEmpty() ? "KIOSKO-01" : disp);
            upd.put("api_base", new ArrayList<Object>(apis));
            cfg.updateConfigJson(upd);
            applyToken(tok, disp, apis);
            if (okFile) d.dispose();
        });
        btns.add(save); btns.add(cancel);
        addCentered(body, btns);
        eTok.addActionListener(e -> save.doClick());
        d.setVisible(true);
    }

    // ---------------- Enroll ----------------
    private void openEnroll() {
        if (enrolling || hasEnrollDialog) return;
        hasEnrollDialog = true;
        JDialog d = baseDialog("Registrar huella", 520, 470);
        JPanel body = (JPanel) d.getContentPane();

        body.add(title("Registrar huella de empleado"));
        body.add(label(serverdb != null && !serverdb.isEmpty() ? ("Empresa: " + serverdb) : "", FG_MUTE, font(9)));
        body.add(Box.createVerticalStrut(10));

        body.add(label("Empleado:", hex("#cbd5e1"), font(11)));
        JComboBox<String> cmb = new JComboBox<>(); cmb.setFont(font(12)); cmb.setMaximumSize(new Dimension(9999, 36));
        cmb.setMaximumRowCount(18);   // mostrar más usuarios en la lista desplegable
        body.add(cmb);
        body.add(Box.createVerticalStrut(6));
        body.add(label("Dedo:", hex("#cbd5e1"), font(11)));
        JComboBox<String> dedo = new JComboBox<>(new String[]{"right-index", "right-thumb", "right-middle", "left-index", "left-thumb"});
        dedo.setSelectedItem(cfg.dedoDefault); dedo.setFont(font(11)); dedo.setMaximumSize(new Dimension(9999, 30));
        body.add(dedo);
        body.add(Box.createVerticalStrut(8));
        JLabel state = label("Cargando empleados...", FG_DIM, font(10)); body.add(state);
        body.add(Box.createVerticalGlue());

        final Map<String,Map<String,Object>> map = new LinkedHashMap<>();
        JPanel btns = new JPanel(new FlowLayout(FlowLayout.RIGHT, 8, 0)); btns.setOpaque(false);
        JButton cancel = flatButton("Cancelar", SLATE, FG_LIGHT);
        JButton startB = flatButton("Iniciar registro", hex("#16a34a"), Color.WHITE);
        startB.setEnabled(false);
        btns.add(startB); btns.add(cancel);
        addCentered(body, btns);

        cancel.addActionListener(e -> {
            if (enrolling) {
                state.setText("Cancelando...");
                new Thread(() -> fp.enrollCancel(4), "enroll-cancel").start();
            } else {
                d.dispose();
            }
        });
        cmb.addActionListener(e -> startB.setEnabled(cmb.getSelectedItem() != null));

        // cargar empleados
        new Thread(() -> {
            Http.Resp r = api.empleadosListar();
            if (r.body == null || !r.ok()) {
                ui(() -> state.setText("Error cargando empleados: " + (r.body != null ? Json.str(r.body, "error") : "sin respuesta")));
                return;
            }
            List<Object> emps = Json.arr(r.body, "empleados");
            String fuente = Json.str(r.body, "fuente", "");
            List<String> vals = new ArrayList<>();
            for (Object o : emps) {
                if (!(o instanceof Map)) continue;
                @SuppressWarnings("unchecked") Map<String,Object> e = (Map<String,Object>) o;
                String extra = "";
                if (Json.bool(e, "tiene_huella")) extra += "  ·  ya tiene huella";
                if (e.containsKey("en_empleados") && !Json.bool(e, "en_empleados")) extra += "  ·  ⚠ no figura en Empleados";
                String tag = Json.str(e, "cod_usuario") + " - " + Json.str(e, "nombre", "") + extra;
                vals.add(tag); map.put(tag, e);
            }
            ui(() -> {
                for (String v : vals) cmb.addItem(v);
                cmb.setSelectedIndex(-1);
                state.setText(vals.size() + " usuario(s) activo(s) [" + fuente + "]. Seleccione uno y pulse 'Iniciar registro'.");
            });
        }, "load-emps").start();

        startB.addActionListener(ev -> {
            String tag = (String) cmb.getSelectedItem();
            Map<String,Object> emp = tag == null ? null : map.get(tag);
            if (emp == null) return;
            String usuarioCodigo = Json.str(emp, "cod_usuario");
            String usuarioNombre = Json.str(emp, "nombre", usuarioCodigo);
            String finger = (String) dedo.getSelectedItem();
            if (finger == null) finger = "right-index";
            final String fFinger = finger;
            startB.setEnabled(false);
            cancel.setText("Cancelar registro");
            cmb.setEnabled(false); dedo.setEnabled(false);
            enrolling = true;
            ui(() -> state.setText("Coloque el dedo en el lector... esperando el toque 1"));
            setMsg("Registrando huella de " + usuarioNombre);
            setFpColor(AMBER); setLed(AMBER);

            new Thread(() -> runEnroll(d, state, usuarioCodigo, usuarioNombre, fFinger), "enroll").start();
        });

        d.setVisible(true);          // modal: bloquea hasta que se cierra
        hasEnrollDialog = false;     // SIEMPRE liberar el flag al cerrar (por X, Cancelar o éxito)
    }

    private void runEnroll(JDialog d, JLabel state, String usuarioCodigo, String usuarioNombre, String finger) {
        final Map<String,Http.Resp> result = new LinkedHashMap<>();
        Thread postT = new Thread(() -> result.put("data", fp.enroll(usuarioCodigo, finger, 240)), "enroll-post");
        postT.start();
        while (postT.isAlive()) {
            Http.Resp pg = fp.enrollProgress(4);
            if (pg.body != null && pg.ok()) {
                int done = Json.intVal(pg.body, "done", 0);
                int needed = Json.intVal(pg.body, "needed", 4);
                String msg = Json.str(pg.body, "msg", "");
                int shown = done < needed ? Math.min(done + 1, needed) : needed;
                ui(() -> state.setText(dots(done, needed) + "   (" + done + "/" + needed + ")\n" + msg));
                setMsg(usuarioNombre + " — toque " + shown + " de " + needed);
            }
            try { postT.join(600); } catch (InterruptedException ignored) {}
        }
        try {
            Http.Resp data = result.get("data");
            if (data == null || data.body == null || !data.ok()) {
                String msg = data != null && data.body != null ? Json.str(data.body, "error", "El registro de huella fallo") : "El registro de huella fallo";
                if (msg != null && msg.toLowerCase().contains("cancel")) { ui(d::dispose); return; }
                ui(() -> state.setText("FALLO: " + msg));
                showErrorCopiable("Registrar huella", msg, "error", d);
                return;
            }
            String templateB64 = Json.str(data.body, "template_b64", "");
            String serial = Json.str(data.body, "serial", "");
            ui(() -> state.setText("Huella capturada — guardando en la base de datos..."));
            Http.Resp r2 = api.huellaRegistrar(usuarioCodigo, finger, templateB64, serial);
            if (r2.body == null || !r2.ok()) {
                String msg = r2.body != null ? Json.str(r2.body, "error", "No se pudo guardar la huella en la base de datos") : "No se pudo guardar la huella";
                if (r2.body != null && Json.bool(r2.body, "needs_migration")) msg = "Falta la migracion HuellaUsuario (20260511104641)";
                final String fmsg = msg;
                ui(() -> state.setText("Huella capturada pero NO guardada: " + fmsg));
                showErrorCopiable("Registrar huella", msg, "warn", d);
                return;
            }
            Log.i("Huella registrada en BD: " + usuarioCodigo + "/" + finger + "/" + cfg.plataforma);
            ui(d::dispose);
            showResult("REGISTRADO", usuarioNombre, "ok", null);
            sleep(1200);
            doMarca(usuarioCodigo);
            sleep(3500); clearResult();
        } catch (Exception e) {
            String tb = Log.trace(e);
            Log.i("Enroll flow:\n" + tb);
            showErrorCopiable("Registrar huella", "Error inesperado:\n\n" + tb, "error", d);
        } finally {
            enrolling = false;
            setLed(fpConnected ? GREEN : FG_MUTE);
        }
    }

    private static String dots(int done, int needed) {
        done = Math.max(0, Math.min(done, needed));
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < done; i++) b.append('●');
        for (int i = 0; i < needed - done; i++) b.append('○');
        return b.toString();
    }

    // ---------------- Error dialog copiable ----------------
    private void showErrorCopiable(String title, String msg, String kind, Window parent) {
        ui(() -> {
            JDialog win = (parent instanceof Dialog)
                    ? new JDialog((Dialog) parent, title, true)
                    : new JDialog(frame, title, true);
            win.getContentPane().setBackground(BG);
            win.setLayout(new BorderLayout(0, 6));
            win.setSize(520, 320);
            win.setLocationRelativeTo(parent != null ? parent : frame);

            Color icoColor = "error".equals(kind) ? RED : ("warn".equals(kind) ? AMBER : BLUE);
            String icoText = "error".equals(kind) ? "✗" : ("warn".equals(kind) ? "⚠" : "ⓘ");
            JPanel hdr = new JPanel(new FlowLayout(FlowLayout.LEFT, 10, 8)); hdr.setBackground(BG);
            JLabel ico = label(icoText, icoColor, font(22, true));
            hdr.add(ico); hdr.add(label(title, FG_LIGHT, font(13, true)));
            win.add(hdr, BorderLayout.NORTH);

            JPanel center = new JPanel(new BorderLayout(0, 4)); center.setBackground(BG);
            center.setBorder(BorderFactory.createEmptyBorder(0, 14, 0, 14));
            String hint = hintForError(msg);
            if (hint != null) center.add(label("<html>" + hint.replace("\n", "<br>") + "</html>", hex("#fbbf24"), font(10)), BorderLayout.NORTH);
            JTextArea ta = new JTextArea(msg == null ? "" : msg);
            ta.setEditable(false); ta.setLineWrap(true); ta.setWrapStyleWord(true);
            ta.setBackground(HDR); ta.setForeground(FG_LIGHT); ta.setFont(mono(11, false));
            ta.setBorder(BorderFactory.createEmptyBorder(6, 8, 6, 8));
            center.add(new JScrollPane(ta), BorderLayout.CENTER);
            win.add(center, BorderLayout.CENTER);

            JPanel btns = new JPanel(new FlowLayout(FlowLayout.RIGHT, 8, 8)); btns.setBackground(BG);
            JButton copy = flatButton("📋 Copiar al portapapeles", hex("#2563eb"), Color.WHITE);
            final String fmsg = msg == null ? "" : msg;
            copy.addActionListener(e -> {
                try {
                    Toolkit.getDefaultToolkit().getSystemClipboard().setContents(new StringSelection(fmsg), null);
                    copy.setText("✓ Copiado"); copy.setBackground(hex("#16a34a"));
                    Timer t = new Timer(1500, ev -> { copy.setText("📋 Copiar al portapapeles"); copy.setBackground(hex("#2563eb")); });
                    t.setRepeats(false); t.start();
                } catch (Exception ignored) {}
            });
            JButton accept = flatButton("Aceptar", SLATE, Color.WHITE);
            accept.addActionListener(e -> win.dispose());
            btns.add(copy); btns.add(accept);
            win.add(btns, BorderLayout.SOUTH);

            win.getRootPane().registerKeyboardAction(e -> win.dispose(),
                    KeyStroke.getKeyStroke(KeyEvent.VK_ESCAPE, 0), JComponent.WHEN_IN_FOCUSED_WINDOW);
            win.setVisible(true);
        });
    }

    private static String hintForError(String msg) {
        String m = msg == null ? "" : msg.toLowerCase();
        if (m.contains("connection refused") || m.contains("refused") || m.contains("10061"))
            return "El servicio local de huella no esta corriendo.\nVerifica: systemctl status factupos-fingerprint-servicio";
        if (m.contains("timed out") || m.contains("timeout") || m.contains("10060"))
            return "Tiempo agotado conectando al servicio. ¿Esta el lector conectado? ¿Otro proceso lo tiene tomado?";
        if (m.contains("needs_migration") || m.contains("huellausuario"))
            return "Falta aplicar la migracion HuellaUsuario (20260511104641) en esta empresa.";
        if (m.contains("no existe en empleados"))
            return "El usuario no figura en la tabla Empleados de la empresa. Agregalo primero desde el sistema web.";
        return null;
    }

    // ---------------- helpers de widgets ----------------
    private JDialog baseDialog(String title, int w, int h) {
        JDialog d = new JDialog(frame, title, true);
        d.setDefaultCloseOperation(JDialog.DISPOSE_ON_CLOSE);
        JPanel p = new JPanel();
        p.setBackground(BG);
        p.setLayout(new BoxLayout(p, BoxLayout.Y_AXIS));
        p.setBorder(BorderFactory.createEmptyBorder(16, 22, 14, 22));
        d.setContentPane(p);
        d.setSize(w, h);
        d.setLocationRelativeTo(frame);
        return d;
    }

    private JLabel title(String t) {
        JLabel l = label(t, FG_LIGHT, font(14, true));
        l.setBorder(BorderFactory.createEmptyBorder(0, 0, 6, 0));
        return l;
    }

    private static JLabel label(String t, Color fg, Font f) {
        JLabel l = new JLabel(t);
        l.setForeground(fg); l.setFont(f);
        l.setAlignmentX(Component.CENTER_ALIGNMENT);
        return l;
    }

    private JTextField darkField(String val) {
        JTextField tf = new JTextField(val == null ? "" : val);
        tf.setBackground(BG); tf.setForeground(FG_LIGHT); tf.setCaretColor(FG_LIGHT);
        tf.setFont(font(11));
        tf.setBorder(BorderFactory.createCompoundBorder(
                BorderFactory.createLineBorder(hex("#475569")),
                BorderFactory.createEmptyBorder(5, 6, 5, 6)));
        tf.setMaximumSize(new Dimension(9999, 34));
        tf.setAlignmentX(Component.CENTER_ALIGNMENT);
        return tf;
    }

    /** Carga el icono propio (instalado por el .deb) para la ventana / barra de tareas. */
    private static void setWindowIcon(JFrame f) {
        String[] paths = {
            "/usr/share/icons/hicolor/256x256/apps/factupos-fingerprint-kiosko.png",
            "/usr/share/icons/hicolor/128x128/apps/factupos-fingerprint-kiosko.png",
            "/usr/share/icons/hicolor/64x64/apps/factupos-fingerprint-kiosko.png",
        };
        java.util.List<Image> imgs = new ArrayList<>();
        for (String p : paths) {
            try {
                if (new java.io.File(p).exists()) {
                    Image im = new ImageIcon(p).getImage();
                    if (im != null) imgs.add(im);
                }
            } catch (Exception ignored) {}
        }
        if (!imgs.isEmpty()) {
            try { f.setIconImages(imgs); } catch (Exception ignored) {}
        }
    }

    private static JButton flatButton(String text, Color bg, Color fg) {
        JButton b = new JButton(text);
        // CLAVE: el L&F GTK (Linux) ignora setBackground/setForeground en los
        // JButton y los pinta con el tema nativo (oscuro en FactuPOS OS) => texto
        // invisible. BasicButtonUI + opaque hace que el botón pinte SUS colores.
        b.setUI(new BasicButtonUI());
        b.setBackground(bg); b.setForeground(fg);
        b.setOpaque(true); b.setContentAreaFilled(true);
        b.setFocusPainted(false); b.setBorderPainted(true);
        b.setFont(font(11)); b.setCursor(new Cursor(Cursor.HAND_CURSOR));
        // borde sutil para que el botón se delimite incluso si su fondo es claro
        b.setBorder(BorderFactory.createCompoundBorder(
            BorderFactory.createLineBorder(hex("#cbd5e1"), 1, true),
            BorderFactory.createEmptyBorder(7, 12, 7, 12)));
        return b;
    }

    private static void addCentered(JComponent parent, JComponent child) {
        child.setAlignmentX(Component.CENTER_ALIGNMENT);
        parent.add(child);
    }

    private static Dimension parseGeo(String geo) {
        try {
            String[] p = geo.toLowerCase().split("x");
            return new Dimension(Integer.parseInt(p[0].trim()), Integer.parseInt(p[1].trim()));
        } catch (Exception e) {
            return new Dimension(420, 640);
        }
    }

    private static Color kindColor(String kind) {
        switch (kind == null ? "" : kind) {
            case "ok":   return GREEN;
            case "exit": return BLUE;
            case "err":  return RED;
            case "warn": return AMBER;
            default:     return FG_LIGHT;
        }
    }

    private static Font font(int size) { return font(size, false); }
    private static Font font(int size, boolean bold) { return new Font("SansSerif", bold ? Font.BOLD : Font.PLAIN, (int) Math.round(size * FSCALE)); }
    private static Font mono(int size, boolean bold) { return new Font("Monospaced", bold ? Font.BOLD : Font.PLAIN, (int) Math.round(size * FSCALE)); }

    static Color hex(String h) {
        return new Color(Integer.parseInt(h.substring(1, 3), 16),
                         Integer.parseInt(h.substring(3, 5), 16),
                         Integer.parseInt(h.substring(5, 7), 16));
    }

    private static void sleep(long ms) {
        try { Thread.sleep(ms); } catch (InterruptedException ignored) {}
    }
}
