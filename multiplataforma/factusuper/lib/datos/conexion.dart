/// Conexión con FactuPOS (#3957). La app solo conoce UNA dirección fija y la LLAVE de la empresa:
/// la empresa, su servidor y su base los resuelve el servidor desde la llave (dbcontrol `factusuper_tokens`),
/// y la estación sale del cajero. No hay servidor, base ni clave de SQL en el equipo.
///
///  · `Authorization: Bearer fs1.…`  → la empresa (la llave de CF-027 › Tokens).
///  · `X-FS-Cajero: <código>`         → quién hace la operación (la llave no define el usuario).
/// La llave solo abre las APIs de FactuSuper (FST_RUTAS en functions/facturacion/factusuper/factusuper_token.php).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

const String servidorFactuPOS = 'https://factupos.com';
const String _api = '/apis/shared/venta/factusuper/';

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

class Conexion {
  final String llave;
  String cajero;
  final String servidor;
  final http.Client _cliente;
  Conexion({required this.llave, required this.cajero, this.servidor = servidorFactuPOS, http.Client? cliente})
      : _cliente = cliente ?? http.Client();

  /// La sesión del servidor (cookie FSSID) se reutiliza entre pedidos: así no se arma una nueva cada vez.
  String? _cookie;

  Map<String, String> get _cabeceras => {
        'Authorization': 'Bearer $llave',
        if (cajero.isNotEmpty) 'X-FS-Cajero': cajero,
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
        'User-Agent': 'FactuSuper-App/1.0',
        if (_cookie != null) 'Cookie': _cookie!,
      };

  Uri _uri(String ruta, [Map<String, String>? q]) =>
      Uri.parse(servidor + (ruta.startsWith('/') ? ruta : _api + ruta)).replace(queryParameters: q);

  Future<Map<String, dynamic>> get(String ruta, {Map<String, String>? query, Duration espera = const Duration(seconds: 60)}) =>
      _pedir(() => _cliente.get(_uri(ruta, query), headers: _cabeceras).timeout(espera));

  Future<Map<String, dynamic>> post(String ruta, Object cuerpo, {Duration espera = const Duration(seconds: 90)}) => _pedir(() =>
      _cliente.post(_uri(ruta), headers: {..._cabeceras, 'Content-Type': 'application/json'}, body: jsonEncode(cuerpo)).timeout(espera));

  Future<Map<String, dynamic>> _pedir(Future<http.Response> Function() hacer) async {
    http.Response r;
    try {
      r = await hacer();
    } on SocketException {
      throw const ErrorConexion('Sin conexión con el servidor', sinInternet: true);
    } on TimeoutException {
      throw const ErrorConexion('El servidor no contestó a tiempo', sinInternet: true);
    } on http.ClientException {
      throw const ErrorConexion('Sin conexión con el servidor', sinInternet: true);
    }
    final galleta = r.headers['set-cookie'];
    if (galleta != null) {
      final m = RegExp(r'(FSSID=[^;]+)').firstMatch(galleta);
      if (m != null) _cookie = m.group(1);
    }
    Map<String, dynamic>? j;
    try {
      final d = jsonDecode(utf8.decode(r.bodyBytes));
      if (d is Map<String, dynamic>) j = d;
    } catch (_) {}
    if (r.statusCode == 401 || r.statusCode == 403) {
      throw ErrorConexion(
        (j?['mensaje'] ?? j?['error'] ?? 'La llave no es válida o fue anulada').toString(),
        motivo: (j?['reason'] ?? 'http${r.statusCode}').toString(),
      );
    }
    if (j == null) throw ErrorConexion('Respuesta no válida del servidor (HTTP ${r.statusCode})');
    if (r.statusCode >= 500 && j['estado'] == null) {
      throw ErrorConexion((j['mensaje'] ?? j['error'] ?? 'Error del servidor (HTTP ${r.statusCode})').toString());
    }
    return j;
  }

  void cerrar() => _cliente.close();
}

/// A qué conecta la llave (`token_info.php`): empresa, nombre, estación y cajero.
class InfoLlave {
  final String empresa, empresaNombre, estacionId, estacionNombre, cajeroCodigo, cajeroNombre;
  const InfoLlave(this.empresa, this.empresaNombre, this.estacionId, this.estacionNombre, this.cajeroCodigo, this.cajeroNombre);

  factory InfoLlave.desde(Map<String, dynamic> j) {
    final e = (j['estacion'] as Map?) ?? const {}, c = (j['cajero'] as Map?) ?? const {};
    return InfoLlave('${j['empresa'] ?? ''}', '${j['empresaNombre'] ?? ''}', '${e['id'] ?? ''}', '${e['nombre'] ?? ''}',
        '${c['codigo'] ?? ''}', '${c['nombre'] ?? ''}');
  }
}

/// Revisa una llave pegada en Configuración. El servidor exige un cajero para armar la sesión: se usa el
/// código del usuario que está configurando la caja (activo y con permiso de facturar, 653).
Future<InfoLlave> revisarLlave(String llave, String usuario, {http.Client? cliente}) async {
  llave = llave.trim();
  usuario = usuario.trim();
  if (!formatoLlave.hasMatch(llave)) {
    throw const ErrorConexion('La llave no tiene el formato correcto: empieza con «fs1.» y sigue con 64 letras y números');
  }
  if (usuario.isEmpty) throw const ErrorConexion('Escriba su código de usuario de FactuPOS');
  final c = Conexion(llave: llave, cajero: usuario, cliente: cliente);
  try {
    final j = await c.get('token_info.php');
    if (j['ok'] != true) throw ErrorConexion((j['mensaje'] ?? 'La llave no es válida o fue anulada').toString());
    return InfoLlave.desde(j);
  } on ErrorConexion catch (e) {
    if (e.motivo == 'cajero_invalido') {
      throw const ErrorConexion('Ese usuario no está activo en la empresa de la llave o no tiene permiso para facturar (653)');
    }
    rethrow;
  } finally {
    c.cerrar();
  }
}
