// #3957 — A/B de la edición de línea: validarLinea() contra FSLinea.validar REAL (node tool/ab_linea.js …).
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/cajeros.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/documento.dart';
import 'package:factusuper/motor/linea.dart';
import 'package:flutter_test/flutter_test.dart';

double _n(Object? v) => (v as num?)?.toDouble() ?? 0;

void main() {
  final f = File('test/ab_linea.json');
  test('validar la línea = la web', () {
    final casos = (jsonDecode(f.readAsStringSync()) as List)
        .cast<Map<String, dynamic>>();
    final malos = <String>[];
    for (var i = 0; i < casos.length; i++) {
      final k = casos[i];
      final datos = DatosCaja.desde(
        articulos: const [],
        precios: const [],
        catalogos: {
          'permisos_usuario': [
            for (final p in (k['permisos'] as List))
              {'usuario': '00006', 'permiso': p},
          ],
        },
      );
      final doc = Documento(datos, const Cajero('00006', 'Ana'));
      final l0 = k['l'] as Map<String, dynamic>,
          c0 = k['c'] as Map<String, dynamic>;
      final l = Linea(
        codigo: 'A',
        cantidad: 1,
        precio: _n(l0['precio']),
        nivel: (l0['nivel'] as num).toInt(),
        descMax: _n(l0['descMax']),
        costo: _n(l0['costo']),
        utilMin: _n(l0['utilMin']),
        nivelBloqueado: l0['nivelBloqueado'] == true,
        descuento: _n(l0['descuento']),
      );
      final c = CambiosLinea(
        cantidad: _n(c0['cantidad']),
        precio: _n(c0['precio']),
        modo: '${c0['modo']}',
        valor: _n(c0['valor']),
        bonificacion: c0['bonificacion'] == true,
        montoConfirmado: c0['montoConfirmado'] == true,
      );
      final r = doc.validarLinea(
        l,
        c,
        (k['auth'] as List).cast<String>().toSet(),
      );
      var dif = r.tipo != k['tipo']
          ? 'tipo web=${k['tipo']} app=${r.tipo}'
          : '';
      final alt = k['alt'] as Map<String, dynamic>?;
      if (dif.isEmpty && alt != null) {
        final a = r.alternativa;
        if (a == null ||
            (a.precio - _n(alt['precio'])).abs() > 1e-9 ||
            a.modo != alt['modo'] ||
            (a.valor - _n(alt['valor'])).abs() > 1e-9) {
          dif =
              'alternativa web=$alt app=${a == null ? null : '${a.precio}/${a.modo}/${a.valor}'}';
        }
      }
      if (dif.isNotEmpty) malos.add('caso $i: $dif');
    }
    // ignore: avoid_print
    print('${casos.length} casos, ${malos.length} con diferencias');
    expect(malos, isEmpty, reason: malos.take(8).join('\n'));
  }, skip: f.existsSync() ? false : 'falta test/ab_linea.json');
}
