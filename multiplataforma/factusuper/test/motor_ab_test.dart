// Prueba A/B del motor (#3957): el cálculo Dart tiene que dar EXACTAMENTE lo mismo que FSDoc de la web.
// Los casos los genera el JS real:  node tool/ab_js.js <factusuper_documento.js> test/ab_casos.json
// (sin el archivo, la prueba se salta: el JS vive en el servidor, no en este repo).
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/motor/linea.dart';
import 'package:factusuper/motor/redondeo.dart';
import 'package:flutter_test/flutter_test.dart';

bool igual(Object? esperado, double real) {
  if (esperado == null) return real.isNaN || real.isInfinite; // JSON de NaN/Infinity = null
  return (esperado as num).toDouble() == real;
}

void main() {
  final archivo = File('test/ab_casos.json');
  final hay = archivo.existsSync();
  final datos = hay ? jsonDecode(archivo.readAsStringSync()) as Map<String, dynamic> : const <String, dynamic>{};

  test('redondear() = el de la web', () {
    final fallas = <String>[];
    for (final r in (datos['redondeos'] as List)) {
      final real = redondear(r[0] as num, r[1] as int);
      if (!igual(r[2], real)) fallas.add('redondear(${r[0]}, ${r[1]}) web=${r[2]} app=$real');
    }
    expect(fallas, isEmpty, reason: fallas.take(10).join('\n'));
  }, skip: hay ? false : 'falta test/ab_casos.json');

  test('líneas y totales = los de la web', () {
    final fallas = <String>[];
    var n = 0;
    for (final c in (datos['casos'] as List)) {
      final p = (c['params'] as Map).map((k, v) => MapEntry(int.parse(k as String), v as String?));
      final dec = Decimales.desdeParametros(p);
      final lineas = <Linea>[];
      for (final e in (c['entrada'] as List)) {
        final m = e as Map<String, dynamic>;
        final exo = m['exo'] as Map<String, dynamic>?;
        lineas.add(calcular(
          Linea(
            codigo: m['codigo'] as String,
            cantidad: (m['cantidad'] as num).toDouble(),
            precio: (m['precio'] as num).toDouble(),
            tarifa: (m['tarifa'] as num).toDouble(),
            naturaleza: m['naturaleza'] as String,
            costo: (m['costo'] as num).toDouble(),
            descuento: ((m['descuento'] ?? 0) as num).toDouble(),
            descMonto: (m['descMonto'] as num?)?.toDouble(),
            exo: exo == null ? null : Exoneracion(porcentaje: (exo['porcentaje'] as num).toDouble()),
          ),
          dec,
          c['medioPago'] as String,
        ));
      }
      final esperadas = c['lineas'] as List;
      for (var i = 0; i < lineas.length; i++) {
        final app = lineas[i].calculado();
        (esperadas[i] as Map<String, dynamic>).forEach((k, v) {
          if (!igual(v, (app[k] as num).toDouble())) fallas.add('caso $n línea $i $k: web=$v app=${app[k]} · ${jsonEncode(c['entrada'][i])} ${c['params']}');
        });
      }
      final t = totales(lineas, dec).aMapa();
      (c['totales'] as Map<String, dynamic>).forEach((k, v) {
        if (!igual(v, (t[k] as num).toDouble())) fallas.add('caso $n totales $k: web=$v app=${t[k]}');
      });
      final cajas = c['cajaPct'] as List;
      for (var i = 0; i < lineas.length; i++) {
        final l = lineas[i]..uxm = 12..descCaja = 7.5;
        if (!igual(cajas[i], descuentoCajaPct(l))) fallas.add('caso $n cajaPct $i: web=${cajas[i]} app=${descuentoCajaPct(l)}');
      }
      n++;
    }
    expect(fallas, isEmpty, reason: '${fallas.length} diferencias:\n${fallas.take(15).join('\n')}');
  }, skip: hay ? false : 'falta test/ab_casos.json');
}
