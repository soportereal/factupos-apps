// Detalle de una venta de la app (#3957, fotos del dueño 26-nov: «al tocar la factura en Ventas no muestra el detalle»).
// Réplica del detalle móvil de la web (components/shared/venta/venta_detalle): cabeza navy con el tipo y el número,
// CLIENTE · ARTÍCULOS · REVISIÓN (estado, contado/crédito, pagos) · ACCIONES.
// Los datos salen de la COPIA del equipo (el paquete que se mandó a facturar): se ve también sin internet.
// Acciones: Clonar a cotización (en el equipo) · Reimprimir (142) · Ver PDF / Compartir PDF / Email cliente / Email
// respaldo (venta_documento.php, la misma venta_correo_enviar() de la web) · NC, ND, NC/ND financiera (_NotaMovil, por
// nota_paso.php = los mismos archivos de VE-020 / MNC-001 de la web) · Generar XML (nota_paso.php?paso=xml, param 386).
part of 'caja.dart';

extension _DetalleMovil on _EstadoCaja {
  Future<void> _fmDetalleVenta(Map<String, dynamic> v) async {
    final accion = await Navigator.of(context).push<String>(
      MaterialPageRoute(
        builder: (_) => _DetalleVenta(
          venta: v,
          datos: widget.datos,
          llave: widget.config.llave,
          cajero: widget.cajero.usuario,
        ),
      ),
    );
    if (!mounted) return;
    if (accion == 'reimprimir') return _reimprimir(v);
    if (accion == 'clonar') return _fmClonar(v);
  }

  /// Clonar a cotización: las líneas de la venta pasan a una venta NUEVA en pantalla (con los precios de HOY).
  Future<void> _fmClonar(Map<String, dynamic> v) async {
    if (doc.lineas.isNotEmpty) {
      return _aviso(
        'Hay una venta en pantalla: guárdela o termínela antes de clonar.',
        error: true,
      );
    }
    final pq = (v['paquete'] as Map?) ?? const {};
    final codCli = '${(pq['cliente'] as Map?)?['codigo'] ?? ''}';
    final cli = widget.datos.cliente(codCli);
    if (cli != null) _cambio(() => doc.cliente = Map.of(cli));
    var n = 0, faltan = 0;
    for (final l in (pq['lineas'] as List?) ?? const []) {
      if (l is! Map) continue;
      final art = widget.datos.articuloExacto('${l['codigo']}');
      if (art == null) {
        faltan++;
        continue;
      }
      final c = ((l['cantidad'] as num?) ?? 1).toDouble();
      final msg = await _fmAgregarDesde(
        art,
        c == c.truncateToDouble() ? '${c.toInt()}' : '$c',
        '${l['bodega'] ?? ''}',
        ((l['tipoPrecio'] as num?) ?? 1).toInt(),
      );
      if (msg.isNotEmpty) n++;
    }
    _aviso(
      'Clonada: $n ${n == 1 ? 'línea' : 'líneas'} con los precios de hoy${faltan > 0 ? ' · $faltan ya no están en el equipo' : ''}. «Guardar» la deja como cotización.',
      error: faltan > 0,
    );
  }
}

class _DetalleVenta extends StatefulWidget {
  final Map<String, dynamic> venta;
  final DatosCaja datos;
  final String llave, cajero;
  const _DetalleVenta({
    required this.venta,
    required this.datos,
    required this.llave,
    required this.cajero,
  });
  @override
  State<_DetalleVenta> createState() => _EstadoDetalleVenta();
}

class _EstadoDetalleVenta extends State<_DetalleVenta> {
  String ocupado = ''; // la acción que está corriendo

  Map<String, dynamic> get v => widget.venta;
  Map get pq => (v['paquete'] as Map?) ?? const {};
  Map? get fac => v['factura'] is Map ? v['factura'] as Map : null;
  String get numero => '${fac?['numero'] ?? fac?['consecutivo'] ?? ''}';
  bool get facturada => v['estado'] == 'procesada' && numero.length == 20;

  String get _tipo {
    final t = numero.length == 20
        ? numero.substring(8, 10)
        : '${(pq['documento'] as Map?)?['tipoDocumento'] ?? '01'}';
    return switch (t) {
      '04' => 'TIQUETE ELECTRÓNICO',
      '09' => 'FACTURA DE EXPORTACIÓN',
      _ => 'FACTURA ELECTRÓNICA',
    };
  }

  void _mensaje(String t, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(t), backgroundColor: error ? Marca.rojo : null),
    );
  }

  /// PDF / correo por venta_documento.php.
  Future<Map<String, dynamic>?> _servidor(String accion) async {
    final con = Conexion(llave: widget.llave, cajero: widget.cajero);
    setState(() => ocupado = accion);
    try {
      final j = await con.post('venta_documento.php', {
        'numero': numero,
        'accion': accion,
      }, espera: const Duration(seconds: 120));
      if (j['ok'] != true) {
        _mensaje('${j['error'] ?? 'No se pudo'}', error: true);
        return null;
      }
      return j;
    } on ErrorConexion catch (e) {
      _mensaje('Sin conexión con el servidor: ${e.mensaje}', error: true);
      return null;
    } catch (e) {
      _mensaje('No se pudo: $e', error: true);
      return null;
    } finally {
      con.cerrar();
      if (mounted) setState(() => ocupado = '');
    }
  }

  String get _clienteCodigo =>
      '${(pq['cliente'] as Map?)?['codigo'] ?? ''}'.trim();
  bool get _clienteGenerico =>
      const ['SN', 'sn', 'Sn', '0', ''].contains(_clienteCodigo);

  /// NC / ND (normal contra ESTA factura, o financiera contra el cliente) — VE-020 de la web.
  Future<void> _nota(String tipo, {bool financiera = false}) async {
    final n = await Navigator.of(context).push<String>(
      MaterialPageRoute(
        builder: (_) => _NotaMovil(
          llave: widget.llave,
          cajero: widget.cajero,
          tipo: tipo,
          financiera: financiera,
          factura: financiera ? '' : numero,
          cliente: _clienteCodigo,
        ),
      ),
    );
    if (n != null) {
      _mensaje(
        '${tipo == '03' ? 'Nota de crédito' : 'Nota de débito'} $n aplicada',
      );
    }
  }

  /// Generar XML (igual que «Generar XML» del detalle de la web: solo con el param 386).
  Future<void> _xml() async {
    final si = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('¿Generar XML?'),
        content: Text('Se genera el XML de Hacienda de la factura $numero.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Generar'),
          ),
        ],
      ),
    );
    if (si != true || !mounted) return;
    final con = Conexion(llave: widget.llave, cajero: widget.cajero);
    setState(() => ocupado = 'xml');
    try {
      final j = await con.post('nota_paso.php?paso=xml', {
        'documento': numero,
      }, espera: const Duration(seconds: 120));
      final ok = j['success'] == true;
      _mensaje(
        ok ? 'XML generado' : '${j['message'] ?? j['error'] ?? 'Error'}',
        error: !ok,
      );
    } on ErrorConexion catch (e) {
      _mensaje('Sin conexión con el servidor: ${e.mensaje}', error: true);
    } catch (e) {
      _mensaje('No se pudo: $e', error: true);
    } finally {
      con.cerrar();
      if (mounted) setState(() => ocupado = '');
    }
  }

  Future<String?> _pdf() async {
    final j = await _servidor('pdf');
    final b = '${j?['pdf_base64'] ?? ''}';
    if (b.isEmpty) return null;
    final dir = await getTemporaryDirectory();
    final nombre = '${j?['filename'] ?? 'factura.pdf'}'.replaceAll(
      RegExp(r'[^\w.\-]'),
      '_',
    );
    final f = File('${dir.path}${Platform.pathSeparator}$nombre');
    await f.writeAsBytes(base64Decode(b));
    return f.path;
  }

  Future<void> _verPdf() async {
    final p = await _pdf();
    if (p == null) return;
    final r = await OpenFilex.open(p);
    if (r.type != ResultType.done) {
      _mensaje('No hay una app para abrir PDF: ${r.message}', error: true);
    }
  }

  Future<void> _compartirPdf() async {
    final p = await _pdf();
    if (p == null) return;
    await SharePlus.instance.share(
      ShareParams(files: [XFile(p)], text: '$_tipo #${numero.substring(12)}'),
    );
  }

  Future<void> _correo(String destino) async {
    final j = await _servidor(destino);
    if (j == null) return;
    final m = '${j['mensaje'] ?? ''}'.trim();
    _mensaje(m.isEmpty ? 'Correo enviado' : m);
  }

  // ── piezas ──
  Widget _seccion(IconData ico, String titulo, Widget hijo, {String? cuenta}) =>
      Container(
        margin: const EdgeInsets.fromLTRB(10, 10, 10, 0),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: _Fm.borde),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(
              padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
              decoration: const BoxDecoration(
                color: Color(0xFFE6EEF8),
                borderRadius: BorderRadius.vertical(top: Radius.circular(14)),
              ),
              child: Row(
                children: [
                  Icon(ico, color: _Fm.navy1),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      titulo,
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        letterSpacing: 1,
                        color: _Fm.navy1,
                      ),
                    ),
                  ),
                  if (cuenta != null)
                    _fmEtiqueta(cuenta, Colors.white, _Fm.acento),
                ],
              ),
            ),
            Padding(padding: const EdgeInsets.all(14), child: hijo),
          ],
        ),
      );

  Widget _renglon(
    IconData ico,
    String t,
    String monto,
    Color fondo,
    Color tinta,
  ) => Container(
    margin: const EdgeInsets.only(bottom: 8),
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
    decoration: BoxDecoration(
      color: fondo,
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: tinta.withValues(alpha: 0.25)),
    ),
    child: Row(
      children: [
        Icon(ico, size: 20, color: tinta),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            t,
            style: TextStyle(fontWeight: FontWeight.w600, color: tinta),
          ),
        ),
        if (monto.isNotEmpty)
          Text(
            monto,
            style: TextStyle(fontWeight: FontWeight.w700, color: tinta),
          ),
      ],
    ),
  );

  Widget _boton(
    IconData ico,
    String t,
    List<Color> colores,
    VoidCallback? f, {
    String clave = '',
    String tip = 'Próximamente en la app',
  }) {
    final activo = f != null && ocupado.isEmpty;
    final b = Opacity(
      opacity: f == null ? 0.45 : 1,
      child: Material(
        borderRadius: BorderRadius.circular(10),
        clipBehavior: Clip.antiAlias,
        child: Ink(
          decoration: BoxDecoration(gradient: LinearGradient(colors: colores)),
          child: InkWell(
            onTap: activo ? f : null,
            child: SizedBox(
              height: 50,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (ocupado == clave && clave.isNotEmpty)
                    const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  else
                    Icon(ico, color: Colors.white, size: 20),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      t,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                        fontSize: 15,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    return f == null ? Tooltip(message: tip, child: b) : b;
  }

  @override
  Widget build(BuildContext context) {
    final cli = (pq['cliente'] as Map?) ?? const {};
    final cc = (pq['clienteCompleto'] as Map?) ?? const {};
    final credito = pq['tipoPago'] == 'credito';
    final fecha = DateTime.tryParse('${pq['cobradoEn'] ?? ''}')?.toLocal();
    String dos(int n) => n.toString().padLeft(2, '0');
    final cuando = fecha == null
        ? ''
        : '${dos(fecha.day)}/${dos(fecha.month)}/${fecha.year} ${dos(fecha.hour)}:${dos(fecha.minute)}';
    final lineas = [
      for (final l in (pq['lineas'] as List?) ?? const [])
        if (l is Map) l,
    ];
    final medios = widget.datos.mediosPago();
    String nombreMedio(Map p) {
      final m = medios.where((x) => x.codigo == '${p['medio']}').firstOrNull;
      final n = m?.nombres['${p['cuenta'] ?? ''}'] ?? '';
      return n.isNotEmpty ? n : (m?.descripcion ?? '${p['medio']}');
    }

    final vendedor = widget.datos.nombreUsuario(
      '${pq['agente'] ?? pq['usuario'] ?? ''}',
    );
    final estado = '${v['estado']}';
    const estados = {
      'pendiente': 'Pendiente de enviar',
      'en_proceso': 'Enviando',
      'error': 'Reintentará',
      'procesada': 'Facturada',
      'rechazada': 'Rechazada',
    };
    final sinFactura = 'Disponible cuando la venta esté facturada';
    const sinGenerico =
        'Las notas financieras no aplican para el cliente genérico (SN)';
    final total = ((v['total'] ?? pq['total']) as num?) ?? 0;

    return Scaffold(
      backgroundColor: _Fm.fondo,
      body: SafeArea(
        child: Column(
          children: [
            Container(
              padding: const EdgeInsets.fromLTRB(10, 12, 16, 12),
              decoration: const BoxDecoration(
                gradient: LinearGradient(colors: [_Fm.navy1, _Fm.navy2]),
              ),
              child: Row(
                children: [
                  IconButton(
                    tooltip: 'Regresar',
                    onPressed: () => Navigator.pop(context),
                    style: IconButton.styleFrom(
                      backgroundColor: const Color(0x33FFFFFF),
                      minimumSize: const Size(48, 48),
                    ),
                    icon: const Icon(Icons.arrow_back, color: Colors.white),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _tipo,
                          style: const TextStyle(
                            color: Colors.white70,
                            letterSpacing: 0.8,
                          ),
                        ),
                        Text(
                          numero.length == 20
                              ? '#${numero.substring(12)}'
                              : '${v['idProceso'] ?? ''}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 20,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      const Text(
                        'CRC',
                        style: TextStyle(color: Colors.white70),
                      ),
                      Text(
                        fmt(total, 0),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 24,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.only(bottom: 20),
                children: [
                  _seccion(
                    Icons.account_circle_outlined,
                    'CLIENTE',
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${cli['nombre'] ?? 'Cliente General'}'.toUpperCase(),
                          style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w800,
                            color: _Fm.tinta,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          [
                            '${cc['cedula'] ?? ''}',
                            cuando,
                            credito
                                ? 'Crédito ${pq['diasCredito'] ?? ''} días'
                                : 'Contado',
                          ].where((x) => x.trim().isNotEmpty).join('  ·  '),
                          style: const TextStyle(color: _Fm.suave),
                        ),
                        if ('${cc['comercial'] ?? ''}'.trim().isNotEmpty) ...[
                          const SizedBox(height: 6),
                          _fmEtiqueta(
                            '${cc['comercial']}',
                            const Color(0xFFEFF4FA),
                            _Fm.tinta,
                          ),
                        ],
                        if (vendedor.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Row(
                            children: [
                              const Icon(
                                Icons.badge_outlined,
                                size: 16,
                                color: _Fm.suave,
                              ),
                              const SizedBox(width: 4),
                              Text(
                                vendedor,
                                style: const TextStyle(color: _Fm.tinta),
                              ),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                  _seccion(
                    Icons.shopping_cart_outlined,
                    'ARTÍCULOS',
                    cuenta: '${lineas.length}',
                    Column(
                      children: [
                        for (var i = 0; i < lineas.length; i++) ...[
                          if (i > 0) const Divider(height: 20),
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      '${lineas[i]['codigo']}',
                                      style: const TextStyle(
                                        fontSize: 12,
                                        color: _Fm.suave,
                                      ),
                                    ),
                                    Text(
                                      '${lineas[i]['nombre'] ?? ''}',
                                      style: const TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w600,
                                        color: _Fm.tinta,
                                      ),
                                    ),
                                    const SizedBox(height: 2),
                                    Wrap(
                                      spacing: 6,
                                      crossAxisAlignment:
                                          WrapCrossAlignment.center,
                                      children: [
                                        Text(
                                          '${fmt((lineas[i]['cantidad'] as num?) ?? 0)} × ${fmt((lineas[i]['precio'] as num?) ?? 0)}',
                                          style: const TextStyle(
                                            color: _Fm.suave,
                                          ),
                                        ),
                                        _fmEtiqueta(
                                          'IVA ${fmt((lineas[i]['iva'] as num?) ?? 0, 0)}%',
                                          const Color(0xFFE0EAFF),
                                          _Fm.acento,
                                        ),
                                        if (((lineas[i]['descuento'] as num?) ??
                                                0) >
                                            0)
                                          _fmEtiqueta(
                                            'Desc ${fmt((lineas[i]['descuento'] as num?) ?? 0)}%',
                                            const Color(0xFFFEF3C7),
                                            const Color(0xFFB45309),
                                          ),
                                      ],
                                    ),
                                  ],
                                ),
                              ),
                              Text(
                                fmt((lineas[i]['total'] as num?) ?? 0),
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w800,
                                  color: _Fm.navy1,
                                ),
                              ),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                  _seccion(
                    Icons.fact_check_outlined,
                    'REVISIÓN',
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        estado == 'procesada'
                            ? _renglon(
                                Icons.check_circle,
                                'Facturada',
                                '',
                                const Color(0xFFECFDF3),
                                Marca.verdeOscuro,
                              )
                            : _renglon(
                                estado == 'rechazada'
                                    ? Icons.cancel
                                    : Icons.schedule,
                                estados[estado] ?? estado,
                                '',
                                estado == 'rechazada'
                                    ? const Color(0xFFFDECEC)
                                    : const Color(0xFFFFF7ED),
                                estado == 'rechazada'
                                    ? Marca.rojo
                                    : Marca.ambar,
                              ),
                        if (v['error'] is Map)
                          _renglon(
                            Icons.error_outline,
                            '${(v['error'] as Map)['mensaje']}',
                            '',
                            const Color(0xFFFDECEC),
                            Marca.rojo,
                          ),
                        if (credito)
                          _renglon(
                            Icons.event_note_outlined,
                            'A crédito · ${pq['diasCredito'] ?? 0} días',
                            'CRC ${fmt(total)}',
                            const Color(0xFFF1EEFF),
                            const Color(0xFF6D28D9),
                          ),
                        for (final p in (pq['pagos'] as List?) ?? const [])
                          if (p is Map)
                            _renglon(
                              Icons.payments_outlined,
                              nombreMedio(p),
                              'CRC ${fmt((p['monto'] as num?) ?? 0)}',
                              const Color(0xFFEFFAF3),
                              Marca.verdeOscuro,
                            ),
                        if (((pq['vuelto'] as num?) ?? 0) > 0)
                          _renglon(
                            Icons.currency_exchange,
                            'Vuelto',
                            'CRC ${fmt((pq['vuelto'] as num?) ?? 0)}',
                            const Color(0xFFF3F6FA),
                            _Fm.tinta,
                          ),
                        if (fac != null && numero.length == 20)
                          _renglon(
                            Icons.receipt_long_outlined,
                            'Consecutivo $numero',
                            '',
                            const Color(0xFFEFF4FA),
                            _Fm.navy1,
                          ),
                      ],
                    ),
                  ),
                  _seccion(
                    Icons.bolt,
                    'ACCIONES',
                    Column(
                      children: [
                        _boton(
                          Icons.copy_all_outlined,
                          'Clonar a cotización',
                          const [Color(0xFF6D5BE6), Color(0xFF4F46E5)],
                          () => Navigator.pop(context, 'clonar'),
                        ),
                        const SizedBox(height: 8),
                        _par(
                          _boton(
                            Icons.print_outlined,
                            'Reimprimir',
                            const [Color(0xFF3B82F6), Color(0xFF2563EB)],
                            facturada
                                ? () => Navigator.pop(context, 'reimprimir')
                                : null,
                            tip: sinFactura,
                          ),
                          _boton(
                            Icons.picture_as_pdf_outlined,
                            'Ver PDF',
                            const [Color(0xFF64748B), Color(0xFF475569)],
                            facturada ? _verPdf : null,
                            clave: 'pdf',
                            tip: sinFactura,
                          ),
                        ),
                        _par(
                          _boton(
                            Icons.remove_circle_outline,
                            'Nota Crédito',
                            const [Color(0xFFE05252), Color(0xFFC53030)],
                            facturada ? () => _nota('03') : null,
                            tip: sinFactura,
                          ),
                          _boton(
                            Icons.add_circle_outline,
                            'Nota Débito',
                            const [Color(0xFFF0A030), Color(0xFFD97706)],
                            facturada ? () => _nota('02') : null,
                            tip: sinFactura,
                          ),
                        ),
                        _par(
                          _boton(
                            Icons.currency_exchange,
                            'NC Financiera',
                            const [Color(0xFF8B5CF6), Color(0xFF7C3AED)],
                            _clienteGenerico
                                ? null
                                : () => _nota('03', financiera: true),
                            tip: sinGenerico,
                          ),
                          _boton(
                            Icons.currency_exchange,
                            'ND Financiera',
                            const [Color(0xFF8B5CF6), Color(0xFF7C3AED)],
                            _clienteGenerico
                                ? null
                                : () => _nota('02', financiera: true),
                            tip: sinGenerico,
                          ),
                        ),
                        _par(
                          _boton(
                            Icons.mail_outline,
                            'Email cliente',
                            const [Color(0xFF3B9BE0), Color(0xFF2B7BC0)],
                            facturada ? () => _correo('correo_cliente') : null,
                            clave: 'correo_cliente',
                            tip: sinFactura,
                          ),
                          _boton(
                            Icons.forward_to_inbox_outlined,
                            'Email respaldo',
                            const [Color(0xFF3B9BE0), Color(0xFF2B7BC0)],
                            facturada ? () => _correo('correo_respaldo') : null,
                            clave: 'correo_respaldo',
                            tip: sinFactura,
                          ),
                        ),
                        _par(
                          _boton(
                            Icons.share_outlined,
                            'Compartir PDF',
                            const [Color(0xFFE0488A), Color(0xFFC0306E)],
                            facturada ? _compartirPdf : null,
                            tip: sinFactura,
                          ),
                          _boton(
                            Icons.code,
                            'Generar XML',
                            const [Color(0xFF334155), Color(0xFF1E293B)],
                            facturada ? _xml : null,
                            clave: 'xml',
                            tip: sinFactura,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _par(Widget a, Widget b) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      children: [
        Expanded(child: a),
        const SizedBox(width: 8),
        Expanded(child: b),
      ],
    ),
  );
}
