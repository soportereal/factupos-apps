/// Actualización de la app (#3957). Dueño (25-nov-2026): «se va a actualizar sola, solo que le pongan aviso al usuario
/// que si desea actualizar ahora» · «esa aplicación va a trabajar en un supermercado, entonces el usuario tiene que decir
/// cuándo actualiza». O sea: la app REVISA sola si hay versión nueva y AVISA; nunca se actualiza sin que el cajero diga
/// «Actualizar ahora». El aviso sale en la ENTRADA (entre cajeros), nunca a media venta.
///
/// La versión publicada sale del mismo `FactuSuper_version.json` que usa la lista de «Aplicaciones FactuPOS».
/// Windows: baja el instalador y lo corre en silencio (/SILENT); el instalador la vuelve a abrir al terminar.
/// Linux (FactuPOS OS): el paquete `factupos-factusuper` del repo apt. «Actualizar ahora» usa el MISMO servicio con que
/// instala la Tienda (factupos-apps-op@instalar-<paquete>, sin clave por su regla polkit; op.sh solo acepta paquetes del
/// repo FactuPOS), revisa que quedó la versión nueva y la vuelve a abrir. Solo si la app es la instalada por el .deb.
/// Android: todavía no.
library;

import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';

const String _jsonVersion =
    'https://soportereal.com/software/factupos-app/windows/FactuSuper_version.json';

class VersionNueva {
  final String actual, nueva, url;
  const VersionNueva(this.actual, this.nueva, this.url);
}

/// -1 / 0 / 1 comparando «1.0.10» con «1.0.9» como números.
int compararVersion(String a, String b) {
  List<int> p(String v) =>
      v.split(RegExp(r'[.+-]')).map((x) => int.tryParse(x) ?? 0).toList();
  final x = p(a), y = p(b);
  for (var i = 0; i < 3; i++) {
    final d = (i < x.length ? x[i] : 0) - (i < y.length ? y[i] : 0);
    if (d != 0) return d.sign;
  }
  return 0;
}

/// null si no hay nada nuevo, no hay internet o la plataforma no se actualiza sola todavía.
Future<VersionNueva?> buscarVersionNueva({http.Client? cliente}) async {
  if (!Platform.isWindows && !linuxSeActualiza()) return null;
  final c = cliente ?? http.Client();
  try {
    final actual = (await PackageInfo.fromPlatform()).version;
    final r = await c
        .get(
          Uri.parse(_jsonVersion),
          headers: {'User-Agent': 'FactuSuper-App/$actual'},
        )
        .timeout(const Duration(seconds: 15));
    if (r.statusCode != 200) return null;
    final j = jsonDecode(utf8.decode(r.bodyBytes));
    final nueva = '${j['version'] ?? ''}', url = '${j['downloadUrl'] ?? ''}';
    if (nueva.isEmpty || !url.startsWith('https://soportereal.com/'))
      return null;
    return compararVersion(nueva, actual) > 0
        ? VersionNueva(actual, nueva, url)
        : null;
  } catch (_) {
    return null;
  } finally {
    if (cliente == null) c.close();
  }
}

const paqueteLinux = 'factupos-factusuper';
const _opTienda = '/usr/lib/factupos-apps/op.sh';

/// En Linux solo se actualiza la app instalada por el paquete (en /opt/factusuper) y con la Tienda en el equipo.
bool linuxSeActualiza() =>
    Platform.isLinux &&
    Platform.resolvedExecutable.startsWith('/opt/factusuper/') &&
    File(_opTienda).existsSync();

/// La versión del paquete instalado (dpkg), o '' si no se puede saber.
Future<String> versionPaqueteLinux() async {
  try {
    final r = await Process.run('dpkg-query', [
      '-W',
      '-f',
      r'${Version}',
      paqueteLinux,
    ]);
    return r.exitCode == 0 ? '${r.stdout}'.trim() : '';
  } catch (_) {
    return '';
  }
}

/// Linux: instala la versión nueva por el servicio de la Tienda, revisa con dpkg y vuelve a abrir la app.
Future<void> _instalarLinux(VersionNueva v) async {
  final r = await Process.run('systemctl', [
    'start',
    'factupos-apps-op@instalar-$paqueteLinux.service',
  ]);
  if (r.exitCode != 0) {
    throw Exception(
      'No se pudo actualizar: ${'${r.stderr}'.trim().isEmpty ? 'el servicio de la Tienda no terminó bien' : '${r.stderr}'.trim()}',
    );
  }
  final quedo = await versionPaqueteLinux();
  if (compararVersion(quedo, v.nueva) < 0) {
    throw Exception(
      'La versión ${v.nueva} todavía no está en el repositorio de FactuPOS OS (quedó la $quedo). Pruebe más tarde.',
    );
  }
  await Process.start(
    '/usr/bin/factusuper',
    const [],
    mode: ProcessStartMode.detached,
  );
  exit(0);
}

/// Baja el instalador y lo arranca en silencio; la app se cierra para que se pueda reemplazar.
/// El instalador (factusuper.iss, [Run] con WizardSilent) la vuelve a abrir solo.
Future<void> instalarVersion(
  VersionNueva v, {
  void Function(int bajado, int total)? avance,
}) async {
  if (Platform.isLinux) return _instalarLinux(v);
  final c = http.Client();
  try {
    final req = http.Request('GET', Uri.parse(v.url))
      ..headers['User-Agent'] = 'FactuSuper-App/${v.actual}';
    final r = await c.send(req);
    if (r.statusCode != 200)
      throw Exception(
        'No se pudo bajar la versión nueva (HTTP ${r.statusCode})',
      );
    final total = r.contentLength ?? 0;
    final f = File(
      '${Directory.systemTemp.path}${Platform.pathSeparator}FactuSuper-Setup-${v.nueva}.exe',
    );
    final s = f.openWrite();
    var bajado = 0;
    await for (final trozo in r.stream) {
      s.add(trozo);
      bajado += trozo.length;
      avance?.call(bajado, total);
    }
    await s.close();
    if (total > 0 && await f.length() != total)
      throw Exception('La descarga quedó incompleta: intente de nuevo');
    await Process.start(f.path, [
      '/SILENT',
      '/SUPPRESSMSGBOXES',
      '/NORESTART',
      '/CLOSEAPPLICATIONS',
    ], mode: ProcessStartMode.detached);
    exit(0);
  } finally {
    c.close();
  }
}
