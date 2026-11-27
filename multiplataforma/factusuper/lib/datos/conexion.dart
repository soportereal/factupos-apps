/// Conexión con FactuPOS (#3957). La app solo conoce las dos direcciones públicas y la LLAVE de la empresa:
/// la empresa, su servidor y su base los resuelve el servidor desde la llave (dbcontrol `factusuper_tokens`),
/// y la estación sale del cajero. No hay servidor, base ni clave de SQL en el equipo.
///
///  · `Authorization: Bearer fs1.…`  → la empresa (la llave de CF-027 › Tokens).
///  · `X-FS-Cajero: <código>`         → quién hace la operación (la llave no define el usuario). Revisar la llave y
///    bajar la copia van SIN cajero (#3957): el cajero se elige después, en la entrada de la caja.
/// La llave solo abre las APIs de FactuSuper (FST_RUTAS en functions/facturacion/factusuper/factusuper_token.php).
///
/// 🔑 DOS DOMINIOS, cada uno por su internet (dueño, 25-nov-2026: «debería rotar entre los dos dominios… si un dominio
///    o una IP pública se cae, que entre por la otra»): invefacon.com (Metrocom) e invefacon.net (Kolbi). Si uno no
///    contesta, se reintenta el MISMO pedido por el otro y la app se queda con el que funcionó.
///    🪤 NO factupos.com: desde internet ese nombre es la página de AWS y las APIs dan 404 (pasó en la primera prueba).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

const List<String> servidoresFactuPOS = [
  'https://invefacon.com',
  'https://invefacon.net',
];
const String _api = '/apis/shared/venta/factusuper/';

/// Por cuál dominio se entró la última vez (compartido por toda la app): el próximo pedido arranca por ahí.
int _preferido = 0;

/// Formato de la llave de la empresa (el mismo que revisa la web).
final RegExp formatoLlave = RegExp(r'^fs1\.[0-9a-f]{64}$');

/// Un error que se le puede mostrar al cajero tal cual.
class ErrorConexion implements Exception {
  final String mensaje;

  /// true = no hubo respuesta del servidor (sin internet): la venta queda en cola, no se pierde.
  final bool sinInternet;

  /// 401 del guard: llave anulada, cajero no válido, etc. (`reason` del servidor).
  final String? motivo;
  const ErrorConexion(this.mensaje, {this.sinInternet = false, this.motivo});
  @override
  String toString() => mensaje;
}

/// Este dominio no sirve ahora: se prueba el otro.
class _DominioCaido implements Exception {
  final String porque;
  const _DominioCaido(this.porque);
}

class Conexion {
  final String llave;
  String cajero;
  final List<String> servidores;
  final http.Client _cliente;
  Conexion({
    required this.llave,
    this.cajero = '',
    this.servidores = servidoresFactuPOS,
    http.Client? cliente,
  }) : _cliente = cliente ?? conexionClientePrueba?.call() ?? http.Client();

  /// La sesión del servidor (cookie FSSID), una por dominio: así no se arma una nueva en cada pedido.
  final Map<String, String> _cookies = {};

  Map<String, String> _cabeceras(String base) => {
    'Authorization': 'Bearer $llave',
    if (cajero.isNotEmpty) 'X-FS-Cajero': cajero,
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': 'application/json',
    'User-Agent': 'FactuSuper-App/1.0',
    if (_cookies[base] != null) 'Cookie': _cookies[base]!,
  };

  Uri _uri(String base, String ruta, [Map<String, String>? q]) =>
      Uri.parse(base + (ruta.startsWith('/') ? ruta : _api + ruta))
          .replace(queryParameters: q);

  Future<Map<String, dynamic>> get(
    String ruta, {
    Map<String, String>? query,
    Duration espera = const Duration(seconds: 60),
  }) => _porDominios(
    (b) => _cliente
        .get(_uri(b, ruta, query), headers: _cabeceras(b))
        .timeout(espera),
  );

  /// 🔑 Un POST solo se reintenta por el otro dominio si NO llegó al servidor (conexión rechazada / nombre que no
  ///    resuelve). Si se cortó a media espera, puede haber llegado: lo resuelve el transaccionId de la venta, no esto.
  Future<Map<String, dynamic>> post(
    String ruta,
    Object cuerpo, {
    Duration espera = const Duration(seconds: 90),
  }) => _porDominios(
    (b) => _cliente
        .post(
          _uri(b, ruta),
          headers: {..._cabeceras(b), 'Content-Type': 'application/json'},
          body: jsonEncode(cuerpo),
        )
        .timeout(espera),
    esPost: true,
  );

  /// POST como formulario (los APIs de FactuDesk que leen `$_POST`, ej. cierre_contabilizar.php).
  Future<Map<String, dynamic>> postForm(
    String ruta,
    Map<String, String> campos, {
    Duration espera = const Duration(seconds: 90),
  }) => _porDominios(
    (b) => _cliente
        .post(
          _uri(b, ruta),
          headers: {
            ..._cabeceras(b),
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: campos,
        )
        .timeout(espera),
    esPost: true,
  );

  Future<Map<String, dynamic>> _porDominios(
    Future<http.Response> Function(String base) hacer, {
    bool esPost = false,
  }) async {
    final n = servidores.length;
    final inicio = _preferido % n;
    String ultimo = '';
    for (var i = 0; i < n; i++) {
      final k = (inicio + i) % n;
      final base = servidores[k];
      try {
        final j = await _pedir(base, () => hacer(base), esPost: esPost);
        _preferido = k;
        return j;
      } on _DominioCaido catch (e) {
        ultimo = e.porque;
      }
    }
    throw ErrorConexion(
      ultimo.isEmpty ? 'Sin conexión con el servidor' : ultimo,
      sinInternet: true,
    );
  }

  Future<Map<String, dynamic>> _pedir(
    String base,
    Future<http.Response> Function() hacer, {
    required bool esPost,
  }) async {
    http.Response r;
    try {
      r = await hacer();
    } on SocketException {
      throw const _DominioCaido('Sin conexión con el servidor');
    } on TimeoutException {
      // motivo 'tiempo': pudo LLEGAR (el servidor puede estar facturando): no cuenta como «sin red» para el provisional.
      if (esPost) {
        throw const ErrorConexion(
          'El servidor no contestó a tiempo',
          sinInternet: true,
          motivo: 'tiempo',
        );
      }
      throw const _DominioCaido('El servidor no contestó a tiempo');
    } on http.ClientException {
      throw const _DominioCaido('Sin conexión con el servidor');
    } on HandshakeException {
      throw const _DominioCaido(
        'No se pudo abrir la conexión segura con el servidor',
      );
    }
    // La entrada de ese internet está caída (el balanceador no tiene a quién pasarle el pedido): por el otro.
    if (r.statusCode == 502 || r.statusCode == 503 || r.statusCode == 504) {
      throw _DominioCaido(
        'El servidor no está disponible (HTTP ${r.statusCode})',
      );
    }
    final galleta = r.headers['set-cookie'];
    if (galleta != null) {
      final m = RegExp(r'(FSSID=[^;]+)').firstMatch(galleta);
      if (m != null) _cookies[base] = m.group(1)!;
    }
    Map<String, dynamic>? j;
    try {
      final d = jsonDecode(utf8.decode(r.bodyBytes));
      if (d is Map<String, dynamic>) j = d;
    } catch (_) {}
    if (r.statusCode == 401 || r.statusCode == 403) {
      throw ErrorConexion(
        (j?['mensaje'] ?? j?['error'] ?? 'La llave no es válida o fue anulada')
            .toString(),
        motivo: (j?['reason'] ?? 'http${r.statusCode}').toString(),
      );
    }
    if (j == null)
      throw ErrorConexion(
        'Respuesta no válida del servidor (HTTP ${r.statusCode})',
      );
    if (r.statusCode >= 500 && j['estado'] == null) {
      throw ErrorConexion(
        (j['mensaje'] ??
                j['error'] ??
                'Error del servidor (HTTP ${r.statusCode})')
            .toString(),
      );
    }
    return j;
  }

  void cerrar() => _cliente.close();
}

/// A qué conecta la llave (`token_info.php`): empresa, nombre, estación y cajero.
class InfoLlave {
  final String empresa,
      empresaNombre,
      estacionId,
      estacionNombre,
      cajeroCodigo,
      cajeroNombre;
  const InfoLlave(
    this.empresa,
    this.empresaNombre,
    this.estacionId,
    this.estacionNombre,
    this.cajeroCodigo,
    this.cajeroNombre,
  );

  factory InfoLlave.desde(Map<String, dynamic> j) {
    final e = (j['estacion'] as Map?) ?? const {},
        c = (j['cajero'] as Map?) ?? const {};
    return InfoLlave(
      '${j['empresa'] ?? ''}',
      '${j['empresaNombre'] ?? ''}',
      '${e['id'] ?? ''}',
      '${e['nombre'] ?? ''}',
      '${c['codigo'] ?? ''}',
      '${c['nombre'] ?? ''}',
    );
  }
}

/// Revisa una llave pegada en Configuración. Con SOLO la llave (dueño: «solo debería pedir la llave de la empresa»):
/// el usuario se elige después, de la lista, en la entrada de la caja.
/// SOLO para las pruebas (capturas): si está puesto, cada Conexion nueva usa este cliente en vez de salir a la red.
http.Client Function()? conexionClientePrueba;

Future<InfoLlave> revisarLlave(String llave, {http.Client? cliente}) async {
  llave = llave.trim();
  if (!formatoLlave.hasMatch(llave)) {
    throw const ErrorConexion(
      'La llave no tiene el formato correcto: empieza con «fs1.» y sigue con 64 letras y números',
    );
  }
  final c = Conexion(llave: llave, cliente: cliente);
  try {
    final j = await c.get('token_info.php');
    if (j['ok'] != true)
      throw ErrorConexion(
        (j['mensaje'] ?? 'La llave no es válida o fue anulada').toString(),
      );
    return InfoLlave.desde(j);
  } on ErrorConexion catch (e) {
    if (e.motivo == 'cajero_invalido') {
      throw const ErrorConexion(
        'La llave no tiene un usuario activo con permiso de facturar para abrirla. '
        'Entre una vez a FactuSuper web con un cajero, o regenere la llave en Configuración › Tokens.',
      );
    }
    rethrow;
  } finally {
    c.cerrar();
  }
}
