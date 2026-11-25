import 'package:factusuper/datos/actualizacion.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('compara versiones como números', () {
    expect(compararVersion('1.0.10', '1.0.9'), 1);
    expect(compararVersion('1.0.1', '1.0.1'), 0);
    expect(compararVersion('1.0.0', '1.0.1'), -1);
    expect(compararVersion('1.1', '1.0.9'), 1);
  });
}
