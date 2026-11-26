/// FactuPOS Apps de ANDROID (#3957, dueño 25-nov-2026): la gemela de la de Windows y la de Linux — mismo nombre, mismo
/// ícono. Lista las apps de FactuPOS para Android y permite instalar, actualizar, abrir y desinstalar cada una.
/// Android siempre pide confirmar cada instalación: la app baja el APK y abre el instalador del sistema.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';

import 'catalogo.dart';

const _canal = MethodChannel('factupos_apps/android');

class Marca {
  static const navy = Color(0xFF16305F);
  static const navyOscuro = Color(0xFF0F2447);
  static const celeste = Color(0xFF38BDF8);
  static const verde = Color(0xFF16A34A);
  static const fondo = Color(0xFFF3F5F9);
  static const tintaSuave = Color(0xFF64748B);
}

void main() => runApp(const AppFactuPOS());

class AppFactuPOS extends StatelessWidget {
  const AppFactuPOS({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'FactuPOS Apps',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      colorScheme: ColorScheme.fromSeed(seedColor: Marca.navy, primary: Marca.navy),
      scaffoldBackgroundColor: Marca.fondo,
      useMaterial3: true,
    ),
    home: const PantallaApps(),
  );
}

class PantallaApps extends StatefulWidget {
  const PantallaApps({super.key});
  @override
  State<PantallaApps> createState() => _EstadoApps();
}

class _EstadoApps extends State<PantallaApps> with WidgetsBindingObserver {
  List<AppCat>? _apps;
  Map<String, Instalada> _inst = {};
  String _error = '';
  bool _es32 = false;
  final Map<String, String> _avance = {}; // id → «Bajando 40 %» mientras baja
  bool get _ocupado => _avance.isNotEmpty;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _cargar();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  /// Al volver del instalador (o de los ajustes) se vuelve a mirar qué quedó instalado.
  @override
  void didChangeAppLifecycleState(AppLifecycleState s) {
    if (s == AppLifecycleState.resumed && _apps != null) _leerInstaladas();
  }

  Future<void> _cargar() async {
    setState(() => _error = '');
    try {
      _es32 = await _canal.invokeMethod<bool>('es32') ?? false;
    } catch (_) {}
    try {
      final r = await http
          .get(Uri.parse(urlCatalogo), headers: {'User-Agent': agente})
          .timeout(const Duration(seconds: 20));
      if (r.statusCode != 200) throw 'El servidor respondió ${r.statusCode}';
      final apps = leerCatalogo(r.body);
      if (!mounted) return;
      setState(() => _apps = apps);
      await _leerInstaladas();
    } catch (e) {
      if (!mounted) return;
      setState(
        () => _error = e is SocketException || e is TimeoutException
            ? 'Sin internet: no se pudo traer la lista de aplicaciones. Revise la conexión y vuelva a intentar.'
            : 'No se pudo traer la lista de aplicaciones ($e).',
      );
    }
  }

  Future<void> _leerInstaladas() async {
    final apps = _apps ?? const [];
    try {
      final r = await _canal.invokeMapMethod<String, dynamic>('instalados', {
        'paquetes': [for (final a in apps) a.paquete],
      });
      if (!mounted) return;
      setState(
        () => _inst = {
          for (final e in (r ?? const {}).entries)
            if (e.value is Map)
              e.key: Instalada(((e.value as Map)['versionCode'] as num?)?.toInt() ?? 0, '${(e.value as Map)['version'] ?? ''}'),
        },
      );
    } catch (_) {}
  }

  void _aviso(String t) => ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(t), duration: const Duration(seconds: 6)));

  Future<void> _instalar(AppCat a) async {
    setState(() => _avance[a.id] = 'Bajando…');
    final cliente = http.Client();
    try {
      final dir = Directory('${(await getTemporaryDirectory()).path}/descargas');
      if (await dir.exists()) await dir.delete(recursive: true); // lo bajado antes ya no sirve
      await dir.create(recursive: true);
      final archivo = File('${dir.path}/${a.id}-${a.versionCode}.apk');
      final req = http.Request('GET', Uri.parse(a.urlPara(es32: _es32)))..headers['User-Agent'] = agente;
      final r = await cliente.send(req).timeout(const Duration(seconds: 30));
      if (r.statusCode != 200) throw 'El servidor respondió ${r.statusCode}';
      final total = r.contentLength ?? a.tamano;
      var llevo = 0;
      final sal = archivo.openWrite();
      await for (final trozo in r.stream) {
        sal.add(trozo);
        llevo += trozo.length;
        if (mounted && total > 0) setState(() => _avance[a.id] = 'Bajando ${(llevo * 100 / total).floor()} %');
      }
      await sal.close();
      if (total > 0 && llevo < total) throw 'La descarga se cortó. Vuelva a intentar.';
      final res = await _canal.invokeMethod<String>('instalar', {'ruta': archivo.path, 'paquete': a.paquete});
      if (!mounted) return;
      switch (res) {
        case 'ok':
          _aviso('Confirme «Instalar» en la ventana de Android.');
        case 'permiso':
          _aviso('Android pide permiso: active «Permitir de esta fuente» para FactuPOS Apps, vuelva y toque otra vez «${_inst.containsKey(a.paquete) ? 'Actualizar' : 'Instalar'}».');
        case 'firma':
          await _firmaDistinta(a);
        default:
          _aviso('No se pudo abrir el instalador de Android.');
      }
    } catch (e) {
      if (mounted) _aviso(e is SocketException || e is TimeoutException ? 'Sin internet: no se pudo bajar ${a.nombre}.' : '$e');
    } finally {
      cliente.close();
      if (mounted) setState(() => _avance.remove(a.id));
    }
  }

  /// La instalada salió con otra llave (versiones viejas de prueba): Android no deja instalar encima.
  Future<void> _firmaDistinta(AppCat a) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Hay que desinstalar la versión vieja de ${a.nombre}'),
        content: const Text(
          'La que está en este teléfono se firmó con otra llave, y Android no deja instalar la nueva encima.\n\n'
          'Al desinstalarla se borra lo que esa app tenía guardado en este teléfono (configuración, y en FactuSuper las ventas que '
          'no se hayan enviado). Anote la configuración antes.\n\n'
          'Después de desinstalar, toque «Instalar».',
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Ahora no')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Desinstalar la vieja')),
        ],
      ),
    );
    if (ok == true) await _canal.invokeMethod('desinstalar', {'paquete': a.paquete});
  }

  Future<void> _desinstalar(AppCat a) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('¿Desinstalar ${a.nombre}?'),
        content: const Text('Se borra también lo que esa app tenía guardado en este teléfono.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancelar')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Desinstalar'),
          ),
        ],
      ),
    );
    if (ok == true) await _canal.invokeMethod('desinstalar', {'paquete': a.paquete});
  }

  Future<void> _abrir(AppCat a) async {
    final ok = await _canal.invokeMethod<bool>('abrir', {'paquete': a.paquete}) ?? false;
    if (!ok && mounted) _aviso('${a.nombre} no se puede abrir desde aquí.');
  }

  Future<void> _actualizarTodo() async {
    for (final a in [...?_apps]) {
      if (a.id != 'apps' && estadoDe(a, _inst[a.paquete]) == Estado.actualizar) {
        await _instalar(a);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final apps = _apps;
    final pendientes = apps == null
        ? 0
        : apps.where((a) => a.id != 'apps' && estadoDe(a, _inst[a.paquete]) == Estado.actualizar).length;
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: _cargar,
        child: CustomScrollView(
          slivers: [
            SliverToBoxAdapter(child: _cabecera(pendientes)),
            if (_error.isNotEmpty)
              SliverToBoxAdapter(child: _cajaError())
            else if (apps == null)
              const SliverFillRemaining(child: Center(child: CircularProgressIndicator()))
            else
              for (final g in agrupar(apps)) ...[
                SliverToBoxAdapter(child: _tituloGrupo(g.key)),
                SliverList.list(children: [for (final a in g.value) _tarjeta(a)]),
              ],
            const SliverToBoxAdapter(child: SizedBox(height: 24)),
          ],
        ),
      ),
    );
  }

  Widget _cabecera(int pendientes) => Container(
    decoration: const BoxDecoration(
      gradient: LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: [Marca.navy, Marca.navyOscuro]),
    ),
    padding: EdgeInsets.fromLTRB(18, MediaQuery.paddingOf(context).top + 16, 18, 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.asset('assets/icono.png', width: 40, height: 40)),
            const SizedBox(width: 12),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('FactuPOS Apps', style: TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w800)),
                  Text('Instalar, actualizar y quitar aplicaciones', style: TextStyle(color: Color(0xFFCBD5E1), fontSize: 13)),
                ],
              ),
            ),
            Text('v$versionApp', style: const TextStyle(color: Color(0xFFCBD5E1), fontSize: 12)),
          ],
        ),
        if (pendientes > 0) ...[
          const SizedBox(height: 14),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: Marca.celeste, foregroundColor: Marca.navyOscuro),
              onPressed: _ocupado ? null : _actualizarTodo,
              icon: const Icon(Icons.system_update_alt),
              label: Text(pendientes == 1 ? 'Actualizar 1 aplicación' : 'Actualizar $pendientes aplicaciones'),
            ),
          ),
        ],
      ],
    ),
  );

  Widget _cajaError() => Padding(
    padding: const EdgeInsets.all(18),
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          children: [
            const Icon(Icons.cloud_off, size: 40, color: Marca.tintaSuave),
            const SizedBox(height: 10),
            Text(_error, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: _cargar, child: const Text('Volver a intentar')),
          ],
        ),
      ),
    ),
  );

  Widget _tituloGrupo(String g) => Padding(
    padding: const EdgeInsets.fromLTRB(18, 18, 18, 6),
    child: Text(
      (g.isEmpty ? 'Esta aplicación' : g).toUpperCase(),
      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 0.8, color: Marca.tintaSuave),
    ),
  );

  static IconData _icono(String id) => switch (id) {
    'apps' => Icons.apps,
    'factusuper' => Icons.shopping_cart_outlined,
    'factumovil' => Icons.phone_iphone,
    'factupos' => Icons.point_of_sale,
    'print' => Icons.print_outlined,
    'sms' => Icons.sms_outlined,
    'soporte' => Icons.support_agent,
    'brave' => Icons.public,
    _ => Icons.android,
  };

  Widget _tarjeta(AppCat a) {
    final i = _inst[a.paquete];
    final est = estadoDe(a, i);
    final avance = _avance[a.id];
    final linea = switch (est) {
      Estado.noInstalada => 'Versión ${a.version}${a.tamano > 0 ? ' · ${megas(a.tamano)}' : ''}',
      Estado.alDia => 'Instalada ${i!.version} · al día',
      Estado.actualizar => 'Instalada ${i!.version} → nueva ${a.version}',
    };
    Widget boton;
    if (avance != null) {
      boton = Text(avance, style: const TextStyle(fontWeight: FontWeight.w600, color: Marca.navy));
    } else {
      boton = Wrap(
        spacing: 6,
        children: [
          if (est == Estado.noInstalada)
            FilledButton(onPressed: _ocupado ? null : () => _instalar(a), child: const Text('Instalar'))
          else ...[
            if (est == Estado.actualizar)
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: Marca.verde),
                onPressed: _ocupado ? null : () => _instalar(a),
                child: const Text('Actualizar'),
              ),
            if (a.id != 'apps') OutlinedButton(onPressed: () => _abrir(a), child: const Text('Abrir')),
            if (a.id != 'apps')
              IconButton(
                tooltip: 'Desinstalar',
                onPressed: _ocupado ? null : () => _desinstalar(a),
                icon: const Icon(Icons.delete_outline, color: Marca.tintaSuave),
              ),
          ],
        ],
      );
    }
    return Card(
      margin: const EdgeInsets.fromLTRB(14, 4, 14, 4),
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: const BorderSide(color: Color(0xFFE2E8F0))),
      color: Colors.white,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(color: const Color(0xFFE8EEF8), borderRadius: BorderRadius.circular(12)),
              child: Icon(_icono(a.id), color: Marca.navy),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(a.nombre, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  if (a.desc.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(a.desc, style: const TextStyle(fontSize: 13, color: Marca.tintaSuave)),
                    ),
                  const SizedBox(height: 6),
                  Text(
                    linea,
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: est == Estado.actualizar ? Marca.verde : Marca.tintaSuave,
                    ),
                  ),
                  const SizedBox(height: 8),
                  boton,
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
