// #3957 — cierre MU-001: el total contado = calcularTotal de contador_monedas.js; con la llave, si el servidor dice
// «token_fuera_de_factusuper», la app lo explica en vez de fallar mudo; el flujo guardar → contabilizar (form).
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/caja/cierre.dart';
import 'package:factusuper/datos/almacen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late HttpServer srv;
  var fuera = false;
  final pedidos = <(String, String, String)>[];
  setUp(() async {
    fuera = false;
    pedidos.clear();
    srv = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    srv.listen((r) async {
      final cuerpo = await utf8.decoder.bind(r).join();
      pedidos.add((r.uri.path, '${r.headers.contentType}', cuerpo));
      r.response.headers.contentType = ContentType.json;
      if (fuera) {
        r.response.statusCode = 403;
        r.response.write(
          jsonEncode({
            'reason': 'token_fuera_de_factusuper',
            'mensaje': 'Ruta no permitida',
          }),
        );
      } else if (r.uri.path.endsWith('cierre_lista_obtener.php')) {
        r.response.write(
          jsonEncode({
            'success': true,
            'cierres': [
              {'Asiento': 4521, 'UsuarioNombre': 'Ana'},
            ],
          }),
        );
      } else if (r.uri.path.endsWith('cierre_resumen_obtener.php')) {
        r.response.write(jsonEncode({'success': true, 'totalCaja': 61500}));
      } else if (r.uri.path.endsWith('cierre_contabilizar.php')) {
        r.response.write(jsonEncode({'success': true, 'impreso': true}));
      } else {
        r.response.write(jsonEncode({'success': true}));
      }
      await r.response.close();
    });
  });
  tearDown(() => srv.close(force: true));
  CierreCaja cc() => CierreCaja(
    ConfigCaja(
      llave: 'fs1.${'a' * 64}',
      empresa: 'demoferre',
      empresaNombre: 'D',
      guardada: DateTime(2026),
    ),
    '00006',
    servidores: ['http://127.0.0.1:${srv.port}'],
  );

  test('total contado como la web', () {
    final c = Conteo()
      ..denominaciones[500] = 3
      ..denominaciones[10000] = 5
      ..tarjeta = 2500
      ..sinpe = 1000
      ..transferencia = 0
      ..gastos = 1000
      ..dolares = 10
      ..tipoCambio = 505.5;
    expect(c.subMonedas, 1500);
    expect(c.subBilletes, 50000);
    expect(c.totalEfectivo, 51500);
    expect(c.total, 51500 + 2500 + 1000 + 1000 + 5055);
    c.tipoCambio = 0;
    expect(
      c.total,
      51500 + 2500 + 1000 + 1000 + 5000,
      reason: 'sin tipo de cambio la web usa 500',
    );
  });

  test(
    'pendiente → contabilizar: guarda el conteo y contabiliza por formulario',
    () async {
      final (p, e) = await cc().pendiente();
      expect(e, '');
      expect(p!.asiento, 4521);
      expect(p.totalCaja, 61500);
      final (ok, e2) = await cc().contabilizar(
        p,
        Conteo()..denominaciones[1000] = 2,
      );
      expect(e2, '');
      expect(ok, 'Contabilizado e impreso ✓');
      final g = pedidos.firstWhere(
        (x) => x.$1.endsWith('cierre_contador_guardar.php'),
      );
      expect((jsonDecode(g.$3) as Map)['cierre'], 4521);
      final c = pedidos.firstWhere(
        (x) => x.$1.endsWith('cierre_contabilizar.php'),
      );
      expect(c.$2, contains('application/x-www-form-urlencoded'));
      expect(c.$3, 'asientos=4521&imprimir=1');
    },
  );

  test('ruta fuera de la llave: se explica', () async {
    fuera = true;
    final (p, e) = await cc().pendiente();
    expect(p, isNull);
    expect(e, sinRutaCierre);
  });
}
