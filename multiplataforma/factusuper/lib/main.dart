/// FactuSuper — caja nativa de FactuPOS (Windows · Linux · Android), caso #3957.
/// Consume las mismas APIs que FactuSuper web (apis/shared/venta/factusuper/): la app es solo la pantalla;
/// precios, impuestos, Hacienda e inventario siguen en el servidor.
///
/// Flujo (dueño, 25-nov-2026): Configuración = SOLO la llave de la empresa → la ENTRADA: el cajero elige su nombre de
/// la lista y pone su clave → la caja.
library;

import 'package:flutter/material.dart';

import 'app/sabor.dart';

import 'caja/cajeros.dart';
import 'caja/cola.dart';
import 'caja/datos_caja.dart';
import 'datos/conexion.dart';
import 'datos/descarga.dart';
import 'datos/almacen.dart';
import 'pantallas/caja.dart';
import 'pantallas/configuracion.dart';
import 'pantallas/entrada.dart';
import 'ui/tema.dart';

Future<void> main() => arrancar(saborFactuSuper);

/// El arranque de las dos apps (FactuMóvil entra por lib/main_factumovil.dart).
Future<void> arrancar(Sabor s) async {
  sabor = s;
  WidgetsFlutterBinding.ensureInitialized();
  final almacen = await Almacen.abrir();
  final cfg = await almacen.leerConfig();
  runApp(FactuSuperApp(almacen: almacen, config: cfg));
}

class FactuSuperApp extends StatefulWidget {
  final Almacen almacen;
  final ConfigCaja? config;
  const FactuSuperApp({super.key, required this.almacen, this.config});

  @override
  State<FactuSuperApp> createState() => _EstadoApp();
}

class _EstadoApp extends State<FactuSuperApp> {
  ConfigCaja? _cfg;
  bool _configurando = false;
  Cajeros? _cajeros;
  Cajero? _cajero;
  DatosCaja? _datos;
  Cola? _cola;
  bool _abriendo = false;

  /// El cajero entró: se refresca su estación (si hay internet), se cargan los datos y la cola de ventas.
  Future<void> _entrar(Cajero c) async {
    final cfg = _cfg!;
    setState(() => _abriendo = true);
    final con = Conexion(llave: cfg.llave, cajero: c.usuario);
    try {
      // «Cuando un usuario entra de nuevo debe sincronizar, pero inteligente» (web): solo lo que cambió. Las firmas de los
      // catálogos dependen del cajero → con otro cajero se baja SU estación (caja, bodega, impresora, nivel de precio).
      await Descarga(con, widget.almacen, cfg.empresa).sincronizarSiHaceFalta();
    } catch (_) {
      // sin internet: sigue con la copia que hay
    } finally {
      con.cerrar();
    }
    final datos = await DatosCaja.cargar(widget.almacen, cfg.empresa);
    final cola = Cola(widget.almacen, cfg.empresa, cfg.llave);
    await cola.cargar();
    if (!mounted) return;
    setState(() {
      _datos = datos;
      _cajeros = Cajeros(
        datos.catalogos,
      ); // la copia recién bajada (supervisores al día)
      _cola = cola;
      _cajero = c;
      _abriendo = false;
    });
  }

  @override
  void initState() {
    super.initState();
    _cfg = widget.config;
    _cargarCajeros();
  }

  Future<void> _cargarCajeros() async {
    final cfg = _cfg;
    if (cfg == null) return;
    final cat = await widget.almacen.leerTabla(cfg.empresa, 'catalogos');
    if (mounted)
      setState(
        () => _cajeros = Cajeros(cat is Map<String, dynamic> ? cat : null),
      );
  }

  /// «Actualizar datos» desde la caja: baja todo de nuevo con el cajero que está adentro y rearma los datos.
  Future<String> _actualizarDatos() async {
    final cfg = _cfg!, c = _cajero!;
    final con = Conexion(llave: cfg.llave, cajero: c.usuario);
    try {
      final n = await Descarga(con, widget.almacen, cfg.empresa).todo();
      final datos = await DatosCaja.cargar(widget.almacen, cfg.empresa);
      if (mounted) {
        setState(() {
          _datos = datos;
          _cajeros = Cajeros(datos.catalogos);
          _cajero = Cajero(
            c.usuario,
            c.nombre,
          ); // nueva clave de pantalla → la caja se rearma con los datos nuevos
          _version++;
        });
      }
      return 'Datos al día: ${n['articulos']} artículos, ${n['precios']} precios, ${n['clientes']} clientes';
    } on ErrorConexion catch (e) {
      return 'No se pudieron actualizar los datos: ${e.mensaje}';
    } finally {
      con.cerrar();
    }
  }

  int _version = 0;

  Widget _inicio() {
    final cfg = _cfg;
    if (cfg == null || _configurando) {
      return PantallaConfiguracion(
        almacen: widget.almacen,
        actual: cfg,
        alGuardar: (c) {
          setState(() {
            _cfg = c;
            _configurando = false;
            _cajero = null;
            _cajeros = null;
          });
          _cargarCajeros();
        },
      );
    }
    final cajeros = _cajeros;
    if (cajeros == null)
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (_abriendo)
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final cajero = _cajero;
    if (cajero == null) {
      return PantallaEntrada(
        almacen: widget.almacen,
        config: cfg,
        cajeros: cajeros,
        alEntrar: _entrar,
        alConfigurar: () => setState(() => _configurando = true),
      );
    }
    return PantallaCaja(
      key: ValueKey('${cajero.usuario}#$_version'),
      config: cfg,
      almacen: widget.almacen,
      cajeros: _cajeros!,
      datos: _datos!,
      cola: _cola!,
      cajero: cajero,
      alSalir: () => setState(() => _cajero = null),
      alActualizar: _actualizarDatos,
    );
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: sabor.nombre,
    debugShowCheckedModeBanner: false,
    theme: temaFactuSuper(),
    home: _inicio(),
  );
}
