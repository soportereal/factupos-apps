/// INGRESO (FCA) y RETIRO (SCA) de fondo de caja (#3957) — réplica de FSFondo (factusuper_fondo.js, MV-112).
///
/// 🔑 Dueño (27-sep-2026): «los ingresos o retiros son en TIEMPO REAL, no funcionan si no hay internet». Se manda YA a
///    fondo_procesar.php, que arma el MISMO asiento que FactuDesk (FCA: DEBE 83 / HABER 243 · SCA: DEBE 243 / HABER 83),
///    imprime el comprobante y abre el cajón de contado. Sin red no se guarda nada (ni cola ni provisional): la ventana
///    queda abierta para reintentar. Sin permisos, como FactuDesk.
///  · El ID «F-caja-sucursal-usuario-hhmmss-día» hace idempotente el envío: si se repite, el servidor contesta el mismo
///    documento y no escribe otro asiento.
///  · Rutas 2/3 de la estación: el servidor devuelve el comprobante y lo imprime ESTE equipo (por FactuPOS Print).
library;

import '../datos/almacen.dart';
import '../datos/conexion.dart';
import 'cajon.dart';
import 'datos_caja.dart';
import 'registro.dart';

class TipoFondo {
  final String codigo, titulo, detalle;
  final int debe, haber;
  const TipoFondo(
    this.codigo,
    this.titulo,
    this.detalle,
    this.debe,
    this.haber,
  );
}

const tiposFondo = {
  'FCA': TipoFondo(
    'FCA',
    'Ingreso de fondo de caja',
    'Ingreso fondo de caja',
    83,
    243,
  ),
  'SCA': TipoFondo(
    'SCA',
    'Retiro de fondo de caja',
    'Retiro fondo de caja',
    243,
    83,
  ),
};

const sinRedFondo =
    'Sin internet: el ingreso o retiro de fondo necesita conexión. Intente de nuevo cuando vuelva la red.';

String _dos(int n) => n.toString().padLeft(2, '0');

/// Fecha con la zona del equipo (isoLocal de la web): el dinero entró o salió ESE día.
String isoLocal(DateTime d) {
  final z = d.timeZoneOffset.inMinutes;
  final a = z.abs();
  return '${d.year}-${_dos(d.month)}-${_dos(d.day)}T${_dos(d.hour)}:${_dos(d.minute)}:${_dos(d.second)}'
      '${z >= 0 ? '+' : '-'}${_dos(a ~/ 60)}:${_dos(a % 60)}';
}

/// caja-sucursal-usuario-hhmmss-día (FSLocal.idControl).
String idControl(DatosCaja datos, String usuario, DateTime cuando) {
  String ult(String s, int n) {
    final x = s.replaceAll(RegExp(r'\D'), '').padLeft(n, '0');
    return x.substring(x.length - n);
  }

  final srv = datos.idProcesoServidor, est = datos.estacion;
  String t(Object? v) => '${v ?? ''}'.trim();
  final suc = ult(t(srv['sucursal']).isEmpty ? '001' : t(srv['sucursal']), 3);
  final caja = ult(
    t(est['caja']).isNotEmpty
        ? t(est['caja'])
        : (t(srv['caja']).isEmpty ? '1' : t(srv['caja'])),
    2,
  );
  final usu = ult(usuario.isEmpty ? '0' : usuario, 5);
  return '$caja-$suc-$usu-${_dos(cuando.hour)}${_dos(cuando.minute)}${_dos(cuando.second)}-${_dos(cuando.day)}';
}

class ResultadoFondo {
  final bool ok;
  final String mensaje, documento;
  final double monto;

  /// El comprobante no salió (el fondo SÍ quedó registrado).
  final String errorImpresion;
  const ResultadoFondo(
    this.ok,
    this.mensaje, {
    this.documento = '',
    this.monto = 0,
    this.errorImpresion = '',
  });
}

class Fondos {
  final ConfigCaja config;
  final DatosCaja datos;
  final Registro? registro;

  /// Las pruebas lo cambian por un servidor de mentira.
  final List<String> servidores;
  Fondos(
    this.config,
    this.datos, {
    this.registro,
    this.servidores = servidoresFactuPOS,
  });

  /// Valida como la web; null = está bien.
  String? validar(String tipo, double monto, String detalle) {
    final t = tiposFondo[tipo];
    if (t == null) return 'Tipo de fondo no válido';
    if (!(monto > 0)) return 'Ingrese el monto';
    if (detalle.length < 2) return 'Ingrese el detalle';
    for (final n in [t.debe, t.haber]) {
      if (datos.param(n, '').isEmpty) {
        return 'Parámetro $n (${n == 83 ? 'cuenta efectivo' : 'cuenta fondo de caja'}) no configurado';
      }
    }
    return null;
  }

  /// Arma el cuerpo que manda la web (mismos campos).
  Map<String, dynamic> cuerpo(
    String tipo,
    double monto,
    String detalle,
    String usuario,
    DateTime ahora,
  ) {
    final est = datos.estacion;
    final imp = (est['impresion'] as Map?) ?? const {};
    final contado = (imp['contado'] as Map?) ?? const {};
    final comp = (imp['comprobante'] as Map?) ?? contado;
    String t(Object? v) => '${v ?? ''}'.trim();
    return {
      'fondoId': 'F-${idControl(datos, usuario, ahora)}',
      'tipo': tipo,
      'monto': (monto * 100).round() / 100,
      'detalle': detalle.trim().replaceAll(RegExp(r'\s+'), ' '),
      'fecha': isoLocal(ahora),
      'oficina': t(est['oficina']).isEmpty ? '001' : t(est['oficina']),
      'impresion': {
        'impresora': t(comp['impresora']).isEmpty
            ? '301'
            : t(comp['impresora']),
        'ruta': int.tryParse(t(comp['ruta'])) ?? 4,
        'ancho': int.tryParse(t(comp['ancho'])) ?? 0,
      },
      'cajon': t(contado['impresora']).isNotEmpty
          ? t(contado['impresora'])
          : (t(comp['impresora']).isEmpty ? '301' : t(comp['impresora'])),
    };
  }

  Future<ResultadoFondo> registrar(
    String tipo,
    double montoTexto,
    String detalle,
    String usuario, {
    DateTime? cuando,
  }) async {
    final error = validar(tipo, montoTexto, detalle.trim());
    if (error != null) return ResultadoFondo(false, error);
    final c = cuerpo(
      tipo,
      montoTexto,
      detalle,
      usuario,
      cuando ?? DateTime.now(),
    );
    final con = Conexion(
      llave: config.llave,
      cajero: usuario,
      servidores: servidores,
    );
    Map<String, dynamic> j;
    try {
      j = await con.post('fondo_procesar.php', c);
    } on ErrorConexion catch (e) {
      return ResultadoFondo(false, e.sinInternet ? sinRedFondo : e.mensaje);
    } finally {
      con.cerrar();
    }
    if (j['estado'] != 'procesado') {
      return ResultadoFondo(
        false,
        '${j['mensaje'] ?? 'El servidor no registró el fondo'}',
      );
    }
    final imp = (j['impresion'] as Map?) ?? const {};
    var errImp = imp['ok'] == false ? '${imp['error'] ?? ''}' : '';
    // Rutas 2/3: el comprobante lo imprime este equipo.
    final tiq = '${imp['tiquete'] ?? ''}';
    if (tiq.isNotEmpty) {
      final e = await alPuerto(
        '${(c['impresion'] as Map)['impresora']}',
        config.empresa,
        tiq,
        'fondo-${c['fondoId']}',
      );
      if (e.isNotEmpty) errImp = e;
    }
    await registro?.anotar(
      idProceso: '${c['fondoId']}',
      tipo: 'fondo',
      json: c,
      estado: 'procesado',
      resultado: '$tipo #${j['documento']}',
    );
    return ResultadoFondo(
      true,
      'registrado',
      documento: '${j['documento'] ?? ''}',
      monto: (c['monto'] as num).toDouble(),
      errorImpresion: errImp,
    );
  }
}
