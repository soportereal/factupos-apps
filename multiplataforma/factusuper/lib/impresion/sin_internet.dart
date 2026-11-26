/// Imprimir SIN internet (#3957) — réplica de FSImprimeLocal (factusuper_imprime_local.js, etapa 14).
/// Dueño (25-nov-2026): «la aplicación va a estar en la misma computadora… conectarse directamente entre las dos
/// aplicaciones y mandar la impresión directa» · «en caso que no tenga conexión con internet».
///
///   · CON internet la imprime el SERVIDOR (cola, ruta 4), como siempre.
///   · SIN internet: el COMPROBANTE PROVISIONAL — el mismo tiquete FIPVIVI002 que arma el servidor (ticket.dart, réplica
///     byte a byte), con los datos del equipo y el ID PROCESO en lugar del número y la clave — directo a FactuPOS Print de
///     esta computadora (127.0.0.1:9302), a la MISMA cola del JSON. jobId = ID proceso (si se repite, no reimprime).
///   · Una sola vez por venta y solo ventas cobradas en los últimos 15 minutos (una vieja no saca papel de sorpresa).
///   · La venta que salió en provisional lleva `impresion.provisional` en el JSON: el servidor NO la vuelve a imprimir
///     (factusuper_imprimir). La oficial se reimprime a mano (142).
library;

import '../caja/cajon.dart' show alPuerto;
import '../caja/datos_caja.dart';
import 'ticket.dart';

const int ventanaMinutos = 15;

String _t(Object? v) => '${v ?? ''}'.trim();
num _n(Object? v) => v is num ? v : (num.tryParse(_t(v)) ?? 0);

/// El documento con la estructura de documento_venta_cargar(), armado con lo que hay en el equipo.
Map<String, dynamic> documentoLocal(Map<String, dynamic> pq, DatosCaja datos) {
  final d = (pq['documento'] as Map?) ?? const {};
  String? par(int n) =>
      datos.parametros.containsKey(n) ? datos.parametros[n] : null;
  final est = datos.estacion;
  final c = (pq['clienteCompleto'] as Map?) ?? const {};
  final generico =
      _t(c['codigo']).isEmpty || _t(c['codigo']).toUpperCase() == 'SN';
  final nombreUsuario = datos.nombreUsuario(_t(pq['usuario']));
  final medios = <String, String>{
    for (final m in (datos.catalogos['medios_pago'] as List? ?? const []))
      if (m is Map) _t(m['codigo']): '${m['descripcion'] ?? ''}',
  };
  final credito = pq['tipoPago'] == 'credito';
  final lineas = [
    for (final l in (pq['lineas'] as List? ?? const []))
      if (l is Map)
        {
          'ArticuloCodigo': l['codigo'],
          'NombreArticulo': l['nombre'],
          'ArticuloSerie': l['serie'] ?? '',
          'ArticuloCabys': l['cabys'] ?? '',
          'ArticuloUnidadMedida': l['unidadMedida'],
          'ArticuloBodegaCodigo': l['bodega'],
          'ArticuloCantidad': l['cantidad'],
          'ArticuloVenta': l['precio'],
          'ArticuloVentaSubTotal1': l['subtotal1'],
          'ArticuloVentaSubTotal3': l['subtotal3'],
          'ArticuloDescuentoPorcentage': l['descuento'],
          'ArticuloDescuentoMonto': l['descuentoMonto'],
          'ArticuloVentaExento': l['montoExento'],
          'ArticuloVentaExonerado': l['montoExonerado'],
          'ArticuloVentaTotal': l['total'],
          'ArticuloIvaMonto': l['ivaTotal'],
          'ArticuloIvaDevuelto': l['ivaDevuelto'],
          'ArticuloIvaPorcentage': l['ivaPorcentaje'],
        },
  ];
  final t = (pq['totales'] as Map?) ?? const {};
  // Pagos NETOS (el vuelto ya descontado del efectivo) + el vuelto aparte como medio '00' («PAGA CON» y «Vuelto»).
  final pagos = <Map<String, dynamic>>[
    if (!credito)
      for (final p in (pq['pagos'] as List? ?? const []))
        if (p is Map)
          {
            'MedioPagoCodigo': p['medio'],
            'MedioPagoNombre': medios[_t(p['medio'])] ?? '',
            'Monto': p['monto'],
          },
  ];
  if (!credito && _n(pq['vuelto']) > 0)
    pagos.add({
      'MedioPagoCodigo': '00',
      'MedioPagoNombre': 'VUELTO',
      'Monto': pq['vuelto'],
    });
  final tc = datos.tipoCambio('USD');
  final cli = (pq['cliente'] as Map?) ?? const {};
  return {
    'tipo': 'factura',
    'origen': 'factusuper',
    'cabecera': {
      'Numero': '',
      'Clave': '',
      'TipoDocumento': _t(d['tipoDocumento']).isEmpty
          ? '04'
          : d['tipoDocumento'],
      'Fecha': pq['cobradoEn'],
      'FormaPagoCodigo': pq['formaPago'],
      'MonedaCodigo': pq['moneda'] ?? 'CRC',
      'Detalle': pq['notas'] ?? '',
      'ClienteCodigo': cli['codigo'],
      'ClienteNombre': cli['nombre'],
      'ClienteNombreComercial': generico ? '' : (c['comercial'] ?? ''),
      'ClienteNombreJuridico': generico ? '' : (c['nombre'] ?? ''),
      'ClienteCedula': generico ? '' : (c['cedula'] ?? ''),
      'ClienteDireccion': generico ? '' : (c['direccion'] ?? ''),
      'ClienteTelefono': generico ? '' : (c['telefonos'] ?? ''),
      'ClienteEmail': generico ? '' : (c['email_general'] ?? ''),
      'AgenteCodigo': pq['agente'],
      'VendedorNombre': nombreUsuario,
      'UsuarioCodigo': pq['usuario'],
      'UsuarioNombre': nombreUsuario,
      'DiasCredito': credito ? _n(pq['diasCredito']) : 0,
    },
    'lineas': lineas,
    // documento_empresa_cargar() lee estos mismos parámetros.
    'empresa': {
      'RazonSocial': par(54) ?? '',
      'NombreComercial': par(62) ?? '',
      'Cedula': par(66) ?? '',
      'Telefono': par(73) ?? '',
      'Resolucion': par(123) ?? '',
    },
    'cliente': {
      'DiasCredito': credito ? _n(pq['diasCredito']) : _n(c['plazo']),
    },
    'mensajes': est['mensajes'] ?? {'encabezado': [], 'pie': []},
    'pagos': pagos,
    'totales': {
      'merc_gravada': t['mercGravado'],
      'merc_exenta': t['mercExento'],
      'serv_gravado': t['servGravado'],
      'serv_exento': t['servExento'],
      'descuento': t['descuento'],
      'iva': t['iva'],
      'iva_devuelto': t['ivaDevuelto'],
      'impuesto_servicio': 0,
      'total': t['total'],
    },
    // Lo que el formato consulta a la base: sin internet solo el tipo de cambio (el del equipo); lo demás no sale.
    'bd': {if (tc > 0) 'tipoCambioVenta': tc},
  };
}

/// Params del formato, como _imprfipv_cargarParametros(): los que existen en la empresa; los demás, el default.
Map<int, String> paramsFormato(DatosCaja datos) {
  const def = {
    15: '1',
    20: '1',
    22: '0',
    23: '1',
    26: '1',
    38: '1',
    43: '0',
    47: '1',
    89: '2104',
    110: '0',
    137: '',
    151: '1',
    192: '1',
    249: 'CRC',
    291: 'PROFORMA',
    307: '0',
    343: '0',
    344: '1',
    346: '0',
    380: '1',
    381: '1',
    382: '1',
    391: '0',
    936: '0',
  };
  return {
    for (final e in def.entries)
      e.key: datos.parametros.containsKey(e.key)
          ? (datos.parametros[e.key] ?? '')
          : e.value,
  };
}

/// Copias como impresion_factura_websocket_enviar(): param 98 crédito / 99 contado, entre 0 y 5.
int copias(DatosCaja datos, bool credito) =>
    (int.tryParse(_t(datos.parametros[credito ? 98 : 99])) ?? 0).clamp(0, 5);

/// Imprime el provisional de UNA venta por la ruta del JSON. → (ok, error, hojas)
Future<(bool, String, int)> imprimirProvisional(
  Map<String, dynamic> venta,
  DatosCaja datos,
  String empresa,
) async {
  final pq = venta['paquete'] as Map<String, dynamic>;
  final cfg = (pq['impresion'] as Map?) ?? const {};
  final ruta = const [2, 3].contains(_n(cfg['ruta']).toInt())
      ? _n(cfg['ruta']).toInt()
      : 4;
  // Rutas 2 (Bluetooth) y 3 (Bridge) son del navegador; la app, en la misma computadora, va por FactuPOS Print (ruta 4).
  if (ruta != 4)
    return (
      false,
      'La impresión sin internet de la app va por FactuPOS Print (ruta 4); esta estación usa la ruta $ruta.',
      0,
    );
  if (_t(cfg['impresora']).isEmpty)
    return (false, 'La estación no tiene impresora (cola) configurada', 0);
  final idp = _t(venta['idProceso']).isNotEmpty
      ? _t(venta['idProceso'])
      : _t((pq['documento'] as Map?)?['idProceso']);
  // Dueño (27-sep): sin internet sale SIEMPRE en FIPVIVI002 con el ancho de la estación (32 o 40).
  final base = fipvivi002(
    documentoLocal(pq, datos),
    _n(cfg['ancho']).toInt() > 0 ? _n(cfg['ancho']).toInt() : 32,
    paramsFormato(datos),
    provisional: idp,
  );
  final elegidas = _n(cfg['copias'])
      .toInt(); // −(n+1) = n copias elegidas en el cobro (FactuMóvil VP-001)
  final n =
      1 +
      (elegidas < 0
          ? (-elegidas - 1).clamp(0, 5)
          : copias(datos, pq['tipoPago'] == 'credito'));
  for (var i = 0; i < n; i++) {
    final hoja = base.replaceFirst(
      '{{COPIA_ETIQUETA}}',
      i == 0 ? 'ORIGINAL' : 'COPIA',
    );
    final error = await alPuerto(
      _t(cfg['impresora']),
      empresa,
      hoja,
      '$idp-$i',
    );
    if (error.isNotEmpty) return (false, error, i);
  }
  return (true, '', n);
}

/// Sin red: imprime el provisional de las ventas recién cobradas que todavía no salieron en papel. Se anota aunque falle
/// (reintentarlo minutos después sacaría papel a destiempo). Devuelve [(idProceso, ok, error)].
Future<List<(String, bool, String)>> imprimirPendientesSinRed(
  List<Map<String, dynamic>> pendientes,
  DatosCaja datos,
  String empresa,
) async {
  final limite = DateTime.now().subtract(
    const Duration(minutes: ventanaMinutos),
  );
  final res = <(String, bool, String)>[];
  for (final v in pendientes) {
    final pq = v['paquete'] as Map<String, dynamic>?;
    final imp = pq?['impresion'] as Map?;
    if (pq == null ||
        imp == null ||
        imp['imprimir'] != true ||
        v['impreso'] == true ||
        v['impresionLocal'] != null)
      continue;
    final f = DateTime.tryParse(_t(v['fecha'] ?? pq['cobradoEn']));
    if (f == null || f.isBefore(limite)) continue;
    (bool, String, int) r;
    try {
      r = await imprimirProvisional(v, datos, empresa);
    } catch (e) {
      r = (false, '$e', 0);
    }
    final ahora = DateTime.now().toIso8601String();
    v['impresionLocal'] = {
      'ok': r.$1,
      'error': r.$2,
      'hojas': r.$3,
      'fecha': ahora,
    };
    if (r.$1) {
      v['impreso'] = true;
      // Viaja en el JSON: el servidor NO la vuelve a imprimir cuando la factura.
      (pq['impresion'] as Map)['provisional'] = {
        'idProceso': v['idProceso'],
        'fecha': ahora,
      };
    }
    res.add(('${v['idProceso']}', r.$1, r.$2));
  }
  return res;
}
