// FactuMóvil / FactuSuper — NOTA DE CRÉDITO / DÉBITO (normal y financiera) desde el DETALLE de la venta (#3957, dueño
// 26-nov: «al ver detalle la factura tiene que hacer todas estas opciones: nota crédito, nota débito…»).
// Réplica de VE-020 móvil de la web (modules/ventas/notas/nota_dc_movil.php + js/nota_dc_movil.js):
//   artículos de la factura (con su DISPONIBLE descontando notas anteriores y el borrador) · barra Todo/Precio/Desc/Cant/
//   Agregar · artículos de la nota · motivo de referencia (Hacienda) + motivo interno + detalle · totales · Aplicar.
// La financiera usa SOLO el artículo NCF/NDF (monto + cantidad + tarifa IVA, exento por defecto), como el escritorio (#3112).
// Todo pasa por apis/shared/venta/factusuper/nota_paso.php, que corre los MISMOS archivos de la web (la lógica es la de
// la web; acá solo cambia la cara). Aplicar abre _NotaProceso (los 11 pasos de MNC-001).
part of 'caja.dart';

double _nn(Object? x) =>
    x is num ? x.toDouble() : (double.tryParse('${x ?? ''}'.trim()) ?? 0);
double _r3(double n) => (n * 1000).roundToDouble() / 1000;

/// leerMonto da NaN con el campo vacío (y jsonEncode revienta con NaN): acá vale el valor por defecto.
double _lm(TextEditingController c, double porDefecto) {
  final v = leerMonto(c.text);
  return v.isNaN ? porDefecto : v;
}

String _cant(double n) =>
    n == n.truncateToDouble() ? '${n.toInt()}' : _r3(n).toString();

class _NotaMovil extends StatefulWidget {
  final String llave, cajero;
  final String tipo; // '03' NC · '02' ND
  final bool financiera;
  final String factura, cliente;
  const _NotaMovil({
    required this.llave,
    required this.cajero,
    required this.tipo,
    required this.financiera,
    this.factura = '',
    this.cliente = '',
  });
  @override
  State<_NotaMovil> createState() => _EstadoNotaMovil();
}

class _EstadoNotaMovil extends State<_NotaMovil> {
  late final Conexion con = Conexion(
    llave: widget.llave,
    cajero: widget.cajero,
  );
  bool cargando = true, ocupado = false;
  String error = '';
  Map<String, dynamic> prep = const {};
  String? documento;
  List<Map> artsFactura = [], artsNota = [];
  Map totales = const {};
  int? sel;
  final precio = TextEditingController(),
      desc = TextEditingController(text: '0'),
      cant = TextEditingController(text: '1'),
      detalle = TextEditingController();
  String motivoRef = '', motivoInt = '', tarifaFin = '10';

  bool get esNC => widget.tipo == '03';
  String get tipoNombre => esNC ? 'Nota de Crédito' : 'Nota de Débito';
  Map get factura => (prep['factura'] as Map?) ?? const {};
  Map? get artFin => prep['articulo_financiero'] as Map?;
  bool get puedeAplicar => prep['puede_aplicar'] == true;

  @override
  void initState() {
    super.initState();
    detalle.text = widget.financiera
        ? (esNC ? 'Nota de crédito financiera' : 'Nota de débito financiera')
        : 'Devolución de mercadería';
    _cargar();
  }

  @override
  void dispose() {
    con.cerrar();
    for (final c in [precio, desc, cant, detalle]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<Map<String, dynamic>> _paso(String paso, Map<String, dynamic> body) =>
      con.post('nota_paso.php?paso=$paso', body);

  void _msg(String t, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(content: Text(t), backgroundColor: error ? Marca.rojo : null),
      );
  }

  String _err(Object e) => e is ErrorConexion ? e.mensaje : '$e';

  Future<void> _cargar() async {
    try {
      final p = await _paso('preparar', {
        'factura': widget.factura,
        'tipo': widget.tipo,
        'financiera': widget.financiera,
        'cliente': widget.cliente,
      });
      if (p['success'] != true) throw '${p['error'] ?? 'No se pudo abrir'}';
      prep = p;
      artsFactura = [
        for (final a in (p['articulos'] as List?) ?? const [])
          if (a is Map) a,
      ];
      final refs = (p['motivos_referencia'] as List?) ?? const [];
      final ints = (p['motivos_internos'] as List?) ?? const [];
      motivoRef = '${p['tipo_ref_default'] ?? ''}';
      if (!refs.any((m) => '${(m as Map)['Codigo']}' == motivoRef)) {
        motivoRef = refs.isEmpty ? '01' : '${(refs.first as Map)['Codigo']}';
      }
      motivoInt = ints.any((m) => '${(m as Map)['Codigo']}' == '02')
          ? '02'
          : (ints.isEmpty ? '' : '${(ints.first as Map)['Codigo']}');
      final ini = await _paso('iniciar', {
        'factura': widget.financiera ? '' : widget.factura,
        'tipo': widget.tipo,
        'cliente': widget.financiera
            ? widget.cliente
            : '${factura['ClienteId'] ?? ''}',
        'financiera': widget.financiera,
      });
      if (ini['success'] != true)
        throw '${ini['error'] ?? 'No se pudo iniciar la nota'}';
      documento = '${ini['documento']}';
      if (ini['recuperado'] == true &&
          ((ini['articulos'] as List?) ?? const []).isNotEmpty) {
        _tomar(ini);
        WidgetsBinding.instance.addPostFrameCallback(
          (_) => _msg(
            'Se recuperó la nota que había quedado a medias, con ${artsNota.length} artículo(s)',
          ),
        );
      }
    } catch (e) {
      error = _err(e);
    }
    if (mounted) setState(() => cargando = false);
  }

  void _tomar(Map j) {
    artsNota = [
      for (final a in (j['articulos'] as List?) ?? const [])
        if (a is Map) a,
    ];
    totales = (j['totales'] as Map?) ?? const {};
  }

  // ── DISPONIBLE EN VIVO (#1142): lo de PHP solo descuenta notas YA aplicadas; acá se resta también el borrador ──
  double _enNotaDeLinea(Map art) {
    final id = _nn(art['ArticuloLineaId']).toInt();
    var s = 0.0;
    for (final l in artsNota) {
      final nl = _nn(l['NumeroLinea']).toInt();
      if (id > 0 && nl > 0) {
        if (nl == id) s += _nn(l['ArticuloCantidad']);
      } else if ('${l['ArticuloCodigo']}' == '${art['ArticuloCodigo']}') {
        s += _nn(l['ArticuloCantidad']);
      }
    }
    return _r3(s);
  }

  double _disp(Map art) {
    final restLinea =
        _nn(art['ArticuloCantidadDisponible']) - _enNotaDeLinea(art);
    var dispCod = 0.0, enNotaCod = 0.0;
    for (final a in artsFactura) {
      if ('${a['ArticuloCodigo']}' == '${art['ArticuloCodigo']}') {
        dispCod += _nn(a['ArticuloCantidadDisponible']);
      }
    }
    for (final l in artsNota) {
      if ('${l['ArticuloCodigo']}' == '${art['ArticuloCodigo']}') {
        enNotaCod += _nn(l['ArticuloCantidad']);
      }
    }
    final r = restLinea < dispCod - enNotaCod ? restLinea : dispCod - enNotaCod;
    return _r3(r < 0 ? 0 : r);
  }

  void _seleccionar(int i) {
    final art = artsFactura[i];
    final rest = _disp(art);
    if (rest <= 0) {
      _msg(
        _enNotaDeLinea(art) > 0
            ? 'Ya está en la nota. Para cambiarla, quítela de abajo.'
            : 'Ya fue acreditada por una nota anterior',
      );
      return;
    }
    setState(() {
      sel = i;
      precio.text = _nn(art['ArticuloPrecio']).toStringAsFixed(4);
      desc.text = _nn(art['ArticuloDescuentoPorcentage']).toStringAsFixed(2);
      cant.text = _cant(rest); // #626: arranca en lo disponible
    });
  }

  Future<void> _agregar() async {
    if (documento == null || ocupado) return;
    final Map<String, dynamic> articulo;
    if (widget.financiera) {
      final af = artFin;
      if (af == null) return;
      final p = _lm(precio, 0);
      final c = _lm(cant, 1).truncate();
      if (p <= 0) return _msg('El monto debe ser mayor a 0', error: true);
      if (c <= 0) return _msg('La cantidad debe ser mayor a 0', error: true);
      articulo = {
        'codigo': '${af['codigo']}',
        'cantidad': c,
        'precio': p,
        'iva_tarifa': tarifaFin,
      };
    } else {
      final i = sel;
      if (i == null) return _msg('Seleccione un artículo', error: true);
      final art = artsFactura[i];
      articulo = {
        'codigo': '${art['ArticuloCodigo']}',
        'cantidad': _lm(cant, 1),
        'precio': _lm(precio, 0),
        'descuento': _lm(desc, 0),
        'linea_id': _nn(art['ArticuloLineaId']).toInt(),
      };
    }
    setState(() => ocupado = true);
    try {
      final j = await _paso('agregar', {
        'documento': documento,
        'articulo': articulo,
        if (!widget.financiera) 'factura_origen': widget.factura,
      });
      if (j['success'] != true) {
        _msg('${j['error'] ?? 'No se pudo agregar'}', error: true);
      } else {
        _tomar(j);
        sel = null;
        if (widget.financiera) {
          precio.text = '';
          cant.text = '1';
          tarifaFin = '10';
        }
      }
    } catch (e) {
      _msg(_err(e), error: true);
    }
    if (mounted) setState(() => ocupado = false);
  }

  Future<void> _todo() async {
    if (documento == null || ocupado) return;
    setState(() => ocupado = true);
    var agregados = 0, yaEnNota = 0;
    String primerError = '';
    for (final art in List<Map>.of(artsFactura)) {
      final d = _disp(art);
      if (d <= 0) {
        if (_enNotaDeLinea(art) > 0) yaEnNota++;
        continue;
      }
      try {
        final j = await _paso('agregar', {
          'documento': documento,
          'articulo': {
            'codigo': '${art['ArticuloCodigo']}',
            'cantidad': d,
            'descuento': _nn(art['ArticuloDescuentoPorcentage']),
            'linea_id': _nn(art['ArticuloLineaId']).toInt(),
          },
          'factura_origen': widget.factura,
        });
        if (j['success'] == true) {
          _tomar(j);
          agregados++;
        } else if (primerError.isEmpty) {
          primerError = '${j['error'] ?? ''}';
        }
      } catch (e) {
        if (primerError.isEmpty) primerError = _err(e);
      }
      if (mounted) setState(() {});
    }
    if (!mounted) return;
    setState(() => ocupado = false);
    if (agregados > 0) {
      _msg('$agregados artículo(s) agregado(s)');
    } else if (yaEnNota > 0) {
      _msg('Ya está todo en la nota. Solo falta Aplicar.');
    } else if (primerError.isNotEmpty) {
      _msg(primerError, error: true);
    } else {
      _msg('No hay artículos con cantidad disponible', error: true);
    }
  }

  Future<void> _quitar(Map l) async {
    if (documento == null || ocupado) return;
    setState(() => ocupado = true);
    try {
      final j = await _paso('quitar', {
        'documento': documento,
        'linea_id': _nn(l['ArticuloLineaId']).toInt(),
        'articulo_codigo': '${l['ArticuloCodigo']}',
      });
      if (j['success'] == true) {
        _tomar(j);
      } else {
        _msg('${j['error'] ?? 'No se pudo quitar'}', error: true);
      }
    } catch (e) {
      _msg(_err(e), error: true);
    }
    if (mounted) setState(() => ocupado = false);
  }

  Future<void> _aplicar() async {
    if (documento == null || artsNota.isEmpty || !puedeAplicar) return;
    final det = detalle.text.trim();
    if (det.isEmpty) return _msg('Ingrese un detalle', error: true);
    final numero = await Navigator.of(context).push<String>(
      MaterialPageRoute(
        builder: (_) => _NotaProceso(
          llave: widget.llave,
          cajero: widget.cajero,
          tipo: widget.tipo,
          documento: documento!,
          detalle: det,
          motivoRef: motivoRef,
          motivoInt: motivoInt,
          factura: widget.financiera ? '' : widget.factura,
          cliente: '${factura['ClienteNombre'] ?? widget.cliente}',
          total: _nn(totales['total']),
        ),
      ),
    );
    if (numero != null && mounted) Navigator.pop(context, numero);
  }

  // ── Vista ──────────────────────────────────────────────────────────────────────────────────────────────────────────

  Future<void> _verAvisos() => showDialog<void>(
    context: context,
    builder: (c) => AlertDialog(
      title: const Text('Avisos de esta factura'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (final a in (prep['avisos'] as List?) ?? const [])
            if (a is Map)
              Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: a['clase'] == 'alerta'
                      ? const Color(0xFFFEF3C7)
                      : const Color(0xFFE0F2FE),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text('${a['texto']}'),
              ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(c),
          child: const Text('Entendido'),
        ),
      ],
    ),
  );

  Widget _cabeza() {
    final avisos = ((prep['avisos'] as List?) ?? const []).length;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 12, 12, 12),
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
                  widget.financiera ? 'FINANCIERA' : 'MANUAL · VE-020',
                  style: const TextStyle(
                    color: Colors.white70,
                    letterSpacing: 0.8,
                  ),
                ),
                Text(
                  tipoNombre,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
          ),
          if (avisos > 0)
            Badge(
              label: Text('$avisos'),
              backgroundColor: const Color(0xFFF59E0B),
              child: IconButton(
                tooltip: 'Avisos de esta factura',
                onPressed: _verAvisos,
                icon: const Icon(
                  Icons.notifications_active,
                  color: Colors.white,
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _info() {
    final num = '${factura['Numero'] ?? ''}';
    return Container(
      color: const Color(0xFFE6EEF8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: Wrap(
        spacing: 14,
        runSpacing: 4,
        children: [
          if (!widget.financiera && num.length >= 8)
            Text.rich(
              TextSpan(
                text: 'Origen: ',
                children: [
                  TextSpan(
                    text: num.substring(num.length - 8),
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                ],
              ),
            ),
          Text.rich(
            TextSpan(
              text: 'Cliente: ',
              children: [
                TextSpan(
                  text:
                      '${factura['ClienteId'] ?? ''} - ${factura['ClienteNombre'] ?? ''}',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ],
            ),
          ),
          Text('${factura['MonedaCodigo'] ?? 'CRC'}'),
        ],
      ),
    );
  }

  Widget _titulo(IconData ico, String t, int n, {Color color = _Fm.navy1}) =>
      Padding(
        padding: const EdgeInsets.fromLTRB(14, 14, 14, 6),
        child: Row(
          children: [
            Icon(ico, color: color, size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                t,
                style: TextStyle(fontWeight: FontWeight.w800, color: color),
              ),
            ),
            _fmEtiqueta('$n', color, Colors.white),
          ],
        ),
      );

  Widget _tarjetaFactura(int i) {
    final a = artsFactura[i];
    final rest = _disp(a);
    final enNota = _enNotaDeLinea(a);
    final notas = [
      for (final n in (a['NotasAplicadas'] as List?) ?? const [])
        if (n is Map) n,
    ];
    final elegida = sel == i;
    return Opacity(
      opacity: rest <= 0 ? 0.55 : 1,
      child: Card(
        margin: const EdgeInsets.fromLTRB(10, 0, 10, 8),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: BorderSide(
            color: elegida ? _Fm.acento : _Fm.borde,
            width: elegida ? 2 : 1,
          ),
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => _seleccionar(i),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '${a['ArticuloCodigo']}',
                        style: const TextStyle(
                          color: _Fm.suave,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    _fmEtiqueta(
                      'Disp: ${_cant(rest)}',
                      rest > 0
                          ? const Color(0xFFDCFCE7)
                          : const Color(0xFFFEE2E2),
                      rest > 0
                          ? const Color(0xFF15803D)
                          : const Color(0xFFB91C1C),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  '${a['ArticuloNombre']}',
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    color: _Fm.tinta,
                  ),
                ),
                Text(
                  'Cant: ${_cant(_nn(a['ArticuloCantidad']))} × ${fmt(_nn(a['ArticuloPrecio']), 4)} = ${fmt(_nn(a['ArticuloTotal']))}',
                  style: const TextStyle(color: _Fm.suave),
                ),
                if (notas.isNotEmpty)
                  Container(
                    margin: const EdgeInsets.only(top: 6),
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFEF3C7),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          rest <= 0
                              ? 'Sin disponible. Notas aplicadas:'
                              : 'Notas aplicadas:',
                          style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 12,
                          ),
                        ),
                        for (final n in notas)
                          Text(
                            '${n['tipo']} ${n['numero']} · ${_cant(_nn(n['cantidad']))} ud'
                            '${'${n['fecha'] ?? ''}'.isEmpty ? '' : ' · ${n['fecha']}'}',
                            style: const TextStyle(fontSize: 12),
                          ),
                      ],
                    ),
                  ),
                if (enNota > 0)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      'Ya está en esta nota: ${_cant(enNota)} ud${rest > 0 ? ' · quedan ${_cant(rest)}' : ' (completa)'}',
                      style: const TextStyle(
                        color: _Fm.acento,
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _campo(String etiqueta, TextEditingController c, [double? ancho]) =>
      SizedBox(
        width: ancho,
        child: TextField(
          controller: c,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: InputDecoration(
            labelText: etiqueta,
            isDense: true,
            filled: true,
            fillColor: Colors.white,
            border: const OutlineInputBorder(),
          ),
        ),
      );

  Widget _barraAgregar() {
    final agregar = FilledButton.icon(
      onPressed: ocupado || documento == null ? null : _agregar,
      icon: const Icon(Icons.arrow_downward),
      label: const Text('Agregar'),
    );
    if (widget.financiera) {
      final af = artFin;
      if (af == null) {
        return Padding(
          padding: const EdgeInsets.all(14),
          child: Text(
            'Falta crear el artículo ${esNC ? 'NCF' : 'NDF'} en el catálogo: la nota financiera solo acepta ese artículo.',
            style: const TextStyle(color: Marca.rojo),
          ),
        );
      }
      final tarifas = [
        for (final t in (prep['tarifas_iva'] as List?) ?? const [])
          if (t is Map) t,
      ];
      return Container(
        margin: const EdgeInsets.fromLTRB(10, 10, 10, 0),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: _Fm.borde),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              '${af['codigo']} · ${af['nombre']}',
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(child: _campo('Monto', precio)),
                const SizedBox(width: 8),
                _campo('Cant', cant, 70),
              ],
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: tarifas.any((t) => '${t['codigo']}' == tarifaFin)
                  ? tarifaFin
                  : null,
              isExpanded: true,
              style: Theme.of(context).textTheme.bodyMedium,
              decoration: const InputDecoration(
                labelText: 'IVA',
                isDense: true,
                border: OutlineInputBorder(),
              ),
              items: [
                for (final t in tarifas)
                  DropdownMenuItem(
                    value: '${t['codigo']}',
                    child: Text(
                      '${t['codigo']} · ${_nn(t['porcentaje']) == 0 ? 'Sin IVA' : '${_nn(t['porcentaje'])}%'}'
                      '${'${t['nombre'] ?? ''}'.isEmpty ? '' : ' · ${t['nombre']}'}',
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              ],
              onChanged: (v) => setState(() => tarifaFin = v ?? '10'),
            ),
            const SizedBox(height: 8),
            agregar,
          ],
        ),
      );
    }
    return Container(
      margin: const EdgeInsets.fromLTRB(10, 4, 10, 0),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Fm.borde),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(child: _campo('Precio', precio)),
              const SizedBox(width: 6),
              _campo('Desc', desc, 80),
              const SizedBox(width: 6),
              _campo('Cant', cant, 74),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: ocupado || documento == null ? null : _todo,
                  icon: const Icon(Icons.add_circle_outline),
                  label: const Text('Todo'),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(child: agregar),
            ],
          ),
        ],
      ),
    );
  }

  Widget _tarjetaNota(Map a) {
    final d = _nn(a['ArticuloDescuentoPorcentage']);
    final iva = _nn(a['ArticuloIvaTarifa']);
    return Card(
      margin: const EdgeInsets.fromLTRB(10, 0, 10, 8),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: const BorderSide(color: Color(0xFFFCA5A5)),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 6, 4, 10),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${a['ArticuloCodigo']}',
                    style: const TextStyle(color: _Fm.suave),
                  ),
                  Text(
                    '${a['ArticuloNombre'] ?? a['ArticuloCodigo']}',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  Wrap(
                    spacing: 8,
                    children: [
                      Text(
                        '${_cant(_nn(a['ArticuloCantidad']))} × ${fmt(_nn(a['ArticuloPrecio']), 4)}',
                      ),
                      if (d > 0)
                        Text(
                          '-${(d * 100).round() / 100}%',
                          style: const TextStyle(color: Marca.rojo),
                        ),
                      if (iva > 0)
                        Text(
                          'IVA ${iva % 1 == 0 ? iva.toInt() : iva}%: ${fmt(_nn(a['ArticuloIvaMonto']))}',
                        ),
                    ],
                  ),
                ],
              ),
            ),
            Text(
              fmt(_nn(a['ArticuloTotal'])),
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
            ),
            IconButton(
              tooltip: 'Quitar de la nota',
              onPressed: ocupado ? null : () => _quitar(a),
              icon: const Icon(Icons.cancel_outlined, color: Marca.rojo),
            ),
          ],
        ),
      ),
    );
  }

  Widget _pie() {
    final refs = [
      for (final m in (prep['motivos_referencia'] as List?) ?? const [])
        if (m is Map) m,
    ];
    final ints = [
      for (final m in (prep['motivos_internos'] as List?) ?? const [])
        if (m is Map) m,
    ];
    final estilo = Theme.of(context).textTheme.bodyMedium;
    DropdownButtonFormField<String> combo(
      String etiqueta,
      List<Map> lista,
      String valor,
      ValueChanged<String> alCambiar,
    ) => DropdownButtonFormField<String>(
      initialValue: lista.any((m) => '${m['Codigo']}' == valor) ? valor : null,
      isExpanded: true,
      style: estilo,
      decoration: InputDecoration(
        labelText: etiqueta,
        isDense: true,
        border: const OutlineInputBorder(),
      ),
      items: [
        for (final m in lista)
          DropdownMenuItem(
            value: '${m['Codigo']}',
            child: Text(
              '${m['Codigo']} - ${m['Descripcion']}',
              overflow: TextOverflow.ellipsis,
            ),
          ),
      ],
      onChanged: (v) => setState(() => alCambiar(v ?? '')),
    );
    final aplicar = FilledButton.icon(
      style: FilledButton.styleFrom(
        backgroundColor: const Color(0xFF16A34A),
        minimumSize: const Size(130, 52),
      ),
      onPressed: puedeAplicar && artsNota.isNotEmpty && !ocupado
          ? _aplicar
          : null,
      icon: const Icon(Icons.check),
      label: const Text(
        'Aplicar',
        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
      ),
    );
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      decoration: const BoxDecoration(
        color: Colors.white,
        boxShadow: [BoxShadow(color: Color(0x22000000), blurRadius: 8)],
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: combo(
                    'Motivo (Hacienda)',
                    refs,
                    motivoRef,
                    (v) => motivoRef = v,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: combo(
                    'Motivo interno',
                    ints,
                    motivoInt,
                    (v) => motivoInt = v,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            TextField(
              controller: detalle,
              decoration: const InputDecoration(
                labelText: 'Detalle de la nota',
                isDense: true,
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Grav: ${fmt(_nn(totales['merc_gravada']))} · IVA: ${fmt(_nn(totales['iva']))}',
                        style: const TextStyle(color: _Fm.suave),
                      ),
                      Text(
                        'Total: ${fmt(_nn(totales['total']))}',
                        style: const TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w800,
                          color: _Fm.tinta,
                        ),
                      ),
                    ],
                  ),
                ),
                puedeAplicar
                    ? aplicar
                    : Tooltip(
                        message:
                            'Sin permiso (${prep['permiso'] ?? ''}) para aplicar $tipoNombre ${widget.financiera ? 'Financiera' : 'Manual'}',
                        child: aplicar,
                      ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    Widget cuerpo;
    if (cargando) {
      cuerpo = const Center(child: CircularProgressIndicator());
    } else if (error.isNotEmpty) {
      cuerpo = Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, color: Marca.rojo, size: 40),
              const SizedBox(height: 10),
              Text(error, textAlign: TextAlign.center),
              const SizedBox(height: 14),
              FilledButton(
                onPressed: () {
                  setState(() {
                    error = '';
                    cargando = true;
                  });
                  _cargar();
                },
                child: const Text('Reintentar'),
              ),
            ],
          ),
        ),
      );
    } else {
      cuerpo = Column(
        children: [
          _info(),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.only(bottom: 12),
              children: [
                if (!widget.financiera) ...[
                  _titulo(
                    Icons.receipt_long,
                    'Artículos Factura',
                    artsFactura.length,
                  ),
                  for (var i = 0; i < artsFactura.length; i++)
                    _tarjetaFactura(i),
                ],
                _barraAgregar(),
                _titulo(
                  Icons.difference_outlined,
                  'Artículos de la Nota',
                  artsNota.length,
                  color: const Color(0xFFC53030),
                ),
                if (artsNota.isEmpty)
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      widget.financiera
                          ? 'Escriba el monto y toque Agregar'
                          : 'Seleccione artículos de la factura',
                      textAlign: TextAlign.center,
                      style: const TextStyle(color: _Fm.suave),
                    ),
                  ),
                for (final a in artsNota) _tarjetaNota(a),
                if (ocupado) const LinearProgressIndicator(),
              ],
            ),
          ),
          _pie(),
        ],
      );
    }
    return Scaffold(
      backgroundColor: _Fm.fondo,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _cabeza(),
            Expanded(child: cuerpo),
          ],
        ),
      ),
    );
  }
}
