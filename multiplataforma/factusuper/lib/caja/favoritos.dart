/// FAVORITOS (#3957) — réplica del panel MV-118 de la web (#2067, TIP #48 de Jorge Marín). Dos listas en una:
///   · MÁS VENDIDOS (★): los elige el sistema (favoritos_obtener.php, ventas procesadas de 30 días), iguales para todos.
///     Se traen con internet al abrir el panel, como mucho cada 10 minutos; sin red, lo último que se bajó.
///   · FAVORITOS DEL CAJERO: cada cajero pone y quita los suyos (máx. 20). NO pasan por el servidor: se guardan en este
///     equipo, por usuario, y funcionan sin internet.
///   Un artículo que está en las dos sale UNA vez, con estrella. «Si ya está en cualquiera de las 2 listas, no hace falta
///   agregarlo.» Un clic agrega 1 unidad SUMANDO a la línea si ya está.
library;

import '../datos/almacen.dart';
import '../datos/conexion.dart';
import '../motor/redondeo.dart';
import 'datos_caja.dart';
import 'documento.dart';

const favMax = 20;
const _refresco = Duration(minutes: 10);

class FilaFav {
  final Map<String, dynamic> art;
  final bool sistema;
  bool mio;
  final int puesto;
  bool sinPrecio = false;
  double precio = 0;
  FilaFav(
    this.art, {
    required this.sistema,
    required this.mio,
    required this.puesto,
  });
  String get codigo => '${art['codigo']}';
  String get nombre => '${art['nombre']}';
}

class Favoritos {
  final Almacen almacen;
  final ConfigCaja config;
  final DatosCaja datos;
  final List<String> servidores;
  DateTime _ultimoRefresco = DateTime.fromMillisecondsSinceEpoch(0);
  Favoritos(
    this.almacen,
    this.config,
    this.datos, {
    this.servidores = servidoresFactuPOS,
  });

  String _clave(String usuario) =>
      'favoritos_${usuario.replaceAll(RegExp(r'[^0-9A-Za-z]'), '')}';

  Future<Map<String, dynamic>> masVendidos() async {
    final v = await almacen.leerTabla(config.empresa, 'mas_vendidos');
    return v is Map
        ? Map<String, dynamic>.from(v)
        : {'fecha': null, 'dias': 30, 'lista': []};
  }

  Future<List<String>> delCajero(String usuario) async {
    final v = await almacen.leerTabla(config.empresa, _clave(usuario));
    return v is List ? [for (final x in v) '$x'] : <String>[];
  }

  Future<List<String>> guardarDelCajero(
    String usuario,
    List<String> codigos,
  ) async {
    final vistos = <String>{};
    final l = [
      for (final c in codigos.map((c) => c.trim()))
        if (c.isNotEmpty && vistos.add(c)) c,
    ];
    await almacen.guardarTabla(config.empresa, _clave(usuario), l);
    return l;
  }

  /// Con internet trae el ranking de hoy (como mucho cada 10 minutos). → true si cambió lo guardado.
  Future<bool> refrescar(String usuario, {bool forzar = false}) async {
    if (!forzar && DateTime.now().difference(_ultimoRefresco) < _refresco)
      return false;
    _ultimoRefresco = DateTime.now();
    final con = Conexion(
      llave: config.llave,
      cajero: usuario,
      servidores: servidores,
    );
    try {
      final j = await con.get(
        'favoritos_obtener.php',
        espera: const Duration(seconds: 8),
      );
      if (j['success'] != true)
        throw ErrorConexion('${j['error'] ?? 'sin datos'}');
      await almacen.guardarTabla(config.empresa, 'mas_vendidos', {
        'fecha': DateTime.now().toUtc().toIso8601String(),
        'dias': (j['dias'] as num?)?.toInt() ?? 30,
        'lista': j['mas_vendidos'] ?? [],
      });
      return true;
    } catch (_) {
      _ultimoRefresco = DateTime.fromMillisecondsSinceEpoch(
        0,
      ); // sin conexión: se queda con lo guardado
      return false;
    } finally {
      con.cerrar();
    }
  }

  /// Arma la lista con lo que hay EN EL EQUIPO (favArmar de la web).
  Future<List<FilaFav>> armar(Documento doc) async {
    final mv = await masVendidos();
    final mapa = <String, FilaFav>{};
    var puesto = 0;
    for (final m in (mv['lista'] as List? ?? const [])) {
      if (puesto >= favMax) break;
      final a = datos.articuloExacto('${(m as Map)['codigo']}');
      if (a == null || mapa.containsKey('${a['codigo']}'))
        continue; // dado de baja o todavía no bajó
      puesto++;
      mapa['${a['codigo']}'] = FilaFav(
        a,
        sistema: true,
        mio: false,
        puesto: puesto,
      );
    }
    var n = 0;
    for (final c in await delCajero(doc.cajero.usuario)) {
      n++;
      final a = datos.articuloExacto(c);
      if (a == null) continue;
      final f = mapa['${a['codigo']}'];
      if (f != null) {
        f.mio = true;
      } else {
        mapa['${a['codigo']}'] = FilaFav(
          a,
          sistema: false,
          mio: true,
          puesto: 1000 + n,
        );
      }
    }
    final nivel = doc.nivelActual();
    for (final f in mapa.values) {
      final p = doc.precioPara(f.codigo, nivel);
      f.sinPrecio = p == null;
      final iva =
          (f.art['tarifa_iva'] as num?)?.toDouble() ??
          double.tryParse('${f.art['tarifa_iva']}') ??
          0;
      f.precio = p == null ? 0 : redondear(p.$1 * (1 + iva / 100), 2);
    }
    return mapa.values.toList();
  }

  /// Orden de la lista: 'origen' (primero el ranking, después los del cajero) · 'codigo' · 'nombre' · 'precio'.
  static List<FilaFav> ordenar(List<FilaFav> filas, String campo, int dir) {
    int cmp(FilaFav a, FilaFav b) => switch (campo) {
      'codigo' => a.codigo.compareTo(b.codigo),
      'nombre' => a.nombre.toLowerCase().compareTo(b.nombre.toLowerCase()),
      'precio' => a.precio.compareTo(b.precio),
      _ =>
        ((b.sistema ? 1 : 0) - (a.sistema ? 1 : 0)) != 0
            ? (b.sistema ? 1 : 0) - (a.sistema ? 1 : 0)
            : a.puesto - b.puesto,
    };
    final l = [...filas]
      ..sort((a, b) {
        final c = dir * cmp(a, b);
        return c != 0 ? c : a.puesto - b.puesto;
      });
    return l;
  }
}
