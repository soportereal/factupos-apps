/// PROFORMAS de la estación (#3957) — réplica de FSProforma (factusuper_proforma.js, MV-114).
///
/// Dueño (26-sep-2026): «las proformas solo se guardan en la máquina, no hay que mandarlas al servidor… la idea es que
/// pueda estar atendiendo a varios clientes a la vez: guarda, atiende a otro cliente y luego recupera la proforma».
///   · Guardar (permiso 104): la venta en curso queda en el equipo y la pantalla queda limpia. Si vino de una proforma,
///     se ACTUALIZA esa misma.
///   · Abrir: se carga tal cual quedó (precios, descuentos, cliente, notas). La venta a medias se guarda sola antes.
///   · Al facturarla sale de la lista; también si se queda sin líneas. Eliminarla a mano pide el 060.
///   · Cotización = Guardar + el papel de cotización (FIPVIVI002 modo proforma) por la impresora de cotizaciones.
library;

import '../datos/almacen.dart';
import '../impresion/sin_internet.dart';
import '../impresion/ticket.dart';
import 'cajon.dart';
import 'datos_caja.dart';
import 'documento.dart';
import 'fondo.dart' show idControl;

class ResultadoProforma {
  final bool ok;
  final String motivo, id;
  final bool actualizada;
  const ResultadoProforma(
    this.ok, {
    this.motivo = '',
    this.id = '',
    this.actualizada = false,
  });
}

String _t(Object? v) => '${v ?? ''}'.trim();

class Proformas {
  final Almacen almacen;
  final String empresa;
  final DatosCaja datos;
  Proformas(this.almacen, this.empresa, this.datos);

  static const tabla = 'proformas';

  Future<List<Map<String, dynamic>>> lista() async {
    final v = await almacen.leerTabla(empresa, tabla);
    return v is List
        ? [
            for (final x in v)
              if (x is Map) Map<String, dynamic>.from(x),
          ]
        : <Map<String, dynamic>>[];
  }

  Future<void> _guardarLista(List<Map<String, dynamic>> l) =>
      almacen.guardarTabla(empresa, tabla, l);

  static String nombreDe(Map<String, dynamic> p) {
    if (_t(p['etiqueta']).isNotEmpty) return _t(p['etiqueta']);
    final c = p['cliente'];
    if (c is Map && _t(c['nombre']).isNotEmpty) return _t(c['nombre']);
    return _t(p['id']);
  }

  static bool clienteGenerico(Documento d) {
    final c = _t(d.cliente['codigo']).toUpperCase();
    return c.isEmpty || c == 'SN' || c == '0';
  }

  /// ¿Hace falta pedir la seña? (cliente de contado y sin etiqueta aún)
  Future<bool> pideEtiqueta(Documento d) async {
    if (!clienteGenerico(d)) return false;
    if (d.proformaOrigen == null) return true;
    final p = (await lista())
        .where((x) => x['id'] == d.proformaOrigen)
        .firstOrNull;
    return p == null || _t(p['etiqueta']).isEmpty;
  }

  /// Guarda la venta en curso y deja la pantalla limpia. `etiqueta` = la seña del cliente de contado (o null).
  Future<ResultadoProforma> guardar(
    Documento d, {
    String? etiqueta,
    bool cotizacion = false,
    DateTime? cuando,
  }) async {
    if (d.lineas.isEmpty) {
      return const ResultadoProforma(
        false,
        motivo: 'La venta no tiene artículos.',
      );
    }
    if (!d.tienePermiso('104')) {
      return const ResultadoProforma(
        false,
        motivo: 'Sin permiso para guardar proformas (104)',
      );
    }
    final l = await lista();
    final ahora = cuando ?? DateTime.now();
    final i = d.proformaOrigen == null
        ? -1
        : l.indexWhere((p) => p['id'] == d.proformaOrigen);
    var et = i >= 0 ? _t(l[i]['etiqueta']) : '';
    if (et.isEmpty && etiqueta != null) {
      et = etiqueta.trim();
      if (et.length > 40) et = et.substring(0, 40);
    }
    // 🪤 Dos guardadas en el MISMO segundo darían el mismo número: si ya existe, lleva sufijo.
    var id = i >= 0
        ? _t(l[i]['id'])
        : 'P-${idControl(datos, d.cajero.usuario, ahora)}';
    if (i < 0) {
      final base = id;
      for (var n = 2; l.any((p) => p['id'] == id); n++) {
        id = '$base-$n';
      }
    }
    final copia = d.aMapa()..remove('proformaOrigen');
    final reg = <String, dynamic>{
      'id': id,
      'fecha': ahora.toUtc().toIso8601String(),
      'etiqueta': et,
      'cotizacion': cotizacion || (i >= 0 && l[i]['cotizacion'] == true),
      'cliente': {'codigo': d.cliente['codigo'], 'nombre': d.cliente['nombre']},
      'lineas': d.lineas.length,
      'total': d.totales.total,
      'doc': copia,
    };
    if (i >= 0) {
      l[i] = reg;
    } else {
      l.add(reg);
    }
    await _guardarLista(l);
    d.nuevo();
    return ResultadoProforma(true, id: id, actualizada: i >= 0);
  }

  /// Carga la proforma en el documento (quien llama guarda antes la venta a medias).
  Future<Map<String, dynamic>?> abrir(String id, Documento d) async {
    final p = (await lista()).where((x) => x['id'] == id).firstOrNull;
    if (p == null) return null;
    d.restaurar({
      ...Map<String, dynamic>.from(p['doc'] as Map),
      'proformaOrigen': id,
    });
    return p;
  }

  Future<void> quitar(String? id) async {
    if (id == null || id.isEmpty) return;
    await _guardarLista((await lista()).where((p) => p['id'] != id).toList());
  }

  /// El papel de COTIZACIÓN (FSImprimeLocal.cotizacion): FIPVIVI002 en modo proforma, sin pagos, con el número de la
  /// proforma, por la impresora de cotizaciones de la estación (o la de contado). → error ('' = salió)
  Future<String> imprimirCotizacion(
    Map<String, dynamic> pq,
    String numero,
  ) async {
    final imp = (datos.estacion['impresion'] as Map?) ?? const {};
    final cfg = (imp['cotiza'] as Map?) ?? (imp['contado'] as Map?) ?? const {};
    final doc = documentoLocal(pq, datos);
    doc['tipo'] = 'proforma';
    doc['origen'] = 'actual';
    (doc['cabecera'] as Map)['Numero'] = numero;
    doc['pagos'] = <Map<String, dynamic>>[];
    final ancho = int.tryParse(_t(cfg['ancho'])) ?? 0;
    final texto = fipvivi002(doc, ancho > 0 ? ancho : 32, paramsFormato(datos));
    final ruta = int.tryParse(_t(cfg['ruta'])) ?? 4;
    if (ruta == 2 || ruta == 3) {
      return 'La impresión de la app va por FactuPOS Print (ruta 4); esta estación usa la ruta $ruta para cotizaciones.';
    }
    if (_t(cfg['impresora']).isEmpty) {
      return 'La estación no tiene impresora de cotizaciones';
    }
    return alPuerto(
      _t(cfg['impresora']),
      empresa,
      texto,
      'cot-$numero-${DateTime.now().millisecondsSinceEpoch}',
    );
  }
}
