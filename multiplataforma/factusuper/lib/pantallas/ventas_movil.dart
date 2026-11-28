// FactuMóvil · VENTAS con filtros (#3957, foto del dueño 28-nov sobre «Ventas de esta caja»: «no se pueden filtrar las
// ventas… cuánto la venta de hoy, ayer, la semana y el mes» · «también para saber las mías y todas»).
//
// 🔑 Las ventas son las del SERVIDOR (apis/shared/venta/factusuper/ventas_resumen.php = la consulta de FmVentas de la web):
//    período Hoy · Ayer · Semana (desde el lunes) · Mes (desde el 1.º) y Mías / Todas. «Todas» pide el permiso 069, igual
//    que la web: sin él queda GRIS con su aviso (y el servidor igual fuerza «mías»).
// 🔑 El total suma como los reportes de ventas: solo lo PROCESADO, la NC resta, en colones. Lo nulo o pendiente sale en la
//    lista con su estado pero no suma.
// 🔑 Lo cobrado en ESTE equipo que todavía no llegó al servidor no está en la cuenta: se avisa, y «Este equipo» abre la
//    lista de siempre (la cola, con «Enviar ahora» y reimprimir).
part of 'caja.dart';

class _VentasMovil extends StatefulWidget {
  final String llave, cajero;
  final List<Map<String, dynamic>> locales;
  final int pendientes;
  final Future<void> Function() alEsteEquipo;
  final Future<void> Function(Map<String, dynamic>) alAbrirLocal;
  const _VentasMovil({
    required this.llave,
    required this.cajero,
    required this.locales,
    required this.pendientes,
    required this.alEsteEquipo,
    required this.alAbrirLocal,
  });

  @override
  State<_VentasMovil> createState() => _EstadoVentasMovil();
}

class _EstadoVentasMovil extends State<_VentasMovil> {
  static const _periodos = ['Hoy', 'Ayer', 'Semana', 'Mes'];
  String _periodo = 'Hoy';
  bool _todas = false;
  bool _puedeOtros =
      true; // optimista hasta la primera respuesta (la web hace igual)
  bool _cargando = true;
  String _error = '';
  Map<String, dynamic> _resumen = const {};
  List<Map<String, dynamic>> _docs = const [];
  Conexion? _con;
  int _pedido = 0;

  static String _t(Object? v) => '${v ?? ''}'.trim();
  static double _n(Object? v) =>
      v is num ? v.toDouble() : double.tryParse('$v') ?? 0;
  static String _ymd(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  static String _dm(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}/${d.year}';

  (DateTime, DateTime) get _rango {
    final n = DateTime.now();
    final hoy = DateTime(n.year, n.month, n.day);
    switch (_periodo) {
      case 'Ayer':
        final a = hoy.subtract(const Duration(days: 1));
        return (a, a);
      case 'Semana':
        return (hoy.subtract(Duration(days: hoy.weekday - 1)), hoy);
      case 'Mes':
        return (DateTime(hoy.year, hoy.month), hoy);
      default:
        return (hoy, hoy);
    }
  }

  String get _rangoTexto {
    final (d, h) = _rango;
    return d == h ? _dm(d) : '${_dm(d)} al ${_dm(h)}';
  }

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  @override
  void dispose() {
    _con?.cerrar();
    super.dispose();
  }

  Future<void> _cargar() async {
    final yo = ++_pedido;
    setState(() {
      _cargando = true;
      _error = '';
    });
    final (d, h) = _rango;
    try {
      final con = _con ??= Conexion(llave: widget.llave, cajero: widget.cajero);
      final j = await con.post(
        '/apis/shared/venta/factusuper/ventas_resumen.php',
        {'desde': _ymd(d), 'hasta': _ymd(h), 'ver': _todas ? 'todas' : 'mias'},
        espera: const Duration(seconds: 20),
      );
      if (!mounted || yo != _pedido)
        return; // llegó tarde: ya se pidió otro período
      setState(() {
        _cargando = false;
        if (j['success'] == true) {
          _puedeOtros = j['puede_ver_otros'] == true;
          if (!_puedeOtros) _todas = false;
          _resumen = j['resumen'] is Map
              ? Map<String, dynamic>.from(j['resumen'] as Map)
              : const {};
          final l = j['documentos'];
          _docs = l is List
              ? [
                  for (final x in l)
                    if (x is Map) Map<String, dynamic>.from(x),
                ]
              : const [];
        } else {
          _error = _t(j['error']).isEmpty
              ? 'No se pudieron consultar las ventas'
              : _t(j['error']);
        }
      });
    } catch (_) {
      if (!mounted || yo != _pedido) return;
      setState(() {
        _cargando = false;
        _error = 'Sin conexión: las ventas se consultan en el servidor. Lo de este equipo se ve en «Este equipo».';
      });
    }
  }

  void _elegirPeriodo(String p) {
    if (p == _periodo) return;
    setState(() => _periodo = p);
    _cargar();
  }

  void _elegirTodas(bool v) {
    if (v == _todas || (v && !_puedeOtros)) return;
    setState(() => _todas = v);
    _cargar();
  }

  Future<void> _abrir(Map<String, dynamic> d) async {
    final num = _t(d['numero']);
    final local = widget.locales
        .where((v) => _t((v['factura'] as Map?)?['numero']) == num)
        .firstOrNull;
    if (local != null && local['paquete'] is Map) {
      await widget.alAbrirLocal(local);
      return;
    }
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        const SnackBar(
          content: Text(
            'Esta venta no se cobró en este equipo: el detalle completo se ve en el equipo donde se hizo.',
          ),
          duration: Duration(seconds: 3),
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _Fm.fondo,
      appBar: PreferredSize(
        preferredSize: const Size.fromHeight(60),
        child: Container(
          padding: EdgeInsets.fromLTRB(
            12,
            MediaQuery.paddingOf(context).top + 10,
            10,
            10,
          ),
          decoration: const BoxDecoration(
            gradient: LinearGradient(colors: [_Fm.navy1, _Fm.navy2]),
          ),
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  'Ventas',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 17,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              Material(
                color: const Color(0xFF991B1B),
                borderRadius: BorderRadius.circular(6),
                child: InkWell(
                  borderRadius: BorderRadius.circular(6),
                  onTap: () => Navigator.pop(context),
                  child: Container(
                    height: 40,
                    padding: const EdgeInsets.symmetric(horizontal: 10),
                    decoration: BoxDecoration(
                      border: Border.all(color: const Color(0x66FFFFFF)),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.arrow_back, color: Colors.white, size: 18),
                        SizedBox(width: 4),
                        Text(
                          'Regresar',
                          style: TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w600,
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: _cargar,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.fromLTRB(8, 10, 8, 24),
          children: [
            _filtros(),
            const SizedBox(height: 10),
            _tarjetaTotal(),
            const SizedBox(height: 8),
            _botonEsteEquipo(),
            const SizedBox(height: 10),
            ..._lista(),
          ],
        ),
      ),
    );
  }

  Widget _filtros() {
    Widget boton(
      String t,
      bool sel,
      VoidCallback? f, {
      String aviso = '',
      IconData? ico,
    }) {
      final apagado = f == null;
      final w = Material(
        color: sel
            ? _Fm.navy1
            : apagado
            ? const Color(0xFFE5E7EB)
            : Colors.white,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: f,
          child: Container(
            height: 42,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              border: Border.all(color: sel ? _Fm.navy1 : _Fm.borde),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (ico != null) ...[
                  Icon(
                    ico,
                    size: 17,
                    color: sel
                        ? Colors.white
                        : apagado
                        ? const Color(0xFF9CA3AF)
                        : _Fm.navy1,
                  ),
                  const SizedBox(width: 5),
                ],
                Text(
                  t,
                  style: TextStyle(
                    fontSize: 14.5,
                    fontWeight: FontWeight.w600,
                    color: sel
                        ? Colors.white
                        : apagado
                        ? const Color(0xFF9CA3AF)
                        : _Fm.tinta,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
      return Expanded(
        child: aviso.isEmpty ? w : Tooltip(message: aviso, child: w),
      );
    }

    return Column(
      children: [
        Row(
          children: [
            for (final p in _periodos) ...[
              if (p != _periodos.first) const SizedBox(width: 6),
              boton(p, _periodo == p, () => _elegirPeriodo(p)),
            ],
          ],
        ),
        const SizedBox(height: 6),
        Row(
          children: [
            boton(
              'Mías',
              !_todas,
              () => _elegirTodas(false),
              ico: Icons.person_outline,
            ),
            const SizedBox(width: 6),
            boton(
              'Todas',
              _todas,
              _puedeOtros ? () => _elegirTodas(true) : null,
              ico: Icons.groups_outlined,
              aviso: _puedeOtros
                  ? ''
                  : 'Ver las ventas de otros usuarios requiere el permiso 069',
            ),
          ],
        ),
      ],
    );
  }

  Widget _tarjetaTotal() {
    final neto = _n(_resumen['neto']);
    final vn = _n(_resumen['ventas_n']).toInt();
    final nc = _n(_resumen['nc']);
    final ncn = _n(_resumen['nc_n']).toInt();
    final sin = _n(_resumen['sin_sumar_n']).toInt();
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        gradient: const LinearGradient(colors: [_Fm.navy1, _Fm.navy2]),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${_todas ? 'Todas las ventas' : 'Mis ventas'} · $_periodo · $_rangoTexto',
            style: const TextStyle(color: Color(0xFFC7D6EA), fontSize: 13),
          ),
          const SizedBox(height: 4),
          if (_cargando)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: SizedBox(
                height: 26,
                width: 26,
                child: CircularProgressIndicator(
                  strokeWidth: 2.5,
                  color: Colors.white,
                ),
              ),
            )
          else if (_error.isNotEmpty)
            Text(
              '—',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 30,
                fontWeight: FontWeight.w800,
              ),
            )
          else ...[
            Text(
              '₡${fmt(neto)}',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 30,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              '$vn ${vn == 1 ? 'documento' : 'documentos'}'
              '${ncn > 0 ? ' · notas de crédito −₡${fmt(nc)} ($ncn)' : ''}',
              style: const TextStyle(color: Colors.white, fontSize: 13.5),
            ),
            if (sin > 0)
              Text(
                '$sin sin sumar (nulos, rechazados o sin procesar)',
                style: const TextStyle(
                  color: Color(0xFFFCD34D),
                  fontSize: 12.5,
                ),
              ),
          ],
          if (widget.pendientes > 0)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                '${widget.pendientes} ${widget.pendientes == 1 ? 'venta' : 'ventas'} de este equipo todavía sin llegar al servidor (no están en la cuenta)',
                style: const TextStyle(
                  color: Color(0xFFFCD34D),
                  fontSize: 12.5,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _botonEsteEquipo() => Material(
    color: Colors.white,
    borderRadius: BorderRadius.circular(8),
    child: InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () async {
        await widget.alEsteEquipo();
        if (mounted) setState(() {});
      },
      child: Container(
        height: 44,
        padding: const EdgeInsets.symmetric(horizontal: 12),
        decoration: BoxDecoration(
          border: Border.all(color: const Color(0xFF86D4AB)),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          children: [
            const Icon(Icons.phone_android, size: 19, color: Color(0xFF059669)),
            const SizedBox(width: 8),
            const Expanded(
              child: Text(
                'Este equipo (envíos y reimprimir)',
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF059669),
                ),
              ),
            ),
            if (widget.pendientes > 0)
              _fmEtiqueta(
                '${widget.pendientes} por enviar',
                const Color(0xFFFEF3C7),
                const Color(0xFFB45309),
              ),
            const Icon(Icons.chevron_right, color: Color(0xFF94A3B8)),
          ],
        ),
      ),
    ),
  );

  List<Widget> _lista() {
    Widget aviso(IconData ico, String t, {bool reintentar = false}) => Padding(
      padding: const EdgeInsets.fromLTRB(16, 30, 16, 10),
      child: Column(
        children: [
          Icon(ico, size: 52, color: const Color(0x809AB0CB)),
          const SizedBox(height: 8),
          Text(
            t,
            textAlign: TextAlign.center,
            style: const TextStyle(color: _Fm.suave, fontSize: 15),
          ),
          if (reintentar) ...[
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: _cargar,
              icon: const Icon(Icons.refresh),
              label: const Text('Reintentar'),
            ),
          ],
        ],
      ),
    );
    if (_cargando && _docs.isEmpty) return const [];
    if (_error.isNotEmpty) {
      return [aviso(Icons.cloud_off_outlined, _error, reintentar: true)];
    }
    if (_docs.isEmpty) {
      return [aviso(Icons.receipt_long_outlined, 'Sin ventas en este período')];
    }
    return [
      if (_docs.length >= 300)
        const Padding(
          padding: EdgeInsets.only(bottom: 6),
          child: Text(
            'Se muestran los 300 más recientes; el total de arriba es del período completo.',
            style: TextStyle(color: _Fm.suave, fontSize: 12.5),
          ),
        ),
      for (final d in _docs) _documento(d),
    ];
  }

  Widget _documento(Map<String, dynamic> d) {
    final nc = _t(d['tipo']) == '03';
    final estado = _n(d['estado']).toInt();
    final f = DateTime.tryParse(_t(d['fecha']));
    final cuando = f == null
        ? ''
        : (_periodo == 'Hoy' || _periodo == 'Ayer')
        ? '${f.hour.toString().padLeft(2, '0')}:${f.minute.toString().padLeft(2, '0')}'
        : '${_dm(f)} ${f.hour.toString().padLeft(2, '0')}:${f.minute.toString().padLeft(2, '0')}';
    final mon = _t(d['moneda']);
    final sim = mon.isEmpty || mon == 'CRC' ? '₡' : '$mon ';
    final total = '${nc ? '−' : ''}$sim${fmt(_n(d['total']))}';
    final cliente = _t(d['cliente']).isEmpty
        ? _t(d['cliente_codigo'])
        : _t(d['cliente']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: () => _abrir(d),
          child: Container(
            padding: const EdgeInsets.fromLTRB(12, 9, 12, 9),
            decoration: BoxDecoration(
              border: Border.all(color: _Fm.borde),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        cliente,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: _Fm.tinta,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      total,
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: estado != 2
                            ? const Color(0xFF9CA3AF)
                            : nc
                            ? const Color(0xFFDC2626)
                            : _Fm.navy1,
                        decoration: estado == 3
                            ? TextDecoration.lineThrough
                            : null,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    _fmEtiqueta(
                      _t(d['tipo_nombre']),
                      nc ? const Color(0xFFFEE2E2) : const Color(0xFFEFF6FF),
                      nc ? const Color(0xFFDC2626) : const Color(0xFF1D4ED8),
                    ),
                    if (estado != 2)
                      _fmEtiqueta(
                        _t(d['estado_nombre']).isEmpty
                            ? 'Estado $estado'
                            : _t(d['estado_nombre']),
                        const Color(0xFFF3F4F6),
                        const Color(0xFF6B7280),
                      ),
                    if (cuando.isNotEmpty)
                      Text(
                        cuando,
                        style: const TextStyle(
                          fontSize: 12.5,
                          color: _Fm.suave,
                        ),
                      ),
                    if (_todas)
                      Text(
                        '· ${_t(d['usuario_nombre'])}',
                        style: const TextStyle(
                          fontSize: 12.5,
                          color: _Fm.suave,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  _t(d['numero']),
                  style: const TextStyle(fontSize: 12, color: _Fm.suave),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
