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
import '../ui/tema.dart';

class PantallaConfiguracion extends StatefulWidget {
  final Almacen almacen;
  final ConfigCaja? actual;
  final void Function(ConfigCaja) alGuardar;
  const PantallaConfiguracion({
    super.key,
    required this.almacen,
    this.actual,
    required this.alGuardar,
  });

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
        avance: (que, hechos, total) => setState(
          () =>
              _avance = 'Bajando $que: $hechos${total > 0 ? ' de $total' : ''}',
        ),
      );
      await widget.almacen.guardarConfig(cfg);
      setState(
        () => _avance =
            'Listo: ${n['articulos']} artículos, ${n['precios']} precios, ${n['clientes']} clientes',
      );
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
    final actual = widget.actual;
    return Scaffold(
      body: FondoMarca(
        titulo: 'Configurar esta caja',
        subtitulo: 'Pegue la llave de la empresa. El sistema sabe a qué empresa conecta y baja los artículos, precios y clientes para que la caja venda también sin internet.',
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        'Configuración',
                        style: TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.w800,
                          letterSpacing: -0.4,
                        ),
                      ),
                    ),
                    if (actual != null)
                      IconButton(
                        tooltip: 'Volver',
                        onPressed: () => widget.alGuardar(actual),
                        icon: const Icon(Icons.close, color: Marca.tintaSuave),
                      ),
                  ],
                ),
                if (actual != null) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Marca.fondo,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.link, color: Marca.azul, size: 20),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            'Conectada a ${actual.empresaNombre.isEmpty ? actual.empresa : actual.empresaNombre} · llave ${actual.llaveVisible}',
                            style: const TextStyle(fontSize: 13),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 22),
                TextField(
                  controller: _llave,
                  decoration: InputDecoration(
                    labelText: 'Llave de la empresa',
                    helperText: 'FactuPOS › Configuración › Tokens (CF-027). Empieza con «fs1.»',
                    helperMaxLines: 2,
                    prefixIcon: const Icon(Icons.key_outlined),
                    suffixIcon: IconButton(
                      icon: const Icon(Icons.content_paste),
                      tooltip: 'Pegar',
                      onPressed: _pegar,
                    ),
                  ),
                  onChanged: (_) => setState(() => _info = null),
                ),
                const SizedBox(height: 18),
                SizedBox(
                  height: 52,
                  child: FilledButton.icon(
                    onPressed: _ocupado ? null : _revisar,
                    icon: const Icon(Icons.verified_user_outlined),
                    label: const Text('Revisar la llave'),
                  ),
                ),
                if (_info != null) ...[
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFECFDF5),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: const Color(0xFFA7F3D0)),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.check_circle, color: Marca.verde),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _info!.empresaNombre.isEmpty
                                    ? _info!.empresa
                                    : _info!.empresaNombre,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              Text(
                                'Empresa ${_info!.empresa}',
                                style: const TextStyle(
                                  fontSize: 12,
                                  color: Marca.tintaSuave,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    height: 52,
                    child: FilledButton.icon(
                      style: FilledButton.styleFrom(
                        backgroundColor: Marca.verde,
                      ),
                      onPressed: _ocupado ? null : _guardar,
                      icon: const Icon(Icons.download_outlined),
                      label: const Text('Guardar y bajar los datos'),
                    ),
                  ),
                ],
                if (_ocupado)
                  const Padding(
                    padding: EdgeInsets.only(top: 18),
                    child: LinearProgressIndicator(
                      minHeight: 6,
                      borderRadius: BorderRadius.all(Radius.circular(3)),
                    ),
                  ),
                if (_avance.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Text(
                      _avance,
                      style: const TextStyle(color: Marca.tintaSuave),
                    ),
                  ),
                if (_error.isNotEmpty)
                  Container(
                    margin: const EdgeInsets.only(top: 16),
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFEF2F2),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.error_outline,
                          color: Marca.rojo,
                          size: 20,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _error,
                            style: const TextStyle(color: Marca.rojo),
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
