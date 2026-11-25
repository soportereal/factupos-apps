/// FactuSuper — caja nativa de FactuPOS (Windows · Linux · Android), caso #3957.
/// Consume las mismas APIs que FactuSuper web (apis/shared/venta/factusuper/): la app es solo la pantalla;
/// precios, impuestos, Hacienda e inventario siguen en el servidor.
///
/// Flujo (dueño, 25-nov-2026): Configuración = SOLO la llave de la empresa → la ENTRADA: el cajero elige su nombre de
/// la lista y pone su clave → la caja.
library;

import 'package:flutter/material.dart';

import 'caja/cajeros.dart';
import 'caja/cola.dart';
import 'caja/datos_caja.dart';
import 'datos/conexion.dart';
import 'datos/descarga.dart';
import 'datos/almacen.dart';
import 'pantallas/caja.dart';
import 'pantallas/configuracion.dart';
import 'pantallas/entrada.dart';

Future<void> main() async {
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
      await Descarga(con, widget.almacen, cfg.empresa).catalogos();
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
    if (mounted) setState(() => _cajeros = Cajeros(cat is Map<String, dynamic> ? cat : null));
  }

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
    if (cajeros == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (_abriendo) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    final cajero = _cajero;
    if (cajero == null) {
      return PantallaEntrada(
        config: cfg,
        cajeros: cajeros,
        alEntrar: _entrar,
        alConfigurar: () => setState(() => _configurando = true),
      );
    }
    return PantallaCaja(
      key: ValueKey(cajero.usuario),
      config: cfg,
      datos: _datos!,
      cola: _cola!,
      cajero: cajero,
      alSalir: () => setState(() => _cajero = null),
    );
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'FactuSuper',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(colorSchemeSeed: const Color(0xFF1E3A8A), useMaterial3: true),
        darkTheme: ThemeData(colorSchemeSeed: const Color(0xFF1E3A8A), brightness: Brightness.dark, useMaterial3: true),
        home: _inicio(),
      );
}
