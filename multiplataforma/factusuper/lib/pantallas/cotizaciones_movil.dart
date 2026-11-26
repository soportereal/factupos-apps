// FactuMóvil — Cotizaciones del equipo (#3957, foto 12 del dueño: «cuando voy a buscar una cotización sale mal»).
// El diálogo de la caja (MV-114) en el celular dejaba el nombre en una columna de una letra (el total y el basurero se
// comían el ancho). Acá: pantalla completa con la barra navy de búsqueda y una tarjeta por cotización.
// → ('abrir' | 'borrar', id) o null — lo mismo que dialogoProformas, así _verProformas no cambia su lógica.
part of 'caja.dart';

class _CotizacionesMovil extends StatefulWidget {
  final List<Map<String, dynamic>> lista;
  final bool puedeBorrar;
  final String? actual;
  const _CotizacionesMovil({
    required this.lista,
    required this.puedeBorrar,
    this.actual,
  });
  @override
  State<_CotizacionesMovil> createState() => _EstadoCotizacionesMovil();
}

class _EstadoCotizacionesMovil extends State<_CotizacionesMovil> {
  final _q = TextEditingController();
  String _filtro = '';

  static String _hora(Object? t) {
    final d = DateTime.tryParse('$t')?.toLocal();
    if (d == null) return '';
    String x(int n) => n.toString().padLeft(2, '0');
    return '${x(d.day)}/${x(d.month)}/${d.year} ${x(d.hour)}:${x(d.minute)}';
  }

  @override
  Widget build(BuildContext context) {
    final partes = _filtro
        .toUpperCase()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty)
        .toList();
    final l = widget.lista.where((p) {
      if (partes.isEmpty) return true;
      final cli = (p['cliente'] as Map?) ?? const {};
      final b =
          '${p['id']} ${cli['codigo'] ?? ''} ${cli['nombre'] ?? ''} ${p['etiqueta'] ?? ''}'
              .toUpperCase();
      return partes.every(b.contains);
    }).toList()..sort((a, b) => '${b['fecha']}'.compareTo('${a['fecha']}'));
    return Scaffold(
      backgroundColor: _Fm.fondo,
      appBar: _fmBarraBusqueda(
        context,
        q: _q,
        pista: 'Buscar cotización',
        alEscribir: (t) => setState(() => _filtro = t.trim()),
      ),
      body: l.isEmpty
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  widget.lista.isEmpty
                      ? 'No hay cotizaciones guardadas en este equipo'
                      : 'No se encontró «$_filtro»',
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: _Fm.suave),
                ),
              ),
            )
          : ListView(
              padding: const EdgeInsets.all(10),
              children: [
                Padding(
                  padding: const EdgeInsets.only(left: 4, bottom: 6),
                  child: Text(
                    '${l.length} ${l.length == 1 ? 'guardada' : 'guardadas'} en este equipo',
                    style: const TextStyle(fontSize: 13, color: _Fm.suave),
                  ),
                ),
                for (final p in l) _tarjeta(p),
              ],
            ),
    );
  }

  Widget _tarjeta(Map<String, dynamic> p) {
    final id = '${p['id']}';
    final cli = (p['cliente'] as Map?) ?? const {};
    final cot = p['cotizacion'] == true;
    final et = '${p['etiqueta'] ?? ''}'.trim();
    final nombre = '${cli['nombre'] ?? ''}'.trim();
    final abierta = widget.actual == id;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => Navigator.pop(context, ('abrir', id)),
          child: Container(
            padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: abierta ? _Fm.acento : _Fm.borde,
                width: abierta ? 2 : 1,
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Wrap(
                        spacing: 6,
                        runSpacing: 4,
                        children: [
                          _fmEtiqueta(
                            cot ? 'COTIZACIÓN' : 'EN ESPERA',
                            cot
                                ? const Color(0xFFDCFCE7)
                                : const Color(0xFFFEF3C7),
                            cot
                                ? const Color(0xFF15803D)
                                : const Color(0xFFB45309),
                          ),
                          _fmEtiqueta(id, const Color(0xFFE2E8F0), _Fm.tinta),
                          if (abierta)
                            _fmEtiqueta('ABIERTA', _Fm.acento, Colors.white),
                        ],
                      ),
                      const SizedBox(height: 6),
                      Text(
                        nombre.isEmpty ? 'Cliente General (SN)' : nombre,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: _Fm.tinta,
                        ),
                      ),
                      if (et.isNotEmpty)
                        Text(
                          et,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontStyle: FontStyle.italic,
                            color: _Fm.suave,
                          ),
                        ),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              '${_hora(p['fecha'])} · ${p['lineas'] ?? 0} líneas',
                              style: const TextStyle(
                                fontSize: 12,
                                color: _Fm.suave,
                              ),
                            ),
                          ),
                          Text(
                            '₡${fmt((p['total'] as num?) ?? 0)}',
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                              color: _Fm.acento,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                Tooltip(
                  message: widget.puedeBorrar
                      ? 'Eliminar del equipo'
                      : 'Sin permiso para eliminar (060)',
                  child: IconButton(
                    icon: const Icon(Icons.delete_outline),
                    color: Marca.rojo,
                    onPressed: widget.puedeBorrar
                        ? () => Navigator.pop(context, ('borrar', id))
                        : null,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
