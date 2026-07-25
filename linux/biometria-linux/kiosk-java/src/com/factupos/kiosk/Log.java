package com.factupos.kiosk;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/** Logger simple: imprime a stdout y agrega a logs/kiosk-YYYY-MM-DD.log */
public final class Log {

    private static Path logsDir = null;
    private static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final DateTimeFormatter DAY = DateTimeFormatter.ofPattern("yyyy-MM-dd");

    public static void init(Path dir) { logsDir = dir; }

    public static synchronized void i(String msg) {
        String line = "[" + LocalDateTime.now().format(TS) + "] " + msg;
        System.out.println(line);
        if (logsDir != null) {
            try {
                Files.createDirectories(logsDir);
                Path f = logsDir.resolve("kiosk-" + LocalDate.now().format(DAY) + ".log");
                Files.write(f, (line + "\n").getBytes(StandardCharsets.UTF_8),
                        StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            } catch (IOException e) { /* ignore */ }
        }
    }

    public static void e(String msg, Throwable t) {
        StringWriter sw = new StringWriter();
        if (t != null) t.printStackTrace(new PrintWriter(sw));
        i(msg + (t != null ? ("\n" + sw) : ""));
    }

    public static String trace(Throwable t) {
        StringWriter sw = new StringWriter();
        if (t != null) t.printStackTrace(new PrintWriter(sw));
        return sw.toString();
    }

    private Log() {}
}
