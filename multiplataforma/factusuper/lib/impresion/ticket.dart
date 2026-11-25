/// El TIQUETE de FactuSuper — formato FIPVIVI002 en Dart: réplica EXACTA de `FSTicket.fipvivi002()` de
/// factupos.com/modules/facturacion/factusuper/js/factusuper_ticket.js (que a su vez replica byte por byte
/// impresion_fipvivi002() del PHP).
///
/// 🔑 Para el MISMO documento, los MISMOS parámetros y la MISMA fecha de impresión, el texto sale IGUAL
/// carácter por carácter que el del JS. Lo prueba test/ticket_ab_test.dart contra el JS real
/// (`node tool/ab_ticket.js factusuper_ticket.js test/ab_ticket.json`). Si se toca el JS, se toca acá y se
/// vuelve a correr la prueba.
///
/// 🪤 Cuidados de la réplica (además de los del JS: PHP ≠ JavaScript):
///    · Los textos de JS son UTF-16 igual que los de Dart; el JS mide «caracteres» con Array.from (puntos
///      de código) → acá con `runes`; y los BYTES de str_pad en UTF-8.
///    · `String(número)` de JS no es `toString()` de Dart (5 → «5», no «5.0»): ver [_numTexto].
///    · `toUpperCase()` de JS (mapeo Unicode completo, ß → SS) no es el de Dart: va con su propia tabla.
///    · `Math.log10` de V8 (fdlibm) puede diferir de `log(x) / ln10` justo en las potencias de 10, y eso
///      cambia el pre-redondeo de round(): se porta el log10 de fdlibm tal cual.
///    · Verdad de JS (`x || {}`, `&& bd.sac`) ≠ verdad de PHP (`verdad()`): se usan las dos donde el JS las usa.
library;

import 'dart:math' as math;
import 'dart:typed_data';

// =====================================================================================
// Réplicas de funciones de PHP (y de JavaScript)
// =====================================================================================

/// `$x ?? $def` — null y «no existe» caen al default; '' y '0' NO.
Object? _nn(Object? v, Object? def) => v ?? def;

/// Propiedad de un objeto de JS: lo que no es un Map no tiene propiedades (undefined).
Object? _g(Object? m, Object k) => m is Map ? m[k] : null;

/// Verdad de PHP: '', '0', 0, null, false, [] son falsos.
bool _verdad(Object? v) {
  if (v == null || v == false) return false;
  if (v is String) return v != '' && v != '0';
  if (v is num) return v != 0; // (NaN != 0 → verdadero, igual que el JS)
  if (v is List) return v.isNotEmpty;
  return true;
}

/// Verdad de JavaScript (`x || def`, `a && b`): '', 0, NaN, null, false son falsos; '0' y [] NO.
bool _verdadJs(Object? v) {
  if (v == null || v == false) return false;
  if (v is String) return v != '';
  if (v is num) return v != 0 && !v.isNaN;
  return true;
}

/// `x || def` de JavaScript.
Object? _o(Object? v, Object? def) => _verdadJs(v) ? v : def;

/// `String(número)` de JavaScript: enteros sin «.0», exponente desde 1e21 y bajo 1e-6 (igual que Dart).
String _numTexto(num n) {
  final x = n.toDouble();
  if (x.isNaN) return 'NaN';
  if (x.isInfinite) return x > 0 ? 'Infinity' : '-Infinity';
  if (x == 0) return '0';
  final s = x.toString();
  return s.endsWith('.0') ? s.substring(0, s.length - 2) : s;
}

/// `String(v)` de JavaScript (para lo que hay adentro de un arreglo).
String _jsTexto(Object? v) {
  if (v == null) return 'null';
  if (v is String) return v;
  if (v is bool) return v ? 'true' : 'false';
  if (v is num) return _numTexto(v);
  if (v is List) return v.map((e) => e == null ? '' : _jsTexto(e)).join(',');
  if (v is Map) return '[object Object]';
  return v.toString();
}

/// `(string)$v` (el `str()` del JS).
String _str(Object? v) {
  if (v == null || v == false) return '';
  if (v == true) return '1';
  return _jsTexto(v);
}

/// `Number(texto)` para un texto que YA pasó una de las expresiones numéricas (solo dígitos, punto,
/// signo, exponente y espacios ASCII alrededor).
double _jsNumero(String s) {
  final t = s.replaceAll(RegExp(r'^[ \t\n\r\v\f]+|[ \t\n\r\v\f]+$'), '');
  return double.tryParse(t) ?? double.nan;
}

/// `(float)$v` — PHP toma el prefijo numérico del texto ('.00' → 0, '12abc' → 12, 'abc' → 0).
final RegExp _rxNum = RegExp(
  r'^[ \t\n\r\v\f]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)',
);
double _flt(Object? v) {
  if (v == null || v == false) return 0;
  if (v == true) return 1;
  if (v is num) return v.toDouble();
  final m = _rxNum.firstMatch(_str(v));
  return m != null ? _jsNumero(m.group(1)!) : 0;
}

/// `(int)$v` — trunca hacia cero (queda en double, como el número de JS).
double _ent(Object? v) {
  final n = _flt(v).truncateToDouble();
  return n.isFinite ? (n == 0 ? 0 : n) : 0;
}

/// trim() de PHP: solo " \t\n\r\0\x0B".
final RegExp _rxTrim = RegExp(r'^[ \t\n\r\0\x0B]+|[ \t\n\r\0\x0B]+$');
String _trim(Object? s) => _str(s).replaceAll(_rxTrim, '');

/// strtoupper() / strtolower() de PHP 8: solo a-z / A-Z.
String _upperAscii(Object? s) =>
    _str(s).replaceAllMapped(RegExp('[a-z]+'), (m) => m[0]!.toUpperCase());
String _lowerAscii(Object? s) =>
    _str(s).replaceAllMapped(RegExp('[A-Z]+'), (m) => m[0]!.toLowerCase());

/// mb_strtoupper() — el `toUpperCase()` de JavaScript (mapeo Unicode completo, sin idioma).
String _mbUpper(Object? s) {
  final t = _str(s);
  final b = StringBuffer();
  for (final r in t.runes) {
    if (r < 0x80) {
      b.writeCharCode(r >= 0x61 && r <= 0x7A ? r - 32 : r);
      continue;
    }
    final varias = _mayusVarias[r];
    if (varias != null) {
      for (final c in varias) {
        b.writeCharCode(c);
      }
      continue;
    }
    b.writeCharCode(r + (_mayusDelta()[r] ?? 0));
  }
  return b.toString();
}

Map<int, int>? _deltaCache;
Map<int, int> _mayusDelta() {
  final ya = _deltaCache;
  if (ya != null) return ya;
  final m = <int, int>{};
  for (var i = 0; i < _mayusRangos.length; i += 4) {
    for (
      var c = _mayusRangos[i];
      c <= _mayusRangos[i + 1];
      c += _mayusRangos[i + 2]
    ) {
      m[c] = _mayusRangos[i + 3];
    }
  }
  return _deltaCache = m;
}

/// stripos($h, $n) !== false — PHP 8 compara sin mayúsculas solo en ASCII.
bool _contieneI(Object? h, Object? n) =>
    _lowerAscii(h).contains(_lowerAscii(n));

/// mb_strlen / mb_substr — por CARACTERES (puntos de código), como Array.from.
List<String> _chars(Object? s) =>
    _str(s).runes.map(String.fromCharCode).toList(growable: false);
int _mbLen(Object? s) => _str(s).runes.length;
String _mbSubstr(Object? s, num inicio, [num? largo]) {
  final c = _chars(s);
  final n = c.length;
  final a = inicio < 0 ? math.max(0, n + inicio) : inicio;
  if (a > n) return '';
  num b;
  if (largo == null) {
    b = n;
  } else if (largo < 0) {
    b = n + largo;
  } else {
    b = math.min(n, a + largo);
  }
  if (b <= a) return '';
  return c.sublist(a.toInt(), b.toInt()).join();
}

/// strlen() — BYTES en UTF-8 (un sustituto suelto cuenta 3, igual que el JS).
int _bytes(Object? s) {
  var b = 0;
  for (final cp in _str(s).runes) {
    b += cp < 0x80
        ? 1
        : cp < 0x800
        ? 2
        : cp < 0x10000
        ? 3
        : 4;
  }
  return b;
}

/// str_pad() — el relleno se mide en BYTES (PHP no sabe de UTF-8 acá).
const int _izqPad = 0, _derPad = 1, _ambosPad = 2;
String _strPad(
  Object? s,
  num largo, [
  String relleno = ' ',
  int tipo = _derPad,
]) {
  final t = _str(s);
  final falta = (largo - _bytes(t)).toInt();
  if (falta <= 0) return t;
  String rep(int k) {
    var r = '';
    while (r.length < k) {
      r += relleno;
    }
    return r.substring(0, k);
  }

  if (tipo == _izqPad) return rep(falta) + t;
  if (tipo == _ambosPad) {
    final i = falta ~/ 2;
    return rep(i) + t + rep(falta - i);
  }
  return t + rep(falta);
}

String _repetir(String s, num n) => n > 0 ? s * n.toInt() : '';

/// rtrim($s, $lista)
String _rtrimChars(Object? s, String lista) {
  final t = _str(s);
  var i = t.length;
  while (i > 0 && lista.contains(t[i - 1])) {
    i--;
  }
  return t.substring(0, i);
}

/// Comparación suelta `==` entre textos de PHP 8 (lo que hace in_array() sin estricto).
final RegExp _rxNumerico = RegExp(
  r'^[ \t\n\r\v\f]*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?[ \t\n\r\v\f]*$',
);
bool _sueltoIgual(Object? a, Object? b) {
  if (a is num || b is num) {
    final x = a is num
        ? a.toDouble()
        : (_rxNumerico.hasMatch(_str(a))
              ? _jsNumero(_trim(_str(a)))
              : double.nan);
    final y = b is num
        ? b.toDouble()
        : (_rxNumerico.hasMatch(_str(b))
              ? _jsNumero(_trim(_str(b)))
              : double.nan);
    if (!x.isNaN && !y.isNaN) return x == y;
    return _str(a) == _str(b);
  }
  final sa = _str(a), sb = _str(b);
  if (_rxNumerico.hasMatch(sa) && _rxNumerico.hasMatch(sb)) {
    return _jsNumero(sa) == _jsNumero(sb);
  }
  return sa == sb;
}

bool _enLista(Object? v, List<Object?> lista) =>
    lista.any((x) => _sueltoIgual(v, x));

// -------------------------------------------------------------------------------------
// round() de PHP 8.3 con su pre-redondeo (como el JS, que usa Math.log10 de V8)
// -------------------------------------------------------------------------------------

const List<double> _pot10Tabla = [
  1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10, 1e11, //
  1e12, 1e13, 1e14, 1e15, 1e16, 1e17, 1e18, 1e19, 1e20, 1e21, 1e22,
];

/// Fuera de la tabla el JS usa Math.pow (que en V8 no siempre da el literal «1eN»); con los 2 decimales
/// del formato el pre-redondeo solo pide exponentes de 0 a 16, así que esa rama nunca se usa.
double _pot10(num p) => p < 0 || p > 22
    ? math.pow(10.0, p.toDouble()).toDouble()
    : _pot10Tabla[p.toInt()];

/// php_round_helper (HALF_UP) de PHP 8.3: floor(v + 0,5) — con SU rareza (0.49999999999999994 → 1).
double _redondeoMitad(double v) =>
    v >= 0 ? (v + 0.5).floorToDouble() : (v - 0.5).ceilToDouble();

double _round(double valor, [int lugares = 0]) {
  if (!valor.isFinite || valor == 0) return valor;
  final precisionLugares = 14 - _log10(valor.abs()).floorToDouble();
  final f1 = _pot10(lugares.abs());
  double tmp;
  if (precisionLugares > lugares && precisionLugares - 15 < lugares) {
    var usar = precisionLugares < -(4 * 15)
        ? -(4 * 15).toDouble()
        : precisionLugares;
    final f2 = _pot10(usar.abs());
    tmp = usar >= 0 ? valor * f2 : valor / f2;
    tmp = _redondeoMitad(tmp);
    usar = lugares - usar;
    usar = math.max(-(4 * 15).toDouble(), usar);
    tmp = tmp / _pot10(usar.abs());
  } else {
    tmp = lugares >= 0 ? valor * f1 : valor / f1;
    if (tmp.abs() >= 1e15) return valor;
  }
  tmp = _redondeoMitad(tmp);
  tmp = lugares > 0 ? tmp / f1 : tmp * f1;
  return tmp;
}

/// number_format($v, $dec) — separador de miles «,» y decimal «.».
final RegExp _rxMiles = RegExp(r'\B(?=(\d{3})+(?!\d))');
String _numberFormat(Object? v, [int dec = 0]) {
  var d = _round(_flt(v), dec);
  var negativo = d < 0;
  d = d.abs();
  final txt = d.toStringAsFixed(dec);
  if (negativo && d == 0) negativo = false;
  var entero = txt, decimales = '';
  final p = txt.indexOf('.');
  if (p != -1) {
    entero = txt.substring(0, p);
    decimales = txt.substring(p + 1);
  }
  entero = entero.replaceAll(_rxMiles, ',');
  return (negativo ? '-' : '') + entero + (dec > 0 ? '.$decimales' : '');
}

// -------------------------------------------------------------------------------------
// Math.log10 de V8 = fdlibm (e_log10.c sobre e_log.c), portado tal cual
// -------------------------------------------------------------------------------------

final ByteData _bits = ByteData(8);
int _alto(double x) {
  _bits.setFloat64(0, x);
  return _bits.getInt32(0);
}

int _bajo(double x) {
  _bits.setFloat64(0, x);
  return _bits.getUint32(4);
}

double _armar(int alto, int bajo) {
  _bits.setInt32(0, alto.toSigned(32));
  _bits.setUint32(4, bajo & 0xFFFFFFFF);
  return _bits.getFloat64(0);
}

const double _two54 = 1.80143985094819840000e+16;

double _logFdlibm(double x) {
  const ln2Hi = 6.93147180369123816490e-01,
      ln2Lo = 1.90821492927058770002e-10,
      lg1 = 6.666666666666735130e-01,
      lg2 = 3.999999999940941908e-01,
      lg3 = 2.857142874366239149e-01,
      lg4 = 2.222219843214978396e-01,
      lg5 = 1.818357216161805012e-01,
      lg6 = 1.531383769920937332e-01,
      lg7 = 1.479819860511658591e-01;
  var hx = _alto(x);
  final lx = _bajo(x);
  var k = 0;
  if (hx < 0x00100000) {
    if (((hx & 0x7FFFFFFF) | lx) == 0) return double.negativeInfinity;
    if (hx < 0) return double.nan;
    k -= 54;
    x *= _two54;
    hx = _alto(x);
  }
  if (hx >= 0x7FF00000) return x + x;
  k += (hx >> 20) - 1023;
  hx &= 0x000FFFFF;
  var i = (hx + 0x95F64) & 0x100000;
  x = _armar(hx | (i ^ 0x3FF00000), _bajo(x));
  k += i >> 20;
  final f = x - 1.0;
  if ((0x000FFFFF & (2 + hx)) < 3) {
    if (f == 0) {
      if (k == 0) return 0;
      final dk = k.toDouble();
      return dk * ln2Hi + dk * ln2Lo;
    }
    final r = f * f * (0.5 - 0.33333333333333333 * f);
    if (k == 0) return f - r;
    final dk = k.toDouble();
    return dk * ln2Hi - ((r - dk * ln2Lo) - f);
  }
  final s = f / (2.0 + f);
  final dk = k.toDouble();
  final z = s * s;
  i = hx - 0x6147A;
  final w = z * z;
  final j = 0x6B851 - hx;
  final t1 = w * (lg2 + w * (lg4 + w * lg6));
  final t2 = z * (lg1 + w * (lg3 + w * (lg5 + w * lg7)));
  i |= j;
  final r = t2 + t1;
  if (i > 0) {
    final hfsq = 0.5 * f * f;
    if (k == 0) return f - (hfsq - s * (hfsq + r));
    return dk * ln2Hi - ((hfsq - (s * (hfsq + r) + dk * ln2Lo)) - f);
  }
  if (k == 0) return f - s * (f - r);
  return dk * ln2Hi - ((s * (f - r) - dk * ln2Lo) - f);
}

double _log10(double x) {
  const ivln10 = 4.34294481903251816668e-01,
      log10y2hi = 3.01029995663611771306e-01,
      log10y2lo = 3.69423907715893078616e-13;
  var hx = _alto(x);
  final lx = _bajo(x);
  var k = 0;
  if (hx < 0x00100000) {
    if (((hx & 0x7FFFFFFF) | lx) == 0) return double.negativeInfinity;
    if (hx < 0) return double.nan;
    k -= 54;
    x *= _two54;
    hx = _alto(x);
  }
  if (hx >= 0x7FF00000) return x + x;
  if (hx == 0x3FF00000 && _bajo(x) == 0) return 0;
  k += (hx >> 20) - 1023;
  final i = k < 0 ? 1 : 0; // (k & 0x80000000) >> 31
  hx = (hx & 0x000FFFFF) | ((0x3FF - i) << 20);
  final y = (k + i).toDouble();
  x = _armar(hx, _bajo(x));
  final z = y * log10y2lo + ivln10 * _logFdlibm(x);
  return z + y * log10y2hi;
}

/// Solo para la prueba de la réplica de Math.log10 (no usarla fuera de acá).
double log10Js(double x) => _log10(x);

/// \s de PCRE sin /u: solo espacios ASCII.
final RegExp _rxSerieUnaFila = RegExp(r'[ \t\n\x0B\f\r]*\r?\n[ \t\n\x0B\f\r]*');

// =====================================================================================
// Fechas — date() / strtotime() sin conversión de zona
// =====================================================================================

String _dos(num n) => _numTexto(n).padLeft(2, '0');

class _Fecha {
  final int y, m, d, h, i, s;
  const _Fecha(this.y, this.m, this.d, this.h, this.i, this.s);
}

final RegExp _rxFecha = RegExp(
  r'^\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?',
);

/// La fecha del documento como la ve PHP: 'aaaa-mm-dd hh:mm:ss[.fff]' o un DateTime. Sin fecha se usa
/// `ahora` — 🪤 si `ahora` es el TEXTO 'dd/mm/aaaa …' no calza con el patrón y da null (igual que el JS).
_Fecha? _leerFecha(Object? v, Object ahora) {
  v ??= ahora;
  if (v is DateTime) {
    return _Fecha(v.year, v.month, v.day, v.hour, v.minute, v.second);
  }
  final m = _rxFecha.firstMatch(_str(v));
  if (m == null) return null;
  int n(int k) => int.parse(m.group(k) ?? '0');
  return _Fecha(n(1), n(2), n(3), n(4), n(5), n(6));
}

/// strtotime('… +N días') = Date.UTC del JS: suma días de calendario. 🪤 Date.UTC toma los años
/// 0–99 como 1900–1999, y normaliza mes/día/hora desbordados.
_Fecha _sumarDias(_Fecha f, int dias) {
  final anio = f.y >= 0 && f.y <= 99 ? 1900 + f.y : f.y;
  final t = DateTime.utc(anio, f.m, f.d + dias, f.h, f.i, f.s);
  return _Fecha(t.year, t.month, t.day, t.hour, t.minute, t.second);
}

String _fmtYmdHi(_Fecha f) =>
    '${f.y}/${_dos(f.m)}/${_dos(f.d)} ${_dos(f.h)}:${_dos(f.i)}';
String _fmtYmd(_Fecha f) => '${f.y}/${_dos(f.m)}/${_dos(f.d)}';
String _fmtAhora(Object a) {
  if (a is String) return a;
  final d = a is DateTime ? a : DateTime.now();
  return '${_dos(d.day)}/${_dos(d.month)}/${d.year} '
      '${_dos(d.hour)}:${_dos(d.minute)}:${_dos(d.second)}';
}

// =====================================================================================
// Auxiliares del formato (_imprfipv_*)
// =====================================================================================

String _izq(num a, Object? t) => _strPad(_mbSubstr(t, 0, a), a);
String _der(num a, Object? t) => _strPad(_mbSubstr(t, 0, a), a, ' ', _izqPad);
String _centro(num a, Object? t) =>
    _strPad(_mbSubstr(t, 0, a), a, ' ', _ambosPad);
String _dosCol(num a, Object? i, Object? d) {
  final maxIzq = a - _mbLen(d) - 1;
  final iz = _mbSubstr(
    i,
    0,
    maxIzq,
  ); // 🪤 maxIzq < 0 corta por el FINAL (mb_substr con largo negativo)
  final esp = a - _mbLen(iz) - _mbLen(d);
  return iz + _repetir(' ', math.max(1, esp)) + _str(d);
}

/// _imprfipv_sinTildes — las impresoras POS no traen tildes.
const Map<String, String> _tildes = {
  'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', //
  'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
  'ñ': 'n', 'Ñ': 'N', 'ü': 'u', 'Ü': 'U',
};
final RegExp _rxTildes = RegExp('[áéíóúÁÉÍÓÚñÑüÜ]');
String _sinTildes(Object? t) =>
    _str(t).replaceAllMapped(_rxTildes, (m) => _tildes[m[0]]!);

/// #706 — _imprfipv_envolver_partes: renglones de a lo sumo $ancho juntando con ", " sin partir partes.
List<String> _envolverPartes(List<Object?> partes, num anchoPedido) {
  final ancho = math.max(8, anchoPedido);
  final out = <String>[];
  var linea = '';
  for (final parte in partes) {
    var p = _str(parte);
    final cand = linea == '' ? p : '$linea, $p';
    if (_mbLen(cand) <= ancho) {
      linea = cand;
      continue;
    }
    if (linea != '') {
      out.add(linea);
      linea = '';
    }
    while (_mbLen(p) > ancho) {
      out.add(_mbSubstr(p, 0, ancho));
      p = _mbSubstr(p, ancho);
    }
    linea = p;
  }
  if (linea != '') out.add(linea);
  return out;
}

/// Parte un texto en trozos de $ancho caracteres (el while mb_substr del PHP).
List<String> _trozos(Object? texto, num ancho) {
  final out = <String>[];
  final n = _mbLen(texto);
  for (num pos = 0; pos < n; pos += ancho) {
    out.add(_mbSubstr(texto, pos, ancho));
  }
  return out;
}

/// `for (const x of v)` del JS: un arreglo da sus elementos y un texto sus caracteres.
Iterable<Object?> _deCorrido(Object? v) {
  if (v is List) return v;
  if (v is String) return _chars(v);
  return const [];
}

/// `v.length` del JS (arreglo o texto en unidades UTF-16); lo demás no tiene largo.
bool _tieneLargo(Object? v) =>
    (v is List && v.isNotEmpty) || (v is String && v.isNotEmpty);

/// venta_condicion() (#1284): crédito con plazo 0 = CONTADO.
String _ventaCondicion(
  Object? formaPago,
  double? plazoCliente,
  Map? bd,
  Object? clienteCodigo,
) {
  var codigo = _trim(_str(formaPago));
  if (codigo == '' || codigo == '00') codigo = '01';
  if (codigo != '02') return codigo;
  if (plazoCliente == null) {
    final cod = _trim(clienteCodigo);
    if (bd == null || cod == '') {
      plazoCliente = null;
    } else if (_upperAscii(cod) == 'SN' || cod == '0') {
      plazoCliente = 0;
    } else {
      plazoCliente = bd['plazoCliente'] == null
          ? null
          : _ent(bd['plazoCliente']);
    }
  }
  if (plazoCliente == null) return '02';
  if (plazoCliente <= 0) return '01';
  return '02';
}

/// Defaults del PHP cuando no le pasan params NI conexión (línea «$params = [15=>'1', …]»).
const Map<int, String> parametrosSinBd = {
  15: '1',
  20: '1',
  21: '0',
  26: '1',
  38: '1',
  43: '0',
  47: '1',
  89: '2104',
  110: '0', //
  137: '',
  151: '1',
  192: '1',
  249: 'CRC',
  307: '0',
  343: '0',
  346: '0',
  380: '1',
  381: '1', 382: '1', 936: '0',
};

// =====================================================================================
// El formato
// =====================================================================================

/// El tiquete FIPVIVI002 (texto ESC/POS listo para la impresora).
///
/// * [doc] = la estructura de documento_venta_cargar() `{tipo, origen, cabecera, lineas, empresa, cliente,
///   mensajes: {encabezado, pie}, pagos, totales}` + `bd` opcional (plazoCliente, tipoCambioVenta,
///   saldoFavor, ordenCompra, otrosDatos, sac): lo que falte = el PHP sin $pdo, ese bloque no sale.
/// * [ancho] = 32 (58 mm), 40 (matriz, Font B), 42, 48 (80 mm).
/// * [params] = `{15: '1', …}` (claves número o texto); null → [parametrosSinBd].
/// * Fecha de impresión del pie: [ahoraTexto] ('dd/mm/aaaa hh:mm:ss' ya armado) o [ahora]; sin ninguna,
///   la hora del equipo. La fecha que falte en la cabecera también sale de acá.
/// * [provisional] = el ID PROCESO del COMPROBANTE PROVISIONAL que se imprime sin internet (etapa 14).
String fipvivi002(
  Map<String, dynamic> doc,
  int ancho,
  Map<dynamic, dynamic>? params, {
  DateTime? ahora,
  String? ahoraTexto,
  String? provisional,
}) {
  final Map<dynamic, dynamic> pr = params ?? parametrosSinBd;
  final Object momento = ahoraTexto ?? ahora ?? DateTime.now();
  // Lo que el PHP consulta a la BD dentro del formato. Sin doc.bd = el PHP sin $pdo.
  final bdDoc = doc['bd'];
  final Map? bd = _verdadJs(bdDoc) && (bdDoc is Map || bdDoc is List)
      ? (bdDoc is Map ? bdDoc : const {})
      : null;
  bool hay(String k) => bd != null && bd.containsKey(k);

  Object? par(int n) => pr.containsKey(n) ? pr[n] : pr['$n'];
  Object? p(int n, Object? def) => _nn(par(n), def);
  bool on(Object? v) => _enLista(_upperAscii(_trim(_nn(v, ''))), const [
    '1',
    'S',
    'SI',
    'TRUE',
    'YES',
    'Y',
  ]);

  final impCod = on(p(15, '1'));
  final impPago = on(p(20, '1'));
  var impSub = on(p(192, '1'));
  final impTel = on(p(380, '1'));
  final formatoDetalle = _ent(p(151, 1)); // 1=sin IVA, 2=con IVA incluido
  final usarSerieComoNombre = on(p(343, '0'));
  final detalleFilaPorEnter = on(p(391, '0'));
  final mostrarCabys = on(p(307, '0'));
  var mostrarDescuento = on(p(344, '1'));

  // #1429 — COTIZACION: el descuento lo manda el 936 (propio de la cotización)
  final esCotizacion = _nn(doc['tipo'], '') == 'proforma';
  final cotizaSinDescuento = esCotizacion && !on(p(936, '0'));
  if (cotizaSinDescuento) {
    // (el JS también apaga impDesc, que calcula del 26 y no vuelve a leer)
    impSub = false;
    mostrarDescuento = false;
  }

  final cab = _o(doc['cabecera'], const {});
  final lineas = _o(doc['lineas'], const []);
  final emp = _o(doc['empresa'], const {});
  final msg = _nn(doc['mensajes'], const {'encabezado': [], 'pie': []});
  final pagos = _nn(doc['pagos'], const []);

  final moneda = _nn(_g(cab, 'MonedaCodigo'), 'CRC') == 'USD' ? 'USD' : 'CRC';

  // === COMANDOS ESC/POS === (matriz ancho 40 = Font B; térmica = Font A, sin interlineado)
  const esc = '\x1B';
  final esMatriz = ancho == 40;
  final String normal, negrita, grande, interlineado;
  if (esMatriz) {
    normal = '$esc\x21\x01';
    negrita = '$esc\x21\x09';
    grande = '$esc\x21\x19';
    interlineado = '$esc\x33\x12';
  } else {
    normal = '$esc\x21\x00';
    negrita = '$esc\x21\x08';
    grande = '$esc\x21\x18';
    interlineado = '';
  }
  const centro = '$esc\x61\x01';
  const izquierda = '$esc\x61\x00';
  const derecha = '$esc\x61\x02';
  const init = '$esc\x40';

  final ln = _repetir('-', ancho);
  final ln2 = _repetir('=', ancho);
  final t = StringBuffer(init + interlineado);

  // === ENCABEZADO EMPRESA ===
  final nomComercial = _trim(_nn(_g(emp, 'NombreComercial'), ''));
  final razonSocial = _trim(_nn(_g(emp, 'RazonSocial'), ''));
  final nombreEmpresa = _verdad(nomComercial)
      ? nomComercial
      : (_verdad(razonSocial) ? razonSocial : 'EMPRESA');
  final cedulaEmpresa = _trim(_nn(_g(emp, 'Cedula'), ''));
  final telefonoEmpresa = _trim(_nn(_g(emp, 'Telefono'), ''));

  t.write('$centro$grande${_sinTildes(_mbUpper(nombreEmpresa))}$normal\n');
  if (razonSocial != '' && _mbUpper(razonSocial) != _mbUpper(nomComercial)) {
    t.write('$normal$centro${_sinTildes(_mbUpper(razonSocial))}\n');
  }
  if (_verdad(cedulaEmpresa)) {
    t.write('$normal${centro}IDENTIFICACION: $cedulaEmpresa\n');
  }

  // Líneas de encabezado (FacturaDetalles pos=1)
  var encTieneTels = false;
  final encabezado = _g(msg, 'encabezado');
  if (_verdad(encabezado) && _tieneLargo(encabezado)) {
    for (final lineaEnc in _deCorrido(encabezado)) {
      if (_contieneI(lineaEnc, 'TELS') || _contieneI(lineaEnc, 'TEL ')) {
        encTieneTels = true;
      }
      for (final chunk in _trozos(lineaEnc, ancho)) {
        t.write('$normal$centro${_sinTildes(chunk)}\n');
      }
    }
  }
  if (_verdad(telefonoEmpresa) && !encTieneTels) {
    t.write('$normal${centro}TELS $telefonoEmpresa\n');
  }
  t.write('$normal$izquierda$ln2\n');

  // === TIPO DOCUMENTO ===
  final tipoOrigen = _nn(doc['tipo'], 'factura');
  final tipoDoc = _nn(
    _g(cab, 'TipoDocumento'),
    _nn(_g(cab, 'TipoDocumentoReferencia'), '01'),
  );
  String tipoDocNombre;
  if (tipoOrigen == 'proforma') {
    tipoDocNombre = _upperAscii(_trim(_nn(par(291), '')));
    if (!_verdad(tipoDocNombre)) tipoDocNombre = 'PROFORMA';
  } else {
    const tiposNombre = {
      '01': 'FACTURA ELECTRONICA',
      '02': 'NOTA DE DEBITO ELECTRONICA',
      '03': 'NOTA DE CREDITO ELECTRONICA',
      '04': 'TIQUETE ELECTRONICO',
      '09': 'FACTURA DE EXPORTACION',
    };
    tipoDocNombre = tiposNombre[_str(tipoDoc)] ?? 'DOCUMENTO ELECTRONICO';
  }
  final provisionalTxt = _trim(_str(provisional));
  if (provisionalTxt != '') {
    // Etapa 14 — sin internet todavía no hay número ni clave: el papel lo dice con todas las letras.
    t.write('$centro${grande}PROVISIONAL$normal\n');
    t.write('$centro${negrita}ID PROCESO$normal\n');
    t.write('$centro$negrita$provisionalTxt$normal\n');
    for (final renglon in [
      '$tipoDocNombre PENDIENTE',
      'SE EMITE AL VOLVER LA CONEXION',
      'SIN VALOR FISCAL',
    ]) {
      for (final chunk in _trozos(renglon, ancho)) {
        t.write('$centro$chunk\n');
      }
    }
  } else {
    t.write('$centro$grande$tipoDocNombre$normal\n');
    // === NUMERO ===
    final numero = _str(_nn(_g(cab, 'Numero'), ''));
    t.write('$centro$grande$numero$normal\n');
  }

  // === REFERENCIA (solo NC/ND, nunca en proforma) ===
  final referencia = _trim(_nn(_g(cab, 'Referencia'), ''));
  if (referencia != '' &&
      tipoOrigen != 'proforma' &&
      _enLista(tipoDoc, const ['02', '03'])) {
    t.write('$normal$izquierda');
    t.write('${_izq(ancho, 'REF: $referencia')}\n');
  }

  // === CLAVE HACIENDA — solo facturas === (el provisional no tiene clave todavía)
  if (tipoOrigen != 'proforma' && provisionalTxt == '') {
    t.write('$normal$izquierda');
    final clave = _trim(_nn(_g(cab, 'Clave'), ''));
    if (clave != '') {
      // substr/length del JS = unidades UTF-16, igual que substring de Dart.
      for (var posC = 0; posC < clave.length; posC += (ancho - 7)) {
        final chunk = clave.substring(
          posC,
          math.min(clave.length, posC + ancho - 7),
        );
        final pre = posC == 0 ? 'CLAVE: ' : '       ';
        t.write('${_izq(ancho, pre + chunk)}\n');
      }
    }
  }

  // Fecha y forma de pago — #1284 crédito con plazo 0 = CONTADO
  final cliDoc = _o(doc['cliente'], const {});
  final diasCli = _g(cliDoc, 'DiasCredito');
  final plazo = diasCli != null ? _ent(diasCli) : null;
  final formaPagoCodigo = _ventaCondicion(
    _nn(_g(cab, 'FormaPagoCodigo'), _nn(_g(cab, 'CondicionVenta'), '01')),
    plazo,
    bd,
    _str(_nn(_g(cab, 'ClienteCodigo'), _nn(_g(cab, 'ClienteID'), ''))),
  );
  final formaPagoTexto = formaPagoCodigo == '02' ? 'CREDITO' : 'CONTADO';
  final fechaDoc = _leerFecha(_g(cab, 'Fecha'), momento);
  t.write(
    '${_izq(ancho, 'FECHA: ${fechaDoc != null ? _fmtYmdHi(fechaDoc) : '1970/01/01 00:00'}')}\n',
  );
  t.write('${_izq(ancho, 'FORMA PAGO: $formaPagoTexto')}\n');

  // Tipo de entrega (param 22)
  if (on(p(22, '0'))) {
    final modEntrega = _nn(_g(cab, 'ModEntregaCodigo'), '');
    final entregaTxt = _sueltoIgual(modEntrega, '1')
        ? 'LOCAL'
        : (_sueltoIgual(modEntrega, '2') ? 'EXPRESS' : '');
    if (entregaTxt != '') t.write('${_izq(ancho, 'ENTREGA: $entregaTxt')}\n');
  }

  // === CLIENTE ===
  final clienteNombre = _sinTildes(
    _mbUpper(_nn(_g(cab, 'ClienteNombre'), 'CLIENTE')),
  );
  final clienteNombreComercial = _sinTildes(
    _mbUpper(_trim(_nn(_g(cab, 'ClienteNombreComercial'), ''))),
  );
  final clienteNombreJuridico = _sinTildes(
    _mbUpper(_trim(_nn(_g(cab, 'ClienteNombreJuridico'), ''))),
  );
  final clienteCodigo = _str(
    _nn(_g(cab, 'ClienteCodigo'), _nn(_g(cab, 'ClienteID'), '')),
  );
  final clienteCedula = _str(_nn(_g(cab, 'ClienteCedula'), ''));
  final clienteDireccion = _sinTildes(
    _trim(_nn(_g(cab, 'ClienteDireccion'), '')),
  );
  final clienteEmail = _str(_nn(_g(cab, 'ClienteEmail'), ''));
  final esClienteGenerico = _enLista(_upperAscii(_trim(clienteCodigo)), const [
    'SN',
    'S/N',
    '0',
    '',
  ]);

  if (!esClienteGenerico) {
    final nomMostrar = _verdad(clienteNombreComercial)
        ? clienteNombreComercial
        : clienteNombre;
    t.write('$centro$grande$nomMostrar$normal\n');
    final nombreLegal = _verdad(clienteNombreJuridico)
        ? clienteNombreJuridico
        : clienteNombre;
    if (nombreLegal != '' && nombreLegal != nomMostrar) {
      t.write('$normal$centro$nombreLegal\n');
    }
  } else {
    t.write('$centro$grande$clienteNombre$normal\n');
  }

  t.write('$normal$izquierda');
  if (!esClienteGenerico && _verdad(clienteCodigo)) {
    final ced = _verdad(clienteCedula) ? ' CEDULA: $clienteCedula' : '';
    t.write('${_izq(ancho, 'CODIGO: $clienteCodigo$ced')}\n');
  }
  if (!esClienteGenerico && _verdad(clienteDireccion)) {
    for (final chunk in _trozos('DIR: $clienteDireccion', ancho)) {
      t.write('${_izq(ancho, chunk)}\n');
    }
  }
  final clienteTelefono = _trim(_nn(_g(cab, 'ClienteTelefono'), ''));
  if (impTel && _verdad(clienteTelefono)) {
    t.write('${_izq(ancho, 'TELS: $clienteTelefono')}\n');
  }
  if (_verdad(clienteEmail)) {
    t.write(
      '${_izq(ancho, 'EMAIL: ${_mbSubstr(clienteEmail, 0, ancho - 7)}')}\n',
    );
  }
  t.write('$ln2\n');

  // === COLUMNAS ===
  t.write('CANT/BOD/COD/NOMBRE/PRECIO/TOTAL\n');
  t.write('$ln\n');

  // === ARTICULOS ===
  double sumDescuento = 0, sumGravado = 0, sumExento = 0, sumExonerado = 0;
  double sumIva = 0, sumIvaDevuelto = 0, sumTotal = 0;
  final resumenIva =
      <double, List<double>>{}; // tarifa → [venta, iva] (en orden de aparición)

  for (final l in _deCorrido(lineas)) {
    final cant = _flt(_nn(_g(l, 'ArticuloCantidad'), 0));
    final codigo = _str(_nn(_g(l, 'ArticuloCodigo'), ''));
    final serieLinea = _trim(_nn(_g(l, 'ArticuloSerie'), ''));
    final nombreBase = _nn(
      _g(l, 'NombreArticulo'),
      _nn(_g(l, 'ArticuloNombre'), codigo),
    );
    String nombre;
    List<String> serieRenglones;
    // params 343/391 (memoria formatos-impresion.md sec 2026-04-15)
    if (usarSerieComoNombre && serieLinea != '') {
      nombre = _sinTildes(serieLinea.replaceAll(_rxSerieUnaFila, ' '));
      serieRenglones = [];
    } else if (!usarSerieComoNombre &&
        serieLinea != '' &&
        !detalleFilaPorEnter) {
      final serieEnLinea = _sinTildes(
        serieLinea.replaceAll(_rxSerieUnaFila, ' '),
      );
      nombre = '${_sinTildes(_mbUpper(nombreBase))} - $serieEnLinea';
      serieRenglones = [];
    } else {
      nombre = _sinTildes(_mbUpper(nombreBase));
      serieRenglones = serieLinea != ''
          ? serieLinea.split(RegExp(r'\r?\n')).where((x) => x != '').toList()
          : [];
    }

    final precioUnitario = _flt(_nn(_g(l, 'ArticuloVenta'), 0));
    final subtotal1 = _flt(_nn(_g(l, 'ArticuloVentaSubTotal1'), 0));
    final descPct = _flt(_nn(_g(l, 'ArticuloDescuentoPorcentage'), 0));
    final descMonto = _flt(_nn(_g(l, 'ArticuloDescuentoMonto'), 0));
    var exentoLinea = _flt(_nn(_g(l, 'ArticuloVentaExento'), 0));
    final exoneradoLinea = _flt(_nn(_g(l, 'ArticuloVentaExonerado'), 0));
    final ivaMonto = _flt(_nn(_g(l, 'ArticuloIvaMonto'), 0));
    final ivaDevuelto = _flt(_nn(_g(l, 'ArticuloIvaDevuelto'), 0));
    final ivaPct = _ent(
      _nn(_g(l, 'TarifaIva'), _nn(_g(l, 'ArticuloIvaPorcentage'), 0)),
    );
    final bodega = _numTexto(_ent(_nn(_g(l, 'ArticuloBodegaCodigo'), 0)));

    // Gravado y total — SubTotal3 (valor real después de descuento)
    final subtotal3 = _flt(_nn(_g(l, 'ArticuloVentaSubTotal3'), 0));
    final baseNeta = subtotal3 > 0
        ? _round(subtotal3, 2)
        : _round(subtotal1 - descMonto, 2);
    final gravadoLinea = ivaPct > 0 ? baseNeta : 0.0;
    if (ivaPct <= 0 && exentoLinea <= 0) exentoLinea = baseNeta;
    final totalGuardado = _flt(_nn(_g(l, 'ArticuloVentaTotal'), 0));
    final totalLinea = totalGuardado > 0
        ? _round(totalGuardado, 2)
        : _round(baseNeta + ivaMonto - ivaDevuelto, 2);

    sumDescuento += descMonto;
    sumGravado += gravadoLinea;
    sumExento += exentoLinea;
    sumExonerado += exoneradoLinea;
    sumIva += ivaMonto;
    sumIvaDevuelto += ivaDevuelto;
    sumTotal += totalLinea;

    final ri = resumenIva.putIfAbsent(ivaPct, () => [0.0, 0.0]);
    ri[0] += baseNeta;
    ri[1] += ivaMonto;

    final cantStr = cant == cant.floorToDouble()
        ? _numTexto(_ent(cant))
        : _numberFormat(cant, 2);

    // Fila 1: (CODIGO) NOMBRE — sangría según ancho
    final indentLen = ancho <= 32 ? 0 : 5;
    final indent = _repetir(' ', indentLen);
    final anchoDisp = ancho - indentLen;
    if (nombre != '') {
      final nombreCompleto = impCod ? '($codigo) $nombre' : nombre;
      for (final chunk in _trozos(nombreCompleto, anchoDisp)) {
        t.write('${_izq(ancho, indent + chunk)}\n');
      }
    }

    // Serie/Detalle: cada enter un renglón
    for (var sRenglon in serieRenglones) {
      sRenglon = _sinTildes(_trim(sRenglon));
      if (sRenglon == '') continue;
      for (final chunk in _trozos(sRenglon, anchoDisp)) {
        t.write('${_izq(ancho, indent + chunk)}\n');
      }
    }

    // #1429 — cotización con el 936 apagado: precio YA rebajado; total de la línea = baseNeta
    var precioImpreso = precioUnitario;
    double? netoLineaImpreso;
    if (cotizaSinDescuento && descMonto > 0 && cant > 0) {
      netoLineaImpreso = baseNeta;
      precioImpreso = _round(netoLineaImpreso / cant, 2);
    }

    // Fila 2: CANT (B#)   PRECIO  TOTAL
    String precioStr, totalStr;
    if (formatoDetalle == 2) {
      final precioConIva = _round(precioImpreso * (1 + ivaPct / 100), 2);
      final totalConIva = netoLineaImpreso != null
          ? _round(netoLineaImpreso * (1 + ivaPct / 100), 2)
          : _round(precioConIva * cant, 2);
      precioStr = _numberFormat(precioConIva, 2);
      totalStr = _numberFormat(totalConIva, 2);
    } else {
      precioStr = _numberFormat(precioImpreso, 2);
      final totalSinDesc = netoLineaImpreso != null
          ? _round(netoLineaImpreso, 2)
          : _round(precioImpreso * cant, 2);
      totalStr = _numberFormat(totalSinDesc, 2);
    }

    var tags = '(G${_numTexto(ivaPct)})';
    if (descMonto > 0 && mostrarDescuento) {
      tags +=
          '(D${_rtrimChars(_rtrimChars(_numberFormat(descPct, 2), '0'), '.')}%)';
    }
    final sep2 = ancho <= 32 ? ' ' : '   ';
    final izq2 = '$cantStr$sep2(B$bodega) $tags';
    final der2 = '$precioStr $totalStr';
    t.write('${_dosCol(ancho, izq2, der2)}\n');

    // === DETALLE ADICIONAL (param 307=1): Cabys, Cod, Uni, Desc, Grav, Exo, Exe ===
    if (mostrarCabys) {
      final cabysL = _trim(_nn(_g(l, 'ArticuloCabys'), ''));
      final unidadL = _trim(_nn(_g(l, 'ArticuloUnidadMedida'), ''));
      final partes = <String>[];
      if (cabysL != '') partes.add('Cabys: $cabysL');
      partes.add('Cod: $codigo');
      if (unidadL != '') partes.add('Uni: $unidadL');
      if (descMonto > 0 && !cotizaSinDescuento) {
        partes.add('Desc: ${_numberFormat(descMonto, 2)}');
      }
      if (gravadoLinea > 0) {
        partes.add('Grav: ${_numberFormat(gravadoLinea, 2)}');
      }
      if (exoneradoLinea > 0) {
        partes.add('Exo: ${_numberFormat(exoneradoLinea, 2)}');
      }
      if (exentoLinea > 0) partes.add('Exe: ${_numberFormat(exentoLinea, 2)}');
      for (final renglon in _envolverPartes(
        partes.map(_sinTildes).toList(),
        ancho,
      )) {
        t.write('${_izq(ancho, renglon)}\n');
      }
    }

    t.write('$ln\n');
  }

  if (formatoDetalle == 2) {
    t.write('${_centro(ancho, 'Precio de articulo ya incluye IVA')}\n');
    t.write('$ln\n');
  }

  // === TOTALES DESGLOSADOS === (#936: V. BRUTA − DESCUENTO = SUB TOTAL → bases → IVA → TOTAL)
  final totales = _nn(doc['totales'], const {});
  final mercGravada = _flt(_nn(_g(totales, 'merc_gravada'), sumGravado));
  final mercExenta = _flt(_nn(_g(totales, 'merc_exenta'), sumExento));
  final servGravado = _flt(_nn(_g(totales, 'serv_gravado'), 0));
  final servExento = _flt(_nn(_g(totales, 'serv_exento'), 0));
  final totalDescuento = _flt(_nn(_g(totales, 'descuento'), sumDescuento));
  final totalIva = _flt(_nn(_g(totales, 'iva'), sumIva));
  final totalIvaDevuelto = _flt(
    _nn(_g(totales, 'iva_devuelto'), sumIvaDevuelto),
  );
  final totalImpServicio = _flt(_nn(_g(totales, 'impuesto_servicio'), 0));

  final subTotalNeto = _round(
    mercGravada + mercExenta + servGravado + servExento + sumExonerado,
    2,
  );
  final ventaBruta = _round(subTotalNeto + totalDescuento, 2);

  t.write(derecha);
  if (impSub) {
    if (totalDescuento > 0) {
      t.write('V. BRUTA ${_numberFormat(ventaBruta, 2)}\n');
      t.write('DESCUENTO ${_numberFormat(totalDescuento, 2)}\n');
    }
    t.write('SUB TOTAL ${_numberFormat(subTotalNeto, 2)}\n');
    if (mercGravada > 0) {
      t.write('MERC GRAVADA ${_numberFormat(mercGravada, 2)}\n');
    }
    if (servGravado > 0) {
      t.write('SERV GRAVADO ${_numberFormat(servGravado, 2)}\n');
    }
    if (sumExonerado > 0) {
      t.write('MERC EXONERADA ${_numberFormat(sumExonerado, 2)}\n');
    }
    if (mercExenta > 0) {
      t.write('MERC EXENTA ${_numberFormat(mercExenta, 2)}\n');
    }
    if (servExento > 0) {
      t.write('SERV EXENTO ${_numberFormat(servExento, 2)}\n');
    }
  } else if (totalDescuento > 0 && !cotizaSinDescuento) {
    t.write('DESCUENTO ${_numberFormat(totalDescuento, 2)}\n');
  }
  if (totalIva > 0) t.write('IVA ${_numberFormat(totalIva, 2)}\n');
  if (totalIvaDevuelto > 0) {
    t.write('IVA DEVUELTO ${_numberFormat(totalIvaDevuelto, 2)}\n');
  }
  if (totalImpServicio > 0) {
    t.write('IMP. SERVICIO ${_numberFormat(totalImpServicio, 2)}\n');
  }
  t.write('$izquierda$ln2\n');

  // TOTAL (total de cabecera, el mismo de pantalla)
  final anchoGrande = ancho;
  final totalCabecera = _flt(
    _nn(_g(_nn(doc['totales'], const {}), 'total'), 0),
  );
  final totalFinal = totalCabecera > 0 ? totalCabecera : sumTotal;
  final totalFormateado = '$moneda ${_numberFormat(totalFinal, 2)}';

  // === EQUIVALENTE USD (param 110) — tipo de cambio de venta ya resuelto en doc.bd.tipoCambioVenta ===
  final monedaNacional = _upperAscii(_trim(_nn(par(249), 'CRC')));
  final monedaDoc = _upperAscii(_trim(_nn(_g(cab, 'MonedaCodigo'), 'CRC')));
  var equivUSDStr = '';
  if (on(p(110, '0')) &&
      monedaDoc == monedaNacional &&
      totalFinal > 0 &&
      hay('tipoCambioVenta')) {
    final tcVenta = _verdad(bd!['tipoCambioVenta'])
        ? _flt(bd['tipoCambioVenta'])
        : 0.0;
    if (tcVenta > 1) {
      final equivUSD = _round(totalFinal / tcVenta, 2);
      equivUSDStr = '\$${_numberFormat(equivUSD, 2)}';
    }
  }
  if (equivUSDStr != '') {
    t.write(
      '$izquierda$grande${_dosCol(anchoGrande, equivUSDStr, totalFormateado)}$normal\n',
    );
  } else {
    t.write(
      '$izquierda$grande${_strPad(totalFormateado, anchoGrande, ' ', _izqPad)}$normal\n',
    );
  }

  // === RESUMEN IVA ===
  final tarifas = resumenIva.keys.toList()..sort();
  var tieneResumen = false;
  for (final tarifa in tarifas) {
    final datos = resumenIva[tarifa]!;
    if (tarifa > 0 && datos[1] > 0) {
      if (!tieneResumen) {
        t.write('${_centro(ancho, '*******RESUMEN IVA*****')}\n');
        t.write('${_dosCol(ancho, '  IVA%', 'VENTA       IVA')}\n');
        tieneResumen = true;
      }
      final lineaIva =
          '  (${_numTexto(tarifa)}%) ${_numberFormat(datos[0], 2)} ${_numberFormat(datos[1], 2)}';
      t.write('${_der(ancho, lineaIva)}\n');
    }
  }
  if (tieneResumen) {
    for (final tarifa in tarifas) {
      if (tarifa <= 0) {
        t.write('${_der(ancho, 'SIN DEFINIR')}\n');
        break;
      }
    }
  }

  // === FECHA VENCIMIENTO (solo crédito) ===
  if (formaPagoTexto == 'CREDITO') {
    final diasCredito = _ent(_nn(_g(cab, 'DiasCredito'), 0));
    if (diasCredito > 0) {
      final f = _leerFecha(_g(cab, 'Fecha'), momento);
      final fechaVence = f != null
          ? _fmtYmd(_sumarDias(f, diasCredito.toInt()))
          : '1970/01/01';
      t.write('$izquierda${_izq(ancho, 'PARA CANCELAR EL $fechaVence')}\n');
    }
  }

  // === MEDIOS DE PAGO (param 20) ===
  if (impPago && _verdad(pagos) && _tieneLargo(pagos)) {
    double sumPagos = 0, vuelto = 0;
    for (final pago in _deCorrido(pagos)) {
      final monto = _flt(_nn(_g(pago, 'Monto'), 0));
      final medioCod = _nn(_g(pago, 'MedioPagoCodigo'), '');
      final medioNombre = _nn(
        _g(pago, 'MedioPagoNombre'),
        _nn(_g(pago, 'CuentaNombre'), ''),
      );
      if (_enLista(medioCod, const ['00', '99'])) {
        vuelto += monto.abs();
        continue;
      }
      if (monto < 0) {
        vuelto += monto.abs();
        continue;
      }
      final label = '${_str(medioCod)}-${_str(medioNombre)}';
      t.write('${_dosCol(ancho, label, _numberFormat(monto, 2))}\n');
      sumPagos += monto;
    }
    if (vuelto > 0 && formaPagoTexto != 'CREDITO') {
      final pagaCon = sumPagos + vuelto;
      t.write('${_dosCol(ancho, 'PAGA CON', _numberFormat(pagaCon, 2))}\n');
      t.write('${_dosCol(ancho, 'Vuelto', _numberFormat(vuelto, 2))}\n');
    }
  }

  // === SALDO A FAVOR (param 346) — ya resuelto en doc.bd.saldoFavor ===
  if (on(p(346, '0')) &&
      !esClienteGenerico &&
      hay('saldoFavor') &&
      _verdad(clienteCodigo)) {
    final saldoFavor = _verdad(bd!['saldoFavor'])
        ? _flt(bd['saldoFavor'])
        : 0.0;
    if (saldoFavor > 0) {
      t.write(
        '${_dosCol(ancho, 'SALDO A FAVOR', _numberFormat(saldoFavor, 2))}\n',
      );
    }
  }
  t.write('$ln\n');

  // === FOOTER ===
  if (on(p(38, '1'))) {
    final agenteNombre = _sinTildes(
      _nn(_g(cab, 'VendedorNombre'), _nn(_g(cab, 'AgenteNombre'), '')),
    );
    final agenteCodigo = _trim(_nn(_g(cab, 'AgenteCodigo'), ''));
    if (_verdad(agenteNombre)) {
      var lineaAgente = 'AGEN: ${_mbUpper(agenteNombre)}';
      if (_verdad(agenteCodigo)) lineaAgente += ' ($agenteCodigo)';
      t.write('${_izq(ancho, lineaAgente)}\n');
    }
  }
  if (on(p(43, '0'))) {
    final usuarioNombre = _sinTildes(_nn(_g(cab, 'UsuarioNombre'), ''));
    final usuarioCodigo = _trim(_nn(_g(cab, 'UsuarioCodigo'), ''));
    if (_verdad(usuarioNombre)) {
      var lineaUsuario = 'USUA: ${_mbUpper(usuarioNombre)}';
      if (_verdad(usuarioCodigo)) lineaUsuario += ' ($usuarioCodigo)';
      t.write('${_izq(ancho, lineaUsuario)}\n');
    }
  }

  t.write('${_izq(ancho, 'B=BODEGA, D=DESC, G=CON IVA')}\n');

  // === DETALLE (cada enter un renglón; «DETALLE: » solo en el primero) ===
  final detalleNotas = _trim(_nn(_g(cab, 'Detalle'), ''));
  if (detalleNotas != '') {
    var primera = true;
    for (var lineaDet in detalleNotas.split(RegExp(r'\r\n|\r|\n'))) {
      lineaDet = _sinTildes(lineaDet);
      String textoN;
      if (primera) {
        textoN = 'DETALLE: $lineaDet';
        primera = false;
      } else {
        textoN = lineaDet;
      }
      if (textoN == '') {
        t.write('\n');
        continue;
      }
      for (final chunk in _trozos(textoN, ancho)) {
        t.write('${_izq(ancho, chunk)}\n');
      }
    }
  }
  // Orden de compra — doc.bd.ordenCompra (FacturaVentaOrdenCompra)
  final numeroDoc = _str(_nn(_g(cab, 'Numero'), ''));
  if (hay('ordenCompra') && _verdad(numeroDoc)) {
    final oc = _trim(_verdad(bd!['ordenCompra']) ? bd['ordenCompra'] : '');
    if (oc != '') t.write('${_izq(ancho, 'OC: $oc')}\n');
  }
  final detallePide = _trim(_nn(_g(cab, 'DetallePide'), ''));
  if (detallePide != '') {
    t.write('${_izq(ancho, 'PEDIDO POR: $detallePide')}\n');
  }
  // Otros datos — doc.bd.otrosDatos (YA ordenados por NombreCampo como los da SQL Server)
  if (hay('otrosDatos') && _verdad(numeroDoc)) {
    for (final od in _deCorrido(_o(bd!['otrosDatos'], const []))) {
      final nombre = _trim(_nn(_g(od, 'NombreCampo'), ''));
      final valor = _trim(_nn(_g(od, 'ValorCampo'), ''));
      if (nombre != '' && valor != '') {
        final textoOD = '${_sinTildes(_mbUpper(nombre))}: ${_sinTildes(valor)}';
        for (final chunk in _trozos(textoOD, ancho)) {
          t.write('${_izq(ancho, chunk)}\n');
        }
      }
    }
  }

  if (tipoOrigen == 'proforma') {
    t.write('$centro${negrita}DOCUMENTO SIN VALOR FISCAL$normal\n');
    final origenDoc = _nn(doc['origen'], '');
    if (origenDoc == 'cotiza' || origenDoc == 'historico') {
      var tituloArch = _upperAscii(_trim(_nn(par(291), '')));
      if (!_verdad(tituloArch)) tituloArch = 'PROFORMA';
      t.write('$centro$negrita$tituloArch ARCHIVADA$normal\n');
    }
  } else {
    // Pie de FacturaDetalles (pos=2)
    final pie = _g(msg, 'pie');
    if (_verdad(pie) && _tieneLargo(pie)) {
      t.write(centro);
      for (final lineaPie in _deCorrido(pie)) {
        for (final chunk in _trozos(lineaPie, ancho)) {
          t.write('${_sinTildes(chunk)}\n');
        }
      }
    }
    // Resolución (param 123)
    final resolucion = _sinTildes(_trim(_nn(_g(emp, 'Resolucion'), '')));
    if (_verdad(resolucion)) {
      t.write(izquierda);
      for (final chunk in _trozos(resolucion, ancho)) {
        t.write('$chunk\n');
      }
    }
    // Copia/Original (el orquestador reemplaza el placeholder)
    t.write('$centro$grande{{COPIA_ETIQUETA}}$normal\n');

    // SAC: bloque MESA — doc.bd.sac = {Mesa, Salon} (VentaMadreSac) o null
    if (hay('sac') && _verdad(_g(cab, 'Numero')) && _verdadJs(bd!['sac'])) {
      final mesaTxt = _sinTildes(_trim(_str(_g(bd['sac'], 'Mesa'))));
      final salonTxt = _sinTildes(_trim(_str(_g(bd['sac'], 'Salon'))));
      var lineaMesa = 'MESA $mesaTxt';
      if (salonTxt != '') lineaMesa += ' - $salonTxt';
      t.write('$centro${_repetir('*', ancho)}\n');
      t.write('$centro$grande$lineaMesa$normal\n');
      t.write('$centro${_repetir('*', ancho)}\n');
    }

    // FIRMA CLIENTE (solo crédito)
    if (formaPagoTexto == 'CREDITO') {
      t.write('$izquierda\n\n\n');
      t.write('${_repetir('_', ancho)}\n');
      t.write('${centro}FIRMA CLIENTE\n\n\n');
      t.write(
        '${izquierda}NOMBRE: ${_repetir('_', math.max(1, ancho - 8))}\n\n',
      );
      t.write('CEDULA: ${_repetir('_', math.max(1, ancho - 8))}\n\n');
      t.write('FECHA:  ${_repetir('_', math.max(1, ancho - 8))}\n\n');
    }
  }
  // Versión y fecha de impresión
  t.write('${centro}Ver.4.5\n');
  t.write('$negrita${_fmtAhora(momento)}$normal\n');
  t.write('$normal$izquierda\n\n\n');
  return t.toString();
}

// =====================================================================================
// Tabla de toUpperCase() de JavaScript (V8/ICU, Unicode 15.1) para lo que no es ASCII.
// Generada con node: [desde, hasta, paso, delta] por tramo + los que dan varios caracteres.
// =====================================================================================

// dart format off
const List<int> _mayusRangos = [
  0xB5, 0xB5, 1, 743,  0xE0, 0xF6, 1, -32,  0xF8, 0xFE, 1, -32,  0xFF, 0xFF, 1, 121,
  0x101, 0x12F, 2, -1,  0x131, 0x131, 1, -232,  0x133, 0x137, 2, -1,  0x13A, 0x148, 2, -1,
  0x14B, 0x177, 2, -1,  0x17A, 0x17E, 2, -1,  0x17F, 0x17F, 1, -300,  0x180, 0x180, 1, 195,
  0x183, 0x185, 2, -1,  0x188, 0x188, 1, -1,  0x18C, 0x18C, 1, -1,  0x192, 0x192, 1, -1,
  0x195, 0x195, 1, 97,  0x199, 0x199, 1, -1,  0x19A, 0x19A, 1, 163,  0x19E, 0x19E, 1, 130,
  0x1A1, 0x1A5, 2, -1,  0x1A8, 0x1A8, 1, -1,  0x1AD, 0x1AD, 1, -1,  0x1B0, 0x1B0, 1, -1,
  0x1B4, 0x1B6, 2, -1,  0x1B9, 0x1B9, 1, -1,  0x1BD, 0x1BD, 1, -1,  0x1BF, 0x1BF, 1, 56,
  0x1C5, 0x1C5, 1, -1,  0x1C6, 0x1C6, 1, -2,  0x1C8, 0x1C8, 1, -1,  0x1C9, 0x1C9, 1, -2,
  0x1CB, 0x1CB, 1, -1,  0x1CC, 0x1CC, 1, -2,  0x1CE, 0x1DC, 2, -1,  0x1DD, 0x1DD, 1, -79,
  0x1DF, 0x1EF, 2, -1,  0x1F2, 0x1F2, 1, -1,  0x1F3, 0x1F3, 1, -2,  0x1F5, 0x1F5, 1, -1,
  0x1F9, 0x21F, 2, -1,  0x223, 0x233, 2, -1,  0x23C, 0x23C, 1, -1,  0x23F, 0x240, 1, 10815,
  0x242, 0x242, 1, -1,  0x247, 0x24F, 2, -1,  0x250, 0x250, 1, 10783,  0x251, 0x251, 1, 10780,
  0x252, 0x252, 1, 10782,  0x253, 0x253, 1, -210,  0x254, 0x254, 1, -206,  0x256, 0x257, 1, -205,
  0x259, 0x259, 1, -202,  0x25B, 0x25B, 1, -203,  0x25C, 0x25C, 1, 42319,  0x260, 0x260, 1, -205,
  0x261, 0x261, 1, 42315,  0x263, 0x263, 1, -207,  0x265, 0x265, 1, 42280,  0x266, 0x266, 1, 42308,
  0x268, 0x268, 1, -209,  0x269, 0x269, 1, -211,  0x26A, 0x26A, 1, 42308,  0x26B, 0x26B, 1, 10743,
  0x26C, 0x26C, 1, 42305,  0x26F, 0x26F, 1, -211,  0x271, 0x271, 1, 10749,  0x272, 0x272, 1, -213,
  0x275, 0x275, 1, -214,  0x27D, 0x27D, 1, 10727,  0x280, 0x280, 1, -218,  0x282, 0x282, 1, 42307,
  0x283, 0x283, 1, -218,  0x287, 0x287, 1, 42282,  0x288, 0x288, 1, -218,  0x289, 0x289, 1, -69,
  0x28A, 0x28B, 1, -217,  0x28C, 0x28C, 1, -71,  0x292, 0x292, 1, -219,  0x29D, 0x29D, 1, 42261,
  0x29E, 0x29E, 1, 42258,  0x345, 0x345, 1, 84,  0x371, 0x373, 2, -1,  0x377, 0x377, 1, -1,
  0x37B, 0x37D, 1, 130,  0x3AC, 0x3AC, 1, -38,  0x3AD, 0x3AF, 1, -37,  0x3B1, 0x3C1, 1, -32,
  0x3C2, 0x3C2, 1, -31,  0x3C3, 0x3CB, 1, -32,  0x3CC, 0x3CC, 1, -64,  0x3CD, 0x3CE, 1, -63,
  0x3D0, 0x3D0, 1, -62,  0x3D1, 0x3D1, 1, -57,  0x3D5, 0x3D5, 1, -47,  0x3D6, 0x3D6, 1, -54,
  0x3D7, 0x3D7, 1, -8,  0x3D9, 0x3EF, 2, -1,  0x3F0, 0x3F0, 1, -86,  0x3F1, 0x3F1, 1, -80,
  0x3F2, 0x3F2, 1, 7,  0x3F3, 0x3F3, 1, -116,  0x3F5, 0x3F5, 1, -96,  0x3F8, 0x3F8, 1, -1,
  0x3FB, 0x3FB, 1, -1,  0x430, 0x44F, 1, -32,  0x450, 0x45F, 1, -80,  0x461, 0x481, 2, -1,
  0x48B, 0x4BF, 2, -1,  0x4C2, 0x4CE, 2, -1,  0x4CF, 0x4CF, 1, -15,  0x4D1, 0x52F, 2, -1,
  0x561, 0x586, 1, -48,  0x10D0, 0x10FA, 1, 3008,  0x10FD, 0x10FF, 1, 3008,  0x13F8, 0x13FD, 1, -8,
  0x1C80, 0x1C80, 1, -6254,  0x1C81, 0x1C81, 1, -6253,  0x1C82, 0x1C82, 1, -6244,  0x1C83, 0x1C84, 1, -6242,
  0x1C85, 0x1C85, 1, -6243,  0x1C86, 0x1C86, 1, -6236,  0x1C87, 0x1C87, 1, -6181,  0x1C88, 0x1C88, 1, 35266,
  0x1D79, 0x1D79, 1, 35332,  0x1D7D, 0x1D7D, 1, 3814,  0x1D8E, 0x1D8E, 1, 35384,  0x1E01, 0x1E95, 2, -1,
  0x1E9B, 0x1E9B, 1, -59,  0x1EA1, 0x1EFF, 2, -1,  0x1F00, 0x1F07, 1, 8,  0x1F10, 0x1F15, 1, 8,
  0x1F20, 0x1F27, 1, 8,  0x1F30, 0x1F37, 1, 8,  0x1F40, 0x1F45, 1, 8,  0x1F51, 0x1F57, 2, 8,
  0x1F60, 0x1F67, 1, 8,  0x1F70, 0x1F71, 1, 74,  0x1F72, 0x1F75, 1, 86,  0x1F76, 0x1F77, 1, 100,
  0x1F78, 0x1F79, 1, 128,  0x1F7A, 0x1F7B, 1, 112,  0x1F7C, 0x1F7D, 1, 126,  0x1FB0, 0x1FB1, 1, 8,
  0x1FBE, 0x1FBE, 1, -7205,  0x1FD0, 0x1FD1, 1, 8,  0x1FE0, 0x1FE1, 1, 8,  0x1FE5, 0x1FE5, 1, 7,
  0x214E, 0x214E, 1, -28,  0x2170, 0x217F, 1, -16,  0x2184, 0x2184, 1, -1,  0x24D0, 0x24E9, 1, -26,
  0x2C30, 0x2C5F, 1, -48,  0x2C61, 0x2C61, 1, -1,  0x2C65, 0x2C65, 1, -10795,  0x2C66, 0x2C66, 1, -10792,
  0x2C68, 0x2C6C, 2, -1,  0x2C73, 0x2C73, 1, -1,  0x2C76, 0x2C76, 1, -1,  0x2C81, 0x2CE3, 2, -1,
  0x2CEC, 0x2CEE, 2, -1,  0x2CF3, 0x2CF3, 1, -1,  0x2D00, 0x2D25, 1, -7264,  0x2D27, 0x2D27, 1, -7264,
  0x2D2D, 0x2D2D, 1, -7264,  0xA641, 0xA66D, 2, -1,  0xA681, 0xA69B, 2, -1,  0xA723, 0xA72F, 2, -1,
  0xA733, 0xA76F, 2, -1,  0xA77A, 0xA77C, 2, -1,  0xA77F, 0xA787, 2, -1,  0xA78C, 0xA78C, 1, -1,
  0xA791, 0xA793, 2, -1,  0xA794, 0xA794, 1, 48,  0xA797, 0xA7A9, 2, -1,  0xA7B5, 0xA7C3, 2, -1,
  0xA7C8, 0xA7CA, 2, -1,  0xA7D1, 0xA7D1, 1, -1,  0xA7D7, 0xA7D9, 2, -1,  0xA7F6, 0xA7F6, 1, -1,
  0xAB53, 0xAB53, 1, -928,  0xAB70, 0xABBF, 1, -38864,  0xFF41, 0xFF5A, 1, -32,  0x10428, 0x1044F, 1, -40,
  0x104D8, 0x104FB, 1, -40,  0x10597, 0x105A1, 1, -39,  0x105A3, 0x105B1, 1, -39,  0x105B3, 0x105B9, 1, -39,
  0x105BB, 0x105BC, 1, -39,  0x10CC0, 0x10CF2, 1, -64,  0x118C0, 0x118DF, 1, -32,  0x16E60, 0x16E7F, 1, -32,
  0x1E922, 0x1E943, 1, -34,
];

const Map<int, List<int>> _mayusVarias = {
  0xDF: [0x53, 0x53], 0x149: [0x2BC, 0x4E], 0x1F0: [0x4A, 0x30C], 0x390: [0x399, 0x308, 0x301],
  0x3B0: [0x3A5, 0x308, 0x301], 0x587: [0x535, 0x552], 0x1E96: [0x48, 0x331], 0x1E97: [0x54, 0x308],
  0x1E98: [0x57, 0x30A], 0x1E99: [0x59, 0x30A], 0x1E9A: [0x41, 0x2BE], 0x1F50: [0x3A5, 0x313],
  0x1F52: [0x3A5, 0x313, 0x300], 0x1F54: [0x3A5, 0x313, 0x301], 0x1F56: [0x3A5, 0x313, 0x342], 0x1F80: [0x1F08, 0x399],
  0x1F81: [0x1F09, 0x399], 0x1F82: [0x1F0A, 0x399], 0x1F83: [0x1F0B, 0x399], 0x1F84: [0x1F0C, 0x399],
  0x1F85: [0x1F0D, 0x399], 0x1F86: [0x1F0E, 0x399], 0x1F87: [0x1F0F, 0x399], 0x1F88: [0x1F08, 0x399],
  0x1F89: [0x1F09, 0x399], 0x1F8A: [0x1F0A, 0x399], 0x1F8B: [0x1F0B, 0x399], 0x1F8C: [0x1F0C, 0x399],
  0x1F8D: [0x1F0D, 0x399], 0x1F8E: [0x1F0E, 0x399], 0x1F8F: [0x1F0F, 0x399], 0x1F90: [0x1F28, 0x399],
  0x1F91: [0x1F29, 0x399], 0x1F92: [0x1F2A, 0x399], 0x1F93: [0x1F2B, 0x399], 0x1F94: [0x1F2C, 0x399],
  0x1F95: [0x1F2D, 0x399], 0x1F96: [0x1F2E, 0x399], 0x1F97: [0x1F2F, 0x399], 0x1F98: [0x1F28, 0x399],
  0x1F99: [0x1F29, 0x399], 0x1F9A: [0x1F2A, 0x399], 0x1F9B: [0x1F2B, 0x399], 0x1F9C: [0x1F2C, 0x399],
  0x1F9D: [0x1F2D, 0x399], 0x1F9E: [0x1F2E, 0x399], 0x1F9F: [0x1F2F, 0x399], 0x1FA0: [0x1F68, 0x399],
  0x1FA1: [0x1F69, 0x399], 0x1FA2: [0x1F6A, 0x399], 0x1FA3: [0x1F6B, 0x399], 0x1FA4: [0x1F6C, 0x399],
  0x1FA5: [0x1F6D, 0x399], 0x1FA6: [0x1F6E, 0x399], 0x1FA7: [0x1F6F, 0x399], 0x1FA8: [0x1F68, 0x399],
  0x1FA9: [0x1F69, 0x399], 0x1FAA: [0x1F6A, 0x399], 0x1FAB: [0x1F6B, 0x399], 0x1FAC: [0x1F6C, 0x399],
  0x1FAD: [0x1F6D, 0x399], 0x1FAE: [0x1F6E, 0x399], 0x1FAF: [0x1F6F, 0x399], 0x1FB2: [0x1FBA, 0x399],
  0x1FB3: [0x391, 0x399], 0x1FB4: [0x386, 0x399], 0x1FB6: [0x391, 0x342], 0x1FB7: [0x391, 0x342, 0x399],
  0x1FBC: [0x391, 0x399], 0x1FC2: [0x1FCA, 0x399], 0x1FC3: [0x397, 0x399], 0x1FC4: [0x389, 0x399],
  0x1FC6: [0x397, 0x342], 0x1FC7: [0x397, 0x342, 0x399], 0x1FCC: [0x397, 0x399], 0x1FD2: [0x399, 0x308, 0x300],
  0x1FD3: [0x399, 0x308, 0x301], 0x1FD6: [0x399, 0x342], 0x1FD7: [0x399, 0x308, 0x342], 0x1FE2: [0x3A5, 0x308, 0x300],
  0x1FE3: [0x3A5, 0x308, 0x301], 0x1FE4: [0x3A1, 0x313], 0x1FE6: [0x3A5, 0x342], 0x1FE7: [0x3A5, 0x308, 0x342],
  0x1FF2: [0x1FFA, 0x399], 0x1FF3: [0x3A9, 0x399], 0x1FF4: [0x38F, 0x399], 0x1FF6: [0x3A9, 0x342],
  0x1FF7: [0x3A9, 0x342, 0x399], 0x1FFC: [0x3A9, 0x399], 0xFB00: [0x46, 0x46], 0xFB01: [0x46, 0x49],
  0xFB02: [0x46, 0x4C], 0xFB03: [0x46, 0x46, 0x49], 0xFB04: [0x46, 0x46, 0x4C], 0xFB05: [0x53, 0x54],
  0xFB06: [0x53, 0x54], 0xFB13: [0x544, 0x546], 0xFB14: [0x544, 0x535], 0xFB15: [0x544, 0x53B],
  0xFB16: [0x54E, 0x546], 0xFB17: [0x544, 0x53D],
};
// dart format on
