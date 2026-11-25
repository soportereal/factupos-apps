/// Bajar la copia de la empresa al equipo y mantenerla al día (#3957) — réplica de FSLocal (factusuper_local.js):
///
///  · `firmas_obtener` → una firma por grupo (articulos · precios · clientes · catalogos) + la HORA del servidor.
///  · Solo se baja el grupo cuya firma cambió («que solo actualice si hubo cambios»).
///  · Artículos/precios/clientes: primero se intenta SOLO LO QUE CAMBIÓ (`cambios_descargar?desde=<hora>`) y se aplica
///    encima; si no se puede confiar en el delta (nunca hubo completa, la completa tiene más de 24 h, el servidor dice
///    «demasiados», o los totales no cuadran después de aplicar) → se baja entero.
///  · Una descarga nunca deja una copia a medias: se verifica el total antes de reemplazar.
library;

import 'almacen.dart';
import 'conexion.dart';

typedef Avance = void Function(String que, int hechos, int total);

const List<String> gruposSync = [
  'articulos',
  'precios',
  'clientes',
  'catalogos',
];
const Duration _dia = Duration(hours: 24);

/// Resultado de una sincronización: 'al_dia' · 'actualizado' · 'sin_conexion'.
class ResultadoSync {
  final String estado;
  final List<String> grupos; // bajados enteros
  final Map<String, dynamic>?
  cambios; // {hechos, codigos, articulos, bajas, clientes, clientesBaja}
  const ResultadoSync(this.estado, {this.grupos = const [], this.cambios});
}

class Descarga {
  final Conexion con;
  final Almacen almacen;
  final String empresa;
  Descarga(this.con, this.almacen, this.empresa);

  Future<Map<String, dynamic>> _estado() async {
    final e = await almacen.leerTabla(empresa, 'sincronizacion');
    return e is Map ? Map<String, dynamic>.from(e) : <String, dynamic>{};
  }

  Future<void> _guardarEstado(Map<String, dynamic> e) =>
      almacen.guardarTabla(empresa, 'sincronizacion', e);

  Future<Map<String, String>> firmasServidor() async {
    final j = await con.get(
      'firmas_obtener.php',
      espera: const Duration(seconds: 8),
    );
    if (j['success'] != true)
      throw ErrorConexion(
        'No se pudieron leer las firmas: ${j['error'] ?? ''}',
      );
    final f = (j['firmas'] as Map?) ?? const {};
    return {
      for (final e in f.entries) '${e.key}': '${e.value}',
      '_hora': '${j['hora'] ?? ''}',
    };
  }

  /// Todo de cero (Configuración / «Actualizar datos»). Devuelve cuántas filas bajó de cada grupo.
  Future<Map<String, int>> todo({Avance? avance}) async {
    final firmas = await firmasServidor();
    return actualizar(gruposSync, firmas, avance: avance);
  }

  /// Baja ENTEROS los grupos indicados y los guarda; anota sus firmas y, si fueron artículos+precios, la hora desde la
  /// que se piden solo los cambios la próxima vez.
  Future<Map<String, int>> actualizar(
    List<String> grupos,
    Map<String, String> firmas, {
    Avance? avance,
  }) async {
    final n = <String, int>{};
    final datos = <String, Object>{};
    for (final g in const ['articulos', 'precios', 'clientes']) {
      if (grupos.contains(g)) datos[g] = await _porTandas(g, avance);
    }
    if (grupos.contains('catalogos')) {
      final cat = await con.get('catalogos_descargar.php');
      if (cat['success'] != true)
        throw ErrorConexion(
          'No se pudieron bajar los catálogos: ${cat['error'] ?? ''}',
        );
      datos['catalogos'] = cat['tablas'] ?? {};
      n['catalogos'] = (cat['tablas'] as Map?)?.length ?? 0;
    }
    // Recién con TODO bajado y verificado se reemplaza la copia (si algo falla arriba, queda la anterior entera).
    for (final e in datos.entries) {
      await almacen.guardarTabla(empresa, e.key, e.value);
      if (e.value is List) n[e.key] = (e.value as List).length;
    }
    final est = await _estado();
    final f = Map<String, dynamic>.from((est['firmas'] as Map?) ?? const {});
    for (final g in grupos) {
      f[g] = firmas[g];
    }
    final ahora = DateTime.now().toIso8601String();
    est['firmas'] = f;
    est['ultima_actualizacion'] = ahora;
    if (grupos.contains('articulos') &&
        grupos.contains('precios') &&
        (firmas['_hora'] ?? '').isNotEmpty) {
      est['sync_hora'] = firmas['_hora'];
      est['sync_completa'] = ahora;
    }
    await _guardarEstado(est);
    return n;
  }

  /// Solo los catálogos, con el CAJERO que entró: así la copia trae SU estación (como la web al cambiar de cajero).
  Future<void> catalogos() async {
    final firmas = await firmasServidor();
    await actualizar(const ['catalogos'], firmas);
  }

  /// Sincronizar SOLO SI HACE FALTA (al abrir, al entrar un cajero, al agregar). [soloCambios] (al agregar): nunca baja todo
  /// ni los catálogos; si no se puede por cambios, queda para la sincronización normal.
  Future<ResultadoSync> sincronizarSiHaceFalta({
    bool soloCambios = false,
    Avance? avance,
  }) async {
    Map<String, String> firmas;
    try {
      firmas = await firmasServidor();
    } on ErrorConexion catch (e) {
      if (e.sinInternet) return const ResultadoSync('sin_conexion');
      rethrow;
    }
    final est = await _estado();
    final guardadas = Map<String, dynamic>.from(
      (est['firmas'] as Map?) ?? const {},
    );
    var grupos = gruposSync
        .where((g) => '${guardadas[g]}' != firmas[g])
        .toList();
    if (soloCambios) grupos.remove('catalogos');
    if (grupos.isEmpty) {
      if (!soloCambios) await _avanzarHora(firmas);
      return const ResultadoSync('al_dia');
    }
    Map<String, dynamic>? cambios;
    if (grupos.any(
      (g) => g == 'articulos' || g == 'precios' || g == 'clientes',
    )) {
      try {
        cambios = await _aplicarCambios(firmas, grupos);
      } catch (_) {
        cambios = null;
      }
      if (cambios != null)
        grupos = grupos
            .where((g) => !(cambios!['hechos'] as List).contains(g))
            .toList();
    }
    if (soloCambios) {
      if (grupos.isEmpty) await _avanzarHora(firmas);
      return ResultadoSync(
        cambios != null ? 'actualizado' : 'al_dia',
        cambios: cambios,
      );
    }
    if (grupos.isNotEmpty) await actualizar(grupos, firmas, avance: avance);
    await _avanzarHora(firmas);
    return ResultadoSync('actualizado', grupos: grupos, cambios: cambios);
  }

  /// Todo lo que difería ya quedó igual: la próxima vez se piden los cambios desde la hora de estas firmas.
  Future<void> _avanzarHora(Map<String, String> firmas) async {
    final est = await _estado();
    if ((firmas['_hora'] ?? '').isNotEmpty && est['sync_completa'] != null) {
      est['sync_hora'] = firmas['_hora'];
      await _guardarEstado(est);
    }
  }

  List<Map<String, dynamic>> _filas(Object? v) => v is List
      ? [
          for (final x in v)
            if (x is Map) Map<String, dynamic>.from(x),
        ]
      : <Map<String, dynamic>>[];

  /// Solo lo que cambió desde la última sincronización (aplicarCambios de la web). null = hay que bajar entero.
  Future<Map<String, dynamic>?> _aplicarCambios(
    Map<String, String> firmas,
    List<String> grupos,
  ) async {
    final est = await _estado();
    final desde = '${est['sync_hora'] ?? ''}';
    final completa = DateTime.tryParse('${est['sync_completa'] ?? ''}');
    if (desde.isEmpty ||
        (firmas['_hora'] ?? '').isEmpty ||
        completa == null ||
        DateTime.now().difference(completa) > _dia)
      return null;
    final d = await con.get('cambios_descargar.php', query: {'desde': desde});
    if (d['success'] != true) return null;
    final hechos = <String>[];
    final r = <String, dynamic>{
      'articulos': 0,
      'bajas': 0,
      'clientes': 0,
      'clientesBaja': 0,
      'codigos': <String>[],
    };

    final quiereArt =
        grupos.contains('articulos') || grupos.contains('precios');
    final dArt = _filas(d['articulos']), dPre = _filas(d['precios']);
    final bajas = [for (final b in (d['bajas'] as List? ?? const [])) '$b'];
    if (quiereArt &&
        d['demasiados'] != true &&
        (dArt.isNotEmpty || bajas.isNotEmpty)) {
      final tocados = {...dArt.map((a) => '${a['codigo']}'), ...bajas};
      final arts = _filas(await almacen.leerTabla(empresa, 'articulos'))
        ..removeWhere((a) => tocados.contains('${a['codigo']}'));
      arts.addAll(dArt);
      final pres = _filas(await almacen.leerTabla(empresa, 'precios'))
        ..removeWhere((p) => tocados.contains('${p['articulo']}'));
      pres.addAll(dPre);
      final tot = (d['totales'] as Map?) ?? const {};
      // Se guarda solo si cuadra con el servidor (si no, se baja entero).
      if (arts.length == (tot['articulos'] as num?)?.toInt() &&
          pres.length == (tot['precios'] as num?)?.toInt()) {
        await almacen.guardarTabla(empresa, 'articulos', arts);
        await almacen.guardarTabla(empresa, 'precios', pres);
        hechos.addAll(['articulos', 'precios']);
        r['articulos'] = dArt.length;
        r['bajas'] = bajas.length;
        r['codigos'] = tocados.toList();
      }
    }
    final c = d['clientes'];
    if (grupos.contains('clientes') &&
        c is Map &&
        (_filas(c['filas']).isNotEmpty ||
            (c['bajas'] as List? ?? const []).isNotEmpty)) {
      final filas = _filas(c['filas']);
      final bajasC = {for (final b in (c['bajas'] as List? ?? const [])) '$b'};
      final nuevos = {for (final f in filas) '${f['codigo']}'};
      final cli = _filas(await almacen.leerTabla(empresa, 'clientes'))
        ..removeWhere(
          (x) =>
              bajasC.contains('${x['codigo']}') ||
              nuevos.contains('${x['codigo']}'),
        );
      cli.addAll(filas);
      final locales = cli
          .where((x) => !'${x['codigo']}'.startsWith('N-'))
          .length;
      if (locales == (c['total'] as num?)?.toInt()) {
        await almacen.guardarTabla(empresa, 'clientes', cli);
        hechos.add('clientes');
        r['clientes'] = filas.length;
        r['clientesBaja'] = bajasC.length;
      }
    }
    if (hechos.isEmpty) return null;
    final f = Map<String, dynamic>.from((est['firmas'] as Map?) ?? const {});
    for (final g in hechos) {
      f[g] = firmas[g];
    }
    est['firmas'] = f;
    est['ultima_actualizacion'] = DateTime.now().toIso8601String();
    await _guardarEstado(est);
    return {'hechos': hechos, ...r};
  }

  Future<List<Map<String, dynamic>>> _porTandas(
    String grupo,
    Avance? avance,
  ) async {
    const tanda = 2000;
    final filas = <Map<String, dynamic>>[];
    int? total;
    for (var offset = 0; ; offset += tanda) {
      final j = await con.get(
        '${grupo}_descargar.php',
        query: {'offset': '$offset', 'limite': '$tanda'},
      );
      if (j['success'] != true)
        throw ErrorConexion('No se pudo bajar $grupo: ${j['error'] ?? ''}');
      if (offset == 0) total = (j['total'] as num?)?.toInt();
      final f = _filas(j['filas']);
      filas.addAll(f);
      avance?.call(grupo, filas.length, total ?? 0);
      if (f.length < tanda) break;
    }
    if (total != null && filas.length != total) {
      throw ErrorConexion(
        'Llegaron ${filas.length} de $total $grupo: no se guardó nada, intente de nuevo.',
      );
    }
    return filas;
  }
}
