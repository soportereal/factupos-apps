// #3957 — si un dominio (una internet) no contesta, el mismo pedido entra por el otro.
import 'dart:convert';
import 'dart:io';

import 'package:factusuper/datos/conexion.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final llave = 'fs1.${'a' * 64}';
  http.Response ok(http.Request r) =>
      http.Response(jsonEncode({'ok': true, 'empresa': r.url.host}), 200);

  test(
    'el primero caído → entra por el segundo, y la próxima arranca por ahí',
    () async {
      final vistos = <String>[];
      final c = MockClient((r) async {
        vistos.add(r.url.host);
        if (r.url.host == 'invefacon.com') throw const SocketException('caído');
        return ok(r);
      });
      final i = await revisarLlave(llave, cliente: c);
      expect(i.empresa, 'invefacon.net');
      expect(vistos, ['invefacon.com', 'invefacon.net']);
      vistos.clear();
      await revisarLlave(llave, cliente: c);
      expect(vistos, ['invefacon.net']);
    },
  );

  test('502 del balanceador también cambia de dominio', () async {
    final c = MockClient(
      (r) async => r.url.host == 'invefacon.net'
          ? http.Response('<html>bad gateway</html>', 502)
          : ok(r),
    );
    expect((await revisarLlave(llave, cliente: c)).empresa, 'invefacon.com');
  });

  test('los dos caídos → sin internet', () async {
    final c = MockClient((r) async => throw const SocketException('caído'));
    await expectLater(
      revisarLlave(llave, cliente: c),
      throwsA(
        isA<ErrorConexion>().having((e) => e.sinInternet, 'sinInternet', true),
      ),
    );
  });

  test('una llave anulada NO cambia de dominio (la respuesta es la misma en los dos)', () async {
    var n = 0;
    final c = MockClient((r) async {
      n++;
      return http.Response(
        jsonEncode({'reason': 'token_invalido', 'mensaje': 'anulada'}),
        401,
      );
    });
    await expectLater(
      revisarLlave(llave, cliente: c),
      throwsA(
        isA<ErrorConexion>().having(
          (e) => e.motivo,
          'motivo',
          'token_invalido',
        ),
      ),
    );
    expect(n, 1);
  });
}
