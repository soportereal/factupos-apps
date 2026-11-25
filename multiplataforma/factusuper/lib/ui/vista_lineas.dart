// #3957 — Vistas de las líneas, igual que la web (dueño, 27-sep-2026): Básica (solo cantidad, nombre y precio) ·
// Simple · Detallada (+ PV, P. unit, subtotal, neto s/IVA, % IVA, IVA, P. neto) · Full (+ una segunda fila con todos los
// campos). El tamaño de letra es POR VISTA (A− / A+, de 12 a 34) y se recuerda en el equipo; sin elegir = el de fábrica.

import '../motor/linea.dart';

const vistasLineas = ['basica', 'simple', 'detallada', 'full'];
const nombresVista = {
  'basica': 'Básica',
  'simple': 'Simple',
  'detallada': 'Detallada',
  'full': 'Full',
};
const letraMin = 12.0, letraMax = 34.0;

/// La letra de fábrica de cada vista (en la app: Básica más grande; Detallada y Full más chicas porque llevan más columnas).
double letraFabrica(String vista) => switch (vista) {
  'basica' => 20,
  'simple' => 15,
  _ => 13,
};

/// El nombre viejo «completa» = detallada; cualquier otra cosa → simple (como `ponerVista` de la web).
String vistaValida(Object? v) {
  final s = v == 'completa' ? 'detallada' : '$v';
  return vistasLineas.contains(s) ? s : 'simple';
}

/// La letra en uso: la elegida para esa vista, o la de fábrica.
double letraDe(String vista, Map<String, double> elegidas) =>
    elegidas[vista] ?? letraFabrica(vista);

/// `cambiarLetra(delta)` de la web: 0 = vuelve a la de fábrica; si no, suma y queda entre 12 y 34.
Map<String, double> cambiarLetra(
  String vista,
  Map<String, double> elegidas,
  int delta,
) {
  final m = Map<String, double>.of(elegidas);
  if (delta == 0) {
    m.remove(vista);
  } else {
    m[vista] = (letraDe(vista, m) + delta).clamp(letraMin, letraMax);
  }
  return m;
}

/// Lo guardado en el equipo → mapa limpio (descarta vistas que no existen y números fuera de rango).
Map<String, double> letrasDesde(Object? crudo) {
  final m = <String, double>{};
  if (crudo is Map) {
    for (final e in crudo.entries) {
      final v = e.value is num ? (e.value as num).toDouble() : null;
      if (vistasLineas.contains('${e.key}') &&
          v != null &&
          v >= letraMin &&
          v <= letraMax) {
        m['${e.key}'] = v;
      }
    }
  }
  return m;
}

const naturalezas = {
  '1': 'Mercancía',
  '2': 'Servicio',
  '3': 'Otro',
  '4': 'Insumo',
  '5': 'Combo',
};

/// `precioConIva(l)` de la web: lo que la tabla muestra como PRECIO (precio × (1 + (IVA − exonerado) / 100)).
double precioConIva(Linea l) =>
    l.precio * (1 + (l.tarifa - l.ivaExonerado) / 100);

/// `descuentoConIva(l)`: el monto del descuento ya con IVA (cuadra: precio con IVA × cant − descuento = total).
double descuentoConIva(Linea l) =>
    l.descuentoMonto * (1 + (l.tarifa - l.ivaExonerado) / 100);
