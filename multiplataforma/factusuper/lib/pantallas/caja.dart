/// La CAJA (#3957) — dueño: «un diseño muy elegante, muy atractivo, profesional».
/// Izquierda: buscador + líneas. Derecha: cliente, totales y cobro por medio de pago. Atajos de teclado para la fila.
/// La venta se guarda en el equipo y sale sola al servidor (mismo transaccionId); la venta EN CURSO también se guarda
/// en cada cambio (si se va la luz, al abrir sigue ahí).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../caja/cajeros.dart';
import '../caja/cajon.dart';
import '../caja/cola.dart';
import '../caja/datos_caja.dart';
import '../caja/documento.dart';
import '../datos/almacen.dart';
import '../datos/conexion.dart';
import '../datos/descarga.dart';
import '../motor/linea.dart';
import '../motor/redondeo.dart';
import '../ui/dialogos.dart';
import '../ui/tema.dart';

class PantallaCaja extends StatefulWidget {
  final ConfigCaja config;
  final Almacen almacen;
  final DatosCaja datos;
  final Cola cola;
  final Cajeros cajeros;
  final Cajero cajero;
  final VoidCallback alSalir;

  /// «Actualizar datos»: vuelve a bajar todo con este cajero (lo hace main, que arma los datos de nuevo).
  final Future<String> Function()? alActualizar;
  const PantallaCaja({
    super.key,
    this.alActualizar,
    required this.config,
    required this.almacen,
    required this.datos,
    required this.cola,
    required this.cajeros,
    required this.cajero,
    required this.alSalir,
  });

  @override
  State<PantallaCaja> createState() => _EstadoCaja();
}

class _EstadoCaja extends State<PantallaCaja> {
  late final Documento doc = Documento(widget.datos, widget.cajero);
  final _buscar = TextEditingController();
  final _focoBuscar = FocusNode();
  final _scroll = ScrollController();
  final _notas = TextEditingController();
  List<Map<String, dynamic>> _resultados = [];
  int _sel = -1;

  /// Líneas marcadas con la casilla: la barra de descuentos / nivel de precio / IVA actúa sobre ellas (como la web).
  final Set<int> _marcadas = {};
  Timer? _reloj;
  bool _enviando = false;
  String _ultimoEnvio = '';

  /// Modo lector (como «Modo barras» de la web): encendido, lo escaneado entra con cantidad 1; apagado, primero pide la cantidad.
  bool _modoLector = true;

  Future<void> _leerPreferencias() async {
    final p = await widget.almacen.leerTabla(
      widget.config.empresa,
      'preferencias',
    );
    if (p is Map && p['modoLector'] == false && mounted)
      setState(() => _modoLector = false);
  }

  void _ponerModoLector(bool v) {
    setState(() => _modoLector = v);
    widget.almacen.guardarTabla(widget.config.empresa, 'preferencias', {
      'modoLector': v,
    });
    _aviso(
      v
          ? 'Modo lector: cada código entra con cantidad 1'
          : 'Modo lector apagado: primero se pide la cantidad',
    );
    _foco();
  }

  Future<void> _romana() async {
    final r = await dialogoRomana(
      context,
      llave: widget.config.llave,
      cajero: widget.cajero.usuario,
      actual:
          widget.datos.romana ??
          (widget.datos.catalogos['romana'] as List?)?.firstOrNull
              as Map<String, dynamic>?,
    );
    if (r != null) {
      widget.datos.romanaPoner(r);
      _aviso(
        'Romana ${r['activo'] == 1 ? 'activa' : 'desactivada'}: configuración guardada',
      );
    }
    _foco();
  }

  Future<void> _actualizarDatos() async {
    final f = widget.alActualizar;
    if (f == null) return;
    if (doc.lineas.isNotEmpty)
      return _aviso(
        'Termine o anule la venta antes de actualizar los datos',
        error: true,
      );
    _aviso('Bajando los datos de la empresa…');
    final r = await f();
    _aviso(r, error: r.startsWith('No '));
  }

  @override
  void initState() {
    super.initState();
    _restaurar();
    _leerPreferencias();
    _reloj = Timer.periodic(const Duration(seconds: 60), (_) => _enviar());
    _enviar();
  }

  Future<void> _restaurar() async {
    final m = await widget.almacen.leerTabla(
      widget.config.empresa,
      'documento',
    );
    if (m is Map && (m['lineas'] as List? ?? const []).isNotEmpty && mounted) {
      setState(() {
        doc.restaurar(Map<String, dynamic>.from(m));
        _notas.text = doc.notas;
      });
      _aviso(
        'Se recuperó la venta que estaba en curso (${doc.lineas.length} líneas)',
      );
    }
  }

  @override
  void dispose() {
    _reloj?.cancel();
    super.dispose();
  }

  /// Cada cambio: se pinta y la venta en curso queda en el disco.
  void _cambio([VoidCallback? f]) {
    setState(f ?? () {});
    _marcadas.removeWhere((i) => i >= doc.lineas.length);
    if (_notas.text != doc.notas) _notas.text = doc.notas;
    widget.almacen.guardarTabla(
      widget.config.empresa,
      'documento',
      doc.aMapa(),
    );
  }

  void _aviso(String t, {bool error = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Row(
            children: [
              Icon(
                error ? Icons.error_outline : Icons.check_circle_outline,
                color: Colors.white,
              ),
              const SizedBox(width: 10),
              Expanded(child: Text(t)),
            ],
          ),
          backgroundColor: error ? Marca.rojo : Marca.tinta,
          duration: Duration(seconds: error ? 6 : 3),
        ),
      );
  }

  Future<void> _enviar() async {
    if (_enviando) return;
    if (widget.cola.pendientes.isEmpty &&
        (await _cajonObj.pendientes()).isEmpty)
      return;
    setState(() => _enviando = true);
    await _cajonObj.subirPendientes(widget.cajero.usuario);
    final r = await widget.cola.enviar();
    if (!mounted) return;
    setState(() {
      _enviando = false;
      _ultimoEnvio = r.detenida;
    });
    if (r.procesadas > 0)
      _aviso(
        '${r.procesadas} ${r.procesadas == 1 ? 'venta facturada' : 'ventas facturadas'} en el servidor',
      );
    if (r.rechazadas > 0)
      _aviso(
        '${r.rechazadas} ${r.rechazadas == 1 ? 'venta rechazada' : 'ventas rechazadas'}: revise la lista de ventas',
        error: true,
      );
  }

  void _foco() => _focoBuscar.requestFocus();

  // ── Cambios del servidor al agregar (revisarCambiosAlAgregar de la web): en segundo plano, como mucho cada 10 s ──
  bool _revisando = false;
  DateTime _ultimaRevision = DateTime.fromMillisecondsSinceEpoch(0);

  Future<void> _revisarCambiosAlAgregar() async {
    if (_revisando ||
        DateTime.now().difference(_ultimaRevision) <
            const Duration(seconds: 10))
      return;
    _revisando = true;
    _ultimaRevision = DateTime.now();
    final con = Conexion(
      llave: widget.config.llave,
      cajero: widget.cajero.usuario,
    );
    try {
      final r = await Descarga(
        con,
        widget.almacen,
        widget.config.empresa,
      ).sincronizarSiHaceFalta(soloCambios: true);
      final c = r.cambios;
      if (c == null || !mounted) return;
      await widget.datos.recargar(
        widget.almacen,
        widget.config.empresa,
        grupos: (c['hechos'] as List).cast<String>(),
      );
      final n = doc.aplicarPreciosNuevos(
        (c['codigos'] as List? ?? const []).map((x) => '$x'),
      );
      if (n > 0) {
        _cambio();
        _aviso(
          'Precio actualizado desde el servidor en $n ${n == 1 ? 'línea' : 'líneas'}',
        );
      }
    } catch (_) {
      // sin internet / el servidor no contestó: se sigue con la copia del equipo
    } finally {
      con.cerrar();
      _revisando = false;
    }
  }

  /// «Revisar cambios» (menú): solo lo que cambió, ya.
  Future<void> _revisarCambios() async {
    final con = Conexion(
      llave: widget.config.llave,
      cajero: widget.cajero.usuario,
    );
    try {
      final r = await Descarga(
        con,
        widget.almacen,
        widget.config.empresa,
      ).sincronizarSiHaceFalta();
      if (r.estado == 'sin_conexion')
        return _aviso(
          'Sin conexión: se sigue con los datos del equipo',
          error: true,
        );
      if (r.estado == 'al_dia') return _aviso('Los datos están al día');
      await widget.datos.recargar(widget.almacen, widget.config.empresa);
      doc.lineas.forEach(doc.agregarRecalculo); // decimales/parámetros nuevos
      final c = r.cambios;
      final partes = [
        if (c != null && (c['hechos'] as List).contains('articulos'))
          '${c['articulos']} artículos cambiados${(c['bajas'] as int) > 0 ? ' y ${c['bajas']} de baja' : ''}',
        if (c != null && (c['hechos'] as List).contains('clientes'))
          '${c['clientes']} clientes nuevos o cambiados',
        if (r.grupos.isNotEmpty) 'se bajó: ${r.grupos.join(', ')}',
      ];
      _cambio();
      _aviso(
        'Datos actualizados${partes.isEmpty ? '' : ' · ${partes.join(' · ')}'}',
      );
    } on ErrorConexion catch (e) {
      _aviso('No se pudo sincronizar: ${e.mensaje}', error: true);
    } finally {
      con.cerrar();
    }
  }

  // ── Agregar ──
  Future<void> _agregar(
    Map<String, dynamic> art, {
    String cantidad = '1',
  }) async {
    var r = doc.agregar(art, cantidad);
    if (r.preguntarRepetido) {
      final m = await showDialog<String>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Ya está en la venta'),
          content: Text('«${art['nombre']}»'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancelar'),
            ),
            if (r.permiteNueva)
              OutlinedButton(
                onPressed: () => Navigator.pop(c, 'nueva'),
                child: const Text('Línea nueva'),
              ),
            FilledButton(
              autofocus: true,
              onPressed: () => Navigator.pop(c, 'sumar'),
              child: const Text('Sumar'),
            ),
          ],
        ),
      );
      if (m == null) return _foco();
      r = doc.agregar(art, cantidad, repetido: m);
    }
    _cambio(() {
      _resultados = [];
      _buscar.clear();
      if (r.ok) _sel = doc.lineas.indexOf(r.linea!);
    });
    if (r.ok) _revisarCambiosAlAgregar();
    final pc = r.ok ? Documento.cabysProblema(r.linea!) : '';
    if (!r.ok) {
      _aviso(r.motivo, error: true);
    } else if (pc.isNotEmpty) {
      _aviso(
        '«${art['nombre']}» $pc: así no se puede facturar (Hacienda la rechaza). Corrija el CABYS en la ficha del artículo.',
        error: true,
      );
    } else if (r.avisos.isNotEmpty) {
      _aviso(r.avisos.join(' · '), error: true);
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients)
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
    });
    _foco();
  }

  /// Enter: «3*código» = 3 unidades; exacto por código/barras → se agrega; si no, la lista.
  /// Enter en el buscador — mismo orden que agregarDesdeBuscador() de la web:
  /// «3*código» · exacto por código/barras (sin modo lector → primero pide la cantidad) · etiqueta de ROMANA · búsqueda.
  Future<void> _alEnter(String texto) async {
    texto = texto.trim();
    if (texto.isEmpty) return;
    var cant = '1';
    final m = RegExp(r'^(\d+(?:[.,]\d+)?)\s*\*\s*(.+)$').firstMatch(texto);
    if (m != null) {
      cant = m.group(1)!;
      texto = m.group(2)!.trim();
    }
    final a = widget.datos.articuloExacto(texto);
    if (a != null) {
      if (m == null && !_modoLector) {
        final c = await pedirCantidad(context, '${a['nombre']}');
        if (c == null) return _foco();
        cant = c;
      }
      _agregar(a, cantidad: cant);
      return;
    }
    final rom = widget.datos.romanaLeer(texto);
    if (rom != null) {
      if (rom['error'] != null) return _aviso('${rom['error']}', error: true);
      final art = rom['articulo'] as Map<String, dynamic>;
      _aviso(
        'Romana: cantidad ${fmt(rom['cantidad'] as num, 3)} (${rom['tipo'] == 'precio' ? 'por precio' : 'por peso'})',
      );
      // Como FactuDesk: SUMA directo, y el peso va con 3 decimales aunque CF-020 diga 2 (#1909c).
      final r = doc.agregar(
        art,
        '${rom['cantidad']}',
        repetido: 'sumar',
        decimales: 3,
      );
      _cambio(() {
        _buscar.clear();
        if (r.ok) _sel = doc.lineas.indexOf(r.linea!);
      });
      if (!r.ok) _aviso(r.motivo, error: true);
      return _foco();
    }
    final l = widget.datos.buscar(texto, limite: 80);
    if (l.isEmpty) {
      _aviso('No se encontró «$texto»', error: true);
      _buscar.selection = TextSelection(
        baseOffset: 0,
        extentOffset: _buscar.text.length,
      );
      _foco();
    } else {
      setState(() => _resultados = l);
    }
  }

  /// F2: la lista de artículos con lo que haya escrito.
  void _abrirBusqueda() {
    final t = _buscar.text.trim();
    setState(
      () => _resultados = t.isEmpty
          ? widget.datos.articulos.take(80).toList()
          : widget.datos.buscar(t, limite: 80),
    );
    _foco();
  }

  /// Quitar líneas: permiso 059 o la clave de un supervisor (puedeQuitar de la web).
  Future<bool> _puedeQuitar() async {
    if (doc.tienePermiso('059')) return true;
    final a = await dialogoSupervisor(
      context,
      widget.cajeros,
      const Validacion(
        permiso: '059',
        motivo: 'Eliminar líneas requiere el permiso 059.',
      ),
    );
    return a is Cajero;
  }

  Future<void> _editar(int i) async {
    if (i < 0 || i >= doc.lineas.length) return;
    if (await dialogoLinea(context, doc, widget.cajeros, i)) _cambio();
    _foco();
  }

  Future<void> _quitar(int i) async {
    if (i < 0 || i >= doc.lineas.length) return;
    if (!await _puedeQuitar()) return _foco();
    _cambio(() {
      doc.quitar(i);
      _sel = doc.lineas.isEmpty
          ? -1
          : (i >= doc.lineas.length ? doc.lineas.length - 1 : i);
    });
    _foco();
  }

  // ── Barra de las líneas marcadas (FactuDesk / web): descuentos rápidos (004), nivel de precio, tarifa de IVA ──
  bool _barraEnCurso = false;

  Future<void> _descuentoLote(double pct) async {
    if (_barraEnCurso) return;
    _barraEnCurso = true;
    try {
      final idx = _marcadas.toList()..sort();
      final ok = <int>[],
          ajustados = <String>[],
          fallos = <String>[],
          autorizo = <String, String>{};
      String nom(Linea l) => '${l.codigo} ${l.nombre}';
      CambiosLinea cam(Linea l, double v) => CambiosLinea(
        cantidad: l.cantidad,
        precio: l.precio,
        modo: 'pct',
        valor: v,
        montoConfirmado: true,
      );
      final p023 = <int>[], p006 = <int>[];
      for (final i in idx) {
        final l = doc.lineas[i];
        if (l.nivelBloqueado) {
          fallos.add('${nom(l)}: el precio ${l.nivel} es «sin descuento»');
          continue;
        }
        final v = doc.validarLinea(l, cam(l, pct), const {});
        if (v.ok) {
          doc.aplicarLinea(l, cam(l, pct), const {});
          ok.add(i);
        } else if (v.permiso == '023') {
          doc.aplicarLinea(l, cam(l, l.descMax), const {});
          p023.add(i);
        } else if (v.permiso == '006') {
          doc.aplicarLinea(l, cam(l, 0), const {});
          p006.add(i);
        } else {
          fallos.add('${nom(l)}: ${v.error.isNotEmpty ? v.error : v.motivo}');
        }
      }
      String? a023;
      if (p023.isNotEmpty && mounted) {
        final r = await dialogoSupervisor(
          context,
          widget.cajeros,
          Validacion(
            permiso: '023',
            motivo:
                'El descuento ${fmt(pct, doc.dec.descPct)} % supera el máximo en ${p023.length} ${p023.length == 1 ? 'línea' : 'líneas'}. Quedaron topadas al máximo.',
          ),
        );
        if (r is Cajero) {
          a023 = r.usuario;
          autorizo['023'] = r.nombre;
          for (final i in p023) {
            final l = doc.lineas[i];
            final v = doc.validarLinea(l, cam(l, pct), {'023'});
            if (v.ok) {
              doc.aplicarLinea(l, cam(l, pct), {'023': r.usuario});
              ok.add(i);
            } else if (v.permiso == '006') {
              p006.add(i);
            } else {
              fallos.add(
                '${nom(l)}: ${v.error.isNotEmpty ? v.error : 'no se aplicó'}',
              );
            }
          }
        } else {
          for (final i in p023) {
            ajustados.add(
              '${nom(doc.lineas[i])}: quedó en el máximo (${fmt(doc.lineas[i].descMax, doc.dec.descPct)} %)',
            );
          }
        }
      }
      if (p006.isNotEmpty && mounted) {
        final r = await dialogoSupervisor(
          context,
          widget.cajeros,
          Validacion(
            permiso: '006',
            motivo:
                'El descuento ${fmt(pct, doc.dec.descPct)} % deja ${p006.length} ${p006.length == 1 ? 'línea' : 'líneas'} bajo la utilidad mínima.',
          ),
        );
        if (r is Cajero) {
          autorizo['006'] = r.nombre;
          for (final i in p006) {
            final l = doc.lineas[i];
            final auth = {'006': r.usuario, if (a023 != null) '023': a023};
            final v = doc.validarLinea(l, cam(l, pct), auth.keys.toSet());
            if (v.ok) {
              doc.aplicarLinea(l, cam(l, pct), auth);
              ok.add(i);
            } else {
              fallos.add(
                '${nom(l)}: ${v.error.isNotEmpty ? v.error : 'no se aplicó'}',
              );
            }
          }
        } else {
          for (final i in p006) {
            ajustados.add(
              '${nom(doc.lineas[i])}: quedó en ${fmt(doc.lineas[i].descuento, doc.dec.descPct)} % (utilidad mínima)',
            );
          }
        }
      }
      _cambio();
      final partes = [
        if (ok.isNotEmpty)
          'Descuento ${fmt(pct, pct % 1 == 0 ? 0 : 2)} % aplicado a ${ok.length} ${ok.length == 1 ? 'línea' : 'líneas'}',
        if (autorizo.isNotEmpty)
          'autorizó ${autorizo.entries.map((e) => '${e.value} (${e.key})').join(', ')}',
        if (ajustados.isNotEmpty) 'Ajustadas: ${ajustados.join(' · ')}',
        if (fallos.isNotEmpty) 'No se aplicó: ${fallos.join(' · ')}',
      ];
      _aviso(
        partes.isEmpty ? 'No se aplicó el descuento' : partes.join(' — '),
        error: fallos.isNotEmpty || ajustados.isNotEmpty,
      );
    } finally {
      _barraEnCurso = false;
      _foco();
    }
  }

  void _nivelLote(int nivel) {
    final saltadas = <String>[], avisos = <String>[];
    var ok = 0;
    for (final i in _marcadas.toList()..sort()) {
      final l = doc.lineas[i];
      final (bien, motivo, av) = doc.cambiarNivel(i, nivel);
      if (bien) {
        ok++;
        avisos.addAll(av.map((a) => '${l.codigo}: $a'));
      } else {
        saltadas.add('${l.codigo}: $motivo');
      }
    }
    _cambio();
    final t = [
      if (ok > 0)
        'Precio P$nivel aplicado a $ok ${ok == 1 ? 'línea' : 'líneas'}',
      if (saltadas.isNotEmpty) 'No se cambió: ${saltadas.join(' · ')}',
      if (avisos.isNotEmpty) avisos.join(' · '),
    ];
    _aviso(
      t.isEmpty ? 'Sin cambios' : t.join(' — '),
      error: saltadas.isNotEmpty || avisos.isNotEmpty,
    );
    _foco();
  }

  void _tarifaLote(Map<String, dynamic> t) {
    final pct = ((t['porcentaje'] as num?) ?? 0).toDouble();
    for (final i in _marcadas) {
      doc.cambiarTarifa(i, '${t['codigo']}', pct);
    }
    _cambio();
    _aviso(
      'IVA ${fmt(pct, pct % 1 == 0 ? 0 : 2)} % (${t['codigo']}) aplicado a ${_marcadas.length} ${_marcadas.length == 1 ? 'línea' : 'líneas'}',
    );
    _foco();
  }

  Future<void> _quitarMarcadas() async {
    if (!await _puedeQuitar()) return _foco();
    final fuera = _marcadas.toList()..sort((a, b) => b.compareTo(a));
    _cambio(() {
      for (final i in fuera) {
        doc.quitar(i);
      }
      _marcadas.clear();
      _sel = -1;
    });
    _foco();
  }

  /// F5 (como la web): con líneas marcadas → la barra; si no, se edita la línea elegida (o la única).
  void _accionDescuento() {
    if (doc.lineas.isEmpty)
      return _aviso('La venta no tiene artículos.', error: true);
    if (_marcadas.isNotEmpty)
      return _aviso('Elija el porcentaje en la barra de descuentos.');
    final i = _sel >= 0 ? _sel : (doc.lineas.length == 1 ? 0 : -1);
    if (i < 0)
      return _aviso(
        'Marque las líneas (casilla) o elija una línea.',
        error: true,
      );
    _editar(i);
  }

  Widget _barraMarcadas() {
    final puede = doc.tienePermiso('004');
    Widget chip(String t, VoidCallback? f, {Color? color, String? tip}) =>
        Tooltip(
          message: tip ?? '',
          child: ActionChip(
            label: Text(
              t,
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: f == null ? Marca.tintaSuave : (color ?? Marca.azul),
              ),
            ),
            backgroundColor: f == null ? Marca.borde : Colors.white,
            side: BorderSide(
              color: f == null
                  ? Marca.borde
                  : (color ?? Marca.azul).withValues(alpha: 0.35),
            ),
            onPressed: f,
          ),
        );
    Widget grupo(String titulo, List<Widget> hijos) => Padding(
      padding: const EdgeInsets.only(right: 18),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            titulo,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: Marca.tintaSuave,
              letterSpacing: 0.6,
            ),
          ),
          const SizedBox(width: 8),
          ...hijos.expand((w) => [w, const SizedBox(width: 6)]),
        ],
      ),
    );
    return Container(
      color: Marca.azulClaro,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: Row(
        children: [
          Text(
            '${_marcadas.length} ${_marcadas.length == 1 ? 'línea' : 'líneas'}',
            style: const TextStyle(
              fontWeight: FontWeight.w700,
              color: Marca.azul,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  grupo('DESCUENTO', [
                    for (final p in doc.escalaDescuentos())
                      chip(
                        '${fmt(p, p % 1 == 0 ? 0 : doc.dec.descPct)} %',
                        puede ? () => _descuentoLote(p) : null,
                        color: Marca.verdeOscuro,
                        tip: puede
                            ? null
                            : 'Sin permiso para aplicar descuentos (004)',
                      ),
                  ]),
                  grupo('PRECIO', [
                    for (final n in widget.datos.nivelesPrecio)
                      chip('P$n', () => _nivelLote(n)),
                  ]),
                  if (widget.datos.tarifasIva.isNotEmpty)
                    grupo('IVA', [
                      for (final t in widget.datos.tarifasIva)
                        chip(
                          '${fmt((t['porcentaje'] as num?) ?? 0, ((t['porcentaje'] as num?) ?? 0) % 1 == 0 ? 0 : 2)} %',
                          () => _tarifaLote(t),
                          color: const Color(0xFF7C3AED),
                          tip: '${t['codigo']} - ${t['nombre'] ?? ''}',
                        ),
                    ]),
                ],
              ),
            ),
          ),
          IconButton(
            tooltip: 'Quitar las marcadas',
            onPressed: _quitarMarcadas,
            icon: const Icon(Icons.delete_outline, color: Marca.rojo),
          ),
          IconButton(
            tooltip: 'Desmarcar',
            onPressed: () => setState(_marcadas.clear),
            icon: const Icon(Icons.close, color: Marca.tintaSuave),
          ),
        ],
      ),
    );
  }

  late final Cajon _cajonObj = Cajon(
    widget.almacen,
    widget.config,
    widget.datos,
  );

  /// F9 — abrir el cajón: permiso 141 o la clave de un supervisor.
  Future<void> _cajon() async {
    var autoriza = '';
    if (!doc.tienePermiso('141')) {
      final a = await dialogoSupervisor(
        context,
        widget.cajeros,
        const Validacion(
          permiso: '141',
          motivo: 'Abrir el cajón requiere permiso (141) o la clave de un supervisor.',
        ),
      );
      if (a is! Cajero) return _foco();
      autoriza = a.nombre;
    }
    final (ok, via, error) = await _cajonObj.abrir(
      cajero: widget.cajero.usuario,
      usuario: '${widget.cajero.usuario} ${widget.cajero.nombre}',
      autoriza: autoriza,
    );
    _aviso(
      ok
          ? 'Cajón abierto${via == 'equipo' ? ' (por FactuPOS Print de este equipo)' : ''}'
          : 'No se pudo abrir el cajón: $error',
      error: !ok,
    );
    _foco();
  }

  Future<void> _consulta() async {
    await dialogoConsulta(
      context,
      widget.datos,
      verCosto: doc.tienePermiso('064'),
      texto: _buscar.text.trim(),
      stock: (codigo) async {
        final con = Conexion(
          llave: widget.config.llave,
          cajero: widget.cajero.usuario,
        );
        try {
          final j = await con.get(
            '/apis/shared/articulos/articulo_detalle_obtener.php',
            query: {'solo': 'bodegas', 'codigo': codigo},
            espera: const Duration(seconds: 4),
          );
          return j['success'] == true ? j : null;
        } catch (_) {
          return null;
        } finally {
          con.cerrar();
        }
      },
    );
    _foco();
  }

  Future<void> _cliente() async {
    final c = await dialogoCliente(context, widget.datos);
    if (c != null) {
      _cambio(() => doc.asignarCliente(c));
      _aviso('Cliente: ${c['nombre']}');
    }
    _foco();
  }

  // ── Cobrar ──
  Future<void> _cobrar(String medioInicial) async {
    final imp = doc.impedimento();
    if (imp.isNotEmpty) {
      await avisoDialogo(context, 'No se puede cobrar', imp);
      return _foco();
    }
    final medios = widget.datos.mediosPago();
    if (medios.isEmpty)
      return _aviso(
        'No hay medios de pago en este equipo: vuelva a bajar los datos desde Configuración.',
        error: true,
      );
    // Medio principal → IVA devuelto con tarjeta.
    final principal = medioInicial == '02' ? '02' : '01';
    if (doc.medioPago != principal) {
      doc.medioPago = principal;
      doc.lineas.forEach(doc.agregarRecalculo);
      setState(() {});
    }
    final total = doc.totales.total;
    final r = await dialogoCobro(
      context,
      total: total,
      medios: medios,
      medioInicial: medioInicial,
      credito: _infoCredito(total),
    );
    if (r == null) return _foco();
    final ahora = DateTime.now();
    final pq = doc.paquete(
      pagos: r.pagos,
      vuelto: r.vuelto,
      transaccionId: uuidV4(),
      cuando: ahora,
      tipoPago: r.tipoPago,
      diasCredito: r.diasCredito,
    );
    final suma = r.pagos.fold<double>(
      0,
      (a, p) => a + ((p['monto'] as num?)?.toDouble() ?? 0),
    );
    if (r.tipoPago == 'contado' &&
        (suma - (pq['total'] as num)).abs() > 0.005) {
      return _aviso(
        'Los pagos (₡${fmt(suma)}) no cuadran con el total (₡${fmt(pq['total'] as num)}).',
        error: true,
      );
    }
    try {
      await widget.cola.agregar(pq);
    } catch (e) {
      return _aviso(
        'No se pudo guardar la venta en el equipo: $e',
        error: true,
      );
    }
    _cambio(() {
      doc.nuevo();
      _sel = -1;
    });
    if (r.tipoPago == 'contado' && r.vuelto > 0 && mounted)
      await dialogoVuelto(context, r.vuelto);
    _aviso(
      'Factura en proceso · ${(pq['documento'] as Map)['idProceso']} · ₡${fmt(total)}',
    );
    _foco();
    _enviar();
  }

  /// Crédito (evaluarCredito de la web): hace falta cliente; con 0 días de plazo y param 937 = 0 no se permite.
  /// La TieneCredito del cliente NO decide (FactuDesk no la mira): el control real es el del servidor (credito_revisar).
  InfoCredito _infoCredito(double total) {
    final c = doc.cliente;
    final dias =
        int.tryParse('${c['plazo'] ?? 0}') ??
        (double.tryParse('${c['plazo']}')?.toInt() ?? 0);
    if ('${c['codigo'] ?? ''}'.isEmpty ||
        '${c['codigo']}'.toUpperCase() == 'SN') {
      return const InfoCredito(
        motivo: 'Elija un cliente (F3) para vender a crédito',
      );
    }
    final p937 = widget.datos.parametros[937];
    if (dias <= 0 && p937 != null && p937.trim() == '0') {
      return const InfoCredito(
        motivo: 'El cliente tiene 0 días de plazo (parámetro 937)',
      );
    }
    return InfoCredito(
      permitido: true,
      dias: dias,
      revisar: () async {
        final con = Conexion(
          llave: widget.config.llave,
          cajero: widget.cajero.usuario,
        );
        try {
          final j = await con.get(
            'credito_revisar.php',
            query: {'cliente': '${c['codigo']}', 'total': '${r2(total)}'},
            espera: const Duration(seconds: 6),
          );
          return j['success'] == true ? j : null;
        } catch (_) {
          return null;
        } finally {
          con.cerrar();
        }
      },
    );
  }

  Future<void> _anular() async {
    if (doc.lineas.isEmpty) return;
    if (!await _puedeQuitar()) return _foco();
    if (await confirmar(
      context,
      '¿Anular la venta?',
      'Se quitan las ${doc.lineas.length} líneas. No se factura nada.',
      'Sí, anular',
    )) {
      _cambio(() {
        doc.nuevo();
        _sel = -1;
      });
    }
    _foco();
  }

  Map<ShortcutActivator, VoidCallback> get _atajos => {
    // Las MISMAS teclas de FactuSuper web (y FactuDesk): F2 artículo · F3 cliente · F4 cobrar · * cobrar.
    const SingleActivator(LogicalKeyboardKey.f2): _abrirBusqueda,
    const SingleActivator(LogicalKeyboardKey.f3): _cliente,
    const SingleActivator(LogicalKeyboardKey.f4): () => _cobrar('01'),
    const SingleActivator(LogicalKeyboardKey.f5): _accionDescuento,
    const SingleActivator(LogicalKeyboardKey.f6): _consulta,
    const SingleActivator(LogicalKeyboardKey.f9): _cajon,
    const SingleActivator(LogicalKeyboardKey.enter, control: true): () =>
        _editar(_sel),
    const SingleActivator(LogicalKeyboardKey.delete): () => _quitar(_sel),
    const SingleActivator(LogicalKeyboardKey.arrowUp): () => setState(
      () => _sel = doc.lineas.isEmpty ? -1 : (_sel <= 0 ? 0 : _sel - 1),
    ),
    const SingleActivator(LogicalKeyboardKey.arrowDown): () => setState(
      () => _sel = doc.lineas.isEmpty
          ? -1
          : (_sel + 1).clamp(0, doc.lineas.length - 1),
    ),
    const SingleActivator(LogicalKeyboardKey.escape): () => setState(() {
      _resultados = [];
      _buscar.clear();
    }),
  };

  // ═══════════ Pantalla ═══════════
  @override
  Widget build(BuildContext context) {
    return CallbackShortcuts(
      bindings: _atajos,
      child: Scaffold(
        appBar: _barra(),
        body: LayoutBuilder(
          builder: (context, c) {
            final ancho = c.maxWidth >= 980;
            if (ancho) {
              return Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(20, 20, 10, 20),
                      child: _zonaLineas(),
                    ),
                  ),
                  SizedBox(
                    width: 400,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(10, 20, 20, 20),
                      child: _panel(),
                    ),
                  ),
                ],
              );
            }
            return Column(
              children: [
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                    child: _zonaLineas(),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: _panelCompacto(),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  PreferredSizeWidget _barra() {
    final cfg = widget.config;
    final est = widget.datos.estacion;
    final pend = widget.cola.pendientes.length;
    final sinRed = _ultimoEnvio.isNotEmpty && pend > 0;
    final angosto = MediaQuery.sizeOf(context).width < 700;
    return AppBar(
      toolbarHeight: 64,
      titleSpacing: 20,
      title: Row(
        children: [
          Logo(tam: angosto ? 16 : 20),
          if (!angosto) const SizedBox(width: 18),
          if (!angosto) Container(width: 1, height: 28, color: Colors.white24),
          if (!angosto) const SizedBox(width: 18),
          if (!angosto)
            Flexible(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    cfg.empresaNombre.isEmpty ? cfg.empresa : cfg.empresaNombre,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  Text(
                    _textoEstacion(est),
                    style: TextStyle(
                      fontSize: 12,
                      color: Colors.white.withValues(alpha: 0.7),
                      fontWeight: FontWeight.w400,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
      actions: [
        Tooltip(
          message: sinRed ? _ultimoEnvio : 'Ver las ventas de esta caja',
          child: InkWell(
            borderRadius: BorderRadius.circular(20),
            onTap: () => dialogoVentas(context, widget.cola.ventas, _enviar),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Row(
                children: [
                  if (_enviando)
                    const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  else
                    Icon(
                      pend == 0
                          ? Icons.cloud_done_outlined
                          : sinRed
                          ? Icons.cloud_off_outlined
                          : Icons.cloud_upload_outlined,
                      size: 18,
                      color: pend == 0
                          ? const Color(0xFF6EE7B7)
                          : sinRed
                          ? const Color(0xFFFCD34D)
                          : Colors.white,
                    ),
                  const SizedBox(width: 8),
                  Text(
                    pend == 0
                        ? (angosto ? '' : 'Todo enviado')
                        : (angosto ? '$pend' : '$pend por enviar'),
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(width: 12),
        PopupMenuButton<String>(
          tooltip: 'Cajero',
          offset: const Offset(0, 48),
          onSelected: (v) {
            switch (v) {
              case 'salir':
                if (doc.lineas.isNotEmpty)
                  return _aviso(
                    'Termine o anule la venta antes de salir',
                    error: true,
                  );
                widget.alSalir();
              case 'lector':
                _ponerModoLector(!_modoLector);
              case 'romana':
                _romana();
              case 'datos':
                _actualizarDatos();
              case 'cambios':
                _revisarCambios();
            }
          },
          itemBuilder: (_) => [
            CheckedPopupMenuItem(
              value: 'lector',
              checked: _modoLector,
              child: const Text('Modo lector de barras'),
            ),
            const PopupMenuItem(
              value: 'romana',
              child: ListTile(
                leading: Icon(Icons.scale_outlined),
                title: Text('Romana / balanza'),
              ),
            ),
            const PopupMenuItem(
              value: 'cambios',
              child: ListTile(
                leading: Icon(Icons.update),
                title: Text('Revisar cambios'),
              ),
            ),
            const PopupMenuItem(
              value: 'datos',
              child: ListTile(
                leading: Icon(Icons.sync),
                title: Text('Actualizar datos (todo)'),
              ),
            ),
            const PopupMenuDivider(),
            const PopupMenuItem(
              value: 'salir',
              child: ListTile(
                leading: Icon(Icons.logout),
                title: Text('Salir (cambiar cajero)'),
              ),
            ),
          ],
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Row(
              children: [
                CircleAvatar(
                  radius: 16,
                  backgroundColor: Marca.verde,
                  child: Text(
                    widget.cajero.nombre.isEmpty
                        ? '?'
                        : widget.cajero.nombre[0],
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  angosto ? '' : widget.cajero.nombre,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                const Icon(Icons.expand_more, color: Colors.white70),
              ],
            ),
          ),
        ),
        const SizedBox(width: 12),
      ],
    );
  }

  /// «CAJA 3» (nombre de la estación) · «Caja 3» solo si el nombre no lo dice ya.
  static String _textoEstacion(Map<String, dynamic> est) {
    final n = '${est['nombre'] ?? ''}'.trim(),
        c = '${est['caja'] ?? ''}'.trim();
    if (n.isEmpty) return 'Caja ${c.isEmpty ? '1' : c}';
    return c.isEmpty || n.toUpperCase().contains(c) ? n : '$n · Caja $c';
  }

  Widget _zonaLineas() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Focus(
          // Esc en el buscador: cierra la lista de resultados (el campo de texto se la quedaba).
          onKeyEvent: (_, e) {
            if (e is KeyDownEvent &&
                e.logicalKey == LogicalKeyboardKey.escape &&
                (_resultados.isNotEmpty || _buscar.text.isNotEmpty)) {
              setState(() {
                _resultados = [];
                _buscar.clear();
              });
              return KeyEventResult.handled;
            }
            return KeyEventResult.ignored;
          },
          child: TextField(
            controller: _buscar,
            focusNode: _focoBuscar,
            autofocus: true,
            style: const TextStyle(fontSize: 18),
            decoration: InputDecoration(
              prefixIcon: const Padding(
                padding: EdgeInsets.symmetric(horizontal: 14),
                child: Icon(Icons.qr_code_scanner, color: Marca.azul),
              ),
              hintText: 'Escanee o escriba código, barras o nombre',
              suffixIcon: MediaQuery.sizeOf(context).width < 700
                  ? null
                  : Padding(
                      padding: const EdgeInsets.only(right: 12),
                      child: Center(
                        widthFactor: 1,
                        child: Text(
                          '3*código = 3 unid.',
                          style: TextStyle(
                            color: Marca.tintaSuave.withValues(alpha: 0.8),
                            fontSize: 12,
                          ),
                        ),
                      ),
                    ),
            ),
            onChanged: (t) {
              if (t.isEmpty && _resultados.isNotEmpty)
                setState(() => _resultados = []);
            },
            // 🔑 Enter NO le quita el foco al buscador (por defecto sí): el lector de barras manda Enter tras cada código.
            onEditingComplete: () {},
            onSubmitted: _alEnter,
          ),
        ),
        const SizedBox(height: 14),
        Expanded(
          child: Card(
            clipBehavior: Clip.antiAlias,
            child: _resultados.isNotEmpty ? _listaResultados() : _tablaLineas(),
          ),
        ),
        if (MediaQuery.sizeOf(context).width >= 980) const SizedBox(height: 10),
        if (MediaQuery.sizeOf(context).width >= 980)
          const Wrap(
            spacing: 16,
            runSpacing: 4,
            children: [
              _Atajo('F2', 'Buscar artículo'),
              _Atajo('F3', 'Cliente'),
              _Atajo('F4  ·  *', 'Cobrar'),
              _Atajo('F5', 'Descuento'),
              _Atajo('F6', 'Consulta'),
              _Atajo('F9', 'Cajón'),
              _Atajo('Ctrl+Enter', 'Editar línea'),
              _Atajo('Supr', 'Quitar'),
              _Atajo('↑ ↓', 'Elegir línea'),
            ],
          ),
      ],
    );
  }

  Widget _listaResultados() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Container(
        color: Marca.azulClaro,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        child: Text(
          '${_resultados.length}${_resultados.length >= 80 ? '+' : ''} artículos — toque uno (Esc para cerrar)',
          style: const TextStyle(
            fontWeight: FontWeight.w600,
            color: Marca.azul,
          ),
        ),
      ),
      Expanded(
        child: ListView.separated(
          itemCount: _resultados.length,
          separatorBuilder: (_, __) => const Divider(),
          itemBuilder: (_, i) {
            final a = _resultados[i];
            final p = widget.datos
                .precios('${a['codigo']}')
                .where((x) => ((x['precio'] as num?) ?? 0) > 0)
                .firstOrNull;
            return ListTile(
              title: Text(
                '${a['nombre']}',
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              subtitle: Text(
                '${a['codigo']}${'${a['barra'] ?? ''}'.isEmpty ? '' : '  ·  ${a['barra']}'}',
              ),
              trailing: p == null
                  ? null
                  : Text(
                      '₡${fmt((p['precio'] as num))}',
                      style: const TextStyle(
                        fontWeight: FontWeight.w600,
                        color: Marca.tintaSuave,
                      ),
                    ),
              onTap: () => _agregar(a),
            );
          },
        ),
      ),
    ],
  );

  Widget _tablaLineas() {
    if (doc.lineas.isEmpty) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(22),
              decoration: const BoxDecoration(
                color: Marca.azulClaro,
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.shopping_basket_outlined,
                size: 44,
                color: Marca.azul,
              ),
            ),
            const SizedBox(height: 16),
            const Text(
              'Lista para vender',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            const Text(
              'Escanee el primer artículo',
              style: TextStyle(color: Marca.tintaSuave),
            ),
          ],
        ),
      );
    }
    if (MediaQuery.sizeOf(context).width < 700) {
      return ListView.separated(
        controller: _scroll,
        itemCount: doc.lineas.length,
        separatorBuilder: (_, __) => const Divider(),
        itemBuilder: (_, i) {
          final l = doc.lineas[i];
          return ListTile(
            onTap: () => _editar(i),
            leading: Container(
              width: 44,
              alignment: Alignment.center,
              padding: const EdgeInsets.symmetric(vertical: 6),
              decoration: BoxDecoration(
                color: Marca.fondo,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                fmt(l.cantidad, l.fraccionable != 0 ? 3 : 0),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
            title: Text(
              l.nombre,
              style: const TextStyle(fontWeight: FontWeight.w600),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            subtitle: Text(
              '₡${fmt(l.precio)}${l.descuento > 0 ? ' · −${fmt(l.descuento, 1)} %' : ''}',
            ),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  '₡${fmt(l.total)}',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(
                    Icons.delete_outline,
                    size: 20,
                    color: Marca.tintaSuave,
                  ),
                  onPressed: () => _quitar(i),
                ),
              ],
            ),
          );
        },
      );
    }
    const estiloCab = TextStyle(
      fontSize: 12,
      fontWeight: FontWeight.w600,
      color: Marca.tintaSuave,
      letterSpacing: 0.4,
    );
    return Column(
      children: [
        Container(
          color: const Color(0xFFF8FAFC),
          padding: const EdgeInsets.fromLTRB(6, 4, 18, 4),
          child: Row(
            children: [
              SizedBox(
                width: 40,
                child: Checkbox(
                  tristate: true,
                  value: _marcadas.isEmpty
                      ? false
                      : (_marcadas.length == doc.lineas.length ? true : null),
                  onChanged: (_) => setState(
                    () => _marcadas.length == doc.lineas.length
                        ? _marcadas.clear()
                        : _marcadas.addAll(
                            List.generate(doc.lineas.length, (i) => i),
                          ),
                  ),
                ),
              ),
              const SizedBox(width: 84, child: Text('CANT.', style: estiloCab)),
              const Expanded(child: Text('DESCRIPCIÓN', style: estiloCab)),
              const SizedBox(
                width: 120,
                child: Text(
                  'PRECIO',
                  style: estiloCab,
                  textAlign: TextAlign.right,
                ),
              ),
              const SizedBox(
                width: 80,
                child: Text(
                  'DESC.',
                  style: estiloCab,
                  textAlign: TextAlign.right,
                ),
              ),
              const SizedBox(
                width: 130,
                child: Text(
                  'TOTAL',
                  style: estiloCab,
                  textAlign: TextAlign.right,
                ),
              ),
              const SizedBox(width: 80),
            ],
          ),
        ),
        const Divider(),
        if (_marcadas.isNotEmpty) _barraMarcadas(),
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            itemCount: doc.lineas.length,
            itemBuilder: (_, i) => _fila(i, doc.lineas[i]),
          ),
        ),
      ],
    );
  }

  Widget _fila(int i, Linea l) {
    final sel = i == _sel;
    return Material(
      color: sel
          ? Marca.azulClaro
          : (i.isOdd ? const Color(0xFFFAFBFD) : Colors.white),
      child: InkWell(
        onTap: () => setState(() => _sel = i),
        onDoubleTap: () => _editar(i),
        child: Container(
          decoration: BoxDecoration(
            border: Border(
              left: BorderSide(
                color: sel ? Marca.azulMedio : Colors.transparent,
                width: 3,
              ),
            ),
          ),
          padding: const EdgeInsets.fromLTRB(3, 10, 15, 10),
          child: Row(
            children: [
              SizedBox(
                width: 40,
                child: Checkbox(
                  value: _marcadas.contains(i),
                  onChanged: (v) => setState(
                    () => v == true ? _marcadas.add(i) : _marcadas.remove(i),
                  ),
                ),
              ),
              SizedBox(
                width: 84,
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 5,
                    ),
                    decoration: BoxDecoration(
                      color: Marca.fondo,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      fmt(l.cantidad, l.fraccionable != 0 ? 3 : 0),
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                ),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      l.nombre,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      [
                        l.codigo,
                        if (l.bonificacion) 'BONIFICACIÓN',
                        if (l.autorizaciones.isNotEmpty) 'autorizado',
                      ].join(' · '),
                      style: const TextStyle(
                        fontSize: 12,
                        color: Marca.tintaSuave,
                      ),
                    ),
                  ],
                ),
              ),
              SizedBox(
                width: 120,
                child: Text('₡${fmt(l.precio)}', textAlign: TextAlign.right),
              ),
              SizedBox(
                width: 80,
                child: Text(
                  l.descuento > 0 ? '${fmt(l.descuento, 1)} %' : '—',
                  textAlign: TextAlign.right,
                  style: TextStyle(
                    color: l.descuento > 0
                        ? Marca.verdeOscuro
                        : Marca.tintaSuave,
                    fontWeight: l.descuento > 0
                        ? FontWeight.w600
                        : FontWeight.w400,
                  ),
                ),
              ),
              SizedBox(
                width: 130,
                child: Text(
                  '₡${fmt(l.total)}',
                  textAlign: TextAlign.right,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 15,
                  ),
                ),
              ),
              SizedBox(
                width: 80,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      tooltip: 'Editar (Ctrl+Enter)',
                      icon: const Icon(
                        Icons.edit_outlined,
                        size: 20,
                        color: Marca.tintaSuave,
                      ),
                      onPressed: () => _editar(i),
                    ),
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      tooltip: 'Quitar (Supr)',
                      icon: const Icon(
                        Icons.delete_outline,
                        size: 20,
                        color: Marca.tintaSuave,
                      ),
                      onPressed: () => _quitar(i),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _tarjetaCliente() {
    final c = doc.cliente;
    final contado = '${c['codigo']}'.toUpperCase() == 'SN';
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: _cliente,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              CircleAvatar(
                backgroundColor: contado ? Marca.fondo : Marca.azulClaro,
                child: Icon(
                  contado ? Icons.person_outline : Icons.person,
                  color: Marca.azul,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${c['nombre'] ?? ''}',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      contado
                          ? 'Tiquete electrónico · F3 para elegir cliente'
                          : '${c['cedula'] ?? ''} · ${tipoDocumento(codigo: '${c['codigo']}', cedula: '${c['cedula'] ?? ''}', tipoCedula: '${c['tipo_cedula'] ?? ''}') == '01' ? 'Factura electrónica' : 'Tiquete'}',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Marca.tintaSuave,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, color: Marca.tintaSuave),
            ],
          ),
        ),
      ),
    );
  }

  Widget _panel() {
    final t = doc.totales;
    final medios = widget.datos.mediosPago();
    final vacia = doc.lineas.isEmpty;
    Widget renglon(String a, String b, {bool fuerte = false}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Text(
            a,
            style: TextStyle(color: fuerte ? Marca.tinta : Marca.tintaSuave),
          ),
          const Spacer(),
          Text(
            b,
            style: TextStyle(
              fontWeight: fuerte ? FontWeight.w700 : FontWeight.w500,
            ),
          ),
        ],
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _tarjetaCliente(),
        const SizedBox(height: 10),
        TextField(
          controller: _notas,
          maxLines: 1,
          decoration: const InputDecoration(
            hintText: 'Notas de la venta (opcional)',
            prefixIcon: Icon(Icons.sticky_note_2_outlined, size: 20),
            isDense: true,
          ),
          onChanged: (t) {
            doc.notas = t;
            widget.almacen.guardarTabla(
              widget.config.empresa,
              'documento',
              doc.aMapa(),
            );
          },
          onSubmitted: (_) => _foco(),
        ),
        const SizedBox(height: 14),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              children: [
                renglon(
                  'Artículos',
                  '${fmt(t.articulos, t.articulos == t.articulos.truncateToDouble() ? 0 : 3)} en ${t.lineas} líneas',
                ),
                renglon('Subtotal', '₡${fmt(t.subtotal)}'),
                if (t.descuento > 0)
                  renglon('Descuento', '−₡${fmt(t.descuento)}'),
                renglon('IVA', '₡${fmt(t.iva)}'),
                if (t.ivaDevuelto > 0)
                  renglon('IVA devuelto', '−₡${fmt(t.ivaDevuelto)}'),
              ],
            ),
          ),
        ),
        const SizedBox(height: 14),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              colors: [Marca.azul, Color(0xFF16408A)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              BoxShadow(
                color: Marca.azul.withValues(alpha: 0.25),
                blurRadius: 18,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'TOTAL A PAGAR',
                  style: TextStyle(
                    color: Colors.white70,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 1.4,
                  ),
                ),
              ),
              const SizedBox(height: 4),
              FittedBox(
                child: Text(
                  '₡${fmt(t.total)}',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 44,
                    fontWeight: FontWeight.w800,
                    letterSpacing: -1,
                  ),
                ),
              ),
            ],
          ),
        ),
        const Spacer(),
        for (final m in medios.take(4))
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _botonMedio(m, vacia),
          ),
        Row(
          children: [
            Tooltip(
              message: 'Abrir el cajón (F9)',
              child: OutlinedButton(
                onPressed: _cajon,
                style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 16)),
                child: const Icon(Icons.inbox_outlined, size: 20),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: vacia
                    ? null
                    : () =>
                          _cobrar(medios.isEmpty ? '01' : medios.first.codigo),
                icon: const Icon(Icons.call_split, size: 18),
                label: const Text('Pago mixto'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                style: OutlinedButton.styleFrom(foregroundColor: Marca.rojo),
                onPressed: vacia ? null : _anular,
                icon: const Icon(Icons.delete_sweep_outlined, size: 18),
                label: const Text('Anular'),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _botonMedio(MedioPago m, bool vacia) {
    final atajo = m.codigo == '01' ? 'F4' : '';
    return SizedBox(
      height: 58,
      child: FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: Marca.medio(m.codigo),
          disabledBackgroundColor: Marca.borde,
        ),
        onPressed: vacia ? null : () => _cobrar(m.codigo),
        child: Row(
          children: [
            Icon(Marca.iconoMedio(m.codigo)),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                m.descripcion,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            if (atajo.isNotEmpty)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  atajo,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// Celular / ventana angosta: total + cobrar abajo.
  Widget _panelCompacto() {
    final t = doc.totales;
    final vacia = doc.lineas.isEmpty;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          children: [
            Row(
              children: [
                TextButton.icon(
                  onPressed: _cliente,
                  icon: const Icon(Icons.person_outline),
                  label: Text(
                    '${doc.cliente['nombre']}',
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const Spacer(),
                Text(
                  '₡${fmt(t.total)}',
                  style: const TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: SizedBox(
                    height: 52,
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: Marca.verde,
                      ),
                      onPressed: vacia ? null : () => _cobrar('01'),
                      icon: const Icon(Icons.point_of_sale),
                      label: const Text('Cobrar'),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                IconButton.outlined(
                  onPressed: vacia ? null : _anular,
                  icon: const Icon(Icons.delete_sweep_outlined),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Atajo extends StatelessWidget {
  final String tecla, que;
  const _Atajo(this.tecla, this.que);
  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: Colors.white,
          border: Border.all(color: Marca.borde),
          borderRadius: BorderRadius.circular(5),
        ),
        child: Text(
          tecla,
          style: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w600,
            color: Marca.tinta,
          ),
        ),
      ),
      const SizedBox(width: 5),
      Text(que, style: const TextStyle(fontSize: 12, color: Marca.tintaSuave)),
    ],
  );
}
