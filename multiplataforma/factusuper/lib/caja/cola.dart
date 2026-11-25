/// Ventas guardadas en el equipo y su envío (#3957) — réplica de FSEnvio (factusuper_envio.js):
/// cada venta viaja con su transaccionId (el MISMO de cuando se cobró) a venta_procesar.php; el servidor garantiza que un
/// id produce como mucho UNA factura, así que reintentar es seguro.
///
///   procesada  → 'procesada' + número de factura y avisos
///   rechazada  → 'rechazada' + motivo (definitivo; sale de la cola y NO la frena)
///   error / en_proceso / sin red / 401 → se reintenta después con el MISMO id y la cola SE DETIENE ahí
///                (lo que viene detrás no se adelanta: la cola va en orden, etapa 17)
library;

import '../datos/almacen.dart';
import '../datos/conexion.dart';

class ResumenEnvio {
  int procesadas = 0, rechazadas = 0;
  String detenida = '';
}

class Cola {
  final Almacen almacen;
  final String empresa, llave;
  List<Map<String, dynamic>> ventas = [];
  bool _enCurso = false;
  Cola(this.almacen, this.empresa, this.llave);

  Future<void> cargar() async {
    final v = await almacen.leerTabla(empresa, 'ventas');
    ventas = v is List ? v.whereType<Map<String, dynamic>>().toList() : [];
    // Se guarda una semana lo terminado.
    final limite = DateTime.now().subtract(const Duration(days: 7));
    ventas.removeWhere(
      (x) =>
          (x['estado'] == 'procesada' || x['estado'] == 'rechazada') &&
          (DateTime.tryParse('${x['fecha']}')?.isBefore(limite) ?? false),
    );
  }

  Future<void> _guardar() => almacen.guardarTabla(empresa, 'ventas', ventas);

  List<Map<String, dynamic>> get pendientes => ventas
      .where((v) => v['estado'] != 'procesada' && v['estado'] != 'rechazada')
      .toList();

  /// Se guarda ANTES de enviar: si no hay internet, la venta no se pierde.
  Future<void> agregar(Map<String, dynamic> paquete) async {
    if (ventas.any((v) => v['transaccionId'] == paquete['transaccionId']))
      throw StateError('La venta ya estaba guardada');
    ventas.add({
      'transaccionId': paquete['transaccionId'],
      'idProceso': (paquete['documento'] as Map)['idProceso'],
      'estado': 'pendiente',
      'fecha': paquete['cobradoEn'],
      'total': paquete['total'],
      'cliente': paquete['cliente'],
      'lineas': (paquete['lineas'] as List).length,
      'intentos': 0,
      'paquete': paquete,
    });
    await _guardar();
  }

  /// Envía lo pendiente, una por una, en el orden en que se cobró.
  Future<ResumenEnvio> enviar() async {
    final r = ResumenEnvio();
    if (_enCurso) return r;
    _enCurso = true;
    try {
      final cola = pendientes
        ..sort((a, b) => '${a['fecha']}'.compareTo('${b['fecha']}'));
      for (final v in cola) {
        final paquete = v['paquete'] as Map<String, dynamic>;
        final con = Conexion(
          llave: llave,
          cajero: '${paquete['usuario'] ?? ''}',
        );
        Map<String, dynamic> d;
        try {
          d = await con.post(
            'venta_procesar.php',
            paquete,
            espera: const Duration(seconds: 90),
          );
        } on ErrorConexion catch (e) {
          r.detenida = e.sinInternet
              ? 'Sin internet: las ventas quedan guardadas y salen solas cuando vuelva'
              : e.mensaje;
          break;
        } finally {
          con.cerrar();
        }
        v['intentos'] = (v['intentos'] as num? ?? 0) + 1;
        v['ultimoEnvio'] = DateTime.now().toIso8601String();
        final estado = '${d['estado'] ?? ''}';
        if (estado.isEmpty) {
          r.detenida = 'El servidor no respondió bien';
          break;
        }
        v['estado'] = estado;
        if (estado == 'procesada') {
          v['factura'] = d['factura'];
          v['avisos'] = d['avisos'] ?? [];
          v['repetida'] = d['repetida'] == true;
          v.remove('error');
          r.procesadas++;
        } else if (estado == 'rechazada') {
          v['error'] = {
            'codigo': d['codigo'] ?? '',
            'mensaje': d['motivo'] ?? d['mensaje'] ?? 'Rechazada',
          };
          r.rechazadas++;
        } else {
          v['error'] = {
            'codigo': d['codigo'] ?? '',
            'mensaje': d['mensaje'] ?? estado,
          };
          await _guardar();
          r.detenida =
              'El servidor no terminó la venta ${v['idProceso']}: ${(v['error'] as Map)['mensaje']}';
          break;
        }
        await _guardar();
      }
    } finally {
      _enCurso = false;
    }
    return r;
  }
}
