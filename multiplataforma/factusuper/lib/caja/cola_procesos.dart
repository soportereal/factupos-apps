/// COLA DE PROCESOS (MV-113) — réplica de `pintarCola()` de la web (#3957): arriba lo que este equipo TODAVÍA no envió,
/// en el orden en que va a salir (en la app: clientes → cajón → ventas, por hora dentro de cada grupo; si uno falla los
/// de abajo esperan), y debajo lo ya enviado de los últimos 7 días (el registro), del más nuevo al más viejo.
library;

class FilaCola {
  final int? orden; // null = ya enviado
  final String tipo, id, fecha, detalle, estado, error;
  final num? monto;
  final Object? json;
  const FilaCola({
    this.orden,
    required this.tipo,
    required this.id,
    required this.fecha,
    this.detalle = '',
    this.monto,
    required this.estado,
    this.error = '',
    this.json,
  });
  bool get pendiente => orden != null;
}

const nombresProceso = {
  'venta': 'Venta',
  'cliente': 'Cliente',
  'cajon': 'Cajón',
  'fondo': 'Fondo',
};
const nombresEstado = {
  'pendiente': 'Pendiente',
  'error': 'Con error (reintenta)',
  'procesado': 'Procesado',
  'procesada': 'Procesado',
  'rechazado': 'Rechazado',
  'rechazada': 'Rechazado',
  'enviando': 'Enviando',
};

String _s(Object? v) => v == null ? '' : '$v';

List<FilaCola> armarCola({
  required List<Map<String, dynamic>> clientes,
  required List<Map<String, dynamic>> cajon,
  required List<Map<String, dynamic>> ventas,
  required List<Map<String, dynamic>> registro,
}) {
  int porHora(Map a, Map b, String k) => _s(a[k]).compareTo(_s(b[k]));
  final cli =
      clientes
          .where((c) => c['estado'] != 'rechazado' || c['nuevo'] == true)
          .toList()
        ..sort((a, b) => porHora(a, b, 'desde'));
  final caj = [...cajon]..sort((a, b) => porHora(a, b, 'fecha'));
  final ven = [...ventas]..sort((a, b) => porHora(a, b, 'fecha'));
  final reg = {for (final r in registro) _s(r['idProceso']): r};

  final filas = <FilaCola>[];
  void agregar(
    String tipo,
    String id,
    String fecha,
    String det,
    num? monto,
    String estado,
    String error,
    Object? json,
  ) {
    final r = reg.remove(id);
    filas.add(
      FilaCola(
        orden: filas.length + 1,
        tipo: tipo,
        id: id,
        fecha: fecha,
        detalle: det,
        monto: monto,
        estado: estado == 'rechazado'
            ? 'rechazado'
            : (r?['estado'] == 'error' || estado == 'error'
                  ? 'error'
                  : 'pendiente'),
        error: error.isNotEmpty ? error : _s(r?['error']),
        json: json,
      ),
    );
  }

  for (final c in cli) {
    final cambios = (c['cambios'] as Map?)?.keys.join(', ') ?? '';
    agregar(
      'cliente',
      _s(c['idProceso']),
      _s(c['desde'] ?? c['fecha']),
      '${c['nuevo'] == true ? 'Alta ' : ''}${_s(c['codigo'])}: $cambios',
      null,
      _s(c['estado']),
      _s(c['error']),
      c,
    );
  }
  for (final a in caj) {
    agregar(
      'cajon',
      _s(a['idProceso']),
      _s(a['fecha']),
      _s(a['autoriza']).isEmpty ? '' : 'Autorizó ${a['autoriza']}',
      null,
      'pendiente',
      '',
      a,
    );
  }
  for (final v in ven) {
    final pq = (v['paquete'] as Map?) ?? const {};
    final cli = (pq['cliente'] as Map?) ?? (v['cliente'] as Map?) ?? const {};
    final il = pq['impresionLocal'] ?? v['impresionLocal'];
    agregar(
      'venta',
      _s(v['idProceso']),
      _s(v['fecha']),
      [
        _s(cli['nombre']),
        if (pq['tipoPago'] == 'credito') 'crédito',
        if (il is Map && il['ok'] == true) 'provisional impreso',
      ].where((x) => x.isNotEmpty).join(' · '),
      v['total'] as num?,
      _s(v['estado']),
      _s(v['error']),
      pq,
    );
  }
  final hechos = reg.values.toList()
    ..sort((a, b) => _s(b['fecha']).compareTo(_s(a['fecha'])));
  for (final p in hechos) {
    final j = p['json'];
    num? monto;
    if (j is Map) monto = (j['total'] ?? j['monto']) as num?;
    filas.add(
      FilaCola(
        tipo: _s(p['tipo']),
        id: _s(p['idProceso']),
        fecha: _s(p['fecha']),
        detalle: _s(p['resultado']),
        monto: monto,
        estado: _s(p['estado']),
        error: _s(p['error']),
        json: j,
      ),
    );
  }
  return filas;
}

/// «3 en cola (salen en este orden…) · 12 enviados en los últimos 7 días».
String resumenCola(List<FilaCola> f) {
  final n = f.where((x) => x.pendiente).length;
  final h = f.length - n;
  return '${n > 0 ? '$n en cola (salen en este orden; si uno falla, los de abajo esperan)' : 'Nada pendiente'}'
      ' · $h enviados en los últimos 7 días';
}
