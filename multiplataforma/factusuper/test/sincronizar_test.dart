// #3957 — sincronización con un servidor de mentira: mismas decisiones que FSLocal.sincronizarSiHaceFalta de la web.
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/datos/almacen.dart';
import 'package:factusuper/datos/conexion.dart';
import 'package:factusuper/datos/descarga.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class Servidor {
  Map<String, String> firmas = {
    'articulos': 'a1',
    'precios': 'p1',
    'clientes': 'c1',
    'catalogos': 'k1',
  };
  String hora = '2026-11-25 10:00:00';
  List<Map<String, dynamic>> articulos = [
    for (var i = 0; i < 5; i++) {'codigo': 'A$i', 'nombre': 'Art $i'},
  ];
  List<Map<String, dynamic>> precios = [
    for (var i = 0; i < 5; i++)
      {'articulo': 'A$i', 'numero': 1, 'precio': 100.0 + i},
  ];
  List<Map<String, dynamic>> clientes = [
    {'codigo': 'C1', 'nombre': 'Juan'},
  ];
  Map<String, dynamic>? cambios; // lo que contesta cambios_descargar
  final pedidos = <String>[];

  http.Client cliente() => MockClient((r) async {
    final n = r.url.pathSegments.last;
    pedidos.add(n);
    Object j;
    switch (n) {
      case 'firmas_obtener.php':
        j = {'success': true, 'firmas': firmas, 'hora': hora};
      case 'catalogos_descargar.php':
        j = {
          'success': true,
          'tablas': {'parametros': []},
        };
      case 'articulos_descargar.php':
        j = {'success': true, 'total': articulos.length, 'filas': articulos};
      case 'precios_descargar.php':
        j = {'success': true, 'total': precios.length, 'filas': precios};
      case 'clientes_descargar.php':
        j = {'success': true, 'total': clientes.length, 'filas': clientes};
      case 'cambios_descargar.php':
        j = {'success': true, ...?cambios};
      default:
        return http.Response('{}', 404);
    }
    return http.Response(
      jsonEncode(j),
      200,
      headers: {'content-type': 'application/json'},
    );
  });
}

void main() {
  late Directory dir;
  late Almacen alm;
  late Servidor srv;
  Descarga d() => Descarga(
    Conexion(llave: 'fs1.${'a' * 64}', cajero: '00001', cliente: srv.cliente()),
    alm,
    'demo',
  );

  setUp(() {
    dir = Directory.systemTemp.createTempSync('fs_sync');
    alm = Almacen(dir);
    srv = Servidor();
  });
  tearDown(() => dir.deleteSync(recursive: true));

  test('firmas iguales → al día, no baja nada', () async {
    await d().todo();
    srv.pedidos.clear();
    final r = await d().sincronizarSiHaceFalta();
    expect(r.estado, 'al_dia');
    expect(srv.pedidos, ['firmas_obtener.php']);
  });

  test('un precio cambió → SOLO los cambios, y quedan aplicados', () async {
    await d().todo();
    srv.firmas = {...srv.firmas, 'precios': 'p2'};
    srv.cambios = {
      'articulos': [
        {'codigo': 'A2', 'nombre': 'Art 2'},
      ],
      'precios': [
        {'articulo': 'A2', 'numero': 1, 'precio': 999.0},
      ],
      'bajas': [],
      'totales': {'articulos': 5, 'precios': 5},
      'clientes': null,
    };
    srv.pedidos.clear();
    final r = await d().sincronizarSiHaceFalta(soloCambios: true);
    expect(r.estado, 'actualizado');
    expect(r.cambios!['codigos'], ['A2']);
    expect(srv.pedidos, ['firmas_obtener.php', 'cambios_descargar.php']);
    final pres = (await alm.leerTabla('demo', 'precios') as List).cast<Map>();
    expect(pres.firstWhere((p) => p['articulo'] == 'A2')['precio'], 999.0);
    expect(pres.length, 5);
    // y la firma quedó: la próxima vez está al día
    expect(
      (await d().sincronizarSiHaceFalta(soloCambios: true)).estado,
      'al_dia',
    );
  });

  test(
    'los totales no cuadran → no confía en el delta y baja entero',
    () async {
      await d().todo();
      srv.firmas = {...srv.firmas, 'articulos': 'a2', 'precios': 'p2'};
      srv.articulos = [
        ...srv.articulos,
        {'codigo': 'A9', 'nombre': 'Nuevo'},
      ];
      srv.precios = [
        ...srv.precios,
        {'articulo': 'A9', 'numero': 1, 'precio': 5.0},
      ];
      srv.cambios = {
        'articulos': [],
        'precios': [],
        'bajas': ['A0'],
        'totales': {'articulos': 6, 'precios': 6},
        'clientes': null,
      };
      srv.pedidos.clear();
      final r = await d().sincronizarSiHaceFalta();
      expect(r.grupos, containsAll(['articulos', 'precios']));
      expect(
        srv.pedidos,
        containsAll(['articulos_descargar.php', 'precios_descargar.php']),
      );
      expect((await alm.leerTabla('demo', 'articulos') as List).length, 6);
    },
  );

  test(
    'la completa tiene más de 24 h → baja entero (red de seguridad)',
    () async {
      await d().todo();
      final est = Map<String, dynamic>.from(
        await alm.leerTabla('demo', 'sincronizacion') as Map,
      );
      est['sync_completa'] = DateTime.now()
          .subtract(const Duration(hours: 25))
          .toIso8601String();
      await alm.guardarTabla('demo', 'sincronizacion', est);
      srv.firmas = {...srv.firmas, 'precios': 'p3'};
      srv.pedidos.clear();
      await d().sincronizarSiHaceFalta();
      expect(srv.pedidos, isNot(contains('cambios_descargar.php')));
      expect(srv.pedidos, contains('precios_descargar.php'));
    },
  );

  test('sin internet → sin_conexion, la copia queda', () async {
    await d().todo();
    final caido = Descarga(
      Conexion(
        llave: 'fs1.${'a' * 64}',
        cajero: '00001',
        cliente: MockClient((_) async => throw const SocketException('x')),
      ),
      alm,
      'demo',
    );
    expect((await caido.sincronizarSiHaceFalta()).estado, 'sin_conexion');
    expect((await alm.leerTabla('demo', 'articulos') as List).length, 5);
  });
}
