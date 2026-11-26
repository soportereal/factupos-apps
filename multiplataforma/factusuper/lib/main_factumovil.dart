/// FactuMóvil — la facturación del vendedor en el celular, como app nativa que vende también sin internet (#3957,
/// dueño 25-nov-2026). Mismo código que FactuSuper (motor, catálogos en el equipo, cola, impresión, llave); entran los
/// usuarios con permiso 654. Android: `flutter build apk --flavor factumovil -t lib/main_factumovil.dart`.
library;

import 'app/sabor.dart';
import 'main.dart' as app;

Future<void> main() => app.arrancar(saborFactuMovil);
