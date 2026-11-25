// #3957 — CF-006 desde la app: la ruta propia de FactuSuper (solo la estación del cajero), listas como EF_LISTAS,
// valores iniciales como combo()/numero() de estacion_form.js, avisos «ya no está en la lista», validación y errores.
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/estacion_config.dart';
import 'package:factusuper/datos/almacen.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> respuestaGet({bool guardar = true}) => {
  'success': true,
  'id': 7,
  'data': {
    'EstacionNombre': 'CAJA 3',
    'BodegaCodigo': '1',
    'Caja': '2',
    'TipoPrecio': '9',
    'ImpContadoNum': '301',
    'ImpContadoFormato': 'fipvivi001',
    'ImpContadoAnchoPapel': 48,
    'ImpContadoRuta': 2,
    'ImpCreditoNum': null,
    'ImpCotizaFormato': 'FIPVIVI007',
    'ImpCompNum': '5000',
    'usuarios': [
      {'cod': '00006', 'nom': 'Ana'},
    ],
  },
  'permisos': {'guardar': guardar},
  'listas': {
    'bodegas': [
      {'cod': '1', 'nom': 'Principal'},
    ],
    'cajas': [
      {'cod': '1', 'nom': 'Caja 1'},
      {'cod': '2', 'nom': 'Caja 2'},
    ],
    'precios': [
      {'cod': '1', 'nom': 'P1'},
      {'cod': '2', 'nom': 'P2'},
    ],
    'anchos': [
      {'cod': '40', 'nom': '40'},
      {'cod': '48', 'nom': '48'},
    ],
    'formatos': [
      {
        'codigo': 'FIPVIVI002',
        'grupo': 'Punto de venta',
        'nombre': 'Tiquete completo',
        'soloCotizacion': false,
      },
      {
        'codigo': 'FIPVIVI001',
        'grupo': 'Punto de venta',
        'nombre': 'Tiquete sencillo',
        'soloCotizacion': false,
      },
      {
        'codigo': 'FIPVIVI007',
        'grupo': 'Punto de venta',
        'nombre': 'Cotización',
        'soloCotizacion': true,
      },
    ],
  },
};

void main() {
  late HttpServer srv;
  final pedidos = <Map<String, dynamic>>[];
  var negar = false;
  setUp(() async {
    pedidos.clear();
    negar = false;
    srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    srv.listen((r) async {
      final cuerpo = await utf8.decoder.bind(r).join();
      pedidos.add({
        'metodo': r.method,
        'ruta': r.uri.path,
        'cajero': r.headers.value('x-fs-cajero'),
        if (cuerpo.isNotEmpty) 'cuerpo': jsonDecode(cuerpo),
      });
      if (negar && r.method == 'POST') {
        r.response.statusCode = 403;
        r.response.write(
          jsonEncode({
            'success': false,
            'message': 'Sin permiso para cambiar la configuración de esta estación (130, o 840 para la propia).',
            'mensaje': 'Sin permiso para cambiar la configuración de esta estación (130, o 840 para la propia).',
          }),
        );
      } else {
        r.response.write(
          jsonEncode(
            r.method == 'GET'
                ? respuestaGet()
                : {
                    'success': true,
                    'message': 'Configuración guardada',
                    'config': {'Caja': '1'},
                  },
          ),
        );
      }
      await r.response.close();
    });
  });
  tearDown(() => srv.close(force: true));

  EstacionConfig ec([List<String>? s]) => EstacionConfig(
    ConfigCaja(
      llave: 'fs1.${'a' * 64}',
      empresa: 'demoferre',
      empresaNombre: 'Demo',
      guardada: DateTime(2026),
    ),
    '00006',
    servidores: s ?? ['http://127.0.0.1:${srv.port}'],
  );

  test(
    'cargar: ruta propia, cajero, listas y valores iniciales como la web',
    () async {
      final (d, e) = await ec().cargar();
      expect(e, '');
      expect(
        pedidos.single['ruta'],
        '/apis/shared/venta/factusuper/estacion_config.php',
      );
      expect(pedidos.single['cajero'], '00006');
      expect(d!.id, 7);
      expect(d.puedeGuardar, true);
      expect(d.usuarios.single['nom'], 'Ana');
      expect(d.opciones('ImpContadoFormato').map((o) => o.cod), [
        'FIPVIVI002',
        'FIPVIVI001',
      ], reason: 'el 007 es solo de cotizaciones');
      expect(d.opciones('ImpCotizaFormato').length, 3);
      expect(d.opciones('ImpCreditoAncho').length, 2);
      expect(
        DatosEstacion.valorInicial('ImpContadoFormato', 'fipvivi001'),
        'FIPVIVI001',
      );
      expect(
        DatosEstacion.valorInicial('ImpCreditoFormato', null),
        'FIPVIVI002',
      );
      expect(DatosEstacion.valorInicial('ImpCreditoNum', null), '301');
      expect(DatosEstacion.valorInicial('ImpCompNum', '5000'), '301');
      expect(
        DatosEstacion.valorInicial('ImpCompAncho', null, anchoDef: 40),
        '40',
      );
      expect(DatosEstacion.valorInicial('ImpContadoRuta', 2), '2');
      expect(DatosEstacion.valorInicial('ImpCreditoRuta', 1), '4');
      expect(
        d.avisoFuera('TipoPrecio', '9', 'El precio'),
        contains(
          'El precio que tenía (9) ya no está en la lista. Al guardar quedará como P1',
        ),
      );
      expect(d.avisoFuera('Caja', '2', 'La caja'), isNull);
    },
  );

  test('guardar: valida antes, manda JSON y devuelve la config; 403 con su motivo; sin red', () async {
    final base = {
      'BodegaCodigo': '1',
      'Caja': '1',
      'TipoPrecio': '1',
      for (final i in impresorasEstacion) i.num: '301',
    };
    expect(
      (await ec().guardar({...base, 'ImpCotizaNum': '0'})).$1,
      'Cotización: el número de impresora va de 1 a 999.',
    );
    expect((await ec().guardar({...base, 'Caja': ''})).$1, 'Elija la caja.');
    expect(pedidos, isEmpty, reason: 'lo que no pasa la validación no viaja');

    final (e, cfg) = await ec().guardar(base);
    expect(e, '');
    expect(cfg, {'Caja': '1'});
    expect(pedidos.single['metodo'], 'POST');
    expect((pedidos.single['cuerpo'] as Map)['TipoPrecio'], '1');

    negar = true;
    expect((await ec().guardar(base)).$1, contains('130, o 840'));

    final libre = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final p = libre.port;
    await libre.close();
    expect((await ec(['http://127.0.0.1:$p']).cargar()).$2, sinRedEstacion);
  });
}
