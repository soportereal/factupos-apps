/// La CAJA (#3957) — dueño: «un diseño muy elegante, muy atractivo, profesional».
/// Izquierda: buscador + líneas. Derecha: cliente, totales y cobro por medio de pago. Atajos de teclado para la fila.
/// La venta se guarda en el equipo y sale sola al servidor (mismo transaccionId); la venta EN CURSO también se guarda
/// en cada cambio (si se va la luz, al abrir sigue ahí).
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app/sabor.dart';
import '../caja/cajeros.dart';
import '../caja/cajon.dart';
import '../caja/cierre.dart';
import '../caja/clientes.dart';
import '../caja/cola.dart';
import '../caja/cola_procesos.dart';
import '../impresion/sin_internet.dart';
import '../caja/datos_caja.dart';
import '../caja/documento.dart';
import '../caja/estacion_config.dart';
import '../caja/favoritos.dart';
import '../caja/fondo.dart';
import '../caja/proformas.dart';
import '../caja/registro.dart';
import '../datos/almacen.dart';
import '../datos/conexion.dart';
import '../datos/descarga.dart';
import '../motor/linea.dart';
import '../motor/redondeo.dart';
import '../ui/dialogos.dart';
import '../ui/dialogos_caja.dart';
import '../ui/tema.dart';
import '../ui/vista_lineas.dart';

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
  final _andamio = GlobalKey<ScaffoldState>();
  late final Registro _registro = Registro(
    widget.almacen,
    widget.config.empresa,
  );
  late final Proformas _proformas = Proformas(
    widget.almacen,
    widget.config.empresa,
    widget.datos,
  );

  /// Las ventas en espera de esta estación (la barra «En espera» de la web).
  List<Map<String, dynamic>> _espera = [];
  late final Favoritos _favoritos = Favoritos(
    widget.almacen,
    widget.config,
    widget.datos,
  );
  late final ClientesLocal _clientes = ClientesLocal(
    widget.almacen,
    widget.config,
    widget.datos,
    registro: _registro,
  );
  late final Fondos _fondos = Fondos(
    widget.config,
    widget.datos,
    registro: _registro,
  );
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
    if (p is! Map || !mounted) return;
    setState(() {
      if (p['modoLector'] == false) _modoLector = false;
      _vista = vistaValida(p['vista']);
      _letras = letrasDesde(p['letras']);
    });
  }

  /// Las preferencias de ESTE equipo (modo lector, vista de las líneas y su letra), todas juntas.
  void _guardarPreferencias() => widget.almacen.guardarTabla(
    widget.config.empresa,
    'preferencias',
    {'modoLector': _modoLector, 'vista': _vista, 'letras': _letras},
  );

  /// Vistas de las líneas (Básica · Simple · Detallada · Full) — se recuerda en el equipo, como la web.
  String _vista = 'simple';
  Map<String, double> _letras = {};

  void _ponerVista(String v) {
    setState(() => _vista = vistaValida(v));
    _guardarPreferencias();
    _foco();
  }

  void _cambiarLetra(int delta) {
    setState(() => _letras = cambiarLetra(_vista, _letras, delta));
    _guardarPreferencias();
  }

  void _ponerModoLector(bool v) {
    setState(() => _modoLector = v);
    _guardarPreferencias();
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
    widget.cola.registro = _registro;
    _restaurar().then((_) => _pintarEspera());
    _favoritos.refrescar(
      widget.cajero.usuario,
    ); // el ranking de hoy, en segundo plano
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
    _scrollLado.dispose();
    super.dispose();
  }

  /// Cada cambio: se pinta y la venta en curso queda en el disco.
  void _cambio([VoidCallback? f]) {
    setState(f ?? () {});
    _marcadas.removeWhere((i) => i >= doc.lineas.length);
    if (_notas.text != doc.notas) _notas.text = doc.notas;
    // #2629n: la venta retomada que se queda SIN líneas sale de la lista de espera.
    final origen = doc.proformaOrigen;
    if (origen != null && doc.lineas.isEmpty) {
      doc.proformaOrigen = null;
      _proformas.quitar(origen).then((_) => _pintarEspera());
      _aviso('La venta en espera se quedó sin artículos: salió de la lista.');
    }
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
    final clientesPend = await _clientes.pendientes();
    if (widget.cola.pendientes.isEmpty &&
        (await _cajonObj.pendientes()).isEmpty &&
        !clientesPend.any(
          (c) => c['estado'] != 'rechazado' || c['nuevo'] == true,
        ))
      return;
    setState(() => _enviando = true);
    // Etapa 17: primero los clientes (si no, la factura sale sin los datos editados), después el cajón y las ventas.
    final rc = await _clientes.subir();
    for (final e in rc.remapeos.entries) {
      await widget.cola.remapearCliente(e.key, e.value);
      if (doc.cliente['codigo'] == e.key) {
        _cambio(() => doc.cliente['codigo'] = e.value);
      }
    }
    for (final x in rc.rechazados) {
      _aviso('El servidor rechazó el cambio del cliente $x', error: true);
    }
    final ResumenEnvio r;
    if (rc.detenida.isNotEmpty) {
      r = ResumenEnvio()
        ..detenida = rc.sinRed
            ? 'Sin internet: las ventas quedan guardadas y salen solas cuando vuelva'
            : rc.detenida
        ..sinRed = rc.sinRed;
    } else {
      await _cajonObj.subirPendientes(widget.cajero.usuario);
      r = await widget.cola.enviar();
    }
    // Sin red: el comprobante PROVISIONAL directo a FactuPOS Print de esta computadora (una vez por venta, últimos 15 min).
    if (r.sinRed) {
      final impresas = await imprimirPendientesSinRed(
        widget.cola.pendientes,
        widget.datos,
        widget.config.empresa,
      );
      if (impresas.isNotEmpty) {
        await widget.cola.guardar();
        for (final (id, ok, error) in impresas) {
          _aviso(
            ok
                ? 'Sin internet: comprobante PROVISIONAL $id impreso'
                : 'Sin internet: no se pudo imprimir el provisional $id — $error',
            error: !ok,
          );
        }
      }
    }
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

  /// CF-006 · Configuración de la estación del cajero. Al guardar baja los catálogos (la estación nueva: impresoras,
  /// caja, bodega, tipo de precio) y repinta, como `datosNuevos()` de la web.
  Future<void> _configEstacion() async {
    _cerrarOpciones();
    final cfg = await dialogoEstacion(
      context,
      EstacionConfig(widget.config, widget.cajero.usuario),
    );
    if (cfg == null || !mounted) return _foco();
    final con = Conexion(
      llave: widget.config.llave,
      cajero: widget.cajero.usuario,
    );
    try {
      await Descarga(con, widget.almacen, widget.config.empresa).catalogos();
      await widget.datos.recargar(
        widget.almacen,
        widget.config.empresa,
        grupos: const ['catalogos'],
      );
      doc.lineas.forEach(doc.agregarRecalculo);
      _cambio();
      _aviso('Configuración de la estación guardada');
    } on ErrorConexion catch (e) {
      _aviso(
        'Se guardó, pero no se pudo bajar la estación nueva: ${e.mensaje} (salga y vuelva a entrar)',
        error: true,
      );
    } finally {
      con.cerrar();
    }
    _foco();
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
    final antes = doc.lineas[i].nivel;
    // FactuMóvil cambia la lista de precio AL INSTANTE dentro del diálogo: aunque se cancele, la línea ya cambió.
    if (await dialogoLinea(context, doc, widget.cajeros, i) ||
        (i < doc.lineas.length && doc.lineas[i].nivel != antes)) {
      _cambio();
    }
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
    final deProforma = doc.proformaOrigen;
    doc.proformaOrigen = null;
    _cambio(() {
      doc.nuevo();
      _sel = -1;
    });
    if (deProforma != null) {
      await _proformas.quitar(deProforma);
      await _pintarEspera();
    }
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

  // ═══════════ OPCIONES (el panel lateral de la web) ═══════════
  void _cerrarOpciones() => _andamio.currentState?.closeEndDrawer();

  Future<void> _fondo(String tipo) async {
    _cerrarOpciones();
    final r = await dialogoFondo(
      context,
      tipo,
      (monto, detalle) =>
          _fondos.registrar(tipo, monto, detalle, widget.cajero.usuario),
    );
    if (r != null) {
      _aviso(
        '${tipo == 'FCA' ? 'Ingreso' : 'Retiro'} de fondo registrado: $tipo #${r.documento} · ₡${fmt(r.monto)}'
        '${r.errorImpresion.isNotEmpty ? ' — no se imprimió: ${r.errorImpresion}' : ''}',
        error: r.errorImpresion.isNotEmpty,
      );
    }
    _foco();
  }

  // ── Proformas / ventas en espera (MV-114) ──
  Future<void> _pintarEspera() async {
    final l = await _proformas.lista();
    l.sort((a, b) => '${a['fecha']}'.compareTo('${b['fecha']}'));
    if (mounted) setState(() => _espera = l);
  }

  /// → true si quedó guardada (o no había nada que guardar).
  Future<bool> _guardarProforma({bool cotizacion = false}) async {
    if (doc.lineas.isEmpty) {
      _aviso('La venta no tiene artículos.', error: true);
      return false;
    }
    if (!doc.tienePermiso('104')) {
      _aviso('Sin permiso para guardar proformas (104)', error: true);
      return false;
    }
    String? etiqueta;
    if (await _proformas.pideEtiqueta(doc)) {
      if (!mounted) return false;
      etiqueta = await pedirTexto(
        context,
        cotizacion ? 'Guardar cotización' : 'Guardar en espera',
        'Nombre o seña del cliente (para encontrarlo en la lista de espera):',
        'Ej.: señora blusa roja',
      );
      if (etiqueta == null) return false;
    }
    Map<String, dynamic>? pq;
    if (cotizacion) {
      try {
        pq = doc.paquete(
          pagos: const [],
          vuelto: 0,
          imprimir: false,
          transaccionId: uuidV4(),
          cuando: DateTime.now(),
        );
      } catch (e) {
        _aviso('No se pudo armar la cotización: $e', error: true);
        return false;
      }
    }
    final r = await _proformas.guardar(
      doc,
      etiqueta: etiqueta,
      cotizacion: cotizacion,
    );
    if (!r.ok) {
      _aviso(r.motivo, error: true);
      return false;
    }
    _cambio(() => _sel = -1);
    await _pintarEspera();
    if (pq != null) {
      final e = await _proformas.imprimirCotizacion(pq, r.id);
      _aviso(
        'Cotización ${r.id} guardada en el equipo${e.isEmpty ? ' e impresa' : ' — no se imprimió: $e'}',
        error: e.isNotEmpty,
      );
    } else {
      _aviso(
        'Venta guardada en espera (${r.id}${r.actualizada ? ', actualizada' : ''}) — puede atender al siguiente cliente',
      );
    }
    _foco();
    return true;
  }

  Future<void> _retomar(String id) async {
    if (doc.proformaOrigen == id) return;
    // La venta a medias se guarda sola (se pasa de un cliente a otro sin perder nada).
    if (doc.lineas.isNotEmpty && !await _guardarProforma()) return;
    final p = await _proformas.abrir(id, doc);
    if (p == null) {
      _aviso('Esa proforma ya no está en el equipo.', error: true);
      return;
    }
    _cambio(() => _sel = -1);
    await _pintarEspera();
    _aviso('Retomada: ${Proformas.nombreDe(p)}');
    _foco();
  }

  Future<void> _verProformas() async {
    _cerrarOpciones();
    await _pintarEspera();
    if (!mounted) return;
    final accion = await dialogoProformas(
      context,
      _espera,
      puedeBorrar: doc.tienePermiso('060'),
      actual: doc.proformaOrigen,
    );
    if (accion == null) return _foco();
    if (accion.$1 == 'abrir') return _retomar(accion.$2);
    if (accion.$1 == 'borrar' && mounted) {
      if (await confirmar(
        context,
        'Eliminar proforma',
        '¿Eliminar la proforma ${accion.$2} de este equipo?',
        'Eliminar',
      )) {
        await _proformas.quitar(accion.$2);
        if (doc.proformaOrigen == accion.$2) doc.proformaOrigen = null;
        await _pintarEspera();
        _aviso('Proforma ${accion.$2} eliminada');
      }
      return _verProformas();
    }
  }

  /// Selector de vista + A− / A+ (la letra es POR VISTA; tocar el número vuelve a la de fábrica).
  Widget _controlVista() {
    final f = letraDe(_vista, _letras);
    final elegida = _letras.containsKey(_vista);
    Widget b(
      String t,
      String ayuda,
      VoidCallback? fn, {
      bool marcado = false,
    }) => Tooltip(
      message: ayuda,
      child: InkWell(
        onTap: fn,
        child: Container(
          constraints: const BoxConstraints(minWidth: 32),
          height: 32,
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(horizontal: 6),
          child: Text(
            t,
            style: TextStyle(
              fontWeight: FontWeight.w800,
              fontSize: 13,
              color: fn == null
                  ? Marca.tintaSuave.withValues(alpha: 0.4)
                  : (marcado ? Marca.azul : Marca.tinta),
            ),
          ),
        ),
      ),
    );
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Tooltip(
            message: 'Cómo se ven las líneas (se recuerda en este equipo)',
            child: DropdownButton<String>(
              value: _vista,
              underline: const SizedBox.shrink(),
              isDense: true,
              icon: const Icon(Icons.view_list_outlined, size: 18),
              style: Theme.of(context).textTheme.bodyMedium!.copyWith(
                fontSize: 13,
                color: Marca.azul,
                fontWeight: FontWeight.w600,
              ),
              items: [
                for (final v in vistasLineas)
                  DropdownMenuItem(
                    value: v,
                    child: Text('Vista ${nombresVista[v]!.toLowerCase()}  '),
                  ),
              ],
              onChanged: (v) => v == null ? null : _ponerVista(v),
            ),
          ),
          const SizedBox(width: 8),
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: Marca.borde),
              borderRadius: BorderRadius.circular(8),
              color: Colors.white,
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                b(
                  'A−',
                  'Letra más chica',
                  f <= letraMin ? null : () => _cambiarLetra(-1),
                ),
                b(
                  fmt(f, 0),
                  elegida
                      ? 'Volver al tamaño original de esta vista'
                      : 'Tamaño de fábrica de esta vista',
                  elegida ? () => _cambiarLetra(0) : null,
                  marcado: elegida,
                ),
                b(
                  'A+',
                  'Letra más grande',
                  f >= letraMax ? null : () => _cambiarLetra(1),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _barraEspera() {
    if (_espera.isEmpty && doc.lineas.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Row(
        children: [
          const Icon(
            Icons.people_alt_outlined,
            size: 18,
            color: Marca.tintaSuave,
          ),
          const SizedBox(width: 8),
          const Text(
            'En espera',
            style: TextStyle(
              color: Marca.tintaSuave,
              fontWeight: FontWeight.w600,
              fontSize: 13,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  if (_espera.isEmpty)
                    const Text(
                      'Ninguna',
                      style: TextStyle(color: Marca.tintaSuave, fontSize: 13),
                    ),
                  for (final p in _espera)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: Tooltip(
                        message:
                            '${p['cotizacion'] == true ? 'Cotización ' : ''}${p['id']} · ${p['lineas']} líneas — tocar para retomarla',
                        child: ChoiceChip(
                          selected: doc.proformaOrigen == p['id'],
                          avatar: Icon(
                            p['cotizacion'] == true
                                ? Icons.description_outlined
                                : Icons.person_outline,
                            size: 16,
                          ),
                          label: Text(
                            '${Proformas.nombreDe(p)}  ₡${fmt((p['total'] as num?) ?? 0)}',
                          ),
                          onSelected: (_) => _retomar('${p['id']}'),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
          if (doc.lineas.isNotEmpty && MediaQuery.sizeOf(context).width >= 700)
            _controlVista(),
          if (doc.lineas.isNotEmpty)
            TextButton.icon(
              onPressed: () => _guardarProforma(),
              icon: const Icon(Icons.save_outlined, size: 18),
              label: const Text('Guardar y atender otro'),
            ),
        ],
      ),
    );
  }

  // ── MV-118 · Favoritos ──
  // Los clics van EN FILA: dos clics rápidos sobre un artículo nuevo no pueden crear dos líneas.
  Future<void> _filaFav = Future.value();
  Future<void> _verFavoritos() async {
    _cerrarOpciones();
    await panelFavoritos(
      context,
      favoritos: _favoritos,
      doc: doc,
      datos: widget.datos,
      aviso: _aviso,
      agregar: (art) => _filaFav = _filaFav.then((_) {
        final r = doc.agregar(art, '1', repetido: 'sumar');
        _cambio(() {
          if (r.ok) _sel = doc.lineas.indexOf(r.linea!);
        });
        if (!r.ok) return _aviso(r.motivo, error: true);
        _revisarCambiosAlAgregar();
        final pc = Documento.cabysProblema(r.linea!);
        if (pc.isNotEmpty) {
          _aviso(
            '«${art['nombre']}» $pc: así no se puede facturar (Hacienda la rechaza). Corrija el CABYS en la ficha del artículo.',
            error: true,
          );
        } else if (r.avisos.isNotEmpty) {
          _aviso(r.avisos.join(' · '), error: true);
        }
      }),
    );
    _foco();
  }

  // ── MV-106 · Exoneración: a las líneas MARCADAS; si no hay ninguna marcada, a todas (y se dice) ──
  Future<void> _exoneracion() async {
    _cerrarOpciones();
    if (doc.lineas.isEmpty)
      return _aviso('La venta no tiene artículos.', error: true);
    final cod = '${doc.cliente['codigo'] ?? ''}';
    if (cod.isEmpty || cod.toUpperCase() == 'SN') {
      return _aviso('Elija el cliente (F3) antes de exonerar.', error: true);
    }
    if (doc.exoneracionesCliente().isEmpty) {
      return _aviso(
        '${doc.cliente['nombre']} no tiene exoneraciones registradas.',
        error: true,
      );
    }
    final marcadas = _marcadas.where((i) => i < doc.lineas.length).toList()
      ..sort();
    final todas = marcadas.isEmpty;
    final indices = todas
        ? [for (var i = 0; i < doc.lineas.length; i++) i]
        : marcadas;
    final r = await dialogoExoneracion(
      context,
      doc: doc,
      indices: indices,
      todas: todas,
    );
    if (r == null) return _foco();
    if (r.$1 == 'aplicar') {
      late List<PlanExo> plan;
      _cambio(() => plan = doc.exoneracionAplicar(indices, r.$2));
      final ok = plan.where((x) => x.exo != null).length;
      _aviso(
        'Exoneración aplicada a $ok de ${plan.length} líneas${ok < plan.length ? ' (las demás no califican)' : ''}',
        error: ok == 0,
      );
    } else {
      var n = 0;
      _cambio(() => n = doc.exoneracionQuitar(indices));
      _aviso(
        n > 0
            ? 'Exoneración quitada de $n líneas'
            : 'Esas líneas no tenían exoneración',
      );
    }
    _foco();
  }

  // ── MV-107 · Ventas de esta caja y REIMPRIMIR (permiso 142 o clave de supervisor, como FactuDesk) ──
  Future<void> _verVentas() => dialogoVentas(
    context,
    widget.cola.ventas,
    _enviar,
    reimprimir: _reimprimir,
  );

  Future<void> _reimprimir(Map<String, dynamic> v) async {
    final fac = (v['factura'] as Map?) ?? const {};
    // Quién pide: el cajero si tiene el 142; si no, el supervisor que lo autoriza (el servidor revisa SU permiso).
    var quien = widget.cajero.usuario;
    if (!doc.tienePermiso('142')) {
      final a = await dialogoSupervisor(
        context,
        widget.cajeros,
        const Validacion(
          permiso: '142',
          motivo: 'Reimprimir una factura requiere el permiso 142.',
        ),
      );
      if (a is! Cajero) return _foco();
      quien = a.usuario;
    }
    final imp = ((v['paquete'] as Map?)?['impresion'] as Map?) ?? const {};
    final con = Conexion(llave: widget.config.llave, cajero: quien);
    try {
      final j = await con.post('venta_reimprimir.php', {
        'numero': '${fac['numero'] ?? ''}',
        'impresora': '${imp['impresora'] ?? ''}',
        'formato': '${imp['formato'] ?? ''}',
      });
      _aviso(
        j['ok'] == true
            ? 'Reimpresa la factura ${fac['numero']}'
            : 'No se pudo reimprimir: ${j['error'] ?? ''}',
        error: j['ok'] != true,
      );
    } on ErrorConexion catch (e) {
      _aviso(
        e.sinInternet
            ? 'Sin internet: la reimpresión necesita conexión'
            : 'No se pudo reimprimir: ${e.mensaje}',
        error: true,
      );
    } finally {
      con.cerrar();
    }
    _foco();
  }

  // ── MU-001 · Cierre de caja: contar siempre; contabilizar solo con la cola vacía ──
  Future<int> _colaParaCierre() async {
    await _enviar();
    final cli = (await _clientes.pendientes()).where(
      (c) => c['estado'] != 'rechazado' || c['nuevo'] == true,
    );
    return widget.cola.pendientes.length +
        (await _cajonObj.pendientes()).length +
        cli.length;
  }

  Future<void> _cierre() async {
    _cerrarOpciones();
    final r = await dialogoCierre(
      context,
      cierre: CierreCaja(widget.config, widget.cajero.usuario),
      nombreCajero: widget.cajero.nombre,
      tipoCambio: widget.datos.tipoCambio('USD'),
      colaPendiente: _colaParaCierre,
    );
    if (r != null) _aviso(r);
    _foco();
  }

  /// MV-113 · la cola en orden + lo enviado en 7 días (`pintarCola` de la web).
  Future<List<FilaCola>> _filasCola() async => armarCola(
    clientes: await _clientes.pendientes(),
    cajon: await _cajonObj.pendientes(),
    ventas: widget.cola.pendientes,
    registro: await _registro.lista(),
  );

  Future<void> _verRegistro() async {
    _cerrarOpciones();
    await dialogoCola(
      context,
      cargar: _filasCola,
      enviar: () async {
        await _enviar();
        return _ultimoEnvio;
      },
      verVentas: _verVentas,
    );
    _foco();
  }

  Widget _opciones() {
    Widget grupo(String t) => Padding(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 6),
      child: Text(
        t.toUpperCase(),
        style: const TextStyle(
          fontSize: 11.5,
          letterSpacing: 1.3,
          fontWeight: FontWeight.w700,
          color: Marca.tintaSuave,
        ),
      ),
    );
    Widget accion(
      IconData i,
      String t,
      VoidCallback? f, {
      String atajo = '',
      String ayuda = '',
    }) => Tooltip(
      message: ayuda,
      waitDuration: const Duration(milliseconds: 600),
      child: ListTile(
        dense: true,
        enabled: f != null,
        leading: Icon(i, color: f == null ? null : Marca.azul),
        title: Text(t, style: const TextStyle(fontSize: 14.5)),
        trailing: atajo.isEmpty
            ? null
            : Container(
                padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                decoration: BoxDecoration(
                  color: Marca.fondo,
                  borderRadius: BorderRadius.circular(5),
                  border: Border.all(color: Marca.borde),
                ),
                child: Text(
                  atajo,
                  style: const TextStyle(fontSize: 11, color: Marca.tintaSuave),
                ),
              ),
        onTap: f,
      ),
    );
    void y(FutureOr<void> Function() f) {
      _cerrarOpciones();
      f();
    }

    return Drawer(
      width: 340,
      child: SafeArea(
        child: ListView(
          padding: const EdgeInsets.only(bottom: 20),
          children: [
            Container(
              padding: const EdgeInsets.fromLTRB(20, 22, 20, 18),
              color: Marca.azul,
              child: const Row(
                children: [
                  Icon(Icons.apps_rounded, color: Colors.white),
                  SizedBox(width: 12),
                  Text(
                    'Opciones',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
            grupo('Documento'),
            accion(
              Icons.star_outline_rounded,
              'Favoritos',
              _verFavoritos,
              ayuda: 'Los más vendidos y los que usted agrega',
            ),
            accion(
              Icons.folder_open_outlined,
              'Abrir proforma',
              _verProformas,
              ayuda: 'Ventas guardadas en ESTE equipo',
            ),
            accion(
              Icons.save_outlined,
              'Guardar en espera',
              doc.lineas.isEmpty ? null : () => y(_guardarProforma),
              ayuda: 'Guardar esta venta en el equipo y atender a otro cliente',
            ),
            accion(
              Icons.print_outlined,
              'Reimprimir',
              () {
                _cerrarOpciones();
                _verVentas();
              },
              ayuda: 'Las ventas de esta caja: reimprimir una factura (permiso 142)',
            ),
            accion(
              Icons.search,
              'Consultar artículo',
              () => y(_consulta),
              atajo: 'F6',
            ),
            grupo('Precio'),
            accion(
              Icons.percent,
              'Descuento',
              doc.lineas.isEmpty ? null : () => y(_accionDescuento),
              atajo: 'F5',
            ),
            accion(
              Icons.description_outlined,
              'Cotización',
              doc.lineas.isEmpty
                  ? null
                  : () => y(() => _guardarProforma(cotizacion: true)),
              ayuda: 'Guardar como cotización en este equipo e imprimirla para el cliente',
            ),
            accion(
              Icons.verified_user_outlined,
              'Exoneración',
              doc.lineas.isEmpty ? null : _exoneracion,
              ayuda: 'Exonerar las líneas marcadas (igual que FactuDesk)',
            ),
            grupo('Caja'),
            accion(
              Icons.inbox_outlined,
              'Abrir cajón',
              () => y(_cajon),
              atajo: 'F9',
              ayuda: 'Permiso 141 o clave de supervisor — también sin internet',
            ),
            accion(
              Icons.calculate_outlined,
              'Cierre de caja',
              _cierre,
              ayuda: 'Contar la caja y contabilizar el cierre (MU-001). Contabilizar pide la cola vacía.',
            ),
            accion(
              Icons.move_to_inbox_outlined,
              'Ingreso de fondo',
              () => _fondo('FCA'),
              ayuda: 'Ingreso de fondo de caja (FCA) — en tiempo real, necesita internet',
            ),
            accion(
              Icons.outbox_outlined,
              'Retiro de fondo',
              () => _fondo('SCA'),
              ayuda: 'Retiro de fondo de caja (SCA) — en tiempo real, necesita internet',
            ),
            grupo('Envíos'),
            accion(Icons.receipt_long_outlined, 'Ventas de esta caja', () {
              _cerrarOpciones();
              _verVentas();
            }),
            accion(
              Icons.history,
              'Cola de procesos',
              _verRegistro,
              ayuda: 'Todo lo que esta caja todavía no envió al servidor (facturas, clientes, cajón), en orden, y lo enviado en la semana',
            ),
          ],
        ),
      ),
    );
  }

  Map<ShortcutActivator, VoidCallback> get _atajos => {
    // Las MISMAS teclas de FactuSuper web (y FactuDesk): F2 artículo · F3 cliente · F4 cobrar · * cobrar.
    const SingleActivator(LogicalKeyboardKey.f2): _abrirBusqueda,
    const SingleActivator(LogicalKeyboardKey.f3): _cliente,
    const SingleActivator(LogicalKeyboardKey.f4): () => _cobrar('01'),
    const SingleActivator(LogicalKeyboardKey.f5): _accionDescuento,
    const SingleActivator(LogicalKeyboardKey.f6): _consulta,
    const SingleActivator(LogicalKeyboardKey.f9): _cajon,
    const SingleActivator(LogicalKeyboardKey.f10): () =>
        _andamio.currentState?.openEndDrawer(),
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
        key: _andamio,
        endDrawer: _opciones(),
        onEndDrawerChanged: (abierto) {
          if (!abierto) _foco();
        },
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
          message: sinRed
              ? _ultimoEnvio
              : 'Cola de procesos: lo que falta enviar, en orden',
          child: InkWell(
            borderRadius: BorderRadius.circular(20),
            onTap: _verRegistro,
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
        const SizedBox(width: 8),
        IconButton(
          tooltip: 'Favoritos: los más vendidos y los suyos',
          onPressed: _verFavoritos,
          icon: const Icon(Icons.star_rounded, color: Color(0xFFFCD34D)),
        ),
        IconButton(
          tooltip: 'Opciones (F10)',
          onPressed: () => _andamio.currentState?.openEndDrawer(),
          icon: const Icon(Icons.apps_rounded),
        ),
        const SizedBox(width: 4),
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
              case 'estacion':
                _configEstacion();
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
              value: 'estacion',
              child: ListTile(
                leading: Icon(Icons.settings_outlined),
                title: Text('Configuración de la estación'),
                subtitle: Text('Impresoras, caja, bodega y tipo de precio'),
              ),
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
        _barraEspera(),
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

  /// Chip chiquito de la línea en el celular (FactuMóvil: P# lista de precio · B# bodega).
  Widget _chipLinea(String t, Color c) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
    decoration: BoxDecoration(
      color: c.withValues(alpha: 0.10),
      borderRadius: BorderRadius.circular(6),
      border: Border.all(color: c.withValues(alpha: 0.35)),
    ),
    child: Text(
      t,
      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c),
    ),
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
            subtitle: sabor.esMovil
                ? Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(
                        '₡${fmt(precioConIva(l), doc.dec.total)}${l.descuento > 0 ? ' · −${fmt(l.descuento, 1)} %' : ''}',
                      ),
                      // Chips de la web (fm-chip-precio / fm-chip-bod): lista de precio y bodega de la línea.
                      _chipLinea('P${l.nivel}', Marca.azul),
                      _chipLinea(
                        'B${doc.bodegaDe(l)}',
                        l.bodega.isEmpty
                            ? Marca.tintaSuave
                            : const Color(0xFFB45309),
                      ),
                    ],
                  )
                : Text(
                    '₡${fmt(precioConIva(l), doc.dec.total)}${l.descuento > 0 ? ' · −${fmt(l.descuento, 1)} %' : ''}',
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
    final f = letraDe(_vista, _letras);
    final estiloCab = TextStyle(
      fontSize: (f * 0.78).clamp(11, 22).toDouble(),
      fontWeight: FontWeight.w600,
      color: Marca.tintaSuave,
      letterSpacing: 0.4,
    );
    final cols = _columnas(f);
    // La descripción no baja de ~14 letras de ancho (web: min-width 14em); si no cabe, la tabla se desliza de lado.
    final fijo =
        40 + f * 5.6 + cols.fold<double>(0, (a, c) => a + c.ancho) + 80 + 24;
    return LayoutBuilder(
      builder: (_, lim) {
        final minimo = fijo + f * 14;
        final tabla = _tablaAncha(f, estiloCab, cols);
        if (lim.maxWidth >= minimo) return tabla;
        return Scrollbar(
          controller: _scrollLado,
          thumbVisibility: true,
          child: SingleChildScrollView(
            controller: _scrollLado,
            scrollDirection: Axis.horizontal,
            child: SizedBox(width: minimo, child: tabla),
          ),
        );
      },
    );
  }

  final _scrollLado = ScrollController();

  Widget _tablaAncha(double f, TextStyle estiloCab, List<_Col> cols) {
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
              SizedBox(
                width: f * 5.6,
                child: Text('CANT.', style: estiloCab),
              ),
              Expanded(child: Text('DESCRIPCIÓN', style: estiloCab)),
              for (final c in cols)
                SizedBox(
                  width: c.ancho,
                  child: Tooltip(
                    message: c.ayuda,
                    child: Text(
                      c.titulo,
                      style: estiloCab,
                      textAlign: TextAlign.right,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
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
            itemBuilder: (_, i) => _fila(i, doc.lineas[i], f, cols),
          ),
        ),
      ],
    );
  }

  /// Las columnas de números de cada vista (después de CANT. y DESCRIPCIÓN), en el orden de la web.
  List<_Col> _columnas(double f) {
    final d = doc.dec;
    final ancho = f * 7.4;
    final precio = _Col(
      'PRECIO',
      'Precio con IVA',
      ancho,
      (l) => Text('₡${fmt(precioConIva(l), d.total)}'),
    );
    final desc = _Col(
      'DESC.',
      'Descuento en colones, con IVA (y su %)',
      f * 5.6,
      (l) => l.descuento > 0
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  fmt(descuentoConIva(l), d.subDesc),
                  style: const TextStyle(
                    color: Marca.rojo,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                Text(
                  '${fmt(l.descuento, d.descPct)} %',
                  style: TextStyle(fontSize: f * 0.7, color: Marca.tintaSuave),
                ),
              ],
            )
          : const Text('—', style: TextStyle(color: Marca.tintaSuave)),
    );
    final total = _Col(
      'TOTAL',
      'Total de la línea, con IVA',
      f * 8.4,
      (l) => Text(
        '₡${fmt(l.total, d.total)}',
        style: TextStyle(fontWeight: FontWeight.w700, fontSize: f + 1),
      ),
    );
    _Col det(String t, String a, Widget Function(Linea) c, [double? w]) =>
        _Col(t, a, w ?? f * 6.4, c, detalle: true);
    return switch (_vista) {
      'basica' => [precio],
      'simple' => [precio, desc, total],
      _ => [
        det('PV', 'Nivel de precio', (l) => Text('P${l.nivel}'), f * 3),
        det(
          'P. UNIT',
          'Precio por unidad, sin IVA',
          (l) => Text(fmt(l.precio, d.precio)),
        ),
        precio,
        desc,
        det(
          'SUBTOTAL',
          'Cantidad × precio, sin IVA ni descuento',
          (l) => Text(fmt(l.subtotal1, d.subDesc)),
        ),
        det(
          'NETO S/IVA',
          'Base después del descuento, sin IVA',
          (l) => Text(fmt(l.subtotal2, d.sub2)),
        ),
        det(
          '% IVA',
          '% de IVA (y lo exonerado)',
          (l) => Text(
            '${fmt(l.tarifa, 0)}%${l.ivaExonerado > 0 ? ' −${fmt(l.ivaExonerado, 0)}' : ''}',
          ),
          f * 4.4,
        ),
        det('IVA', 'Monto del IVA', (l) => Text(fmt(l.iva, d.iva))),
        det(
          'P. NETO',
          'Precio unitario con el descuento y con IVA (Total ÷ Cantidad)',
          (l) =>
              Text(l.cantidad != 0 ? fmt(l.total / l.cantidad, d.total) : ''),
        ),
        total,
      ],
    };
  }

  Widget _fila(int i, Linea l, double f, List<_Col> cols) {
    final sel = i == _sel;
    final full = _vista == 'full';
    final fondo = sel
        ? Marca.azulClaro
        : (i.isOdd ? const Color(0xFFFAFBFD) : Colors.white);
    final compacta = _vista == 'basica' || _vista == 'simple';
    return Material(
      color: fondo,
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
          padding: EdgeInsets.fromLTRB(
            3,
            compacta ? 5 : 8,
            15,
            compacta ? 5 : 8,
          ),
          child: DefaultTextStyle.merge(
            style: TextStyle(fontSize: f, color: Marca.tinta),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    SizedBox(
                      width: 40,
                      child: Checkbox(
                        value: _marcadas.contains(i),
                        onChanged: (v) => setState(
                          () => v == true
                              ? _marcadas.add(i)
                              : _marcadas.remove(i),
                        ),
                      ),
                    ),
                    SizedBox(
                      width: f * 5.6,
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: Container(
                          padding: EdgeInsets.symmetric(
                            horizontal: f * 0.6,
                            vertical: f * 0.25,
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
                              if (_vista != 'basica') l.codigo,
                              'IVA ${fmt(l.tarifa, 0)}%',
                              if (l.ivaExonerado > 0)
                                'EXO ${fmt(l.ivaExonerado, 0)}%',
                              if (l.bonificacion) 'BONIFICACIÓN',
                              if (l.autorizaciones.isNotEmpty) 'autorizado',
                            ].join(' · '),
                            style: TextStyle(
                              fontSize: (f * 0.62).clamp(10, 20).toDouble(),
                              color: Marca.tintaSuave,
                            ),
                          ),
                        ],
                      ),
                    ),
                    for (final c in cols)
                      SizedBox(
                        width: c.ancho,
                        child: Align(
                          alignment: Alignment.centerRight,
                          child: DefaultTextStyle.merge(
                            style: c.detalle
                                ? TextStyle(
                                    fontSize: f * 0.85,
                                    color: Marca.tintaSuave,
                                  )
                                : const TextStyle(),
                            maxLines: 1,
                            child: FittedBox(
                              fit: BoxFit.scaleDown,
                              alignment: Alignment.centerRight,
                              child: c.celda(l),
                            ),
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
                if (full) _filaFull(l, f),
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// Vista FULL: la segunda fila con todos los campos de la línea (`filaFull` de la web).
  Widget _filaFull(Linea l, double f) {
    final d = doc.dec;
    Widget c(String rot, String val, [String? ayuda]) {
      final w = Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: '${rot.toUpperCase()} ',
              style: TextStyle(
                fontSize: f * 0.62,
                color: Marca.tintaSuave,
                letterSpacing: 0.3,
              ),
            ),
            TextSpan(text: val),
          ],
        ),
        style: TextStyle(fontSize: f * 0.72),
      );
      return ayuda == null ? w : Tooltip(message: ayuda, child: w);
    }

    return Padding(
      padding: EdgeInsets.fromLTRB(44 + f * 5.6, 4, 0, 0),
      child: Wrap(
        spacing: 16,
        runSpacing: 4,
        children: [
          c(
            'Tipo precio',
            'P${l.nivel} · lista ${fmt(l.precioLista, d.precio)}',
          ),
          c('CABYS', l.cabys.isEmpty ? '—' : l.cabys),
          c(
            'Actividad',
            l.actividad.isEmpty ? '—' : l.actividad,
            'Actividad económica',
          ),
          c('Unidad', l.unidad),
          c('Naturaleza', naturalezas[l.naturaleza] ?? l.naturaleza),
          c(
            'Tarifa',
            '${l.codigoTarifa} · ${fmt(l.tarifa, 0)} %',
            'Código de tarifa de IVA de Hacienda y su porcentaje',
          ),
          c(
            'Descuento',
            '${fmt(l.descuento, d.descPct)} % · ${fmt(l.descuentoMonto, d.subDesc)}',
            'Porcentaje y monto sin IVA',
          ),
          c('Gravado', fmt(l.gravado, 2)),
          c('Exento', fmt(l.exento, 2)),
          c('Exonerado', fmt(l.exonerado, 2)),
          c(
            '% Exoneración',
            '${fmt(l.ivaExonerado, 0)} %',
            'Puntos de IVA exonerados en esta línea',
          ),
          c('IVA', fmt(l.iva, d.iva)),
          c('IVA exonerado', fmt(l.ivaExoneradoMonto, d.iva)),
          if (l.ivaDevuelto != 0) c('IVA devuelto', fmt(l.ivaDevuelto, d.iva)),
          if (l.exo != null) c('Documento exo.', l.exo!.documento),
          if (l.barra.isNotEmpty) c('Barra', l.barra),
        ],
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
              _botonCliente(
                Icons.edit_outlined,
                contado
                    ? 'Elija un cliente (F3) para editarlo'
                    : !doc.tienePermiso('313')
                    ? 'Sin permiso para editar clientes (313)'
                    : 'Editar los datos del cliente (se guarda sin conexión)',
                contado || !doc.tienePermiso('313') ? null : _clienteEditar,
              ),
              _botonCliente(
                Icons.person_add_alt_1_outlined,
                doc.tienePermiso('311')
                    ? 'Crear un cliente nuevo (también sin internet; el código lo da el servidor)'
                    : 'Sin permiso para crear clientes (311)',
                doc.tienePermiso('311') ? _clienteNuevo : null,
              ),
              const Icon(Icons.chevron_right, color: Marca.tintaSuave),
            ],
          ),
        ),
      ),
    );
  }

  /// Sin permiso el botón NO se oculta: queda gris con la razón.
  Widget _botonCliente(IconData i, String ayuda, VoidCallback? f) => Tooltip(
    message: ayuda,
    child: IconButton(
      visualDensity: VisualDensity.compact,
      icon: Icon(i, size: 20),
      color: Marca.azul,
      onPressed: f,
    ),
  );

  List<Map<String, dynamic>> get _monedas => [
    for (final m in (widget.datos.catalogos['monedas'] as List? ?? const []))
      if (m is Map) Map<String, dynamic>.from(m),
  ];

  Future<void> _clienteNuevo() async {
    if (!doc.tienePermiso('311')) {
      return _aviso('Sin permiso para crear clientes (311)', error: true);
    }
    final c = await dialogoClienteEditar(
      context,
      titulo: 'Nuevo cliente',
      nota: 'Cliente nuevo: la cédula es obligatoria y no puede existir ya. Se guarda en el equipo con un código provisional; el código real lo da el servidor al enviarlo.',
      esNuevo: true,
      conFactura: _clientes.conFactura,
      original: const {
        'tipo_cedula': '01',
        'tipo_precio': 1,
        'descuento': 0,
        'moneda': 'CRC',
        'plazo': 0,
        'monto_credito': 0,
      },
      monedas: _monedas,
      guardar: (v) => _clientes.crear(v, widget.cajero.usuario),
    );
    if (c != null) {
      _cambio(() => doc.asignarCliente(c));
      _aviso('Cliente ${c['codigo']} · ${c['nombre']} creado en el equipo');
      _enviar();
    }
    _foco();
  }

  Future<void> _clienteEditar() async {
    final cod = '${doc.cliente['codigo'] ?? ''}';
    final original = widget.datos.cliente(cod) ?? doc.cliente;
    final pend = (await _clientes.pendientes())
        .where((p) => p['codigo'] == cod)
        .firstOrNull;
    if (!mounted) return;
    final act = widget.datos.actividadCliente(cod);
    final c = await dialogoClienteEditar(
      context,
      titulo: '$cod · ${original['nombre'] ?? ''}',
      nota: pend == null
          ? 'Los cambios se guardan en este equipo y suben al servidor cuando haya conexión.'
          : pend['estado'] == 'rechazado'
          ? '⚠ El servidor rechazó el último cambio: ${pend['error']}'
          : pend['nuevo'] == true
          ? 'Cliente nuevo: todavía no se creó en el servidor (código provisional).'
          : 'Tiene cambios que todavía no subieron al servidor.',
      esNuevo: false,
      conFactura: _clientes.conFactura,
      original: {...original, if (act.isNotEmpty) 'actividad': act},
      monedas: _monedas,
      guardar: (v) => _clientes.editar(cod, v, widget.cajero.usuario),
    );
    if (c != null) {
      // Es el MISMO cliente: se actualizan sus datos sin quitar las exoneraciones de las líneas.
      _cambio(() => doc.cliente = Map.of(c));
      _aviso('Cliente $cod actualizado en el equipo');
      _enviar();
    }
    _foco();
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
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 16,
                  ),
                ),
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

/// Una columna de números de la tabla de líneas.
class _Col {
  final String titulo, ayuda;
  final double ancho;
  final Widget Function(Linea) celda;
  final bool detalle;
  const _Col(
    this.titulo,
    this.ayuda,
    this.ancho,
    this.celda, {
    this.detalle = false,
  });
}
