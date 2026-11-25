/// MV-117 en la app (#3957) — la ENTRADA de la caja: el cajero elige su nombre y pone su clave (validada en el equipo,
/// también sin internet). Aquí sale el aviso de versión nueva: entre cajeros, nunca a media venta.
library;

import 'dart:io';

import 'package:flutter/material.dart';

import '../caja/cajeros.dart';
import '../datos/actualizacion.dart';
import '../datos/almacen.dart';
import '../ui/tema.dart';

class PantallaEntrada extends StatefulWidget {
  final ConfigCaja config;
  final Cajeros cajeros;
  final void Function(Cajero) alEntrar;
  final VoidCallback alConfigurar;
  const PantallaEntrada({
    super.key,
    required this.config,
    required this.cajeros,
    required this.alEntrar,
    required this.alConfigurar,
  });

  @override
  State<PantallaEntrada> createState() => _EstadoEntrada();
}

class _EstadoEntrada extends State<PantallaEntrada> {
  final _clave = TextEditingController();
  final _foco = FocusNode();
  String? _usuario;
  String _error = '';
  bool _ocupado = false;
  VersionNueva? _nueva;
  String _avanceAct = '';

  @override
  void initState() {
    super.initState();
    buscarVersionNueva().then((v) {
      if (mounted && v != null) setState(() => _nueva = v);
    });
  }

  Future<void> _actualizar() async {
    final v = _nueva!;
    setState(
      () => _avanceAct = Platform.isLinux
          ? 'Instalando la versión ${v.nueva}…'
          : 'Bajando la versión ${v.nueva}…',
    );
    try {
      await instalarVersion(
        v,
        avance: (b, t) {
          if (mounted && t > 0)
            setState(
              () => _avanceAct =
                  'Bajando la versión ${v.nueva}: ${(b * 100 / t).floor()} %',
            );
        },
      );
      // Android: el instalador del sistema quedó abierto; ahí se confirma.
      if (mounted && Platform.isAndroid) {
        setState(
          () => _avanceAct =
              'Confirme «Instalar» en la ventana de Android (la versión ${v.nueva}).',
        );
      }
    } catch (e) {
      if (mounted)
        setState(() => _avanceAct = '$e'.replaceFirst('Exception: ', ''));
    }
  }

  Future<void> _entrar() async {
    setState(() {
      _ocupado = true;
      _error = '';
    });
    await Future<void>.delayed(const Duration(milliseconds: 30));
    final r = widget.cajeros.validar(_usuario ?? '', _clave.text);
    if (!mounted) return;
    if (r != null) {
      setState(() {
        _error = r;
        _ocupado = false;
      });
      _clave.selection = TextSelection(
        baseOffset: 0,
        extentOffset: _clave.text.length,
      );
      _foco.requestFocus();
      return;
    }
    widget.alEntrar(widget.cajeros.buscar(_usuario!)!);
  }

  @override
  Widget build(BuildContext context) {
    final lista = widget.cajeros.conPermiso();
    final cfg = widget.config;
    final empresa = cfg.empresaNombre.isEmpty ? cfg.empresa : cfg.empresaNombre;
    return Scaffold(
      body: FondoMarca(
        titulo: empresa,
        subtitulo: 'Elija su nombre y escriba su clave para abrir la caja. Funciona también sin internet: las ventas se guardan y salen solas cuando vuelve la conexión.',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_nueva != null) _avisoVersion(),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(28),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        const Expanded(
                          child: Text(
                            'Entrar a la caja',
                            style: TextStyle(
                              fontSize: 24,
                              fontWeight: FontWeight.w800,
                              letterSpacing: -0.4,
                            ),
                          ),
                        ),
                        IconButton(
                          tooltip: 'Configuración',
                          onPressed: widget.alConfigurar,
                          icon: const Icon(
                            Icons.settings_outlined,
                            color: Marca.tintaSuave,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      empresa,
                      style: const TextStyle(color: Marca.tintaSuave),
                    ),
                    const SizedBox(height: 24),
                    if (lista.isEmpty)
                      const Text(
                        'No hay usuarios con permiso para facturar (653) en la copia de esta caja. Revise los permisos en FactuPOS y vuelva a bajar los datos desde Configuración.',
                      )
                    else ...[
                      DropdownButtonFormField<String>(
                        initialValue: _usuario,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Su nombre',
                          prefixIcon: Icon(Icons.person_outline),
                        ),
                        items: [
                          for (final c in lista)
                            DropdownMenuItem(
                              value: c.usuario,
                              child: Text(c.nombre),
                            ),
                        ],
                        onChanged: (v) {
                          setState(() => _usuario = v);
                          _foco.requestFocus();
                        },
                      ),
                      const SizedBox(height: 14),
                      TextField(
                        controller: _clave,
                        focusNode: _foco,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Clave',
                          prefixIcon: Icon(Icons.lock_outline),
                        ),
                        onSubmitted: (_) => _ocupado ? null : _entrar(),
                      ),
                      const SizedBox(height: 22),
                      SizedBox(
                        height: 54,
                        child: FilledButton.icon(
                          style: FilledButton.styleFrom(
                            backgroundColor: Marca.verde,
                          ),
                          onPressed: _ocupado ? null : _entrar,
                          icon: _ocupado
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.white,
                                  ),
                                )
                              : const Icon(Icons.login),
                          label: Text(_ocupado ? 'Validando…' : 'Entrar'),
                        ),
                      ),
                    ],
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
          ],
        ),
      ),
    );
  }

  Widget _avisoVersion() => Container(
    margin: const EdgeInsets.only(bottom: 16),
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: Marca.azulClaro,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFC7D7F5)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(Icons.system_update_alt, color: Marca.azul),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                'Versión nueva ${_nueva!.nueva}',
                style: const TextStyle(
                  fontWeight: FontWeight.w700,
                  color: Marca.azul,
                ),
              ),
            ),
            Text(
              'tiene la ${_nueva!.actual}',
              style: const TextStyle(fontSize: 12, color: Marca.tintaSuave),
            ),
          ],
        ),
        const SizedBox(height: 6),
        const Text(
          'Tarda un par de minutos y la caja se vuelve a abrir sola. Hágalo cuando no haya clientes en fila.',
          style: TextStyle(fontSize: 13),
        ),
        const SizedBox(height: 12),
        if (_avanceAct.isNotEmpty)
          Text(_avanceAct, style: const TextStyle(fontWeight: FontWeight.w600))
        else
          Row(
            children: [
              FilledButton(
                onPressed: _actualizar,
                child: const Text('Actualizar ahora'),
              ),
              const SizedBox(width: 8),
              TextButton(
                onPressed: () => setState(() => _nueva = null),
                child: const Text('Más tarde'),
              ),
            ],
          ),
      ],
    ),
  );
}
