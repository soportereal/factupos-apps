// #3957 — clientes MV-110 sin internet: validaciones de la web, permisos 311/313, alta con código provisional N-…
// (el formato que acepta factusuper_cliente_crear), solo lo que cambió, subida en orden y el código real en todo el equipo.
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/clientes.dart';
import 'package:factusuper/caja/cola.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/registro.dart';
import 'package:factusuper/datos/almacen.dart';
import 'package:flutter_test/flutter_test.dart';

final altaPhp = RegExp(r'^N-\d{2}-\d{3}-\d{5}-\d{6}-\d{2}$');

void main() {
  late HttpServer srv;
  late Directory tmp;
  final pedidos = <Map<String, dynamic>>[];
  var rechazarEdicion = false;
  setUp(() async {
    pedidos.clear();
    rechazarEdicion = false;
    tmp = await Directory.systemTemp.createTemp('fs_cli');
    srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    srv.listen((r) async {
      final b =
          jsonDecode(await utf8.decoder.bind(r).join()) as Map<String, dynamic>;
      pedidos.add({
        ...b,
        '_ruta': r.uri.path,
        '_cajero': r.headers.value('x-fs-cajero'),
      });
      Map<String, dynamic> resp;
      if (r.uri.path.endsWith('cliente_guardar.php')) {
        if (b['nuevo'] == true) {
          resp = altaPhp.hasMatch('${b['idProceso']}')
              ? {'estado': 'guardado', 'codigo': '00777'}
              : {
                  'estado': 'rechazado',
                  'mensaje': 'El alta no trae un ID válido',
                };
        } else {
          resp = rechazarEdicion
              ? {'estado': 'rechazado', 'mensaje': 'El correo no es válido'}
              : {'estado': 'guardado'};
        }
      } else {
        resp = {
          'estado': 'procesada',
          'factura': {'numero': '1'},
        };
      }
      r.response
        ..headers.contentType = ContentType.json
        ..write(jsonEncode(resp));
      await r.response.close();
    });
  });
  tearDown(() async {
    await srv.close(force: true);
    await tmp.delete(recursive: true);
  });

  DatosCaja datos({
    bool fe = true,
    List<String> permisos = const ['311', '313'],
  }) => DatosCaja.desde(
    articulos: const [],
    precios: const [],
    clientes: [
      {
        'codigo': '00010',
        'nombre': 'ANA MORA',
          'comercial': 'ANA MORA',
        'cedula': '1-0111-0222',
        'tipo_precio': 1,
        'descuento': 0,
        'email_factura': 'ana@x.com',
      },
    ],
    catalogos: {
      'parametros': [
        {'parametro': 125, 'valor': fe ? '1' : '0'},
      ],
      'estacion': [
        {'clave': 'actual', 'id': 1, 'caja': '2'},
      ],
      'permisos_usuario': [
        for (final p in permisos) {'usuario': '00006', 'permiso': p},
      ],
    },
  );
  ConfigCaja cfg() => ConfigCaja(
    llave: 'fs1.${'a' * 64}',
    empresa: 'demoferre',
    empresaNombre: 'Demo',
    guardada: DateTime(2026),
  );
  ClientesLocal cl(DatosCaja d) => ClientesLocal(
    Almacen(tmp),
    cfg(),
    d,
    registro: Registro(Almacen(tmp), 'demoferre'),
    servidores: ['http://127.0.0.1:${srv.port}'],
  );

  test('validaciones de la web', () {
    final c = cl(datos());
    final base = {
      'nombre': 'X',
      'cedula': '123',
      'email_factura': 'a@b.co',
      'tipo_precio': '1',
      'actividad': '4711.0',
    };
    String v(Map<String, dynamic> m, {bool nuevo = true}) =>
        c.validar(ClientesLocal.normalizar({...base, ...m}), esNuevo: nuevo);
    expect(v({}), '');
    expect(v({'nombre': ''}), 'El nombre es obligatorio.');
    expect(v({'cedula': ''}), contains('cédula es requerida'));
    expect(v({'email_factura': ''}), contains('correo de facturación'));
    expect(v({'actividad': ''}), contains('actividad económica es requerida'));
    expect(v({'actividad': ''}, nuevo: false), '');
    expect(v({'actividad': '47110'}), contains('formato de Hacienda'));
    expect(
      v({'cedula': '1 23'}),
      'La cédula solo lleva números (sin espacios).',
    );
    expect(
      v({'email_general': 'a@b.co, malo'}),
      'Email General: el correo «malo» no es válido.',
    );
    expect(v({'email_cobro': 'a​@b.co'}), contains('carácter invisible'));
    expect(v({'tipo_precio': '11'}), 'El tipo de precio va de 1 a 10.');
    expect(v({'descuento': '101'}), 'El descuento va de 0 a 100 %.');
    expect(v({'plazo': '1.5'}), 'El plazo son días enteros (0 o más).');
    expect(
      v({'monto_credito': '-1'}),
      'El monto de crédito no puede ser negativo.',
    );
    expect(ClientesLocal.normalizar({'nombre': 'PEPE'})['comercial'], 'PEPE');
  });

  test('alta sin internet → sube, el código real reemplaza al provisional, y la venta esperó su turno', () async {
    final d = datos();
    final c = cl(d);
    final (nuevo, e) = await c.crear(
      {
        'nombre': 'LUIS SOTO',
        'cedula': '2-0333-0444',
        'email_factura': 'l@s.com',
        'tipo_precio': '2',
        'actividad': '4711.0',
      },
      '00006',
      cuando: DateTime(2026, 11, 25, 8, 1, 2),
    );
    expect(e, '');
    expect(nuevo!['codigo'], 'N-02-001-00006-080102-25');
    expect(altaPhp.hasMatch('${nuevo['codigo']}'), true);
    expect(d.cliente('N-02-001-00006-080102-25'), isNotNull);

    final (_, dup) = await c.crear({
      'nombre': 'OTRO',
      'cedula': '203330444',
      'email_factura': 'o@o.com',
      'tipo_precio': '1',
      'actividad': '4711.0',
    }, '00006');
    expect(dup, contains('Ya existe el cliente N-02-001-00006-080102-25'));

    // Una venta de ese cliente: la cola NO la manda mientras el código sea provisional.
    final cola = Cola(Almacen(tmp), 'demoferre', cfg().llave);
    await cola.agregar({
      'transaccionId': 't1',
      'cobradoEn': '2026-11-25T08:02:00Z',
      'total': 100,
      'usuario': '00006',
      'cliente': {'codigo': 'N-02-001-00006-080102-25'},
      'clienteCompleto': {'codigo': 'N-02-001-00006-080102-25'},
      'documento': {'idProceso': '02-001-00006-080200-25'},
      'lineas': [],
    });
    final r0 = await cola.enviar();
    expect(r0.detenida, contains('espera a que el servidor cree su cliente'));

    final r = await c.subir();
    expect(r.guardados, 1);
    expect(r.remapeos, {'N-02-001-00006-080102-25': '00777'});
    expect(pedidos.single['nuevo'], true);
    expect(pedidos.single['_cajero'], '00006');
    expect(d.cliente('00777')!['nombre'], 'LUIS SOTO');
    expect(d.cliente('N-02-001-00006-080102-25'), isNull);
    expect(await c.pendientes(), isEmpty);

    await cola.remapearCliente('N-02-001-00006-080102-25', '00777');
    expect(
      ((cola.pendientes.single['paquete'] as Map)['cliente'] as Map)['codigo'],
      '00777',
    );
  });

  test('edición: solo lo que cambió, se acumula, y rechazada sale de la cola sin frenarla', () async {
    final d = datos();
    final c = cl(d);
    final (sin, _) = await c.editar('00010', {...d.cliente('00010')!}, '00006');
    expect(sin, isNull, reason: 'sin cambios no se encola nada');
    await c.editar('00010', {
      ...d.cliente('00010')!,
      'telefonos': '8888-0000',
    }, '00006');
    await c.editar('00010', {
      ...d.cliente('00010')!,
      'descuento': '5',
    }, '00006');
    final p = (await c.pendientes()).single;
    expect(p['cambios'], {'telefonos': '8888-0000', 'descuento': 5});
    expect('${p['idProceso']}', startsWith('C-02-001-00006-'));
    expect(
      d.cliente('00010')!['telefonos'],
      '8888-0000',
      reason: 'se aplica YA en el equipo',
    );

    rechazarEdicion = true;
    final r = await c.subir();
    expect(r.rechazados.single, contains('El correo no es válido'));
    expect(r.detenida, '');
    expect((await c.pendientes()).single['estado'], 'rechazado');
  });

  test('permisos 311 / 313 y el genérico', () async {
    final d = datos(permisos: const []);
    final c = cl(d);
    expect(
      (await c.crear({'nombre': 'X'}, '00006')).$2,
      'Sin permiso para crear clientes (311)',
    );
    expect(
      (await c.editar('00010', {'nombre': 'X'}, '00006')).$2,
      'Sin permiso para editar clientes (313)',
    );
    expect(
      (await c.editar('SN', {'nombre': 'X'}, '00006')).$2,
      'Elija un cliente (F3) para editarlo',
    );
  });
}
