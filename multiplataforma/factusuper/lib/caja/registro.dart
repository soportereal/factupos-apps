/// REGISTRO de lo que este equipo mandó a procesar (#3957) — réplica de FSLocal.colaRegistrar (MV-113 de la web):
/// cada proceso (venta, fondo, cliente, cajón) con su JSON, estado, intentos, resultado y la hora de respuesta.
/// Se guarda UNA SEMANA: lo terminado (procesado / rechazado) con más de 7 días se borra.
library;

import '../datos/almacen.dart';

class Registro {
  final Almacen almacen;
  final String empresa;
  Registro(this.almacen, this.empresa);

  static const tabla = 'cola_procesos';

  Future<List<Map<String, dynamic>>> lista() async {
    final v = await almacen.leerTabla(empresa, tabla);
    final l = v is List
        ? v.whereType<Map<String, dynamic>>().toList()
        : <Map<String, dynamic>>[];
    l.sort((a, b) => '${b['fecha']}'.compareTo('${a['fecha']}'));
    return l;
  }

  /// Crea o actualiza el renglón del proceso (se mezclan los campos).
  Future<void> anotar({
    required String idProceso,
    required String tipo,
    Object? json,
    required String estado,
    String resultado = '',
    String error = '',
    int intentos = 1,
  }) async {
    final ahora = DateTime.now().toUtc().toIso8601String();
    final l = await lista();
    final i = l.indexWhere((p) => p['idProceso'] == idProceso);
    final previo = i >= 0 ? l[i] : <String, dynamic>{'fecha': ahora};
    final nuevo = {
      ...previo,
      'idProceso': idProceso,
      'tipo': tipo,
      if (json != null) 'json': json,
      'estado': estado,
      'resultado': resultado,
      'error': error,
      'intentos': intentos,
      'respondidoEn': ahora,
      'actualizado': ahora,
    };
    if (i >= 0) {
      l[i] = nuevo;
    } else {
      l.add(nuevo);
    }
    final limite = DateTime.now().subtract(const Duration(days: 7));
    l.removeWhere(
      (p) =>
          (p['estado'] == 'procesado' || p['estado'] == 'rechazado') &&
          (DateTime.tryParse('${p['fecha']}')?.isBefore(limite) ?? false),
    );
    await almacen.guardarTabla(empresa, tabla, l);
  }
}
