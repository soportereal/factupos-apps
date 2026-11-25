// #3957 — A/B de la ROMANA: DatosCaja.romanaLeer contra romanaLeer REAL de la web (node tool/ab_romana.js …).
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/datos_caja.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final f = File('test/ab_romana.json');
  test('romana = la web', () {
    final casos = (jsonDecode(f.readAsStringSync()) as List)
        .cast<Map<String, dynamic>>();
    final malos = <String>[];
    for (var i = 0; i < casos.length; i++) {
      final k = casos[i], e = k['E'] as Map<String, dynamic>;
      final d = DatosCaja.desde(
        articulos: (e['articulos'] as List).cast<Map<String, dynamic>>(),
        precios: (e['precios'] as List).cast<Map<String, dynamic>>(),
        catalogos: {
          'romana': [e['cfg']],
          'estacion': [
            {...(e['estacion'] as Map), 'clave': 'actual'},
          ],
          'tipo_cambio': [
            {'moneda': 'USD', 'fecha': '2026-11-25', 'venta': e['tc']},
          ],
        },
      );
      final r = d.romanaLeer('${k['codigo']}');
      final app = r == null
          ? null
          : r['error'] != null
          ? {'error': r['error']}
          : {
              'articulo': (r['articulo'] as Map)['codigo'],
              'cantidad': r['cantidad'],
              'tipo': r['tipo'],
              'valor': r['valor'],
            };
      final web = k['r'] as Map<String, dynamic>?;
      final igual =
          (web == null && app == null) ||
          (web != null &&
              app != null &&
              web['error'] == app['error'] &&
              web['articulo'] == app['articulo'] &&
              web['tipo'] == app['tipo'] &&
              web['valor'] == app['valor'] &&
              ((web['cantidad'] as num?) ?? 0) ==
                  ((app['cantidad'] as num?) ?? 0));
      if (!igual) malos.add('caso $i ${k['codigo']}: web=$web app=$app');
    }
    // ignore: avoid_print
    print('${casos.length} casos, ${malos.length} con diferencias');
    expect(malos, isEmpty, reason: malos.take(6).join('\n'));
  }, skip: f.existsSync() ? false : 'falta test/ab_romana.json');
}
