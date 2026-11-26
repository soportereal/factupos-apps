// FactuMóvil — la pantalla del VENDEDOR (#3957, dueño 26-nov-2026): «FactuSuper está diseñado para tiendas, FactuMóvil
// para gente de venta» · «tiene que tener la misma apariencia de FactuMóvil web». Réplica de modules/factumovil
// (factumovil.php + css/factumovil.css + fm_cotizacion_lineas_render): barra navy de dos renglones con el cliente,
// acordeón del cliente, Cotizaciones · Ventas · Categorías · ⋮, líneas en tarjeta (código + nombre / chips d·P·B·i + −/+ /
// P.Ud · Precio · Desc · Subtot · IVA · total), «Agregar artículo» verde y el pie con detalle, total, Guardar y Procesar.
// 🔑 La LÓGICA es la misma de la caja (Documento, cola sin internet, impresión, permisos): acá solo cambia la apariencia.
part of 'caja.dart';

/// La paleta de la web (:root de factumovil.css).
abstract final class _Fm {
  static const navy1 = Color(0xFF1A4D80), navy2 = Color(0xFF143D66);
  static const fondo = Color(0xFFEEF3FA), borde = Color(0xFFCBD9EA);
  static const tinta = Color(0xFF0F2438), suave = Color(0xFF5A7088);
  static const acento = Color(0xFF2563EB);
}

extension _VistaMovil on _EstadoCaja {
  Widget _movil() {
    return Scaffold(
      key: _andamio,
      backgroundColor: _Fm.fondo,
      endDrawer: _opciones(),
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _fmBarra(),
            if (_fmCliAbierto) _fmCliPanel(),
            _fmNav(),
            Expanded(
              child: Stack(
                children: [
                  Positioned.fill(child: _fmLista()),
                  Positioned(right: 16, bottom: 12, child: _fmFab()),
                ],
              ),
            ),
            _fmTotales(),
          ],
        ),
      ),
    );
  }

  bool get _fmCliAbierto => _cliAbierto;

  // ── Barra de arriba: cliente ▾ · nombre del documento · Regresar / Seleccionar cliente · Refrescar ──
  Widget _fmBarra() {
    final cod = '${doc.cliente['codigo'] ?? 'SN'}';
    final pend = widget.cola.pendientes.length;
    final filo = Border.all(color: Colors.white.withValues(alpha: 0.4));
    Widget boton(
      Widget hijo, {
      VoidCallback? alTocar,
      Color fondo = const Color(0x33FFFFFF),
    }) => Material(
      color: fondo,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        borderRadius: BorderRadius.circular(6),
        onTap: alTocar,
        child: Container(
          height: 34,
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(
            border: filo,
            borderRadius: BorderRadius.circular(6),
          ),
          alignment: Alignment.center,
          child: DefaultTextStyle.merge(
            style: const TextStyle(
              color: Colors.white,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
            child: IconTheme.merge(
              data: const IconThemeData(color: Colors.white, size: 16),
              child: hijo,
            ),
          ),
        ),
      ),
    );
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          colors: [_Fm.navy1, _Fm.navy2],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
      ),
      child: Column(
        children: [
          Row(
            children: [
              boton(
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      cod,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Icon(_fmCliAbierto ? Icons.expand_less : Icons.expand_more),
                  ],
                ),
                fondo: const Color(0x1FFFFFFF),
                alTocar: () => _cambio(() => _cliAbierto = !_cliAbierto),
              ),
              const SizedBox(width: 6),
              Expanded(
                child: SizedBox(
                  height: 34,
                  child: TextField(
                    key: ValueKey('nom-$cod'),
                    controller: _fmNombre,
                    style: const TextStyle(color: _Fm.tinta, fontSize: 13),
                    decoration: InputDecoration(
                      isDense: true,
                      hintText: 'Nombre del documento...',
                      hintStyle: const TextStyle(color: Color(0xFF8AA0B8)),
                      filled: true,
                      fillColor: Colors.white,
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 8,
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(6),
                        borderSide: const BorderSide(color: Color(0x40FFFFFF)),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(6),
                        borderSide: const BorderSide(color: Color(0x99FFFFFF)),
                      ),
                    ),
                    onChanged: (v) {
                      // Nombre manual del documento (fm_cotizacion_nombremanual_guardar): solo al cliente de contado.
                      if (cod.toUpperCase() == 'SN') {
                        doc.cliente['nombre'] = v.trim().isEmpty
                            ? 'CLIENTE CONTADO'
                            : v.trim();
                        _cambio();
                      }
                    },
                  ),
                ),
              ),
              const SizedBox(width: 6),
              boton(
                const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.arrow_back),
                    SizedBox(width: 4),
                    Text('Regresar'),
                  ],
                ),
                fondo: const Color(0xFF991B1B),
                alTocar: widget.alSalir,
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: boton(
                  const Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.search),
                      SizedBox(width: 5),
                      Text('Seleccionar cliente'),
                    ],
                  ),
                  fondo: const Color(0xFF059669),
                  alTocar: _fmClientes,
                ),
              ),
              const SizedBox(width: 6),
              boton(
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.refresh),
                    const SizedBox(width: 5),
                    Text(
                      pend > 0 ? 'Refrescar · $pend por enviar' : 'Refrescar',
                    ),
                  ],
                ),
                alTocar: () async {
                  await _enviar();
                  await _revisarCambios();
                },
              ),
            ],
          ),
        ],
      ),
    );
  }

  // ── Acordeón del cliente ──
  Widget _fmCliPanel() {
    final c = doc.cliente;
    String v(String k) {
      final t = '${c[k] ?? ''}'.trim();
      return t.isEmpty ? '—' : t;
    }

    Widget dato(String r, String val) => Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            r,
            style: const TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w600,
              color: _Fm.suave,
            ),
          ),
          Text(
            val,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: _Fm.tinta,
            ),
          ),
        ],
      ),
    );
    Widget accion(IconData i, String t, Color col, VoidCallback? f) => Expanded(
      child: SizedBox(
        height: 42,
        child: FilledButton.icon(
          style: FilledButton.styleFrom(
            backgroundColor: col,
            disabledBackgroundColor: const Color(0xFF4B5563),
            disabledForegroundColor: const Color(0xFF9CA3AF),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(6),
            ),
            padding: const EdgeInsets.symmetric(horizontal: 6),
          ),
          onPressed: f,
          icon: Icon(i, size: 16),
          label: Text(t, style: const TextStyle(fontSize: 12)),
        ),
      ),
    );
    return Container(
      width: double.infinity,
      color: const Color(0xFFDDE8F5),
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          dato('Comercial', v('comercial')),
          dato('Jurídico', v('nombre')),
          dato('Cédula', v('cedula')),
          dato('Teléfono', v('telefonos')),
          dato('Correo facturación', v('email_factura')),
          Row(
            children: [
              accion(
                Icons.person_add_alt,
                'Nuevo cliente',
                const Color(0xFF0D9488),
                _clienteNuevo,
              ),
              const SizedBox(width: 8),
              accion(
                Icons.edit_note,
                'Editar cliente',
                _Fm.navy1,
                '${c['codigo'] ?? 'SN'}'.toUpperCase() == 'SN'
                    ? null
                    : _clienteEditar,
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              accion(
                Icons.description_outlined,
                'Estado de cuenta',
                const Color(0xFF0284C7),
                null,
              ),
            ],
          ),
        ],
      ),
    );
  }

  // ── Cotizaciones · Ventas · Categorías · ⋮ (colores de .fm-nav button:nth-child) ──
  Widget _fmNav() {
    Widget b(
      IconData i,
      String t,
      Color fondo,
      Color borde,
      Color tinta,
      VoidCallback? f, {
      String? tip,
      bool chico = false,
    }) {
      final w = Material(
        color: f == null ? const Color(0xFFE5E7EB) : fondo,
        borderRadius: BorderRadius.circular(6),
        child: InkWell(
          borderRadius: BorderRadius.circular(6),
          onTap: f,
          child: Container(
            height: 34,
            decoration: BoxDecoration(
              border: Border.all(
                color: f == null ? const Color(0xFFD1D5DB) : borde,
              ),
              borderRadius: BorderRadius.circular(6),
            ),
            alignment: Alignment.center,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  i,
                  size: 15,
                  color: f == null ? const Color(0xFF9CA3AF) : tinta,
                ),
                if (t.isNotEmpty) ...[
                  const SizedBox(width: 4),
                  Flexible(
                    child: Text(
                      t,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w600,
                        color: f == null ? const Color(0xFF9CA3AF) : tinta,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      );
      final x = tip == null ? w : Tooltip(message: tip, child: w);
      return chico ? SizedBox(width: 40, child: x) : Expanded(child: x);
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 12, 8, 8),
      child: Row(
        children: [
          b(
            Icons.assignment_turned_in_outlined,
            'Cotizaciones',
            const Color(0xFFE8F0FE),
            const Color(0xFF93B8EF),
            const Color(0xFF2563EB),
            _verProformas,
          ),
          const SizedBox(width: 5),
          b(
            Icons.receipt_long_outlined,
            'Ventas',
            const Color(0xFFE7F6EE),
            const Color(0xFF86D4AB),
            const Color(0xFF059669),
            _verVentas,
          ),
          const SizedBox(width: 5),
          b(
            Icons.grid_view,
            'Categorías',
            const Color(0xFFF1EAFE),
            const Color(0xFFC4A8F5),
            const Color(0xFF7C3AED),
            null,
            tip: 'Categorías: llega en la próxima versión',
          ),
          const SizedBox(width: 5),
          b(
            Icons.more_vert,
            '',
            const Color(0xFFFDEEF0),
            const Color(0xFFF0A3B3),
            const Color(0xFFE11D48),
            () => _andamio.currentState?.openEndDrawer(),
            chico: true,
          ),
        ],
      ),
    );
  }

  // ── Las líneas (fm_cotizacion_lineas_render) ──
  Widget _fmLista() {
    if (doc.lineas.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.inventory_2_outlined,
              size: 46,
              color: Color(0x809AB0CB),
            ),
            SizedBox(height: 8),
            Text(
              'Sin artículos',
              style: TextStyle(fontSize: 14, color: Color(0xFF9AB0CB)),
            ),
            SizedBox(height: 4),
            Text(
              'Toque «Agregar artículo» para empezar',
              style: TextStyle(fontSize: 12, color: Color(0xFFB6C6DA)),
            ),
          ],
        ),
      );
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(8, 0, 8, 56),
      itemCount: doc.lineas.length,
      itemBuilder: (_, i) => _fmLinea(i, doc.lineas[i]),
    );
  }

  Widget _fmChip(String t, Color fondo, Color tinta, double ancho) => Container(
    width: ancho,
    margin: const EdgeInsets.only(right: 3),
    padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 1),
    decoration: BoxDecoration(
      color: fondo,
      borderRadius: BorderRadius.circular(4),
    ),
    alignment: Alignment.center,
    child: Text(
      t,
      maxLines: 1,
      overflow: TextOverflow.clip,
      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: tinta),
    ),
  );

  Widget _fmLinea(int i, Linea l) {
    double r2(double n) => (n * 100).roundToDouble() / 100;
    final precioTotal = r2(l.precio * l.cantidad);
    final descMonto = r2(l.descuentoMonto);
    final subtotal = r2(precioTotal - descMonto);
    final bodegaPropia = l.bodega.isNotEmpty;
    final verUtil = doc.tienePermiso('064');
    Widget celda(
      String r,
      String v, {
      bool total = false,
      bool resalta = false,
    }) => Padding(
      padding: const EdgeInsets.only(right: 14),
      child: Column(
        crossAxisAlignment: total
            ? CrossAxisAlignment.end
            : CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (!total)
            Text(
              r,
              style: const TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w600,
                color: _Fm.suave,
              ),
            ),
          Text(
            v,
            style: TextStyle(
              fontSize: total ? 14 : (resalta ? 12 : 10),
              fontWeight: FontWeight.w700,
              color: total
                  ? _Fm.acento
                  : (resalta ? const Color(0xFFB45309) : _Fm.tinta),
            ),
          ),
        ],
      ),
    );
    Widget qty(
      String t,
      Color fondo,
      Color tinta,
      Color borde,
      VoidCallback f,
    ) => Material(
      color: fondo,
      borderRadius: BorderRadius.circular(6),
      child: InkWell(
        borderRadius: BorderRadius.circular(6),
        onTap: f,
        child: Container(
          width: 38,
          height: 28,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            border: Border.all(color: borde),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(
            t,
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: tinta,
            ),
          ),
        ),
      ),
    );
    String util() {
      if (l.costo <= 0.01) return 'u —';
      final p = (l.precio * (1 - l.descuento / 100) - l.costo) / l.costo * 100;
      return p > 1000 ? 'u ERR' : 'u${fmt(p, 1)}%';
    }

    return Dismissible(
      key: ObjectKey(l),
      direction: DismissDirection.endToStart,
      background: Container(
        margin: const EdgeInsets.only(bottom: 4),
        decoration: BoxDecoration(
          color: const Color(0xFFFEE2E2),
          border: Border.all(color: const Color(0xFFFCA5A5)),
          borderRadius: BorderRadius.circular(6),
        ),
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 16),
        child: const Icon(Icons.delete_outline, color: Color(0xFFDC2626)),
      ),
      confirmDismiss: (_) async {
        await _quitar(i);
        return false; // _quitar ya repinta la lista
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 4),
        padding: const EdgeInsets.fromLTRB(9, 5, 9, 5),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: _Fm.borde),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            InkWell(
              onTap: () => _editar(i),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 1,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFFE2E8F0),
                      borderRadius: BorderRadius.circular(5),
                    ),
                    child: Text(
                      l.codigo,
                      style: const TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: Color(0xFF475569),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      l.nombre,
                      style: const TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w700,
                        color: _Fm.tinta,
                        height: 1.15,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 3),
            Row(
              children: [
                Expanded(
                  child: InkWell(
                    onTap: () => _editar(i),
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      physics: const NeverScrollableScrollPhysics(),
                      child: Row(
                        children: [
                          _fmChip(
                            'd${fmt(l.descuento, 0)}%',
                            l.descuento > 0
                                ? const Color(0xFFFEF3C7)
                                : const Color(0xFFF1F5F9),
                            l.descuento > 0
                                ? const Color(0xFFB45309)
                                : const Color(0xFF64748B),
                            34,
                          ),
                          _fmChip(
                            'P${l.nivel}',
                            const Color(0xFFCCFBF1),
                            const Color(0xFF0D9488),
                            26,
                          ),
                          _fmChip(
                            'B${doc.bodegaDe(l)}',
                            bodegaPropia
                                ? const Color(0xFFFEF3C7)
                                : const Color(0xFFDBEAFE),
                            bodegaPropia
                                ? const Color(0xFFB45309)
                                : const Color(0xFF2563EB),
                            30,
                          ),
                          _fmChip(
                            'i${fmt(l.tarifa, 0)}%',
                            Colors.transparent,
                            _Fm.tinta,
                            36,
                          ),
                          if (verUtil)
                            _fmChip(
                              util(),
                              util().contains('-')
                                  ? const Color(0xFFFEE2E2)
                                  : const Color(0xFFEDE9FE),
                              util().contains('-')
                                  ? const Color(0xFFDC2626)
                                  : const Color(0xFF7C3AED),
                              48,
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
                qty(
                  '−',
                  const Color(0xFFFEE2E2),
                  const Color(0xFFDC2626),
                  const Color(0xFFFCA5A5),
                  () => _fmCantidad(i, l.cantidad - 1),
                ),
                InkWell(
                  onTap: () => _fmCantidadEscrita(i),
                  child: Container(
                    width: 64,
                    height: 28,
                    margin: const EdgeInsets.symmetric(horizontal: 3),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      border: Border.all(color: _Fm.borde),
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      fmt(l.cantidad, l.fraccionable != 0 ? 3 : 0),
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: _Fm.tinta,
                      ),
                    ),
                  ),
                ),
                qty(
                  '+',
                  const Color(0xFFD1FAE5),
                  const Color(0xFF059669),
                  const Color(0xFF6EE7B7),
                  () => _fmCantidad(i, l.cantidad + 1),
                ),
              ],
            ),
            const SizedBox(height: 3),
            InkWell(
              onTap: () => _editar(i),
              child: Row(
                children: [
                  Expanded(
                    child: Wrap(
                      runSpacing: 2,
                      children: [
                        celda('P.Ud', fmt(l.precio)),
                        celda('Precio', fmt(precioTotal)),
                        celda('Desc', fmt(descMonto), resalta: descMonto > 0),
                        celda('Subtot', fmt(subtotal)),
                        celda('IVA', fmt(l.iva)),
                      ],
                    ),
                  ),
                  celda('', fmt(l.total), total: true),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// − / +: cambia la cantidad con las MISMAS reglas de la línea; si algo pide permiso o «SI», abre la línea.
  Future<void> _fmCantidad(int i, double nueva) async {
    final l = doc.lineas[i];
    if (nueva <= 0) return _quitar(i);
    final c = CambiosLinea(
      cantidad: nueva,
      precio: l.precio,
      modo: l.descMonto != null ? 'monto' : 'pct',
      valor: l.descMonto ?? l.descuento,
      bonificacion: l.bonificacion,
    );
    final v = doc.validarLinea(l, c, const {});
    if (v.ok) {
      _cambio(() => doc.aplicarLinea(l, c, const {}));
    } else {
      _aviso(v.error.isNotEmpty ? v.error : v.motivo, error: true);
    }
  }

  Future<void> _fmCantidadEscrita(int i) async {
    final l = doc.lineas[i];
    final t = await pedirTexto(
      context,
      'Cantidad',
      l.nombre,
      fmt(l.cantidad, l.fraccionable != 0 ? 3 : 0),
    );
    if (t == null) return;
    final n = leerMonto(t);
    if (n.isNaN) return _aviso('Revise la cantidad.', error: true);
    await _fmCantidad(i, n);
  }

  Widget _fmFab() => DecoratedBox(
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(6),
      boxShadow: const [
        BoxShadow(
          color: Color(0x66047857),
          blurRadius: 14,
          offset: Offset(0, 4),
        ),
      ],
    ),
    child: Material(
      borderRadius: BorderRadius.circular(6),
      clipBehavior: Clip.antiAlias,
      child: Ink(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            colors: [Color(0xFF10B981), Color(0xFF047857)],
          ),
        ),
        child: InkWell(
          onTap: _fmBuscar,
          child: const Padding(
            padding: EdgeInsets.symmetric(horizontal: 14, vertical: 9),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.add, color: Colors.white, size: 18),
                SizedBox(width: 5),
                Text(
                  'Agregar artículo',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );

  /// Búsqueda de artículos a pantalla completa (components/factumovil/busqueda), con el catálogo del equipo.
  Future<void> _fmBuscar() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => _BusquedaMovil(
          doc: doc,
          datos: widget.datos,
          alAgregar: _fmAgregarDesde,
        ),
      ),
    );
    _cambio();
  }

  /// «+ Agregar» de la tarjeta: agrega con las reglas de siempre y, si quedó una línea NUEVA, le pone la bodega y la
  /// lista de precio que eligió el vendedor (los combos solo se habilitan con 033 / 034). → mensaje para la búsqueda.
  Future<String> _fmAgregarDesde(
    Map<String, dynamic> art,
    String cant,
    String bodega,
    int nivel,
  ) async {
    final antes = doc.lineas.length;
    await _agregar(art, cantidad: cant);
    if (_sel < 0 || _sel >= doc.lineas.length) return '';
    final l = doc.lineas[_sel];
    if (doc.lineas.length > antes) {
      if (nivel != l.nivel) doc.cambiarNivel(_sel, nivel);
      if (bodega.isNotEmpty && bodega != doc.bodegaDe(l)) {
        l.bodega = bodega == '${widget.datos.estacion['bodega'] ?? ''}'.trim()
            ? ''
            : bodega;
      }
      _cambio();
    }
    return doc.lineas.length > antes || l.codigo == '${art['codigo']}'
        ? 'Agregado: ${art['nombre']}'
        : '';
  }

  /// Seleccionar cliente (components/factumovil/clientes) a pantalla completa.
  Future<void> _fmClientes() async {
    final c = await Navigator.of(context).push<Map<String, dynamic>>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => _ClientesMovil(datos: widget.datos),
      ),
    );
    if (!mounted) return;
    if (c == null) return;
    if (c['__nuevo'] == true) return _clienteNuevo();
    _cambio(() => doc.asignarCliente(c));
    _aviso('Cliente: ${c['nombre']}');
  }

  // ── Pie: detalle · conteo / moneda · descuento · total · Guardar · Procesar ──
  Widget _fmTotales() {
    final t = doc.totales;
    final vacia = doc.lineas.isEmpty;
    final guarda = doc.tienePermiso('104');
    Widget ficha(
      Widget hijo,
      Color fondo,
      VoidCallback? f, {
      Color? borde,
      int flex = 0,
      String? tip,
    }) {
      final w = Material(
        color: f == null && borde != null ? const Color(0xFF4B5563) : fondo,
        borderRadius: BorderRadius.circular(6),
        child: InkWell(
          borderRadius: BorderRadius.circular(6),
          onTap: f,
          child: Container(
            height: 48,
            padding: const EdgeInsets.symmetric(horizontal: 8),
            decoration: borde == null
                ? null
                : BoxDecoration(
                    border: Border.all(color: borde),
                    borderRadius: BorderRadius.circular(6),
                  ),
            alignment: Alignment.center,
            child: hijo,
          ),
        ),
      );
      final x = tip == null ? w : Tooltip(message: tip, child: w);
      return flex > 0 ? Expanded(flex: flex, child: x) : x;
    }

    Widget icoTexto(IconData i, String s, {bool apagado = false}) => Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(
          i,
          size: 17,
          color: apagado ? const Color(0xFF9CA3AF) : Colors.white,
        ),
        Text(
          s,
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w600,
            color: apagado ? const Color(0xFF9CA3AF) : Colors.white,
          ),
        ),
      ],
    );
    final arts = fmt(
      t.articulos,
      t.articulos == t.articulos.truncateToDouble() ? 0 : 3,
    );
    return Container(
      padding: EdgeInsets.fromLTRB(
        10,
        6,
        10,
        6 + MediaQuery.paddingOf(context).bottom,
      ),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: _Fm.borde)),
        boxShadow: [
          BoxShadow(
            color: Color(0x14081428),
            blurRadius: 10,
            offset: Offset(0, -2),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            margin: const EdgeInsets.only(bottom: 6),
            padding: const EdgeInsets.symmetric(horizontal: 10),
            decoration: BoxDecoration(
              color: const Color(0xFFF1F5FB),
              border: Border.all(color: _Fm.borde),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              children: [
                const Icon(Icons.edit_note, color: _Fm.suave, size: 18),
                const SizedBox(width: 6),
                Expanded(
                  child: TextField(
                    controller: _notas,
                    style: Theme.of(context).textTheme.bodyMedium!
                        .copyWith(fontSize: 13, color: _Fm.tinta),
                    decoration: const InputDecoration(
                      isDense: true,
                      border: InputBorder.none,
                      enabledBorder: InputBorder.none,
                      focusedBorder: InputBorder.none,
                      filled: false,
                      hintText: 'Detalle del documento...',
                      contentPadding: EdgeInsets.symmetric(vertical: 9),
                    ),
                    onChanged: (v) {
                      doc.notas = v;
                      widget.almacen.guardarTabla(
                        widget.config.empresa,
                        'documento',
                        doc.aMapa(),
                      );
                    },
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 7,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFE2EAF5),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '${t.lineas} filas · $arts art.',
                    style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: _Fm.suave,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Row(
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(6),
                  child: InkWell(
                    onTap: vacia ? null : _fmDesglose,
                    child: Row(
                      children: [
                        Container(
                          height: 48,
                          color: const Color(0xFF334155),
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          alignment: Alignment.center,
                          child: const Text(
                            'CRC',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.5,
                            ),
                          ),
                        ),
                        Container(
                          height: 48,
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          decoration: const BoxDecoration(
                            color: Color(0xFF475569),
                            border: Border(
                              right: BorderSide(color: Color(0x26FFFFFF)),
                            ),
                          ),
                          alignment: Alignment.center,
                          child: Text(
                            fmt(t.descuento),
                            style: const TextStyle(
                              color: Color(0xFFFCA5A5),
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                        Expanded(
                          child: Container(
                            height: 48,
                            color: const Color(0xFF475569),
                            padding: const EdgeInsets.symmetric(horizontal: 6),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.end,
                              children: [
                                const Icon(
                                  Icons.expand_less,
                                  color: Color(0x99FFFFFF),
                                  size: 16,
                                ),
                                const SizedBox(width: 4),
                                Flexible(
                                  child: FittedBox(
                                    fit: BoxFit.scaleDown,
                                    child: Text(
                                      fmt(t.total),
                                      style: const TextStyle(
                                        color: Color(0xFFA7F3D0),
                                        fontSize: 18,
                                        fontWeight: FontWeight.w800,
                                        letterSpacing: -0.5,
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 6),
              ficha(
                icoTexto(Icons.save_outlined, 'Guardar', apagado: !guarda),
                const Color(0xFFF59E0B),
                guarda && !vacia
                    ? () => _guardarProforma(cotizacion: true)
                    : null,
                borde: guarda
                    ? const Color(0xFFB45309)
                    : const Color(0xFF6B7280),
                tip: guarda ? null : 'Sin permiso para guardar (104)',
              ),
              const SizedBox(width: 6),
              ficha(
                icoTexto(Icons.send_outlined, 'Procesar'),
                const Color(0xFF10B981),
                vacia ? null : _fmProcesar,
                borde: const Color(0xFF047857),
              ),
            ],
          ),
        ],
      ),
    );
  }

  /// Desglose de totales (fm_totales_detalle_abrir): hoja de abajo.
  void _fmDesglose() {
    final t = doc.totales;
    Widget fila(String a, String b, {bool fuerte = false}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          Text(
            a,
            style: TextStyle(fontSize: fuerte ? 16 : 14, color: _Fm.tinta),
          ),
          const Spacer(),
          Text(
            b,
            style: TextStyle(
              fontSize: fuerte ? 18 : 14,
              fontWeight: fuerte ? FontWeight.w800 : FontWeight.w600,
              color: _Fm.tinta,
            ),
          ),
        ],
      ),
    );
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: _Fm.fondo,
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Row(
                children: [
                  Icon(Icons.receipt_outlined, color: _Fm.navy1),
                  SizedBox(width: 8),
                  Text(
                    'Desglose',
                    style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                      color: _Fm.navy1,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              fila('Subtotal', '₡${fmt(t.subtotal)}'),
              fila('Descuento', '−₡${fmt(t.descuento)}'),
              fila('IVA', '₡${fmt(t.iva)}'),
              if (t.ivaDevuelto > 0)
                fila('IVA devuelto', '−₡${fmt(t.ivaDevuelto)}'),
              const Divider(),
              fila('Total', '₡${fmt(t.total)}', fuerte: true),
            ],
          ),
        ),
      ),
    );
  }
}

/// Barra navy de las pantallas de búsqueda (foto del dueño, 26-nov): [chips] · buscador blanco · lupa · Regresar.
PreferredSizeWidget _fmBarraBusqueda(
  BuildContext context, {
  required TextEditingController q,
  required String pista,
  required ValueChanged<String> alEscribir,
  ValueChanged<String>? alEnter,
  List<Widget> chips = const [],
}) {
  Widget caja(Widget hijo, Color fondo, {VoidCallback? f, double? ancho}) =>
      Material(
        color: fondo,
        borderRadius: BorderRadius.circular(6),
        child: InkWell(
          borderRadius: BorderRadius.circular(6),
          onTap: f,
          child: Container(
            height: 40,
            width: ancho,
            padding: const EdgeInsets.symmetric(horizontal: 10),
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0x66FFFFFF)),
              borderRadius: BorderRadius.circular(6),
            ),
            alignment: Alignment.center,
            child: hijo,
          ),
        ),
      );
  return PreferredSize(
    preferredSize: const Size.fromHeight(60),
    child: Container(
      padding: EdgeInsets.fromLTRB(
        10,
        MediaQuery.paddingOf(context).top + 10,
        10,
        10,
      ),
      decoration: const BoxDecoration(
        gradient: LinearGradient(colors: [_Fm.navy1, _Fm.navy2]),
      ),
      child: Row(
        children: [
          for (final c in chips) ...[c, const SizedBox(width: 6)],
          Expanded(
            child: SizedBox(
              height: 40,
              child: TextField(
                controller: q,
                autofocus: true,
                style: const TextStyle(fontSize: 16, color: _Fm.tinta),
                decoration: InputDecoration(
                  isDense: true,
                  filled: true,
                  fillColor: Colors.white,
                  hintText: pista,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: BorderSide.none,
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(6),
                    borderSide: BorderSide.none,
                  ),
                ),
                onChanged: alEscribir,
                onSubmitted: alEnter,
              ),
            ),
          ),
          const SizedBox(width: 6),
          caja(
            const Icon(Icons.search, color: Colors.white),
            const Color(0x33FFFFFF),
            f: () => alEscribir(q.text),
            ancho: 44,
          ),
          const SizedBox(width: 6),
          caja(
            const Row(
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
            const Color(0xFF991B1B),
            f: () => Navigator.pop(context),
          ),
        ],
      ),
    ),
  );
}

Widget _fmEtiqueta(String t, Color fondo, Color tinta) => Container(
  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
  decoration: BoxDecoration(
    color: fondo,
    borderRadius: BorderRadius.circular(8),
  ),
  child: Text(
    t,
    style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: tinta),
  ),
);

/// Buscar artículos (components/factumovil/busqueda): cada tarjeta con su bodega, su lista de precio, la cantidad y
/// «+ Agregar». La pantalla queda abierta para seguir agregando (como la web).
class _BusquedaMovil extends StatefulWidget {
  final Documento doc;
  final DatosCaja datos;
  final Future<String> Function(Map<String, dynamic>, String, String, int)
  alAgregar;
  const _BusquedaMovil({
    required this.doc,
    required this.datos,
    required this.alAgregar,
  });

  @override
  State<_BusquedaMovil> createState() => _EstadoBusquedaMovil();
}

class _EstadoBusquedaMovil extends State<_BusquedaMovil> {
  final _q = TextEditingController();
  List<Map<String, dynamic>> _res = [];
  final Map<String, String> _bodega = {};
  final Map<String, int> _nivel = {};
  final Map<String, double> _cant = {};

  Documento get doc => widget.doc;
  String get _bodegaEst => '${widget.datos.estacion['bodega'] ?? ''}'.trim();

  void _buscar(String t) => setState(
    () => _res = t.trim().isEmpty ? [] : widget.datos.buscar(t, limite: 60),
  );

  Future<void> _agregar(Map<String, dynamic> a) async {
    final cod = '${a['codigo'] ?? ''}';
    final c = _cant[cod] ?? 1;
    final m = await widget.alAgregar(
      a,
      c == c.truncateToDouble() ? '${c.toInt()}' : '$c',
      _bodega[cod] ?? _bodegaEst,
      _nivel[cod] ?? doc.nivelActual(),
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
    final nivelCli = doc.nivelActual();
    final bodegas = widget.datos.bodegas;
    final puedeBod =
        bodegas.isNotEmpty &&
        !widget.datos.bodegaAtadaEstacion &&
        doc.tienePermiso('033');
    final puedeNivel = doc.tienePermiso('034');
    return Scaffold(
      backgroundColor: _Fm.fondo,
      appBar: _fmBarraBusqueda(
        context,
        q: _q,
        pista: 'Buscar artículo',
        alEscribir: _buscar,
        alEnter: (t) {
          final a = widget.datos.articuloExacto(t);
          if (a != null) _agregar(a);
        },
        chips: [
          _fmEtiqueta('B$_bodegaEst', const Color(0x33FFFFFF), Colors.white),
          _fmEtiqueta(
            'P$nivelCli',
            const Color(0x3314B8A6),
            const Color(0xFF99F6E4),
          ),
        ],
      ),
      body: _res.isEmpty
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  _q.text.trim().isEmpty
                      ? 'Escriba el nombre, el código o las barras.\nBusca en el catálogo del equipo: funciona también sin internet.'
                      : 'No se encontró «${_q.text.trim()}»',
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: _Fm.suave),
                ),
              ),
            )
          : ListView.builder(
              padding: const EdgeInsets.all(10),
              itemCount: _res.length,
              itemBuilder: (_, i) =>
                  _tarjeta(_res[i], bodegas, puedeBod, puedeNivel, nivelCli),
            ),
    );
  }

  Widget _tarjeta(
    Map<String, dynamic> a,
    List<Map<String, dynamic>> bodegas,
    bool puedeBod,
    bool puedeNivel,
    int nivelCli,
  ) {
    final cod = '${a['codigo'] ?? ''}';
    final iva = ((a['tarifa_iva'] as num?) ?? 0).toDouble();
    final nat = '${a['naturaleza'] ?? '1'}';
    final cabys = '${a['cabys'] ?? ''}';
    final servicio =
        nat == '2' ||
        (cabys.isNotEmpty && '6789'.contains(cabys.substring(0, 1)));
    final niveles = <int>[
      for (final n in widget.datos.nivelesPrecio)
        if (doc.precioPara(cod, n)?.$2 == n) n,
    ];
    var nivel = _nivel[cod] ?? nivelCli;
    if (!niveles.contains(nivel) && niveles.isNotEmpty) {
      nivel = doc.precioPara(cod, nivel)?.$2 ?? niveles.first;
    }
    final p = doc.precioPara(cod, nivel);
    final bod = _bodega[cod] ?? _bodegaEst;
    final cant = _cant[cod] ?? 1;
    String txtNivel(int n) {
      final x = doc.precioPara(cod, n);
      if (x == null) return 'P$n';
      return 'P$n - CRC ${fmt(x.$1)} (c/IVA ${fmt(x.$1 * (1 + iva / 100))})';
    }

    InputDecoration combo() => InputDecoration(
      isDense: true,
      filled: true,
      fillColor: const Color(0xFFEFF4FB),
      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: _Fm.borde),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(8),
        borderSide: const BorderSide(color: _Fm.borde),
      ),
    );
    Widget qty(String t, Color fondo, Color tinta, VoidCallback f) => Material(
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
            border: Border.all(color: tinta.withValues(alpha: 0.35)),
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
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
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
                  '${a['nombre'] ?? ''}',
                  style: const TextStyle(fontSize: 15, color: _Fm.tinta),
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    p == null ? 'sin precio' : 'CRC ${fmt(p.$1)}',
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF16A34A),
                    ),
                  ),
                  if (p != null)
                    Text(
                      'c/IVA ${fmt(p.$1 * (1 + iva / 100))}',
                      style: const TextStyle(fontSize: 12, color: _Fm.suave),
                    ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              if (bodegas.isNotEmpty)
                Flexible(
                  child: DropdownButtonFormField<String>(
                    initialValue: bodegas.any((b) => '${b['codigo']}' == bod)
                        ? bod
                        : null,
                    isExpanded: true,
                    isDense: true,
                    decoration: combo(),
                    style: const TextStyle(fontSize: 13, color: _Fm.tinta),
                    items: [
                      for (final b in bodegas)
                        DropdownMenuItem(
                          value: '${b['codigo']}',
                          child: Text(
                            '${b['nombre'] ?? b['codigo']}',
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: puedeBod
                        ? (v) => setState(() => _bodega[cod] = v ?? bod)
                        : null,
                  ),
                ),
              const SizedBox(width: 8),
              _fmEtiqueta(
                cod,
                const Color(0xFFF1F5F9),
                const Color(0xFF475569),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              if (niveles.isNotEmpty)
                Flexible(
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFE8F0FE),
                      border: Border.all(color: const Color(0xFF93B8EF)),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: DropdownButtonHideUnderline(
                      child: DropdownButton<int>(
                        value: niveles.contains(nivel) ? nivel : null,
                        isDense: true,
                        isExpanded: true,
                        style: Theme.of(context).textTheme.bodyMedium!.copyWith(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: const Color(0xFF1E3A8A),
                        ),
                        items: [
                          for (final n in niveles)
                            DropdownMenuItem(
                              value: n,
                              child: Text(
                                txtNivel(n),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                        ],
                        onChanged: puedeNivel
                            ? (n) => setState(() => _nivel[cod] = n ?? nivel)
                            : null,
                      ),
                    ),
                  ),
                ),
              if (servicio) ...[
                const SizedBox(width: 6),
                _fmEtiqueta(
                  'Servicio',
                  const Color(0xFFE0E7FF),
                  const Color(0xFF4338CA),
                ),
              ],
              const SizedBox(width: 6),
              _fmEtiqueta(
                'i${fmt(iva, 0)}%',
                const Color(0xFFFEF3C7),
                const Color(0xFFB45309),
              ),
            ],
          ),
          const Divider(height: 18),
          Row(
            children: [
              Material(
                color: p == null
                    ? const Color(0xFF9CA3AF)
                    : const Color(0xFF16A34A),
                borderRadius: BorderRadius.circular(8),
                child: InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: p == null ? null : () => _agregar(a),
                  child: const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 18, vertical: 9),
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
              ),
              const Spacer(),
              qty(
                '−',
                const Color(0xFFFEE2E2),
                const Color(0xFFDC2626),
                () => setState(() => _cant[cod] = cant > 1 ? cant - 1 : 1),
              ),
              InkWell(
                onTap: () async {
                  final t = await pedirTexto(
                    context,
                    'Cantidad',
                    '${a['nombre'] ?? ''}',
                    fmt(cant, 0),
                  );
                  if (t == null) return;
                  final n = leerMonto(t);
                  if (!n.isNaN && n > 0) setState(() => _cant[cod] = n);
                },
                child: Container(
                  width: 70,
                  height: 40,
                  margin: const EdgeInsets.symmetric(horizontal: 4),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    border: Border.all(color: _Fm.borde),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    fmt(cant, cant == cant.truncateToDouble() ? 0 : 3),
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
              qty(
                '+',
                const Color(0xFFDCFCE7),
                const Color(0xFF16A34A),
                () => setState(() => _cant[cod] = cant + 1),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Seleccionar cliente (components/factumovil/clientes): «Cliente General (SN)» · «Nuevo cliente» · tarjetas.
class _ClientesMovil extends StatefulWidget {
  final DatosCaja datos;
  const _ClientesMovil({required this.datos});

  @override
  State<_ClientesMovil> createState() => _EstadoClientesMovil();
}

class _EstadoClientesMovil extends State<_ClientesMovil> {
  final _q = TextEditingController();
  List<Map<String, dynamic>> _res = [];

  void _buscar(String t) {
    final partes = t
        .trim()
        .toUpperCase()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty)
        .toList();
    final out = <Map<String, dynamic>>[];
    if (partes.isNotEmpty) {
      for (final c in widget.datos.clientes.values) {
        final b =
            '${c['codigo']} ${c['cedula'] ?? ''} ${c['nombre'] ?? ''} ${c['comercial'] ?? ''}'
                .toUpperCase();
        if (partes.every(b.contains)) {
          out.add(c);
          if (out.length >= 80) break;
        }
      }
    }
    setState(() => _res = out);
  }

  @override
  Widget build(BuildContext context) {
    String v(Map c, String k) => '${c[k] ?? ''}'.trim();
    Widget linea(IconData i, String t) => Padding(
      padding: const EdgeInsets.only(right: 14),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(i, size: 15, color: _Fm.suave),
          const SizedBox(width: 4),
          Flexible(
            child: Text(
              t,
              style: const TextStyle(fontSize: 13, color: Color(0xFF334155)),
            ),
          ),
        ],
      ),
    );
    return Scaffold(
      backgroundColor: _Fm.fondo,
      appBar: _fmBarraBusqueda(
        context,
        q: _q,
        pista: 'Buscar cliente',
        alEscribir: _buscar,
      ),
      body: ListView(
        padding: const EdgeInsets.all(10),
        children: [
          Row(
            children: [
              Expanded(
                child: Material(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(8),
                  child: InkWell(
                    borderRadius: BorderRadius.circular(8),
                    onTap: () => Navigator.pop(context, Map.of(clienteContado)),
                    child: Container(
                      height: 64,
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      decoration: BoxDecoration(
                        border: Border.all(color: _Fm.borde),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        children: [
                          Container(
                            width: 38,
                            height: 38,
                            decoration: BoxDecoration(
                              color: const Color(0xFF64748B),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: const Icon(
                              Icons.person_outline,
                              color: Colors.white,
                            ),
                          ),
                          const SizedBox(width: 10),
                          const Expanded(
                            child: Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Cliente General (SN)',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    fontWeight: FontWeight.w700,
                                    color: _Fm.tinta,
                                  ),
                                ),
                                Text(
                                  'Venta sin cliente',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: _Fm.suave,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: SizedBox(
                  height: 64,
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(
                      backgroundColor: const Color(0xFF0D9488),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                    onPressed: () => Navigator.pop(context, {'__nuevo': true}),
                    icon: const Icon(Icons.person_add_alt),
                    label: const Text(
                      'Nuevo cliente',
                      style: TextStyle(fontSize: 15),
                    ),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (_res.isEmpty)
            Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                _q.text.trim().isEmpty
                    ? 'Escriba el nombre, la cédula o el código del cliente.'
                    : 'No se encontró «${_q.text.trim()}»',
                textAlign: TextAlign.center,
                style: const TextStyle(color: _Fm.suave),
              ),
            ),
          for (final c in _res)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Material(
                color: Colors.white,
                borderRadius: BorderRadius.circular(8),
                child: InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: () => Navigator.pop(context, c),
                  child: Container(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                    decoration: BoxDecoration(
                      border: Border.all(color: _Fm.borde),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            _fmEtiqueta(
                              v(c, 'codigo'),
                              const Color(0xFFF1F5F9),
                              const Color(0xFF475569),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                v(c, 'comercial').isNotEmpty
                                    ? v(c, 'comercial')
                                    : v(c, 'nombre'),
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w600,
                                  color: _Fm.tinta,
                                ),
                              ),
                            ),
                            _fmEtiqueta(
                              'P${(num.tryParse(v(c, 'tipo_precio')) ?? 0) > 0 ? v(c, 'tipo_precio') : 1}',
                              const Color(0xFFE8F0FE),
                              const Color(0xFF2563EB),
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Row(
                          children: [
                            if (v(c, 'cedula').isNotEmpty) ...[
                              _fmEtiqueta(
                                v(c, 'cedula'),
                                const Color(0xFFE8F0FE),
                                const Color(0xFF1E3A8A),
                              ),
                              const SizedBox(width: 8),
                            ],
                            Expanded(
                              child: Text(
                                v(c, 'nombre'),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 13,
                                  color: Color(0xFF475569),
                                ),
                              ),
                            ),
                          ],
                        ),
                        if (v(c, 'email_factura').isNotEmpty ||
                            v(c, 'telefonos').isNotEmpty) ...[
                          const Divider(height: 14),
                          Wrap(
                            runSpacing: 4,
                            children: [
                              if (v(c, 'email_factura').isNotEmpty)
                                linea(
                                  Icons.mail_outline,
                                  v(c, 'email_factura'),
                                ),
                              if (v(c, 'telefonos').isNotEmpty)
                                linea(Icons.phone_outlined, v(c, 'telefonos')),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
