package com.factupos.printbridge;

import java.io.ByteArrayOutputStream;

/**
 * EscPos - Formateo del contenido que llega de la cola.
 *
 * Portado del cliente Python (Windows/Linux) para que el tiquete salga IGUAL en las
 * tres plataformas. Trabaja siempre con byte[]: el contenido de la cola son bytes
 * crudos y pasarlos por String/UTF-8 corrompe todo byte > 0x7F.
 *
 * Tres formas de contenido, detectadas igual que en el Python:
 *   1. VB6      -> trae los separadores 0xDF (campo) y 0xDD (fin de linea)
 *   2. ESC/POS  -> ya trae 0x1B / 0x1D, se manda tal cual
 *   3. Texto plano -> puede traer marcadores {{G}} {{B}} {{C}} {{D}} {{N}}
 *
 * DIFERENCIA DELIBERADA CON EL PYTHON: alla los marcadores se interpretan solo en el
 * camino ESC/P (matricial) y GDI; en termica nunca se tocaban porque el PHP ya mandaba
 * ESC/POS armado. En Android la mayoria de las impresoras son termicas y el contenido
 * de fipvivi003/004 llega con marcadores, asi que aca SI se traducen a ESC/POS. Sin
 * esto las llaves saldrian impresas literalmente en el papel.
 */
public class EscPos {

    // --- Comandos base ---
    public static final byte[] INIT         = {0x1B, 0x40};                    // ESC @
    public static final byte[] CUT_PAPER    = {0x1D, 0x56, 0x42, 0x03};        // GS V B 3
    public static final byte[] OPEN_DRAWER  = {0x1B, 0x70, 0x00, 0x19, 0x19};  // ESC p 0 25 25
    public static final byte[] FONT_A       = {0x1B, 0x4D, 0x00};              // ESC M 0
    public static final byte[] FONT_B       = {0x1B, 0x4D, 0x01};              // ESC M 1
    public static final byte[] CODEPAGE_437 = {0x1B, 0x74, 0x00};              // ESC t 0

    private static final byte[] ALIGN_LEFT   = {0x1B, 0x61, 0x00};
    private static final byte[] ALIGN_CENTER = {0x1B, 0x61, 0x01};
    private static final byte[] ALIGN_RIGHT  = {0x1B, 0x61, 0x02};
    private static final byte[] BOLD_ON      = {0x1B, 0x45, 0x01};
    private static final byte[] BOLD_OFF     = {0x1B, 0x45, 0x00};
    private static final byte[] SIZE_NORMAL  = {0x1B, 0x21, 0x00};             // ESC ! 0
    private static final byte[] SIZE_BIG     = {0x1B, 0x21, 0x30};             // ESC ! doble alto+ancho
    private static final byte[] LINE_SPACING = {0x1B, 0x33, 0x12};             // ESC 3 18 dots

    // Separadores del protocolo VB6
    private static final int VB6_DF = 0xDF;   // separador de campo
    private static final int VB6_DD = 0xDD;   // fin de linea
    private static final int VB6_E3 = 0xE3;   // sub-separador (dentro del codigo 3)

    private static final byte[] VB6_FONT_NORMAL = {0x1B, 0x21, 0x01};   // Font B normal

    // ------------------------------------------------------------------
    // Deteccion (misma logica que el Python)
    // ------------------------------------------------------------------

    /** VB6 si trae los DOS separadores: 0xDF de campo y 0xDD de fin de linea. */
    public static boolean isVb6(byte[] data) {
        if (data == null) return false;
        boolean df = false, dd = false;
        for (int i = 0; i < data.length; i++) {
            int b = data[i] & 0xFF;
            if (b == VB6_DF) df = true;
            else if (b == VB6_DD) dd = true;
            if (df && dd) return true;
        }
        return false;
    }

    /** Texto plano si NO trae ESC (0x1B) ni GS (0x1D) ni separadores VB6. */
    public static boolean isPlainText(byte[] data) {
        if (data == null) return false;
        for (int i = 0; i < data.length; i++) {
            int b = data[i] & 0xFF;
            if (b == 0x1B || b == 0x1D) return false;
        }
        return !isVb6(data);
    }

    public static boolean hasMarkers(byte[] data) {
        if (data == null) return false;
        String s = decodificar(data);
        return s.contains("{{G}}") || s.contains("{{B}}") || s.contains("{{C}}")
            || s.contains("{{D}}") || s.contains("{{N}}");
    }

    // ------------------------------------------------------------------
    // Texto plano + marcadores -> ESC/POS
    // ------------------------------------------------------------------

    /**
     * Traduce texto plano a ESC/POS aplicando los marcadores POR LINEA, igual que
     * plain_to_escp del Python: se activan al empezar la linea y se restauran al
     * terminarla, no son estados que se arrastran.
     */
    public static byte[] plainToEscPos(byte[] data) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        write(out, INIT);
        write(out, CODEPAGE_437);

        String texto = decodificar(data);
        String[] lineas = texto.split("\n", -1);

        for (int i = 0; i < lineas.length; i++) {
            String linea = lineas[i];
            if (linea.endsWith("\r")) linea = linea.substring(0, linea.length() - 1);

            boolean grande = linea.contains("{{G}}");
            boolean bold   = linea.contains("{{B}}");
            boolean centro = linea.contains("{{C}}");
            boolean derecha= linea.contains("{{D}}");

            String limpia = quitarMarcadores(linea);

            if (centro)  write(out, ALIGN_CENTER);
            else if (derecha) write(out, ALIGN_RIGHT);
            if (grande) write(out, SIZE_BIG);
            if (bold)   write(out, BOLD_ON);

            write(out, cp437(limpia));
            write(out, new byte[]{0x0A});

            if (bold)   write(out, BOLD_OFF);
            if (grande) write(out, SIZE_NORMAL);
            if (centro || derecha) write(out, ALIGN_LEFT);
        }
        return out.toByteArray();
    }

    private static String quitarMarcadores(String s) {
        return s.replace("{{G}}", "").replace("{{N}}", "").replace("{{B}}", "")
                .replace("{{C}}", "").replace("{{D}}", "");
    }

    // ------------------------------------------------------------------
    // VB6 -> ESC/POS  (port de vb6_to_escpos)
    // ------------------------------------------------------------------

    public static byte[] vb6ToEscPos(byte[] data, boolean cutPaper) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        write(out, INIT);
        write(out, LINE_SPACING);

        String texto = latin1(data);
        String[] lineas = texto.split(String.valueOf((char) VB6_DD));

        for (int i = 0; i < lineas.length; i++) {
            String linea = lineas[i].trim();
            if (linea.isEmpty()) continue;

            int sep = linea.indexOf((char) VB6_DF);
            if (sep < 0) continue;                      // linea sin separador: se ignora
            String codigo = linea.substring(0, sep).trim();
            String contenido = linea.substring(sep + 1);

            if ("3".equals(codigo)) {
                // "NombreFuente CPI<E3>tamano<E3>modo"
                int e3 = contenido.indexOf((char) VB6_E3);
                String nombre = (e3 >= 0 ? contenido.substring(0, e3) : contenido).trim().toLowerCase();
                write(out, fuenteVb6(nombre));

            } else if ("4".equals(codigo)) {
                write(out, VB6_FONT_NORMAL);
                write(out, ALIGN_LEFT);

            } else if ("1".equals(codigo)) {
                write(out, ALIGN_LEFT);
                write(out, cp437(contenido));
                write(out, new byte[]{0x0A});

            } else if ("13".equals(codigo)) {
                write(out, ALIGN_RIGHT);
                write(out, cp437(contenido));
                write(out, new byte[]{0x0A});
                write(out, ALIGN_LEFT);

            } else if ("14".equals(codigo)) {
                write(out, ALIGN_CENTER);
                write(out, cp437(contenido));
                write(out, new byte[]{0x0A});
                write(out, ALIGN_LEFT);

            } else if ("9".equals(codigo)) {
                write(out, new byte[]{0x0A, 0x0A, 0x0A});
                if (cutPaper) write(out, CUT_PAPER);
            }
        }
        return out.toByteArray();
    }

    /** Mapa de fuentes VB6 -> ESC ! n (mismos valores que ESCPOS_FONT_MAP del Python). */
    private static byte[] fuenteVb6(String nombre) {
        if ("draft 5cpi".equals(nombre))  return new byte[]{0x1B, 0x21, 0x19};
        if ("draft 10cpi".equals(nombre)) return new byte[]{0x1B, 0x21, 0x01};
        if ("draft 12cpi".equals(nombre)) return new byte[]{0x1B, 0x21, 0x01};
        if ("roman 6cpi".equals(nombre))  return new byte[]{0x1B, 0x21, 0x18};
        if ("roman 10cpi".equals(nombre)) return new byte[]{0x1B, 0x21, 0x00};
        if ("roman 12cpi".equals(nombre)) return new byte[]{0x1B, 0x21, 0x00};
        return VB6_FONT_NORMAL;
    }

    // ------------------------------------------------------------------
    // Decoracion final (fuente A/B, cajon, corte)
    // ------------------------------------------------------------------

    /**
     * Aplica los ajustes del perfil al stream ya armado, en el mismo orden que el
     * Python: primero ESC M (fuente), despues el cajon, y el corte al final.
     */
    public static byte[] decorar(byte[] payload, String escposFont,
                                 boolean openDrawer, boolean cutPaper) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if ("B".equalsIgnoreCase(escposFont))      write(out, FONT_B);
        else if ("A".equalsIgnoreCase(escposFont)) write(out, FONT_A);
        if (openDrawer) write(out, OPEN_DRAWER);
        write(out, payload);
        if (cutPaper && !terminaEnCorte(payload)) {
            write(out, new byte[]{0x0A, 0x0A, 0x0A});
            write(out, CUT_PAPER);
        }
        return out.toByteArray();
    }

    /**
     * Evita cortar dos veces cuando el contenido ya traia su propio corte.
     * Mira solo la cola del stream: un GS V a mitad del tiquete no es el corte final.
     */
    private static boolean terminaEnCorte(byte[] p) {
        if (p == null || p.length < 2) return false;
        int desde = Math.max(0, p.length - 8);
        for (int i = desde; i < p.length - 1; i++) {
            int a = p[i] & 0xFF, b = p[i + 1] & 0xFF;
            if (a == 0x1D && b == 0x56) return true;   // GS V - corte (cualquier variante)
            if (a == 0x1B && b == 0x69) return true;   // ESC i - corte total
            if (a == 0x1B && b == 0x6D) return true;   // ESC m - corte parcial
        }
        return false;
    }

    // ------------------------------------------------------------------
    // Codificacion
    // ------------------------------------------------------------------

    private static String latin1(byte[] data) {
        if (data == null) return "";
        try {
            return new String(data, "ISO-8859-1");
        } catch (Exception e) {
            return new String(data);
        }
    }

    /**
     * Decodifica el contenido entrante detectando la codificacion.
     *
     * El PHP puede mandar UTF-8 o latin-1 segun el formato. Decodificar siempre como
     * latin-1 rompe el UTF-8: por ejemplo el colon llega como los 3 bytes E2 82 A1 y
     * se parte en tres caracteres sueltos, con lo cual nunca se lo reconoce como
     * simbolo de moneda ni se lo convierte al codigo.
     *
     * Se intenta UTF-8 estricto primero; si el contenido no es UTF-8 valido (caso
     * tipico: VB6, que usa 0xDF/0xDD, invalidos en UTF-8) se cae a latin-1.
     */
    public static String decodificar(byte[] data) {
        if (data == null || data.length == 0) return "";
        try {
            java.nio.charset.CharsetDecoder dec = java.nio.charset.Charset.forName("UTF-8")
                .newDecoder()
                .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT);
            return dec.decode(java.nio.ByteBuffer.wrap(data)).toString();
        } catch (Exception e) {
            return latin1(data);
        }
    }

    /**
     * Codifica a CP437, que es la tabla por defecto de las termicas ESC/POS.
     *
     * Se hace a mano porque Android NO garantiza el charset IBM437: pedirlo con
     * Charset.forName revienta en muchos equipos. Los caracteres que CP437 no tiene
     * (mayusculas acentuadas, el colon) se transliteran en vez de salir como basura.
     */
    public static byte[] cp437(String s) {
        if (s == null) return new byte[0];
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c < 0x80) { out.write(c); continue; }
            switch (c) {
                case 'á': out.write(0xA0); break;
                case 'é': out.write(0x82); break;
                case 'í': out.write(0xA1); break;
                case 'ó': out.write(0xA2); break;
                case 'ú': out.write(0xA3); break;
                case 'ñ': out.write(0xA4); break;
                case 'Ñ': out.write(0xA5); break;
                case 'ü': out.write(0x81); break;
                case 'Ü': out.write(0x9A); break;
                case 'ç': out.write(0x87); break;
                case 'Ç': out.write(0x80); break;
                case 'É': out.write(0x90); break;
                case '¿': out.write(0xA8); break;
                case '¡': out.write(0xAD); break;
                case 'º': out.write(0xA7); break;
                case 'ª': out.write(0xA6); break;
                case '°': out.write(0xF8); break;
                case '¢': out.write(0x9B); break;
                case '±': out.write(0xF1); break;
                case '÷': out.write(0xF6); break;
                // MONEDA: la convencion del sistema es el CODIGO ISO (CRC, USD, EUR...),
                // nunca el simbolo (ver configuracion-regional: "Simbolo: no se usa").
                // Ademas ninguno de estos existe en CP437, asi que dibujarlos daria
                // un caracter equivocado en el papel.
                case '₡': write(out, "CRC"); break;
                case '€': write(out, "EUR"); break;
                case '£': write(out, "GBP"); break;
                case '¥': write(out, "JPY"); break;
                // Mayusculas acentuadas: CP437 no las tiene (salvo E), se transliteran
                case 'Á': out.write('A'); break;
                case 'Í': out.write('I'); break;
                case 'Ó': out.write('O'); break;
                case 'Ú': out.write('U'); break;
                case '´': out.write('\''); break;
                case '“': case '”': out.write('"'); break;
                case '‘': case '’': out.write('\''); break;
                case '–': case '—': out.write('-'); break;
                default:
                    // Ultimo recurso: si entra en latin-1 se manda tal cual; si no, '?'
                    if (c <= 0xFF) out.write(c); else out.write('?');
            }
        }
        return out.toByteArray();
    }

    /**
     * Extrae el texto legible de un stream ESC/POS, descartando los comandos.
     *
     * Hace falta para SUNMI: su AIDL solo expone printText(String) — no tiene
     * sendRAWData —, asi que la impresora interna no puede recibir bytes crudos.
     * Se pierde el formato (negrita, tamanos), pero sale el contenido; mandarle los
     * bytes tal cual imprimiria basura.
     */
    public static String toPlainText(byte[] data) {
        if (data == null || data.length == 0) return "";
        StringBuilder sb = new StringBuilder();
        int i = 0;
        while (i < data.length) {
            int b = data[i] & 0xFF;

            if (b == 0x1B) {                       // ESC
                int n = (i + 1 < data.length) ? (data[i + 1] & 0xFF) : -1;
                // ESC @ (reset) y ESC 2 no llevan parametro
                if (n == 0x40 || n == 0x32) { i += 2; continue; }
                // ESC ! n / ESC M n / ESC a n / ESC E n / ESC t n / ESC 3 n / ESC p ...
                if (n == 0x70) { i += 5; continue; }              // ESC p m t1 t2
                if (n >= 0) { i += 3; continue; }                 // comandos de 1 parametro
                i += 1; continue;

            } else if (b == 0x1D) {                // GS
                int n = (i + 1 < data.length) ? (data[i + 1] & 0xFF) : -1;
                if (n == 0x56) {                                   // GS V (corte)
                    int m = (i + 2 < data.length) ? (data[i + 2] & 0xFF) : 0;
                    i += (m == 0x42 || m == 0x41) ? 4 : 3;
                    continue;
                }
                if (n >= 0) { i += 3; continue; }
                i += 1; continue;

            } else if (b == 0x0A || b == 0x0D || b >= 0x20) {
                sb.append(desdeCp437(b));
            }
            i++;
        }
        // Colapsar los saltos de linea de relleno que deja el corte
        String s = sb.toString();
        while (s.contains("\n\n\n\n")) s = s.replace("\n\n\n\n", "\n\n");
        return s;
    }

    /** Inversa parcial de cp437(): devuelve el caracter Unicode de un byte CP437. */
    private static char desdeCp437(int b) {
        switch (b) {
            case 0xA0: return 'á';
            case 0x82: return 'é';
            case 0xA1: return 'í';
            case 0xA2: return 'ó';
            case 0xA3: return 'ú';
            case 0xA4: return 'ñ';
            case 0xA5: return 'Ñ';
            case 0x81: return 'ü';
            case 0x9A: return 'Ü';
            case 0x87: return 'ç';
            case 0x80: return 'Ç';
            case 0x90: return 'É';
            case 0xA8: return '¿';
            case 0xAD: return '¡';
            case 0xA7: return 'º';
            case 0xA6: return 'ª';
            case 0xF8: return '°';
            case 0x9B: return '¢';
            default:   return (char) b;
        }
    }

    private static void write(ByteArrayOutputStream out, byte[] b) {
        if (b != null && b.length > 0) out.write(b, 0, b.length);
    }

    /** Escribe una cadena ASCII (usada para los codigos de moneda). */
    private static void write(ByteArrayOutputStream out, String s) {
        for (int i = 0; i < s.length(); i++) out.write(s.charAt(i));
    }
}
