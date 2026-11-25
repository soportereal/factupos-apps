// #3957 — A/B de la CAJA: agregar (reglas de FactuDesk) + paquete, contra FSDoc REAL de la web.
// Los casos salen de: node tool/ab_agregar.js <factusuper_documento.js> test/ab_caja.json
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/cajeros.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/documento.dart';
import 'package:flutter_test/flutter_test.dart';

const _volatiles = {
  'transaccionId',
  'cobradoEn',
  'fecha',
  'idProceso',
  'idProcesoSucursal',
  'idProcesoCaja',
};

void comparar(Object? a, Object? b, String ruta, List<String> dif) {
  if (dif.length > 20) return;
  if (a is num && b is num) {
    if ((a - b).abs() > 1e-9) dif.add('$ruta: web=$a app=$b');
  } else if (a is Map && b is Map) {
    for (final k in {...a.keys, ...b.keys}) {
      if (_volatiles.contains(k)) continue;
      if (!a.containsKey(k) || !b.containsKey(k)) {
        dif.add('$ruta.$k: falta en ${a.containsKey(k) ? 'app' : 'web'}');
        continue;
      }
      comparar(a[k], b[k], '$ruta.$k', dif);
    }
  } else if (a is List && b is List) {
    if (a.length != b.length) {
      dif.add('$ruta: largo web=${a.length} app=${b.length}');
      return;
    }
    for (var i = 0; i < a.length; i++) {
      comparar(a[i], b[i], '$ruta[$i]', dif);
    }
  } else if ('$a' != '$b') {
    dif.add('$ruta: web=$a app=$b');
  }
}

void main() {
  final f = File('test/ab_caja.json');
  test(
    'agregar + paquete = los de la web',
    () {
      final escenarios = (jsonDecode(f.readAsStringSync()) as List)
          .cast<Map<String, dynamic>>();
      var malos = 0;
      final ejemplos = <String>[];
      for (var k = 0; k < escenarios.length; k++) {
        final e = escenarios[k];
        final articulos = (e['articulos'] as List).cast<Map<String, dynamic>>();
        final params = (e['params'] as Map).map((k, v) => MapEntry(k, v));
        final datos = DatosCaja.desde(
          articulos: articulos,
          precios: (e['precios'] as List).cast<Map<String, dynamic>>(),
          clientes: (e['clientes'] as List).cast<Map<String, dynamic>>(),
          catalogos: {
            'parametros': [
              for (final p in params.entries)
                {'parametro': p.key, 'valor': p.value},
            ],
            'estacion': [
              {...(e['estacion'] as Map), 'clave': 'actual'},
            ],
            'permisos_usuario': [
              for (final p in (e['permisos'] as List))
                {'usuario': '00006', 'permiso': p},
            ],
            'tipo_cambio': [
              for (final t in (e['tc'] as Map).entries)
                {'moneda': t.key, 'fecha': '2026-11-25', 'venta': t.value},
            ],
            'actividades_empresa': [
              {'codigo': '523101'},
            ],
          },
        );
        final doc = Documento(datos, const Cajero('00006', 'Ana'));
        if (e['cliente'] != null)
          doc.cliente = Map<String, dynamic>.from(e['cliente'] as Map);
        final pasos = <Map<String, dynamic>>[];
        for (final p in (e['pasos'] as List).cast<Map<String, dynamic>>()) {
          final a = articulos.firstWhere((x) => x['codigo'] == p['articulo']);
          final r = doc.agregar(a, '${p['cantidad']}');
          pasos.add({
            'articulo': p['articulo'],
            'cantidad': p['cantidad'],
            'ok': r.ok,
            'motivo': r.motivo,
            'avisos': r.avisos,
          });
        }
        final barra = <Map<String, dynamic>>[];
        for (final b
            in (e['barra'] as List? ?? const []).cast<Map<String, dynamic>>()) {
          final i = (b['i'] as num).toInt();
          if (b['tipo'] == 'nivel') {
            final (ok, motivo, avisos) = doc.cambiarNivel(
              i,
              (b['nivel'] as num).toInt(),
            );
            barra.add({...b, 'ok': ok, 'motivo': motivo, 'avisos': avisos});
          } else {
            doc.cambiarTarifa(
              i,
              '${b['codigo']}',
              (b['porcentaje'] as num).toDouble(),
            );
            barra.add(b);
          }
        }
        doc.medioPago = '${e['medio']}';
        for (final l in doc.lineas) {
          doc.agregarRecalculo(l);
        }
        final credito = e['tipoPago'] == 'credito';
        final pq = doc.paquete(
          pagos: credito
              ? []
              : [
                  {
                    'medio': e['medio'],
                    'cuenta': '',
                    'monto': doc.totales.total,
                    'comprobante': '',
                  },
                ],
          vuelto: 0,
          transaccionId: 'x',
          cuando: DateTime(2026, 11, 25, 10, 0, 0),
          tipoPago: '${e['tipoPago'] ?? 'contado'}',
          diasCredito: ((e['diasCredito'] as num?) ?? 0).toInt(),
        );
        final dif = <String>[];
        comparar(e['pasos'], pasos, 'pasos', dif);
        comparar(e['barra'] ?? const [], barra, 'barra', dif);
        comparar(e['escala'], doc.escalaDescuentos(), 'escala', dif);
        comparar(e['paquete'], jsonDecode(jsonEncode(pq)), 'paquete', dif);
        if (dif.isNotEmpty) {
          malos++;
          if (ejemplos.length < 6)
            ejemplos.add('escenario $k:\n  ${dif.take(6).join('\n  ')}');
        }
      }
      // ignore: avoid_print
      print('${escenarios.length} escenarios, $malos con diferencias');
      expect(malos, 0, reason: ejemplos.join('\n'));
    },
    skip: f.existsSync()
        ? false
        : 'falta test/ab_caja.json (node tool/ab_agregar.js …)',
  );
}
