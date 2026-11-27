// FactuMóvil / FactuSuper — APLICAR la nota de crédito / débito (#3957). Réplica del modal MNC-001 de la web
// (components/ventas/notas/nota_dc_progreso/nota_dc_progreso.js): MISMOS 11 pasos, MISMO orden, mismas condiciones para
// omitir, y la misma pregunta de qué pasa con la plata en la NC (#2908: saldo a favor · efectivo · tarjeta/datáfono).
//   1 Crear documento · 2 Inventario · 3 Contabilizar · 4 Hacienda · 5 Imprimir · 6 Saldo a favor · 7 Documento en CxC ·
//   8 Aplicar recibo (NC: saldo a favor · ND: cargo en CxC) · 9 Imprimir recibo · 10 Enviar recibo · 11 Finalizar
// Todo por nota_paso.php (los MISMOS archivos de la web). Devuelve el número de la nota creada (o null si no se creó).
part of 'caja.dart';

enum _EstPaso { espera, corriendo, hecho, omitido, error }

class _NotaProceso extends StatefulWidget {
  final String llave, cajero, tipo, documento, detalle, motivoRef, motivoInt;
  final String factura, cliente;
  final double total;
  const _NotaProceso({
    required this.llave,
    required this.cajero,
    required this.tipo,
    required this.documento,
    required this.detalle,
    required this.motivoRef,
    required this.motivoInt,
    required this.factura,
    required this.cliente,
    required this.total,
  });
  @override
  State<_NotaProceso> createState() => _EstadoNotaProceso();
}

class _EstadoNotaProceso extends State<_NotaProceso> {
  static const _titulos = [
    'Crear documento',
    'Aplicar inventario',
    'Contabilizar',
    'Enviar a Hacienda',
    'Imprimir documento',
    'Verificar saldo a favor',
    'Verificar documento en CxC',
    'Aplicar recibo',
    'Imprimir recibo',
    'Enviar recibo',
    'Finalizar',
  ];
  late final Conexion con = Conexion(
    llave: widget.llave,
    cajero: widget.cajero,
  );
  final est = List<_EstPaso>.filled(11, _EstPaso.espera);
  final det = List<String>.filled(11, '');
  bool iniciado = false, terminado = false, huboFallo = false, imprimir = true;
  String error = '';

  // Destino del dinero (solo NC)
  bool cargandoDestino = true;
  String destinoNota = '', medioTitulo = '';
  List<Map> medios = [], opciones = [], visibles = [];
  String? destino; // clave elegida (null = falta elegir)
  String destinoCuenta = '';
  String pregunta =
      ''; // '' · 'datafono' · texto del encabezado de la respuesta

  // Resultado
  String numero = '',
      recibo = '',
      destinoAplicado = 'saldo',
      facturaOrigen = '';
  Object? hacienda;
  bool xmlPhp = false;
  Map? verif;

  bool get esNC => widget.tipo == '03';

  @override
  void initState() {
    super.initState();
    _cargarDestino();
  }

  @override
  void dispose() {
    con.cerrar();
    super.dispose();
  }

  Future<Map<String, dynamic>> _paso(String paso, Map<String, dynamic> body) =>
      con.post(
        'nota_paso.php?paso=$paso',
        body,
        espera: const Duration(seconds: 120),
      );

  Future<void> _cargarDestino() async {
    destino = 'saldo';
    if (!esNC) {
      setState(() => cargandoDestino = false);
      return;
    }
    try {
      final d = await _paso('destino', {'documento': widget.documento});
      if (d['success'] == true) {
        medios = [
          for (final m in (d['medios'] as List?) ?? const [])
            if (m is Map) m,
        ];
        medioTitulo = medios.length > 1
            ? 'Factura con pago múltiple:'
            : 'Factura pagada con:';
        if (d['aplica'] != true) {
          if (medios.length > 1) {
            visibles = [
              {
                'clave': 'saldo',
                'texto': 'Dejar como saldo a favor',
                'ayuda': '${d['razon'] ?? ''}',
                'disponible': true,
              },
            ];
          } else {
            destinoNota = '${d['razon'] ?? ''}';
          }
        } else {
          destinoNota = 'Hacienda recibe la nota con el mismo medio de pago de la factura original.';
          opciones = [
            for (final o in (d['opciones'] as List?) ?? const [])
              if (o is Map) o,
          ];
          if (opciones.where((o) => o['clave'] == 'tarjeta_no_paso').length ==
              1) {
            _preguntaDatafono();
          } else {
            visibles = opciones;
          }
        }
      }
    } catch (_) {
      // Si la consulta falla queda «saldo a favor», lo de siempre (igual que la web).
    }
    if (mounted) setState(() => cargandoDestino = false);
  }

  Map? _op(String clave) =>
      opciones.where((o) => o['clave'] == clave).firstOrNull;

  void _preguntaDatafono() {
    pregunta = 'datafono';
    visibles = [];
    destino = null; // hasta contestar no se puede iniciar
  }

  void _datafono(bool paso) {
    setState(() {
      if (paso) {
        final ef = _op('tarjeta_efectivo') ?? _op('efectivo');
        visibles = [
          ?_op('tarjeta_anulada'),
          ?_op('saldo'),
          if (ef != null) {...ef, 'texto': 'Devolver el efectivo al cliente'},
        ];
        destino = null;
        pregunta = 'Se cobró en el datáfono. ¿Qué hacemos con el dinero?';
      } else {
        final np = _op('tarjeta_no_paso');
        visibles = [?np];
        destino = np?['disponible'] == true ? 'tarjeta_no_paso' : null;
        destinoCuenta = '${np?['cuenta'] ?? ''}';
        pregunta = 'El cobro no pasó: nunca entró el dinero.';
      }
    });
  }

  // ── Los pasos ──────────────────────────────────────────────────────────────────────────────────────────────────────

  Future<void> _iniciar() async {
    if (destino == null) {
      setState(() => error = 'Elegí qué pasa con el dinero antes de iniciar');
      return;
    }
    setState(() {
      iniciado = true;
      error = '';
    });
    final pasos = <Future<String?> Function()>[
      _p1,
      _p2,
      _p3,
      _p4,
      _p5,
      _p6,
      _p7,
      _p8,
      _p9,
      _p10,
      _p11,
    ];
    for (var i = 0; i < pasos.length; i++) {
      if (!mounted) return;
      setState(() => est[i] = _EstPaso.corriendo);
      try {
        final r = await pasos[i]();
        if (!mounted) return;
        setState(() {
          if (r == null) {
            est[i] = _EstPaso.omitido;
            if (det[i].isEmpty) det[i] = 'No aplica';
          } else {
            est[i] = _EstPaso.hecho;
            if (r.isNotEmpty) det[i] = r;
          }
        });
      } catch (e) {
        if (!mounted) return;
        final m = e is ErrorConexion
            ? (e.motivo == 'tiempo'
                  ? 'El servidor no contestó a tiempo. Antes de reintentar, revise en FactuPOS si la nota se creó.'
                  : e.mensaje)
            : '$e'.replaceFirst('Exception: ', '');
        setState(() {
          est[i] = _EstPaso.error;
          det[i] = m;
          error = m;
        });
        return;
      }
    }
    if (mounted) setState(() => terminado = true);
  }

  Never _falla(Map j, String porDefecto) =>
      throw Exception('${j['error'] ?? j['message'] ?? porDefecto}');

  Future<String?> _p1() async {
    final j = await _paso('aplicar', {
      'documento': widget.documento,
      'detalle': widget.detalle,
      'motivo_referencia': widget.motivoRef.isEmpty ? '01' : widget.motivoRef,
      'motivo_interno': widget.motivoInt,
      'destino': destino ?? 'saldo',
      'destino_cuenta': destinoCuenta,
    });
    if (j['success'] != true) _falla(j, 'Error al crear documento');
    numero = '${j['nota_credito'] ?? j['nota_debito'] ?? j['documento'] ?? ''}';
    hacienda = j['hacienda'];
    xmlPhp = j['generar_xml_php'] == true;
    facturaOrigen = '${j['factura_origen'] ?? widget.factura}';
    destinoAplicado = '${j['destino'] ?? 'saldo'}';
    final dinero = '${j['destino_texto'] ?? ''}';
    return 'Documento creado: $numero${dinero.isEmpty ? '' : ' — Dinero: $dinero'}';
  }

  Future<String?> _p2() async {
    final j = await _paso(esNC ? 'inventario_nc' : 'inventario_nd', {
      esNC ? 'nota_credito' : 'nota_debito': numero,
    });
    if (j['success'] != true) _falla(j, 'Error en inventario');
    return '${j['articulos_procesados'] ?? 0} artículo(s) procesado(s)';
  }

  Future<String?> _p3() async {
    final j = await _paso(esNC ? 'asiento_nc' : 'asiento_nd', {
      'documento': numero,
      'cajero': widget.cajero,
      'operacion': 1,
      'aplicar_saldo_favor': false,
    });
    if (j['success'] != true) _falla(j, 'Error en contabilización');
    return 'Asiento #${j['asiento'] ?? '-'}';
  }

  Future<String?> _p4() async {
    if (xmlPhp) {
      final j = await _paso('xml', {
        'documento': numero,
        'referencia': facturaOrigen,
      });
      if (j['success'] != true) {
        throw Exception(
          'Hacienda: ${j['message'] ?? j['error'] ?? 'Error desconocido'}',
        );
      }
      return 'XML generado';
    }
    final h = hacienda;
    if (h == null) {
      det[3] = 'No electrónica';
      return null;
    }
    if (h is Map && h['error'] != null && '${h['error']}'.isNotEmpty) {
      throw Exception('${h['error']}');
    }
    if (h is Map && h['enviado'] == true) {
      return 'Enviado vía ${h['subproceso'] ?? 'MODVENT071'}';
    }
    throw Exception('No se pudo enviar a Hacienda');
  }

  Future<String?> _p5() async {
    if (!imprimir) {
      det[4] = 'Impresión desactivada por el usuario';
      return null;
    }
    // Un fallo de impresión NO detiene la nota (igual que la web): queda anotado.
    try {
      final j = await _paso('imprimir', {'numero': numero});
      if (j['success'] == true) return 'Impresora ${j['impresora'] ?? ''}: OK';
      huboFallo = true;
      return '❌ No se imprimió: ${j['error'] ?? 'error'}';
    } catch (e) {
      huboFallo = true;
      return '❌ No se imprimió: ${e is ErrorConexion ? e.mensaje : e}';
    }
  }

  bool get _devuelto => esNC && destinoAplicado != 'saldo';

  Future<Map> _verificar() async {
    final v = verif;
    if (v != null) return v;
    final j = await _paso('saldo_favor', {
      'nota_credito': numero,
      'cajero': widget.cajero,
      'solo_verificar': true,
    });
    return verif = j;
  }

  Future<String?> _p6() async {
    if (_devuelto) {
      det[5] = 'Dinero devuelto al cliente: no queda saldo a favor';
      return null;
    }
    if (!esNC) return null;
    final v = await _verificar();
    if (v['success'] != true) _falla(v, 'Error consultando el saldo a favor');
    if (v['ya_aplicado'] == true) {
      recibo = '${v['recibo'] ?? ''}';
      return 'Recibo #$recibo ya aplicado';
    }
    final saldo = _nn(v['saldo_favor']);
    if (saldo <= 0) return null;
    return 'Saldo a favor: ₡${fmt(saldo)} — cuenta ${v['cuenta_saldo_favor'] ?? '-'}';
  }

  Future<String?> _p7() async {
    if (!esNC || recibo.isNotEmpty || _devuelto) return null;
    final v = await _verificar();
    if (v['es_credito'] != true ||
        v['en_cxc'] != true ||
        v['alcanza'] != true) {
      return null;
    }
    return 'Factura ${v['factura_original'] ?? ''} pendiente ₡${fmt(_nn(v['saldo_pendiente']))} — el saldo a favor la cubre';
  }

  Future<String?> _p8() async {
    if (esNC) {
      if (recibo.isNotEmpty) return 'Recibo #$recibo';
      if (_devuelto) return null;
      final v = await _verificar();
      if (v['es_credito'] != true ||
          v['en_cxc'] != true ||
          v['alcanza'] != true) {
        return null;
      }
      final j = await _paso('saldo_favor', {
        'nota_credito': numero,
        'cajero': widget.cajero,
      });
      if (j['success'] != true) _falla(j, 'Error aplicando el recibo');
      if (j['aplicado'] != true && j['ya_aplicado'] != true) return null;
      recibo = '${j['recibo'] ?? '-'}';
      return 'Recibo #$recibo — ₡${fmt(_nn(j['monto_aplicado']))} — factura saldada';
    }
    final j = await _paso('cxc_nd', {
      'nota_debito': numero,
      'cajero': widget.cajero,
    });
    if (j['success'] != true) _falla(j, 'Error en CxC');
    if (j['aplicado'] != true) return null;
    return 'Cargo a factura ${j['factura_original'] ?? '-'} — ₡${fmt(_nn(j['monto']))}';
  }

  Future<String?> _p9() async {
    if (recibo.isEmpty) return null;
    final j = await _paso('recibo_imprimir', {'recibo': recibo});
    if (j['success'] != true) {
      huboFallo = true;
      return '❌ No se imprimió: ${j['message'] ?? j['error'] ?? 'error'}';
    }
    return 'Impreso en impresora ${j['impresora'] ?? '-'}';
  }

  Future<String?> _p10() async {
    if (recibo.isEmpty) return null;
    final lineas = <String>[];
    try {
      final j = await _paso('recibo_enviar', {'recibo': recibo});
      if (j['success'] == true && '${j['email'] ?? ''}'.isNotEmpty) {
        lineas.add('Enviado a correo ${j['email']}');
      } else if (j['success'] != true) {
        lineas.add(
          'Correo no enviado: ${j['message'] ?? j['error'] ?? 'error'}',
        );
      }
    } catch (e) {
      lineas.add('Correo no enviado: ${e is ErrorConexion ? e.mensaje : e}');
    }
    try {
      final j = await _paso('recibo_enviar', {
        'recibo': recibo,
        'canal': 'whatsapp',
      });
      final dest = [
        for (final d in (j['destinos'] as List?) ?? const [])
          if (d is Map && '${d['telefono'] ?? d['para'] ?? ''}'.isNotEmpty)
            '${d['telefono'] ?? d['para']}',
      ];
      if (j['success'] == true && dest.isNotEmpty) {
        lineas.add('Enviado a WhatsApp ${dest.join(', ')}');
      }
    } catch (_) {}
    if (lineas.isEmpty) return null;
    return lineas.join(' · ');
  }

  Future<String?> _p11() async => huboFallo
      ? 'Revise los pasos marcados: algo no salió.'
      : 'Proceso completado';

  // ── Vista ──────────────────────────────────────────────────────────────────────────────────────────────────────────

  Widget _icono(_EstPaso e) => switch (e) {
    _EstPaso.espera => const Icon(
      Icons.radio_button_unchecked,
      color: _Fm.borde,
    ),
    _EstPaso.corriendo => const SizedBox(
      width: 22,
      height: 22,
      child: CircularProgressIndicator(strokeWidth: 2.5),
    ),
    _EstPaso.hecho => const Icon(Icons.check_circle, color: Color(0xFF16A34A)),
    _EstPaso.omitido => const Icon(
      Icons.remove_circle_outline,
      color: _Fm.suave,
    ),
    _EstPaso.error => const Icon(Icons.cancel, color: Marca.rojo),
  };

  Widget _destino() {
    if (!esNC) return const SizedBox.shrink();
    if (cargandoDestino) return const LinearProgressIndicator();
    // Material (no Container con color): los RadioListTile pintan sobre el Material más cercano.
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Material(
        color: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: _Fm.borde),
        ),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '¿Qué pasa con el dinero?',
                style: TextStyle(fontWeight: FontWeight.w800, color: _Fm.navy1),
              ),
              if (medios.isNotEmpty) ...[
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(medioTitulo, style: const TextStyle(color: _Fm.suave)),
                    for (final m in medios)
                      _fmEtiqueta(
                        '${m['nombre']} ₡${fmt(_nn(m['monto']))}',
                        const Color(0xFFE2E8F0),
                        _Fm.tinta,
                      ),
                  ],
                ),
              ],
              if (destinoNota.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text(
                    destinoNota,
                    style: const TextStyle(color: _Fm.suave, fontSize: 13),
                  ),
                ),
              if (pregunta == 'datafono') ...[
                const SizedBox(height: 10),
                const Text(
                  '¿El cobro con tarjeta pasó por el datáfono?',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: iniciado ? null : () => _datafono(true),
                        icon: const Icon(Icons.check_circle_outline),
                        label: const Text('Sí, se cobró'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: iniciado ? null : () => _datafono(false),
                        icon: const Icon(Icons.highlight_off),
                        label: const Text('No, no pasó'),
                      ),
                    ),
                  ],
                ),
              ] else if (pregunta.isNotEmpty) ...[
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        pregunta,
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                    if (!iniciado)
                      TextButton(
                        onPressed: () => setState(_preguntaDatafono),
                        child: const Text('Cambiar'),
                      ),
                  ],
                ),
              ],
              for (final o in visibles)
                RadioListTile<String>(
                  contentPadding: EdgeInsets.zero,
                  value: '${o['clave']}',
                  // ignore: deprecated_member_use
                  groupValue: destino,
                  // ignore: deprecated_member_use
                  onChanged: iniciado || o['disponible'] != true
                      ? null
                      : (v) => setState(() {
                          destino = v;
                          destinoCuenta = '${o['cuenta'] ?? ''}';
                          error = '';
                        }),
                  title: Text('${o['texto']}'),
                  subtitle: Text(
                    o['disponible'] == true
                        ? '${o['ayuda'] ?? ''}'
                        : '${o['motivo'] ?? 'No disponible'}',
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final hechos = est
        .where((e) => e == _EstPaso.hecho || e == _EstPaso.omitido)
        .length;
    final tipoTexto = esNC ? 'Nota de Crédito' : 'Nota de Débito';
    return PopScope(
      canPop: !iniciado || terminado || error.isNotEmpty,
      child: Scaffold(
        backgroundColor: _Fm.fondo,
        body: SafeArea(
          child: Column(
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
                decoration: const BoxDecoration(
                  gradient: LinearGradient(colors: [_Fm.navy1, _Fm.navy2]),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '$tipoTexto · MNC-001',
                      style: const TextStyle(color: Colors.white70),
                    ),
                    Text(
                      numero.isNotEmpty
                          ? '${esNC ? 'NC' : 'ND'}: $numero'
                          : (widget.factura.isEmpty
                                ? 'Financiera'
                                : 'Factura ${widget.factura.length > 8 ? widget.factura.substring(widget.factura.length - 8) : widget.factura}'),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    Text(
                      '${widget.cliente} · Total ₡${fmt(widget.total)}',
                      style: const TextStyle(color: Colors.white),
                    ),
                    if (recibo.isNotEmpty)
                      Text(
                        'Recibo CxC: $recibo',
                        style: const TextStyle(
                          color: Color(0xFF6EE7B7),
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                  ],
                ),
              ),
              LinearProgressIndicator(
                value: hechos / 11,
                minHeight: 5,
                backgroundColor: Colors.white,
              ),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.all(12),
                  children: [
                    if (!iniciado) ...[
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        value: imprimir,
                        onChanged: (v) => setState(() => imprimir = v ?? true),
                        title: const Text('Imprimir comprobante'),
                        secondary: const Icon(Icons.print_outlined),
                      ),
                      _destino(),
                      const SizedBox(height: 12),
                    ],
                    for (var i = 0; i < 11; i++)
                      Container(
                        margin: const EdgeInsets.only(bottom: 6),
                        padding: const EdgeInsets.fromLTRB(10, 10, 12, 10),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(
                            color: est[i] == _EstPaso.error
                                ? Marca.rojo
                                : (est[i] == _EstPaso.corriendo
                                      ? _Fm.acento
                                      : _Fm.borde),
                          ),
                        ),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            SizedBox(
                              width: 26,
                              child: Text(
                                '${i + 1}',
                                style: const TextStyle(
                                  color: _Fm.suave,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                            _icono(est[i]),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    _titulos[i],
                                    style: TextStyle(
                                      fontWeight: FontWeight.w700,
                                      color: est[i] == _EstPaso.omitido
                                          ? _Fm.suave
                                          : _Fm.tinta,
                                    ),
                                  ),
                                  if (det[i].isNotEmpty)
                                    Text(
                                      det[i],
                                      style: TextStyle(
                                        fontSize: 13,
                                        color: est[i] == _EstPaso.error
                                            ? Marca.rojo
                                            : _Fm.suave,
                                      ),
                                    ),
                                ],
                              ),
                            ),
                          ],
                        ),
                      ),
                    if (error.isNotEmpty)
                      Container(
                        margin: const EdgeInsets.only(top: 6),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: const Color(0xFFFEE2E2),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          error,
                          style: const TextStyle(color: Color(0xFFB91C1C)),
                        ),
                      ),
                    if (terminado)
                      Container(
                        margin: const EdgeInsets.only(top: 6),
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: const Color(0xFFDCFCE7),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          '$tipoTexto $numero aplicada${huboFallo ? ' (con avisos: revise los pasos marcados)' : ''}.',
                          style: const TextStyle(
                            color: Color(0xFF15803D),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.all(12),
                color: Colors.white,
                child: Row(
                  children: [
                    if (!iniciado) ...[
                      Expanded(
                        child: OutlinedButton(
                          style: OutlinedButton.styleFrom(
                            minimumSize: const Size(0, 52),
                          ),
                          onPressed: () => Navigator.pop(context),
                          child: const Text('Cancelar'),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        flex: 2,
                        child: FilledButton.icon(
                          style: FilledButton.styleFrom(
                            backgroundColor: const Color(0xFF16A34A),
                            minimumSize: const Size(0, 52),
                          ),
                          onPressed: cargandoDestino ? null : _iniciar,
                          icon: const Icon(Icons.play_arrow),
                          label: const Text(
                            'Iniciar proceso',
                            style: TextStyle(fontWeight: FontWeight.w800),
                          ),
                        ),
                      ),
                    ] else
                      Expanded(
                        child: FilledButton(
                          style: FilledButton.styleFrom(
                            minimumSize: const Size(0, 52),
                          ),
                          onPressed: terminado || error.isNotEmpty
                              ? () => Navigator.pop(
                                  context,
                                  numero.isEmpty ? null : numero,
                                )
                              : null,
                          child: Text(
                            terminado || error.isNotEmpty
                                ? 'Aceptar'
                                : 'Procesando…',
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
