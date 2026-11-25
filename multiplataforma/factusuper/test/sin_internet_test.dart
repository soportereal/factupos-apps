// #3957 — sin internet: el provisional va DIRECTO a FactuPOS Print de la computadora (servidor de mentira en un puerto libre).
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/cajeros.dart';
import 'package:factusuper/caja/cajon.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/documento.dart';
import 'package:factusuper/impresion/sin_internet.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late HttpServer srv;
  final trabajos = <Map<String, dynamic>>[];
  setUp(() async {
    trabajos.clear();
    srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    puertoPrint = 'http://127.0.0.1:${srv.port}';
    srv.listen((r) async {
      trabajos.add(
        jsonDecode(await utf8.decoder.bind(r).join()) as Map<String, dynamic>,
      );
      r.response
        ..headers.contentType = ContentType.json
        ..write('{"ok":true}');
      await r.response.close();
    });
  });
  tearDown(() => srv.close(force: true));

  DatosCaja datos() => DatosCaja.desde(
    articulos: [
      {
        'codigo': 'P1',
        'nombre': 'Café molido',
        'tarifa_iva': 13,
        'codigo_tarifa_iva': '08',
        'cabys': '2399999000000',
        'cabys_ok': 1,
        'naturaleza': '1',
        'costo': 100,
      },
    ],
    precios: [
      {'articulo': 'P1', 'numero': 1, 'precio': 1000, 'moneda': 'CRC'},
    ],
    catalogos: {
      'estacion': [
        {
          'clave': 'actual',
          'id': 7,
          'nombre': 'CAJA 3',
          'caja': '3',
          'impresion': {
            'contado': {
              'ruta': 4,
              'impresora': '301',
              'formato': 'FIPVIVI002',
              'ancho': 40,
            },
          },
        },
      ],
      'parametros': [
        {'parametro': 62, 'valor': 'Súper Demo'},
        {'parametro': 99, 'valor': '1'},
      ],
      'medios_pago': [
        {'codigo': '01', 'descripcion': 'Efectivo', 'mostrar': 1},
      ],
      'usuarios': [
        {'usuario': '00006', 'nombre': 'Ana'},
      ],
    },
  );

  Map<String, dynamic> venta(DatosCaja d, DateTime cuando) {
    final doc = Documento(d, const Cajero('00006', 'Ana'))
      ..agregar(d.articuloExacto('P1')!, '2');
    final pq = doc.paquete(
      pagos: [
        {'medio': '01', 'monto': 5000.0},
      ],
      vuelto: 2740,
      transaccionId: uuidV4(),
      cuando: cuando,
    );
    return {
      'transaccionId': pq['transaccionId'],
      'idProceso': (pq['documento'] as Map)['idProceso'],
      'estado': 'pendiente',
      'fecha': pq['cobradoEn'],
      'paquete': pq,
    };
  }

  test('provisional directo a FactuPOS Print, con copia, una sola vez, y el servidor no lo reimprime', () async {
    final d = datos();
    final v = venta(d, DateTime.now());
    final r = await imprimirPendientesSinRed([v], d, 'demoferre');
    expect(r.single.$2, true, reason: r.single.$3);
    expect(trabajos.length, 2); // original + 1 copia (param 99)
    final t0 = latin1.decode(base64Decode(trabajos[0]['data'] as String));
    expect(trabajos[0]['queue'], '301');
    expect(trabajos[0]['empresa'], 'demoferre');
    expect(trabajos[0]['jobId'], '${v['idProceso']}-0');
    expect(t0, contains('PROVISIONAL'));
    expect(t0, contains('${v['idProceso']}'));
    expect(t0, contains('ORIGINAL'));
    expect(
      latin1.decode(base64Decode(trabajos[1]['data'] as String)),
      contains('COPIA'),
    );
    expect(v['impreso'], true);
    expect(
      ((v['paquete'] as Map)['impresion'] as Map)['provisional'],
      isNotNull,
    );
    await imprimirPendientesSinRed([v], d, 'demoferre');
    expect(trabajos.length, 2, reason: 'no se reimprime');
  });

  test('una venta de hace más de 15 minutos no saca papel', () async {
    final d = datos();
    final v = venta(d, DateTime.now().subtract(const Duration(minutes: 20)));
    expect(await imprimirPendientesSinRed([v], d, 'demoferre'), isEmpty);
    expect(trabajos, isEmpty);
  });

  test(
    'FactuPOS Print apagado: se anota el error y no se reintenta solo',
    () async {
      final d = datos();
      await srv.close(force: true);
      final v = venta(d, DateTime.now());
      final r = await imprimirPendientesSinRed([v], d, 'demoferre');
      expect(r.single.$2, false);
      expect(r.single.$3, contains('FactuPOS Print no responde'));
      expect(v['impresionLocal'], isNotNull);
      expect(v['impreso'], isNot(true));
    },
  );
}
