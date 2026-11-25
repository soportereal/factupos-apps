/// CREAR y EDITAR clientes, también SIN internet (#3957) — réplica de FSCliente (factusuper_cliente.js, MV-110) +
/// FSLocal.clienteCrear/clienteEditar/clienteRemapear + FSEnvio.enviarCliente.
///
/// Dueño: «debe poder editar el cliente offline y en algún momento se actualiza cuando tenga internet» · «aplica los
/// mismos permisos de FactuPOS» · «primero se manda la orden de editar el cliente, porque si no la factura sale sin los
/// datos editados».
///   · permisos 311 (crear) y 313 (editar), los mismos que exige el servidor; el genérico (SN) no se edita;
///   · las MISMAS validaciones (param 125 = 1 → cédula, correo de facturación y, al crear, la actividad);
///   · el cambio se aplica YA en el equipo y sube por cliente_guardar.php ANTES que las ventas;
///   · un cliente NUEVO lleva código provisional N-caja-sucursal-usuario-hhmmss-día; el REAL lo da el servidor y se
///     cambia en todo el equipo (cliente, ventas pendientes, venta en curso). Solo con cédula NUEVA.
/// 🔑 La app usa siempre la ventana básica (MV-110): la web, con internet, abre el modal oficial MCL-001 de FactuDesk,
///    que no está en las APIs de la llave.
library;

import '../datos/almacen.dart';
import '../datos/conexion.dart';
import 'datos_caja.dart';
import 'fondo.dart' show idControl;
import 'registro.dart';

const camposCliente = [
  'tipo_cedula',
  'cedula',
  'nombre',
  'comercial',
  'email_factura',
  'email_general',
  'email_cobro',
  'telefonos',
  'contacto',
  'direccion',
  'tipo_precio',
  'descuento',
  'moneda',
  'monto_credito',
  'plazo',
  'actividad',
];
const checksCliente = ['exento', 'no_forzar_credito'];
const _numericos = ['tipo_precio', 'descuento', 'monto_credito', 'plazo'];

String _t(Object? v) => '${v ?? ''}'.trim();

/// Caracteres que se cuelan al copiar un correo y no se ven (el servidor los rechaza, #1473).
final _invisibles = RegExp('[­​-‏ - ⁠﻿]');
String correoProblema(String lista, String nombre) {
  for (final c in lista.split(RegExp(r'[,;\s]+')).where((x) => x.isNotEmpty)) {
    if (_invisibles.hasMatch(c)) {
      return '$nombre: «${c.replaceAll(_invisibles, '')}» trae un carácter invisible pegado; vuelva a escribirlo.';
    }
    if (!RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(c)) {
      return '$nombre: el correo «$c» no es válido.';
    }
  }
  return '';
}

String normCedula(Object? c) =>
    _t(c).replaceAll(RegExp(r'[^0-9A-Za-z]'), '').toUpperCase();

class ResumenClientes {
  int guardados = 0;
  final List<String> rechazados = [];

  /// '' = no se detuvo.
  String detenida = '';
  bool sinRed = false;

  /// provisional → real
  final Map<String, String> remapeos = {};
}

class ClientesLocal {
  final Almacen almacen;
  final ConfigCaja config;
  final DatosCaja datos;
  final Registro? registro;
  final List<String> servidores;
  ClientesLocal(
    this.almacen,
    this.config,
    this.datos, {
    this.registro,
    this.servidores = servidoresFactuPOS,
  });

  static const tabla = 'clientes_pendientes';

  bool get conFactura => datos.param(125, '0') == '1';

  Future<List<Map<String, dynamic>>> pendientes() async {
    final v = await almacen.leerTabla(config.empresa, tabla);
    return v is List
        ? [
            for (final x in v)
              if (x is Map) Map<String, dynamic>.from(x),
          ]
        : <Map<String, dynamic>>[];
  }

  Future<void> _guardarPendientes(List<Map<String, dynamic>> l) =>
      almacen.guardarTabla(config.empresa, tabla, l);

  /// Las validaciones de FSCliente.validar (las del guardado de FactuDesk). '' = está bien.
  String validar(Map<String, dynamic> v, {required bool esNuevo}) {
    final fe = conFactura;
    if (_t(v['nombre']).isEmpty) return 'El nombre es obligatorio.';
    if (fe && _t(v['cedula']).isEmpty) {
      return 'La cédula es requerida (la empresa emite factura electrónica).';
    }
    if (fe && _t(v['email_factura']).isEmpty) {
      return 'El correo de facturación es requerido (la empresa emite factura electrónica).';
    }
    if (fe && esNuevo && _t(v['actividad']).isEmpty) {
      return 'La actividad económica es requerida (la empresa emite factura electrónica).';
    }
    if (_t(v['actividad']).isNotEmpty &&
        esNuevo &&
        !RegExp(r'^\d{4}\.\d$').hasMatch(_t(v['actividad']))) {
      return 'La actividad económica va con el formato de Hacienda: cuatro números, punto y uno (ej. 4711.0).';
    }
    if (_t(v['cedula']).isNotEmpty &&
        !RegExp(r'^[0-9A-Za-z-]+$').hasMatch(_t(v['cedula']))) {
      return 'La cédula solo lleva números (sin espacios).';
    }
    for (final (k, n) in const [
      ('email_general', 'Email General'),
      ('email_factura', 'Email Factura'),
      ('email_cobro', 'Email Estado de Cuenta'),
    ]) {
      final p = correoProblema(_t(v[k]), n);
      if (p.isNotEmpty) return p;
    }
    final tp = double.tryParse(_t(v['tipo_precio'])) ?? double.nan;
    if (!(tp >= 1 && tp <= 10)) return 'El tipo de precio va de 1 a 10.';
    final d =
        double.tryParse(
          _t(v['descuento']).isEmpty ? '0' : _t(v['descuento']),
        ) ??
        double.nan;
    if (!(d >= 0 && d <= 100)) return 'El descuento va de 0 a 100 %.';
    final pl =
        double.tryParse(_t(v['plazo']).isEmpty ? '0' : _t(v['plazo'])) ??
        double.nan;
    if (!(pl >= 0) || pl != pl.truncateToDouble()) {
      return 'El plazo son días enteros (0 o más).';
    }
    final mc =
        double.tryParse(
          _t(v['monto_credito']).isEmpty ? '0' : _t(v['monto_credito']),
        ) ??
        double.nan;
    if (!(mc >= 0)) return 'El monto de crédito no puede ser negativo.';
    return '';
  }

  /// Valores del formulario tal como los guarda la web: el comercial vacío = el nombre (#236), números como número.
  static Map<String, dynamic> normalizar(Map<String, dynamic> v) {
    final out = <String, dynamic>{};
    for (final k in camposCliente) {
      final x = _t(v[k]);
      out[k] = _numericos.contains(k)
          ? (num.tryParse(x.isEmpty ? '0' : x) ?? 0)
          : x;
    }
    for (final k in checksCliente) {
      out[k] = (v[k] == true || _t(v[k]) == '1') ? 1 : 0;
    }
    if (_t(out['comercial']).isEmpty) out['comercial'] = out['nombre'];
    return out;
  }

  Map<String, dynamic>? porCedula(String cedula) {
    final k = normCedula(cedula);
    if (k.isEmpty) return null;
    for (final c in datos.clientes.values) {
      if (normCedula(c['cedula']) == k) return c;
    }
    return null;
  }

  Future<void> _guardarClientes() => almacen.guardarTabla(
    config.empresa,
    'clientes',
    datos.clientes.values.toList(),
  );

  /// Etapa 18 — alta: permiso 311 y cédula NUEVA. → (cliente, error)
  Future<(Map<String, dynamic>?, String)> crear(
    Map<String, dynamic> formulario,
    String usuario, {
    DateTime? cuando,
  }) async {
    if (!datos.tienePermiso(usuario, '311')) {
      return (null, 'Sin permiso para crear clientes (311)');
    }
    final v = normalizar(formulario);
    final e = validar(v, esNuevo: true);
    if (e.isNotEmpty) return (null, e);
    if (_t(v['cedula']).isEmpty) {
      return (null, 'La cédula es obligatoria para crear un cliente.');
    }
    final ya = porCedula(_t(v['cedula']));
    if (ya != null) {
      return (
        null,
        'Ya existe el cliente ${ya['codigo']} · ${ya['nombre']} con esa cédula: elíjalo en Clientes (F3).',
      );
    }
    final ahora = cuando ?? DateTime.now();
    final id = 'N-${idControl(datos, usuario, ahora)}';
    final pend = await pendientes();
    if (pend.any((p) => p['codigo'] == id) || datos.cliente(id) != null) {
      return (null, 'Espere un segundo y vuelva a guardar.');
    }
    final iso = ahora.toUtc().toIso8601String();
    final nuevo = {...v, 'codigo': id, '_nuevo': true};
    datos.clientes[id.toUpperCase()] = nuevo;
    await _guardarClientes();
    pend.add({
      'nuevo': true,
      'codigo': id,
      'idProceso': id,
      'cambios': v,
      'desde': iso,
      'fecha': iso,
      'estado': 'pendiente',
      'intentos': 0,
      'usuario': usuario,
    });
    await _guardarPendientes(pend);
    return (nuevo, '');
  }

  /// Edición: permiso 313; solo lo que cambió (la actividad de uno que ya existe no se cambia acá).
  /// → (cliente actualizado o null si no hubo cambios, error)
  Future<(Map<String, dynamic>?, String)> editar(
    String codigo,
    Map<String, dynamic> formulario,
    String usuario, {
    DateTime? cuando,
  }) async {
    if (codigo.isEmpty || codigo.toUpperCase() == 'SN') {
      return (null, 'Elija un cliente (F3) para editarlo');
    }
    if (!datos.tienePermiso(usuario, '313')) {
      return (null, 'Sin permiso para editar clientes (313)');
    }
    final original = datos.cliente(codigo) ?? {'codigo': codigo};
    final v = normalizar(formulario);
    final e = validar(v, esNuevo: false);
    if (e.isNotEmpty) return (null, e);
    final cambios = <String, dynamic>{};
    for (final k in [...camposCliente, ...checksCliente]) {
      if (k == 'actividad') continue;
      final antes = original[k], ahora = v[k];
      final igual = ahora is num
          ? (num.tryParse(_t(antes).isEmpty ? '0' : _t(antes)) ?? 0) == ahora
          : _t(antes) == _t(ahora);
      if (!igual) cambios[k] = ahora;
    }
    if (cambios.isEmpty) return (null, '');
    original.addAll(cambios);
    datos.clientes[codigo.toUpperCase()] = original;
    await _guardarClientes();
    final pend = await pendientes();
    final i = pend.indexWhere((p) => p['codigo'] == codigo);
    final previo = i >= 0
        ? pend[i]
        : <String, dynamic>{'codigo': codigo, 'cambios': {}};
    final iso = (cuando ?? DateTime.now()).toUtc().toIso8601String();
    final reg = <String, dynamic>{
      if (previo['nuevo'] == true) 'nuevo': true,
      'codigo': codigo,
      'idProceso':
          previo['idProceso'] ??
          'C-${idControl(datos, usuario, cuando ?? DateTime.now())}',
      'cambios': {...(previo['cambios'] as Map? ?? {}), ...cambios},
      // `desde` = la PRIMERA edición pendiente (su lugar en la cola en orden). `fecha` = la última.
      'desde': previo['desde'] ?? previo['fecha'] ?? iso,
      'fecha': iso,
      'estado': 'pendiente',
      'intentos': previo['intentos'] ?? 0,
      'usuario': usuario,
    };
    if (i >= 0) {
      pend[i] = reg;
    } else {
      pend.add(reg);
    }
    await _guardarPendientes(pend);
    return (original, '');
  }

  /// El servidor dio el código REAL: cambia en el cliente del equipo y en los pendientes (si lo editaron mientras se
  /// creaba, esa edición queda como EDICIÓN del cliente real).
  Future<void> _remapear(String provisional, String real) async {
    final c = datos.clientes.remove(provisional.toUpperCase());
    if (c != null && datos.cliente(real) == null) {
      datos.clientes[real.toUpperCase()] = {...c, 'codigo': real}
        ..remove('_nuevo');
    }
    await _guardarClientes();
  }

  /// Sube lo pendiente, en orden (el más viejo primero). Un alta rechazada NO sale de la cola: sus facturas no pueden
  /// adelantarse (se corrige editando el cliente). Un error que se reintenta DETIENE la cola.
  Future<ResumenClientes> subir() async {
    final r = ResumenClientes();
    var pend =
        (await pendientes())
            .where((c) => c['estado'] != 'rechazado' || c['nuevo'] == true)
            .toList()
          ..sort(
            (a, b) => '${a['desde'] ?? a['fecha']}'.compareTo(
              '${b['desde'] ?? b['fecha']}',
            ),
          );
    for (final c in pend) {
      final nuevo = c['nuevo'] == true;
      final cuerpo = nuevo
          ? {'nuevo': true, 'idProceso': c['idProceso'], 'datos': c['cambios']}
          : {'codigo': c['codigo'], 'cambios': c['cambios']};
      final con = Conexion(
        llave: config.llave,
        cajero: _t(c['usuario']),
        servidores: servidores,
      );
      Map<String, dynamic> d;
      try {
        d = await con.post('cliente_guardar.php', cuerpo);
      } on ErrorConexion catch (e) {
        r.detenida = e.sinInternet ? 'Sin internet' : e.mensaje;
        r.sinRed = e.sinInternet && e.motivo != 'tiempo';
        break;
      } finally {
        con.cerrar();
      }
      final estado = _t(d['estado']);
      final todos = await pendientes();
      final i = todos.indexWhere((x) => x['codigo'] == c['codigo']);
      if (estado == 'guardado' && nuevo) {
        final real = _t(d['codigo']);
        if (real.isEmpty) {
          r.detenida = 'El servidor creó el cliente pero no devolvió su código';
          break;
        }
        if (i >= 0) {
          // ¿lo editaron mientras se creaba? Si la «fecha» es posterior al alta, queda como edición del real.
          final p = todos.removeAt(i);
          if (p['fecha'] != c['fecha']) {
            todos.add(
              {
                ...p,
                'codigo': real,
                'idProceso': 'C${_t(p['idProceso']).substring(1)}',
                'estado': 'pendiente',
                'error': '',
              }..remove('nuevo'),
            );
          }
        }
        await _guardarPendientes(todos);
        await _remapear(_t(c['codigo']), real);
        r.remapeos[_t(c['codigo'])] = real;
        r.guardados++;
        await registro?.anotar(
          idProceso: _t(c['idProceso']),
          tipo: 'cliente',
          json: cuerpo,
          estado: 'procesado',
          resultado:
              'Cliente creado: $real${d['existente'] == true ? ' (ya existía con esa cédula)' : ''}',
        );
        continue;
      }
      if (estado == 'guardado') {
        // Si lo volvieron a editar mientras subía, queda lo nuevo pendiente.
        if (i >= 0 && todos[i]['fecha'] == c['fecha']) todos.removeAt(i);
        await _guardarPendientes(todos);
        r.guardados++;
        await registro?.anotar(
          idProceso: _t(c['idProceso']),
          tipo: 'cliente',
          json: cuerpo,
          estado: 'procesado',
          resultado: 'Cliente ${c['codigo']} actualizado',
        );
        continue;
      }
      final rechazado = estado == 'rechazado';
      final msg = _t(d['mensaje']).isEmpty ? estado : _t(d['mensaje']);
      if (i >= 0) {
        todos[i] = {
          ...todos[i],
          'estado': rechazado ? 'rechazado' : 'error',
          'error': msg,
          'intentos': ((todos[i]['intentos'] as num?) ?? 0) + 1,
        };
        await _guardarPendientes(todos);
      }
      await registro?.anotar(
        idProceso: _t(c['idProceso']),
        tipo: 'cliente',
        json: cuerpo,
        estado: rechazado ? 'rechazado' : 'pendiente',
        error: msg,
      );
      if (rechazado && !nuevo) {
        r.rechazados.add('${c['codigo']}: $msg');
        continue; // una edición rechazada sale de la cola y no la frena
      }
      r.detenida =
          'La cola espera por ${nuevo ? 'el alta' : 'la edición'} del cliente ${c['codigo']}: $msg';
      break;
    }
    return r;
  }
}
