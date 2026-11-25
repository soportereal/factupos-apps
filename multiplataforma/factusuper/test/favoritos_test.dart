// #3957 — favoritos (MV-118): ranking del servidor + los del cajero en el equipo; uno en las dos sale una vez con ★,
// los dados de baja no salen, el precio va con IVA, y sin red se queda lo guardado.
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/cajeros.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/documento.dart';
import 'package:factusuper/caja/favoritos.dart';
import 'package:factusuper/datos/almacen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late HttpServer srv;
  late Directory tmp;
  setUp(() async {
    tmp = await Directory.systemTemp.createTemp('fs_fav');
    srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    srv.listen((r) async {
      expect(r.uri.path, '/apis/shared/venta/factusuper/favoritos_obtener.php');
      r.response
        ..headers.contentType = ContentType.json
        ..write(
          jsonEncode({
            'success': true,
            'dias': 30,
            'maximo': 20,
            'mas_vendidos': [
              {'codigo': 'B', 'veces': 9, 'unidades': 20},
              {'codigo': 'BAJA', 'veces': 8, 'unidades': 1},
              {'codigo': 'A', 'veces': 5, 'unidades': 7},
            ],
          }),
        );
      await r.response.close();
    });
  });
  tearDown(() async {
    await srv.close(force: true);
    await tmp.delete(recursive: true);
  });

  Map<String, dynamic> art(String c, String n) => {
    'codigo': c,
    'nombre': n,
    'tarifa_iva': 13,
    'codigo_tarifa_iva': '08',
    'cabys': '2399999000000',
    'cabys_ok': 1,
    'naturaleza': '1',
  };
  DatosCaja datos() => DatosCaja.desde(
    articulos: [art('A', 'Arroz'), art('B', 'Banano'), art('C', 'Culantro')],
    precios: [
      {'articulo': 'A', 'numero': 1, 'precio': 1000, 'moneda': 'CRC'},
      {'articulo': 'B', 'numero': 1, 'precio': 100, 'moneda': 'CRC'},
    ],
    catalogos: {
      'estacion': [
        {'clave': 'actual', 'id': 1},
      ],
    },
  );
  ConfigCaja cfg() => ConfigCaja(
    llave: 'fs1.${'a' * 64}',
    empresa: 'demoferre',
    empresaNombre: 'Demo',
    guardada: DateTime(2026),
  );

  test('ranking + los del cajero, una vez cada uno', () async {
    final d = datos();
    final f = Favoritos(
      Almacen(tmp),
      cfg(),
      d,
      servidores: ['http://127.0.0.1:${srv.port}'],
    );
    final doc = Documento(d, const Cajero('00006', 'Ana'));
    expect(await f.refrescar('00006'), true);
    expect(
      await f.refrescar('00006'),
      false,
      reason: 'como mucho cada 10 minutos',
    );
    await f.guardarDelCajero('00006', ['C', 'A', 'C', ' ']);
    expect(await f.delCajero('00006'), ['C', 'A']);
    expect(await f.delCajero('00007'), isEmpty, reason: 'son por usuario');

    final filas = Favoritos.ordenar(await f.armar(doc), 'origen', 1);
    expect(filas.map((x) => x.codigo), ['B', 'A', 'C']);
    expect(
      filas[1].sistema && filas[1].mio,
      true,
      reason: 'A está en las dos: una vez, con ★',
    );
    expect(filas[0].precio, 113.0);
    expect(filas[2].sinPrecio, true);
    expect(Favoritos.ordenar(filas, 'precio', -1).first.codigo, 'A');
  });

  test('sin red: se queda con lo guardado', () async {
    final d = datos();
    final libre = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final p = libre.port;
    await libre.close();
    final f = Favoritos(
      Almacen(tmp),
      cfg(),
      d,
      servidores: ['http://127.0.0.1:$p'],
    );
    expect(await f.refrescar('6'), false);
    expect((await f.masVendidos())['lista'], isEmpty);
  });
}
