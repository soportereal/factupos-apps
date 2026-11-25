/// La CAJA (#3957, F1c) — buscar/escanear, líneas, cobro directo por medio de pago, la venta se guarda en el equipo y
/// sale sola al servidor (con el mismo transaccionId). Réplica de lo esencial de FactuSuper web.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../caja/cajeros.dart';
import '../caja/cola.dart';
import '../caja/datos_caja.dart';
import '../caja/documento.dart';
import '../datos/almacen.dart';
import '../motor/redondeo.dart';

String fmt(num n, [int d = 2]) {
  final s = redondear(n, d).toStringAsFixed(d);
  final partes = s.split('.');
  final ent = partes[0].replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => '.');
  return d > 0 ? '$ent,${partes[1]}' : ent;
}

class PantallaCaja extends StatefulWidget {
  final ConfigCaja config;
  final DatosCaja datos;
  final Cola cola;
  final Cajero cajero;
  final VoidCallback alSalir;
  const PantallaCaja({super.key, required this.config, required this.datos, required this.cola, required this.cajero, required this.alSalir});

  @override
  State<PantallaCaja> createState() => _EstadoCaja();
}

class _EstadoCaja extends State<PantallaCaja> {
  late final Documento doc = Documento(widget.datos, widget.cajero);
  final _buscar = TextEditingController();
  final _focoBuscar = FocusNode();
  List<Map<String, dynamic>> _resultados = [];
  Timer? _reloj;
  bool _enviando = false;

  @override
  void initState() {
    super.initState();
    _reloj = Timer.periodic(const Duration(seconds: 60), (_) => _enviar());
    _enviar();
  }

  @override
  void dispose() {
    _reloj?.cancel();
    super.dispose();
  }

  void _aviso(String t, {bool error = false}) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(t), backgroundColor: error ? Theme.of(context).colorScheme.error : null, duration: Duration(seconds: error ? 6 : 3)));
  }

  Future<void> _enviar() async {
    if (_enviando || widget.cola.pendientes.isEmpty) return;
    setState(() => _enviando = true);
    final r = await widget.cola.enviar();
    if (!mounted) return;
    setState(() => _enviando = false);
    if (r.procesadas > 0) _aviso('${r.procesadas} ${r.procesadas == 1 ? 'venta facturada' : 'ventas facturadas'} en el servidor');
    if (r.rechazadas > 0) _aviso('${r.rechazadas} ${r.rechazadas == 1 ? 'venta rechazada' : 'ventas rechazadas'}: revise la lista de ventas', error: true);
    if (r.detenida.isNotEmpty && r.procesadas == 0) _aviso('${r.detenida} — se reintenta en un minuto', error: true);
  }

  // ── Agregar ──
  Future<void> _agregar(Map<String, dynamic> art, {String cantidad = '1'}) async {
    var r = doc.agregar(art, cantidad);
    if (r.preguntarRepetido) {
      final m = await showDialog<String>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Ese artículo ya está en la venta'),
          content: Text('«${art['nombre']}»'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c), child: const Text('Cancelar')),
            if (r.permiteNueva) TextButton(onPressed: () => Navigator.pop(c, 'nueva'), child: const Text('Línea nueva')),
            FilledButton(onPressed: () => Navigator.pop(c, 'sumar'), child: const Text('Sumar')),
          ],
        ),
      );
      if (m == null) return _volverAlBuscador();
      r = doc.agregar(art, cantidad, repetido: m);
    }
    setState(() {
      _resultados = [];
      _buscar.clear();
    });
    if (!r.ok) {
      _aviso(r.motivo, error: true);
    } else if (r.avisos.isNotEmpty) {
      _aviso(r.avisos.join(' · '));
    }
    _volverAlBuscador();
  }

  void _volverAlBuscador() => _focoBuscar.requestFocus();

  /// Enter en el buscador: «3*código» = 3 unidades; exacto por código/barras → se agrega; si no, la lista.
  void _alEnter(String texto) {
    texto = texto.trim();
    if (texto.isEmpty) return;
    var cant = '1';
    final m = RegExp(r'^(\d+(?:[.,]\d+)?)\*(.+)$').firstMatch(texto);
    if (m != null) {
      cant = m.group(1)!;
      texto = m.group(2)!.trim();
    }
    final a = widget.datos.articuloExacto(texto);
    if (a != null) {
      _agregar(a, cantidad: cant);
      return;
    }
    final l = widget.datos.buscar(texto, limite: 60);
    if (l.isEmpty) {
      _aviso('No se encontró «$texto»', error: true);
      _buscar.selection = TextSelection(baseOffset: 0, extentOffset: _buscar.text.length);
      _volverAlBuscador();
    } else if (l.length == 1) {
      _agregar(l.first, cantidad: cant);
    } else {
      setState(() => _resultados = l);
    }
  }

  Future<void> _editarCantidad(int i) async {
    final l = doc.lineas[i];
    final c = TextEditingController(text: fmt(l.cantidad, l.fraccionable != 0 ? 3 : 0).replaceAll('.', ''));
    final v = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(l.nombre),
        content: TextField(
          controller: c,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(labelText: 'Cantidad'),
          onSubmitted: (t) => Navigator.pop(ctx, t),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, c.text), child: const Text('Aceptar')),
        ],
      ),
    );
    if (v != null) {
      final aviso = doc.cambiarCantidad(i, v);
      setState(() {});
      if (aviso.isNotEmpty) _aviso(aviso);
    }
    _volverAlBuscador();
  }

  // ── Cobrar ──
  void _medioPrincipal(String medio) {
    final m = medio == '02' ? '02' : '01';
    if (doc.medioPago != m) {
      doc.medioPago = m;
      for (final l in doc.lineas) {
        doc.agregarRecalculo(l);
      }
    }
  }

  Future<void> _cobrar(MedioPago medio) async {
    final imp = doc.impedimento();
    if (imp.isNotEmpty) return _aviso(imp, error: true);
    var cuenta = medio.cuentas.length == 1 ? medio.cuentas.first : '';
    if (medio.cuentas.length > 1) {
      final c = await showDialog<String>(
        context: context,
        builder: (ctx) => SimpleDialog(
          title: Text('${medio.descripcion}: ¿a qué cuenta?'),
          children: [for (final x in medio.cuentas) SimpleDialogOption(onPressed: () => Navigator.pop(ctx, x), child: Text(x))],
        ),
      );
      if (c == null) return _volverAlBuscador();
      cuenta = c;
    }
    _medioPrincipal(medio.codigo);
    setState(() {});
    final total = r2(doc.totales.total);
    var vuelto = 0.0;
    var comprobante = '';
    if (medio.codigo == '01') {
      // Efectivo: cuánto entrega el cliente → vuelto. Enter sin escribir = exacto.
      final recibido = await _pedirMonto('Efectivo — total ₡${fmt(total)}', 'Recibido (vacío = exacto)');
      if (recibido == null) return _volverAlBuscador();
      final rec = recibido.isEmpty ? total : (double.tryParse(recibido.replaceAll('.', '').replaceAll(',', '.')) ?? -1);
      if (rec < total) return _aviso('Falta dinero: el total es ₡${fmt(total)}', error: true);
      vuelto = r2(rec - total);
    } else {
      final c = await _pedirMonto('${medio.descripcion} — ₡${fmt(total)}', 'Comprobante (opcional)', numerico: false);
      if (c == null) return _volverAlBuscador();
      comprobante = c;
    }
    final ahora = DateTime.now();
    final pq = doc.paquete(
      pagos: [{'medio': medio.codigo, 'cuenta': cuenta, 'monto': total, 'comprobante': comprobante}],
      vuelto: vuelto,
      transaccionId: uuidV4(),
      cuando: ahora,
    );
    try {
      await widget.cola.agregar(pq);
    } catch (e) {
      return _aviso('No se pudo guardar la venta en el equipo: $e', error: true);
    }
    final id = (pq['documento'] as Map)['idProceso'];
    setState(doc.nuevo);
    if (vuelto > 0 && mounted) {
      await showDialog<void>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('VUELTO'),
          content: Text('₡${fmt(vuelto)}', style: Theme.of(ctx).textTheme.displaySmall),
          actions: [FilledButton(autofocus: true, onPressed: () => Navigator.pop(ctx), child: const Text('Listo'))],
        ),
      );
    }
    _aviso('Factura en proceso · $id · ₡${fmt(total)}');
    _volverAlBuscador();
    _enviar();
  }

  Future<String?> _pedirMonto(String titulo, String etiqueta, {bool numerico = true}) {
    final c = TextEditingController();
    return showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(titulo),
        content: TextField(
          controller: c,
          autofocus: true,
          keyboardType: numerico ? const TextInputType.numberWithOptions(decimal: true) : TextInputType.text,
          decoration: InputDecoration(labelText: etiqueta),
          onSubmitted: (t) => Navigator.pop(ctx, t.trim()),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('Cobrar')),
        ],
      ),
    );
  }

  void _verVentas() {
    final ventas = widget.cola.ventas.reversed.toList();
    const nombres = {'pendiente': 'Pendiente', 'en_proceso': 'Enviando', 'error': 'Reintentará', 'procesada': 'Facturada', 'rechazada': 'RECHAZADA'};
    showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Ventas de esta caja'),
        content: SizedBox(
          width: 560,
          height: 420,
          child: ventas.isEmpty
              ? const Center(child: Text('Todavía no hay ventas.'))
              : ListView(children: [
                  for (final v in ventas)
                    ListTile(
                      dense: true,
                      title: Text('${v['idProceso']} · ₡${fmt((v['total'] as num?) ?? 0)}'),
                      subtitle: Text([
                        nombres['${v['estado']}'] ?? '${v['estado']}',
                        if (v['factura'] is Map) 'Factura ${(v['factura'] as Map)['numero'] ?? ''}',
                        if (v['error'] is Map) '${(v['error'] as Map)['mensaje']}',
                      ].join(' · ')),
                    ),
                ]),
        ),
        actions: [
          TextButton(onPressed: () { Navigator.pop(ctx); _enviar(); }, child: const Text('Enviar ahora')),
          FilledButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cerrar')),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final t = doc.totales;
    final cfg = widget.config;
    final pend = widget.cola.pendientes.length;
    final medios = widget.datos.mediosPago();
    final tema = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text('${cfg.empresaNombre.isEmpty ? cfg.empresa : cfg.empresaNombre} · ${widget.cajero.nombre}'),
        actions: [
          TextButton.icon(
            onPressed: _verVentas,
            icon: _enviando ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : Icon(pend > 0 ? Icons.cloud_upload : Icons.cloud_done),
            label: Text(pend > 0 ? '$pend por enviar' : 'Ventas'),
          ),
          TextButton.icon(onPressed: doc.lineas.isEmpty ? widget.alSalir : () => _aviso('Termine o anule la venta antes de salir', error: true), icon: const Icon(Icons.logout), label: const Text('Salir')),
        ],
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
          child: CallbackShortcuts(
            bindings: {const SingleActivator(LogicalKeyboardKey.escape): () => setState(() { _resultados = []; _buscar.clear(); })},
            child: TextField(
              controller: _buscar,
              focusNode: _focoBuscar,
              autofocus: true,
              decoration: const InputDecoration(
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.qr_code_scanner),
                hintText: 'Escanee o escriba código, barras o nombre (3*código = 3 unidades)',
              ),
              onSubmitted: _alEnter,
            ),
          ),
        ),
        if (_resultados.isNotEmpty)
          Expanded(
            child: Card(
              margin: const EdgeInsets.symmetric(horizontal: 12),
              child: ListView(children: [
                for (final a in _resultados)
                  ListTile(dense: true, title: Text('${a['nombre']}'), subtitle: Text('${a['codigo']}  ${a['barra'] ?? ''}'), onTap: () => _agregar(a)),
              ]),
            ),
          )
        else
          Expanded(
            child: doc.lineas.isEmpty
                ? Center(child: Text('Escanee el primer artículo', style: tema.textTheme.titleMedium))
                : ListView.separated(
                    itemCount: doc.lineas.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (_, i) {
                      final l = doc.lineas[i];
                      return ListTile(
                        title: Text(l.nombre),
                        subtitle: Text('${l.codigo} · ₡${fmt(l.precio)}${l.descuento > 0 ? ' · desc. ${fmt(l.descuento)} %' : ''}'),
                        leading: InkWell(
                          onTap: () => _editarCantidad(i),
                          child: Chip(label: Text(fmt(l.cantidad, l.fraccionable != 0 ? 3 : 0))),
                        ),
                        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                          Text('₡${fmt(l.total)}', style: tema.textTheme.titleMedium),
                          IconButton(icon: const Icon(Icons.delete_outline), tooltip: 'Quitar', onPressed: () => setState(() => doc.quitar(i))),
                        ]),
                      );
                    },
                  ),
          ),
        Material(
          elevation: 6,
          color: tema.colorScheme.surfaceContainerHigh,
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Row(children: [
                Text('${t.lineas} líneas · ${fmt(t.articulos, 0)} art. · IVA ₡${fmt(t.iva)}'),
                const Spacer(),
                Text('₡${fmt(t.total)}', style: tema.textTheme.displaySmall?.copyWith(fontWeight: FontWeight.bold)),
              ]),
              const SizedBox(height: 8),
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final m in medios)
                  FilledButton.tonal(onPressed: doc.lineas.isEmpty ? null : () => _cobrar(m), child: Text(m.descripcion)),
                OutlinedButton(
                  onPressed: doc.lineas.isEmpty
                      ? null
                      : () async {
                          final ok = await showDialog<bool>(
                            context: context,
                            builder: (c) => AlertDialog(
                              title: const Text('¿Anular esta venta?'),
                              actions: [
                                TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('No')),
                                FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Sí, anular')),
                              ],
                            ),
                          );
                          if (ok == true) setState(doc.nuevo);
                          _volverAlBuscador();
                        },
                  child: const Text('Anular'),
                ),
              ]),
            ]),
          ),
        ),
      ]),
    );
  }
}
