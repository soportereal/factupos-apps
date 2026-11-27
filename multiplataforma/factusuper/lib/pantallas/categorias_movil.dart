// FactuMóvil · CATEGORÍAS (components/factumovil/categorias, foto 7 del dueño en el #3957:
// «Categorías › *AUTOMOTRIZ › PARQUEO» con el árbol, los conteos, «Stock 0», − cantidad + y «+ Agregar»).
//
// 🔑 Igual que la web: árbol en acordeón categoría › subcategoría › artículos, todo queda a la vista y cada rama se
//    puede cerrar; la ruta de lo que se está viendo va arriba y «Regresar» a la DERECHA. Si una categoría no tiene
//    subcategorías, sus artículos cuelgan directo de ella.
// 🔑 A diferencia de la web, el árbol se arma con la COPIA del equipo (categoría y subcategoría vienen en la descarga
//    de artículos): funciona sin internet. La existencia no se guarda en el equipo: se pide al servidor
//    (articulo_stock.php) solo de la rama que se abre, y si no hay conexión no se muestra.
part of 'caja.dart';

class _CategoriasMovil extends StatefulWidget {
  final Documento doc;
  final DatosCaja datos;
  final String llave, cajero;
  final Future<String> Function(Map<String, dynamic>, String, String, int)
  alAgregar;
  const _CategoriasMovil({
    required this.doc,
    required this.datos,
    required this.llave,
    required this.cajero,
    required this.alAgregar,
  });

  @override
  State<_CategoriasMovil> createState() => _EstadoCategoriasMovil();
}

class _RamaCat {
  final String nombre;
  final Map<String, List<Map<String, dynamic>>> subs;
  final List<Map<String, dynamic>> directos;
  _RamaCat(this.nombre, this.subs, this.directos);
}

class _EstadoCategoriasMovil extends State<_CategoriasMovil> {
  late final List<_RamaCat> _arbol = _armar(widget.datos.articulos);
  final Set<String> _catAbierta = {}, _subAbierta = {};
  String _focoCat = '', _focoSub = '';
  final Map<String, double> _cant = {};
  final Map<String, double> _stock = {};
  final Set<String> _pedidos = {};
  Conexion? _con;

  Documento get doc => widget.doc;
  String get _bodegaEst => '${widget.datos.estacion['bodega'] ?? ''}'.trim();

  /// Param 25: decimales de cantidad de los fraccionados (la web: DECIMALES_CANTIDAD, 2 si no está).
  int get _decFrac =>
      int.tryParse('${widget.datos.parametros[25] ?? ''}'.trim()) ?? 2;

  static String _t(Object? v) => '${v ?? ''}'.trim();

  /// Orden sin distinguir mayúsculas (como el ORDER BY de SQL Server).
  static int _orden(String a, String b) =>
      a.toUpperCase().compareTo(b.toUpperCase());

  /// Como categoria_arbol.php: solo artículos con categoría; categorías y subcategorías en orden alfabético, artículos
  /// por nombre. Si la categoría tiene ALGUNA subcategoría, se muestra por subcategorías (los sin subcategoría no
  /// salen, igual que en la web); si no tiene ninguna, sus artículos cuelgan directo de ella.
  static List<_RamaCat> _armar(List<Map<String, dynamic>> articulos) {
    final porCat = <String, Map<String, List<Map<String, dynamic>>>>{};
    final sinSub = <String, List<Map<String, dynamic>>>{};
    for (final a in articulos) {
      final c = _t(a['categoria']);
      if (c.isEmpty) continue;
      final s = _t(a['subcategoria']);
      porCat.putIfAbsent(c, () => {});
      if (s.isEmpty) {
        (sinSub[c] ??= []).add(a);
      } else {
        (porCat[c]![s] ??= []).add(a);
      }
    }
    int porNombre(Map<String, dynamic> x, Map<String, dynamic> y) =>
        _orden(_t(x['nombre']), _t(y['nombre']));
    final cats = porCat.keys.toList()..sort(_orden);
    return [
      for (final c in cats)
        _RamaCat(
          c,
          {
            for (final s in (porCat[c]!.keys.toList()..sort(_orden)))
              s: porCat[c]![s]!..sort(porNombre),
          },
          porCat[c]!.isEmpty ? ((sinSub[c] ?? [])..sort(porNombre)) : const [],
        ),
    ];
  }

  @override
  void dispose() {
    _con?.cerrar();
    super.dispose();
  }

  /// Pide la existencia de los artículos de la rama que se abrió (los que todavía no se pidieron).
  Future<void> _pedirStock(List<Map<String, dynamic>> arts) async {
    final faltan = [
      for (final a in arts)
        if (!_pedidos.contains(_t(a['codigo']))) _t(a['codigo']),
    ];
    if (faltan.isEmpty) return;
    _pedidos.addAll(faltan);
    final con = _con ??= Conexion(llave: widget.llave, cajero: widget.cajero);
    for (var i = 0; i < faltan.length; i += 500) {
      try {
        final j = await con.post(
          '/apis/shared/venta/factusuper/articulo_stock.php',
          {'codigos': faltan.sublist(i, (i + 500).clamp(0, faltan.length))},
          espera: const Duration(seconds: 8),
        );
        final s = j['stock'];
        if (j['success'] == true && s is Map && mounted) {
          setState(() {
            s.forEach((k, v) {
              final n = v is num ? v.toDouble() : double.tryParse('$v');
              if (n != null) _stock['$k'] = n;
            });
          });
        }
      } catch (_) {
        // Sin conexión: la existencia no se muestra (el árbol sigue sirviendo).
        _pedidos.removeAll(faltan);
        return;
      }
    }
  }

  void _abrirCat(_RamaCat c) {
    setState(() {
      if (_catAbierta.remove(c.nombre)) return;
      _catAbierta.add(c.nombre);
      _focoCat = c.nombre;
      _focoSub = '';
    });
    if (_catAbierta.contains(c.nombre) && c.subs.isEmpty)
      _pedirStock(c.directos);
  }

  void _abrirSub(_RamaCat c, String s) {
    final k = '${c.nombre}\u0000$s';
    setState(() {
      if (_subAbierta.remove(k)) return;
      _subAbierta.add(k);
      _focoCat = c.nombre;
      _focoSub = s;
    });
    if (_subAbierta.contains(k)) _pedirStock(c.subs[s]!);
  }

  String get _ruta {
    final p = ['Categorías'];
    if (_focoCat.isNotEmpty && _catAbierta.contains(_focoCat)) {
      p.add(_focoCat);
      if (_focoSub.isNotEmpty &&
          _subAbierta.contains('$_focoCat\u0000$_focoSub')) {
        p.add(_focoSub);
      }
    }
    return p.join(' › ');
  }

  bool _frac(Map<String, dynamic> a) => _t(a['fraccionable']) == '1';

  double _redondear(double v, bool frac) {
    if (!frac) return v.roundToDouble();
    final m = math.pow(10, _decFrac).toDouble();
    return (v * m).round() / m;
  }

  double _minCant(bool frac) =>
      frac && _decFrac > 0 ? 1 / math.pow(10, _decFrac) : 1;

  void _mover(Map<String, dynamic> a, int delta) {
    final cod = _t(a['codigo']);
    final f = _frac(a);
    var v = _redondear((_cant[cod] ?? 1) + delta, f);
    if (v < _minCant(f)) v = _minCant(f);
    setState(() => _cant[cod] = v);
  }

  String _txtCant(double v) => v == v.truncateToDouble()
      ? '${v.toInt()}'
      : v.toStringAsFixed(_decFrac).replaceFirst(RegExp(r'0+$'), '');

  Future<void> _agregar(Map<String, dynamic> a) async {
    final cod = _t(a['codigo']);
    final f = _frac(a);
    var c = _redondear(_cant[cod] ?? 1, f);
    if (c < _minCant(f)) c = _minCant(f);
    final m = await widget.alAgregar(
      a,
      _txtCant(c),
      _bodegaEst,
      doc.nivelActual(),
    );
    if (!mounted) return;
    setState(() => _cant.remove(cod));
    if (m.isNotEmpty) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(
          SnackBar(
            content: Text(m),
            backgroundColor: const Color(0xFF047857),
            duration: const Duration(seconds: 2),
          ),
        );
    }
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
              Expanded(
                child: Text(
                  _ruta,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: Colors.white,
                    height: 1.15,
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
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
      body: _arbol.isEmpty
          ? const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Sin categorías.\nLos artículos de esta empresa no tienen categoría asignada.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: _Fm.suave),
                ),
              ),
            )
          : ListView(
              padding: const EdgeInsets.fromLTRB(8, 10, 8, 24),
              children: [for (final c in _arbol) ..._rama(c)],
            ),
    );
  }

  List<Widget> _rama(_RamaCat c) {
    final abierta = _catAbierta.contains(c.nombre);
    final w = <Widget>[
      _nodo(
        abierta: abierta,
        icono: abierta ? Icons.folder_open_outlined : Icons.folder_outlined,
        colorIcono: const Color(0xFFF59E0B),
        texto: c.nombre,
        cuenta: c.subs.isNotEmpty ? c.subs.length : c.directos.length,
        borde: const Color(0xFF4F7FD9),
        fondoAbierto: const Color(0xFFF0F5FF),
        sangria: 0,
        onTap: () => _abrirCat(c),
      ),
    ];
    if (!abierta) return w;
    if (c.subs.isEmpty) {
      if (c.directos.isEmpty) w.add(_vacio(18));
      for (final a in c.directos) {
        w.add(_articulo(a, 18));
      }
      return w;
    }
    c.subs.forEach((s, arts) {
      final k = '${c.nombre}\u0000$s';
      final sa = _subAbierta.contains(k);
      w.add(
        _nodo(
          abierta: sa,
          icono: Icons.sell_outlined,
          colorIcono: const Color(0xFF0D9488),
          texto: s,
          cuenta: arts.length,
          borde: const Color(0xFF2DB3A0),
          fondoAbierto: const Color(0xFFF0FBF8),
          sangria: 18,
          onTap: () => _abrirSub(c, s),
        ),
      );
      if (sa) {
        for (final a in arts) {
          w.add(_articulo(a, 34));
        }
      }
    });
    return w;
  }

  Widget _vacio(double sangria) => Padding(
    padding: EdgeInsets.fromLTRB(sangria + 12, 4, 0, 10),
    child: const Text('Sin artículos', style: TextStyle(color: _Fm.suave)),
  );

  Widget _nodo({
    required bool abierta,
    required IconData icono,
    required Color colorIcono,
    required String texto,
    required int cuenta,
    required Color borde,
    required Color fondoAbierto,
    required double sangria,
    required VoidCallback onTap,
  }) => Padding(
    padding: EdgeInsets.only(left: sangria, bottom: 6),
    child: Material(
      color: abierta ? fondoAbierto : const Color(0xFFF8FAFD),
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
          decoration: BoxDecoration(
            border: Border.all(
              color: abierta ? borde : _Fm.borde,
              width: abierta ? 1.4 : 1,
            ),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              Icon(
                abierta ? Icons.expand_more : Icons.chevron_right,
                size: 20,
                color: const Color(0xFF94A3B8),
              ),
              const SizedBox(width: 6),
              Icon(icono, size: 20, color: colorIcono),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  texto,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: _Fm.tinta,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: const Color(0xFFEEF2F7),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  '$cuenta',
                  style: const TextStyle(fontSize: 12.5, color: _Fm.suave),
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget _articulo(Map<String, dynamic> a, double sangria) {
    final cod = _t(a['codigo']);
    final cant = _cant[cod] ?? 1;
    final stk = _stock[cod];
    final precio = doc.precioPara(cod, doc.nivelActual());
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
      color: precio == null ? const Color(0xFF9CA3AF) : const Color(0xFF4FB783),
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: precio == null ? null : () => _agregar(a),
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
      padding: EdgeInsets.only(left: sangria, bottom: 6),
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
            Text(
              _t(a['nombre']),
              style: const TextStyle(fontSize: 15, color: _Fm.tinta),
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
                if (stk != null)
                  _fmEtiqueta(
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
                      _t(a['nombre']),
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
                precio == null
                    ? Tooltip(message: 'Sin precio', child: agregar)
                    : agregar,
              ],
            ),
          ],
        ),
      ),
    );
  }
}
