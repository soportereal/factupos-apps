/// MV-117 en la app (#3957) — la ENTRADA de la caja: el cajero elige su nombre de la lista y pone su clave.
/// Se valida en el equipo (sin internet también). La Configuración solo pidió la llave de la empresa.
library;

import 'package:flutter/material.dart';

import '../caja/cajeros.dart';
import '../datos/almacen.dart';

class PantallaEntrada extends StatefulWidget {
  final ConfigCaja config;
  final Cajeros cajeros;
  final void Function(Cajero) alEntrar;
  final VoidCallback alConfigurar;
  const PantallaEntrada({super.key, required this.config, required this.cajeros, required this.alEntrar, required this.alConfigurar});

  @override
  State<PantallaEntrada> createState() => _EstadoEntrada();
}

class _EstadoEntrada extends State<PantallaEntrada> {
  final _clave = TextEditingController();
  final _foco = FocusNode();
  String? _usuario;
  String _error = '';
  bool _ocupado = false;

  Future<void> _entrar() async {
    setState(() {
      _ocupado = true;
      _error = '';
    });
    // bcrypt tarda un momento: se deja pintar el «Validando…» antes.
    await Future<void>.delayed(const Duration(milliseconds: 30));
    final r = widget.cajeros.validar(_usuario ?? '', _clave.text);
    if (!mounted) return;
    if (r != null) {
      setState(() {
        _error = r;
        _ocupado = false;
      });
      _clave.selection = TextSelection(baseOffset: 0, extentOffset: _clave.text.length);
      _foco.requestFocus();
      return;
    }
    widget.alEntrar(widget.cajeros.buscar(_usuario!)!);
  }

  @override
  Widget build(BuildContext context) {
    final lista = widget.cajeros.conPermiso();
    final cfg = widget.config;
    return Scaffold(
      appBar: AppBar(
        title: Text('FactuSuper · ${cfg.empresaNombre.isEmpty ? cfg.empresa : cfg.empresaNombre}'),
        actions: [IconButton(icon: const Icon(Icons.settings), tooltip: 'Configuración', onPressed: widget.alConfigurar)],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.all(20),
            children: [
              Text('Entrar a la caja', style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 16),
              if (lista.isEmpty)
                const Text('No hay usuarios con permiso para facturar (653) en la copia de esta caja. '
                    'Revise los permisos en FactuPOS y vuelva a bajar los datos desde Configuración.')
              else ...[
                DropdownButtonFormField<String>(
                  initialValue: _usuario,
                  isExpanded: true,
                  decoration: const InputDecoration(border: OutlineInputBorder(), labelText: 'Su nombre'),
                  items: [for (final c in lista) DropdownMenuItem(value: c.usuario, child: Text(c.nombre))],
                  onChanged: (v) {
                    setState(() => _usuario = v);
                    _foco.requestFocus();
                  },
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _clave,
                  focusNode: _foco,
                  obscureText: true,
                  decoration: const InputDecoration(border: OutlineInputBorder(), labelText: 'Clave'),
                  onSubmitted: (_) => _ocupado ? null : _entrar(),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: _ocupado ? null : _entrar,
                  icon: const Icon(Icons.login),
                  label: Text(_ocupado ? 'Validando…' : 'Entrar'),
                ),
              ],
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
