/// Bajar la copia de la empresa al equipo (#3957) — las mismas APIs que usa FactuSuper web:
/// `firmas_obtener` (qué cambió) · `catalogos_descargar` (tablas chicas: parámetros, estación, usuarios, medios…)
/// · `articulos_/precios_/clientes_descargar` por tandas de 2000.
library;

import 'almacen.dart';
import 'conexion.dart';

typedef Avance = void Function(String que, int hechos, int total);

class Descarga {
  final Conexion con;
  final Almacen almacen;
  final String empresa;
  Descarga(this.con, this.almacen, this.empresa);

  /// Todo de cero. Devuelve cuántas filas bajó de cada grupo.
  Future<Map<String, int>> todo({Avance? avance}) async {
    final firmas = await con.get('firmas_obtener.php');
    final cat = await con.get('catalogos_descargar.php');
    if (cat['success'] != true) throw ErrorConexion('No se pudieron bajar los catálogos: ${cat['error'] ?? ''}');
    await almacen.guardarTabla(empresa, 'catalogos', cat['tablas'] ?? {});
    final n = <String, int>{'catalogos': (cat['tablas'] as Map?)?.length ?? 0};
    for (final g in const ['articulos', 'precios', 'clientes']) {
      n[g] = await _porTandas(g, avance);
    }
    await almacen.guardarTabla(empresa, 'sincronizacion', {
      'firmas': firmas['firmas'],
      'hora': firmas['hora'],
      'equipo': DateTime.now().toIso8601String(),
      'cuantos': n,
    });
    return n;
  }

  Future<int> _porTandas(String grupo, Avance? avance) async {
    const tanda = 2000;
    final filas = <dynamic>[];
    var total = 0;
    for (var offset = 0;; offset += tanda) {
      final j = await con.get('${grupo}_descargar.php', query: {'offset': '$offset', 'limite': '$tanda'});
      if (j['success'] != true) throw ErrorConexion('No se pudo bajar $grupo: ${j['error'] ?? ''}');
      if (offset == 0) total = (j['total'] as num?)?.toInt() ?? 0;
      final f = (j['filas'] as List?) ?? const [];
      filas.addAll(f);
      avance?.call(grupo, filas.length, total);
      if (f.length < tanda) break;
    }
    // 🔑 Se verifica que quedó entero antes de reemplazar la copia buena (como la web: compara con el total).
    if (total > 0 && filas.length < total) {
      throw ErrorConexion('La descarga de $grupo quedó incompleta (${filas.length} de $total). Se conserva la copia anterior.');
    }
    await almacen.guardarTabla(empresa, grupo, filas);
    return filas.length;
  }
}
