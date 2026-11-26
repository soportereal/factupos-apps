// FactuMóvil — Procesar (PM-001), Cobro de Factura y Venta a Crédito (VP-001), #3957 (dueño 26-nov-2026, fotos 10, 8, 9 y
// 11 de Auxiliares). Réplica de la web: PM-001 = hoja con CONTADO (Definir · Efectivo · Tarjeta · SINPE), CRÉDITO y
// ENVIAR; VP-001 = botones de medio (uno por CUENTA: «Tarjetas BN», «Sinpe Movil Bac»…), Fijar default, monto con moneda,
// billetes CRC/USD, «Todo …», la lista de pagos, PAGADO / COMPLETO y el pie Cancelar · Copias · No Imprime · Confirmar.
// 🔑 Solo cambia la cara: el cobro sigue siendo el de la caja (_cobrar → doc.paquete → cola sin internet).
part of 'caja.dart';

/// «SINPE MOVIL BNCR» → «Sinpe Movil Bncr» (como lo muestra la web).
String _fmTitulo(String s) => s
    .trim()
    .toLowerCase()
    .split(RegExp(r'\s+'))
    .where((w) => w.isNotEmpty)
    .map((w) => w[0].toUpperCase() + w.substring(1))
    .join(' ');

/// Un botón de medio de pago: el medio + UNA de sus cuentas.
class _BotonMedio {
  final MedioPago medio;
  final String cuenta;
  const _BotonMedio(this.medio, this.cuenta);
  String get etiqueta {
    final n = medio.nombres[cuenta] ?? '';
    if (medio.codigo == '01' || n.isEmpty || medio.cuentas.length <= 1) {
      return _fmTitulo(medio.descripcion);
    }
    return _fmTitulo(n);
  }

  String get clave => '${medio.codigo}|$cuenta';
}

List<_BotonMedio> _botonesMedio(List<MedioPago> medios) => [
  for (final m in medios)
    if (m.cuentas.isEmpty)
      _BotonMedio(m, '')
    else
      for (final c in m.cuentas) _BotonMedio(m, c),
];

IconData _iconoMedioFm(String codigo) => switch (codigo) {
  '01' => Icons.payments_outlined,
  '02' => Icons.credit_card,
  '04' => Icons.account_balance_outlined,
  '06' => Icons.phone_android,
  _ => Icons.account_balance_wallet_outlined,
};

extension _ProcesarMovil on _EstadoCaja {
  /// PM-001: ¿cómo se procesa? (hoja de abajo, como la web).
  Future<void> _fmProcesar() async {
    final imp = doc.impedimento();
    if (imp.isNotEmpty) {
      await avisoDialogo(context, 'No se puede procesar', imp);
      return;
    }
    final medios = widget.datos.mediosPago();
    MedioPago? de(String c) => medios.where((m) => m.codigo == c).firstOrNull;
    final tarjeta = de('02'), sinpe = de('06');
    final accion = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: _Fm.fondo,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) {
        Widget ficha(
          IconData ico,
          Color color,
          String titulo,
          String sub,
          String? accion, {
          String tip = 'Próximamente en la app',
        }) {
          final activo = accion != null;
          final t = Material(
            color: activo ? const Color(0xFFF8FAFD) : const Color(0xFFF1F3F6),
            borderRadius: BorderRadius.circular(10),
            child: InkWell(
              borderRadius: BorderRadius.circular(10),
              onTap: activo ? () => Navigator.pop(ctx, accion) : null,
              child: Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: _Fm.borde),
                ),
                child: Row(
                  children: [
                    Container(
                      width: 40,
                      height: 40,
                      decoration: BoxDecoration(
                        color: activo ? color : const Color(0xFF9CA3AF),
                        borderRadius: BorderRadius.circular(9),
                      ),
                      child: Icon(ico, color: Colors.white, size: 22),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            titulo,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              fontSize: 15,
                              color: activo ? _Fm.tinta : _Fm.suave,
                            ),
                          ),
                          Text(
                            sub,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 12,
                              color: _Fm.suave,
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
          return activo ? t : Tooltip(message: tip, child: t);
        }

        Widget seccion(IconData ico, String titulo, List<Widget> fichas) {
          final filas = <Widget>[];
          for (var i = 0; i < fichas.length; i += 2) {
            filas.add(
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Row(
                  children: [
                    Expanded(child: fichas[i]),
                    const SizedBox(width: 8),
                    Expanded(
                      child: i + 1 < fichas.length
                          ? fichas[i + 1]
                          : const SizedBox(),
                    ),
                  ],
                ),
              ),
            );
          }
          return Container(
            margin: const EdgeInsets.fromLTRB(12, 10, 12, 0),
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: _Fm.borde),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(ico, size: 18, color: _Fm.suave),
                    const SizedBox(width: 6),
                    Text(
                      titulo,
                      style: const TextStyle(
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1,
                        color: _Fm.suave,
                      ),
                    ),
                  ],
                ),
                ...filas,
              ],
            ),
          );
        }

        final cred = _infoCredito(doc.totales.total);
        return FractionallySizedBox(
          heightFactor: 0.9,
          child: Column(
            children: [
              _fmCabeza(ctx, Icons.send_outlined, 'Procesar', 'PM-001'),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.only(bottom: 20),
                  children: [
                    seccion(Icons.payments_outlined, 'CONTADO', [
                      ficha(
                        Icons.account_balance_wallet_outlined,
                        const Color(0xFF4CAF7A),
                        'Definir',
                        'Medio y montos',
                        'definir',
                      ),
                      ficha(
                        Icons.payments_outlined,
                        const Color(0xFF4CAF7A),
                        'Efectivo',
                        'Total y procesa',
                        de('01') == null ? null : 'efectivo',
                        tip: 'No hay efectivo en los medios de pago',
                      ),
                      ficha(
                        Icons.credit_card,
                        const Color(0xFF4F7BE8),
                        'Tarjeta',
                        'Total y procesa',
                        tarjeta == null ? null : 'tarjeta',
                        tip: 'No hay tarjeta en los medios de pago',
                      ),
                      ficha(
                        Icons.phone_android,
                        const Color(0xFF3B8B7A),
                        'SINPE',
                        'Total y procesa',
                        sinpe == null ? null : 'sinpe',
                        tip: 'No hay SINPE Móvil en los medios de pago',
                      ),
                    ]),
                    seccion(Icons.credit_card, 'CRÉDITO', [
                      ficha(
                        Icons.credit_card,
                        const Color(0xFF6D5BE6),
                        'Crédito',
                        'Facturar a crédito',
                        cred.permitido ? 'credito' : null,
                        tip: cred.motivo,
                      ),
                    ]),
                    seccion(Icons.send_outlined, 'ENVIAR', [
                      ficha(
                        Icons.send_and_archive_outlined,
                        const Color(0xFFF0A030),
                        'Pedido',
                        'Con fecha de hoy',
                        null,
                      ),
                      ficha(
                        Icons.inventory_2_outlined,
                        const Color(0xFF6B7280),
                        'A Cajas',
                        'Punto de venta',
                        null,
                      ),
                      ficha(
                        Icons.mail_outline,
                        const Color(0xFF3B9BE0),
                        'Correo',
                        'Email al cliente',
                        null,
                      ),
                      ficha(
                        Icons.chat_outlined,
                        const Color(0xFF3B8B7A),
                        'WhatsApp',
                        'Directo con PDF',
                        null,
                      ),
                      ficha(
                        Icons.share_outlined,
                        const Color(0xFF5CC86A),
                        'Compartir',
                        'WhatsApp/Telegram',
                        null,
                      ),
                      ficha(
                        Icons.local_drink_outlined,
                        const Color(0xFF3B8B5A),
                        'Consumo de Personal',
                        'A la cuenta del empleado',
                        null,
                      ),
                    ]),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
    switch (accion) {
      case 'definir':
        await _cobrar('');
      case 'efectivo':
        await _cobrar('01', directo: true);
      case 'tarjeta':
        await _cobrar('02', directo: true);
      case 'sinpe':
        await _cobrar('06', directo: true);
      case 'credito':
        await _cobrar('01', credito: true);
    }
  }

  /// El cobro de FactuMóvil: «Total y procesa» sin pantalla (si el medio tiene UNA cuenta), si no VP-001.
  Future<ResultadoCobro?> _fmCobro(
    double total,
    List<MedioPago> medios,
    String medioInicial, {
    String cuenta = '',
    bool directo = false,
    bool credito = false,
  }) async {
    final m = medios.where((x) => x.codigo == medioInicial).firstOrNull;
    if (directo && m != null && (m.cuentas.length <= 1 || cuenta.isNotEmpty)) {
      return ResultadoCobro([
        {
          'medio': m.codigo,
          'cuenta': cuenta.isNotEmpty
              ? cuenta
              : (m.cuentas.isEmpty ? '' : m.cuentas.first),
          'monto': r2(total),
          'comprobante': '',
        },
      ], 0);
    }
    return Navigator.of(context).push<ResultadoCobro>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => _CobroMovil(
          total: total,
          medios: medios,
          medioInicial: medioInicial,
          credito: credito,
          info: _infoCredito(total),
          cajeros: widget.cajeros,
          cliente: doc.cliente,
          documento: doc.proformaOrigen ?? '',
          copiasBase: copias(widget.datos, credito),
          tipoCambio: widget.datos.tipoCambio('USD'),
          almacen: widget.almacen,
          empresa: widget.config.empresa,
        ),
      ),
    );
  }
}

/// Cabeza navy de las hojas de FactuMóvil: ícono, título, código y la X.
Widget _fmCabeza(
  BuildContext context,
  IconData ico,
  String titulo,
  String codigo,
) => Container(
  padding: const EdgeInsets.fromLTRB(16, 14, 10, 14),
  decoration: const BoxDecoration(
    gradient: LinearGradient(colors: [_Fm.navy1, _Fm.navy2]),
    borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
  ),
  child: Row(
    children: [
      Icon(ico, color: Colors.white, size: 24),
      const SizedBox(width: 10),
      Flexible(
        child: Text(
          titulo,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 20,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      const SizedBox(width: 8),
      _fmEtiqueta(codigo, const Color(0x33FFFFFF), Colors.white),
      const Spacer(),
      IconButton(
        tooltip: 'Cerrar',
        onPressed: () => Navigator.pop(context),
        style: IconButton.styleFrom(backgroundColor: const Color(0x33FFFFFF)),
        icon: const Icon(Icons.close, color: Colors.white),
      ),
    ],
  ),
);

class _PagoFm {
  final _BotonMedio boton;
  double monto; // en colones (lo que viaja)
  double usd; // si se cobró en dólares, cuántos
  _PagoFm(this.boton, this.monto, {this.usd = 0});
}

class _CobroMovil extends StatefulWidget {
  final double total;
  final List<MedioPago> medios;
  final String medioInicial;
  final bool credito;
  final InfoCredito info;
  final Cajeros cajeros;
  final Map<String, dynamic> cliente;
  final String documento;
  final int copiasBase;
  final double tipoCambio;
  final Almacen almacen;
  final String empresa;
  const _CobroMovil({
    required this.total,
    required this.medios,
    required this.medioInicial,
    required this.credito,
    required this.info,
    required this.cajeros,
    required this.cliente,
    required this.documento,
    required this.copiasBase,
    required this.tipoCambio,
    required this.almacen,
    required this.empresa,
  });
  @override
  State<_CobroMovil> createState() => _EstadoCobroMovil();
}

class _EstadoCobroMovil extends State<_CobroMovil> {
  late final List<_BotonMedio> botones = _botonesMedio(widget.medios);
  int sel = 0;
  String porDefecto = '';
  String moneda = 'CRC';
  final monto = TextEditingController();
  final copias = TextEditingController();
  final pagos = <_PagoFm>[];

  // crédito
  bool revisando = false;
  Map<String, dynamic>? servidor;
  String autorizo = ''; // el supervisor que autorizó el crédito (314)

  @override
  void initState() {
    super.initState();
    copias.text = '${widget.copiasBase}';
    final i = botones.indexWhere((b) => b.medio.codigo == widget.medioInicial);
    sel = i < 0 ? 0 : i;
    if (widget.medioInicial.isEmpty) _leerDefecto();
    if (widget.credito && widget.info.permitido) _revisar();
  }

  Future<void> _leerDefecto() async {
    final d = await widget.almacen.leerTabla(
      widget.empresa,
      'fm_medio_defecto',
    );
    final clave = d is Map ? '${d['clave'] ?? ''}' : '';
    final i = botones.indexWhere((b) => b.clave == clave);
    if (!mounted) return;
    setState(() {
      porDefecto = i < 0 ? '' : botones[i].etiqueta;
      if (i >= 0) sel = i;
    });
  }

  Future<void> _fijarDefecto() async {
    if (botones.isEmpty) return;
    final b = botones[sel];
    await widget.almacen.guardarTabla(widget.empresa, 'fm_medio_defecto', {
      'clave': b.clave,
    });
    if (mounted) setState(() => porDefecto = b.etiqueta);
  }

  Future<void> _revisar() async {
    setState(() => revisando = true);
    final r = widget.info.revisar == null ? null : await widget.info.revisar!();
    if (!mounted) return;
    setState(() {
      servidor = r ?? {'sinConexion': true};
      revisando = false;
    });
  }

  List<Map<String, dynamic>> get _mapas => [
    for (final p in pagos)
      {
        'medio': p.boton.medio.codigo,
        'cuenta': p.boton.cuenta,
        'monto': r2(p.monto),
        'comprobante': '',
      },
  ];

  void _sumar(_BotonMedio b, double colones, {double usd = 0}) {
    if (!(colones > 0)) return;
    setState(() {
      final p = pagos.where((x) => x.boton.clave == b.clave).firstOrNull;
      if (p == null) {
        pagos.add(_PagoFm(b, r2(colones), usd: usd));
      } else {
        p.monto = r2(p.monto + colones);
        p.usd += usd;
      }
    });
  }

  void _agregarEscrito() {
    final v = leerMonto(monto.text);
    if (v.isNaN || v <= 0 || botones.isEmpty) return;
    final tc = widget.tipoCambio;
    if (moneda == 'USD') {
      _sumar(botones[sel], v * tc, usd: v);
    } else {
      _sumar(botones[sel], v);
    }
    monto.clear();
  }

  double get _falta => cuentasCobro(widget.total, _mapas).falta;

  String get _impide {
    if (!widget.credito) return cuentasCobro(widget.total, _mapas).impide;
    if (!widget.info.permitido) return widget.info.motivo;
    if (revisando) return 'Revisando el saldo y el límite de crédito…';
    final s = servidor;
    if (s != null && s['puede'] == false && autorizo.isEmpty) {
      return '${s['motivo'] ?? 'No se puede vender a crédito.'}';
    }
    return '';
  }

  void _confirmar({bool imprimir = true}) {
    final impide = _impide;
    if (impide.isNotEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(impide), backgroundColor: Marca.rojo),
      );
      return;
    }
    final n = int.tryParse(copias.text.trim());
    final cop = (n == null || n == widget.copiasBase) ? null : n.clamp(0, 5);
    if (widget.credito) {
      Navigator.pop(
        context,
        ResultadoCobro(
          const [],
          0,
          tipoPago: 'credito',
          diasCredito: widget.info.dias,
          imprimir: imprimir,
          copias: cop,
        ),
      );
      return;
    }
    final c = cuentasCobro(widget.total, _mapas);
    Navigator.pop(
      context,
      ResultadoCobro(
        pagosFinales(_mapas, c.vuelto),
        c.vuelto,
        imprimir: imprimir,
        copias: cop,
      ),
    );
  }

  Future<void> _autorizar(bool? marcar) async {
    if (marcar != true) {
      setState(() => autorizo = '');
      return;
    }
    final r = await dialogoSupervisor(
      context,
      widget.cajeros,
      Validacion(
        permiso: '314',
        motivo:
            '${servidor?['motivo'] ?? 'El cliente no tiene crédito disponible.'} Un supervisor con el permiso 314 puede autorizar esta venta a crédito.',
      ),
    );
    if (r is Cajero && mounted) setState(() => autorizo = r.nombre);
  }

  // ── piezas ──
  Widget _tarjeta(Widget hijo, {Color? fondo, Color? borde}) => Container(
    margin: const EdgeInsets.fromLTRB(12, 10, 12, 0),
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: fondo ?? Colors.white,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: borde ?? _Fm.borde),
    ),
    child: hijo,
  );

  Widget _dato(
    String t,
    String v, {
    Color color = _Fm.navy1,
    double tam = 20,
  }) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        t,
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.8,
          color: _Fm.suave,
        ),
      ),
      const SizedBox(height: 2),
      Text(
        v,
        style: TextStyle(
          fontSize: tam,
          fontWeight: FontWeight.w800,
          color: color,
        ),
      ),
    ],
  );

  Widget _arriba() => Row(
    children: [
      Expanded(
        child: _tarjeta(
          _dato(
            'DOCUMENTO',
            widget.documento.isEmpty ? 'Nuevo' : widget.documento,
            tam: 17,
          ),
        ),
      ),
      Expanded(
        child: Padding(
          padding: const EdgeInsets.only(left: 0),
          child: _tarjeta(
            _dato(
              widget.credito ? 'CRÉDITO' : 'PAGAR',
              'CRC ${fmt(widget.total)}',
            ),
          ),
        ),
      ),
    ],
  );

  Widget _boton(int i) {
    final b = botones[i];
    final activo = i == sel;
    return Material(
      color: activo ? _Fm.navy1 : Colors.white,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: () => setState(() => sel = i),
        child: Container(
          height: 46,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: activo ? _Fm.navy1 : _Fm.borde),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                _iconoMedioFm(b.medio.codigo),
                size: 18,
                color: activo ? Colors.white : _Fm.tinta,
              ),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  b.etiqueta,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontWeight: FontWeight.w600,
                    color: activo ? Colors.white : _Fm.tinta,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _pares(List<Widget> w) => Column(
    children: [
      for (var i = 0; i < w.length; i += 2)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(
            children: [
              Expanded(child: w[i]),
              const SizedBox(width: 8),
              Expanded(child: i + 1 < w.length ? w[i + 1] : const SizedBox()),
            ],
          ),
        ),
    ],
  );

  Widget _billete(String mon, double v) {
    final usd = mon == 'USD';
    return Material(
      color: usd ? const Color(0xFFFFF4E5) : const Color(0xFFF1F6FD),
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: botones.isEmpty
            ? null
            : () => usd
                  ? _sumar(botones[sel], v * widget.tipoCambio, usd: v)
                  : _sumar(botones[sel], v),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: usd ? const Color(0xFFF2C98A) : _Fm.borde,
            ),
          ),
          child: Text(
            '$mon${fmt(v, 0)}',
            style: TextStyle(
              fontWeight: FontWeight.w700,
              color: usd ? const Color(0xFFB45309) : _Fm.navy1,
            ),
          ),
        ),
      ),
    );
  }

  Widget _todo(_BotonMedio b) => Material(
    color: _Fm.navy1,
    borderRadius: BorderRadius.circular(8),
    child: InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => _sumar(b, _falta),
      child: Container(
        height: 50,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(_iconoMedioFm(b.medio.codigo), color: Colors.white, size: 18),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                'Todo ${b.etiqueta}',
                maxLines: 2,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ],
        ),
      ),
    ),
  );

  Widget _medios() {
    final tc = widget.tipoCambio;
    final estilo = Theme.of(context).textTheme.bodyMedium!
        .copyWith(fontSize: 16, fontWeight: FontWeight.w600, color: _Fm.tinta);
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 10, 12, 0),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: _Fm.borde),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: const BoxDecoration(
              color: Color(0xFFE6EEF8),
              borderRadius: BorderRadius.vertical(top: Radius.circular(12)),
            ),
            child: const Row(
              children: [
                Icon(Icons.account_balance_wallet_outlined, color: _Fm.navy1),
                SizedBox(width: 8),
                Text(
                  'MEDIOS DE PAGO',
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    letterSpacing: 1,
                    color: _Fm.navy1,
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _pares([for (var i = 0; i < botones.length; i++) _boton(i)]),
                const SizedBox(height: 10),
                Row(
                  children: [
                    OutlinedButton.icon(
                      onPressed: _fijarDefecto,
                      icon: const Icon(
                        Icons.star,
                        color: Color(0xFFF2B01E),
                        size: 18,
                      ),
                      label: const Text('Fijar default'),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text.rich(
                        TextSpan(
                          text: 'Default: ',
                          style: const TextStyle(color: _Fm.suave),
                          children: [
                            TextSpan(
                              text: porDefecto.isEmpty ? '—' : porDefecto,
                              style: const TextStyle(
                                color: _Fm.navy1,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
                if (botones.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Text(
                    '${botones[sel].etiqueta}:',
                    style: const TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                      color: _Fm.navy1,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      Container(
                        height: 48,
                        padding: const EdgeInsets.symmetric(horizontal: 10),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: _Fm.borde),
                        ),
                        child: DropdownButtonHideUnderline(
                          child: DropdownButton<String>(
                            value: moneda,
                            style: estilo,
                            items: [
                              const DropdownMenuItem(
                                value: 'CRC',
                                child: Text('CRC'),
                              ),
                              if (tc > 0)
                                const DropdownMenuItem(
                                  value: 'USD',
                                  child: Text('USD'),
                                ),
                            ],
                            onChanged: (v) =>
                                setState(() => moneda = v ?? 'CRC'),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: TextField(
                          controller: monto,
                          textAlign: TextAlign.right,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          style: estilo.copyWith(fontSize: 18),
                          decoration: const InputDecoration(
                            hintText: '0.00',
                            isDense: true,
                          ),
                          onSubmitted: (_) => _agregarEscrito(),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SizedBox(
                        width: 54,
                        height: 48,
                        child: Material(
                          color: _Fm.navy1,
                          borderRadius: BorderRadius.circular(8),
                          child: InkWell(
                            borderRadius: BorderRadius.circular(8),
                            onTap: _agregarEscrito,
                            child: const Icon(Icons.add, color: Colors.white),
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (moneda == 'USD')
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        'Tipo de cambio: ₡${fmt(tc)}',
                        style: const TextStyle(fontSize: 12, color: _Fm.suave),
                      ),
                    ),
                  const SizedBox(height: 10),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final b in const [
                        1000.0,
                        2000.0,
                        5000.0,
                        10000.0,
                        20000.0,
                      ])
                        _billete('CRC', b),
                      if (tc > 0)
                        for (final b in const [
                          1.0,
                          5.0,
                          10.0,
                          20.0,
                          50.0,
                          100.0,
                        ])
                          _billete('USD', b),
                    ],
                  ),
                  const SizedBox(height: 4),
                  _pares([for (final b in botones) _todo(b)]),
                ],
                for (var i = 0; i < pagos.length; i++) _filaPago(i),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _filaPago(int i) {
    final p = pagos[i];
    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFD),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _Fm.borde),
      ),
      child: Row(
        children: [
          Icon(_iconoMedioFm(p.boton.medio.codigo), color: _Fm.navy1),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  p.boton.etiqueta,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                    color: _Fm.tinta,
                  ),
                ),
                if (p.usd > 0)
                  Text(
                    'USD ${fmt(p.usd)}',
                    style: const TextStyle(fontSize: 12, color: _Fm.suave),
                  ),
              ],
            ),
          ),
          Text(
            'CRC ${fmt(p.monto)}',
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: _Fm.navy1,
            ),
          ),
          IconButton(
            tooltip: 'Quitar',
            onPressed: () => setState(() => pagos.removeAt(i)),
            icon: const Icon(Icons.delete_outline, color: Marca.rojo),
          ),
        ],
      ),
    );
  }

  Widget _resumen() {
    final c = cuentasCobro(widget.total, _mapas);
    final (t, v, color) = c.falta > 0
        ? ('FALTA', c.falta, Marca.ambar)
        : c.vuelto > 0
        ? ('VUELTO', c.vuelto, Marca.verdeOscuro)
        : ('COMPLETO', 0.0, Marca.verdeOscuro);
    return Row(
      children: [
        Expanded(child: _tarjeta(_dato('PAGADO', 'CRC ${fmt(c.pagado)}'))),
        Expanded(child: _tarjeta(_dato(t, 'CRC ${fmt(v)}', color: color))),
      ],
    );
  }

  // ── Crédito (foto 11) ──
  Widget _credito() {
    final s = servidor;
    final c = widget.cliente;
    double n(String k) => ((s?[k] as num?) ?? 0).toDouble();
    final hay = s != null && s['sinConexion'] != true;
    Widget casilla(String t, String v, Color fondo, Color tinta) => Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      decoration: BoxDecoration(
        color: fondo,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: tinta.withValues(alpha: 0.25)),
      ),
      child: Column(
        children: [
          Text(
            t,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: tinta,
            ),
          ),
          const SizedBox(height: 2),
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              'CRC$v',
              style: TextStyle(fontWeight: FontWeight.w800, color: tinta),
            ),
          ),
        ],
      ),
    );
    const azul = Color(0xFFF4F8FD), tAzul = _Fm.navy1;
    final vencido = n('vencido'), saldo = n('saldo');
    final f = DateTime.now().add(Duration(days: widget.info.dias));
    final venc =
        '${f.day.toString().padLeft(2, '0')}/${f.month.toString().padLeft(2, '0')}/${f.year}';
    final bloqueo = s != null && s['puede'] == false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _tarjeta(
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const CircleAvatar(
                    radius: 24,
                    backgroundColor: _Fm.navy2,
                    child: Icon(Icons.badge_outlined, color: Colors.white),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${c['nombre'] ?? ''}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w700,
                            color: _Fm.navy1,
                          ),
                        ),
                        Text(
                          'Código: ${c['codigo'] ?? ''}',
                          style: const TextStyle(color: _Fm.suave),
                        ),
                      ],
                    ),
                  ),
                  _dato('PLAZO', '${widget.info.dias} días', tam: 17),
                ],
              ),
              if (!widget.info.permitido)
                _alerta(widget.info.motivo)
              else if (revisando)
                const Padding(
                  padding: EdgeInsets.only(top: 12),
                  child: LinearProgressIndicator(),
                )
              else if (!hay)
                _alerta(
                  'Sin internet: no se revisó el saldo ni el límite del cliente.',
                  color: Marca.ambar,
                )
              else ...[
                _pares([
                  casilla('LÍMITE', fmt(n('limite')), azul, tAzul),
                  casilla(
                    'VENCIDO (${s['docsVencidos'] ?? 0})',
                    fmt(vencido),
                    vencido > 0 ? const Color(0xFFFCE8E8) : azul,
                    vencido > 0 ? Marca.rojo : tAzul,
                  ),
                  casilla(
                    'SIN VENCER',
                    fmt(saldo > vencido ? saldo - vencido : 0),
                    const Color(0xFFEAF7EE),
                    Marca.verdeOscuro,
                  ),
                  casilla('USADO', fmt(saldo), azul, tAzul),
                  casilla('DISPONIBLE', fmt(n('disponible')), azul, tAzul),
                  casilla('ESTA FACTURA', fmt(widget.total), azul, tAzul),
                ]),
                if (bloqueo) ...[
                  _alerta('${s['motivo'] ?? 'No puede facturar a crédito.'}'),
                  Container(
                    margin: const EdgeInsets.only(top: 10),
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFF7ED),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: const Color(0xFFF2C98A)),
                    ),
                    child: CheckboxListTile(
                      value: autorizo.isNotEmpty,
                      onChanged: _autorizar,
                      controlAffinity: ListTileControlAffinity.leading,
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        autorizo.isEmpty
                            ? 'Autorizar a crédito con clave de supervisor'
                            : 'Autorizado por $autorizo',
                        style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          color: Color(0xFF9A3412),
                        ),
                      ),
                    ),
                  ),
                ],
              ],
            ],
          ),
        ),
        Container(
          margin: const EdgeInsets.fromLTRB(12, 10, 12, 0),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: _Fm.borde),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Container(
                padding: const EdgeInsets.all(12),
                decoration: const BoxDecoration(
                  color: Color(0xFFE6EEF8),
                  borderRadius: BorderRadius.vertical(top: Radius.circular(12)),
                ),
                child: const Row(
                  children: [
                    Icon(Icons.settings_outlined, color: _Fm.navy1),
                    SizedBox(width: 8),
                    Text(
                      'CONDICIONES',
                      style: TextStyle(
                        fontWeight: FontWeight.w700,
                        letterSpacing: 1,
                        color: _Fm.navy1,
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Expanded(
                      child: _dato(
                        'DÍAS CRÉDITO',
                        '${widget.info.dias}',
                        tam: 17,
                      ),
                    ),
                    Expanded(child: _dato('FECHA VENCE', venc, tam: 17)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _alerta(String t, {Color color = Marca.rojo}) => Container(
    margin: const EdgeInsets.only(top: 10),
    padding: const EdgeInsets.all(10),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.1),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: color.withValues(alpha: 0.3)),
    ),
    child: Row(
      children: [
        Icon(Icons.warning_amber_rounded, color: color),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            t,
            style: TextStyle(color: color, fontWeight: FontWeight.w600),
          ),
        ),
      ],
    ),
  );

  Widget _pie() {
    final impide = _impide;
    final listo = impide.isEmpty;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: _Fm.borde)),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  flex: 5,
                  child: SizedBox(
                    height: 48,
                    child: OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                      ),
                      onPressed: () => Navigator.pop(context),
                      child: const Text('Cancelar'),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 70,
                  child: Column(
                    children: [
                      const Text(
                        'Copias',
                        style: TextStyle(fontSize: 12, color: _Fm.suave),
                      ),
                      TextField(
                        controller: copias,
                        textAlign: TextAlign.center,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(isDense: true),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  flex: 6,
                  child: SizedBox(
                    height: 48,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFFC2671F),
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                      ),
                      onPressed: listo
                          ? () => _confirmar(imprimir: false)
                          : null,
                      child: const Text('No Imprime'),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            SizedBox(
              height: 52,
              child: FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF3E9A4E),
                ),
                onPressed: listo ? _confirmar : null,
                icon: const Icon(Icons.check_circle_outline),
                label: const Text(
                  'Confirmar',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final impide = _impide;
    return Scaffold(
      backgroundColor: _Fm.fondo,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _fmCabeza(
              context,
              Icons.point_of_sale_outlined,
              widget.credito ? 'Venta a Crédito' : 'Cobro de Factura',
              'VP-001',
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.only(bottom: 16),
                children: [
                  _arriba(),
                  if (widget.credito)
                    _credito()
                  else ...[
                    _medios(),
                    _resumen(),
                    if (pagos.isNotEmpty && impide.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                        child: Text(
                          impide,
                          style: const TextStyle(color: Marca.rojo),
                        ),
                      ),
                  ],
                ],
              ),
            ),
            _pie(),
          ],
        ),
      ),
    );
  }
}
