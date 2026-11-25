// #3957 — exoneración MV-106: réplica de FSDoc.exoneracionPlan (mapa de CABYS, sin mapa, 0 %, incompleta, tipo 01,
// sin IVA, tope en la tarifa), aplicar recalcula el IVA, quitar lo devuelve, y viaja en el paquete y en la venta guardada.
import 'package:factusuper/caja/cajeros.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/documento.dart';
import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> art(String c, String cabys, num iva) => {
  'codigo': c,
  'nombre': 'Art $c',
  'tarifa_iva': iva,
  'codigo_tarifa_iva': iva == 0 ? '01' : '08',
  'cabys': cabys,
  'cabys_ok': 1,
  'naturaleza': '1',
};

DatosCaja datos({bool conMapa = true}) => DatosCaja.desde(
  articulos: [
    art('A', '1111111111111', 13),
    art('B', '2222222222222', 13),
    art('C', '3333333333333', 0),
    art('D', '', 13),
  ],
  precios: [
    for (final c in ['A', 'B', 'C', 'D'])
      {'articulo': c, 'numero': 1, 'precio': 1000, 'moneda': 'CRC'},
  ],
  clientes: [
    {
      'codigo': '00010',
      'nombre': 'ESCUELA',
      'cedula': '3101123456',
      'tipo_cedula': '02',
    },
  ],
  catalogos: {
    'estacion': [
      {'clave': 'actual', 'id': 1},
    ],
    'exoneraciones': [
      {
        'id': 1,
        'cliente': '00010',
        'documento': 'AL-1',
        'tipo_documento': '04',
        'porcentaje': 13,
        'institucion': 'MEP',
        'vencimiento': '2099-12-31',
      },
      {
        'id': 2,
        'cliente': '00010',
        'documento': 'AL-2',
        'tipo_documento': '01',
        'porcentaje': 20,
        'vencimiento': '2098-01-01',
      },
      {
        'id': 3,
        'cliente': '00010',
        'documento': 'VIEJA',
        'tipo_documento': '04',
        'porcentaje': 5,
        'vencimiento': '2001-01-01',
      },
    ],
    'exoneraciones_cabys': [
      if (conMapa)
        {'cliente': '00010', 'cabys': '1111111111111', 'documento': 'AL-1'},
      if (conMapa)
        {'cliente': '00010', 'cabys': '3333333333333', 'documento': 'AL-1'},
    ],
  },
);

void main() {
  Documento armar(DatosCaja d) {
    final doc = Documento(d, const Cajero('00006', 'Ana'));
    for (final c in ['A', 'B', 'C', 'D']) {
      doc.agregar(d.articuloExacto(c)!, '1');
    }
    doc.asignarCliente(d.cliente('00010'));
    return doc;
  }

  test('con mapa de CABYS: cada línea con la que cubre su CABYS', () {
    final doc = armar(datos());
    final v = doc.exoneracionesCliente();
    expect(v.map((e) => e['documento']), ['AL-1', 'AL-2', 'VIEJA']);
    expect(v.last['vigente'], false);
    final p = doc.exoneracionPlan([0, 1, 2, 3], null);
    expect(p[0].exo!['documento'], 'AL-1');
    expect(p[0].porcentaje, 13);
    expect(
      p[1].motivo,
      'CABYS no autorizado en ninguna exoneración del cliente',
    );
    expect(p[2].motivo, 'La línea no lleva IVA');
    expect(p[3].motivo, 'La línea no tiene CABYS');
  });

  test('sin mapa: la elegida cubre todo; tipo 01 exige CABYS autorizado; tope en la tarifa', () {
    final doc = armar(datos(conMapa: false));
    final v = doc.exoneracionesCliente();
    final p = doc.exoneracionPlan([0, 1], v[0]);
    expect(p.every((r) => r.exo != null), true);
    final p01 = doc.exoneracionPlan([0], v[1]);
    expect(p01.single.motivo, 'CABYS 1111111111111 no exonerado');
    final p0 = doc.exoneracionPlan([0], {...v[0], 'porcentaje': 0});
    expect(p0.single.motivo, 'La exoneración tiene 0 %');
    final pinc = doc.exoneracionPlan([0], {...v[0], 'documento': ''});
    expect(pinc.single.motivo, contains('incompleta'));
  });

  test('aplicar baja el IVA, viaja en el paquete y en la venta guardada; quitar lo devuelve', () {
    final d = datos();
    final doc = armar(d);
    final antes = doc.totales.total;
    doc.exoneracionAplicar([0], null);
    final l = doc.lineas[0];
    expect(l.ivaExonerado, 13);
    expect(doc.totales.total, closeTo(antes - 130, 0.001));
    final pq = doc.paquete(
      pagos: [
        {'medio': '01', 'monto': doc.totales.total},
      ],
      vuelto: 0,
      transaccionId: 't',
      cuando: DateTime(2026, 11, 25, 9),
    );
    final linea = (pq['lineas'] as List).first as Map;
    expect((linea['exoneracion'] as Map)['numeroDocumento'], 'AL-1');
    expect(linea['porcentajeExoneracion'], 13);

    final copia = Documento(d, const Cajero('00006', 'Ana'))
      ..restaurar(doc.aMapa());
    expect(
      copia.lineas[0].ivaExonerado,
      13,
      reason:
          'la exoneración se guarda con la venta (proformas, venta en curso)',
    );

    expect(doc.exoneracionQuitar([0, 1]), 1);
    expect(doc.totales.total, closeTo(antes, 0.001));
  });
}
