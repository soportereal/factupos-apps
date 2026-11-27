// FactuMóvil · ÚLTIMAS COMPRAS DEL CLIENTE (components/factumovil/ultimas_compras, foto 5 del dueño en el #3957:
// «Ver últimas compras del cliente» en la pantalla principal vacía).
//
// 🔑 Igual que la web: una tarjeta por artículo con la ÚLTIMA venta al cliente — precio neto, fecha, nivel P, descuento,
//    IVA, existencia — y «Agregar» REPITE ese trato (nivel, precio base y descuento: Documento.repetirTrato). Lo que se
//    agrega sale de la lista.
// 🔑 Las ventas viven en el servidor: esta pantalla necesita conexión (apis/shared/venta/factusuper/ultimas_compras.php,
//    el mismo motor que la web). Sin internet lo dice y nada más; la venta sigue igual.
part of 'caja.dart';

class _UltimasMovil extends StatefulWidget {
  final Documento doc;
  final DatosCaja datos;
  final String llave, cajero;

  /// (historial, cantidad) → (ok, mensaje).
  final Future<(bool, String)> Function(Map<String, dynamic>, String) alRepetir;
  const _UltimasMovil({
    required this.doc,
    required this.datos,
    required this.llave,
    required this.cajero,
    required this.alRepetir,
  });

  @override
  State<_UltimasMovil> createState() => _EstadoUltimasMovil();
}

class _EstadoUltimasMovil extends State<_UltimasMovil> {
  List<Map<String, dynamic>> _arts = [];
  final Map<String, double> _cant = {};
  bool _cargando = true;
  String _error = '';
  bool _agregoAlgo = false;
  Conexion? _con;

  static String _t(Object? v) => '${v ?? ''}'.trim();
  static double _n(Object? v) =>
      v is num ? v.toDouble() : double.tryParse('$v') ?? 0;

  String get _bodegaEst => _t(widget.datos.estacion['bodega']);
  int get _decFrac => int.tryParse(_t(widget.datos.parametros[25])) ?? 2;

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
    setState(() {
      _cargando = true;
      _error = '';
    });
    try {
      final con = _con ??= Conexion(llave: widget.llave, cajero: widget.cajero);
      final j = await con.post(
        '/apis/shared/venta/factusuper/ultimas_compras.php',
        {'cliente': _t(widget.doc.cliente['codigo']), 'bodega': _bodegaEst},
        espera: const Duration(seconds: 15),
      );
      if (!mounted) return;
      final a = j['articulos'];
      setState(() {
        _cargando = false;
        if (j['success'] == true && a is List) {
          _arts = [
            for (final x in a)
              if (x is Map) Map<String, dynamic>.from(x),
          ];
        } else {
          _error = _t(j['error']).isEmpty
              ? 'No se pudieron consultar las últimas compras'
              : _t(j['error']);
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _cargando = false;
        _error =
            'Sin conexión: las últimas compras se consultan en el servidor. La venta sigue igual.';
      });
    }
  }

  bool _frac(Map<String, dynamic> a) => _t(a['Fraccionamiento']) == '1';

  double _redondear(double v, bool frac) {
    if (!frac) return v.roundToDouble();
    final m = math.pow(10, _decFrac).toDouble();
    return (v * m).round() / m;
  }

  double _minCant(bool frac) =>
      frac && _decFrac > 0 ? 1 / math.pow(10, _decFrac) : 1;

  String _txtCant(double v) => v == v.truncateToDouble()
      ? '${v.toInt()}'
      : v.toStringAsFixed(_decFrac).replaceFirst(RegExp(r'0+$'), '');

  void _mover(Map<String, dynamic> a, int delta) {
    final cod = _t(a['ArticuloCodigo']);
    final f = _frac(a);
    var v = _redondear((_cant[cod] ?? 1) + delta, f);
    if (v < _minCant(f)) v = _minCant(f);
    setState(() => _cant[cod] = v);
  }

  Future<void> _agregar(Map<String, dynamic> a) async {
    final cod = _t(a['ArticuloCodigo']);
    final f = _frac(a);
    var c = _redondear(_cant[cod] ?? 1, f);
    if (c < _minCant(f)) c = _minCant(f);
    final (ok, m) = await widget.alRepetir(a, _txtCant(c));
    if (!mounted) return;
    setState(() {
      if (ok) {
        _agregoAlgo = true;
        _arts.remove(a); // ya quedó en la venta → sale de la lista (como la web)
        _cant.remove(cod);
      }
    });
    if (m.isEmpty) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(m),
          backgroundColor: ok
              ? const Color(0xFF047857)
              : const Color(0xFFB91C1C),
          duration: Duration(seconds: ok ? 2 : 4),
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    final cli = widget.doc.cliente;
    final nombre = _t(cli['nombre']);
    return Scaffold(
      backgroundColor: _Fm.fondo,
      appBar: PreferredSize(
        preferredSize: const Size.fromHeight(64),
        child: Container(
          padding: EdgeInsets.fromLTRB(
            12,
            MediaQuery.paddingOf(context).top + 8,
            10,
            8,
          ),
          decoration: const BoxDecoration(
            gradient: LinearGradient(colors: [_Fm.navy1, _Fm.navy2]),
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text(
                      'Últimas compras',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      '${_t(cli['codigo'])} — ${nombre.isEmpty ? 'Cliente' : nombre}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Color(0xFFC7D6EA),
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
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
      body: _cuerpo(),
    );
  }

  Widget _aviso(IconData ico, String t, {bool reintentar = false}) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(ico, size: 56, color: const Color(0x809AB0CB)),
          const SizedBox(height: 10),
          Text(
            t,
            textAlign: TextAlign.center,
            style: const TextStyle(color: _Fm.suave, fontSize: 15),
          ),
          if (reintentar) ...[
            const SizedBox(height: 14),
            OutlinedButton.icon(
              onPressed: _cargar,
              icon: const Icon(Icons.refresh),
              label: const Text('Reintentar'),
            ),
          ],
        ],
      ),
    ),
  );

  Widget _cuerpo() {
    if (_cargando) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error.isNotEmpty) {
      return _aviso(Icons.cloud_off_outlined, _error, reintentar: true);
    }
    if (_arts.isEmpty) {
      return _aviso(
        Icons.history,
        _agregoAlgo
            ? 'Listo: agregó todo lo de la lista'
            : 'Este cliente no tiene compras previas',
      );
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(8, 10, 8, 24),
      children: [for (final a in _arts) _tarjeta(a)],
    );
  }

  Widget _tarjeta(Map<String, dynamic> a) {
    final cod = _t(a['ArticuloCodigo']);
    final cant = _cant[cod] ?? 1;
    final desc = _n(a['Descuento']);
    final stk = _n(a['Stock']);
    final cabys = _t(a['Cabys']);
    final servicio =
        _n(a['NaturalezaCodigo']).toInt() == 2 ||
        (cabys.isNotEmpty && '6789'.contains(cabys[0]));
    final enEquipo = widget.datos.articuloExacto(cod) != null;
    String pct(double v) => fmt(v, v % 1 == 0 ? 0 : 2);
    Widget paso(
      String t,
      Color fondo,
      Color tinta,
      Color linea,
      VoidCallback f,
    ) => Material(
      color: fondo,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: f,
        child: Container(
          width: 42,
          height: 40,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            border: Border.all(color: linea),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            t,
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: tinta,
            ),
          ),
        ),
      ),
    );
    final agregar = Material(
      color: enEquipo ? const Color(0xFF4FB783) : const Color(0xFF9CA3AF),
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: enEquipo ? () => _agregar(a) : null,
        child: const Padding(
          padding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.add, color: Colors.white, size: 20),
              SizedBox(width: 6),
              Text(
                'Agregar',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
        ),
      ),
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: _Fm.borde),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    _t(a['ArticuloNombre']),
                    style: const TextStyle(fontSize: 15, color: _Fm.tinta),
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  '₡${fmt(_n(a['PrecioNeto']))}',
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: _Fm.navy1,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                _fmEtiqueta(
                  cod,
                  const Color(0xFFF1F5F9),
                  const Color(0xFF475569),
                ),
                _fmEtiqueta(
                  _t(a['Fecha']),
                  const Color(0xFFEFF6FF),
                  const Color(0xFF1D4ED8),
                ),
                _fmEtiqueta(
                  'P${_n(a['TipoPrecio']).toInt() > 0 ? _n(a['TipoPrecio']).toInt() : 1}',
                  const Color(0xFFEDE9FE),
                  const Color(0xFF6D28D9),
                ),
                if (desc > 0)
                  _fmEtiqueta(
                    '-${pct(desc)}%',
                    const Color(0xFFFFEDD5),
                    const Color(0xFFC2410C),
                  ),
                _fmEtiqueta(
                  'i${pct(_n(a['Iva']))}%',
                  const Color(0xFFF1F5F9),
                  const Color(0xFF475569),
                ),
                servicio
                    ? _fmEtiqueta(
                        'Servicio',
                        const Color(0xFFE0F2FE),
                        const Color(0xFF0369A1),
                      )
                    : _fmEtiqueta(
                        'Stock ${_txtCant(stk)}',
                        stk <= 0
                            ? const Color(0xFFFEE2E2)
                            : const Color(0xFFDCFCE7),
                        stk <= 0
                            ? const Color(0xFFDC2626)
                            : const Color(0xFF15803D),
                      ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'Base ₡${fmt(_n(a['PrecioUnitario']))}'
              '${desc > 0 ? ' · desc ${pct(desc)}%' : ''}'
              ' · última cant.: ${_txtCant(_n(a['Cantidad']))}',
              style: const TextStyle(fontSize: 12.5, color: _Fm.suave),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                paso(
                  '−',
                  const Color(0xFFF1F5F9),
                  _Fm.tinta,
                  _Fm.borde,
                  () => _mover(a, -1),
                ),
                InkWell(
                  onTap: () async {
                    final t = await pedirTexto(
                      context,
                      'Cantidad',
                      _t(a['ArticuloNombre']),
                      _txtCant(cant),
                    );
                    if (t == null) return;
                    final n = leerMonto(t);
                    if (!n.isNaN && n > 0) {
                      setState(() => _cant[cod] = _redondear(n, _frac(a)));
                    }
                  },
                  child: Container(
                    width: 64,
                    height: 40,
                    margin: const EdgeInsets.symmetric(horizontal: 5),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      border: Border.all(color: _Fm.borde),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      _txtCant(cant),
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ),
                paso(
                  '+',
                  const Color(0xFF1E4A7A),
                  Colors.white,
                  const Color(0xFF1E4A7A),
                  () => _mover(a, 1),
                ),
                const Spacer(),
                enEquipo
                    ? agregar
                    : Tooltip(
                        message:
                            'No está en la copia del equipo (inactivo o sin descargar): refresque los datos',
                        child: agregar,
                      ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
