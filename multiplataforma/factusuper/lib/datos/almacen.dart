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
  const ConfigCaja({
    required this.llave,
    required this.empresa,
    required this.empresaNombre,
    required this.guardada,
  });

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
  String get llaveVisible => llave.length > 12
      ? '${llave.substring(0, 8)}…${llave.substring(llave.length - 4)}'
      : llave;
}

class Almacen {
  final Directory raiz;
  Almacen(this.raiz);

  static Future<Almacen> abrir() async {
    final d = Directory(
      '${(await getApplicationSupportDirectory()).path}${Platform.pathSeparator}factusuper',
    );
    await d.create(recursive: true);
    return Almacen(d);
  }

  File get _config => File('${raiz.path}${Platform.pathSeparator}config.json');

  Future<ConfigCaja?> leerConfig() async {
    try {
      if (!await _config.exists()) return null;
      return ConfigCaja.desde(
        jsonDecode(await _config.readAsString()) as Map<String, dynamic>,
      );
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

  // ── «Recordar usuario y clave» en la entrada (dueño, 26-nov-2026, #3957) ──
  // Va en la carpeta privada de la app (como la llave) y con permisos 600. La clave se sigue VALIDANDO cada vez
  // contra la lista local (bcrypt): si la cambian o le quitan el permiso, la recordada deja de servir.
  File _recordar(String empresa) =>
      File('${_empresa(empresa).path}${Platform.pathSeparator}recordar.json');

  Future<(String, String)?> leerRecordado(String empresa) async {
    try {
      final f = _recordar(empresa);
      if (!await f.exists()) return null;
      final m = jsonDecode(await f.readAsString());
      if (m is! Map) return null;
      final u = '${m['usuario'] ?? ''}', c = '${m['clave'] ?? ''}';
      return u.isEmpty ? null : (u, c);
    } catch (_) {
      return null;
    }
  }

  Future<void> guardarRecordado(
    String empresa,
    String usuario,
    String clave,
  ) async {
    final f = _recordar(empresa);
    await f.parent.create(recursive: true);
    await _escribir(f, jsonEncode({'usuario': usuario, 'clave': clave}));
    if (!Platform.isWindows) {
      try {
        await Process.run('chmod', ['600', f.path]);
      } catch (_) {}
    }
  }

  Future<void> borrarRecordado(String empresa) async {
    try {
      final f = _recordar(empresa);
      if (await f.exists()) await f.delete();
    } catch (_) {}
  }

  Directory _empresa(String empresa) => Directory(
    '${raiz.path}${Platform.pathSeparator}${empresa.replaceAll(RegExp(r'[^a-zA-Z0-9_-]'), '_')}',
  );

  Future<void> guardarTabla(String empresa, String tabla, Object datos) async {
    final d = _empresa(empresa);
    await d.create(recursive: true);
    await _escribir(
      File('${d.path}${Platform.pathSeparator}$tabla.json'),
      jsonEncode(datos),
    );
  }

  Future<dynamic> leerTabla(String empresa, String tabla) async {
    final f = File(
      '${_empresa(empresa).path}${Platform.pathSeparator}$tabla.json',
    );
    if (!await f.exists()) return null;
    return jsonDecode(await f.readAsString());
  }

  /// Escribir a un temporal y renombrar: si se va la luz a media escritura, queda el archivo anterior entero.
  /// 🔑 Las escrituras de un MISMO archivo van en FILA (el lector de barras dispara varias seguidas: en paralelo
  ///    chocaban en el temporal — «Cannot rename file»). Gana siempre la última.
  final Map<String, Future<void>> _fila = {};

  Future<void> _escribir(File f, String texto) {
    final anterior = _fila[f.path] ?? Future<void>.value();
    final esta = anterior.catchError((_) {}).then((_) async {
      final tmp = File('${f.path}.tmp');
      await tmp.writeAsString(texto, flush: true);
      await tmp.rename(f.path);
    });
    _fila[f.path] = esta;
    esta
        .whenComplete(() {
          if (identical(_fila[f.path], esta)) _fila.remove(f.path);
        })
        .catchError((_) {});
    return esta;
  }
}
