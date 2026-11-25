/// El documento que se arma en la caja (#3957) — réplica de FSDoc (factusuper_documento.js): mismas reglas de
/// FactuDesk al agregar (nivel por param 57, primer precio > 0, descuento automático con tope 023 y utilidad 006,
/// descuento por caja, cliente exento → tarifa 10, servicio → costo 0, repetido por params 345/40/60) y el MISMO
/// paquete que espera apis/shared/venta/factusuper/venta_procesar.php.
library;

import 'dart:math' as math;

import '../motor/linea.dart';
import '../motor/redondeo.dart';
import 'cajeros.dart';
import 'datos_caja.dart';

String _t(Object? v) => '${v ?? ''}'.trim();
double _n(Object? v) => v is num ? v.toDouble() : (double.tryParse(_t(v)) ?? 0);

const Map<String, dynamic> clienteContado = {'codigo': 'SN', 'nombre': 'CLIENTE CONTADO', 'tipo_precio': 0, 'descuento': 0};

class ResultadoAgregar {
  final bool ok;
  final String motivo;
  final Linea? linea;
  final bool sumada, preguntarRepetido, permiteNueva;
  final List<String> avisos;
  const ResultadoAgregar({this.ok = false, this.motivo = '', this.linea, this.sumada = false, this.preguntarRepetido = false,
      this.permiteNueva = false, this.avisos = const []});
}

class Documento {
  final DatosCaja datos;
  Cajero cajero;
  Map<String, dynamic> cliente = Map.of(clienteContado);
  final List<Linea> lineas = [];
  String medioPago = '01';
  String notas = '';

  Documento(this.datos, this.cajero);

  Decimales get dec => datos.decimales;
  Totales get totales => totales_(lineas, dec);

  void nuevo() {
    lineas.clear();
    cliente = Map.of(clienteContado);
    medioPago = '01';
    notas = '';
  }

  /// FDF:407 — param 57 = 1 → siempre el de la estación; si no, el del cliente (no SN, > 0); si no, el de la estación.
  int nivelActual() {
    final nEst = _n(datos.estacion['tipo_precio']).toInt();
    final est = nEst > 0 ? nEst : 1;
    if (datos.param(57, '0') == '1') return est;
    final c = _t(cliente['codigo']).toUpperCase();
    final tp = _n(cliente['tipo_precio']).toInt();
    return c.isNotEmpty && c != 'SN' && tp > 0 ? tp : est;
  }

  /// Params 153→P10 … 158→P5 (1 = el nivel no lleva descuento).
  bool nivelSinDescuento(int nivel) {
    const mapa = {10: 153, 9: 154, 8: 155, 7: 156, 6: 157, 5: 158};
    return mapa[nivel] != null && datos.param(mapa[nivel]!, '0') == '1';
  }

  double _utilidadMinima(Map<String, dynamic> fila) {
    final u = _n(fila['utilidad_minima']);
    return u > 0 ? u : _n(datos.param(16, '0'));
  }

  bool _permiso(String p) => datos.tienePermiso(cajero.usuario, p);

  /// Descuento automático (LA:328-500). Devuelve los avisos.
  List<String> descuentoAutomatico(Linea l) {
    final avisos = <String>[];
    if (l.bonificacion) return avisos;
    var base = _n(cliente['descuento']) > 0 ? _n(cliente['descuento']) : l.descFijo;
    if (l.nivelBloqueado) base = 0;
    if (base > l.descMax && !_permiso('023')) {
      avisos.add('Descuento ajustado al máximo (${_fmt(l.descMax)} %): pasarlo requiere el permiso 023');
      base = l.descMax;
    }
    if (base > 0 && l.costo > 0 && utilidad(l.precio, base, l.costo) < l.utilMin && !_permiso('006')) {
      avisos.add('Descuento quitado: dejaba la utilidad bajo el mínimo (${_fmt(l.utilMin)} %) — requiere el permiso 006');
      base = 0;
    }
    var caja = l.nivelBloqueado ? 0.0 : descuentoCajaPct(l);
    if (caja > 0 && l.costo > 0 && utilidad(l.precio, base + caja, l.costo) < l.utilMin && !_permiso('006')) caja = 0;
    l.descuento = redondear(base + caja, 6);
    l.descMonto = null;
    return avisos;
  }

  void _calc(Linea l) => calcular(l, dec, medioPago);

  /// Recalcular una línea (al cambiar el medio principal: tarjeta → IVA devuelto).
  void agregarRecalculo(Linea l) => _calc(l);

  /// «X no se fracciona…» o '' (#2134).
  String _avisoEntero(Map<String, dynamic> art, String texto, double queda) {
    final n = double.tryParse(texto.trim().replaceFirst(',', '.')) ?? double.nan;
    if (_n(art['fraccionable']) != 0 || !(n > 0) || n == n.truncateToDouble()) return '';
    return '«${_t(art['nombre'])}» no se fracciona: ${queda > 0 ? 'la cantidad quedó en ${_fmt(queda)}' : 'escriba una cantidad entera'}';
  }

  /// [repetido]: null = decide el parámetro; 'sumar' | 'nueva' = ya lo eligió el cajero.
  ResultadoAgregar agregar(Map<String, dynamic> art, String cantidadTexto, {String? repetido}) {
    final fracc = _n(art['fraccionable']) != 0;
    final cant = cantidadValida(cantidadTexto, fraccionable: fracc, decimales: dec);
    if (!(cant > 0)) {
      final m = _avisoEntero(art, cantidadTexto, 0);
      return ResultadoAgregar(motivo: m.isEmpty ? 'Cantidad inválida' : m);
    }
    final entero = _avisoEntero(art, cantidadTexto, cant);
    final codigo = _t(art['codigo']);
    final existe = lineas.where((l) => l.codigo == codigo).firstOrNull;
    if (existe != null && repetido == null) {
      final preguntar = datos.param(345, '0') == '1' || datos.param(40, '0') == '1';
      if (preguntar) return ResultadoAgregar(preguntarRepetido: true, permiteNueva: datos.param(60, '0') == '1');
      repetido = 'sumar';
    }
    if (existe != null && repetido == 'sumar') {
      existe.cantidad = cantidadValida(_fmtNum(existe.cantidad + cant), fraccionable: fracc, decimales: dec, dec: 3);
      final avisos = existe.descManual ? <String>[] : descuentoAutomatico(existe);
      if (entero.isNotEmpty) avisos.add(entero);
      _calc(existe);
      return ResultadoAgregar(ok: true, linea: existe, sumada: true, avisos: avisos);
    }
    final nivel = nivelActual();
    final lista = datos.precios(codigo);
    final p = lista.where((x) => _n(x['numero']).toInt() == nivel && _n(x['precio']) > 0).firstOrNull ??
        lista.where((x) => _n(x['precio']) > 0).firstOrNull;
    if (p == null) return ResultadoAgregar(motivo: '«${_t(art['nombre'])}» no tiene precio de venta');
    var precio = _n(p['precio']);
    final moneda = _t(p['moneda']).isNotEmpty ? _t(p['moneda']) : (_t(art['moneda']).isNotEmpty ? _t(art['moneda']) : 'CRC');
    if (moneda != 'CRC') {
      final tc = datos.tipoCambio(moneda);
      precio = tc > 0 ? redondear(precio * tc, 5) : 0;
    }
    if (!(precio > 0)) return ResultadoAgregar(motivo: '«${_t(art['nombre'])}» no tiene precio de venta');
    final exento = _n(cliente['exento']) == 1;
    final servicio = _t(art['naturaleza']) == '2';
    final nivelP = _n(p['numero']).toInt();
    final cabysOk = art['cabys_ok'] == null ? null : _n(art['cabys_ok']).toInt();
    final l = Linea(
      codigo: codigo,
      nombre: _t(art['nombre']),
      barra: _t(art['barra']),
      cantidad: cant,
      precio: precio,
      nivel: nivelP,
      descFijo: _n(p['descuento_fijo']),
      descMax: p['descuento_maximo'] == null ? 100 : _n(p['descuento_maximo']),
      utilMin: _utilidadMinima(p),
      descCaja: _n(p['descuento_caja']),
      uxm: _n(art['unidades_x_medida']),
      nivelBloqueado: nivelSinDescuento(nivelP),
      tarifa: exento ? 0 : _n(art['tarifa_iva']),
      codigoTarifa: exento ? '10' : _t(art['codigo_tarifa_iva']),
      cabys: _t(art['cabys']),
      cabysOk: cabysOk,
      unidad: _t(art['unidad']).isEmpty ? 'Unid' : _t(art['unidad']),
      naturaleza: _t(art['naturaleza']).isEmpty ? '1' : _t(art['naturaleza']),
      actividad: _t(art['actividad_economica']),
      fraccionable: fracc ? 1 : 0,
      costo: servicio ? 0 : _n(art['costo']),
    );
    final avisos = descuentoAutomatico(l);
    if (entero.isNotEmpty) avisos.add(entero);
    _calc(l);
    lineas.add(l);
    return ResultadoAgregar(ok: true, linea: l, avisos: avisos);
  }

  /// Cambiar la cantidad de una línea. Devuelve el aviso (o '').
  String cambiarCantidad(int i, String texto) {
    final l = lineas[i];
    final c = cantidadValida(texto, fraccionable: l.fraccionable != 0, decimales: dec);
    if (c > 0) {
      l.cantidad = c;
      if (!l.descManual && l.descCaja > 0) descuentoAutomatico(l);
      _calc(l);
    }
    return _avisoEntero({'fraccionable': l.fraccionable, 'nombre': l.nombre}, texto, c > 0 ? c : l.cantidad);
  }

  void quitar(int i) => lineas.removeAt(i);

  /// '' si la línea se puede facturar, o el problema (Hacienda rechaza CABYS malo y precio 0).
  static String cabysProblema(Linea l) {
    final c = l.cabys.trim();
    if (c.isEmpty) return 'no tiene CABYS';
    if (!RegExp(r'^\d{13}$').hasMatch(c)) return 'el CABYS «$c» está mal escrito (son 13 números)';
    if (l.cabysOk == 0) return 'el CABYS $c no existe en el catálogo de Hacienda';
    return '';
  }

  /// Qué impide cobrar, o ''.
  String impedimento() {
    if (lineas.isEmpty) return 'La venta no tiene artículos.';
    final malas = lineas.where((l) => cabysProblema(l).isNotEmpty).map((l) => '${l.codigo} ${l.nombre}: ${cabysProblema(l)}').toList();
    if (malas.isNotEmpty) {
      return 'No se puede facturar — Hacienda la rechazaría: ${malas.join(' · ')}. Corrija el CABYS en la ficha del artículo o quite la línea.';
    }
    final cero = lineas.where((l) => !(l.precio > 0)).map((l) => '${l.codigo} ${l.nombre}').toList();
    if (cero.isNotEmpty) return 'No se puede facturar — Hacienda la rechazaría: ${cero.join(' · ')} tiene precio ₡0.';
    return '';
  }

  /// El paquete de la cola de ventas — mismo contrato que `paquete()` de la web.
  Map<String, dynamic> paquete({required List<Map<String, dynamic>> pagos, required double vuelto, bool imprimir = true, required String transaccionId, required DateTime cuando}) {
    final est = datos.estacion;
    final bodega = _t(est['bodega']);
    final ls = <Map<String, dynamic>>[];
    for (final l in lineas) {
      final exo = l.exo != null && l.ivaExonerado > 0 ? l.exo : null;
      ls.add({
        'codigo': l.codigo, 'cantidad': l.cantidad, 'precio': l.precio, 'costo': l.costo,
        'descuento': l.descuento, 'descuentoMonto': l.descuentoMonto,
        'iva': l.tarifa, 'ivaTarifa': l.codigoTarifa.isEmpty ? '08' : l.codigoTarifa, 'ivaTotal': l.iva, 'ivaDevuelto': l.ivaDevuelto,
        'gravado': l.gravado, 'exento': l.exento, 'exonerado': l.exonerado,
        'subtotal': l.subtotal1, 'total': l.total,
        'bodega': bodega, 'tipoPrecio': l.nivel,
        'unidadMedida': l.unidad, 'cabys': l.cabys, 'actividadEconomica': l.actividad,
        'naturaleza': int.tryParse(l.naturaleza) ?? 1,
        'numeroLinea': ls.length + 1, 'numeroPrecio': l.nivel, 'nombre': l.nombre, 'precioVenta': l.precio,
        'porcentajeDescuento': l.descuento, 'montoDescuento': l.descuentoMonto, 'subtotalConDescuento': l.subtotal2,
        'porcentajeExoneracion': l.ivaExonerado, 'serie': '',
        'subtotal1': l.subtotal1, 'subtotal2': l.subtotal2, 'otrosCargos': 0, 'subtotal3': l.subtotal3,
        'ivaPorcentaje': l.tarifa, 'ivaExonerado': l.ivaExonerado, 'ivaExoneradoMonto': l.ivaExoneradoMonto,
        'montoGravado': l.gravado, 'montoExonerado': l.exonerado, 'montoExento': l.exento,
        'exoneracion': exo == null
            ? null
            : {
                'tipoDocumento': exo.tipoDocumento, 'numeroDocumento': exo.documento, 'articulo': exo.articulo, 'inciso': exo.inciso,
                'institucion': exo.institucion, 'institucionCodigo': exo.institucionCodigo, 'fechaEmision': exo.fechaEmision,
                'vencimiento': exo.vencimiento, 'porcentaje': l.ivaExonerado, 'monto': redondear(l.exonerado * l.ivaExonerado / 100, 5),
              },
      });
    }
    final t = totales;
    final cobrado = ahoraIso(cuando);
    final medio = pagos.isEmpty ? '01' : _t(pagos.first['medio']);
    final imp = ((est['impresion'] as Map?)?['contado'] as Map?) ?? const {};
    final ruta = _n(imp['ruta']).toInt();
    final codCli = _t(cliente['codigo']);
    Map<String, dynamic> cliCompleto;
    if (codCli.isNotEmpty && codCli.toUpperCase() != 'SN') {
      cliCompleto = {...(datos.cliente(codCli) ?? cliente)}..removeWhere((k, _) => k.startsWith('_'));
      cliCompleto['actividad_economica'] = datos.actividadCliente(codCli);
    } else {
      cliCompleto = {...cliente, 'actividad_economica': ''};
    }
    final actividadEmisor = lineas.map((l) => l.actividad).firstWhere((a) => a.isNotEmpty, orElse: () => datos.actividadEmpresa);
    final pq = <String, dynamic>{
      'transaccionId': transaccionId,
      'origen': 'FACTUSUPER',
      'cobradoEn': cobrado,
      'estacion': {'oficina': _t(est['oficina']).isEmpty ? '001' : _t(est['oficina']), 'caja': _t(est['caja']).isEmpty ? '1' : _t(est['caja']), 'bodega': bodega},
      'usuario': cajero.usuario, 'agente': cajero.usuario,
      'cliente': {'codigo': codCli, 'nombre': _t(cliente['nombre'])},
      'moneda': 'CRC', 'tipoCambio': 1,
      'tipoPago': 'contado', 'diasCredito': 0,
      'notas': notas,
      'total': r2(t.total),
      'lineas': ls,
      'pagos': [for (final p in pagos) {'medio': p['medio'], 'cuenta': p['cuenta'] ?? '', 'moneda': 'CRC', 'monto': r2(_n(p['monto'])), 'comprobante': p['comprobante'] ?? ''}],
      'vuelto': r2(vuelto),
      'formaPago': '01',
      'medioPago': medio,
      'totales': totalesDocumento(lineas),
      'impresion': {
        'imprimir': imprimir,
        'ruta': const [2, 3, 4].contains(ruta) ? ruta : 4,
        'impresora': _t(imp['impresora']),
        'formato': _t(imp['formato']).isEmpty ? 'FIPVIVI002' : _t(imp['formato']),
        'ancho': _n(imp['ancho']).toInt(),
        'copias': 0,
      },
      'documento': {
        'transaccionId': transaccionId,
        'tipoDocumento': tipoDocumento(codigo: codCli, cedula: _t(cliente['cedula']), tipoCedula: _t(cliente['tipo_cedula'])),
        'fecha': cobrado,
        'origen': 'FACTUSUPER',
        'oficina': _t(est['oficina']).isEmpty ? '001' : _t(est['oficina']),
        'caja': _t(est['caja']).isEmpty ? '1' : _t(est['caja']),
        'bodega': bodega,
        'estacionId': est['id'], 'estacionNombre': _t(est['nombre']),
        'usuario': cajero.usuario, 'agente': cajero.usuario,
        'moneda': 'CRC', 'tipoCambio': 1,
        'condicionVenta': '01', 'plazo': 0, 'medioPago': medio,
        'notas': notas,
        'actividadEmisor': actividadEmisor,
        'lineas': ls.length,
      },
      'clienteCompleto': cliCompleto,
      'exoneracion': null,
    };
    // ID PROCESO: caja-sucursal-usuario-hhmmss-día (asignarIdProceso de la web).
    final srv = datos.idProcesoServidor;
    String dig(String s) => s.replaceAll(RegExp(r'\D'), '');
    String pad(String s, int n) {
      final x = s.padLeft(n, '0');
      return x.substring(x.length - n);
    }

    final suc = pad(dig(_t(srv['sucursal']).isEmpty ? '001' : _t(srv['sucursal'])), 3);
    final caja = pad(dig(_t(est['caja']).isNotEmpty ? _t(est['caja']) : (_t(srv['caja']).isEmpty ? '1' : _t(srv['caja']))), 2);
    final usu = pad(dig(cajero.usuario.isEmpty ? '0' : cajero.usuario), 5);
    String p2(int n) => n.toString().padLeft(2, '0');
    final id = '$caja-$suc-$usu-${p2(cuando.hour)}${p2(cuando.minute)}${p2(cuando.second)}-${p2(cuando.day)}';
    final d = pq['documento'] as Map<String, dynamic>;
    d['idProceso'] = id;
    d['idProcesoSucursal'] = suc;
    d['idProcesoCaja'] = caja;
    return pq;
  }
}

Totales totales_(List<Linea> l, Decimales d) => totales(l, d);

/// Hora local con su desfase (-06:00): la cola la guarda como la hora REAL del cobro.
String ahoraIso(DateTime d) {
  String p(int n) => n.abs().toString().padLeft(2, '0');
  final z = d.timeZoneOffset.inMinutes;
  return '${d.year}-${p(d.month)}-${p(d.day)}T${p(d.hour)}:${p(d.minute)}:${p(d.second)}'
      '${z >= 0 ? '+' : '-'}${p(z ~/ 60)}:${p(z % 60)}';
}

String _fmtNum(double n) => n == n.truncateToDouble() ? n.toInt().toString() : n.toString();
String _fmt(double n) => _fmtNum(redondear(n, 2));

/// UUID v4 para la transacción.
String uuidV4() {
  final r = math.Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
}
