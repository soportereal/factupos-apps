// FactuMóvil — Editar línea MFM-EDIT (#3957, foto 6 de Auxiliares): réplica del editor de la web. Cabeza navy con código,
// nombre, CABYS y actividad · Bodega · Tipo de precio P1…Pn (con su precio) · Tarifa IVA · Precio oficial sin/con IVA ·
// Precio VIRTUAL sin/con IVA «para llegar a un descuento» · Descuento % (real) y monto (virtual) · Cantidad por monto
// (solo fraccionados) · Totales · Cancelar / Guardar.
// 🔑 Las reglas son las de MV-108 (aplicarCambiosLinea): permisos 024/004/033/034, supervisor, «SI» bajo el costo.
part of 'caja.dart';

class _EdicionMovil {
  final CambiosLinea cambios;
  final Map<String, dynamic>?
  tarifa; // la tarifa de IVA elegida (null = no cambió)
  const _EdicionMovil(this.cambios, this.tarifa);
}

extension _EditarMovil on _EstadoCaja {
  /// Abre MFM-EDIT para la línea [i] y aplica lo que se guarde con las reglas de la caja.
  Future<void> _fmEditar(int i) async {
    if (i < 0 || i >= doc.lineas.length) return;
    final l = doc.lineas[i];
    final antes = l.nivel;
    final r = await Navigator.of(context).push<_EdicionMovil>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => _EditorLineaMovil(doc: doc, indice: i),
      ),
    );
    if (!mounted) return;
    var cambio = l.nivel != antes; // la lista de precio se aplica al instante
    if (r != null) {
      final t = r.tarifa;
      final tarifaAntes = (l.codigoTarifa, l.tarifa);
      if (t != null) {
        doc.cambiarTarifa(
          i,
          '${t['codigo']}',
          ((t['porcentaje'] as num?) ?? 0).toDouble(),
        );
      }
      if (await aplicarCambiosLinea(
        context,
        doc,
        widget.cajeros,
        l,
        r.cambios,
      )) {
        cambio = true;
      } else if (t != null) {
        doc.cambiarTarifa(
          i,
          tarifaAntes.$1,
          tarifaAntes.$2,
        ); // no se guardó: el IVA vuelve
      }
    }
    if (cambio) _cambio();
  }
}

class _EditorLineaMovil extends StatefulWidget {
  final Documento doc;
  final int indice;
  const _EditorLineaMovil({required this.doc, required this.indice});
  @override
  State<_EditorLineaMovil> createState() => _EstadoEditorLineaMovil();
}

class _EstadoEditorLineaMovil extends State<_EditorLineaMovil> {
  Documento get doc => widget.doc;
  Linea get l => doc.lineas[widget.indice];

  late double precio; // sin IVA
  late double desc; // %
  late double cantidad;
  late String bodega;
  Map<String, dynamic>? tarifa; // elegida (null = la de la línea)
  String error = '';

  final oficialSin = TextEditingController(),
      oficialCon = TextEditingController(),
      virtualSin = TextEditingController(),
      virtualCon = TextEditingController(),
      pct = TextEditingController(),
      monto = TextEditingController(),
      porMonto = TextEditingController();

  double get _t => (tarifa == null
      ? l.tarifa
      : ((tarifa!['porcentaje'] as num?) ?? 0).toDouble());
  double get _f => 1 + _t / 100;
  double get _virtual => precio * (1 - desc / 100);

  @override
  void initState() {
    super.initState();
    _desdeLinea();
    bodega = doc.bodegaDe(l);
  }

  void _desdeLinea() {
    precio = l.precio;
    cantidad = l.cantidad;
    desc = l.descMonto != null && l.cantidad * l.precio > 0
        ? l.descMonto! / (l.cantidad * l.precio) * 100
        : l.descuento;
    _pintar();
  }

  String _n(double v, [int? d]) =>
      fmt(v, d ?? doc.dec.precio).replaceAll(',', '');

  /// Reescribe todos los campos menos [salvo] (el que se está escribiendo).
  void _pintar([TextEditingController? salvo]) {
    void p(TextEditingController c, String v) {
      if (!identical(c, salvo)) c.text = v;
    }

    p(oficialSin, _n(precio));
    p(oficialCon, _n(precio * _f, 2));
    p(virtualSin, _n(_virtual));
    p(virtualCon, _n(_virtual * _f, 2));
    p(pct, desc > 0 ? _n(desc, doc.dec.descPct) : '0');
    p(monto, _n(precio - _virtual, 2));
  }

  void _escribio(TextEditingController c) {
    final v = leerMonto(c.text);
    if (v.isNaN) return;
    setState(() {
      error = '';
      if (identical(c, oficialSin)) {
        precio = v;
      } else if (identical(c, oficialCon)) {
        precio = v / _f;
      } else if (precio > 0 && identical(c, virtualSin)) {
        desc = (1 - v / precio) * 100;
      } else if (precio > 0 && identical(c, virtualCon)) {
        desc = (1 - v / _f / precio) * 100;
      } else if (identical(c, pct)) {
        desc = v;
      } else if (precio > 0 && identical(c, monto)) {
        desc = v / precio * 100;
      } else if (identical(c, porMonto)) {
        final u = _virtual * _f;
        if (u > 0) cantidad = redondear(v / u, 3);
      }
      if (desc < 0) desc = 0;
      _pintar(c);
    });
  }

  Linea get _vista {
    final c = lineaDesde(lineaAMapa(l))
      ..cantidad = cantidad
      ..precio = precio
      ..tarifa = _t
      ..descuento = redondear(desc, doc.dec.descPct)
      ..descMonto = null;
    return calcular(c, doc.dec, doc.medioPago);
  }

  void _guardar() {
    if (!(precio > 0) || !(cantidad > 0)) {
      setState(() => error = 'Revise el precio y la cantidad.');
      return;
    }
    Navigator.pop(
      context,
      _EdicionMovil(
        CambiosLinea(
          cantidad: cantidad,
          precio: redondear(precio, doc.dec.precio),
          modo: 'pct',
          valor: redondear(desc, doc.dec.descPct),
          bonificacion: false,
          bodega: doc.datos.bodegas.isNotEmpty ? bodega : null,
        ),
        tarifa,
      ),
    );
  }

  void _nivel(int n) {
    final (bien, _, _) = doc.cambiarNivel(widget.indice, n);
    setState(() {
      if (!bien) {
        error = 'El artículo no tiene precio en P$n';
        return;
      }
      error = '';
      _desdeLinea();
    });
  }

  // ── piezas ──
  Widget _caja(Widget hijo, {Color borde = _Fm.borde, Color? fondo}) =>
      Container(
        margin: const EdgeInsets.fromLTRB(10, 8, 10, 0),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: fondo ?? Colors.white,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: borde, width: 1.4),
        ),
        child: hijo,
      );

  Widget _campo(
    TextEditingController c, {
    String? pista,
    bool activo = true,
    Color color = _Fm.tinta,
  }) => TextField(
    controller: c,
    enabled: activo,
    textAlign: TextAlign.right,
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    style: TextStyle(fontSize: 19, fontWeight: FontWeight.w600, color: color),
    decoration: InputDecoration(isDense: true, hintText: pista),
    onChanged: (_) => _escribio(c),
    onTap: () =>
        c.selection = TextSelection(baseOffset: 0, extentOffset: c.text.length),
  );

  Widget _titulo(IconData ico, String t, Color color, [String extra = '']) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(
          children: [
            Icon(ico, size: 18, color: color),
            const SizedBox(width: 6),
            Text(
              t,
              style: TextStyle(
                fontWeight: FontWeight.w700,
                fontSize: 15,
                color: color,
              ),
            ),
            if (extra.isNotEmpty) ...[
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  extra,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontStyle: FontStyle.italic,
                    fontSize: 12,
                    color: _Fm.suave,
                  ),
                ),
              ),
            ],
          ],
        ),
      );

  Widget _parSinCon(
    TextEditingController sin,
    TextEditingController con, {
    bool activo = true,
    Color color = _Fm.tinta,
  }) => Row(
    children: [
      const Text('Sin IVA', style: TextStyle(color: _Fm.suave)),
      const SizedBox(width: 6),
      Expanded(
        child: _campo(sin, activo: activo, color: color),
      ),
      const SizedBox(width: 8),
      const Text('Con IVA', style: TextStyle(color: _Fm.suave)),
      const SizedBox(width: 6),
      Expanded(
        child: _campo(con, activo: activo, color: color),
      ),
    ],
  );

  Widget _cabeza() => Container(
    padding: const EdgeInsets.fromLTRB(14, 10, 8, 12),
    decoration: const BoxDecoration(
      gradient: LinearGradient(colors: [_Fm.navy1, _Fm.navy2]),
    ),
    child: Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  _fmEtiqueta(l.codigo, Colors.white, _Fm.navy1),
                  const Spacer(),
                  _fmEtiqueta(
                    'MFM-EDIT',
                    const Color(0x33FFFFFF),
                    Colors.white,
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                l.nombre.toUpperCase(),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 17,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const SizedBox(height: 4),
              Wrap(
                spacing: 12,
                children: [
                  if (l.cabys.isNotEmpty)
                    Text(
                      'CABYS ${l.cabys}',
                      style: const TextStyle(color: Colors.white70),
                    ),
                  if (l.actividad.isNotEmpty)
                    Text(
                      'Act. ${l.actividad}',
                      style: const TextStyle(color: Colors.white70),
                    ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(width: 6),
        IconButton(
          tooltip: 'Cerrar',
          onPressed: () => Navigator.pop(context),
          style: IconButton.styleFrom(backgroundColor: const Color(0x33FFFFFF)),
          icon: const Icon(Icons.close, color: Colors.white),
        ),
      ],
    ),
  );

  Widget _bodega() {
    final bodegas = doc.datos.bodegas;
    final codigos = [for (final b in bodegas) '${b['codigo'] ?? ''}'];
    final atada = doc.datos.bodegaAtadaEstacion;
    final estilo = Theme.of(context).textTheme.bodyMedium!
        .copyWith(fontSize: 16, color: _Fm.tinta);
    final d = DropdownButton<String>(
      value: codigos.contains(bodega) ? bodega : null,
      isExpanded: true,
      style: estilo,
      underline: const SizedBox(),
      items: [
        for (final c in codigos)
          DropdownMenuItem(
            value: c,
            child: Text(
              doc.datos.nombreBodega(c),
              overflow: TextOverflow.ellipsis,
            ),
          ),
      ],
      onChanged: atada ? null : (v) => setState(() => bodega = v ?? bodega),
    );
    return _caja(
      Row(
        children: [
          const SizedBox(
            width: 90,
            child: Text('Bodega', style: TextStyle(color: _Fm.suave)),
          ),
          Expanded(
            child: atada
                ? Tooltip(message: 'Atada a la estación (251)', child: d)
                : d,
          ),
        ],
      ),
    );
  }

  Widget _precios() {
    final niveles = {...doc.datos.nivelesPrecio, l.nivel}.toList()..sort();
    final puede = doc.tienePermiso('034');
    final tarifas = doc.datos.tarifasIva;
    final codTarifa = tarifa == null ? l.codigoTarifa : '${tarifa!['codigo']}';
    final estilo = Theme.of(context).textTheme.bodyMedium!
        .copyWith(fontSize: 16, color: _Fm.tinta);
    Widget boton(int n) {
      final p = doc.precioPara(l.codigo, n);
      final tiene = p != null && p.$2 == n;
      final activo = n == l.nivel;
      final b = Material(
        color: activo ? _Fm.acento : Colors.white,
        borderRadius: BorderRadius.circular(8),
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: puede && tiene && !activo ? () => _nivel(n) : null,
          child: Container(
            height: 50,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: activo ? _Fm.acento : _Fm.borde),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  'P$n',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 16,
                    color: activo ? Colors.white : _Fm.navy1,
                  ),
                ),
                if (tiene)
                  FittedBox(
                    child: Text(
                      fmt(p.$1 * _f),
                      style: TextStyle(
                        fontSize: 11,
                        color: activo ? Colors.white : _Fm.suave,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      );
      return puede ? b : Tooltip(message: 'Sin permiso (034)', child: b);
    }

    return _caja(
      Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _titulo(Icons.format_list_numbered, 'Tipo de precio', _Fm.navy1),
          Row(
            children: [
              for (final n in niveles) ...[
                Expanded(child: boton(n)),
                if (n != niveles.last) const SizedBox(width: 5),
              ],
            ],
          ),
          if (tarifas.isNotEmpty) ...[
            const SizedBox(height: 8),
            Row(
              children: [
                const SizedBox(
                  width: 90,
                  child: Text('Tarifa IVA', style: TextStyle(color: _Fm.suave)),
                ),
                Expanded(
                  child: DropdownButton<String>(
                    value: tarifas.any((t) => '${t['codigo']}' == codTarifa)
                        ? codTarifa
                        : null,
                    isExpanded: true,
                    style: estilo,
                    underline: const SizedBox(),
                    items: [
                      for (final t in tarifas)
                        DropdownMenuItem(
                          value: '${t['codigo']}',
                          child: Text(
                            '${t['codigo']} - ${t['nombre'] ?? ''}',
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: (v) => setState(() {
                      tarifa = tarifas.firstWhere((t) => '${t['codigo']}' == v);
                      _pintar();
                    }),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _totales() {
    final v = _vista;
    Widget celda(String t, double n, {bool fuerte = false}) => Expanded(
      child: Container(
        margin: const EdgeInsets.only(right: 6),
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: fuerte ? _Fm.navy1 : const Color(0xFFF3F6FA),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(
              t,
              style: TextStyle(
                fontSize: 12,
                color: fuerte ? Colors.white70 : _Fm.suave,
              ),
            ),
            FittedBox(
              child: Text(
                fmt(n),
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  color: fuerte ? Colors.white : _Fm.tinta,
                ),
              ),
            ),
          ],
        ),
      ),
    );
    return _caja(
      Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _titulo(Icons.calculate_outlined, 'Totales', _Fm.navy1, 'CRC'),
          Row(
            children: [
              celda('Subtotal', v.subtotal3),
              celda('IVA', v.iva),
              celda('Total neto', v.total, fuerte: true),
            ],
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final edita = doc.tienePermiso('024'), descuenta = doc.tienePermiso('004');
    final frac = l.fraccionable != 0;
    const ambar = Color(0xFFB45309);
    return Scaffold(
      backgroundColor: _Fm.fondo,
      body: SafeArea(
        child: Column(
          children: [
            _cabeza(),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.only(bottom: 12),
                children: [
                  if (doc.datos.bodegas.isNotEmpty) _bodega(),
                  _precios(),
                  _caja(
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _titulo(
                          Icons.verified,
                          'Precio oficial',
                          _Fm.acento,
                          edita ? '' : 'cambiarlo pide permiso 024',
                        ),
                        _parSinCon(oficialSin, oficialCon, color: _Fm.acento),
                      ],
                    ),
                    borde: const Color(0xFF7FA6E8),
                  ),
                  _caja(
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _titulo(
                          Icons.sell_outlined,
                          'Precio virtual',
                          ambar,
                          'para llegar a un descuento',
                        ),
                        _parSinCon(virtualSin, virtualCon),
                      ],
                    ),
                    borde: const Color(0xFFF2D3A8),
                    fondo: const Color(0xFFFFFBF5),
                  ),
                  _caja(
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _titulo(
                          Icons.percent,
                          'Descuento',
                          ambar,
                          descuenta ? '' : 'pide permiso 004',
                        ),
                        Row(
                          children: [
                            const Text('%', style: TextStyle(color: _Fm.suave)),
                            const SizedBox(width: 4),
                            _fmEtiqueta('REAL', Marca.rojo, Colors.white),
                            const SizedBox(width: 6),
                            Expanded(child: _campo(pct)),
                            const SizedBox(width: 8),
                            const Text(
                              'Monto',
                              style: TextStyle(color: _Fm.suave),
                            ),
                            const SizedBox(width: 6),
                            Expanded(child: _campo(monto)),
                          ],
                        ),
                      ],
                    ),
                    borde: const Color(0xFFF2D3A8),
                    fondo: const Color(0xFFFFFBF5),
                  ),
                  _caja(
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _titulo(
                          Icons.scale_outlined,
                          'Cantidad por monto',
                          frac ? _Fm.navy1 : _Fm.suave,
                          'usa precio virtual',
                        ),
                        _campo(porMonto, pista: 'Monto con IVA', activo: frac),
                        const SizedBox(height: 4),
                        Text(
                          frac ? 'Cantidad: ${fmt(cantidad, 3)}' : 'Solo fraccionados (kg/lt). Usa el precio virtual de la ficha de Descuento.',
                          style: const TextStyle(
                            fontSize: 12,
                            color: _Fm.suave,
                          ),
                        ),
                      ],
                    ),
                    fondo: frac ? null : const Color(0xFFF5F7FA),
                  ),
                  _totales(),
                  if (error.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(14, 10, 14, 0),
                      child: Text(
                        error,
                        style: const TextStyle(color: Marca.rojo),
                      ),
                    ),
                ],
              ),
            ),
            Container(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
              decoration: const BoxDecoration(
                color: Colors.white,
                border: Border(top: BorderSide(color: _Fm.borde)),
              ),
              child: Row(
                children: [
                  Expanded(
                    flex: 2,
                    child: SizedBox(
                      height: 50,
                      child: OutlinedButton(
                        onPressed: () => Navigator.pop(context),
                        child: const Text('Cancelar'),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    flex: 3,
                    child: SizedBox(
                      height: 50,
                      child: FilledButton.icon(
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFF4CAF7A),
                        ),
                        onPressed: _guardar,
                        icon: const Icon(Icons.check),
                        label: const Text(
                          'Guardar',
                          style: TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
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
}
