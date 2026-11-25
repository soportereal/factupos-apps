/// Lo que la caja guarda en el equipo (#3957): la configuración (llave + empresa) y la copia de los datos
/// para vender sin internet. Una carpeta por EMPRESA (si se cambia la llave a otra empresa, no se mezclan).
///
/// F1: archivos JSON (artículos, precios, clientes, catálogos) cargados a memoria al abrir. Alcanza de sobra
/// para un súper (decenas de miles de artículos); si algún cliente lo pide más grande, se pasa a SQLite sin
/// cambiar a quién lo usa.
library;

import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

class ConfigCaja {
  final String llave, empresa, empresaNombre;
  final DateTime guardada;
  const ConfigCaja({required this.llave, required this.empresa, required this.empresaNombre, required this.guardada});

  Map<String, Object?> aMapa() => {
        'llave': llave,
        'empresa': empresa,
        'empresaNombre': empresaNombre,
        'guardada': guardada.toIso8601String(),
      };
  factory ConfigCaja.desde(Map<String, dynamic> m) => ConfigCaja(
        llave: '${m['llave'] ?? ''}',
        empresa: '${m['empresa'] ?? ''}',
        empresaNombre: '${m['empresaNombre'] ?? ''}',
        guardada: DateTime.tryParse('${m['guardada']}') ?? DateTime.now(),
      );

  /// La llave a medias, para mostrarla sin exponerla entera.
  String get llaveVisible => llave.length > 12 ? '${llave.substring(0, 8)}…${llave.substring(llave.length - 4)}' : llave;
}

class Almacen {
  final Directory raiz;
  Almacen(this.raiz);

  static Future<Almacen> abrir() async {
    final d = Directory('${(await getApplicationSupportDirectory()).path}${Platform.pathSeparator}factusuper');
    await d.create(recursive: true);
    return Almacen(d);
  }

  File get _config => File('${raiz.path}${Platform.pathSeparator}config.json');

  Future<ConfigCaja?> leerConfig() async {
    try {
      if (!await _config.exists()) return null;
      return ConfigCaja.desde(jsonDecode(await _config.readAsString()) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  /// 🔒 La llave queda en la carpeta privada de la app; en Linux/Android además solo la lee el usuario dueño.
  Future<void> guardarConfig(ConfigCaja c) async {
    await _escribir(_config, jsonEncode(c.aMapa()));
    if (!Platform.isWindows) {
      try {
        await Process.run('chmod', ['600', _config.path]);
      } catch (_) {}
    }
  }

  Future<void> borrarConfig() async {
    if (await _config.exists()) await _config.delete();
  }

  Directory _empresa(String empresa) => Directory('${raiz.path}${Platform.pathSeparator}${empresa.replaceAll(RegExp(r'[^a-zA-Z0-9_-]'), '_')}');

  Future<void> guardarTabla(String empresa, String tabla, Object datos) async {
    final d = _empresa(empresa);
    await d.create(recursive: true);
    await _escribir(File('${d.path}${Platform.pathSeparator}$tabla.json'), jsonEncode(datos));
  }

  Future<dynamic> leerTabla(String empresa, String tabla) async {
    final f = File('${_empresa(empresa).path}${Platform.pathSeparator}$tabla.json');
    if (!await f.exists()) return null;
    return jsonDecode(await f.readAsString());
  }

  /// Escribir a un temporal y renombrar: si se va la luz a media escritura, queda el archivo anterior entero.
  Future<void> _escribir(File f, String texto) async {
    final tmp = File('${f.path}.tmp');
    await tmp.writeAsString(texto, flush: true);
    await tmp.rename(f.path);
  }
}
