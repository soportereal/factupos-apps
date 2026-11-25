/// El cálculo de una línea y de los totales — réplica de `calcular()`, `totales()`,
/// `totalesDocumento()`, `descuentoCajaPct()`, `utilidad()` y `cantidadValida()` de FSDoc
/// (factupos.com/modules/facturacion/factusuper/js/factusuper_documento.js).
///
/// 🔑 Regla del dueño: la venta va «ya toda preparada» y el servidor NO recalcula las líneas: lo que
/// sale de acá es lo que queda en la factura. Cualquier cambio en el JS se replica acá y se vuelve a
/// correr la prueba A/B (tool/ab_js.js → test/motor_ab_test.dart).
library;

import 'dart:math' as math;

import 'redondeo.dart';

/// Decimales de la empresa (CF-020). Igual que `cargarDecimales()`: por defecto 2, con su tope.
class Decimales {
  final int cantidad, precio, subDesc, descPct, sub2, iva, total;
  final bool sinRedondeo;
  const Decimales({
    this.cantidad = 2,
    this.precio = 4,
    this.subDesc = 2,
    this.descPct = 2,
    this.sub2 = 2,
    this.iva = 2,
    this.total = 2,
    this.sinRedondeo = false,
  });

  /// Desde los parámetros de la empresa (número → valor en texto).
  factory Decimales.desdeParametros(Map<int, String?> p) {
    int leer(int n, int def, int max) {
      final v = p[n]?.trim() ?? '';
      final x = num.tryParse(v);
      return x == null ? def : math.max(0, math.min(max, x.truncate()));
    }

    return Decimales(
      cantidad: leer(25, 2, 3),
      precio: leer(924, 4, 5),
      subDesc: leer(197, 2, 5),
      descPct: leer(18, 2, 4),
      sub2: leer(198, 2, 5),
      iva: leer(195, 2, 5),
      total: leer(199, 2, 5),
      sinRedondeo: leer(190, 0, 1) == 1,
    );
  }
}

/// Exoneración aplicada a una línea (fila del equipo: exoneraciones del cliente).
class Exoneracion {
  final double porcentaje;
  final String tipoDocumento,
      documento,
      articulo,
      inciso,
      institucion,
      institucionCodigo,
      fechaEmision,
      vencimiento;
  const Exoneracion({
    required this.porcentaje,
    this.tipoDocumento = '',
    this.documento = '',
    this.articulo = '',
    this.inciso = '',
    this.institucion = '',
    this.institucionCodigo = '',
    this.fechaEmision = '',
    this.vencimiento = '',
  });
}

/// Una línea de la venta. Los nombres siguen a los del JS para poder compararlos.
class Linea {
  String codigo,
      nombre,
      barra,
      codigoTarifa,
      cabys,
      unidad,
      naturaleza,
      actividad;
  double cantidad,
      precio,
      precioLista,
      tarifa,
      costo,
      descFijo,
      descMax,
      utilMin,
      descCaja,
      uxm;
  int nivel, fraccionable;
  int? cabysOk;
  bool nivelBloqueado, descManual, bonificacion;

  /// % de descuento (con descuento por monto es el % «virtual»).
  double descuento;

  /// Descuento por MONTO: si viene, manda sobre el %.
  double? descMonto;
  Exoneracion? exo;

  /// Quién autorizó cada permiso en esta línea (permiso → usuario), como `l.autorizaciones` de la web.
  final Map<String, String> autorizaciones = {};

  // ── Lo que deja calcular() (con los redondeos del UPDATE de ProformaHija) ──
  double ivaExonerado = 0,
      ivaExoneradoMonto = 0,
      subtotal1 = 0,
      descuentoMonto = 0,
      subtotal2 = 0,
      subtotal3 = 0,
      exonerado = 0,
      gravado = 0,
      exento = 0,
      iva = 0,
      ivaDevuelto = 0,
      total = 0;

  Linea({
    required this.codigo,
    this.nombre = '',
    this.barra = '',
    required this.cantidad,
    required this.precio,
    double? precioLista,
    this.nivel = 1,
    this.tarifa = 0,
    this.codigoTarifa = '',
    this.cabys = '',
    this.cabysOk,
    this.unidad = 'Unid',
    this.naturaleza = '1',
    this.actividad = '',
    this.fraccionable = 0,
    this.costo = 0,
    this.descFijo = 0,
    this.descMax = 100,
    this.utilMin = 0,
    this.descCaja = 0,
    this.uxm = 0,
    this.nivelBloqueado = false,
    this.descManual = false,
    this.bonificacion = false,
    this.descuento = 0,
    this.descMonto,
    this.exo,
  }) : precioLista = precioLista ?? precio;

  Map<String, Object?> calculado() => {
    'ivaExonerado': ivaExonerado,
    'ivaExoneradoMonto': ivaExoneradoMonto,
    'subtotal1': subtotal1,
    'descuento': descuento,
    'descuentoMonto': descuentoMonto,
    'subtotal2': subtotal2,
    'subtotal3': subtotal3,
    'exonerado': exonerado,
    'gravado': gravado,
    'exento': exento,
    'iva': iva,
    'ivaDevuelto': ivaDevuelto,
    'total': total,
  };
}

/// `calcular(l)`. [medioPago] = el medio principal del documento ('02' = tarjeta → IVA devuelto en servicios de salud 4 %).
Linea calcular(Linea l, Decimales dec, String medioPago) {
  final ivaPct = l.tarifa;
  final ivaExo = l.exo != null && ivaPct > 0
      ? math.min(l.exo!.porcentaje, ivaPct)
      : 0.0;
  final crudo = dec.sinRedondeo;

  final sub1 = crudo
      ? redondear(l.cantidad, 3) * l.precio
      : redondear(redondear(l.cantidad, 3) * l.precio, dec.subDesc);
  double descM;
  if (l.descMonto != null) {
    final m = math.max(0.0, math.min(l.descMonto!, sub1));
    // «Pegado»: si lo que sobra no llega a medio céntimo, el monto cubre la línea exacto (bonificación 100 %).
    descM = (r2(sub1) > 0 && r2(sub1 - m) <= 0) ? sub1 : m;
    l.descuento = sub1 > 0 ? redondear(descM / sub1 * 100, 6) : 0;
  } else {
    descM = sub1 * (l.descuento / 100);
  }
  final sub2 = crudo ? sub1 - descM : redondear(sub1 - descM, dec.sub2);
  final sub3 = sub2;
  final base = crudo ? sub3 : redondear(sub3, dec.sub2);
  final sub3r2 = r2(sub3);
  final exonerado = ivaPct > 0 ? sub3r2 * (ivaExo / ivaPct) : 0.0;
  final gravado = ivaPct > 0 ? sub3r2 - exonerado : 0.0;
  final exento = sub3r2 - gravado - exonerado;
  final iva = base * ((ivaPct - ivaExo) / 100);
  final ivaDev = medioPago == '02' && ivaPct == 4 && l.naturaleza == '2'
      ? iva
      : 0.0;
  final total =
      r2(gravado) +
      r2(exonerado) +
      r2(exento) +
      redondear(iva, dec.iva) -
      redondear(ivaDev, dec.iva);

  l.ivaExonerado = ivaExo;
  l.ivaExoneradoMonto = redondear(base * (ivaExo / 100), dec.iva);
  l.subtotal1 = redondear(sub1, dec.subDesc);
  l.descuentoMonto = redondear(descM, dec.subDesc);
  l.subtotal2 = redondear(sub2, dec.sub2);
  l.subtotal3 = redondear(sub3, dec.sub2);
  l.exonerado = r2(exonerado);
  l.gravado = r2(gravado);
  l.exento = r2(exento);
  l.iva = redondear(iva, dec.iva);
  l.ivaDevuelto = redondear(ivaDev, dec.iva);
  l.total = redondear(total, dec.total);
  return l;
}

/// Los totales de la pantalla — `totales()`.
class Totales {
  final double subtotal,
      descuento,
      subtotal2,
      iva,
      ivaDevuelto,
      total,
      articulos;
  final int lineas;
  const Totales(
    this.subtotal,
    this.descuento,
    this.subtotal2,
    this.iva,
    this.ivaDevuelto,
    this.total,
    this.articulos,
    this.lineas,
  );
  Map<String, Object?> aMapa() => {
    'subtotal': subtotal,
    'descuento': descuento,
    'subtotal2': subtotal2,
    'iva': iva,
    'ivaDevuelto': ivaDevuelto,
    'total': total,
    'lineas': lineas,
    'articulos': articulos,
  };
}

Totales totales(List<Linea> lineas, Decimales dec) {
  double sub = 0, desc = 0, sub2 = 0, iva = 0, dev = 0, tot = 0, art = 0;
  for (final l in lineas) {
    sub += l.subtotal1;
    desc += l.descuentoMonto;
    sub2 += l.subtotal2;
    iva += l.iva;
    dev += l.ivaDevuelto;
    tot += l.total;
    art += l.cantidad;
  }
  return Totales(
    redondear(sub, dec.subDesc),
    redondear(desc, dec.subDesc),
    redondear(sub2, dec.sub2),
    redondear(iva, dec.iva),
    redondear(dev, dec.iva),
    redondear(tot, dec.total),
    redondear(art, 3),
    lineas.length,
  );
}

/// Totales de ProformaMadre (mercancía y servicio aparte) — `totalesDocumento()`.
Map<String, double> totalesDocumento(List<Linea> lineas) {
  final t = <String, double>{
    for (final k in const [
      'costo',
      'venta',
      'descuento',
      'mercGravado',
      'mercExonerado',
      'mercExento',
      'servGravado',
      'servExonerado',
      'servExento',
      'iva',
      'ivaExonerado',
      'ivaDevuelto',
      'total',
    ])
      k: 0,
  };
  for (final l in lineas) {
    final serv = l.naturaleza == '2';
    t['costo'] = t['costo']! + l.costo * l.cantidad;
    t['venta'] = t['venta']! + l.subtotal1;
    t['descuento'] = t['descuento']! + l.descuentoMonto;
    final g = serv ? 'serv' : 'merc';
    t['${g}Gravado'] = t['${g}Gravado']! + l.gravado;
    t['${g}Exonerado'] = t['${g}Exonerado']! + l.exonerado;
    t['${g}Exento'] = t['${g}Exento']! + l.exento;
    t['iva'] = t['iva']! + l.iva;
    t['ivaExonerado'] = t['ivaExonerado']! + l.ivaExoneradoMonto;
    t['ivaDevuelto'] = t['ivaDevuelto']! + l.ivaDevuelto;
    t['total'] = t['total']! + l.total;
  }
  return t.map((k, v) => MapEntry(k, redondear(v, 5)));
}

/// Utilidad % de un precio neto sobre el costo. Sin costo = infinita (no frena descuentos).
double utilidad(double precio, double descPct, double costo) => costo > 0
    ? ((precio * (1 - descPct / 100)) - costo) / costo * 100
    : double.infinity;

/// % equivalente del descuento POR CAJA (solo las cajas enteras).
double descuentoCajaPct(Linea l) {
  if (!(l.descCaja > 0) || !(l.uxm > 1) || !(l.cantidad > 0)) return 0;
  final enCajas = (l.cantidad / l.uxm).floorToDouble() * l.uxm;
  return redondear(l.descCaja * enCajas / l.cantidad, 6);
}

/// Cantidad válida para el artículo: entera si no se fracciona (0 = no válida).
/// [dec] = decimales a respetar (el peso de la romana pasa 3); sin él, los de CF-020.
double cantidadValida(
  String texto, {
  required bool fraccionable,
  required Decimales decimales,
  int? dec,
}) {
  final n = double.tryParse(texto.trim().replaceFirst(',', '.')) ?? double.nan;
  if (!(n > 0)) return 0;
  return fraccionable
      ? redondear(n, math.min(3, dec ?? decimales.cantidad))
      : (n + 0.5).floorToDouble();
}

/// Tipo de documento — misma regla que el servidor (vtx_tipo_documento): 01 factura · 04 tiquete · 09 exportación.
String tipoDocumento({
  required String codigo,
  String cedula = '',
  String tipoCedula = '',
}) {
  final ced = cedula.trim(), ident = tipoCedula.trim();
  if (codigo.isEmpty || codigo.toUpperCase() == 'SN') return '04';
  if (ced.isEmpty || ced.length < 9 || ident == '00' || ident == '06')
    return '04';
  if (ident == '05') return '09';
  return '01';
}
