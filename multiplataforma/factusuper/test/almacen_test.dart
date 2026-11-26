// #3957 — el lector de barras dispara varios guardados seguidos del mismo archivo: no pueden chocar y gana el último.
import 'dart:io';

import 'package:factusuper/datos/almacen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    '100 guardados en paralelo del mismo archivo: sin choque, queda el último',
    () async {
      final d = Directory.systemTemp.createTempSync('fs_alm');
      final a = Almacen(d);
      await Future.wait([
        for (var i = 0; i < 100; i++)
          a.guardarTabla('demo', 'documento', {'n': i}),
      ]);
      expect((await a.leerTabla('demo', 'documento'))['n'], 99);
      d.deleteSync(recursive: true);
    },
  );

  test(
    'recordar usuario y clave: por empresa, se borra al desmarcar',
    () async {
      final d = Directory.systemTemp.createTempSync('fs_rec');
      final a = Almacen(d);
      expect(await a.leerRecordado('demoferre'), isNull);
      await a.guardarRecordado('demoferre', '00006', 'clave123');
      expect(await a.leerRecordado('demoferre'), ('00006', 'clave123'));
      expect(await a.leerRecordado('otra'), isNull);
      await a.borrarRecordado('demoferre');
      expect(await a.leerRecordado('demoferre'), isNull);
      d.deleteSync(recursive: true);
    },
  );
}
