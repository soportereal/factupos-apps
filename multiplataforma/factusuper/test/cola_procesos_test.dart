// #3957 — MV-113: la cola en el orden en que sale (clientes → cajón → ventas, por hora) y debajo lo enviado (7 días),
// del más nuevo al más viejo; el error del registro se ve en la fila pendiente.
import 'package:factusuper/caja/cola_procesos.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('orden de salida, detalle, monto y lo ya enviado', () {
    final f = armarCola(
      clientes: [
        {
          'idProceso': 'C-2',
          'codigo': '00010',
          'desde': '2026-11-25T10:05:00Z',
          'cambios': {'telefonos': '1', 'descuento': 5},
          'estado': 'pendiente',
        },
        {
          'idProceso': 'N-1',
          'codigo': 'N-1',
          'nuevo': true,
          'desde': '2026-11-25T10:01:00Z',
          'cambios': {'nombre': 'X'},
          'estado': 'pendiente',
        },
        {'idProceso': 'C-9', 'codigo': '9', 'estado': 'rechazado'},
      ],
      cajon: [
        {
          'idProceso': 'A-1',
          'fecha': '2026-11-25T09:00:00Z',
          'autoriza': '00002',
        },
      ],
      ventas: [
        {
          'idProceso': 'V-2',
          'fecha': '2026-11-25T11:00:00Z',
          'total': 500,
          'estado': 'pendiente',
          'paquete': {
            'cliente': {'nombre': 'ANA'},
            'tipoPago': 'credito',
          },
        },
        {
          'idProceso': 'V-1',
          'fecha': '2026-11-25T08:00:00Z',
          'total': 100,
          'estado': 'pendiente',
          'paquete': {
            'cliente': {'nombre': 'CONTADO'},
            'impresionLocal': {'ok': true},
          },
        },
      ],
      registro: [
        {'idProceso': 'V-1', 'estado': 'error', 'error': 'Sin internet'},
        {
          'idProceso': 'V-0',
          'tipo': 'venta',
          'fecha': '2026-11-24T08:00:00Z',
          'estado': 'procesado',
          'json': {'total': 50},
        },
        {
          'idProceso': 'F-1',
          'tipo': 'fondo',
          'fecha': '2026-11-25T07:00:00Z',
          'estado': 'procesado',
          'json': {'monto': 2000},
        },
      ],
    );
    expect(f.map((x) => x.id), [
      'N-1',
      'C-2',
      'A-1',
      'V-1',
      'V-2',
      'F-1',
      'V-0',
    ]);
    expect(f.map((x) => x.orden), [1, 2, 3, 4, 5, null, null]);
    expect(f[0].detalle, 'Alta N-1: nombre');
    expect(f[1].detalle, '00010: telefonos, descuento');
    expect(f[2].detalle, 'Autorizó 00002');
    expect(f[3].detalle, 'CONTADO · provisional impreso');
    expect(f[3].estado, 'error');
    expect(f[3].error, 'Sin internet');
    expect(f[4].detalle, 'ANA · crédito');
    expect(f[4].monto, 500);
    expect(f[5].monto, 2000);
    expect(resumenCola(f), startsWith('5 en cola'));
    expect(resumenCola(f), endsWith('2 enviados en los últimos 7 días'));
    expect(
      resumenCola(const []),
      'Nada pendiente · 0 enviados en los últimos 7 días',
    );
  });
}
