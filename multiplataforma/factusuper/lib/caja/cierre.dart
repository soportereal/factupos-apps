/// CIERRE DE CAJA (#3957) — réplica del contador de monedas MU-001 de FactuDesk que abre FactuSuper (etapa 19).
///   · CONTAR se puede siempre (también sin internet): monedas, billetes, tarjeta, SINPE, transferencia, gastos y
///     dólares × tipo de cambio = el total contado (calcularTotal de contador_monedas.js).
///   · CONTABILIZAR cierra el asiento del cajero: primero se envía la cola y, si no queda vacía, NO se contabiliza
///     (esa venta caería en OTRO cierre). Permisos 012 (contabilizar) y 031 (imprimir) los revisa el servidor.
///   · Usa los MISMOS APIs de la web: cierre_lista_obtener · cierre_resumen_obtener · cierre_contador_guardar ·
///     cierre_contabilizar · caja_contador_monedas_imprimir.
/// 🪤 Esos APIs NO están en FST_RUTAS: con la llave contestan 403 «token_fuera_de_factusuper» (la web en modo llave
///    tampoco puede). Hasta que el dueño decida habilitarlos, la app lo dice claro en vez de fallar mudo.
library;

import '../datos/almacen.dart';
import '../datos/conexion.dart';
import '../motor/redondeo.dart';

const monedasCrc = [5, 10, 25, 50, 100, 500];
const billetesCrc = [1000, 2000, 5000, 10000, 20000, 50000];

const sinRutaCierre =
    'El cierre de caja todavía no está habilitado para la llave de FactuSuper (sus servicios no están en la lista de la llave). Use el cierre de FactuDesk mientras tanto.';

class Conteo {
  final Map<int, double> denominaciones = {
    for (final d in [...monedasCrc, ...billetesCrc]) d: 0,
  };
  double tarjeta = 0, sinpe = 0, transferencia = 0, gastos = 0, dolares = 0;
  double tipoCambio = 500;

  double get totalEfectivo => redondear(
    denominaciones.entries.fold<double>(0, (a, e) => a + e.key * e.value),
    2,
  );
  double get subMonedas => redondear(
    monedasCrc.fold<double>(0, (a, d) => a + d * (denominaciones[d] ?? 0)),
    2,
  );
  double get subBilletes => redondear(
    billetesCrc.fold<double>(0, (a, d) => a + d * (denominaciones[d] ?? 0)),
    2,
  );

  /// Un solo total: monedas + billetes + otros medios + dólares + gastos.
  double get total => redondear(
    totalEfectivo +
        tarjeta +
        sinpe +
        transferencia +
        gastos +
        dolares * (tipoCambio > 0 ? tipoCambio : 500),
    2,
  );

  Map<String, dynamic> aMapa() => {
    'denominaciones': {
      for (final e in denominaciones.entries) '${e.key}': e.value,
    },
    'dolares': dolares,
    'tipoCambio': tipoCambio > 0 ? tipoCambio : 500,
    'tarjeta': tarjeta,
    'sinpe': sinpe,
    'transferencia': transferencia,
    'gastos': gastos,
  };
}

class CierrePendiente {
  final int asiento;
  final String nombre;
  final double totalCaja;
  const CierrePendiente(this.asiento, this.nombre, this.totalCaja);
}

class CierreCaja {
  final ConfigCaja config;
  final String cajero;
  final List<String> servidores;
  CierreCaja(this.config, this.cajero, {this.servidores = servidoresFactuPOS});

  Conexion _con() =>
      Conexion(llave: config.llave, cajero: cajero, servidores: servidores);

  static String _error(ErrorConexion e) =>
      e.motivo == 'token_fuera_de_factusuper' ? sinRutaCierre : e.mensaje;

  /// El cierre pendiente del cajero y lo que debería haber en caja. → (cierre o null, error)
  Future<(CierrePendiente?, String)> pendiente() async {
    final con = _con();
    try {
      final l = await con.get(
        '/apis/cajas/cierre_caja/cierre_lista_obtener.php',
        query: {'estado': '0', 'cajero': cajero},
      );
      final cierres = (l['cierres'] as List?) ?? const [];
      if (l['success'] != true || cierres.isEmpty) return (null, '');
      final c = cierres.first as Map;
      final asiento = int.tryParse('${c['Asiento']}') ?? 0;
      final r = await con.get(
        '/apis/cajas/cierre_caja/cierre_resumen_obtener.php',
        query: {'asiento': '$asiento'},
      );
      return (
        CierrePendiente(
          asiento,
          '${c['UsuarioNombre'] ?? ''}',
          (r['totalCaja'] as num?)?.toDouble() ?? 0,
        ),
        '',
      );
    } on ErrorConexion catch (e) {
      return (
        null,
        e.sinInternet
            ? 'Sin internet: puede contar, pero no contabilizar'
            : _error(e),
      );
    } finally {
      con.cerrar();
    }
  }

  /// Tiquete del conteo en la impresora de comprobantes de la estación. → error ('' = salió)
  Future<String> imprimir(
    Conteo c,
    String nombreCajero,
    CierrePendiente? p,
  ) async {
    final con = _con();
    try {
      final j = await con.post(
        '/apis/shared/cajas/caja_contador_monedas_imprimir.php',
        {
          'cajero': nombreCajero,
          ...c.aMapa(),
          'totalEfectivo': c.totalEfectivo,
          'totalContado': c.total,
          'control': null,
          if (p != null) 'asiento': p.asiento,
        },
      );
      return j['success'] == true ? '' : '${j['error'] ?? 'Error al imprimir'}';
    } on ErrorConexion catch (e) {
      return e.sinInternet ? 'Sin internet' : _error(e);
    } finally {
      con.cerrar();
    }
  }

  /// Guarda el conteo y contabiliza (imprimir=1: el servidor decide con el 031). → (mensaje, error)
  Future<(String, String)> contabilizar(CierrePendiente p, Conteo c) async {
    final con = _con();
    try {
      await con.post('/apis/cajas/cierre_caja/cierre_contador_guardar.php', {
        'cierre': p.asiento,
        ...c.aMapa(),
      });
      final j = await con.postForm(
        '/apis/cajas/cierre_caja/cierre_contabilizar.php',
        {'asientos': '${p.asiento}', 'imprimir': '1'},
      );
      if (j['success'] != true)
        return ('', '${j['error'] ?? 'Error al contabilizar'}');
      if (j['impresion_omitida_sin_permiso'] == true) {
        return ('Contabilizado ✓ (sin imprimir — no tiene permiso 031)', '');
      }
      return (
        j['impreso'] == true
            ? 'Contabilizado e impreso ✓'
            : 'Cierre contabilizado correctamente',
        '',
      );
    } on ErrorConexion catch (e) {
      return (
        '',
        e.sinInternet ? 'Sin internet: no se puede contabilizar' : _error(e),
      );
    } finally {
      con.cerrar();
    }
  }
}
