/// FactuSuper — caja nativa de FactuPOS (Windows · Linux · Android), caso #3957.
/// Consume las mismas APIs que FactuSuper web (apis/shared/venta/factusuper/): la app es solo la pantalla;
/// precios, impuestos, Hacienda e inventario siguen en el servidor.
library;

import 'package:flutter/material.dart';

import 'datos/almacen.dart';
import 'pantallas/configuracion.dart';

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

  @override
  void initState() {
    super.initState();
    _cfg = widget.config;
  }

  @override
  Widget build(BuildContext context) {
    final cfg = _cfg;
    return MaterialApp(
      title: 'FactuSuper',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: const Color(0xFF1E3A8A), useMaterial3: true),
      darkTheme: ThemeData(colorSchemeSeed: const Color(0xFF1E3A8A), brightness: Brightness.dark, useMaterial3: true),
      home: cfg == null || _configurando
          ? PantallaConfiguracion(
              almacen: widget.almacen,
              actual: cfg,
              alGuardar: (c) => setState(() {
                _cfg = c;
                _configurando = false;
              }),
            )
          : _CajaPendiente(config: cfg, alConfigurar: () => setState(() => _configurando = true)),
    );
  }
}

/// F1 en construcción: acá va la caja (entrada del cajero, buscar/escanear, líneas, cobro).
class _CajaPendiente extends StatelessWidget {
  final ConfigCaja config;
  final VoidCallback alConfigurar;
  const _CajaPendiente({required this.config, required this.alConfigurar});

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: Text('FactuSuper · ${config.empresaNombre.isEmpty ? config.empresa : config.empresaNombre}'),
          actions: [IconButton(icon: const Icon(Icons.settings), tooltip: 'Configuración', onPressed: alConfigurar)],
        ),
        body: const Center(child: Text('Datos bajados. La caja se está construyendo (#3957, fase 1).')),
      );
}
