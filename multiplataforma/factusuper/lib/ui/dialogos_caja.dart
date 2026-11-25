/// Diálogos de las OPCIONES de caja (#3957): fondo de caja (MV-112), registro de procesos (MV-113).
library;

import 'package:flutter/material.dart';

import '../caja/cierre.dart';
import '../caja/clientes.dart';
import '../caja/datos_caja.dart';
import '../caja/documento.dart';
import '../caja/favoritos.dart';
import '../caja/fondo.dart';
import '../motor/redondeo.dart';
import 'dialogos.dart';
import 'tema.dart';

/// MV-112 · Ingreso / retiro de fondo. `guardar` manda YA al servidor: si falla, la ventana queda abierta con el error
/// (para reintentar con el mismo monto); si sale bien, devuelve el resultado.
Future<ResultadoFondo?> dialogoFondo(
  BuildContext context,
  String tipo,
  Future<ResultadoFondo> Function(double monto, String detalle) guardar,
) {
  final t = tiposFondo[tipo]!;
  final monto = TextEditingController();
  final detalle = TextEditingController(text: t.detalle);
  final focoMonto = FocusNode();
  var error = '';
  var enviando = false;
  return showDialog<ResultadoFondo>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        Future<void> enviar() async {
          if (enviando) return;
          final m = leerMonto(monto.text);
          set(() {
            enviando = true;
            error = 'Registrando…';
          });
          final r = await guardar(m.isNaN ? 0 : m, detalle.text);
          if (!ctx.mounted) return;
          if (r.ok) return Navigator.pop(ctx, r);
          set(() {
            enviando = false;
            error = r.mensaje;
          });
          if (r.mensaje.contains('monto')) focoMonto.requestFocus();
        }

        return AlertDialog(
          title: tituloDialogo(
            t.titulo,
            codigo: 'MV-112',
            icono: tipo == 'FCA'
                ? Icons.move_to_inbox_outlined
                : Icons.outbox_outlined,
          ),
          content: SizedBox(
            width: 440,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: monto,
                  focusNode: focoMonto,
                  autofocus: true,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  style: const TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w700,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Monto',
                    prefixText: '₡ ',
                  ),
                  onSubmitted: (_) => enviar(),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: detalle,
                  decoration: const InputDecoration(labelText: 'Detalle'),
                  onSubmitted: (_) => enviar(),
                ),
                const SizedBox(height: 10),
                const Text(
                  'Se registra en tiempo real: necesita internet. Sale el comprobante y se abre el cajón.',
                  style: TextStyle(color: Marca.tintaSuave, fontSize: 12.5),
                ),
                if (error.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Text(
                    error,
                    style: TextStyle(
                      color: enviando ? Marca.azul : Marca.rojo,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: enviando ? null : () => Navigator.pop(ctx),
              child: const Text('Cancelar'),
            ),
            FilledButton.icon(
              onPressed: enviando ? null : enviar,
              icon: const Icon(Icons.check),
              label: const Text('Guardar'),
            ),
          ],
        );
      },
    ),
  );
}

/// MV-113 · Registro de la semana: todo lo que este equipo mandó a procesar.
Future<void> dialogoRegistro(
  BuildContext context,
  List<Map<String, dynamic>> lista,
) => showDialog<void>(
  context: context,
  builder: (ctx) => AlertDialog(
    title: tituloDialogo(
      'Registro de procesos (7 días)',
      codigo: 'MV-113',
      icono: Icons.history,
    ),
    content: SizedBox(
      width: 720,
      height: 460,
      child: lista.isEmpty
          ? const Center(
              child: Text(
                'Todavía no hay procesos registrados en este equipo',
                style: TextStyle(color: Marca.tintaSuave),
              ),
            )
          : ListView.separated(
              itemCount: lista.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (_, i) {
                final p = lista[i];
                final ok = p['estado'] == 'procesado';
                final mal = p['estado'] == 'rechazado';
                final f = DateTime.tryParse('${p['fecha']}')?.toLocal();
                String d(int n) => n.toString().padLeft(2, '0');
                return ListTile(
                  dense: true,
                  leading: Icon(
                    ok
                        ? Icons.check_circle
                        : mal
                        ? Icons.cancel
                        : Icons.schedule,
                    color: ok
                        ? Marca.verde
                        : mal
                        ? Marca.rojo
                        : Marca.ambar,
                  ),
                  title: Text('${p['idProceso']} · ${p['tipo']}'),
                  subtitle: Text(
                    [
                      if (f != null)
                        '${d(f.day)}/${d(f.month)} ${d(f.hour)}:${d(f.minute)}',
                      if ('${p['resultado'] ?? ''}'.isNotEmpty)
                        '${p['resultado']}',
                      if ('${p['error'] ?? ''}'.isNotEmpty) '${p['error']}',
                    ].join(' · '),
                  ),
                  trailing: Text('${p['estado']}'),
                );
              },
            ),
    ),
    actions: [
      FilledButton(
        onPressed: () => Navigator.pop(ctx),
        child: const Text('Cerrar'),
      ),
    ],
  ),
);

/// MV-114 · Proformas de ESTE equipo. → ('abrir' | 'borrar', id) o null.
Future<(String, String)?> dialogoProformas(
  BuildContext context,
  List<Map<String, dynamic>> lista, {
  required bool puedeBorrar,
  String? actual,
}) {
  final l = [...lista]
    ..sort((a, b) => '${b['fecha']}'.compareTo('${a['fecha']}'));
  String hora(Object? t) {
    final d = DateTime.tryParse('$t')?.toLocal();
    if (d == null) return '';
    String x(int n) => n.toString().padLeft(2, '0');
    return '${x(d.day)}/${x(d.month)}/${d.year} ${x(d.hour)}:${x(d.minute)}';
  }

  return showDialog<(String, String)>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: tituloDialogo(
        'Proformas de esta caja',
        codigo: 'MV-114',
        icono: Icons.folder_open_outlined,
      ),
      content: SizedBox(
        width: 760,
        height: 440,
        child: l.isEmpty
            ? const Center(
                child: Text(
                  'No hay proformas guardadas en este equipo',
                  style: TextStyle(color: Marca.tintaSuave),
                ),
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${l.length} ${l.length == 1 ? 'proforma guardada' : 'proformas guardadas'} en esta caja',
                    style: const TextStyle(color: Marca.tintaSuave),
                  ),
                  const SizedBox(height: 8),
                  Expanded(
                    child: ListView.separated(
                      itemCount: l.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (_, i) {
                        final p = l[i];
                        final id = '${p['id']}';
                        final cli = (p['cliente'] as Map?) ?? const {};
                        final et = '${p['etiqueta'] ?? ''}';
                        return ListTile(
                          selected: actual == id,
                          onTap: () => Navigator.pop(ctx, ('abrir', id)),
                          leading: Icon(
                            p['cotizacion'] == true
                                ? Icons.description_outlined
                                : Icons.person_outline,
                            color: Marca.azul,
                          ),
                          title: Text.rich(
                            TextSpan(
                              children: [
                                if (p['cotizacion'] == true)
                                  const TextSpan(
                                    text: 'COTIZACIÓN  ',
                                    style: TextStyle(
                                      color: Marca.verde,
                                      fontWeight: FontWeight.w700,
                                      fontSize: 12,
                                    ),
                                  ),
                                TextSpan(text: '${cli['nombre'] ?? ''}'),
                                if (et.isNotEmpty)
                                  TextSpan(
                                    text: ' · $et',
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                              ],
                            ),
                          ),
                          subtitle: Text(
                            '$id · ${hora(p['fecha'])} · ${p['lineas']} líneas',
                          ),
                          trailing: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                '₡${fmt((p['total'] as num?) ?? 0)}',
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                  fontSize: 15,
                                ),
                              ),
                              const SizedBox(width: 12),
                              Tooltip(
                                message: puedeBorrar
                                    ? 'Eliminar esta proforma del equipo'
                                    : 'Sin permiso para eliminar proformas (060)',
                                child: IconButton(
                                  icon: const Icon(Icons.delete_outline),
                                  color: Marca.rojo,
                                  onPressed: puedeBorrar
                                      ? () => Navigator.pop(ctx, ('borrar', id))
                                      : null,
                                ),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
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
    ),
  );
}

/// MV-118 · FAVORITOS: panel lateral que se queda abierto para agregar varios (se oculta con «Ocultar», Esc o tocando
/// afuera). `agregar` suma 1 unidad; `cantidadEnVenta` dice cuánto ya va de ese artículo.
Future<void> panelFavoritos(
  BuildContext context, {
  required Favoritos favoritos,
  required Documento doc,
  required DatosCaja datos,
  required Future<void> Function(Map<String, dynamic> art) agregar,
  required void Function(String texto, {bool error}) aviso,
}) {
  var filas = <FilaFav>[];
  var mios = <String>[];
  var info = <String, dynamic>{};
  var campo = 'origen';
  var dir = 1;
  var cargado = false;
  final buscar = TextEditingController();
  var sugerencias = <Map<String, dynamic>>[];
  final ancho = MediaQuery.sizeOf(context).width;
  final w = ancho < 700 ? ancho * 0.85 : 440.0;

  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: true,
    barrierLabel: 'Ocultar favoritos',
    barrierColor: Colors.black26,
    transitionDuration: const Duration(milliseconds: 220),
    transitionBuilder: (_, a, _, child) => SlideTransition(
      position: Tween(
        begin: const Offset(1, 0),
        end: Offset.zero,
      ).animate(CurvedAnimation(parent: a, curve: Curves.easeOutCubic)),
      child: child,
    ),
    pageBuilder: (ctx, _, _) => Align(
      alignment: Alignment.centerRight,
      child: Material(
        elevation: 12,
        child: SizedBox(
          width: w,
          height: double.infinity,
          child: StatefulBuilder(
            builder: (ctx, set) {
              Future<void> armar() async {
                final f = await favoritos.armar(doc);
                final m = await favoritos.delCajero(doc.cajero.usuario);
                final i = await favoritos.masVendidos();
                if (!ctx.mounted) return;
                set(() {
                  filas = f;
                  mios = m;
                  info = i;
                  cargado = true;
                });
              }

              if (!cargado) {
                cargado = true;
                armar().then((_) async {
                  if (await favoritos.refrescar(doc.cajero.usuario)) {
                    await armar();
                  }
                });
              }
              final enVenta = <String, double>{};
              for (final l in doc.lineas) {
                enVenta[l.codigo] = (enVenta[l.codigo] ?? 0) + l.cantidad;
              }
              Future<void> sumarMio(Map<String, dynamic> art) async {
                set(() => sugerencias = []);
                final ya = filas
                    .where((f) => f.codigo == '${art['codigo']}')
                    .firstOrNull;
                if (ya != null) {
                  aviso(
                    '«${art['nombre']}» ya está en la lista${ya.sistema ? ' (es de los más vendidos)' : ''}: no hace falta agregarlo',
                  );
                  buscar.clear();
                  return;
                }
                if (mios.length >= favMax) {
                  aviso(
                    'Son máximo $favMax favoritos propios: quite uno para agregar otro.',
                    error: true,
                  );
                  return;
                }
                await favoritos.guardarDelCajero(doc.cajero.usuario, [
                  ...mios,
                  '${art['codigo']}',
                ]);
                buscar.clear();
                await armar();
                aviso('«${art['nombre']}» quedó en sus favoritos');
              }

              Future<void> quitarMio(String codigo) async {
                await favoritos.guardarDelCajero(
                  doc.cajero.usuario,
                  mios.where((c) => c != codigo).toList(),
                );
                await armar();
              }

              Widget orden(String c, String t) {
                final activo = campo == c;
                return Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    label: Text('$t${activo ? (dir == 1 ? ' ▲' : ' ▼') : ''}'),
                    selected: activo,
                    onSelected: (_) => set(() {
                      if (activo) {
                        dir = -dir;
                      } else {
                        campo = c;
                        dir = 1;
                      }
                    }),
                  ),
                );
              }

              final lista = Favoritos.ordenar(filas, campo, dir);
              final fecha = DateTime.tryParse('${info['fecha']}')?.toLocal();
              String d2(int n) => n.toString().padLeft(2, '0');
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Container(
                    color: Marca.azul,
                    padding: const EdgeInsets.fromLTRB(20, 18, 8, 18),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.star_rounded,
                          color: Color(0xFFFCD34D),
                        ),
                        const SizedBox(width: 10),
                        const Expanded(
                          child: Text(
                            'Favoritos',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 18,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                        const Text(
                          'MV-118',
                          style: TextStyle(color: Colors.white54, fontSize: 11),
                        ),
                        TextButton.icon(
                          style: TextButton.styleFrom(
                            foregroundColor: Colors.white,
                          ),
                          onPressed: () => Navigator.pop(ctx),
                          icon: const Icon(Icons.chevron_right),
                          label: const Text('Ocultar'),
                        ),
                      ],
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(14, 12, 14, 4),
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(
                        children: [
                          orden('origen', '★ Origen'),
                          orden('codigo', 'Código'),
                          orden('nombre', 'Nombre'),
                          orden('precio', 'Precio'),
                        ],
                      ),
                    ),
                  ),
                  Expanded(
                    child: lista.isEmpty
                        ? const Padding(
                            padding: EdgeInsets.all(24),
                            child: Text(
                              'Todavía no hay favoritos en este equipo.\nLos más vendidos aparecen solos cuando hay ventas; los suyos se agregan abajo.',
                              textAlign: TextAlign.center,
                              style: TextStyle(color: Marca.tintaSuave),
                            ),
                          )
                        : ListView.separated(
                            itemCount: lista.length,
                            separatorBuilder: (_, _) =>
                                const Divider(height: 1),
                            itemBuilder: (_, i) {
                              final f = lista[i];
                              final n = enVenta[f.codigo] ?? 0;
                              return ListTile(
                                onTap: () async {
                                  await agregar(f.art);
                                  if (ctx.mounted) set(() {});
                                },
                                leading: SizedBox(
                                  width: 24,
                                  child: f.sistema
                                      ? Tooltip(
                                          message:
                                              'Más vendido n.º ${f.puesto}: lo eligió el sistema',
                                          child: const Icon(
                                            Icons.star_rounded,
                                            color: Marca.ambar,
                                          ),
                                        )
                                      : null,
                                ),
                                title: Text(
                                  f.nombre,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                subtitle: Text(
                                  '${f.codigo}${f.sistema && f.mio ? ' · también en sus favoritos' : ''}',
                                ),
                                trailing: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    if (n > 0)
                                      Container(
                                        margin: const EdgeInsets.only(right: 8),
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 7,
                                          vertical: 2,
                                        ),
                                        decoration: BoxDecoration(
                                          color: Marca.azulClaro,
                                          borderRadius: BorderRadius.circular(
                                            10,
                                          ),
                                        ),
                                        child: Text(
                                          '× ${fmt(n, 3).replaceFirst(RegExp(r',?0+$'), '')}',
                                          style: const TextStyle(
                                            color: Marca.azul,
                                            fontWeight: FontWeight.w700,
                                          ),
                                        ),
                                      ),
                                    f.sinPrecio
                                        ? const Text(
                                            'sin precio',
                                            style: TextStyle(color: Marca.rojo),
                                          )
                                        : Text(
                                            fmt(f.precio),
                                            style: const TextStyle(
                                              fontWeight: FontWeight.w700,
                                            ),
                                          ),
                                    SizedBox(
                                      width: 40,
                                      child: f.mio
                                          ? IconButton(
                                              tooltip:
                                                  'Quitar de mis favoritos',
                                              icon: const Icon(
                                                Icons.close,
                                                size: 18,
                                              ),
                                              onPressed: () =>
                                                  quitarMio(f.codigo),
                                            )
                                          : null,
                                    ),
                                  ],
                                ),
                              );
                            },
                          ),
                  ),
                  const Divider(height: 1),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
                    child: Text(
                      '★ = más vendidos de los últimos ${info['dias'] ?? 30} días'
                      '${fecha == null ? ' · todavía sin bajar (necesita internet una vez)' : ' · al ${d2(fecha.day)}/${d2(fecha.month)} ${d2(fecha.hour)}:${d2(fecha.minute)}'}\n'
                      'Sin estrella = sus favoritos (${mios.length} de $favMax), guardados en esta caja para ${doc.cajero.nombre}',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Marca.tintaSuave,
                      ),
                    ),
                  ),
                  if (sugerencias.isNotEmpty)
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxHeight: 220),
                      child: ListView(
                        shrinkWrap: true,
                        children: [
                          for (final s in sugerencias)
                            ListTile(
                              dense: true,
                              title: Text('${s['nombre']}'),
                              subtitle: Text('${s['codigo']}'),
                              onTap: () => sumarMio(s),
                            ),
                        ],
                      ),
                    ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(14, 4, 14, 14),
                    child: TextField(
                      controller: buscar,
                      decoration: const InputDecoration(
                        prefixIcon: Icon(Icons.add),
                        hintText: 'Agregar a mis favoritos: código o nombre…',
                      ),
                      onChanged: (t) => set(
                        () => sugerencias = t.trim().length < 2
                            ? []
                            : datos.buscar(t, limite: 8),
                      ),
                      onSubmitted: (t) {
                        final a = datos.articuloExacto(t.trim());
                        if (a != null) {
                          sumarMio(a);
                        } else if (sugerencias.length == 1) {
                          sumarMio(sugerencias.single);
                        }
                      },
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    ),
  );
}

/// MV-110 · Crear / editar cliente (también sin internet). `guardar` valida y guarda en el equipo; devuelve el error
/// ('' = listo) y la ventana se cierra con el cliente.
Future<Map<String, dynamic>?> dialogoClienteEditar(
  BuildContext context, {
  required String titulo,
  required String nota,
  required bool esNuevo,
  required bool conFactura,
  required Map<String, dynamic> original,
  required List<Map<String, dynamic>> monedas,
  required Future<(Map<String, dynamic>?, String)> Function(
    Map<String, dynamic> valores,
  )
  guardar,
}) {
  final ctl = <String, TextEditingController>{
    for (final k in camposCliente)
      if (k != 'tipo_cedula' && k != 'moneda')
        k: TextEditingController(text: '${original[k] ?? ''}'),
  };
  if (ctl['tipo_precio']!.text.isEmpty) ctl['tipo_precio']!.text = '1';
  var tipoCedula = '${original['tipo_cedula'] ?? ''}'.trim();
  if (tipoCedula.isEmpty) tipoCedula = '01';
  var moneda = '${original['moneda'] ?? ''}'.trim();
  if (moneda.isEmpty) moneda = 'CRC';
  final checks = {
    for (final k in checksCliente) k: '${original[k] ?? 0}' == '1',
  };
  var error = '';
  var guardando = false;
  const tipos = {
    '01': '01 - Cédula Física',
    '02': '02 - Cédula Jurídica',
    '03': '03 - DIMEX',
    '04': '04 - NITE',
    '05': '05 - Extranjero no domiciliado',
    '06': '06 - No contribuyente',
  };
  final listaMonedas = {
    for (final m in monedas)
      '${m['codigo']}': '${m['codigo']} · ${m['nombre']}',
    if (!monedas.any((m) => '${m['codigo']}' == moneda)) moneda: moneda,
  };

  return showDialog<Map<String, dynamic>>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        Future<void> enviar() async {
          if (guardando) return;
          final v = <String, dynamic>{
            for (final e in ctl.entries) e.key: e.value.text,
            'tipo_cedula': tipoCedula,
            'moneda': moneda,
            for (final e in checks.entries) e.key: e.value ? 1 : 0,
          };
          set(() => guardando = true);
          final (c, e) = await guardar(v);
          if (!ctx.mounted) return;
          if (e.isEmpty) return Navigator.pop(ctx, c ?? original);
          set(() {
            guardando = false;
            error = e;
          });
        }

        String req(String t, {bool fe = false}) =>
            (fe ? conFactura : true) ? '$t *' : t;
        Widget campo(
          String k,
          String etiqueta, {
          double ancho = 260,
          String? ayuda,
          bool soloLectura = false,
          TextInputType? teclado,
          bool foco = false,
        }) => SizedBox(
          width: ancho,
          child: TextField(
            controller: ctl[k],
            autofocus: foco,
            readOnly: soloLectura,
            keyboardType: teclado,
            decoration: InputDecoration(
              labelText: etiqueta,
              hintText: ayuda,
              filled: soloLectura ? true : null,
            ),
            onSubmitted: (_) => enviar(),
          ),
        );

        return AlertDialog(
          title: tituloDialogo(
            titulo,
            codigo: 'MV-110',
            icono: esNuevo
                ? Icons.person_add_alt_1_outlined
                : Icons.manage_accounts_outlined,
          ),
          content: SizedBox(
            width: 820,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(nota, style: const TextStyle(color: Marca.tintaSuave)),
                  const SizedBox(height: 14),
                  Wrap(
                    spacing: 14,
                    runSpacing: 14,
                    children: [
                      SizedBox(
                        width: 260,
                        child: DropdownButtonFormField<String>(
                          initialValue: tipos.containsKey(tipoCedula)
                              ? tipoCedula
                              : '01',
                          decoration: const InputDecoration(
                            labelText: 'Tipo de identificación',
                          ),
                          items: [
                            for (final e in tipos.entries)
                              DropdownMenuItem(
                                value: e.key,
                                child: Text(e.value),
                              ),
                          ],
                          onChanged: (v) => tipoCedula = v ?? '01',
                        ),
                      ),
                      campo(
                        'cedula',
                        req('Cédula / ID', fe: !esNuevo) +
                            (esNuevo && !conFactura ? ' *' : ''),
                        foco: esNuevo,
                      ),
                      campo(
                        'nombre',
                        req('Nombre jurídico / Razón social'),
                        ancho: 534,
                        foco: !esNuevo,
                      ),
                      campo(
                        'comercial',
                        'Nombre comercial',
                        ancho: 534,
                        ayuda: '(vacío = el nombre)',
                      ),
                      campo(
                        'email_factura',
                        req('Email facturación', fe: true),
                        ancho: 534,
                        ayuda: 'correo@ejemplo.com, otro@ejemplo.com',
                      ),
                      campo('email_general', 'Email general', ancho: 260),
                      campo(
                        'email_cobro',
                        'Email estado de cuenta',
                        ancho: 260,
                      ),
                      campo('telefonos', 'Teléfonos'),
                      campo('contacto', 'Contacto'),
                      campo('direccion', 'Dirección', ancho: 534),
                      campo(
                        'actividad',
                        esNuevo
                            ? req('Actividad económica', fe: true)
                            : 'Actividad económica',
                        ayuda: 'ej. 4711.0',
                        soloLectura: !esNuevo,
                      ),
                      campo(
                        'tipo_precio',
                        'Tipo de precio (1-10)',
                        ancho: 170,
                        teclado: TextInputType.number,
                      ),
                      campo(
                        'descuento',
                        'Descuento %',
                        ancho: 170,
                        teclado: TextInputType.number,
                      ),
                      SizedBox(
                        width: 260,
                        child: DropdownButtonFormField<String>(
                          initialValue: moneda,
                          decoration: const InputDecoration(
                            labelText: 'Moneda',
                          ),
                          items: [
                            for (final e in listaMonedas.entries)
                              DropdownMenuItem(
                                value: e.key,
                                child: Text(e.value),
                              ),
                          ],
                          onChanged: (v) => moneda = v ?? 'CRC',
                        ),
                      ),
                      campo(
                        'monto_credito',
                        'Monto de crédito',
                        ancho: 170,
                        teclado: TextInputType.number,
                      ),
                      campo(
                        'plazo',
                        'Plazo (días)',
                        ancho: 170,
                        teclado: TextInputType.number,
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 20,
                    children: [
                      for (final (k, t) in const [
                        ('exento', 'Exento de IVA'),
                        ('no_forzar_credito', 'No forzar crédito'),
                      ])
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Checkbox(
                              value: checks[k],
                              onChanged: (v) =>
                                  set(() => checks[k] = v ?? false),
                            ),
                            Text(t),
                          ],
                        ),
                    ],
                  ),
                  if (error.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text(
                        error,
                        style: const TextStyle(
                          color: Marca.rojo,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: guardando ? null : () => Navigator.pop(ctx),
              child: const Text('Cancelar'),
            ),
            FilledButton.icon(
              onPressed: guardando ? null : enviar,
              icon: const Icon(Icons.check),
              label: Text(esNuevo ? 'Crear cliente' : 'Guardar'),
            ),
          ],
        );
      },
    ),
  );
}

/// MV-106 · Exoneración (igual que FactuDesk) sobre [indices]. → 'aplicar' / 'quitar' con el plan, o null.
Future<(String, Map<String, dynamic>?)?> dialogoExoneracion(
  BuildContext context, {
  required Documento doc,
  required List<int> indices,
  required bool todas,
}) {
  final lista = doc.exoneracionesCliente();
  final mapa = doc.cabysExonerados();
  Map<String, dynamic>? elegida =
      lista.where((e) => e['vigente'] == true).firstOrNull ?? lista.firstOrNull;
  return showDialog<(String, Map<String, dynamic>?)>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        final plan = doc.exoneracionPlan(indices, elegida);
        final ok = plan.where((r) => r.exo != null).length;
        return AlertDialog(
          title: tituloDialogo(
            'Exoneración',
            codigo: 'MV-106',
            icono: Icons.verified_user_outlined,
          ),
          content: SizedBox(
            width: 820,
            height: 520,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text.rich(
                  TextSpan(
                    children: [
                      TextSpan(
                        text:
                            '${doc.cliente['codigo']} · ${doc.cliente['nombre']}',
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      TextSpan(
                        text: todas
                            ? ' — todas las líneas (no hay ninguna marcada)'
                            : ' — ${indices.length} líneas marcadas',
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  mapa.isNotEmpty
                      ? 'El cliente tiene ${mapa.length} CABYS autorizados: a cada línea le toca la exoneración que cubre su CABYS.'
                      : 'El cliente no tiene CABYS registrados: la exoneración elegida cubre todas las líneas.',
                  style: const TextStyle(color: Marca.tintaSuave),
                ),
                const SizedBox(height: 10),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxHeight: 170),
                  child: ListView(
                    shrinkWrap: true,
                    children: [
                      for (final e in lista)
                        RadioListTile<Map<String, dynamic>>(
                          dense: true,
                          value: e,
                          // ignore: deprecated_member_use
                          groupValue: elegida,
                          // ignore: deprecated_member_use
                          onChanged: mapa.isNotEmpty
                              ? null
                              : (v) => set(() => elegida = v),
                          title: Text(
                            '${'${e['documento'] ?? ''}'.isEmpty ? '(sin número)' : e['documento']} · tipo ${e['tipo_documento'] ?? '—'} · ${e['institucion'] ?? ''} · ${fmt((num.tryParse('${e['porcentaje']}') ?? 0))}%',
                            style: TextStyle(
                              color: e['vigente'] == true
                                  ? null
                                  : Marca.tintaSuave,
                            ),
                          ),
                          subtitle: Text(
                            '${e['vencimiento'] ?? ''}'.isEmpty
                                ? 'sin vencimiento'
                                : '${e['vigente'] == true ? 'vence' : 'VENCIDA'} ${e['vencimiento']}',
                            style: TextStyle(
                              color: e['vigente'] == true ? null : Marca.rojo,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
                const Divider(),
                Expanded(
                  child: ListView.separated(
                    itemCount: plan.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (_, i) {
                      final r = plan[i];
                      final l = doc.lineas[r.indice];
                      return ListTile(
                        dense: true,
                        title: Text('${r.codigo} · ${r.nombre}'),
                        subtitle: Text(
                          'CABYS ${r.cabys.isEmpty ? '—' : r.cabys} · IVA ${fmt(l.tarifa, 0)}%',
                        ),
                        trailing: r.exo != null
                            ? Text(
                                '✔ ${fmt(r.porcentaje)}% · doc ${r.exo!['documento']}',
                                style: const TextStyle(
                                  color: Marca.verde,
                                  fontWeight: FontWeight.w600,
                                ),
                              )
                            : SizedBox(
                                width: 300,
                                child: Text(
                                  '✖ ${r.motivo}',
                                  textAlign: TextAlign.right,
                                  style: const TextStyle(color: Marca.rojo),
                                ),
                              ),
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
            OutlinedButton(
              onPressed: () => Navigator.pop(ctx, ('quitar', null)),
              child: const Text('Quitar exoneración'),
            ),
            FilledButton.icon(
              onPressed: ok == 0
                  ? null
                  : () => Navigator.pop(ctx, ('aplicar', elegida)),
              icon: const Icon(Icons.verified_user_outlined),
              label: Text('Aplicar a $ok de ${plan.length}'),
            ),
          ],
        );
      },
    ),
  );
}

/// MU-001 · Cierre de caja (contador de monedas). [colaPendiente] = procesos sin enviar: se puede contar, pero no
/// contabilizar hasta enviarlos.
Future<String?> dialogoCierre(
  BuildContext context, {
  required CierreCaja cierre,
  required String nombreCajero,
  required double tipoCambio,
  required Future<int> Function() colaPendiente,
}) {
  final c = Conteo()..tipoCambio = tipoCambio > 0 ? tipoCambio : 500;
  final ctl = <String, TextEditingController>{};
  TextEditingController campo(String k, [String v = '']) =>
      ctl.putIfAbsent(k, () => TextEditingController(text: v));
  CierrePendiente? pend;
  var buscando = true, trabajando = false;
  var nota = '', error = '';
  var cola = 0;
  campo('tc', fmt(c.tipoCambio));
  return showDialog<String>(
    context: context,
    barrierDismissible: false,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) {
        if (buscando && nota.isEmpty) {
          nota = 'Buscando el cierre pendiente…';
          () async {
            cola = await colaPendiente();
            final (p, e) = await cierre.pendiente();
            if (!ctx.mounted) return; // lo cerraron antes de que contestara
            set(() {
              buscando = false;
              pend = p;
              nota = e.isNotEmpty
                  ? e
                  : p == null
                  ? 'Modo solo conteo: no hay cierre pendiente. Contabilizar deshabilitado.'
                  : 'Cierre pendiente: asiento ${p.asiento}${p.nombre.isEmpty ? '' : ' · ${p.nombre}'}';
              if (cola > 0) {
                error =
                    'Hay $cola ${cola == 1 ? 'proceso' : 'procesos'} en la cola: puede contar, pero no contabilizar hasta enviarlos.';
              }
            });
          }();
        }
        double n(String t) {
          final v = leerMonto(t);
          return v.isNaN ? 0 : v;
        }

        void leer() {
          for (final d in c.denominaciones.keys.toList()) {
            c.denominaciones[d] = n(campo('d$d').text);
          }
          c
            ..tarjeta = n(campo('tarjeta').text)
            ..sinpe = n(campo('sinpe').text)
            ..transferencia = n(campo('transferencia').text)
            ..gastos = n(campo('gastos').text)
            ..dolares = n(campo('dolares').text)
            ..tipoCambio = n(campo('tc').text);
        }

        Widget fila(String k, String etiqueta, {double? valor}) => Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(
            children: [
              SizedBox(
                width: valor == null ? 122 : 96,
                child: Text(
                  etiqueta,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
              SizedBox(
                width: 96,
                child: TextField(
                  controller: campo(k),
                  textAlign: TextAlign.right,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    isDense: true,
                    hintText: '0',
                  ),
                  onChanged: (_) => set(leer),
                ),
              ),
              if (valor != null)
                Expanded(
                  child: Text(
                    '₡${fmt(valor * n(campo(k).text), 0)}',
                    textAlign: TextAlign.right,
                    maxLines: 1,
                    softWrap: false,
                    overflow: TextOverflow.fade,
                    style: const TextStyle(
                      color: Marca.tintaSuave,
                      fontSize: 13,
                    ),
                  ),
                ),
            ],
          ),
        );

        final dif = pend == null
            ? null
            : redondear(c.total - pend!.totalCaja, 2);
        final puedeContabilizar = pend != null && cola == 0 && !trabajando;
        Widget total(String t, double v, {Color? color, bool grande = false}) =>
            Row(
              children: [
                Expanded(child: Text(t)),
                Text(
                  '₡${fmt(v)}',
                  style: TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: grande ? 22 : 15,
                    color: color,
                  ),
                ),
              ],
            );
        return AlertDialog(
          title: tituloDialogo(
            'Cierre de caja',
            codigo: 'MU-001',
            icono: Icons.calculate_outlined,
          ),
          content: SizedBox(
            width: 860,
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Cajero: $nombreCajero',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  Text(nota, style: const TextStyle(color: Marca.tintaSuave)),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 30,
                    runSpacing: 12,
                    children: [
                      SizedBox(
                        width: 260,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'MONEDAS',
                              style: TextStyle(
                                color: Marca.tintaSuave,
                                letterSpacing: 1.2,
                                fontSize: 12,
                              ),
                            ),
                            const SizedBox(height: 6),
                            for (final d in monedasCrc)
                              fila('d$d', '₡${fmt(d, 0)}', valor: d.toDouble()),
                            total('Subtotal', c.subMonedas),
                          ],
                        ),
                      ),
                      SizedBox(
                        width: 260,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'BILLETES',
                              style: TextStyle(
                                color: Marca.tintaSuave,
                                letterSpacing: 1.2,
                                fontSize: 12,
                              ),
                            ),
                            const SizedBox(height: 6),
                            for (final d in billetesCrc)
                              fila('d$d', '₡${fmt(d, 0)}', valor: d.toDouble()),
                            total('Subtotal', c.subBilletes),
                          ],
                        ),
                      ),
                      SizedBox(
                        width: 260,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'OTROS',
                              style: TextStyle(
                                color: Marca.tintaSuave,
                                letterSpacing: 1.2,
                                fontSize: 12,
                              ),
                            ),
                            const SizedBox(height: 6),
                            fila('tarjeta', 'Tarjeta'),
                            fila('sinpe', 'SINPE'),
                            fila('transferencia', 'Transferencia'),
                            fila('gastos', 'Gastos'),
                            fila('dolares', 'Dólares'),
                            fila('tc', 'Tipo cambio'),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const Divider(height: 28),
                  total('Efectivo (monedas + billetes)', c.totalEfectivo),
                  const SizedBox(height: 6),
                  total(
                    'TOTAL CONTADO',
                    c.total,
                    grande: true,
                    color: Marca.azul,
                  ),
                  if (pend != null) ...[
                    const SizedBox(height: 6),
                    total('Según el sistema (control)', pend!.totalCaja),
                    total(
                      'Diferencia',
                      dif!,
                      color: dif.abs() < 0.01 ? Marca.verde : Marca.rojo,
                    ),
                  ],
                  if (error.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Text(
                      error,
                      style: const TextStyle(
                        color: Marca.rojo,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: trabajando ? null : () => Navigator.pop(ctx),
              child: const Text('Cerrar'),
            ),
            OutlinedButton.icon(
              onPressed: trabajando
                  ? null
                  : () async {
                      leer();
                      set(() => trabajando = true);
                      final e = await cierre.imprimir(c, nombreCajero, pend);
                      if (!ctx.mounted) return;
                      set(() {
                        trabajando = false;
                        error = e.isEmpty ? '' : 'No se imprimió: $e';
                        if (e.isEmpty)
                          nota =
                              'Conteo enviado a la impresora de comprobantes';
                      });
                    },
              icon: const Icon(Icons.print_outlined),
              label: const Text('Imprimir conteo'),
            ),
            Tooltip(
              message: pend == null
                  ? 'Requiere cierre de caja pendiente'
                  : cola > 0
                  ? 'Primero hay que enviar la cola (se necesita internet)'
                  : 'Contabilizar este cierre',
              child: FilledButton.icon(
                onPressed: !puedeContabilizar
                    ? null
                    : () async {
                        leer();
                        final d = redondear(c.total - pend!.totalCaja, 2);
                        if (d.abs() > 0.01 &&
                            !await confirmar(
                              ctx,
                              'Diferencia en el cierre',
                              'El cierre tiene una diferencia de ₡${fmt(d)}.\n\n¿Desea contabilizar de todos modos?',
                              'Contabilizar',
                            )) {
                          return;
                        }
                        // Justo antes: la cola tiene que seguir vacía.
                        final n = await colaPendiente();
                        if (n > 0) {
                          set(() {
                            cola = n;
                            error =
                                'No se puede contabilizar el cierre: hay $n procesos en la cola sin enviar.';
                          });
                          return;
                        }
                        set(() => trabajando = true);
                        final (ok, e) = await cierre.contabilizar(pend!, c);
                        if (!ctx.mounted) return;
                        if (e.isEmpty) return Navigator.pop(ctx, ok);
                        set(() {
                          trabajando = false;
                          error = e;
                        });
                      },
                icon: const Icon(Icons.task_alt),
                label: const Text('Contabilizar'),
              ),
            ),
          ],
        );
      },
    ),
  );
}
