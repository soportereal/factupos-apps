/// Tema de FactuSuper (#3957) — dueño: «un diseño muy elegante, muy atractivo, profesional».
/// Azul marino de marca + verde para cobrar, superficies claras, bordes suaves, Inter embebida.
library;

import 'package:flutter/material.dart';

class Marca {
  static const azul = Color(0xFF0B2A5B);
  static const azulMedio = Color(0xFF1D4ED8);
  static const azulClaro = Color(0xFFE8EEFB);
  static const verde = Color(0xFF0E9F6E);
  static const verdeOscuro = Color(0xFF057A55);
  static const ambar = Color(0xFFD97706);
  static const rojo = Color(0xFFDC2626);
  static const fondo = Color(0xFFF3F5F9);
  static const borde = Color(0xFFE2E8F0);
  static const tinta = Color(0xFF0F172A);
  static const tintaSuave = Color(0xFF64748B);

  /// Color de cada medio de pago (Hacienda): 01 efectivo · 02 tarjeta · 04 transferencia · 06 SINPE…
  static Color medio(String codigo) => switch (codigo) {
    '01' => verde,
    '02' => azulMedio,
    '04' => const Color(0xFF7C3AED),
    '06' => const Color(0xFF0891B2),
    _ => const Color(0xFF475569),
  };
  static IconData iconoMedio(String codigo) => switch (codigo) {
    '01' => Icons.payments_outlined,
    '02' => Icons.credit_card,
    '04' => Icons.account_balance_outlined,
    '06' => Icons.phone_iphone,
    _ => Icons.wallet_outlined,
  };
}

ThemeData temaFactuSuper() {
  final esquema = ColorScheme.fromSeed(
    seedColor: Marca.azul,
    primary: Marca.azul,
    secondary: Marca.verde,
    surface: Colors.white,
    error: Marca.rojo,
  );
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: esquema,
    fontFamily: 'Inter',
    scaffoldBackgroundColor: Marca.fondo,
  );
  final redondo = RoundedRectangleBorder(
    borderRadius: BorderRadius.circular(12),
  );
  return base.copyWith(
    textTheme: base.textTheme.apply(
      bodyColor: Marca.tinta,
      displayColor: Marca.tinta,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: Marca.azul,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontFamily: 'Inter',
        fontSize: 17,
        fontWeight: FontWeight.w600,
        color: Colors.white,
      ),
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: Marca.borde),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: Marca.borde),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: Marca.borde),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: Marca.azulMedio, width: 2),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        shape: redondo,
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
        textStyle: const TextStyle(
          fontFamily: 'Inter',
          fontSize: 15,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        shape: redondo,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
        side: const BorderSide(color: Marca.borde),
        foregroundColor: Marca.tinta,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(shape: redondo),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: Colors.white,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      titleTextStyle: const TextStyle(
        fontFamily: 'Inter',
        fontSize: 20,
        fontWeight: FontWeight.w700,
        color: Marca.tinta,
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      width: 520,
    ),
    dividerTheme: const DividerThemeData(
      color: Marca.borde,
      space: 1,
      thickness: 1,
    ),
    chipTheme: base.chipTheme.copyWith(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      side: BorderSide.none,
    ),
  );
}

/// La marca: cuadro con el carrito + «FactuSuper».
class Logo extends StatelessWidget {
  final bool claro;
  final double tam;
  const Logo({super.key, this.claro = true, this.tam = 22});
  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        padding: EdgeInsets.all(tam * 0.3),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            colors: [Marca.verde, Color(0xFF34D399)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
          borderRadius: BorderRadius.circular(tam * 0.45),
        ),
        child: Icon(
          Icons.shopping_cart_rounded,
          color: Colors.white,
          size: tam,
        ),
      ),
      SizedBox(width: tam * 0.5),
      Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: 'Factu',
              style: TextStyle(
                fontWeight: FontWeight.w500,
                color: claro ? Colors.white : Marca.tinta,
              ),
            ),
            TextSpan(
              text: 'Super',
              style: TextStyle(
                fontWeight: FontWeight.w800,
                color: claro ? const Color(0xFF6EE7B7) : Marca.verde,
              ),
            ),
          ],
        ),
        style: TextStyle(fontSize: tam * 0.95, letterSpacing: -0.3),
      ),
    ],
  );
}

/// Fondo de las pantallas de entrada/configuración: panel de marca a la izquierda (en pantallas anchas).
class FondoMarca extends StatelessWidget {
  final Widget child;
  final String titulo, subtitulo;
  const FondoMarca({
    super.key,
    required this.child,
    this.titulo = 'Caja de supermercado',
    this.subtitulo = '',
  });
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, c) {
      final ancho = c.maxWidth >= 900;
      final tarjeta = Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: child,
          ),
        ),
      );
      if (!ancho) return Container(color: Marca.fondo, child: tarjeta);
      return Row(
        children: [
          Container(
            width: c.maxWidth * 0.42,
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                colors: [Marca.azul, Color(0xFF143D80)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
            ),
            padding: const EdgeInsets.all(48),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Logo(tam: 26),
                const Spacer(),
                Text(
                  titulo,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 34,
                    fontWeight: FontWeight.w700,
                    height: 1.15,
                    letterSpacing: -0.6,
                  ),
                ),
                const SizedBox(height: 14),
                Text(
                  subtitulo,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.75),
                    fontSize: 15,
                    height: 1.5,
                  ),
                ),
                const Spacer(),
                Text(
                  'FactuPOS · Soporte Real',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.5),
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: Container(color: Marca.fondo, child: tarjeta),
          ),
        ],
      );
    },
  );
}
