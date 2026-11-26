// #3957 FactuMóvil F1b — reglas propias de FactuMóvil sobre la línea (editar.js de la web):
// bodega por línea (033 · param 251), «SI» por línea bajo el costo con 021, y la venta lleva la bodega de cada línea.
import 'package:factusuper/app/sabor.dart';
import 'package:factusuper/caja/cajeros.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/documento.dart';
import 'package:flutter_test/flutter_test.dart';

DatosCaja _datos({List<String> permisos = const [], bool atada = false}) =>
    DatosCaja.desde(
      articulos: [
        {
          'codigo': 'A1',
          'nombre': 'Martillo',
          'tarifa_iva': 13,
          'codigo_tarifa_iva': '08',
          'cabys': '2399999000000',
          'unidad': 'Unid',
          'naturaleza': '1',
          'fraccionable': 0,
          'costo': 1000,
          'moneda': 'CRC',
        },
      ],
      precios: [
        {'articulo': 'A1', 'numero': 1, 'precio': 2000, 'moneda': 'CRC'},
        {'articulo': 'A1', 'numero': 2, 'precio': 1500, 'moneda': 'CRC'},
      ],
      catalogos: {
        'parametros': [
          {'parametro': 251, 'valor': atada ? '1' : '0'},
        ],
        'estacion': [
          {
            'clave': 'actual',
            'bodega': '0',
            'tipo_precio': 1,
            'oficina': '001',
            'caja': '1',
          },
        ],
        'permisos_usuario': [
          for (final p in permisos) {'usuario': '00006', 'permiso': p},
        ],
        'bodegas': [
          {'codigo': '0', 'nombre': 'Principal'},
          {'codigo': '2', 'nombre': 'Ramírez'},
        ],
      },
    );

Documento _doc(DatosCaja d) {
  final doc = Documento(d, const Cajero('00006', 'Ana'));
  expect(doc.agregar(d.articuloExacto('A1')!, '1').ok, isTrue);
  return doc;
}

void main() {
  tearDown(() => sabor = saborFactuSuper);

  group('FactuMóvil', () {
    setUp(() => sabor = saborFactuMovil);

    test('cambiar la bodega de la línea sin 033 pide el permiso', () {
      final doc = _doc(_datos());
      final l = doc.lineas.first;
      final v = doc.validarLinea(
        l,
        CambiosLinea(cantidad: 1, precio: l.precio, bodega: '2'),
        const {},
      );
      expect(v.permiso, '033');
    });

    test('con 033 la línea queda en su bodega y la venta la lleva', () {
      final doc = _doc(_datos(permisos: ['033']));
      final l = doc.lineas.first;
      final c = CambiosLinea(cantidad: 1, precio: l.precio, bodega: '2');
      expect(doc.validarLinea(l, c, const {}).ok, isTrue);
      doc.aplicarLinea(l, c, const {});
      expect(doc.bodegaDe(l), '2');
      final pq = doc.paquete(
        pagos: const [],
        vuelto: 0,
        transaccionId: 't',
        cuando: DateTime(2026, 11, 26),
      );
      expect(
        ((pq['lineas'] ?? (pq['documento'] as Map)['lineas']) as List)
            .first['bodega'],
        '2',
      );
      // Volver a la de la estación la deja «sin bodega propia».
      doc.aplicarLinea(
        l,
        CambiosLinea(cantidad: 1, precio: l.precio, bodega: '0'),
        const {},
      );
      expect(l.bodega, '');
    });

    test('param 251: la bodega está atada a la estación', () {
      final doc = _doc(_datos(permisos: ['033'], atada: true));
      final l = doc.lineas.first;
      final v = doc.validarLinea(
        l,
        CambiosLinea(cantidad: 1, precio: l.precio, bodega: '2'),
        const {},
      );
      expect(v.error, contains('251'));
    });

    test('bajo el costo: sin 021 no se puede, con 021 pide «SI»', () {
      final sin = _doc(_datos(permisos: ['004', '023', '006']));
      final l1 = sin.lineas.first;
      final c = CambiosLinea(cantidad: 1, precio: l1.precio, valor: 60);
      expect(sin.validarLinea(l1, c, const {}).error, contains('021'));

      final con = _doc(_datos(permisos: ['004', '023', '006', '021']));
      final l2 = con.lineas.first;
      final v = con.validarLinea(l2, c, const {});
      expect(v.confirmarSi, isTrue);
      expect(v.confirma, 'costo');
      expect(
        con.validarLinea(l2, c.con(costoConfirmado: true), const {}).ok,
        isTrue,
      );
    });

    test('la lista de bodegas viene ordenada por código', () {
      expect(_datos().bodegas.map((b) => b['codigo']), ['0', '2']);
      expect(_datos().nombreBodega('2'), '2 - Ramírez');
    });
  });

  test(
    'FactuSuper: con 021 TAMBIÉN pide «SI» (dueño, 26-nov: para las dos)',
    () {
      sabor = saborFactuSuper;
      final doc = _doc(_datos(permisos: ['004', '023', '006', '021']));
      final l = doc.lineas.first;
      expect(
        doc
            .validarLinea(
              l,
              CambiosLinea(cantidad: 1, precio: l.precio, valor: 60),
              const {},
            )
            .confirma,
        'costo',
      );
    },
  );
}
