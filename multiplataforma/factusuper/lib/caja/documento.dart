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

const Map<String, dynamic> clienteContado = {
  'codigo': 'SN',
  'nombre': 'CLIENTE CONTADO',
  'tipo_precio': 0,
  'descuento': 0,
};

class ResultadoAgregar {
  final bool ok;
  final String motivo;
  final Linea? linea;
  final bool sumada, preguntarRepetido, permiteNueva;
  final List<String> avisos;
  const ResultadoAgregar({
    this.ok = false,
    this.motivo = '',
    this.linea,
    this.sumada = false,
    this.preguntarRepetido = false,
    this.permiteNueva = false,
    this.avisos = const [],
  });
}

/// Cambios pedidos a una línea (MV-108): cantidad, precio, descuento por % o por monto, bonificación.
class CambiosLinea {
  final double cantidad, precio, valor;
  final String modo; // 'pct' | 'monto'
  final bool bonificacion, montoConfirmado;
  const CambiosLinea({
    required this.cantidad,
    required this.precio,
    this.modo = 'pct',
    this.valor = 0,
    this.bonificacion = false,
    this.montoConfirmado = false,
  });
  CambiosLinea con({
    double? precio,
    String? modo,
    double? valor,
    bool? montoConfirmado,
  }) => CambiosLinea(
    cantidad: cantidad,
    precio: precio ?? this.precio,
    modo: modo ?? this.modo,
    valor: valor ?? this.valor,
    bonificacion: bonificacion,
    montoConfirmado: montoConfirmado ?? this.montoConfirmado,
  );
}

/// Resultado de validar: ok · error · requiere (permiso + alternativa) · confirmar «SI».
class Validacion {
  final bool ok;
  final String error, permiso, motivo, alternativaTexto;
  final CambiosLinea? alternativa;
  final bool confirmarSi;
  const Validacion({
    this.ok = false,
    this.error = '',
    this.permiso = '',
    this.motivo = '',
    this.alternativaTexto = '',
    this.alternativa,
    this.confirmarSi = false,
  });
  String get tipo => ok
      ? 'ok'
      : error.isNotEmpty
      ? 'error'
      : confirmarSi
      ? 'confirmar'
      : 'requiere:$permiso';
}

const double montoConfirmar = 5000000, montoBloqueo = 85000000;

class Documento {
  final DatosCaja datos;
  Cajero cajero;
  Map<String, dynamic> cliente = Map.of(clienteContado);
  final List<Linea> lineas = [];
  String medioPago = '01';
  String notas = '';

  /// La venta vino de una proforma de este equipo (MV-114): al facturarla sale de la lista.
  String? proformaOrigen;

  Documento(this.datos, this.cajero);

  Decimales get dec => datos.decimales;
  Totales get totales => totales_(lineas, dec);

  Map<String, dynamic> aMapa() => {
    'cliente': cliente,
    'medioPago': medioPago,
    'notas': notas,
    'proformaOrigen': ?proformaOrigen,
    'lineas': [for (final l in lineas) lineaAMapa(l)],
  };

  /// Restaura la venta en curso guardada (y la recalcula con los decimales de hoy).
  void restaurar(Map<String, dynamic>? m) {
    if (m == null) return;
    lineas
      ..clear()
      ..addAll([
        for (final x in (m['lineas'] as List? ?? const []))
          if (x is Map) lineaDesde(Map<String, dynamic>.from(x)),
      ]);
    cliente = m['cliente'] is Map
        ? Map<String, dynamic>.from(m['cliente'] as Map)
        : Map.of(clienteContado);
    medioPago = _t(m['medioPago']).isEmpty ? '01' : _t(m['medioPago']);
    notas = _t(m['notas']);
    proformaOrigen = _t(m['proformaOrigen']).isEmpty
        ? null
        : _t(m['proformaOrigen']);
    lineas.forEach(_calc);
  }

  void nuevo() {
    lineas.clear();
    cliente = Map.of(clienteContado);
    medioPago = '01';
    notas = '';
    proformaOrigen = null;
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

  /// ¿El cajero tiene el permiso? (para mostrar/permitir sin clave de supervisor).
  bool tienePermiso(String p) => _permiso(p);

  /// Descuento automático (LA:328-500). Devuelve los avisos.
  List<String> descuentoAutomatico(Linea l) {
    final avisos = <String>[];
    if (l.bonificacion) return avisos;
    var base = _n(cliente['descuento']) > 0
        ? _n(cliente['descuento'])
        : l.descFijo;
    if (l.nivelBloqueado) base = 0;
    if (base > l.descMax && !_permiso('023')) {
      avisos.add(
        'Descuento ajustado al máximo (${_fmt(l.descMax)} %): pasarlo requiere el permiso 023',
      );
      base = l.descMax;
    }
    if (base > 0 &&
        l.costo > 0 &&
        utilidad(l.precio, base, l.costo) < l.utilMin &&
        !_permiso('006')) {
      avisos.add(
        'Descuento quitado: dejaba la utilidad bajo el mínimo (${_fmt(l.utilMin)} %) — requiere el permiso 006',
      );
      base = 0;
    }
    var caja = l.nivelBloqueado ? 0.0 : descuentoCajaPct(l);
    if (caja > 0 &&
        l.costo > 0 &&
        utilidad(l.precio, base + caja, l.costo) < l.utilMin &&
        !_permiso('006'))
      caja = 0;
    l.descuento = redondear(base + caja, 6);
    l.descMonto = null;
    return avisos;
  }

  void _calc(Linea l) => calcular(l, dec, medioPago);

  /// Recalcular una línea (al cambiar el medio principal: tarjeta → IVA devuelto).
  void agregarRecalculo(Linea l) => _calc(l);

  /// «X no se fracciona…» o '' (#2134).
  String _avisoEntero(Map<String, dynamic> art, String texto, double queda) {
    final n =
        double.tryParse(texto.trim().replaceFirst(',', '.')) ?? double.nan;
    if (_n(art['fraccionable']) != 0 || !(n > 0) || n == n.truncateToDouble())
      return '';
    return '«${_t(art['nombre'])}» no se fracciona: ${queda > 0 ? 'la cantidad quedó en ${_fmt(queda)}' : 'escriba una cantidad entera'}';
  }

  /// [repetido]: null = decide el parámetro; 'sumar' | 'nueva' = ya lo eligió el cajero.
  ResultadoAgregar agregar(
    Map<String, dynamic> art,
    String cantidadTexto, {
    String? repetido,
    int? decimales,
  }) {
    final fracc = _n(art['fraccionable']) != 0;
    // #1909c: el PESO de la romana va con 3 decimales aunque CF-020 diga 2.
    final cant = cantidadValida(
      cantidadTexto,
      fraccionable: fracc,
      decimales: dec,
      dec: decimales,
    );
    if (!(cant > 0)) {
      final m = _avisoEntero(art, cantidadTexto, 0);
      return ResultadoAgregar(motivo: m.isEmpty ? 'Cantidad inválida' : m);
    }
    final entero = _avisoEntero(art, cantidadTexto, cant);
    final codigo = _t(art['codigo']);
    final existe = lineas.where((l) => l.codigo == codigo).firstOrNull;
    if (existe != null && repetido == null) {
      final preguntar =
          datos.param(345, '0') == '1' || datos.param(40, '0') == '1';
      if (preguntar)
        return ResultadoAgregar(
          preguntarRepetido: true,
          permiteNueva: datos.param(60, '0') == '1',
        );
      repetido = 'sumar';
    }
    if (existe != null && repetido == 'sumar') {
      existe.cantidad = cantidadValida(
        _fmtNum(existe.cantidad + cant),
        fraccionable: fracc,
        decimales: dec,
        dec: 3,
      );
      final avisos = existe.descManual
          ? <String>[]
          : descuentoAutomatico(existe);
      if (entero.isNotEmpty) avisos.add(entero);
      _calc(existe);
      return ResultadoAgregar(
        ok: true,
        linea: existe,
        sumada: true,
        avisos: avisos,
      );
    }
    final nivel = nivelActual();
    final lista = datos.precios(codigo);
    final p =
        lista
            .where(
              (x) => _n(x['numero']).toInt() == nivel && _n(x['precio']) > 0,
            )
            .firstOrNull ??
        lista.where((x) => _n(x['precio']) > 0).firstOrNull;
    if (p == null)
      return ResultadoAgregar(
        motivo: '«${_t(art['nombre'])}» no tiene precio de venta',
      );
    var precio = _n(p['precio']);
    final moneda = _t(p['moneda']).isNotEmpty
        ? _t(p['moneda'])
        : (_t(art['moneda']).isNotEmpty ? _t(art['moneda']) : 'CRC');
    if (moneda != 'CRC') {
      final tc = datos.tipoCambio(moneda);
      precio = tc > 0 ? redondear(precio * tc, 5) : 0;
    }
    if (!(precio > 0))
      return ResultadoAgregar(
        motivo: '«${_t(art['nombre'])}» no tiene precio de venta',
      );
    final exento = _n(cliente['exento']) == 1;
    final servicio = _t(art['naturaleza']) == '2';
    final nivelP = _n(p['numero']).toInt();
    final cabysOk = art['cabys_ok'] == null
        ? null
        : _n(art['cabys_ok']).toInt();
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

  /// Precio de lista (colones) del artículo para el nivel: si el nivel no tiene precio > 0, el PRIMER precio > 0 y su nivel.
  /// → (precio, nivel) o null si no tiene precio (precioPara de la web).
  (double, int)? precioPara(String codigo, int nivel) {
    final lista = datos.precios(codigo);
    final p =
        lista
            .where(
              (x) => _n(x['numero']).toInt() == nivel && _n(x['precio']) > 0,
            )
            .firstOrNull ??
        lista.where((x) => _n(x['precio']) > 0).firstOrNull;
    if (p == null) return null;
    final art = datos.articuloExacto(codigo) ?? const {};
    var precio = _n(p['precio']);
    final moneda = _t(p['moneda']).isNotEmpty
        ? _t(p['moneda'])
        : (_t(art['moneda']).isNotEmpty ? _t(art['moneda']) : 'CRC');
    if (moneda != 'CRC') {
      final tc = datos.tipoCambio(moneda);
      precio = tc > 0 ? redondear(precio * tc, 5) : 0;
    }
    return precio > 0 ? (precio, _n(p['numero']).toInt()) : null;
  }

  /// Tras bajar cambios del servidor: las líneas de [codigos] toman el precio nuevo (revisarCambiosAlAgregar de la web).
  /// No toca las líneas con precio o descuento puestos a mano. → cuántas cambiaron.
  int aplicarPreciosNuevos(Iterable<String> codigos) {
    final cambiados = codigos.toSet();
    var n = 0;
    for (var i = 0; i < lineas.length; i++) {
      final l = lineas[i];
      if (!cambiados.contains(l.codigo) ||
          l.descManual ||
          l.precio != l.precioLista)
        continue;
      if (datos.articuloExacto(l.codigo) == null) continue;
      final p = precioPara(l.codigo, l.nivel > 0 ? l.nivel : 1);
      if (p == null || p.$1 == l.precioLista) continue;
      if (cambiarNivel(i, p.$2).$1) n++;
    }
    return n;
  }

  /// Barra: cambiar el NIVEL DE PRECIO de una línea (cotizacion_tipoprecio_cambiar.php + reaplicar descuento de FactuDesk):
  /// si el nivel no tiene precio > 0 se SALTA; si no, toma su precio y reglas, el descuento vuelve a 0 y se re-aplica el
  /// automático. → (ok, motivo, avisos)
  (bool, String, List<String>) cambiarNivel(int i, int nivel) {
    final l = lineas[i];
    final lista = datos.precios(l.codigo);
    final fila = lista
        .where((x) => _n(x['numero']).toInt() == nivel)
        .firstOrNull;
    if (fila == null || !(_n(fila['precio']) > 0))
      return (false, 'sin precio en P$nivel', const []);
    final art = datos.articuloExacto(l.codigo) ?? const {};
    var precio = _n(fila['precio']);
    final moneda = _t(fila['moneda']).isNotEmpty
        ? _t(fila['moneda'])
        : (_t(art['moneda']).isNotEmpty ? _t(art['moneda']) : 'CRC');
    if (moneda != 'CRC') {
      final tc = datos.tipoCambio(moneda);
      precio = tc > 0 ? redondear(precio * tc, 5) : 0;
    }
    if (!(precio > 0)) return (false, 'sin precio en P$nivel', const []);
    l
      ..precio = precio
      ..precioLista = precio
      ..nivel = nivel
      ..descFijo = _n(fila['descuento_fijo'])
      ..descMax = fila['descuento_maximo'] == null
          ? 100
          : _n(fila['descuento_maximo'])
      ..utilMin = _utilidadMinima(fila)
      ..descCaja = _n(fila['descuento_caja'])
      ..nivelBloqueado = nivelSinDescuento(nivel)
      ..descMonto = null
      ..bonificacion = false
      ..descManual = false
      ..descuento = 0;
    final avisos = descuentoAutomatico(l);
    _calc(l);
    return (true, '', avisos);
  }

  /// Barra: cambiar la TARIFA DE IVA de una línea (código + % del catálogo).
  void cambiarTarifa(int i, String codigo, double porcentaje) {
    final l = lineas[i];
    l.codigoTarifa = codigo;
    l.tarifa = porcentaje;
    _calc(l);
  }

  /// Escala de descuentos rápidos — factudesk_descuentos_rapidos(): param 395 = CSV, 1-12 valores 0 ≤ n < 100,
  /// 2 decimales, únicos y ordenados; si no → [0,5,10,15,20,25,30,35].
  List<double> escalaDescuentos() {
    const preset = <double>[0, 5, 10, 15, 20, 25, 30, 35];
    final crudo = datos.param(395, '');
    if (crudo.isEmpty) return [...preset];
    final vals = <double>{
      for (final x
          in crudo.split(',').map((x) => x.trim()).where((x) => x.isNotEmpty))
        if (double.tryParse(x) != null) redondear(double.parse(x), 2),
    }.where((n) => n >= 0 && n < 100).toList()..sort();
    return vals.isNotEmpty && vals.length <= 12 ? vals : [...preset];
  }

  /// Cambiar la cantidad de una línea. Devuelve el aviso (o '').
  String cambiarCantidad(int i, String texto) {
    final l = lineas[i];
    final c = cantidadValida(
      texto,
      fraccionable: l.fraccionable != 0,
      decimales: dec,
    );
    if (c > 0) {
      l.cantidad = c;
      if (!l.descManual && l.descCaja > 0) descuentoAutomatico(l);
      _calc(l);
    }
    return _avisoEntero(
      {'fraccionable': l.fraccionable, 'nombre': l.nombre},
      texto,
      c > 0 ? c : l.cantidad,
    );
  }

  void quitar(int i) => lineas.removeAt(i);

  /// Validar cambios de una línea — réplica de FSLinea.validar (reglas de cotizacion_linea_actualizar.php, en su orden).
  /// [auth] = permisos ya autorizados por un supervisor. NO modifica la línea.
  Validacion validarLinea(Linea l, CambiosLinea c, Set<String> auth) {
    bool perm(String p) => auth.contains(p) || _permiso(p);
    final precio = c.precio, cant = c.cantidad, bonif = c.bonificacion;
    if (!(cant > 0))
      return const Validacion(error: 'La cantidad tiene que ser mayor que 0.');
    if (!(precio > 0))
      return const Validacion(error: 'El precio tiene que ser mayor que 0.');
    final cambioPrecio = (precio - l.precio).abs() > 1e-9;
    if (cambioPrecio && !perm('024'))
      return const Validacion(
        permiso: '024',
        motivo: 'Cambiar el precio de venta requiere el permiso 024.',
      );
    final bruto = cant * precio;
    final desc = bonif
        ? 100.0
        : c.modo == 'monto'
        ? (bruto > 0 ? math.min(c.valor, bruto) / bruto * 100 : 0.0)
        : c.valor;
    if (desc < 0 || desc > 100)
      return const Validacion(error: 'El descuento va de 0 a 100 %.');
    if (!bonif && l.nivelBloqueado && desc > 0)
      return Validacion(
        error: 'El precio ${l.nivel} es «sin descuento»: no admite descuento.',
      );
    if (desc > l.descuento + 1e-9 && !perm('004'))
      return const Validacion(
        permiso: '004',
        motivo: 'Aplicar o subir el descuento requiere el permiso 004.',
      );
    if (!bonif) {
      if (desc > l.descMax + 1e-9 && !perm('023')) {
        return Validacion(
          permiso: '023',
          motivo: 'El descuento máximo de este precio es ${_fmt(l.descMax)} %.',
          alternativaTexto: 'Ajustar al máximo (${_fmt(l.descMax)} %)',
          alternativa: c.con(modo: 'pct', valor: l.descMax),
        );
      }
      if (desc > 0 &&
          l.costo > 0 &&
          utilidad(precio, desc, l.costo) < l.utilMin &&
          !perm('006')) {
        return Validacion(
          permiso: '006',
          motivo:
              'Con ese descuento la utilidad queda bajo el mínimo (${_fmt(l.utilMin)} %).',
          alternativaTexto: 'Quitar el descuento',
          alternativa: c.con(modo: 'pct', valor: 0),
        );
      }
      if (cambioPrecio &&
          l.costo > 0 &&
          l.utilMin > 0 &&
          desc < 100 &&
          !perm('006')) {
        final minimo =
            (redondear(l.costo * (1 + l.utilMin / 100) / (1 - desc / 100), 4) *
                    100)
                .ceilToDouble() /
            100;
        if (precio < minimo) {
          return Validacion(
            permiso: '006',
            motivo:
                'El precio mínimo para no bajar de la utilidad (${_fmt(l.utilMin)} %) es ${_fmt(minimo)}.',
            alternativaTexto: 'Subir al mínimo (${_fmt(minimo)})',
            alternativa: c.con(precio: minimo),
          );
        }
      }
      final neto = precio * (1 - desc / 100);
      if (l.costo > 0 && neto < l.costo - 1e-9 && !perm('021')) {
        return Validacion(
          error:
              'El precio neto (${_fmt(neto)}) queda bajo el costo (${_fmt(l.costo)}): requiere el permiso 021.',
        );
      }
    }
    if (bruto >= montoBloqueo)
      return Validacion(
        error: 'La línea suma ${_fmt(bruto)}: el máximo es 85.000.000.',
      );
    if (bruto > montoConfirmar && !c.montoConfirmado)
      return Validacion(
        confirmarSi: true,
        motivo: 'La línea suma ${_fmt(bruto)}. Escriba SI para confirmar.',
      );
    return const Validacion(ok: true);
  }

  /// Aplica cambios YA validados (FSLinea.aplicar): el descuento queda manual (el de caja ya no se recalcula solo).
  void aplicarLinea(Linea l, CambiosLinea c, Map<String, String> autorizaron) {
    l.cantidad = c.cantidad;
    l.precio = c.precio;
    l.bonificacion = c.bonificacion;
    l.descManual = true;
    if (l.bonificacion) {
      l.descuento = 100;
      l.descMonto = null;
    } else if (c.modo == 'monto') {
      l.descMonto = c.valor;
    } else {
      l.descuento = c.valor;
      l.descMonto = null;
    }
    l.autorizaciones.addAll(autorizaron);
    _calc(l);
  }

  /// Cambiar el cliente — como FactuDesk: NO recalcula las líneas que ya están; las nuevas toman su nivel/descuento.
  /// Las exoneraciones se quitan (eran del cliente anterior).
  void asignarCliente(Map<String, dynamic>? c) {
    cliente = c == null ? Map.of(clienteContado) : Map.of(c);
    for (final l in lineas) {
      if (l.exo != null) {
        l.exo = null;
        _calc(l);
      }
    }
  }

  // ═══ EXONERACIÓN (MV-106) — réplica de FSDoc.exoneracionPlan/Aplicar/Quitar (= FactuDesk + las validaciones de
  //     cotizacion_exoneracion_aplicar.php) sobre las tablas del equipo ═══

  /// Las del cliente, la de vencimiento más lejano primero, con `vigente`.
  List<Map<String, dynamic>> exoneracionesCliente({DateTime? hoy}) {
    final h = (hoy ?? DateTime.now()).toIso8601String().substring(0, 10);
    final k = _t(cliente['codigo']).toUpperCase();
    final l = [
      for (final e in (datos.catalogos['exoneraciones'] as List? ?? const []))
        if (e is Map && _t(e['cliente']).toUpperCase() == k)
          {
            ...Map<String, dynamic>.from(e),
            'vigente':
                _t(e['vencimiento']).isNotEmpty &&
                _t(e['vencimiento'])
                        .substring(0, math.min(10, _t(e['vencimiento']).length))
                        .compareTo(h) >=
                    0,
          },
    ];
    l.sort((a, b) => _t(b['vencimiento']).compareTo(_t(a['vencimiento'])));
    return l;
  }

  /// CABYS → documentos que lo cubren (el «cabysMap» de FactuDesk). Vacío = sin mapa.
  Map<String, List<String>> cabysExonerados() {
    final k = _t(cliente['codigo']).toUpperCase();
    final m = <String, List<String>>{};
    for (final r
        in (datos.catalogos['exoneraciones_cabys'] as List? ?? const [])) {
      if (r is! Map || _t(r['cliente']).toUpperCase() != k) continue;
      final l = m.putIfAbsent(_t(r['cabys']), () => []);
      final d = _t(r['documento']);
      if (d.isNotEmpty && !l.contains(d)) l.add(d);
    }
    return m;
  }

  /// Qué pasaría con cada línea. [elegida] se usa cuando el cliente no tiene mapa de CABYS.
  List<PlanExo> exoneracionPlan(
    List<int> indices,
    Map<String, dynamic>? elegida,
  ) {
    final lista = exoneracionesCliente();
    final mapa = cabysExonerados();
    final sinMapa = mapa.isEmpty;
    return [
      for (final i in indices)
        () {
          final l = lineas[i];
          final cab = l.cabys.trim();
          Map<String, dynamic>? exo;
          var motivo = '';
          if (sinMapa) {
            exo = elegida ?? lista.firstOrNull;
          } else if (cab.isEmpty) {
            motivo = 'La línea no tiene CABYS';
          } else {
            final docs = mapa[cab] ?? const [];
            exo = lista.where((e) => docs.contains(e['documento'])).firstOrNull;
            if (exo == null)
              motivo = 'CABYS no autorizado en ninguna exoneración del cliente';
          }
          if (exo != null && motivo.isEmpty) {
            if (!(_n(exo['porcentaje']) > 0)) {
              motivo = 'La exoneración tiene 0 %';
            } else if (_t(exo['tipo_documento']).isEmpty ||
                _t(exo['documento']).isEmpty) {
              motivo = 'Exoneración incompleta: falta el tipo o el número de documento';
            } else if (_t(exo['tipo_documento']) == '01' &&
                !mapa.containsKey(cab)) {
              motivo = 'CABYS ${cab.isEmpty ? '(vacío)' : cab} no exonerado';
            } else if (!(l.tarifa > 0)) {
              motivo = 'La línea no lleva IVA';
            }
          }
          final ok = exo != null && motivo.isEmpty;
          return PlanExo(
            i,
            l.codigo,
            l.nombre,
            cab,
            ok ? exo : null,
            ok ? math.min(_n(exo['porcentaje']), l.tarifa) : 0,
            motivo,
          );
        }(),
    ];
  }

  List<PlanExo> exoneracionAplicar(
    List<int> indices,
    Map<String, dynamic>? elegida,
  ) {
    final plan = exoneracionPlan(indices, elegida);
    for (final r in plan) {
      final l = lineas[r.indice];
      l.exo = r.exo == null ? null : Exoneracion.desdeFila(r.exo!);
      _calc(l);
    }
    return plan;
  }

  int exoneracionQuitar(List<int> indices) {
    var n = 0;
    for (final i in indices) {
      if (i < lineas.length && lineas[i].exo != null) {
        lineas[i].exo = null;
        _calc(lineas[i]);
        n++;
      }
    }
    return n;
  }

  /// '' si la línea se puede facturar, o el problema (Hacienda rechaza CABYS malo y precio 0).
  static String cabysProblema(Linea l) {
    final c = l.cabys.trim();
    if (c.isEmpty) return 'no tiene CABYS';
    if (!RegExp(r'^\d{13}$').hasMatch(c))
      return 'el CABYS «$c» está mal escrito (son 13 números)';
    if (l.cabysOk == 0)
      return 'el CABYS $c no existe en el catálogo de Hacienda';
    return '';
  }

  /// Qué impide cobrar, o ''.
  String impedimento() {
    if (lineas.isEmpty) return 'La venta no tiene artículos.';
    final malas = lineas
        .where((l) => cabysProblema(l).isNotEmpty)
        .map((l) => '${l.codigo} ${l.nombre}: ${cabysProblema(l)}')
        .toList();
    if (malas.isNotEmpty) {
      return 'No se puede facturar — Hacienda la rechazaría: ${malas.join(' · ')}. Corrija el CABYS en la ficha del artículo o quite la línea.';
    }
    final cero = lineas
        .where((l) => !(l.precio > 0))
        .map((l) => '${l.codigo} ${l.nombre}')
        .toList();
    if (cero.isNotEmpty)
      return 'No se puede facturar — Hacienda la rechazaría: ${cero.join(' · ')} tiene precio ₡0.';
    return '';
  }

  /// El paquete de la cola de ventas — mismo contrato que `paquete()` de la web.
  Map<String, dynamic> paquete({
    required List<Map<String, dynamic>> pagos,
    required double vuelto,
    bool imprimir = true,
    required String transaccionId,
    required DateTime cuando,
    String tipoPago = 'contado',
    int diasCredito = 0,
  }) {
    final credito = tipoPago == 'credito';
    final est = datos.estacion;
    final bodega = _t(est['bodega']);
    final ls = <Map<String, dynamic>>[];
    for (final l in lineas) {
      final exo = l.exo != null && l.ivaExonerado > 0 ? l.exo : null;
      ls.add({
        'codigo': l.codigo,
        'cantidad': l.cantidad,
        'precio': l.precio,
        'costo': l.costo,
        'descuento': l.descuento,
        'descuentoMonto': l.descuentoMonto,
        'iva': l.tarifa,
        'ivaTarifa': l.codigoTarifa.isEmpty ? '08' : l.codigoTarifa,
        'ivaTotal': l.iva,
        'ivaDevuelto': l.ivaDevuelto,
        'gravado': l.gravado,
        'exento': l.exento,
        'exonerado': l.exonerado,
        'subtotal': l.subtotal1,
        'total': l.total,
        'bodega': bodega,
        'tipoPrecio': l.nivel,
        'unidadMedida': l.unidad,
        'cabys': l.cabys,
        'actividadEconomica': l.actividad,
        'naturaleza': int.tryParse(l.naturaleza) ?? 1,
        'numeroLinea': ls.length + 1,
        'numeroPrecio': l.nivel,
        'nombre': l.nombre,
        'precioVenta': l.precio,
        'porcentajeDescuento': l.descuento,
        'montoDescuento': l.descuentoMonto,
        'subtotalConDescuento': l.subtotal2,
        'porcentajeExoneracion': l.ivaExonerado,
        'serie': '',
        'subtotal1': l.subtotal1,
        'subtotal2': l.subtotal2,
        'otrosCargos': 0,
        'subtotal3': l.subtotal3,
        'ivaPorcentaje': l.tarifa,
        'ivaExonerado': l.ivaExonerado,
        'ivaExoneradoMonto': l.ivaExoneradoMonto,
        'montoGravado': l.gravado,
        'montoExonerado': l.exonerado,
        'montoExento': l.exento,
        'exoneracion': exo == null
            ? null
            : {
                'tipoDocumento': exo.tipoDocumento,
                'numeroDocumento': exo.documento,
                'articulo': exo.articulo,
                'inciso': exo.inciso,
                'institucion': exo.institucion,
                'institucionCodigo': exo.institucionCodigo,
                'fechaEmision': exo.fechaEmision,
                'vencimiento': exo.vencimiento,
                'porcentaje': l.ivaExonerado,
                'monto': redondear(l.exonerado * l.ivaExonerado / 100, 5),
              },
      });
    }
    final t = totales;
    final cobrado = ahoraIso(cuando);
    final medio = credito
        ? ''
        : (pagos.isEmpty ? '01' : _t(pagos.first['medio']));
    final imp =
        ((est['impresion'] as Map?)?[credito ? 'credito' : 'contado']
            as Map?) ??
        const {};
    final ruta = _n(imp['ruta']).toInt();
    final codCli = _t(cliente['codigo']);
    Map<String, dynamic> cliCompleto;
    if (codCli.isNotEmpty && codCli.toUpperCase() != 'SN') {
      cliCompleto = {...(datos.cliente(codCli) ?? cliente)}
        ..removeWhere((k, _) => k.startsWith('_'));
      cliCompleto['actividad_economica'] = datos.actividadCliente(codCli);
    } else {
      cliCompleto = {...cliente, 'actividad_economica': ''};
    }
    final actividadEmisor = lineas
        .map((l) => l.actividad)
        .firstWhere((a) => a.isNotEmpty, orElse: () => datos.actividadEmpresa);
    final pq = <String, dynamic>{
      'transaccionId': transaccionId,
      'origen': 'FACTUSUPER',
      'cobradoEn': cobrado,
      'estacion': {
        'oficina': _t(est['oficina']).isEmpty ? '001' : _t(est['oficina']),
        'caja': _t(est['caja']).isEmpty ? '1' : _t(est['caja']),
        'bodega': bodega,
      },
      'usuario': cajero.usuario,
      'agente': cajero.usuario,
      'cliente': {'codigo': codCli, 'nombre': _t(cliente['nombre'])},
      'moneda': 'CRC',
      'tipoCambio': 1,
      'tipoPago': tipoPago,
      'diasCredito': credito ? diasCredito : 0,
      'notas': notas,
      'total': r2(t.total),
      'lineas': ls,
      'pagos': credito
          ? <Map<String, dynamic>>[]
          : [
              for (final p in pagos)
                {
                  'medio': p['medio'],
                  'cuenta': p['cuenta'] ?? '',
                  'moneda': 'CRC',
                  'monto': r2(_n(p['monto'])),
                  'comprobante': p['comprobante'] ?? '',
                },
            ],
      'vuelto': credito ? 0 : r2(vuelto),
      'formaPago': credito ? '02' : '01',
      'medioPago': medio,
      'totales': totalesDocumento(lineas),
      'impresion': {
        'imprimir': imprimir,
        'ruta': const [2, 3, 4].contains(ruta) ? ruta : 4,
        'impresora': _t(imp['impresora']),
        'formato': _t(imp['formato']).isEmpty
            ? 'FIPVIVI002'
            : _t(imp['formato']),
        'ancho': _n(imp['ancho']).toInt(),
        'copias': 0,
      },
      'documento': {
        'transaccionId': transaccionId,
        'tipoDocumento': tipoDocumento(
          codigo: codCli,
          cedula: _t(cliente['cedula']),
          tipoCedula: _t(cliente['tipo_cedula']),
        ),
        'fecha': cobrado,
        'origen': 'FACTUSUPER',
        'oficina': _t(est['oficina']).isEmpty ? '001' : _t(est['oficina']),
        'caja': _t(est['caja']).isEmpty ? '1' : _t(est['caja']),
        'bodega': bodega,
        'estacionId': est['id'],
        'estacionNombre': _t(est['nombre']),
        'usuario': cajero.usuario,
        'agente': cajero.usuario,
        'moneda': 'CRC',
        'tipoCambio': 1,
        'condicionVenta': credito ? '02' : '01',
        'plazo': credito ? diasCredito : 0,
        'medioPago': medio,
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

    final suc = pad(
      dig(_t(srv['sucursal']).isEmpty ? '001' : _t(srv['sucursal'])),
      3,
    );
    final caja = pad(
      dig(
        _t(est['caja']).isNotEmpty
            ? _t(est['caja'])
            : (_t(srv['caja']).isEmpty ? '1' : _t(srv['caja'])),
      ),
      2,
    );
    final usu = pad(dig(cajero.usuario.isEmpty ? '0' : cajero.usuario), 5);
    String p2(int n) => n.toString().padLeft(2, '0');
    final id =
        '$caja-$suc-$usu-${p2(cuando.hour)}${p2(cuando.minute)}${p2(cuando.second)}-${p2(cuando.day)}';
    final d = pq['documento'] as Map<String, dynamic>;
    d['idProceso'] = id;
    d['idProcesoSucursal'] = suc;
    d['idProcesoCaja'] = caja;
    return pq;
  }
}

/// Pago mixto (FSCobro.guardar): los pagos tienen que sumar EXACTO el total; el vuelto se le descuenta al EFECTIVO,
/// del último al primero. → los pagos finales (sin los que quedan en 0).
List<Map<String, dynamic>> pagosFinales(
  List<Map<String, dynamic>> pagos,
  double vuelto,
) {
  var resto = vuelto;
  final f = [
    for (final p in pagos) {...p, 'monto': r2(_n(p['monto']))},
  ];
  for (var i = f.length - 1; i >= 0 && resto > 0; i--) {
    if (f[i]['medio'] != '01') continue;
    final q = math.min(_n(f[i]['monto']), resto);
    f[i]['monto'] = r2(_n(f[i]['monto']) - q);
    resto = r2(resto - q);
  }
  return f.where((p) => _n(p['monto']) > 0).toList();
}

/// Cuentas del cobro: total, pagado, falta, sobra, vuelto, efectivo — y qué impide cobrar ('' = se puede).
({double total, double pagado, double falta, double vuelto, String impide})
cuentasCobro(double total, List<Map<String, dynamic>> pagos) {
  final t = r2(total);
  final pagado = r2(pagos.fold<double>(0, (a, p) => a + _n(p['monto'])));
  final sobra = r2(pagado - t);
  final efectivo = r2(
    pagos
        .where((p) => p['medio'] == '01')
        .fold<double>(0, (a, p) => a + _n(p['monto'])),
  );
  final falta = math.max(0.0, r2(t - pagado));
  var impide = '';
  if (pagos.isEmpty) {
    impide = 'Agregue un medio de pago.';
  } else if (pagos.any((p) => !(_n(p['monto']) > 0))) {
    impide = 'Falta el monto de un pago.';
  } else if (falta > 0) {
    impide = 'Faltan ₡${_fmt(falta)}.';
  } else if (sobra > 0 && sobra > efectivo) {
    impide = 'El pago sobra y no es efectivo: el vuelto solo puede salir del efectivo.';
  }
  return (
    total: t,
    pagado: pagado,
    falta: falta,
    vuelto: sobra > 0 ? sobra : 0,
    impide: impide,
  );
}

/// La venta en curso al disco (si se va la luz o se cierra la app, al abrir sigue ahí).
Map<String, dynamic> lineaAMapa(Linea l) => {
  'codigo': l.codigo,
  'nombre': l.nombre,
  'barra': l.barra,
  'cantidad': l.cantidad,
  'precio': l.precio,
  'precioLista': l.precioLista,
  'nivel': l.nivel,
  'tarifa': l.tarifa,
  'codigoTarifa': l.codigoTarifa,
  'cabys': l.cabys,
  'cabysOk': l.cabysOk,
  'unidad': l.unidad,
  'naturaleza': l.naturaleza,
  'actividad': l.actividad,
  'fraccionable': l.fraccionable,
  'costo': l.costo,
  'descFijo': l.descFijo,
  'descMax': l.descMax,
  'utilMin': l.utilMin,
  'descCaja': l.descCaja,
  'uxm': l.uxm,
  'nivelBloqueado': l.nivelBloqueado,
  'descManual': l.descManual,
  'bonificacion': l.bonificacion,
  'descuento': l.descuento,
  'descMonto': l.descMonto,
  'autorizaciones': l.autorizaciones,
  if (l.exo != null) 'exo': l.exo!.aFila(),
};

Linea lineaDesde(Map<String, dynamic> m) =>
    Linea(
        codigo: _t(m['codigo']),
        nombre: _t(m['nombre']),
        barra: _t(m['barra']),
        cantidad: _n(m['cantidad']),
        precio: _n(m['precio']),
        precioLista: _n(m['precioLista']),
        nivel: _n(m['nivel']).toInt(),
        tarifa: _n(m['tarifa']),
        codigoTarifa: _t(m['codigoTarifa']),
        cabys: _t(m['cabys']),
        cabysOk: m['cabysOk'] == null ? null : _n(m['cabysOk']).toInt(),
        unidad: _t(m['unidad']),
        naturaleza: _t(m['naturaleza']),
        actividad: _t(m['actividad']),
        fraccionable: _n(m['fraccionable']).toInt(),
        costo: _n(m['costo']),
        descFijo: _n(m['descFijo']),
        descMax: _n(m['descMax']),
        utilMin: _n(m['utilMin']),
        descCaja: _n(m['descCaja']),
        uxm: _n(m['uxm']),
        nivelBloqueado: m['nivelBloqueado'] == true,
        descManual: m['descManual'] == true,
        bonificacion: m['bonificacion'] == true,
        descuento: _n(m['descuento']),
        descMonto: m['descMonto'] == null ? null : _n(m['descMonto']),
        exo: m['exo'] is Map
            ? Exoneracion.desdeFila(Map<String, dynamic>.from(m['exo'] as Map))
            : null,
      )
      ..autorizaciones.addAll(
        ((m['autorizaciones'] as Map?) ?? const {}).map(
          (k, v) => MapEntry('$k', '$v'),
        ),
      );

Totales totales_(List<Linea> l, Decimales d) => totales(l, d);

/// Resultado del plan de exoneración por línea.
class PlanExo {
  final int indice;
  final String codigo, nombre, cabys;
  final Map<String, dynamic>? exo;
  final double porcentaje;
  final String motivo;
  const PlanExo(
    this.indice,
    this.codigo,
    this.nombre,
    this.cabys,
    this.exo,
    this.porcentaje,
    this.motivo,
  );
}

/// Hora local con su desfase (-06:00): la cola la guarda como la hora REAL del cobro.
String ahoraIso(DateTime d) {
  String p(int n) => n.abs().toString().padLeft(2, '0');
  final z = d.timeZoneOffset.inMinutes;
  return '${d.year}-${p(d.month)}-${p(d.day)}T${p(d.hour)}:${p(d.minute)}:${p(d.second)}'
      '${z >= 0 ? '+' : '-'}${p(z ~/ 60)}:${p(z % 60)}';
}

String _fmtNum(double n) =>
    n == n.truncateToDouble() ? n.toInt().toString() : n.toString();
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
