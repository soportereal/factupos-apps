// #3957 — fondo de caja (MV-112): el cuerpo pasa las MISMAS validaciones de fondo_procesar.php, en tiempo real,
// sin red no se guarda nada, rutas 2/3 imprimen el comprobante en el equipo y queda en el registro (MV-113).
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/cajon.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/fondo.dart';
import 'package:factusuper/caja/registro.dart';
import 'package:factusuper/datos/almacen.dart';
import 'package:flutter_test/flutter_test.dart';

// Las reglas de factusuper_fondo_procesar() (PHP), copiadas tal cual.
final idPhp = RegExp(r'^F-\d{2}-\d{3}-\d{5}-\d{6}-\d{2}$');
final fechaPhp = RegExp(r'^(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}');

void main() {
  late HttpServer api, print;
  late Directory tmp;
  final recibidos = <Map<String, dynamic>>[],
      impresos = <Map<String, dynamic>>[];
  var ruta = 4;
  setUp(() async {
    recibidos.clear();
    impresos.clear();
    tmp = await Directory.systemTemp.createTemp('fs_fondo');
    api = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    api.listen((r) async {
      final b =
          jsonDecode(await utf8.decoder.bind(r).join()) as Map<String, dynamic>;
      recibidos.add({
        ...b,
        '_cajero': r.headers.value('x-fs-cajero'),
        '_ruta': r.uri.path,
      });
      final ok =
          idPhp.hasMatch('${b['fondoId']}') &&
          fechaPhp.hasMatch('${b['fecha']}');
      r.response
        ..headers.contentType = ContentType.json
        ..write(
          jsonEncode(
            ok
                ? {
                    'estado': 'procesado',
                    'documento': '125',
                    'asiento': 9,
                    'impresion': ruta == 4
                        ? {'ok': true, 'ruta': 4}
                        : {'ok': true, 'ruta': ruta, 'tiquete': 'COMPROBANTE'},
                  }
                : {'estado': 'rechazado', 'mensaje': 'formato'},
          ),
        );
      await r.response.close();
    });
    print = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    puertoPrint = 'http://127.0.0.1:${print.port}';
    print.listen((r) async {
      impresos.add(
        jsonDecode(await utf8.decoder.bind(r).join()) as Map<String, dynamic>,
      );
      r.response
        ..headers.contentType = ContentType.json
        ..write('{"ok":true}');
      await r.response.close();
    });
  });
  tearDown(() async {
    await api.close(force: true);
    await print.close(force: true);
    await tmp.delete(recursive: true);
  });

  DatosCaja datos({bool sin243 = false}) => DatosCaja.desde(
    articulos: const [],
    precios: const [],
    catalogos: {
      'parametros': [
        {'parametro': 83, 'valor': '110101'},
        if (!sin243) {'parametro': 243, 'valor': '110102'},
      ],
      'estacion': [
        {
          'clave': 'actual',
          'id': 7,
          'caja': '3',
          'oficina': '002',
          'impresion': {
            'contado': {'ruta': 4, 'impresora': '305'},
            'comprobante': {'ruta': 3, 'impresora': '310', 'ancho': 48},
          },
        },
      ],
      'id_proceso': [
        {'clave': 'actual', 'sucursal': '1', 'caja': '9'},
      ],
    },
  );
  ConfigCaja cfg() => ConfigCaja(
    llave: 'fs1.${'a' * 64}',
    empresa: 'demoferre',
    empresaNombre: 'Demo',
    guardada: DateTime(2026),
  );

  test(
    'ingreso: el cuerpo pasa las reglas del servidor y queda en el registro',
    () async {
      ruta = 4;
      final reg = Registro(Almacen(tmp), 'demoferre');
      final f = Fondos(
        cfg(),
        datos(),
        registro: reg,
        servidores: ['http://127.0.0.1:${api.port}'],
      );
      final r = await f.registrar(
        'FCA',
        15000.555,
        '  Ingreso   fondo  ',
        '00006',
        cuando: DateTime(2026, 11, 25, 7, 4, 9),
      );
      expect(r.ok, true, reason: r.mensaje);
      expect(r.documento, '125');
      final b = recibidos.single;
      expect(b['_ruta'], '/apis/shared/venta/factusuper/fondo_procesar.php');
      expect(b['_cajero'], '00006');
      expect(b['fondoId'], 'F-03-001-00006-070409-25');
      expect(b['tipo'], 'FCA');
      expect(b['monto'], 15000.56);
      expect(b['detalle'], 'Ingreso fondo');
      expect(b['oficina'], '002');
      expect(b['cajon'], '305');
      expect(b['impresion'], {'impresora': '310', 'ruta': 3, 'ancho': 48});
      expect(impresos, isEmpty);
      final l = await reg.lista();
      expect(l.single['idProceso'], 'F-03-001-00006-070409-25');
      expect(l.single['resultado'], 'FCA #125');
    },
  );

  test('rutas 2/3: el comprobante que devuelve el servidor sale por FactuPOS Print', () async {
    ruta = 3;
    final f = Fondos(
      cfg(),
      datos(),
      servidores: ['http://127.0.0.1:${api.port}'],
    );
    final r = await f.registrar('SCA', 500, 'Retiro', '6');
    expect(r.ok, true);
    expect(impresos.single['queue'], '310');
    expect(
      utf8.decode(base64Decode('${impresos.single['data']}')),
      'COMPROBANTE',
    );
  });

  test('validaciones de la web antes de mandar', () async {
    final f = Fondos(
      cfg(),
      datos(),
      servidores: ['http://127.0.0.1:${api.port}'],
    );
    expect(
      (await f.registrar('FCA', 0, 'x x', '6')).mensaje,
      'Ingrese el monto',
    );
    expect(
      (await f.registrar('FCA', 10, ' ', '6')).mensaje,
      'Ingrese el detalle',
    );
    final g = Fondos(
      cfg(),
      datos(sin243: true),
      servidores: ['http://127.0.0.1:${api.port}'],
    );
    expect(
      (await g.registrar('SCA', 10, 'Retiro', '6')).mensaje,
      'Parámetro 243 (cuenta fondo de caja) no configurado',
    );
    expect(recibidos, isEmpty);
  });

  test('sin red: no se guarda nada y avisa que necesita conexión', () async {
    final libre = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final puerto = libre.port;
    await libre.close();
    final reg = Registro(Almacen(tmp), 'demoferre');
    final f = Fondos(
      cfg(),
      datos(),
      registro: reg,
      servidores: ['http://127.0.0.1:$puerto'],
    );
    final r = await f.registrar('FCA', 100, 'Ingreso', '6');
    expect(r.ok, false);
    expect(r.mensaje, sinRedFondo);
    expect(await reg.lista(), isEmpty);
  });
}
