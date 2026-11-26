/// Diálogos de la caja (#3957): cobro (efectivo / mixto), editar línea, clave de supervisor, cliente, ventas.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../caja/cajeros.dart';
import '../caja/datos_caja.dart';
import '../caja/documento.dart';
import '../datos/conexion.dart';
import '../motor/linea.dart';
import '../motor/redondeo.dart';
import 'tema.dart';

/// Dueño (26-nov, #3957): miles con COMA y decimales con PUNTO, como la web → «12,601.27».
String fmt(num n, [int d = 2]) {
  final s = redondear(n, d).abs().toStringAsFixed(d);
  final p = s.split('.');
  final ent = p[0].replaceAllMapped(
    RegExp(r'\B(?=(\d{3})+(?!\d))'),
    (_) => ',',
  );
  return '${n < 0 ? '-' : ''}${d > 0 ? '$ent.${p[1]}' : ent}';
}

/// «12,500.50» / «12500.5» / «12,500» → número. Si alguien escribe «12,5» (coma como decimal) también se entiende.
double leerMonto(String t) {
  var s = t.trim().replaceAll(RegExp(r'[₡\s]'), '');
  if (s.contains('.')) {
    s = s.replaceAll(',', '');
  } else if (RegExp(r'^\d{1,3}(,\d{3})+$').hasMatch(s)) {
    s = s.replaceAll(',', '');
  } else {
    s = s.replaceAll(',', '.');
  }
  return double.tryParse(s) ?? double.nan;
}

Widget tituloDialogo(String t, {String? codigo, IconData? icono}) => Row(
  children: [
    if (icono != null) ...[
      Icon(icono, color: Marca.azul),
      const SizedBox(width: 10),
    ],
    Expanded(child: Text(t)),
    if (codigo != null)
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: Marca.fondo,
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(
          codigo,
          style: const TextStyle(
            fontSize: 11,
            color: Marca.tintaSuave,
            fontWeight: FontWeight.w500,
          ),
        ),
      ),
  ],
);

// ════════════ COBRO ════════════

class ResultadoCobro {
  final List<Map<String, dynamic>> pagos;
  final double vuelto;
  final String tipoPago; // 'contado' | 'credito'
  final int diasCredito;

  /// FactuMóvil (VP-001): «No Imprime» → false; copias elegidas a mano (null = las de los parámetros 98/99).
  final bool imprimir;
  final int? copias;
  const ResultadoCobro(
    this.pagos,
    this.vuelto, {
    this.tipoPago = 'contado',
    this.diasCredito = 0,
    this.imprimir = true,
    this.copias,
  });
}

/// Crédito del cliente para el cobro: si se permite (motivo si no), sus días, y cómo preguntarle al servidor.
class InfoCredito {
  final bool permitido;
  final String motivo;
  final int dias;
  final Future<Map<String, dynamic>?> Function()? revisar;
  const InfoCredito({
    this.permitido = false,
    this.motivo = '',
    this.dias = 0,
    this.revisar,
  });
}

/// Cobro: arranca con [medioInicial] por el total. Efectivo → «Recibido» con billetes rápidos y vuelto; se pueden sumar
/// otros medios (pago mixto). El vuelto solo sale del efectivo (como la web).
Future<ResultadoCobro?> dialogoCobro(
  BuildContext context, {
  required double total,
  required List<MedioPago> medios,
  required String medioInicial,
  InfoCredito credito = const InfoCredito(),
}) => showDialog<ResultadoCobro>(
  context: context,
  builder: (_) => _Cobro(
    total: total,
    medios: medios,
    medioInicial: medioInicial,
    credito: credito,
  ),
);

class _Pago {
  final MedioPago medio;
  String cuenta;
  final TextEditingController monto, comprobante = TextEditingController();
  _Pago(this.medio, double m)
    : cuenta = medio.cuentas.length == 1 ? medio.cuentas.first : '',
      monto = TextEditingController(text: m > 0 ? fmt(m) : '');
}

class _Cobro extends StatefulWidget {
  final double total;
  final List<MedioPago> medios;
  final String medioInicial;
  final InfoCredito credito;
  const _Cobro({
    required this.total,
    required this.medios,
    required this.medioInicial,
    required this.credito,
  });
  @override
  State<_Cobro> createState() => _EstadoCobro();
}

class _EstadoCobro extends State<_Cobro> {
  final List<_Pago> pagos = [];
  final _foco = FocusNode();
  String tipo = 'contado';
  bool revisando = false;
  Map<String, dynamic>?
  servidor; // respuesta de credito_revisar (o {'sinConexion': true})

  Future<void> _elegirCredito() async {
    if (!widget.credito.permitido) return;
    setState(() {
      tipo = 'credito';
      revisando = true;
      servidor = null;
    });
    final r = widget.credito.revisar == null
        ? null
        : await widget.credito.revisar!();
    if (!mounted) return;
    setState(() {
      servidor = r ?? {'sinConexion': true};
      revisando = false;
    });
  }

  String get _impideCredito {
    if (!widget.credito.permitido) return widget.credito.motivo;
    if (revisando) return 'Revisando el saldo y el límite de crédito…';
    final s = servidor;
    if (s != null && s['puede'] == false) {
      return '${s['motivo'] ?? 'No se puede vender a crédito.'} Para venderle a crédito igual, quien tenga el permiso 314 lo autoriza en la ficha del cliente → Crédito → Autorizar crédito.';
    }
    return '';
  }

  @override
  void initState() {
    super.initState();
    final m =
        widget.medios
            .where((x) => x.codigo == widget.medioInicial)
            .firstOrNull ??
        widget.medios.first;
    pagos.add(_Pago(m, widget.total));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _foco.requestFocus();
      pagos.first.monto.selection = TextSelection(
        baseOffset: 0,
        extentOffset: pagos.first.monto.text.length,
      );
    });
  }

  List<Map<String, dynamic>> get _mapas => [
    for (final p in pagos)
      {
        'medio': p.medio.codigo,
        'cuenta': p.cuenta,
        'monto': leerMonto(p.monto.text).isNaN ? 0.0 : leerMonto(p.monto.text),
        'comprobante': p.comprobante.text.trim(),
      },
  ];

  String get _impide {
    if (tipo == 'credito') return _impideCredito;
    for (final p in pagos) {
      if (p.medio.cuentas.length > 1 && p.cuenta.isEmpty)
        return 'Elija la cuenta de ${p.medio.descripcion}.';
    }
    return cuentasCobro(widget.total, _mapas).impide;
  }

  void _guardar() {
    if (_impide.isNotEmpty) return;
    if (tipo == 'credito') {
      Navigator.pop(
        context,
        ResultadoCobro(
          const [],
          0,
          tipoPago: 'credito',
          diasCredito: widget.credito.dias,
        ),
      );
      return;
    }
    final c = cuentasCobro(widget.total, _mapas);
    Navigator.pop(
      context,
      ResultadoCobro(pagosFinales(_mapas, c.vuelto), c.vuelto),
    );
  }

  void _sumarEfectivo(double billete) {
    final e = pagos.where((p) => p.medio.codigo == '01').firstOrNull;
    if (e == null) return;
    final actual = leerMonto(e.monto.text);
    // El primer billete reemplaza el «exacto»; los siguientes se suman.
    final base = (actual.isNaN || (actual - widget.total).abs() < 0.005)
        ? 0.0
        : actual;
    setState(() => e.monto.text = fmt(base + billete));
  }

  @override
  Widget build(BuildContext context) {
    final c = cuentasCobro(widget.total, _mapas);
    final impide = _impide;
    final hayEfectivo = pagos.any((p) => p.medio.codigo == '01');
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.f4): _guardar,
      }, // como la web: en el cobro, F4 guarda
      child: AlertDialog(
        title: tituloDialogo(
          'Cobrar',
          codigo: 'MV-COBRO',
          icono: Icons.point_of_sale,
        ),
        content: SizedBox(
          width: 520,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  padding: const EdgeInsets.all(18),
                  decoration: BoxDecoration(
                    color: Marca.azul,
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Row(
                    children: [
                      const Text(
                        'TOTAL',
                        style: TextStyle(
                          color: Colors.white70,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 1.2,
                        ),
                      ),
                      const Spacer(),
                      Text(
                        '₡${fmt(widget.total)}',
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 32,
                          fontWeight: FontWeight.w800,
                          letterSpacing: -0.5,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                SegmentedButton<String>(
                  segments: [
                    const ButtonSegment(
                      value: 'contado',
                      label: Text('Contado'),
                      icon: Icon(Icons.payments_outlined),
                    ),
                    ButtonSegment(
                      value: 'credito',
                      label: const Text('Crédito'),
                      icon: const Icon(Icons.event_note_outlined),
                      enabled: widget.credito.permitido,
                    ),
                  ],
                  selected: {tipo},
                  onSelectionChanged: (x) => x.first == 'credito'
                      ? _elegirCredito()
                      : setState(() => tipo = 'contado'),
                ),
                if (!widget.credito.permitido)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Text(
                      widget.credito.motivo,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Marca.tintaSuave,
                      ),
                    ),
                  ),
                const SizedBox(height: 16),
                if (tipo == 'credito')
                  _bloqueCredito()
                else ...[
                  for (var i = 0; i < pagos.length; i++) _filaPago(i),
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final m in widget.medios)
                        ActionChip(
                          avatar: Icon(
                            Marca.iconoMedio(m.codigo),
                            size: 18,
                            color: Marca.medio(m.codigo),
                          ),
                          label: Text('+ ${m.descripcion}'),
                          onPressed: () =>
                              setState(() => pagos.add(_Pago(m, c.falta))),
                        ),
                    ],
                  ),
                  if (hayEfectivo) ...[
                    const SizedBox(height: 14),
                    const Text(
                      'Billetes',
                      style: TextStyle(
                        fontSize: 12,
                        color: Marca.tintaSuave,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final b in const [
                          1000.0,
                          2000.0,
                          5000.0,
                          10000.0,
                          20000.0,
                          50000.0,
                        ])
                          OutlinedButton(
                            onPressed: () => _sumarEfectivo(b),
                            style: OutlinedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 14,
                                vertical: 12,
                              ),
                            ),
                            child: Text('₡${fmt(b, 0)}'),
                          ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 16),
                ],
                if (tipo == 'contado')
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: c.vuelto > 0
                          ? const Color(0xFFECFDF5)
                          : c.falta > 0
                          ? const Color(0xFFFFF7ED)
                          : Marca.fondo,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        Text(
                          c.vuelto > 0
                              ? 'VUELTO'
                              : c.falta > 0
                              ? 'FALTA'
                              : 'EXACTO',
                          style: TextStyle(
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1,
                            color: c.vuelto > 0
                                ? Marca.verdeOscuro
                                : c.falta > 0
                                ? Marca.ambar
                                : Marca.tintaSuave,
                          ),
                        ),
                        const Spacer(),
                        Text(
                          '₡${fmt(c.vuelto > 0 ? c.vuelto : c.falta)}',
                          style: TextStyle(
                            fontSize: 26,
                            fontWeight: FontWeight.w800,
                            color: c.vuelto > 0
                                ? Marca.verdeOscuro
                                : c.falta > 0
                                ? Marca.ambar
                                : Marca.tinta,
                          ),
                        ),
                      ],
                    ),
                  ),
                if (impide.isNotEmpty && (tipo == 'credito' || c.falta == 0))
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Text(
                      impide,
                      style: const TextStyle(color: Marca.rojo),
                    ),
                  ),
              ],
            ),
          ),
        ),
        actionsPadding: const EdgeInsets.fromLTRB(24, 0, 24, 20),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar'),
          ),
          FilledButton.icon(
            style: FilledButton.styleFrom(backgroundColor: Marca.verde),
            onPressed: impide.isEmpty ? _guardar : null,
            icon: const Icon(Icons.check_circle_outline),
            label: const Text('Procesar factura  (F4)'),
          ),
        ],
      ),
    );
  }

  /// El crédito del cliente en casillas (como htmlCredito de la web): estado arriba, la cuenta de esta venta abajo.
  Widget _bloqueCredito() {
    final s = servidor;
    Widget casilla(String t, String v, {Color? color}) => Expanded(
      child: Container(
        padding: const EdgeInsets.all(10),
        margin: const EdgeInsets.only(right: 6, bottom: 6),
        decoration: BoxDecoration(
          color: (color ?? Marca.tintaSuave).withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              t,
              style: const TextStyle(
                fontSize: 11,
                color: Marca.tintaSuave,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              v,
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: color ?? Marca.tinta,
              ),
            ),
          ],
        ),
      ),
    );
    double n(String k) => ((s?[k] as num?) ?? 0).toDouble();
    final filas = <Widget>[
      Row(
        children: [
          casilla('Plazo', '${widget.credito.dias} días'),
          if (s != null && s['sinConexion'] != true) ...[
            casilla('Límite', '₡${fmt(n('limite'))}'),
            casilla('Saldo (debe)', '₡${fmt(n('saldo'))}'),
            casilla(
              'Vencido',
              '₡${fmt(n('vencido'))}',
              color: n('vencido') > 0 ? Marca.rojo : null,
            ),
          ],
        ],
      ),
    ];
    if (s != null && s['sinConexion'] != true) {
      final queda = n('disponible') - widget.total;
      filas.add(
        Row(
          children: [
            casilla('Disponible', '₡${fmt(n('disponible'))}'),
            casilla(
              '− Esta factura',
              '₡${fmt(widget.total)}',
              color: Marca.azul,
            ),
            casilla(
              '= Le queda',
              '₡${fmt(queda)}',
              color: queda < 0 ? Marca.rojo : Marca.verdeOscuro,
            ),
          ],
        ),
      );
    }
    String nota = '';
    if (revisando) nota = 'Revisando el saldo y el límite con el servidor…';
    if (s?['sinConexion'] == true)
      nota = 'Sin internet: no se revisó el saldo ni el límite.';
    if (s?['autorizado'] == true)
      nota = 'Crédito autorizado por un supervisor.';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ...filas,
        if (nota.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              nota,
              style: const TextStyle(fontSize: 13, color: Marca.tintaSuave),
            ),
          ),
      ],
    );
  }

  Widget _filaPago(int i) {
    final p = pagos[i];
    final efectivo = p.medio.codigo == '01';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 44,
            height: 52,
            decoration: BoxDecoration(
              color: Marca.medio(p.medio.codigo).withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(
              Marca.iconoMedio(p.medio.codigo),
              color: Marca.medio(p.medio.codigo),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            flex: 3,
            child: TextField(
              controller: p.monto,
              focusNode: i == 0 ? _foco : null,
              textAlign: TextAlign.right,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
              decoration: InputDecoration(
                labelText: efectivo
                    ? 'Recibido en efectivo'
                    : p.medio.descripcion,
                prefixText: '₡ ',
              ),
              onChanged: (_) => setState(() {}),
              onSubmitted: (_) => _guardar(),
            ),
          ),
          if (!efectivo) ...[
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: TextField(
                controller: p.comprobante,
                decoration: const InputDecoration(labelText: 'Comprobante'),
              ),
            ),
          ],
          if (p.medio.cuentas.length > 1) ...[
            const SizedBox(width: 8),
            Expanded(
              flex: 2,
              child: DropdownButtonFormField<String>(
                initialValue: p.cuenta.isEmpty ? null : p.cuenta,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Cuenta'),
                items: [
                  for (final x in p.medio.cuentas)
                    DropdownMenuItem(
                      value: x,
                      child: Text(x, overflow: TextOverflow.ellipsis),
                    ),
                ],
                onChanged: (v) => setState(() => p.cuenta = v ?? ''),
              ),
            ),
          ],
          if (pagos.length > 1)
            IconButton(
              onPressed: () => setState(() => pagos.removeAt(i)),
              icon: const Icon(Icons.close, color: Marca.tintaSuave),
            ),
        ],
      ),
    );
  }
}

// ════════════ SUPERVISOR ════════════

/// Pide la clave de un supervisor con el permiso. → el que autorizó, 'alternativa' (usar la opción sin permiso) o null.
Future<Object?> dialogoSupervisor(
  BuildContext context,
  Cajeros cajeros,
  Validacion v,
) {
  final clave = TextEditingController();
  String error = '';
  return showDialog<Object>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        void autorizar() {
          final (c, motivo) = cajeros.identificarPorClave(
            clave.text,
            v.permiso,
          );
          if (motivo == null && c != null) {
            Navigator.pop(ctx, c);
          } else {
            set(() => error = motivo ?? 'Clave incorrecta');
            clave.selection = TextSelection(
              baseOffset: 0,
              extentOffset: clave.text.length,
            );
          }
        }

        return AlertDialog(
          title: tituloDialogo(
            'Autorización',
            codigo: 'MV-109 · ${v.permiso}',
            icono: Icons.admin_panel_settings_outlined,
          ),
          content: SizedBox(
            width: 420,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFF7ED),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    v.motivo,
                    style: const TextStyle(color: Color(0xFF9A3412)),
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: clave,
                  autofocus: true,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Clave del supervisor',
                    prefixIcon: Icon(Icons.lock_outline),
                  ),
                  onSubmitted: (_) => autorizar(),
                ),
                if (error.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Text(
                      error,
                      style: const TextStyle(color: Marca.rojo),
                    ),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancelar'),
            ),
            if (v.alternativa != null)
              OutlinedButton(
                onPressed: () => Navigator.pop(ctx, 'alternativa'),
                child: Text(v.alternativaTexto),
              ),
            FilledButton(onPressed: autorizar, child: const Text('Autorizar')),
          ],
        );
      },
    ),
  );
}

// ════════════ EDITAR LÍNEA ════════════

/// MV-108: cantidad, precio, descuento (% o ₡) y bonificación, con las reglas de FactuDesk y la clave de supervisor.
/// Devuelve true si cambió la línea.
Future<bool> dialogoLinea(
  BuildContext context,
  Documento doc,
  Cajeros cajeros,
  int indice,
) async {
  final l = doc.lineas[indice];
  final cant = TextEditingController(
    text: fmt(l.cantidad, l.fraccionable != 0 ? 3 : 0).replaceAll(',', ''),
  );
  final precio = TextEditingController(
    text: fmt(l.precio, doc.dec.precio).replaceAll(',', ''),
  );
  var modo = l.descMonto != null ? 'monto' : 'pct';
  final valor = TextEditingController(
    text: l.descMonto != null
        ? fmt(l.descMonto!)
        : (l.descuento > 0 ? fmt(l.descuento, doc.dec.descPct) : ''),
  );
  var bonif = l.bonificacion;
  String error = '';
  final verUtil = doc.tienePermiso('064'),
      editaPrecio = doc.tienePermiso('024');
  // FactuSuper y FactuMóvil (dueño, 26-nov): bodega y lista de precio POR LÍNEA (editar.js: 033 / 034 / param 251).
  final bodegas = doc.datos.bodegas;
  var bodega = doc.bodegaDe(l);
  final atada = doc.datos.bodegaAtadaEstacion,
      cambiaNivel = doc.tienePermiso('034');
  final r = await showDialog<CambiosLinea>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        CambiosLinea? leer() {
          final c = leerMonto(cant.text),
              p = leerMonto(precio.text),
              v = valor.text.trim().isEmpty ? 0.0 : leerMonto(valor.text);
          if (c.isNaN || p.isNaN || v.isNaN) return null;
          return CambiosLinea(
            cantidad: c,
            precio: p,
            modo: modo,
            valor: v,
            bonificacion: bonif,
            bodega: bodegas.isNotEmpty ? bodega : null,
          );
        }

        // Vista previa con una copia de la línea.
        final c = leer();
        double? total;
        if (c != null && c.cantidad > 0 && c.precio > 0) {
          final copia = lineaDesde(lineaAMapa(l));
          copia
            ..cantidad = c.cantidad
            ..precio = c.precio
            ..bonificacion = c.bonificacion;
          if (c.bonificacion) {
            copia.descuento = 100;
            copia.descMonto = null;
          } else if (c.modo == 'monto') {
            copia.descMonto = c.valor;
          } else {
            copia.descuento = c.valor;
            copia.descMonto = null;
          }
          total = calcular(copia, doc.dec, doc.medioPago).total;
        }
        return AlertDialog(
          title: tituloDialogo(
            l.nombre,
            codigo: 'MV-108',
            icono: Icons.edit_note,
          ),
          content: SizedBox(
            width: 460,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  '${l.codigo}${l.barra.isEmpty ? '' : ' · ${l.barra}'} · precio ${l.nivel}',
                  style: const TextStyle(color: Marca.tintaSuave, fontSize: 13),
                ),
                ...[
                  const SizedBox(height: 12),
                  _selectoresMovil(
                    doc: doc,
                    l: l,
                    bodegas: bodegas,
                    bodega: bodega,
                    atada: atada,
                    cambiaNivel: cambiaNivel,
                    alBodega: (b) => set(() => bodega = b),
                    alNivel: (n) {
                      // Acción INMEDIATA, como la web (cotizacion_tipoprecio_cambiar): toma el precio del nivel
                      // y el descuento vuelve a 0 (+ el automático del nivel).
                      final (bien, motivo, _) = doc.cambiarNivel(indice, n);
                      set(() {
                        if (!bien) {
                          error = 'El artículo no tiene precio en P$n';
                          return;
                        }
                        error = '';
                        precio.text = fmt(
                          l.precio,
                          doc.dec.precio,
                        ).replaceAll(',', '');
                        modo = 'pct';
                        bonif = false;
                        valor.text = l.descuento > 0
                            ? fmt(l.descuento, doc.dec.descPct)
                            : '';
                      });
                    },
                  ),
                ],
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: cant,
                        autofocus: true,
                        decoration: const InputDecoration(
                          labelText: 'Cantidad',
                        ),
                        onChanged: (_) => set(() {}),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        controller: precio,
                        decoration: InputDecoration(
                          labelText: 'Precio (sin IVA)',
                          prefixText: '₡ ',
                          helperText: editaPrecio
                              ? null
                              : 'Requiere permiso 024 o supervisor',
                        ),
                        onChanged: (_) => set(() {}),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: valor,
                        enabled: !bonif,
                        decoration: InputDecoration(
                          labelText: 'Descuento',
                          suffixText: modo == 'pct' ? '%' : null,
                          prefixText: modo == 'monto' ? '₡ ' : null,
                        ),
                        onChanged: (_) => set(() {}),
                      ),
                    ),
                    const SizedBox(width: 12),
                    SegmentedButton<String>(
                      segments: const [
                        ButtonSegment(value: 'pct', label: Text('%')),
                        ButtonSegment(value: 'monto', label: Text('₡')),
                      ],
                      selected: {modo},
                      onSelectionChanged: bonif
                          ? null
                          : (s) => set(() => modo = s.first),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Bonificación (regalo, 100 %)'),
                  value: bonif,
                  onChanged: (v) => set(() => bonif = v),
                ),
                const Divider(),
                if (verUtil && l.costo > 0 && c != null && c.precio > 0)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Row(
                      children: [
                        Text(
                          'Costo ₡${fmt(l.costo)}',
                          style: const TextStyle(
                            color: Marca.tintaSuave,
                            fontSize: 13,
                          ),
                        ),
                        const Spacer(),
                        Builder(
                          builder: (_) {
                            final d = c.bonificacion
                                ? 100.0
                                : c.modo == 'monto'
                                ? (c.cantidad * c.precio > 0
                                      ? c.valor / (c.cantidad * c.precio) * 100
                                      : 0.0)
                                : c.valor;
                            final u = utilidad(c.precio, d, l.costo);
                            return Text(
                              'Utilidad ${fmt(u, 1)} %${l.utilMin > 0 ? ' (mín. ${fmt(l.utilMin, 1)} %)' : ''}',
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                                color: u < l.utilMin
                                    ? Marca.rojo
                                    : Marca.verdeOscuro,
                              ),
                            );
                          },
                        ),
                      ],
                    ),
                  ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Text(
                      'Total de la línea',
                      style: TextStyle(color: Marca.tintaSuave),
                    ),
                    const Spacer(),
                    Text(
                      total == null ? '—' : '₡${fmt(total)}',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ],
                ),
                if (error.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Text(
                      error,
                      style: const TextStyle(color: Marca.rojo),
                    ),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancelar'),
            ),
            FilledButton(
              onPressed: () {
                final x = leer();
                if (x == null) return set(() => error = 'Revise los números.');
                Navigator.pop(ctx, x);
              },
              child: const Text('Aplicar'),
            ),
          ],
        );
      },
    ),
  );
  if (r == null || !context.mounted) return false;
  return aplicarCambiosLinea(context, doc, cajeros, l, r);
}

/// Las reglas de MV-108, en orden (FactuSuper y el editor de FactuMóvil MFM-EDIT): cada permiso que falta lo puede
/// autorizar un supervisor; «SI» para monto alto o bajo el costo. → true si la línea cambió.
Future<bool> aplicarCambiosLinea(
  BuildContext context,
  Documento doc,
  Cajeros cajeros,
  Linea l,
  CambiosLinea r,
) async {
  var cambios = r;
  final auth = <String, String>{};
  for (var vuelta = 0; vuelta < 12; vuelta++) {
    final v = doc.validarLinea(l, cambios, auth.keys.toSet());
    if (v.ok) {
      doc.aplicarLinea(l, cambios, auth);
      return true;
    }
    if (!context.mounted) return false;
    if (v.error.isNotEmpty) {
      await avisoDialogo(context, 'No se puede', v.error);
      return false;
    }
    if (v.confirmarSi) {
      final costo = v.confirma == 'costo';
      final si = await pedirTexto(
        context,
        costo ? 'Bajo el costo (021)' : 'Monto alto',
        v.motivo,
        'Escriba SI',
      );
      if (si?.trim().toUpperCase() != 'SI') return false;
      cambios = costo
          ? cambios.con(costoConfirmado: true)
          : cambios.con(montoConfirmado: true);
      continue;
    }
    final a = await dialogoSupervisor(context, cajeros, v);
    if (a == null) return false;
    if (a == 'alternativa') {
      cambios = v.alternativa!;
    } else if (a is Cajero) {
      auth[v.permiso] = a.usuario;
    }
  }
  return false;
}

/// MV-108 (FactuSuper y FactuMóvil): Bodega (033 · param 251) y Lista de precio P1…Pn (034) de la línea, deshabilitados (no ocultos) sin permiso.
Widget _selectoresMovil({
  required Documento doc,
  required Linea l,
  required List<Map<String, dynamic>> bodegas,
  required String bodega,
  required bool atada,
  required bool cambiaNivel,
  required void Function(String) alBodega,
  required void Function(int) alNivel,
}) {
  final niveles = {...doc.datos.nivelesPrecio, l.nivel}.toList()..sort();
  final codigos = [for (final b in bodegas) '${b['codigo'] ?? ''}'];
  return Row(
    children: [
      if (bodegas.isNotEmpty)
        Expanded(
          flex: 3,
          child: DropdownButtonFormField<String>(
            initialValue: codigos.contains(bodega) ? bodega : null,
            isExpanded: true,
            decoration: InputDecoration(
              labelText: 'Bodega',
              helperText: atada
                  ? 'Atada a la estación'
                  : (doc.tienePermiso('033')
                        ? null
                        : 'Requiere permiso 033 o supervisor'),
            ),
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
            onChanged: atada ? null : (v) => v == null ? null : alBodega(v),
          ),
        ),
      if (bodegas.isNotEmpty) const SizedBox(width: 12),
      Expanded(
        flex: 2,
        child: DropdownButtonFormField<int>(
          initialValue: l.nivel,
          isExpanded: true,
          decoration: InputDecoration(
            labelText: 'Lista de precio',
            helperText: cambiaNivel ? null : 'Sin permiso (034)',
          ),
          items: [
            for (final n in niveles)
              DropdownMenuItem(
                value: n,
                child: Text(_etiquetaNivel(doc, l, n)),
              ),
          ],
          onChanged: cambiaNivel
              ? (n) => n == null || n == l.nivel ? null : alNivel(n)
              : null,
        ),
      ),
    ],
  );
}

/// «P2 - 5,000.00» (precio del nivel con IVA, como la web #219); «P2» si el nivel no tiene precio.
String _etiquetaNivel(Documento doc, Linea l, int n) {
  final p = doc.precioPara(l.codigo, n);
  if (p == null || p.$2 != n) return 'P$n';
  return 'P$n - ${fmt(p.$1 * (1 + l.tarifa / 100))}';
}

// ════════════ CLIENTE ════════════

Future<Map<String, dynamic>?> dialogoCliente(
  BuildContext context,
  DatosCaja datos,
) {
  final q = TextEditingController();
  List<Map<String, dynamic>> res = [];
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        void buscar(String t) {
          final partes = t
              .trim()
              .toUpperCase()
              .split(RegExp(r'\s+'))
              .where((p) => p.isNotEmpty)
              .toList();
          if (partes.isEmpty) return set(() => res = []);
          final out = <Map<String, dynamic>>[];
          for (final c in datos.clientes.values) {
            final b =
                '${c['codigo']} ${c['cedula'] ?? ''} ${c['nombre'] ?? ''} ${c['comercial'] ?? ''}'
                    .toUpperCase();
            if (partes.every(b.contains)) {
              out.add(c);
              if (out.length >= 80) break;
            }
          }
          set(() => res = out);
        }

        return AlertDialog(
          title: tituloDialogo(
            'Cliente',
            codigo: 'MCL',
            icono: Icons.person_search_outlined,
          ),
          content: SizedBox(
            width: 560,
            height: 460,
            child: Column(
              children: [
                TextField(
                  controller: q,
                  autofocus: true,
                  decoration: const InputDecoration(
                    hintText: 'Nombre, cédula o código',
                    prefixIcon: Icon(Icons.search),
                  ),
                  onChanged: buscar,
                  onSubmitted: (_) {
                    if (res.length == 1) Navigator.pop(ctx, res.first);
                  },
                ),
                const SizedBox(height: 10),
                Expanded(
                  child: res.isEmpty
                      ? Center(
                          child: Text(
                            q.text.isEmpty
                                ? 'Escriba para buscar en ${datos.clientes.length} clientes'
                                : 'Sin resultados',
                            style: const TextStyle(color: Marca.tintaSuave),
                          ),
                        )
                      : ListView.separated(
                          itemCount: res.length,
                          separatorBuilder: (_, __) => const Divider(),
                          itemBuilder: (_, i) {
                            final c = res[i];
                            return ListTile(
                              leading: CircleAvatar(
                                backgroundColor: Marca.azulClaro,
                                child: Text(
                                  '${c['nombre'] ?? '?'}'.trim().isEmpty
                                      ? '?'
                                      : '${c['nombre']}'.trim()[0],
                                  style: const TextStyle(
                                    color: Marca.azul,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                              title: Text(
                                '${c['nombre'] ?? ''}',
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              subtitle: Text(
                                '${c['cedula'] ?? ''} · ${c['codigo']}${'${c['tipo_precio'] ?? 0}' != '0' ? ' · precio ${c['tipo_precio']}' : ''}',
                              ),
                              onTap: () => Navigator.pop(ctx, c),
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancelar'),
            ),
            OutlinedButton.icon(
              onPressed: () =>
                  Navigator.pop(ctx, Map<String, dynamic>.of(clienteContado)),
              icon: const Icon(Icons.person_outline),
              label: const Text('Cliente contado'),
            ),
          ],
        );
      },
    ),
  );
}

// ════════════ VARIOS ════════════

Future<void> avisoDialogo(BuildContext context, String titulo, String texto) =>
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(titulo),
        content: SizedBox(width: 420, child: Text(texto)),
        actions: [
          FilledButton(
            autofocus: true,
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Entendido'),
          ),
        ],
      ),
    );

Future<String?> pedirTexto(
  BuildContext context,
  String titulo,
  String texto,
  String etiqueta,
) {
  final c = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(titulo),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(texto),
            const SizedBox(height: 12),
            TextField(
              controller: c,
              autofocus: true,
              decoration: InputDecoration(labelText: etiqueta),
              onSubmitted: (t) => Navigator.pop(ctx, t),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(ctx, c.text),
          child: const Text('Aceptar'),
        ),
      ],
    ),
  );
}

Future<bool> confirmar(
  BuildContext context,
  String titulo,
  String texto,
  String si,
) async =>
    await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(titulo),
        content: Text(texto),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('No'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Marca.rojo),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(si),
          ),
        ],
      ),
    ) ==
    true;

/// VUELTO en grande (para que el cajero no se equivoque).
Future<void> dialogoVuelto(BuildContext context, double vuelto) =>
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        contentPadding: const EdgeInsets.fromLTRB(32, 32, 32, 8),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.check_circle, color: Marca.verde, size: 56),
            const SizedBox(height: 12),
            const Text(
              'VUELTO',
              style: TextStyle(
                letterSpacing: 2,
                fontWeight: FontWeight.w700,
                color: Marca.tintaSuave,
              ),
            ),
            Text(
              '₡${fmt(vuelto)}',
              style: const TextStyle(
                fontSize: 48,
                fontWeight: FontWeight.w800,
                color: Marca.verdeOscuro,
                letterSpacing: -1,
              ),
            ),
          ],
        ),
        actions: [
          FilledButton(
            autofocus: true,
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Listo  (Enter)'),
          ),
        ],
      ),
    );

/// Lista de ventas de esta caja (MV-107).
Future<void> dialogoVentas(
  BuildContext context,
  List<Map<String, dynamic>> ventas,
  VoidCallback enviar, {
  void Function(Map<String, dynamic> venta)? reimprimir,
}) {
  const nombres = {
    'pendiente': 'Pendiente',
    'en_proceso': 'Enviando',
    'error': 'Reintentará',
    'procesada': 'Facturada',
    'rechazada': 'Rechazada',
  };
  Color color(String e) => switch (e) {
    'procesada' => Marca.verde,
    'rechazada' => Marca.rojo,
    'error' => Marca.ambar,
    _ => Marca.azulMedio,
  };
  final lista = ventas.reversed.toList();
  return showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: tituloDialogo(
        'Ventas de esta caja',
        codigo: 'MV-107',
        icono: Icons.receipt_long_outlined,
      ),
      content: SizedBox(
        width: 640,
        height: 460,
        child: lista.isEmpty
            ? const Center(
                child: Text(
                  'Todavía no hay ventas.',
                  style: TextStyle(color: Marca.tintaSuave),
                ),
              )
            : ListView.separated(
                itemCount: lista.length,
                separatorBuilder: (_, __) => const Divider(),
                itemBuilder: (_, i) {
                  final v = lista[i];
                  final e = '${v['estado']}';
                  final fac = v['factura'] is Map
                      ? (v['factura'] as Map)
                      : null;
                  return ListTile(
                    title: Text(
                      '₡${fmt((v['total'] as num?) ?? 0)}',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    subtitle: Text(
                      [
                        '${v['idProceso']}',
                        '${(v['cliente'] as Map?)?['nombre'] ?? ''}',
                        if (fac != null)
                          'Factura ${fac['numero'] ?? fac['consecutivo'] ?? ''}',
                        if (v['error'] is Map)
                          '${(v['error'] as Map)['mensaje']}',
                      ].where((x) => x.isNotEmpty).join(' · '),
                    ),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (v['impresionLocal'] is Map)
                          Padding(
                            padding: const EdgeInsets.only(right: 8),
                            child: Text(
                              (v['impresionLocal'] as Map)['ok'] == true
                                  ? '✔ provisional'
                                  : '✖ provisional no salió',
                              style: TextStyle(
                                fontSize: 12,
                                color:
                                    (v['impresionLocal'] as Map)['ok'] == true
                                    ? Marca.verde
                                    : Marca.rojo,
                              ),
                            ),
                          ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: color(e).withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Text(
                            nombres[e] ?? e,
                            style: TextStyle(
                              color: color(e),
                              fontWeight: FontWeight.w600,
                              fontSize: 12,
                            ),
                          ),
                        ),
                        if (fac != null && reimprimir != null)
                          IconButton(
                            tooltip: 'Reimprimir (permiso 142)',
                            icon: const Icon(Icons.print_outlined),
                            onPressed: () {
                              Navigator.pop(ctx);
                              reimprimir(v);
                            },
                          ),
                      ],
                    ),
                  );
                },
              ),
      ),
      actions: [
        TextButton.icon(
          onPressed: () {
            Navigator.pop(ctx);
            enviar();
          },
          icon: const Icon(Icons.cloud_upload_outlined),
          label: const Text('Enviar ahora'),
        ),
        FilledButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Cerrar'),
        ),
      ],
    ),
  );
}

/// Modo lector APAGADO: primero la cantidad (como pedirCantidad de la web). → el texto, o null.
Future<String?> pedirCantidad(BuildContext context, String articulo) {
  final c = TextEditingController(text: '1')
    ..selection = const TextSelection(baseOffset: 0, extentOffset: 1);
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: tituloDialogo('Cantidad', icono: Icons.numbers),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(articulo, style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 14),
            TextField(
              controller: c,
              autofocus: true,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 28, fontWeight: FontWeight.w700),
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
              onSubmitted: (t) =>
                  Navigator.pop(ctx, t.trim().isEmpty ? '1' : t.trim()),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: () =>
              Navigator.pop(ctx, c.text.trim().isEmpty ? '1' : c.text.trim()),
          child: const Text('Agregar'),
        ),
      ],
    ),
  );
}

/// MCF-ROM — configuración de la ROMANA (la misma de FactuDesk, dbo.RomanaConfig de la EMPRESA): se lee y se guarda en el
/// servidor (romana_config_obtener / romana_config_guardar, permitidas con la llave) y queda también en la copia del equipo.
/// → la config guardada (formato de la copia) o null.
Future<Map<String, dynamic>?> dialogoRomana(
  BuildContext context, {
  required String llave,
  required String cajero,
  required Map<String, dynamic>? actual,
}) async {
  int n(Object? v, int d) =>
      v is num ? v.toInt() : int.tryParse('${v ?? ''}') ?? d;
  var activo = n(actual?['activo'], 0) == 1;
  var tipo = '${actual?['tipo'] ?? 'cantidad'}' == 'precio'
      ? 'precio'
      : 'cantidad';
  final ci = TextEditingController(text: '${n(actual?['pos_codigo_ini'], 1)}'),
      cf = TextEditingController(text: '${n(actual?['pos_codigo_fin'], 7)}');
  final vi = TextEditingController(text: '${n(actual?['pos_valor_ini'], 8)}'),
      vf = TextEditingController(text: '${n(actual?['pos_valor_fin'], 12)}');
  final prueba = TextEditingController();
  var error = '', ocupado = false, leida = false;
  return showDialog<Map<String, dynamic>>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        Future<void> leer() async {
          leida = true;
          final con = Conexion(llave: llave, cajero: cajero);
          try {
            final j = await con.get(
              '/apis/shared/estacion/romana_config_obtener.php',
            );
            final c = j['config'];
            if (j['success'] == true && c is Map) {
              set(() {
                activo = c['activo'] == true || c['activo'] == 1;
                tipo = '${c['tipo']}' == 'precio' ? 'precio' : 'cantidad';
                ci.text = '${c['posCodigoIni']}';
                cf.text = '${c['posCodigoFin']}';
                vi.text = '${c['posValorIni']}';
                vf.text = '${c['posValorFin']}';
              });
            }
          } catch (_) {
            set(
              () => error = 'Sin conexión: se muestra la configuración guardada en esta caja.',
            );
          } finally {
            con.cerrar();
          }
        }

        if (!leida) leer();
        Future<void> guardar() async {
          final a = int.tryParse(ci.text) ?? 0,
              b = int.tryParse(cf.text) ?? 0,
              c = int.tryParse(vi.text) ?? 0,
              d = int.tryParse(vf.text) ?? 0;
          if (a < 1 || b < a)
            return set(() => error = 'Posiciones del código inválidas.');
          if (c < 1 || d < c)
            return set(() => error = 'Posiciones del valor inválidas.');
          set(() {
            ocupado = true;
            error = '';
          });
          final con = Conexion(llave: llave, cajero: cajero);
          try {
            final j = await con.post(
              '/apis/shared/estacion/romana_config_guardar.php',
              {
                'activo': activo,
                'posCodigoIni': a,
                'posCodigoFin': b,
                'posValorIni': c,
                'posValorFin': d,
                'tipo': tipo,
              },
            );
            if (j['success'] != true)
              throw ErrorConexion('${j['error'] ?? 'No se pudo guardar'}');
            if (ctx.mounted) {
              Navigator.pop(ctx, {
                'clave': 'actual',
                'activo': activo ? 1 : 0,
                'pos_codigo_ini': a,
                'pos_codigo_fin': b,
                'pos_valor_ini': c,
                'pos_valor_fin': d,
                'tipo': tipo,
              });
            }
          } on ErrorConexion catch (e) {
            set(
              () => error = e.sinInternet
                  ? 'Sin conexión: la configuración de la romana se guarda en el servidor.'
                  : e.mensaje,
            );
          } finally {
            con.cerrar();
            if (ctx.mounted) set(() => ocupado = false);
          }
        }

        // Vista previa con un código de ejemplo.
        String vista = '';
        final t = prueba.text.trim(),
            a = int.tryParse(ci.text) ?? 0,
            b = int.tryParse(cf.text) ?? 0,
            c = int.tryParse(vi.text) ?? 0,
            d = int.tryParse(vf.text) ?? 0;
        if (t.isNotEmpty &&
            a >= 1 &&
            b >= a &&
            c >= 1 &&
            d >= c &&
            t.length >= (b > d ? b : d)) {
          final val = int.tryParse(t.substring(c - 1, d)) ?? 0;
          vista =
              'Artículo «${t.substring(a - 1, b)}» · ${tipo == 'precio' ? 'precio ₡${fmt(val, 0)}' : 'peso ${fmt(val / 1000, 3)} kg'}';
        }
        Widget pos(String l, TextEditingController x) => Expanded(
          child: TextField(
            controller: x,
            keyboardType: TextInputType.number,
            decoration: InputDecoration(labelText: l),
            onChanged: (_) => set(() {}),
          ),
        );
        return AlertDialog(
          title: tituloDialogo(
            'Romana / balanza',
            codigo: 'MCF-ROM',
            icono: Icons.scale_outlined,
          ),
          content: SizedBox(
            width: 480,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Leer etiquetas de balanza'),
                  value: activo,
                  onChanged: (v) => set(() => activo = v),
                ),
                const SizedBox(height: 6),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(
                      value: 'cantidad',
                      label: Text('La etiqueta trae el PESO'),
                    ),
                    ButtonSegment(
                      value: 'precio',
                      label: Text('Trae el PRECIO'),
                    ),
                  ],
                  selected: {tipo},
                  onSelectionChanged: (x) => set(() => tipo = x.first),
                ),
                const SizedBox(height: 16),
                const Text(
                  'Posiciones en el código (desde 1)',
                  style: TextStyle(
                    fontSize: 12,
                    color: Marca.tintaSuave,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    pos('Código desde', ci),
                    const SizedBox(width: 8),
                    pos('hasta', cf),
                    const SizedBox(width: 16),
                    pos('Valor desde', vi),
                    const SizedBox(width: 8),
                    pos('hasta', vf),
                  ],
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: prueba,
                  decoration: const InputDecoration(
                    labelText: 'Probar con una etiqueta',
                    prefixIcon: Icon(Icons.qr_code),
                  ),
                  onChanged: (_) => set(() {}),
                ),
                if (vista.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(
                      vista,
                      style: const TextStyle(
                        color: Marca.verdeOscuro,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                if (error.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Text(
                      error,
                      style: const TextStyle(color: Marca.rojo),
                    ),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancelar'),
            ),
            FilledButton(
              onPressed: ocupado ? null : guardar,
              child: Text(ocupado ? 'Guardando…' : 'Guardar'),
            ),
          ],
        );
      },
    ),
  );
}

/// F6 — CONSULTA de artículo (fichaConsulta de la web): datos, precios por nivel (sin y con IVA, desc. fijo y máximo),
/// el costo y la utilidad mínima solo con el permiso 064, y el stock por bodega (solo con conexión).
Future<void> dialogoConsulta(
  BuildContext context,
  DatosCaja datos, {
  required bool verCosto,
  required Future<Map<String, dynamic>?> Function(String codigo) stock,
  String texto = '',
}) {
  final q = TextEditingController(text: texto);
  List<Map<String, dynamic>> res = texto.isEmpty
      ? []
      : datos.buscar(texto, limite: 60);
  Map<String, dynamic>? sel;
  Future<Map<String, dynamic>?>? stockF;
  return showDialog<void>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        Widget ficha(Map<String, dynamic> a) {
          final iva = ((a['tarifa_iva'] as num?) ?? 0).toDouble();
          final ps = datos.precios('${a['codigo']}');
          Widget dato(String t, String v) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              children: [
                SizedBox(
                  width: 130,
                  child: Text(
                    t,
                    style: const TextStyle(color: Marca.tintaSuave),
                  ),
                ),
                Expanded(
                  child: Text(
                    v,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
          );
          const cab = TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            color: Marca.tintaSuave,
          );
          return ListView(
            children: [
              Text(
                '${a['codigo']} · ${a['nombre']}',
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 10),
              dato(
                'Código de barras',
                '${a['barra'] ?? ''}'.isEmpty ? '—' : '${a['barra']}',
              ),
              dato(
                'CABYS',
                '${a['cabys'] ?? ''}'.isEmpty ? '—' : '${a['cabys']}',
              ),
              dato(
                'IVA',
                '${fmt(iva, iva % 1 == 0 ? 0 : 2)} % (${a['codigo_tarifa_iva'] ?? ''})',
              ),
              dato(
                'Unidad',
                '${a['unidad'] ?? ''}${'${a['fraccionable']}' == '1' ? ' · se fracciona' : ''}${((a['unidades_x_medida'] as num?) ?? 0) > 1 ? ' · caja de ${a['unidades_x_medida']}' : ''}',
              ),
              if (verCosto) dato('Costo', '₡${fmt((a['costo'] as num?) ?? 0)}'),
              const SizedBox(height: 12),
              Table(
                columnWidths: const {0: FlexColumnWidth(1.1)},
                children: [
                  TableRow(
                    children: [
                      const Text('PRECIO', style: cab),
                      const Text(
                        'SIN IVA',
                        style: cab,
                        textAlign: TextAlign.right,
                      ),
                      const Text(
                        'CON IVA',
                        style: cab,
                        textAlign: TextAlign.right,
                      ),
                      const Text(
                        'DESC. FIJO',
                        style: cab,
                        textAlign: TextAlign.right,
                      ),
                      const Text(
                        'DESC. MÁX.',
                        style: cab,
                        textAlign: TextAlign.right,
                      ),
                      if (verCosto)
                        const Text(
                          'UTIL. MÍN.',
                          style: cab,
                          textAlign: TextAlign.right,
                        ),
                    ],
                  ),
                  for (final p in ps)
                    TableRow(
                      children: [
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          child: Text(
                            'P${p['numero']}${'${p['moneda'] ?? 'CRC'}' != 'CRC' ? ' (${p['moneda']})' : ''}',
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          child: Text(
                            fmt((p['precio'] as num?) ?? 0),
                            textAlign: TextAlign.right,
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          child: Text(
                            fmt(((p['precio'] as num?) ?? 0) * (1 + iva / 100)),
                            textAlign: TextAlign.right,
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          child: Text(
                            ((p['descuento_fijo'] as num?) ?? 0) != 0
                                ? '${fmt(p['descuento_fijo'] as num)} %'
                                : '',
                            textAlign: TextAlign.right,
                          ),
                        ),
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 6),
                          child: Text(
                            p['descuento_maximo'] == null
                                ? ''
                                : '${fmt(p['descuento_maximo'] as num)} %',
                            textAlign: TextAlign.right,
                          ),
                        ),
                        if (verCosto)
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 6),
                            child: Text(
                              ((p['utilidad_minima'] as num?) ?? 0) != 0
                                  ? '${fmt(p['utilidad_minima'] as num)} %'
                                  : '',
                              textAlign: TextAlign.right,
                            ),
                          ),
                      ],
                    ),
                ],
              ),
              if (ps.isEmpty)
                const Text(
                  'Sin precios',
                  style: TextStyle(color: Marca.tintaSuave),
                ),
              const SizedBox(height: 12),
              FutureBuilder<Map<String, dynamic>?>(
                future: stockF,
                builder: (_, sn) {
                  if (sn.connectionState != ConnectionState.done)
                    return const Text(
                      'Stock: consultando…',
                      style: TextStyle(color: Marca.tintaSuave),
                    );
                  final j = sn.data;
                  if (j == null)
                    return const Text(
                      'Stock: requiere conexión (no se guarda en el equipo).',
                      style: TextStyle(color: Marca.tintaSuave),
                    );
                  final b = (j['bodegas'] as List? ?? const [])
                      .whereType<Map>()
                      .map(
                        (x) =>
                            '${x['BodegaNombre'] ?? x['BodegaCodigo']}: ${fmt((x['Stock'] as num?) ?? 0)}',
                      )
                      .join(' · ');
                  return Text(
                    'Stock total: ${fmt((j['stockTotal'] as num?) ?? 0)}${b.isEmpty ? '' : ' · $b'}',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  );
                },
              ),
            ],
          );
        }

        return AlertDialog(
          title: tituloDialogo(
            'Consulta de artículo',
            codigo: 'F6',
            icono: Icons.manage_search,
          ),
          content: SizedBox(
            width: 860,
            height: 480,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(
                  width: 320,
                  child: Column(
                    children: [
                      TextField(
                        controller: q,
                        autofocus: true,
                        decoration: const InputDecoration(
                          hintText: 'Código, barras o nombre',
                          prefixIcon: Icon(Icons.search),
                        ),
                        onChanged: (t) =>
                            set(() => res = datos.buscar(t, limite: 60)),
                      ),
                      const SizedBox(height: 8),
                      Expanded(
                        child: ListView.separated(
                          itemCount: res.length,
                          separatorBuilder: (_, __) => const Divider(),
                          itemBuilder: (_, i) => ListTile(
                            dense: true,
                            selected: identical(res[i], sel),
                            title: Text(
                              '${res[i]['nombre']}',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                            ),
                            subtitle: Text('${res[i]['codigo']}'),
                            onTap: () => set(() {
                              sel = res[i];
                              stockF = stock('${res[i]['codigo']}');
                            }),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const VerticalDivider(width: 28),
                Expanded(
                  child: sel == null
                      ? const Center(
                          child: Text(
                            'Elija un artículo',
                            style: TextStyle(color: Marca.tintaSuave),
                          ),
                        )
                      : ficha(sel!),
                ),
              ],
            ),
          ),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cerrar'),
            ),
          ],
        );
      },
    ),
  );
}
