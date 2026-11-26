/// Las DOS apps que salen de este mismo código (#3957, dueño 25-nov-2026): FactuSuper (la caja, 653) y FactuMóvil (la
/// facturación del vendedor en el celular, 654; «nativa, también sin internet»). Comparten motor, catálogos en el
/// equipo, cola, impresión y llave; cambia el nombre, quién entra y el archivo de la app. Lo fija el punto de entrada
/// (lib/main.dart · lib/main_factumovil.dart) ANTES de arrancar.
library;

class Sabor {
  final String id, nombre, permiso, queHace, apk;
  const Sabor({required this.id, required this.nombre, required this.permiso, required this.queHace, required this.apk});
  bool get esMovil => id == 'factumovil';
}

const saborFactuSuper = Sabor(
  id: 'factusuper',
  nombre: 'FactuSuper',
  permiso: '653',
  queHace: 'facturar',
  apk: 'FactuSuper-Android.apk',
);

const saborFactuMovil = Sabor(
  id: 'factumovil',
  nombre: 'FactuMóvil',
  permiso: '654',
  queHace: 'facturar en FactuMóvil',
  apk: 'FactuMovil-Android.apk',
);

/// La app que está corriendo (la pone el punto de entrada).
Sabor sabor = saborFactuSuper;
