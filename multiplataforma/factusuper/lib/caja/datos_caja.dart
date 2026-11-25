/// Los datos de la caja en memoria (#3957) — réplica de FSLocal (factusuper_local.js): la copia que bajó
/// Configuración (artículos, precios, clientes, catálogos), con los mismos índices: por código, por código de
/// barras y la búsqueda por partes (todas las palabras, en cualquier orden).
library;

import '../datos/almacen.dart';
import '../motor/linea.dart';
import '../motor/redondeo.dart';

String _t(Object? v) => '${v ?? ''}'.trim();
double _n(Object? v) => v is num ? v.toDouble() : (double.tryParse(_t(v)) ?? 0);

class DatosCaja {
  final List<Map<String, dynamic>> articulos;
  final Map<String, Map<String, dynamic>> _porCodigo = {}, _porBarra = {};
  final Map<String, List<Map<String, dynamic>>> _precios = {};
  final Map<String, String> _busca = {};
  final Map<int, String?> parametros;
  final Map<String, dynamic> catalogos;
  final Map<String, Map<String, dynamic>> clientes = {};

  DatosCaja._(
    this.articulos,
    List<Map<String, dynamic>> precios,
    List<Map<String, dynamic>> clientesL,
    this.catalogos,
  ) : parametros = {
        for (final p in _filas(catalogos['parametros']))
          (int.tryParse(_t(p['parametro'])) ?? -1): p['valor']?.toString(),
      } {
    for (final a in articulos) {
      final c = _t(a['codigo']).toUpperCase();
      _porCodigo[c] = a;
      final b = _t(a['barra']).toUpperCase();
      if (b.isNotEmpty) _porBarra[b] = a;
      _busca[c] = '$c $b ${_t(a['nombre'])}'.toUpperCase();
    }
    for (final p in precios) {
      (_precios[_t(p['articulo'])] ??= []).add(p);
    }
    for (final c in clientesL) {
      clientes[_t(c['codigo']).toUpperCase()] = c;
    }
  }

  /// Para las pruebas (y para armarla desde datos ya en memoria).
  factory DatosCaja.desde({
    required List<Map<String, dynamic>> articulos,
    required List<Map<String, dynamic>> precios,
    List<Map<String, dynamic>> clientes = const [],
    required Map<String, dynamic> catalogos,
  }) => DatosCaja._(articulos, precios, clientes, catalogos);

  static List<Map<String, dynamic>> _filas(Object? v) => v is List
      ? [
          for (final x in v)
            if (x is Map) Map<String, dynamic>.from(x),
        ]
      : <Map<String, dynamic>>[];

  static Future<DatosCaja> cargar(Almacen almacen, String empresa) async {
    final cat = await almacen.leerTabla(empresa, 'catalogos');
    return DatosCaja._(
      _filas(await almacen.leerTabla(empresa, 'articulos')),
      _filas(await almacen.leerTabla(empresa, 'precios')),
      _filas(await almacen.leerTabla(empresa, 'clientes')),
      cat is Map<String, dynamic> ? cat : <String, dynamic>{},
    );
  }

  Decimales get decimales => Decimales.desdeParametros(parametros);
  String param(int n, String def) => parametros[n]?.trim() ?? def;

  /// Exacto por código o por código de barras (lo que manda el lector).
  Map<String, dynamic>? articuloExacto(String texto) {
    final k = texto.trim().toUpperCase();
    return _porCodigo[k] ?? _porBarra[k];
  }

  /// Búsqueda por partes: todas las palabras tienen que aparecer.
  List<Map<String, dynamic>> buscar(String texto, {int limite = 200}) {
    final partes = texto
        .trim()
        .toUpperCase()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty)
        .toList();
    if (partes.isEmpty) return const [];
    final out = <Map<String, dynamic>>[];
    for (final a in articulos) {
      final b = _busca[_t(a['codigo']).toUpperCase()] ?? '';
      if (partes.every(b.contains)) {
        out.add(a);
        if (out.length >= limite) break;
      }
    }
    return out;
  }

  List<Map<String, dynamic>> precios(String articulo) =>
      [...(_precios[articulo] ?? const [])]
        ..sort((a, b) => _n(a['numero']).compareTo(_n(b['numero'])));

  /// La estación del cajero (la fila `clave = actual` que bajó con su sesión).
  Map<String, dynamic> get estacion =>
      _filas(catalogos['estacion'])
          .where((e) => _t(e['clave']) == 'actual')
          .firstOrNull ??
      const {};

  /// Tipo de cambio de VENTA más reciente de la moneda.
  double tipoCambio(String moneda) {
    if (moneda.isEmpty || moneda == 'CRC') return 1;
    final l =
        _filas(catalogos['tipo_cambio'])
            .where((t) => _t(t['moneda']) == moneda)
            .toList()
          ..sort((a, b) => _t(b['fecha']).compareTo(_t(a['fecha'])));
    return l.isEmpty ? 0 : _n(l.first['venta']);
  }

  bool tienePermiso(String usuario, String permiso) {
    for (final p in _filas(catalogos['permisos_usuario'])) {
      if (_t(p['usuario']) == usuario && _t(p['permiso']) == permiso)
        return true;
    }
    return false;
  }

  /// Medios de pago visibles, uno por código con sus cuentas.
  List<MedioPago> mediosPago() {
    final m = <String, MedioPago>{};
    for (final f in _filas(catalogos['medios_pago'])) {
      final c = _t(f['codigo']);
      if (_n(f['mostrar']) != 1 || c == '00') continue;
      final x = m.putIfAbsent(
        c,
        () => MedioPago(
          c,
          _t(f['descripcion']).isEmpty ? c : _t(f['descripcion']),
        ),
      );
      if (_t(f['cuenta']).isNotEmpty) x.cuentas.add(_t(f['cuenta']));
    }
    return m.values.toList();
  }

  Map<String, dynamic> get idProcesoServidor =>
      _filas(catalogos['id_proceso'])
          .where((e) => _t(e['clave']) == 'actual')
          .firstOrNull ??
      const {};

  /// Actividad económica del emisor: la primera de la empresa.
  String get actividadEmpresa =>
      _t(_filas(catalogos['actividades_empresa']).firstOrNull?['codigo']);

  /// Config de la romana (dbo.RomanaConfig, MCF-ROM), solo si está activa.
  Map<String, dynamic>? get romana {
    final r = _filas(catalogos['romana']).firstOrNull;
    return r != null && _n(r['activo']) == 1 ? r : null;
  }

  /// Etiqueta de BALANZA — réplica de romanaLeer(): solo dígitos, 8 o más, que NO sea código ni barras conocido.
  /// tipo 'cantidad' → la etiqueta trae el PESO (valor/1000, 5 decimales); 'precio' → trae el precio CON IVA:
  /// cantidad = (precio ÷ (1 + IVA)) ÷ precio del nivel de la estación (si no, el 1), a 3 decimales.
  /// → null (no es de romana) · {error} · {articulo, cantidad, tipo, valor}
  Map<String, dynamic>? romanaLeer(String codigo) {
    codigo = codigo.trim();
    if (!RegExp(r'^\d+$').hasMatch(codigo) || codigo.length < 8) return null;
    final cfg = romana;
    if (cfg == null) return null;
    final ci = _n(cfg['pos_codigo_ini']).toInt(),
        cf = _n(cfg['pos_codigo_fin']).toInt();
    final vi = _n(cfg['pos_valor_ini']).toInt(),
        vf = _n(cfg['pos_valor_fin']).toInt();
    if (codigo.length < (cf > vf ? cf : vf)) return null;
    if (ci < 1 || vi < 1 || cf < ci || vf < vi) return null;
    final codArt = codigo.substring(ci - 1, cf);
    final valor = int.tryParse(codigo.substring(vi - 1, vf)) ?? 0;
    if (codArt.isEmpty || valor <= 0 || codArt == codigo) return null;
    final art = articuloExacto(codArt);
    if (art == null) return null;
    if (_t(cfg['tipo']) == 'precio') {
      final nivel = _n(estacion['tipo_precio']).toInt() > 0
          ? _n(estacion['tipo_precio']).toInt()
          : 1;
      final lista = precios(_t(art['codigo']));
      final fila =
          lista
              .where(
                (x) => _n(x['numero']).toInt() == nivel && _n(x['precio']) > 0,
              )
              .firstOrNull ??
          lista.where((x) => _n(x['numero']).toInt() == 1).firstOrNull;
      var base = fila == null ? 0.0 : _n(fila['precio']);
      if (fila != null &&
          _t(fila['moneda']).isNotEmpty &&
          _t(fila['moneda']) != 'CRC') {
        final tc = tipoCambio(_t(fila['moneda']));
        base = tc > 0 ? base * tc : 0;
      }
      if (!(base > 0))
        return {
          'error':
              'Romana por precio: «${_t(art['nombre'])}» no tiene precio configurado',
        };
      final iva = _n(art['tarifa_iva']);
      final sinIva = iva > 0 ? valor / (1 + iva / 100) : valor.toDouble();
      return {
        'articulo': art,
        'cantidad': ((sinIva / base) * 1000).roundToDouble() / 1000,
        'tipo': 'precio',
        'valor': valor,
      };
    }
    return {
      'articulo': art,
      'cantidad': ((valor / 1000) * 100000).roundToDouble() / 100000,
      'tipo': 'cantidad',
      'valor': valor,
    };
  }

  /// La config de la romana recién guardada en el servidor queda también en la copia del equipo.
  void romanaPoner(Map<String, dynamic> c) => catalogos['romana'] = [c];

  /// Niveles de precio de la empresa (P1, P2…).
  List<int> get nivelesPrecio {
    final n = _filas(
      catalogos['niveles_precio'],
    ).map((x) => _n(x['numero']).toInt()).toList()..sort();
    return n.isEmpty ? [1] : n;
  }

  /// Tarifas de IVA (código, nombre, %), de menor a mayor.
  List<Map<String, dynamic>> get tarifasIva =>
      _filas(catalogos['tarifas_iva'])..sort((a, b) {
        final c = _n(a['porcentaje']).compareTo(_n(b['porcentaje']));
        return c != 0 ? c : _t(a['codigo']).compareTo(_t(b['codigo']));
      });

  Map<String, dynamic>? cliente(String codigo) =>
      clientes[codigo.trim().toUpperCase()];

  String actividadCliente(String codigo) {
    final l = _filas(catalogos['actividades_cliente'])
        .where((a) => _t(a['cliente']).toUpperCase() == codigo.toUpperCase())
        .toList();
    final p =
        l.where((a) => _n(a['predeterminada']) == 1).firstOrNull ??
        l.firstOrNull;
    return _t(p?['actividad']);
  }

  /// Nombre de un usuario de la lista local.
  String nombreUsuario(String codigo) {
    for (final u in _filas(catalogos['usuarios'])) {
      if (_t(u['usuario']) == codigo) return _t(u['nombre']);
    }
    return codigo;
  }

  static double redondeo(double n, int d) => redondear(n, d);
}

class MedioPago {
  final String codigo, descripcion;
  final List<String> cuentas = [];
  MedioPago(this.codigo, this.descripcion);
}
