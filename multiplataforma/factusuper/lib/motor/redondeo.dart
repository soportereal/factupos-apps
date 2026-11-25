/// Redondeo de FactuSuper — réplica EXACTA de `redondear()` de
/// factupos.com/modules/facturacion/factusuper/js/factusuper_documento.js (FSDoc).
///
/// Es el ROUND de SQL Server (mitad hacia afuera) sobre DECIMAL exacto: primero se limpia el ruido
/// binario del double (15 cifras significativas) y recién ahí se redondea, corriendo la coma por TEXTO
/// (`'e' + d`) igual que el JS. 🔑 El servidor graba las líneas tal cual llegan (no recalcula): este
/// redondeo tiene que dar lo mismo que el de la pantalla web, céntimo por céntimo. Lo prueba
/// test/motor_ab_test.dart contra el JS real.
library;

double redondear(num? valor, int decimales) {
  final n = (valor ?? 0).toDouble();
  if (n.isNaN) return 0; // Number(NaN) || 0 = 0
  final s = n < 0 ? -1 : 1;
  final limpio = double.parse(n.abs().toStringAsPrecision(15));
  // 🪤 Con valores diminutos (< 1e-6) el JS arma «1.5e-7e2» = NaN, y eso CAMBIA decisiones (p. ej. el «pegado»
  //    del descuento por monto: `NaN <= 0` es falso). Se devuelve NaN igual, para decidir lo mismo que la web.
  final corrido = double.tryParse('${_texto(limpio)}e$decimales');
  if (corrido == null) return double.nan;
  // Math.round de JS con x ≥ 0 = «mitad hacia arriba» = roundToDouble() de Dart.
  final entero = corrido.roundToDouble();
  final r = double.parse('${_texto(entero)}e-$decimales');
  return s * r == 0 ? 0 : s * r;
}

double r2(num? n) => redondear(n, 2);

/// `String(n)` de JavaScript para los casos que usa el redondeo (enteros sin «.0»).
String _texto(double x) {
  if (x == x.truncateToDouble() && x.abs() < 1e21) return x.toStringAsFixed(0);
  return x.toString();
}
