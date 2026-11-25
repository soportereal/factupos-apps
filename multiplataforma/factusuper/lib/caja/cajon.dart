/// Abrir el CAJÓN (#3957) — réplica de FSCajon (factusuper_cajon.js), también SIN internet:
///   · permiso 141 o la clave de un supervisor que lo tenga (en el equipo);
///   · con internet → el API de FactuDesk (apis/shared/impresion/cajon_abrir.php): pulso + comprobante «CAJON ABIERTO»;
///   · sin internet → los MISMOS bytes a FactuPOS Print del equipo (127.0.0.1:9302), a la cola de CONTADO de la estación,
///     y la apertura queda anotada y sube a la bitácora (cajon_bitacora.php) cuando vuelve la red, con su hora real.
///   🪤 cajon_abrir.php NO está en FST_RUTAS: con la LLAVE el servidor contesta 403 «token_fuera_de_factusuper». La web
///      se queda en ese error; la app, en ese caso, también lo abre por el equipo (decisión anotada en la memoria del caso).
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import '../datos/almacen.dart';
import '../datos/conexion.dart';
import 'datos_caja.dart';

const String puertoPrint = 'http://127.0.0.1:9302';

String _dos(int n) => n.toString().padLeft(2, '0');

/// Sin tildes (la térmica no recibe UTF-8), como el PHP.
String sinTildes(String s) {
  const de = 'áéíóúÁÉÍÓÚñÑüÜ', a = 'aeiouAEIOUnNuU';
  final b = StringBuffer();
  for (final ch in s.split('')) {
    final i = de.indexOf(ch);
    b.write(i >= 0 ? a[i] : ch);
  }
  return b.toString();
}

/// Los mismos bytes que cajon_abrir.php: ESC p 0 25 250 + «CAJON ABIERTO» + corte, en UN solo trabajo.
String comandoCajon(
  String estacionId,
  String usuario,
  String autoriza,
  DateTime ahora,
) {
  const lf = '\n',
      cen = '\x1B\x61\x01',
      izq = '\x1B\x61\x00',
      non = '\x1B\x45\x01',
      noff = '\x1B\x45\x00';
  const gon = '\x1D\x21\x11', goff = '\x1D\x21\x00', corte = '\x1D\x56\x01';
  final momento =
      '${_dos(ahora.day)}/${_dos(ahora.month)}/${ahora.year} ${_dos(ahora.hour)}:${_dos(ahora.minute)}';
  var t = '$cen$non${gon}CAJON ABIERTO$lf$goff$noff';
  t += '$cen$momento$lf$izq';
  if (usuario.isNotEmpty) t += 'Usuario : $usuario$lf';
  t += 'Estacion: $estacionId$lf';
  if (autoriza.isNotEmpty) t += 'Autoriza: $autoriza$lf';
  t += lf * 3 + corte;
  return '\x1B\x70\x00\x19\xFA$t';
}

/// Texto → base64 de sus bytes latin-1 (lo que no entre sale «?»).
String base64Latin1(String texto) =>
    base64Encode([for (final c in texto.runes) c < 256 ? c : 63]);

/// Empresa como la nombra la cola de impresión: minúsculas, solo letras y números.
String empresaCola(String empresa) =>
    empresa.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]'), '');

/// Manda un trabajo crudo a FactuPOS Print del equipo. → '' si salió, o el error.
Future<String> alPuerto(
  String cola,
  String empresa,
  String texto,
  String jobId, {
  http.Client? cliente,
}) async {
  final c = cliente ?? http.Client();
  try {
    final r = await c
        .post(
          Uri.parse('$puertoPrint/print'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'queue': cola,
            'empresa': empresaCola(empresa),
            'data': base64Latin1(texto),
            'jobId': jobId,
          }),
        )
        .timeout(const Duration(seconds: 30));
    final j = jsonDecode(r.body);
    return j is Map && j['ok'] == true
        ? ''
        : '${(j is Map ? j['mensaje'] : null) ?? 'FactuPOS Print respondió ${r.statusCode}'}';
  } catch (_) {
    return 'FactuPOS Print no responde en este equipo (¿está abierto y en la versión 4.54 o más?)';
  } finally {
    if (cliente == null) c.close();
  }
}

class Cajon {
  final Almacen almacen;
  final ConfigCaja config;
  final DatosCaja datos;
  Cajon(this.almacen, this.config, this.datos);

  Future<List<Map<String, dynamic>>> pendientes() async {
    final v = await almacen.leerTabla(config.empresa, 'cajon_pendientes');
    return v is List
        ? [
            for (final x in v)
              if (x is Map) Map<String, dynamic>.from(x),
          ]
        : <Map<String, dynamic>>[];
  }

  /// → (ok, por dónde, error). [usuario] = «código nombre» de quien abre; [autoriza] = nombre del supervisor.
  Future<(bool, String, String)> abrir({
    required String cajero,
    required String usuario,
    String autoriza = '',
  }) async {
    final con = Conexion(llave: config.llave, cajero: cajero);
    try {
      final j = await con.post('/apis/shared/impresion/cajon_abrir.php', {
        'modulo': 'FactuSuper',
      });
      return (
        j['success'] == true,
        'servidor',
        j['success'] == true
            ? ''
            : '${j['error'] ?? 'No se pudo abrir el cajón'}',
      );
    } on ErrorConexion catch (e) {
      if (!e.sinInternet && e.motivo != 'token_fuera_de_factusuper')
        return (false, 'servidor', e.mensaje);
    } finally {
      con.cerrar();
    }
    return _abrirLocal(usuario, autoriza, cajero);
  }

  Future<(bool, String, String)> _abrirLocal(
    String usuario,
    String autoriza,
    String cajero,
  ) async {
    final est = datos.estacion;
    final cfg = ((est['impresion'] as Map?)?['contado'] as Map?) ?? const {};
    final ahora = DateTime.now();
    final suc = '${datos.idProcesoServidor['sucursal'] ?? '001'}'
        .replaceAll(RegExp(r'\D'), '')
        .padLeft(3, '0');
    final caja = '${est['caja'] ?? datos.idProcesoServidor['caja'] ?? '1'}'
        .replaceAll(RegExp(r'\D'), '')
        .padLeft(2, '0');
    final usu = cajero.replaceAll(RegExp(r'\D'), '').padLeft(5, '0');
    final ap = <String, dynamic>{
      'aperturaId': '${ahora.microsecondsSinceEpoch}',
      'idProceso':
          'A-${caja.substring(caja.length - 2)}-${suc.substring(suc.length - 3)}-${usu.substring(usu.length - 5)}-${_dos(ahora.hour)}${_dos(ahora.minute)}${_dos(ahora.second)}-${_dos(ahora.day)}',
      'fecha': ahora.toUtc().toIso8601String(),
      'estacion': '${est['id'] ?? ''}',
      'impresora': '${cfg['impresora'] ?? '301'}',
      'autoriza': autoriza,
    };
    String error;
    final ruta = int.tryParse('${cfg['ruta'] ?? 4}') ?? 4;
    if (ruta != 4) {
      error = 'Sin internet el cajón solo se abre con FactuPOS Print (ruta 4 de la estación).';
    } else {
      error = await alPuerto(
        '${ap['impresora']}',
        config.empresa,
        comandoCajon(
          '${ap['estacion']}',
          sinTildes(usuario),
          sinTildes(autoriza),
          ahora,
        ),
        'cajon-${ap['aperturaId']}',
      );
    }
    ap['ok'] = error.isEmpty;
    ap['error'] = error;
    final lista = await pendientes()
      ..add(ap);
    await almacen.guardarTabla(config.empresa, 'cajon_pendientes', lista);
    return (error.isEmpty, 'equipo', error);
  }

  /// Sube a la bitácora las aperturas hechas sin internet (antes que las ventas, por su orden).
  Future<bool> subirPendientes(String cajero) async {
    var lista = await pendientes();
    for (final ap in [...lista]) {
      final con = Conexion(llave: config.llave, cajero: cajero);
      Map<String, dynamic> j;
      try {
        j = await con.post('cajon_bitacora.php', ap);
      } catch (_) {
        return false;
      } finally {
        con.cerrar();
      }
      if (j['estado'] == 'error') return false;
      lista = lista.where((x) => x['aperturaId'] != ap['aperturaId']).toList();
      await almacen.guardarTabla(config.empresa, 'cajon_pendientes', lista);
    }
    return true;
  }
}
