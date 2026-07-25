package com.factupos.kiosk;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Parser/serializador JSON minimo, sin dependencias externas.
 * Mapea: objeto -> Map<String,Object>, array -> List<Object>,
 *        string -> String, numero -> Double/Long, bool -> Boolean, null -> null.
 */
public final class Json {

    // ---------------- Parse ----------------
    public static Object parse(String s) {
        if (s == null) return null;
        Parser p = new Parser(s);
        p.skipWs();
        Object v = p.value();
        p.skipWs();
        return v;
    }

    /** parse seguro a Map; devuelve mapa vacio si no es objeto JSON. */
    @SuppressWarnings("unchecked")
    public static Map<String,Object> parseObj(String s) {
        Object o = null;
        try { o = parse(s); } catch (Exception e) { /* ignore */ }
        if (o instanceof Map) return (Map<String,Object>) o;
        return new LinkedHashMap<>();
    }

    private static final class Parser {
        private final String s;
        private int i = 0;
        Parser(String s) { this.s = s; }

        void skipWs() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') i++;
                else break;
            }
        }

        Object value() {
            skipWs();
            if (i >= s.length()) return null;
            char c = s.charAt(i);
            switch (c) {
                case '{': return object();
                case '[': return array();
                case '"': return string();
                case 't': case 'f': return bool();
                case 'n': i += 4; return null; // null
                default:  return number();
            }
        }

        Map<String,Object> object() {
            Map<String,Object> m = new LinkedHashMap<>();
            i++; // {
            skipWs();
            if (i < s.length() && s.charAt(i) == '}') { i++; return m; }
            while (i < s.length()) {
                skipWs();
                String key = string();
                skipWs();
                if (i < s.length() && s.charAt(i) == ':') i++;
                Object val = value();
                m.put(key, val);
                skipWs();
                if (i < s.length() && s.charAt(i) == ',') { i++; continue; }
                if (i < s.length() && s.charAt(i) == '}') { i++; break; }
                break;
            }
            return m;
        }

        List<Object> array() {
            List<Object> a = new ArrayList<>();
            i++; // [
            skipWs();
            if (i < s.length() && s.charAt(i) == ']') { i++; return a; }
            while (i < s.length()) {
                Object val = value();
                a.add(val);
                skipWs();
                if (i < s.length() && s.charAt(i) == ',') { i++; continue; }
                if (i < s.length() && s.charAt(i) == ']') { i++; break; }
                break;
            }
            return a;
        }

        String string() {
            StringBuilder b = new StringBuilder();
            if (i < s.length() && s.charAt(i) == '"') i++;
            while (i < s.length()) {
                char c = s.charAt(i++);
                if (c == '"') break;
                if (c == '\\' && i < s.length()) {
                    char e = s.charAt(i++);
                    switch (e) {
                        case '"':  b.append('"'); break;
                        case '\\': b.append('\\'); break;
                        case '/':  b.append('/'); break;
                        case 'n':  b.append('\n'); break;
                        case 't':  b.append('\t'); break;
                        case 'r':  b.append('\r'); break;
                        case 'b':  b.append('\b'); break;
                        case 'f':  b.append('\f'); break;
                        case 'u':
                            if (i + 4 <= s.length()) {
                                b.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                                i += 4;
                            }
                            break;
                        default:   b.append(e);
                    }
                } else {
                    b.append(c);
                }
            }
            return b.toString();
        }

        Boolean bool() {
            if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
            if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
            i++;
            return Boolean.FALSE;
        }

        Object number() {
            int start = i;
            while (i < s.length()) {
                char c = s.charAt(i);
                if ((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') i++;
                else break;
            }
            String num = s.substring(start, i);
            try {
                if (num.contains(".") || num.contains("e") || num.contains("E")) return Double.parseDouble(num);
                return Long.parseLong(num);
            } catch (Exception e) {
                return 0L;
            }
        }
    }

    // ---------------- Write ----------------
    public static String write(Object o) {
        StringBuilder b = new StringBuilder();
        writeVal(b, o);
        return b.toString();
    }

    @SuppressWarnings("unchecked")
    private static void writeVal(StringBuilder b, Object o) {
        if (o == null) { b.append("null"); return; }
        if (o instanceof String) { writeStr(b, (String) o); return; }
        if (o instanceof Boolean || o instanceof Number) { b.append(o.toString()); return; }
        if (o instanceof Map) {
            b.append('{');
            boolean first = true;
            for (Map.Entry<String,Object> e : ((Map<String,Object>) o).entrySet()) {
                if (!first) b.append(',');
                first = false;
                writeStr(b, e.getKey());
                b.append(':');
                writeVal(b, e.getValue());
            }
            b.append('}');
            return;
        }
        if (o instanceof List) {
            b.append('[');
            boolean first = true;
            for (Object v : (List<Object>) o) {
                if (!first) b.append(',');
                first = false;
                writeVal(b, v);
            }
            b.append(']');
            return;
        }
        writeStr(b, o.toString());
    }

    private static void writeStr(StringBuilder b, String s) {
        b.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':  b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                case '\b': b.append("\\b"); break;
                case '\f': b.append("\\f"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        b.append('"');
    }

    // ---------------- Helpers de acceso ----------------
    public static String str(Map<String,Object> m, String k) {
        Object v = m == null ? null : m.get(k);
        return v == null ? null : v.toString();
    }

    public static String str(Map<String,Object> m, String k, String def) {
        String v = str(m, k);
        return v == null ? def : v;
    }

    public static boolean bool(Map<String,Object> m, String k) {
        Object v = m == null ? null : m.get(k);
        if (v instanceof Boolean) return (Boolean) v;
        if (v instanceof Number) return ((Number) v).doubleValue() != 0;
        if (v instanceof String) return "true".equalsIgnoreCase((String) v) || "1".equals(v);
        return false;
    }

    public static int intVal(Map<String,Object> m, String k, int def) {
        Object v = m == null ? null : m.get(k);
        if (v instanceof Number) return ((Number) v).intValue();
        if (v instanceof String) { try { return Integer.parseInt((String) v); } catch (Exception e) { return def; } }
        return def;
    }

    @SuppressWarnings("unchecked")
    public static Map<String,Object> obj(Map<String,Object> m, String k) {
        Object v = m == null ? null : m.get(k);
        if (v instanceof Map) return (Map<String,Object>) v;
        return new LinkedHashMap<>();
    }

    @SuppressWarnings("unchecked")
    public static List<Object> arr(Map<String,Object> m, String k) {
        Object v = m == null ? null : m.get(k);
        if (v instanceof List) return (List<Object>) v;
        return new ArrayList<>();
    }

    private Json() {}
}
