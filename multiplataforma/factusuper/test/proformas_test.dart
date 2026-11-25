// #3957 — proformas de la estación (MV-114): solo en el equipo, permiso 104, se actualiza la misma al volver a guardar,
// la seña del cliente de contado, sufijo si dos caen en el mismo segundo, y el papel de cotización por FactuPOS Print.
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/cajeros.dart';
import 'package:factusuper/caja/cajon.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/documento.dart';
import 'package:factusuper/caja/proformas.dart';
import 'package:factusuper/datos/almacen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late HttpServer srv;
  late Directory tmp;
  final trabajos = <Map<String, dynamic>>[];
  setUp(() async {
    trabajos.clear();
    tmp = await Directory.systemTemp.createTemp('fs_prof');
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
  tearDown(() async {
    await srv.close(force: true);
    await tmp.delete(recursive: true);
  });

  DatosCaja datos({bool con104 = true}) => DatosCaja.desde(
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
          'caja': '3',
          'impresion': {
            'contado': {'ruta': 4, 'impresora': '301', 'ancho': 40},
            'cotiza': {'ruta': 4, 'impresora': '320', 'ancho': 40},
          },
        },
      ],
      'parametros': [
        {'parametro': 62, 'valor': 'Súper Demo'},
      ],
      'usuarios': [
        {'usuario': '00006', 'nombre': 'Ana'},
      ],
      'permisos_usuario': [
        if (con104) {'usuario': '00006', 'permiso': '104'},
      ],
    },
  );

  test('guardar, retomar, actualizar la misma y quitar', () async {
    final d = datos();
    final p = Proformas(Almacen(tmp), 'demoferre', d);
    final doc = Documento(d, const Cajero('00006', 'Ana'))
      ..agregar(d.articuloExacto('P1')!, '2')
      ..notas = 'entregar mañana';
    expect(await p.pideEtiqueta(doc), true);
    final cuando = DateTime(2026, 11, 25, 10, 20, 30);
    final r = await p.guardar(
      doc,
      etiqueta: 'señora blusa roja',
      cuando: cuando,
    );
    expect(r.ok, true);
    expect(r.id, 'P-03-001-00006-102030-25');
    expect(doc.lineas, isEmpty, reason: 'la pantalla queda limpia');

    // Otra en el MISMO segundo: sufijo (si no, al facturar una se borraban las dos).
    doc.agregar(d.articuloExacto('P1')!, '1');
    final r2 = await p.guardar(doc, etiqueta: 'don Luis', cuando: cuando);
    expect(r2.id, 'P-03-001-00006-102030-25-2');

    final pf = await p.abrir(r.id, doc);
    expect(pf, isNotNull);
    expect(doc.lineas.single.cantidad, 2);
    expect(doc.notas, 'entregar mañana');
    expect(doc.proformaOrigen, r.id);
    expect(await p.pideEtiqueta(doc), false, reason: 'ya tiene seña');

    doc.agregar(d.articuloExacto('P1')!, '1');
    final r3 = await p.guardar(doc);
    expect(r3.actualizada, true);
    expect(r3.id, r.id);
    final l = await p.lista();
    expect(l.length, 2);
    final misma = l.firstWhere((x) => x['id'] == r.id);
    expect(misma['lineas'], 1, reason: 'el mismo artículo suma en la misma línea');
    expect(misma['total'], greaterThan(3000));
    expect(misma['etiqueta'], 'señora blusa roja');
    expect((misma['doc'] as Map).containsKey('proformaOrigen'), false);

    await p.quitar(r.id);
    expect((await p.lista()).single['id'], r2.id);
  });

  test('sin permiso 104 no se guarda', () async {
    final d = datos(con104: false);
    final p = Proformas(Almacen(tmp), 'demoferre', d);
    final doc = Documento(d, const Cajero('00006', 'Ana'))
      ..agregar(d.articuloExacto('P1')!, '1');
    final r = await p.guardar(doc);
    expect(r.ok, false);
    expect(r.motivo, 'Sin permiso para guardar proformas (104)');
    expect(doc.lineas, isNotEmpty);
  });

  test('papel de cotización: modo proforma, sin valor fiscal, a la impresora de cotizaciones', () async {
    final d = datos();
    final p = Proformas(Almacen(tmp), 'demoferre', d);
    final doc = Documento(d, const Cajero('00006', 'Ana'))
      ..agregar(d.articuloExacto('P1')!, '3');
    final pq = doc.paquete(
      pagos: const [],
      vuelto: 0,
      imprimir: false,
      transaccionId: uuidV4(),
      cuando: DateTime.now(),
    );
    final e = await p.imprimirCotizacion(pq, 'P-03-001-00006-102030-25');
    expect(e, '');
    expect(trabajos.single['queue'], '320');
    final t = latin1.decode(base64Decode('${trabajos.single['data']}'));
    expect(t, contains('DOCUMENTO SIN VALOR FISCAL'));
    expect(t, contains('P-03-001-00006-102030-25'));
    expect(t, isNot(contains('{{COPIA_ETIQUETA}}')));
  });
}
