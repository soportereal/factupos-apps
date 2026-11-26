/// La lista de apps de FactuPOS para Android (soportereal.com/descarga/catalogo_android.php) y qué hacer con cada una.
/// La versión de cada app la lee el servidor del propio APK; acá se compara su versionCode con el instalado.
library;

import 'dart:convert';

const urlCatalogo = 'https://soportereal.com/descarga/catalogo_android.php';

/// Sin «Mozilla»: el servidor deja bajar los APK directo a las apps (a los navegadores les pide usuario de FactuPOS).
const agente = 'FactuPOS-Apps-Android/$versionApp';
const versionApp = '1.0.1';

class AppCat {
  final String id, nombre, desc, grupo, paquete, version, url, url32, fecha;
  final int versionCode, tamano;
  const AppCat({
    required this.id,
    required this.nombre,
    this.desc = '',
    this.grupo = '',
    required this.paquete,
    required this.versionCode,
    this.version = '',
    required this.url,
    this.url32 = '',
    this.fecha = '',
    this.tamano = 0,
  });

  factory AppCat.desde(Map j) => AppCat(
    id: '${j['id'] ?? ''}',
    nombre: '${j['nombre'] ?? ''}',
    desc: '${j['desc'] ?? ''}',
    grupo: '${j['grupo'] ?? ''}',
    paquete: '${j['paquete'] ?? ''}',
    versionCode: (j['versionCode'] as num?)?.toInt() ?? 0,
    version: '${j['version'] ?? ''}',
    url: '${j['url'] ?? ''}',
    url32: '${j['url_32'] ?? ''}',
    fecha: '${j['fecha'] ?? ''}',
    tamano: (j['tamano'] as num?)?.toInt() ?? 0,
  );

  /// El APK que corresponde a este teléfono (los de 32 bits bajan el de 32 si existe).
  String urlPara({required bool es32}) => es32 && url32.isNotEmpty ? url32 : url;
}

/// Lo que hay instalado de una app en el teléfono.
class Instalada {
  final int versionCode;
  final String version;
  const Instalada(this.versionCode, this.version);
}

enum Estado { noInstalada, alDia, actualizar }

Estado estadoDe(AppCat a, Instalada? i) {
  if (i == null) return Estado.noInstalada;
  return a.versionCode > i.versionCode ? Estado.actualizar : Estado.alDia;
}

/// Orden de los grupos en pantalla (lo que no esté acá va al final, en el orden en que llegó).
const ordenGrupos = ['', 'Facturación', 'Impresión', 'Bancos', 'Soporte', 'Otras apps'];

List<AppCat> leerCatalogo(String cuerpo) {
  final j = jsonDecode(cuerpo);
  final lista = (j is Map ? j['apps'] : null) as List? ?? const [];
  return [
    for (final x in lista)
      if (x is Map && '${x['paquete'] ?? ''}'.isNotEmpty && '${x['url'] ?? ''}'.isNotEmpty) AppCat.desde(x),
  ];
}

/// Agrupa respetando [ordenGrupos]; «FactuPOS Apps» misma (grupo vacío) queda arriba.
List<MapEntry<String, List<AppCat>>> agrupar(List<AppCat> apps) {
  final m = <String, List<AppCat>>{};
  for (final a in apps) {
    (m[a.grupo] ??= []).add(a);
  }
  int pos(String g) {
    final i = ordenGrupos.indexOf(g);
    return i < 0 ? ordenGrupos.length : i;
  }

  final claves = m.keys.toList()..sort((a, b) => pos(a).compareTo(pos(b)));
  return [for (final k in claves) MapEntry(k, m[k]!)];
}

String megas(int bytes) => bytes <= 0 ? '' : '${(bytes / 1048576).toStringAsFixed(bytes < 10485760 ? 1 : 0)} MB';
