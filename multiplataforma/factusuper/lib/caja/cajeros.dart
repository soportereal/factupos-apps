/// Entrada del cajero (#3957) — réplica de la web (factusuper_local.js: usuariosConPermiso / validarUsuarioClave):
/// USUARIO + CLAVE (dueño: «con solo la clave, dos usuarios con la misma no se distinguen»), con permiso de facturar
/// (653), validada EN EL EQUIPO con bcrypt contra la copia bajada (`catalogos.usuarios`): funciona sin internet.
library;

import 'package:bcrypt/bcrypt.dart';

import '../app/sabor.dart';

/// 653 en FactuSuper · 654 en FactuMóvil (ver app/sabor.dart).
String get permisoFacturar => sabor.permiso;

class Cajero {
  final String usuario, nombre;
  const Cajero(this.usuario, this.nombre);
}

class Cajeros {
  final List<Map<String, dynamic>> _usuarios;
  final List<Map<String, dynamic>> _permisos;
  Cajeros(Map<String, dynamic>? catalogos)
    : _usuarios = _filas(catalogos?['usuarios']),
      _permisos = _filas(catalogos?['permisos_usuario']);

  static List<Map<String, dynamic>> _filas(Object? v) => v is List
      ? [
          for (final x in v)
            if (x is Map) Map<String, dynamic>.from(x),
        ]
      : <Map<String, dynamic>>[];
  static String _t(Object? v) => '${v ?? ''}'.trim();

  bool _tiene(Map<String, dynamic> u, String permiso) {
    final cod = _t(u['usuario']);
    final propios = u['permisos'];
    if (propios is List && propios.map(_t).contains(permiso)) return true;
    return _permisos.any(
      (p) => _t(p['usuario']) == cod && _t(p['permiso']) == permiso,
    );
  }

  /// Los que pueden entrar (tienen clave y el permiso), por nombre: la gente no se sabe su código.
  List<Cajero> conPermiso([String? permisoPedido]) {
    final permiso = permisoPedido ?? permisoFacturar;
    final l = _usuarios
        .where((u) => _t(u['hash']).isNotEmpty && _tiene(u, permiso))
        .map(
          (u) => Cajero(
            _t(u['usuario']),
            _t(u['nombre']).isEmpty ? _t(u['usuario']) : _t(u['nombre']),
          ),
        )
        .toList();
    l.sort((a, b) => a.nombre.toLowerCase().compareTo(b.nombre.toLowerCase()));
    return l;
  }

  /// null = entró; si no, el motivo (sin decir cuál de los dos datos falló).
  String? validar(
    String usuario,
    String clave, [
    String? permisoPedido,
  ]) {
    final permiso = permisoPedido ?? permisoFacturar;
    usuario = usuario.trim().toUpperCase();
    if (usuario.isEmpty) return 'Elija su nombre';
    if (clave.isEmpty) return 'Escriba su clave';
    String sinCeros(String c) =>
        c.trim().toUpperCase().replaceFirst(RegExp(r'^0+(?=.)'), '');
    Map<String, dynamic>? u;
    for (final x in _usuarios) {
      if (_t(x['usuario']).toUpperCase() == usuario) {
        u = x;
        break;
      }
    }
    u ??= _usuarios
        .where((x) => sinCeros(_t(x['usuario'])) == sinCeros(usuario))
        .firstOrNull;
    const malo = 'Usuario o clave incorrectos';
    if (u == null) return malo;
    // PHP guarda $2y$; es el mismo algoritmo que $2b$.
    final hash = _t(u['hash']).replaceFirst(RegExp(r'^\$2y\$'), r'$2b$');
    bool ok;
    try {
      ok = BCrypt.checkpw(clave, hash);
    } catch (_) {
      ok = false;
    }
    if (!ok) return malo;
    return _tiene(u, permiso)
        ? null
        : '${_t(u['nombre'])} no tiene permiso para facturar ($permiso)';
  }

  /// Clave de SUPERVISOR (sin internet) — réplica de identificarPorClave(): con la clave se obtiene el usuario y se
  /// pregunta si ESE usuario tiene el permiso. Si dos comparten clave, gana el que lo tiene.
  /// → (cajero, null) si autoriza · (null o el usuario, motivo) si no.
  (Cajero?, String?) identificarPorClave(String clave, String permiso) {
    clave = clave.trim();
    if (clave.isEmpty) return (null, 'Escriba la clave');
    final lista = _usuarios.where((u) => _t(u['hash']).isNotEmpty).toList()
      ..sort((a, b) {
        final ta = _tiene(a, permiso) ? 1 : 0, tb = _tiene(b, permiso) ? 1 : 0;
        return tb != ta
            ? tb - ta
            : _t(a['usuario']).compareTo(_t(b['usuario']));
      });
    for (final u in lista) {
      bool ok;
      try {
        ok = BCrypt.checkpw(
          clave,
          _t(u['hash']).replaceFirst(RegExp(r'^\$2y\$'), r'$2b$'),
        );
      } catch (_) {
        ok = false;
      }
      if (!ok) continue;
      final c = Cajero(_t(u['usuario']), _t(u['nombre']));
      return _tiene(u, permiso)
          ? (c, null)
          : (c, '${c.nombre} no tiene el permiso $permiso');
    }
    return (null, 'Clave incorrecta');
  }

  Cajero? buscar(String usuario) {
    for (final x in _usuarios) {
      if (_t(x['usuario']) == usuario)
        return Cajero(
          usuario,
          _t(x['nombre']).isEmpty ? usuario : _t(x['nombre']),
        );
    }
    return null;
  }
}
