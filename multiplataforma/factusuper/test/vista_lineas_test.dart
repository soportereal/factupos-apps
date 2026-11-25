// #3957 — vistas de las líneas (Básica/Simple/Detallada/Full) y letra POR VISTA, como la web; precio y descuento con IVA.
import 'package:factusuper/motor/linea.dart';
import 'package:factusuper/ui/vista_lineas.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('vista válida (completa = detallada, otra cosa = simple)', () {
    expect(vistaValida('full'), 'full');
    expect(vistaValida('completa'), 'detallada');
    expect(vistaValida(null), 'simple');
    expect(vistaValida('rara'), 'simple');
  });

  test('letra por vista: A−/A+ entre 12 y 34, 0 vuelve a la de fábrica', () {
    var m = <String, double>{};
    expect(letraDe('basica', m), 20);
    m = cambiarLetra('basica', m, 1);
    expect(m, {'basica': 21});
    expect(letraDe('simple', m), 15, reason: 'las otras vistas no cambian');
    for (var i = 0; i < 40; i++) {
      m = cambiarLetra('basica', m, 1);
    }
    expect(letraDe('basica', m), 34);
    for (var i = 0; i < 40; i++) {
      m = cambiarLetra('full', m, -1);
    }
    expect(letraDe('full', m), 12);
    m = cambiarLetra('basica', m, 0);
    expect(m.containsKey('basica'), false);
    expect(letrasDesde({'full': 12, 'basica': 99, 'otra': 15, 'simple': 'x'}), {
      'full': 12.0,
    });
  });

  test('precio y descuento con IVA (cuadran con el total)', () {
    final l = Linea(
      codigo: 'A',
      cantidad: 2,
      precio: 1000,
      tarifa: 13,
      descuento: 10,
    );
    calcular(l, const Decimales(), '01');
    expect(precioConIva(l), closeTo(1130, 1e-9));
    expect(descuentoConIva(l), closeTo(226, 1e-9));
    expect(precioConIva(l) * 2 - descuentoConIva(l), closeTo(l.total, 0.01));
  });
}
