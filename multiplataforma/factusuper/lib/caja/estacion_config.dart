/// CONFIGURACIÓN DE LA ESTACIÓN (CF-006 de la web, `EstacionConfig.abrir`) desde la app (#3957): bodega, caja, tipo de
/// precio e impresoras (número · formato · ancho de papel; la ruta solo si hoy es Bluetooth/Bridge, como la web).
/// 🔑 Solo la estación del CAJERO (la de la sesión) y solo su configuración — `apis/shared/venta/factusuper/estacion_config.php`,
///    que revisa en el SERVIDOR el 130 (o el 840 para la propia) y valida con las mismas funciones de la web.
///    Necesita internet: es configuración de la empresa, no se guarda en el equipo.
library;

import '../datos/conexion.dart';
import '../datos/almacen.dart';

const rutaEstacionConfig = '/apis/shared/venta/factusuper/estacion_config.php';
const sinRedEstacion =
    'Sin internet: la configuración de la estación se guarda en el servidor. Pruebe cuando vuelva la conexión.';

/// Una impresora del formulario (como `impresora()` de estacion_form.js).
class ImpresoraEst {
  final String clave, titulo, ayuda, num, ancho, ruta;
  final String? formato;
  final int anchoDef;
  const ImpresoraEst(
    this.clave,
    this.titulo,
    this.ayuda,
    this.num,
    this.formato,
    this.ancho,
    this.anchoDef,
    this.ruta,
  );
}

const impresorasEstacion = [
  ImpresoraEst(
    'fac',
    'Factura',
    'Impresora de facturas',
    'ImpContadoNum',
    'ImpContadoFormato',
    'ImpContadoAnchoPapel',
    48,
    'ImpContadoRuta',
  ),
  ImpresoraEst(
    'cre',
    'Crédito',
    'Impresora de crédito',
    'ImpCreditoNum',
    'ImpCreditoFormato',
    'ImpCreditoAncho',
    48,
    'ImpCreditoRuta',
  ),
  ImpresoraEst(
    'cot',
    'Cotización',
    'Impresora de cotizaciones',
    'ImpCotizaNum',
    'ImpCotizaFormato',
    'ImpCotizaAncho',
    48,
    'ImpCotizaRuta',
  ),
  ImpresoraEst(
    'com',
    'Comprobantes',
    'Impresora de comprobantes (recibos, notas, etc.)',
    'ImpCompNum',
    null,
    'ImpCompAncho',
    40,
    'ImpCompRuta',
  ),
];

class Opcion {
  final String cod, txt, grupo;
  const Opcion(this.cod, this.txt, [this.grupo = '']);
}

/// Lo que trae el servidor: la fila de la estación, sus usuarios, qué puede hacer quien la abre y las listas.
class DatosEstacion {
  final int id;
  final Map<String, dynamic> fila;
  final List<Map<String, dynamic>> usuarios;
  final bool puedeGuardar;
  final Map<String, List<Opcion>> listas;
  DatosEstacion(
    this.id,
    this.fila,
    this.usuarios,
    this.puedeGuardar,
    this.listas,
  );

  factory DatosEstacion.desde(Map<String, dynamic> j) {
    final d = Map<String, dynamic>.from(j['data'] as Map? ?? const {});
    final l = (j['listas'] as Map?) ?? const {};
    List<Opcion> ops(String k, String Function(Map) txt) => [
      for (final x in (l[k] as List? ?? const []))
        if (x is Map) Opcion('${x['cod']}', txt(x)),
    ];
    return DatosEstacion(
      (j['id'] as num?)?.toInt() ?? 0,
      d,
      [
        for (final u in (d['usuarios'] as List? ?? const []))
          if (u is Map) Map<String, dynamic>.from(u),
      ],
      ((j['permisos'] as Map?)?['guardar']) == true,
      {
        'BodegaCodigo': ops('bodegas', (x) => '${x['cod']} - ${x['nom']}'),
        'Caja': ops('cajas', (x) => '${x['cod']} - ${x['nom']}'),
        'TipoPrecio': ops('precios', (x) => '${x['nom']}'),
        'ancho': ops('anchos', (x) => '${x['nom']}'),
        'formato': [
          for (final f in (l['formatos'] as List? ?? const []))
            if (f is Map)
              Opcion(
                '${f['codigo']}',
                '${f['codigo']} - ${f['nombre']}',
                '${f['grupo'] ?? ''}${f['soloCotizacion'] == true ? '|cot' : ''}',
              ),
        ],
      },
    );
  }

  /// Las opciones de un campo (los formatos «solo cotización» solo en la impresora de cotizaciones).
  List<Opcion> opciones(String campo) {
    if (campo.contains('Ancho')) return listas['ancho']!;
    if (campo.contains('Formato')) {
      final cot = campo == 'ImpCotizaFormato';
      return [
        for (final o in listas['formato']!)
          if (cot || !o.grupo.endsWith('|cot'))
            Opcion(o.cod, o.txt, o.grupo.replaceAll('|cot', '')),
      ];
    }
    return listas[campo] ?? const [];
  }

  /// El valor inicial del formulario (como `combo()`: formatos en mayúscula, FIPVIVI002 por defecto; número 1–999 o 301).
  static String valorInicial(String campo, Object? v, {int anchoDef = 48}) {
    final s = v == null ? '' : '$v'.trim();
    if (campo.contains('Formato'))
      return s.isEmpty ? 'FIPVIVI002' : s.toUpperCase();
    if (campo.endsWith('Num')) {
      final n = int.tryParse(s);
      return (n != null && n >= 1 && n <= 999) ? '$n' : '301';
    }
    if (campo.contains('Ancho')) return s.isEmpty ? '$anchoDef' : s;
    if (campo.endsWith('Ruta')) {
      final n = int.tryParse(s);
      return (n == 2 || n == 3) ? '$n' : '4';
    }
    return s;
  }

  /// Si lo guardado ya no está en la lista, NO se cambia en silencio: el aviso de la web.
  String? avisoFuera(String campo, String valor, String queEs) {
    final ops = opciones(campo);
    if (valor.isEmpty || ops.isEmpty || ops.any((o) => o.cod == valor)) {
      return null;
    }
    return '$queEs que tenía ($valor) ya no está en la lista. Al guardar quedará como ${ops.first.txt}; elija el que corresponda.';
  }
}

/// Valida lo que el servidor también valida, para avisar antes de mandar.
String validarEstacion(Map<String, String> v) {
  for (final i in impresorasEstacion) {
    final n = int.tryParse(v[i.num] ?? '');
    if (n == null || n < 1 || n > 999) {
      return '${i.titulo}: el número de impresora va de 1 a 999.';
    }
  }
  for (final k in const ['BodegaCodigo', 'Caja', 'TipoPrecio']) {
    if ((v[k] ?? '').isEmpty) {
      return 'Elija ${k == 'BodegaCodigo'
          ? 'la bodega'
          : k == 'Caja'
          ? 'la caja'
          : 'el tipo de precio'}.';
    }
  }
  return '';
}

class EstacionConfig {
  final ConfigCaja config;
  final String cajero;
  final List<String> servidores;
  EstacionConfig(
    this.config,
    this.cajero, {
    this.servidores = servidoresFactuPOS,
  });

  Conexion _con() =>
      Conexion(llave: config.llave, cajero: cajero, servidores: servidores);

  Future<(DatosEstacion?, String)> cargar() async {
    final con = _con();
    try {
      final j = await con.get(rutaEstacionConfig);
      if (j['success'] != true) {
        return (null, '${j['message'] ?? 'No se pudo cargar la estación'}');
      }
      return (DatosEstacion.desde(j), '');
    } on ErrorConexion catch (e) {
      return (null, e.sinInternet ? sinRedEstacion : e.mensaje);
    } finally {
      con.cerrar();
    }
  }

  /// → ('', config guardada) o (error, null).
  Future<(String, Map<String, dynamic>?)> guardar(
    Map<String, String> valores,
  ) async {
    final e = validarEstacion(valores);
    if (e.isNotEmpty) return (e, null);
    final con = _con();
    try {
      final j = await con.post(rutaEstacionConfig, valores);
      if (j['success'] != true) {
        return ('${j['message'] ?? 'No se pudo guardar'}', null);
      }
      return ('', Map<String, dynamic>.from(j['config'] as Map? ?? const {}));
    } on ErrorConexion catch (e) {
      return (e.sinInternet ? sinRedEstacion : e.mensaje, null);
    } finally {
      con.cerrar();
    }
  }
}
