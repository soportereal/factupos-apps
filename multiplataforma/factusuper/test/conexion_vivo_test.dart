// Prueba contra el servidor real (#3957). Solo corre con FS_PRUEBA_VIVO=1; la llave buena viene por variable de entorno
// (FS_LLAVE / FS_USUARIO), nunca escrita en el repo. Pruebas SIEMPRE con la llave de demoferre.
import 'dart:io';

import 'package:factusuper/datos/conexion.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final vivo = Platform.environment['FS_PRUEBA_VIVO'] == '1';
  test('una llave falsa se rechaza con un mensaje claro', () async {
    await expectLater(
      revisarLlave('fs1.${'0' * 64}'),
      throwsA(
        isA<ErrorConexion>().having((e) => e.sinInternet, 'sinInternet', false),
      ),
    );
  }, skip: vivo ? false : 'FS_PRUEBA_VIVO=1');
  test('formato malo no sale a la red', () async {
    await expectLater(revisarLlave('hola'), throwsA(isA<ErrorConexion>()));
  });
  final llave = Platform.environment['FS_LLAVE'] ?? '';
  test('la llave buena dice a qué empresa conecta', () async {
    final i = await revisarLlave(llave);
    stdout.writeln(
      '→ ${i.empresa} · ${i.empresaNombre} · estación ${i.estacionId} ${i.estacionNombre} · ${i.cajeroCodigo} ${i.cajeroNombre}',
    );
    expect(i.empresa, 'demoferre');
  }, skip: vivo && llave.isNotEmpty ? false : 'FS_LLAVE');
}
