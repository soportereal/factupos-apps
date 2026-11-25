/// Configuración de la caja (#3957) — dueño: «la aplicación tiene que tener una parte de la configuración
/// para poner el token» · «solo debería pedir la llave de la empresa, porque el usuario cuando entra a la
/// aplicación lo tiene que seleccionar desde la lista y autenticarse». Se pega SOLO la LLAVE (FactuPOS ›
/// Configuración › Tokens, CF-027); la app la revisa con el servidor, muestra a qué empresa conecta y, al
/// guardar, baja la copia de los datos (con la lista de usuarios para la entrada) para vender sin internet.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../datos/almacen.dart';
import '../datos/conexion.dart';
import '../datos/descarga.dart';

class PantallaConfiguracion extends StatefulWidget {
  final Almacen almacen;
  final ConfigCaja? actual;
  final void Function(ConfigCaja) alGuardar;
  const PantallaConfiguracion({super.key, required this.almacen, this.actual, required this.alGuardar});

  @override
  State<PantallaConfiguracion> createState() => _EstadoConfiguracion();
}

class _EstadoConfiguracion extends State<PantallaConfiguracion> {
  final _llave = TextEditingController();
  InfoLlave? _info;
  String _error = '';
  String _avance = '';
  bool _ocupado = false;

  Future<void> _pegar() async {
    final d = await Clipboard.getData(Clipboard.kTextPlain);
    if (d?.text != null) setState(() => _llave.text = d!.text!.trim());
  }

  Future<void> _revisar() async {
    setState(() {
      _ocupado = true;
      _error = '';
      _info = null;
    });
    try {
      final i = await revisarLlave(_llave.text);
      setState(() => _info = i);
    } on ErrorConexion catch (e) {
      setState(() => _error = e.mensaje);
    } finally {
      setState(() => _ocupado = false);
    }
  }

  Future<void> _guardar() async {
    final i = _info;
    if (i == null) return;
    setState(() {
      _ocupado = true;
      _error = '';
    });
    final cfg = ConfigCaja(
      llave: _llave.text.trim(),
      empresa: i.empresa,
      empresaNombre: i.empresaNombre,
      guardada: DateTime.now(),
    );
    final con = Conexion(llave: cfg.llave);
    try {
      final n = await Descarga(con, widget.almacen, cfg.empresa).todo(
        avance: (que, hechos, total) => setState(() => _avance = 'Bajando $que: $hechos${total > 0 ? ' de $total' : ''}'),
      );
      await widget.almacen.guardarConfig(cfg);
      setState(() => _avance = 'Listo: ${n['articulos']} artículos, ${n['precios']} precios, ${n['clientes']} clientes');
      widget.alGuardar(cfg);
    } on ErrorConexion catch (e) {
      setState(() => _error = e.mensaje);
    } finally {
      con.cerrar();
      if (mounted) setState(() => _ocupado = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final actual = widget.actual;
    return Scaffold(
      appBar: AppBar(title: const Text('FactuSuper · Configuración')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              if (actual != null)
                Card(
                  child: ListTile(
                    leading: const Icon(Icons.link),
                    title: Text('Conectada a: ${actual.empresaNombre.isEmpty ? actual.empresa : actual.empresaNombre}'),
                    subtitle: Text('Llave ${actual.llaveVisible}'),
                  ),
                ),
              Text('Llave de la empresa', style: t.titleMedium),
              const SizedBox(height: 4),
              Text('Se copia en FactuPOS › Configuración › Tokens (CF-027). Empieza con «fs1.».', style: t.bodySmall),
              const SizedBox(height: 8),
              TextField(
                controller: _llave,
                decoration: InputDecoration(
                  border: const OutlineInputBorder(),
                  hintText: 'fs1.…',
                  suffixIcon: IconButton(icon: const Icon(Icons.content_paste), tooltip: 'Pegar', onPressed: _pegar),
                ),
                onChanged: (_) => setState(() => _info = null),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _ocupado ? null : _revisar,
                icon: const Icon(Icons.verified_user),
                label: const Text('Revisar la llave'),
              ),
              if (_info != null) ...[
                const SizedBox(height: 16),
                Card(
                  color: Colors.green.shade50,
                  child: ListTile(
                    leading: const Icon(Icons.check_circle, color: Colors.green),
                    title: Text(_info!.empresaNombre.isEmpty ? _info!.empresa : _info!.empresaNombre),
                    subtitle: Text('Empresa ${_info!.empresa}'),
                  ),
                ),
                const SizedBox(height: 8),
                FilledButton.icon(
                  onPressed: _ocupado ? null : _guardar,
                  icon: const Icon(Icons.download),
                  label: const Text('Guardar y bajar los datos'),
                ),
              ],
              if (_ocupado) const Padding(padding: EdgeInsets.only(top: 16), child: LinearProgressIndicator()),
              if (_avance.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_avance)),
              if (_error.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(_error, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
