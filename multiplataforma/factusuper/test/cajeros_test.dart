// #3957 — entrada del cajero: usuario + clave validada en el equipo contra el hash de PHP ($2y$).
import 'package:factusuper/caja/cajeros.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const hash = r'$2y$10$bOAuYIxtPueTLF.aUqWdjuKa1oGPD1ooZUy7ktrGWkmAfifYDDViS';
  final c = Cajeros({
    'usuarios': [
      {
        'usuario': '00006',
        'nombre': 'Ana',
        'hash': hash,
        'permisos': <String>[],
      },
      {
        'usuario': '00007',
        'nombre': 'Beto',
        'hash': hash,
        'permisos': <String>[],
      },
      {
        'usuario': '00008',
        'nombre': 'Sin clave',
        'hash': '',
        'permisos': <String>[],
      },
    ],
    'permisos_usuario': [
      {'usuario': '00006', 'permiso': '653'},
      {'usuario': '00008', 'permiso': '653'},
    ],
  });

  test('la lista solo trae a los que tienen clave y permiso 653', () {
    expect(c.conPermiso().map((x) => x.nombre), ['Ana']);
  });
  test('clave buena entra (también sin ceros a la izquierda)', () {
    expect(c.validar('00006', 'clave123'), isNull);
    expect(c.validar('6', 'clave123'), isNull);
  });
  test('clave mala no dice cuál dato falló', () {
    expect(c.validar('00006', 'otra'), 'Usuario o clave incorrectos');
    expect(c.validar('99999', 'clave123'), 'Usuario o clave incorrectos');
  });
  test('sin permiso 653 no entra aunque la clave sea buena', () {
    expect(c.validar('00007', 'clave123'), contains('no tiene permiso'));
  });
}
