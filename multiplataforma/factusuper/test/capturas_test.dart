// #3957 — CAPTURAS de las pantallas con datos de ejemplo (para revisar el diseño sin un Windows a mano).
// Corre solo con FS_CAPTURAS=<carpeta>: flutter test test/capturas_test.dart (deja los PNG ahí).
import 'dart:io';
import 'dart:ui' as ui;

import 'package:factusuper/app/sabor.dart';
import 'package:factusuper/ui/vista_lineas.dart';
import 'package:factusuper/caja/cajeros.dart';
import 'package:factusuper/caja/cola.dart';
import 'package:factusuper/caja/datos_caja.dart';
import 'package:factusuper/caja/estacion_config.dart';
import 'package:factusuper/ui/dialogos_caja.dart';

import 'estacion_config_test.dart' show respuestaGet;

import 'package:factusuper/datos/almacen.dart';
import 'package:factusuper/pantallas/caja.dart';
import 'package:factusuper/pantallas/configuracion.dart';
import 'package:factusuper/pantallas/entrada.dart';
import 'package:factusuper/ui/tema.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

final salida = Platform.environment['FS_CAPTURAS'] ?? '';

Future<void> fuentes() async {
  final inter = FontLoader('Inter');
  for (final w in ['Regular', 'Medium', 'SemiBold', 'Bold', 'ExtraBold']) {
    inter.addFont(
      File('assets/fonts/Inter-$w.ttf')
          .readAsBytes()
          .then((b) => ByteData.view(b.buffer)),
    );
  }
  await inter.load();
  final iconos = FontLoader('MaterialIcons');
  final sdk =
      Platform.environment['FLUTTER_ROOT'] ??
      '${Platform.environment['HOME']}/flutter';
  iconos.addFont(
    File('$sdk/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf')
        .readAsBytes()
        .then((b) => ByteData.view(b.buffer)),
  );
  await iconos.load();
}

final marco = GlobalKey();
Widget app(Widget home) => RepaintBoundary(
  key: marco,
  child: MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: temaFactuSuper(),
    home: home,
  ),
);

Future<void> foto(WidgetTester t, String nombre) async {
  await t.pump(const Duration(milliseconds: 400));
  final rb = marco.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  final img = await t.runAsync(() => rb.toImage(pixelRatio: 1));
  final png = await t.runAsync(
    () => img!.toByteData(format: ui.ImageByteFormat.png),
  );
  File('$salida/$nombre.png').writeAsBytesSync(png!.buffer.asUint8List());
}

DatosCaja datosEjemplo() {
  final arts = <Map<String, dynamic>>[];
  final precios = <Map<String, dynamic>>[];
  const nombres = [
    'Arroz Tío Pelón 1,8 kg',
    'Frijoles negros Ducal 800 g',
    'Café Rey molido 500 g',
    'Leche Dos Pinos 1 L',
    'Huevos blancos x 15',
    'Aceite Clover 1,5 L',
    'Azúcar Doña María 2 kg',
    'Pan cuadrado Bimbo',
    'Atún Sardimar 140 g',
    'Papel higiénico Nevax x 4',
  ];
  const pre = [
    2150.0,
    1480.0,
    3290.0,
    765.0,
    2390.0,
    3990.0,
    1850.0,
    1640.0,
    1120.0,
    2480.0,
  ];
  for (var i = 0; i < nombres.length; i++) {
    arts.add({
      'codigo': 'P${100 + i}',
      'nombre': nombres[i],
      'barra': '74400${10000 + i}',
      'tarifa_iva': i == 3 ? 1 : 13,
      'codigo_tarifa_iva': i == 3 ? '02' : '08',
      'cabys': '2399999000000',
      'cabys_ok': 1,
      'naturaleza': '1',
      'fraccionable': 0,
      'costo': pre[i] * 0.7,
      'unidades_x_medida': 0,
    });
    precios.add({
      'articulo': 'P${100 + i}',
      'numero': 1,
      'precio': pre[i] / 1.13,
      'moneda': 'CRC',
      'descuento_fijo': 0,
      'descuento_maximo': 30,
      'utilidad_minima': 0,
      'descuento_caja': 0,
    });
  }
  return DatosCaja.desde(
    articulos: arts,
    precios: precios,
    clientes: [
      {
        'codigo': 'C001',
        'nombre': 'Supermercado La Esquina S.A.',
        'cedula': '3101123456',
        'tipo_cedula': '02',
        'tipo_precio': 0,
        'plazo': 30,
      },
    ],
    catalogos: {
      'estacion': [
        {
          'clave': 'actual',
          'nombre': 'CAJA 3',
          'caja': '3',
          'oficina': '001',
          'bodega': '01',
          'tipo_precio': 1,
        },
      ],
      'tarifas_iva': [
        {'codigo': '01', 'nombre': 'Exento', 'porcentaje': 0},
        {'codigo': '04', 'nombre': 'IVA reducido 4%', 'porcentaje': 4},
        {'codigo': '08', 'nombre': 'IVA general 13%', 'porcentaje': 13},
      ],
      'medios_pago': [
        {'codigo': '01', 'descripcion': 'Efectivo', 'mostrar': 1},
        {
          'codigo': '02',
          'descripcion': 'Tarjeta',
          'mostrar': 1,
          'cuenta': '110107',
          'cuenta_nombre': 'Tarjetas BN',
        },
        {
          'codigo': '02',
          'descripcion': 'Tarjeta',
          'mostrar': 1,
          'cuenta': '110108',
          'cuenta_nombre': 'Tarjetas Bac',
        },
        {
          'codigo': '06',
          'descripcion': 'SINPE Móvil',
          'mostrar': 1,
          'cuenta': '110103',
          'cuenta_nombre': 'Sinpe Movil Bac',
        },
      ],
      'usuarios': [
        {
          'usuario': '00006',
          'nombre': 'Ana Rodríguez',
          'hash':
              r'$2y$10$abcdefghijklmnopqrstuuJ0r0sYb8V3S1x8t1Gm0V2k2K5n6Q5yW',
        },
        {
          'usuario': '00007',
          'nombre': 'Carlos Mora',
          'hash':
              r'$2y$10$abcdefghijklmnopqrstuuJ0r0sYb8V3S1x8t1Gm0V2k2K5n6Q5yW',
        },
      ],
      'permisos_usuario': [
        {'usuario': '00006', 'permiso': '653'},
        {'usuario': '00006', 'permiso': '104'},
        {'usuario': '00007', 'permiso': '653'},
      ],
    },
  );
}

void main() {
  final cfg = ConfigCaja(
    llave: 'fs1.${'a' * 64}',
    empresa: 'demoferre',
    empresaNombre: 'Ferretería Demo',
    guardada: DateTime(2026, 11, 25),
  );

  Future<void> preparar(
    WidgetTester t, {
    double w = 1440,
    double h = 900,
  }) async {
    await t.runAsync(fuentes); // E/S real: fuera del reloj falso de la prueba
    t.view.physicalSize = Size(w, h);
    t.view.devicePixelRatio = 1;
  }

  testWidgets('capturas', (t) async {
    await preparar(t);
    final tmp = Directory.systemTemp.createTempSync('fs_cap');
    final almacen = Almacen(tmp);
    final datos = datosEjemplo();
    final cajeros = Cajeros(datos.catalogos);

    await t.pumpWidget(
      app(PantallaConfiguracion(almacen: almacen, alGuardar: (_) {})),
    );
    await foto(t, '1-configuracion');

    await t.pumpWidget(
      app(
        PantallaEntrada(
          almacen: almacen,
          config: cfg,
          cajeros: cajeros,
          alEntrar: (_) {},
          alConfigurar: () {},
        ),
      ),
    );
    await foto(t, '2-entrada');

    final cola = Cola(almacen, 'demoferre', cfg.llave);
    await t.pumpWidget(
      app(
        PantallaCaja(
          config: cfg,
          almacen: almacen,
          datos: datos,
          cola: cola,
          cajeros: cajeros,
          cajero: const Cajero('00006', 'Ana Rodríguez'),
          alSalir: () {},
        ),
      ),
    );
    await t.pump();
    await foto(t, '3-caja-vacia');

    for (final c in ['P100', '3*P103', 'P102', 'P105', '7440010008', 'P101']) {
      await t.enterText(find.byType(TextField).first, c);
      await t.testTextInput.receiveAction(TextInputAction.done);
      await t.pump(const Duration(milliseconds: 300));
    }
    await t.pump(const Duration(seconds: 4));
    await foto(t, '4-caja-con-lineas');

    await t.enterText(find.byType(TextField).first, 'leche');
    await t.testTextInput.receiveAction(TextInputAction.done);
    await t.pump(const Duration(milliseconds: 300));
    await t.enterText(find.byType(TextField).first, 'a');
    await t.testTextInput.receiveAction(TextInputAction.done);
    await t.pump(const Duration(milliseconds: 300));
    await foto(t, '5-busqueda');
    await t.sendKeyEvent(LogicalKeyboardKey.escape);
    await t.pump();

    await t.tap(find.widgetWithText(FilledButton, 'Efectivo'));
    await t.pump(const Duration(milliseconds: 500));
    await t.tap(find.text('₡20,000'));
    await t.pump(const Duration(milliseconds: 300));
    await foto(t, '6-cobro-efectivo');
    await t.tap(find.text('Cancelar'));
    await t.pump(const Duration(milliseconds: 500));

    await t.tap(find.byTooltip('Editar (Ctrl+Enter)').first);
    await t.pump(const Duration(milliseconds: 500));
    await foto(t, '7-editar-linea');
    await t.tap(find.text('Cancelar'));
    await t.pump(const Duration(milliseconds: 500));

    // Barra de marcadas
    await t.tap(find.byType(Checkbox).first);
    await t.pump(const Duration(milliseconds: 400));
    await foto(t, '7b-marcadas');
    await t.tap(find.byType(Checkbox).first);
    await t.pump(const Duration(milliseconds: 300));
    // Consulta F6
    await t.sendKeyEvent(LogicalKeyboardKey.f6);
    await t.pump(const Duration(milliseconds: 500));
    await t.enterText(find.byType(TextField).last, 'cafe');
    await t.pump(const Duration(milliseconds: 300));
    await t.enterText(find.byType(TextField).last, 'Café');
    await t.pump(const Duration(milliseconds: 300));
    await t.tap(find.text('Café Rey molido 500 g').last);
    await t.pump(const Duration(seconds: 5));
    await foto(t, '7c-consulta');
    await t.tap(find.text('Cerrar'));
    await t.pump(const Duration(milliseconds: 500));
    // Opciones (F10) · fondo · cierre · favoritos
    await t.sendKeyEvent(LogicalKeyboardKey.f10);
    await t.pump(const Duration(milliseconds: 600));
    await foto(t, '7d-opciones');
    await t.tap(find.text('Ingreso de fondo'));
    await t.pump(const Duration(milliseconds: 600));
    await foto(t, '7e-fondo');
    await t.tap(find.text('Cancelar'));
    for (var i = 0; i < 4; i++) {
      await t.pump(const Duration(milliseconds: 400));
    }
    await t.sendKeyEvent(LogicalKeyboardKey.f10);
    for (var i = 0; i < 4; i++) {
      await t.pump(const Duration(milliseconds: 400));
    }
    await t.tap(find.text('Cierre de caja'));
    await t.runAsync(() => Future.delayed(const Duration(seconds: 2)));
    await t.pump(const Duration(milliseconds: 600));
    await foto(t, '7f-cierre');
    await t.tap(find.text('Cerrar').last);
    await t.pump(const Duration(milliseconds: 500));
    await t.tap(find.byTooltip('Favoritos: los más vendidos y los suyos'));
    await t.runAsync(() => Future.delayed(const Duration(seconds: 1)));
    await t.pump(const Duration(milliseconds: 600));
    await foto(t, '7g-favoritos');
    await t.tap(find.text('Ocultar'));
    await t.pump(const Duration(milliseconds: 500));
    // Vistas de las líneas + letra por vista
    var actual = 'simple';
    for (final v in ['basica', 'detallada', 'full']) {
      await t.tap(find.text('Vista ${nombresVista[actual]!.toLowerCase()}  '));
      await t.pump(const Duration(milliseconds: 500));
      await t.tap(find.text('Vista ${nombresVista[v]!.toLowerCase()}  ').last);
      await t.pump(const Duration(milliseconds: 500));
      actual = v;
      await foto(t, '7h-vista-$v');
    }
    await t.tap(find.text('A+'));
    await t.pump();
    await t.tap(find.text('A+'));
    await t.pump(const Duration(milliseconds: 300));
    await foto(t, '7i-full-letra-mas');
    await t.tap(
      find.byTooltip('Cola de procesos: lo que falta enviar, en orden'),
    );
    for (var i = 0; i < 3; i++) {
      await t.pump(const Duration(milliseconds: 200));
      await t.runAsync(() => Future.delayed(const Duration(milliseconds: 300)));
    }
    await t.runAsync(() => Future.delayed(const Duration(milliseconds: 500)));
    await t.pump(const Duration(milliseconds: 600));
    await foto(t, '7j-cola');
    await t.tap(find.text('Cerrar').last);
    await t.pump(const Duration(milliseconds: 500));
    // CF-006 · configuración de la estación (sin servidor: los datos de ejemplo de estacion_config_test)
    dialogoEstacion(t.element(find.byType(PantallaCaja)), _EstacionFalsa());
    for (var i = 0; i < 3; i++) {
      await t.pump(const Duration(milliseconds: 200));
      await t.runAsync(() => Future.delayed(const Duration(milliseconds: 100)));
    }
    await foto(t, '7k-estacion');
    await t.tap(find.text('Cancelar').last);
    await t.pump(const Duration(milliseconds: 500));

    await t.pumpWidget(
      app(
        PantallaCaja(
          key: const ValueKey('cel'),
          config: cfg,
          almacen: almacen,
          datos: datos,
          cola: cola,
          cajeros: cajeros,
          cajero: const Cajero('00006', 'Ana Rodríguez'),
          alSalir: () {},
        ),
      ),
    );
    t.view.physicalSize = const Size(420, 860);
    await t.pump(const Duration(seconds: 1));
    await foto(t, '8-celular');
    for (final c in ['P100', '2*P104', 'P109']) {
      await t.enterText(find.byType(TextField).first, c);
      await t.testTextInput.receiveAction(TextInputAction.done);
      await t.pump(const Duration(milliseconds: 300));
    }
    await t.pump(const Duration(seconds: 4));
    await foto(t, '9-celular-lineas');

    // FactuMóvil: SU pantalla (réplica de FactuMóvil web), con la venta en curso que quedó guardada.
    sabor = saborFactuMovil;
    await t.pumpWidget(
      app(
        PantallaCaja(
          key: const ValueKey('movil'),
          config: cfg,
          almacen: almacen,
          datos: datos,
          cola: cola,
          cajeros: cajeros,
          cajero: const Cajero('00006', 'Ana Rodríguez'),
          alSalir: () {},
        ),
      ),
    );
    await t.pump(const Duration(seconds: 1));
    await foto(t, '10-factumovil');
    await t.tap(find.byIcon(Icons.expand_more).first);
    await t.pump(const Duration(milliseconds: 400));
    await foto(t, '11-factumovil-cliente');
    await t.tap(find.byIcon(Icons.expand_less).first);
    await t.pump(const Duration(milliseconds: 400));
    await t.tap(find.text('Agregar artículo'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    Finder campo(String pista) => find.byWidgetPredicate(
      (w) => w is TextField && w.decoration?.hintText == pista,
    );
    await t.enterText(campo('Buscar artículo'), 'caf');
    await t.pump(const Duration(milliseconds: 400));
    await foto(t, '12-factumovil-buscar');
    await t.tap(find.text('Agregar').first);
    await t.pump(const Duration(seconds: 1));
    await t.enterText(campo('Buscar artículo'), 'arroz');
    await t.pump(const Duration(milliseconds: 400));
    await t.tap(find.text('+').first);
    await t.tap(find.text('+').first);
    await t.pump(const Duration(milliseconds: 300));
    await t.tap(find.text('Agregar').first);
    await t.pump(const Duration(seconds: 1));
    await foto(t, '13-factumovil-agregado');
    await t.tap(find.text('Regresar').last);
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await t.tap(find.text('Seleccionar cliente'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await t.enterText(campo('Buscar cliente'), 'a');
    await t.pump(const Duration(milliseconds: 400));
    await foto(t, '14-factumovil-clientes');
    await t.tap(find.text('Regresar').last);
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await foto(t, '15-factumovil-final');
    // PM-001 Procesar → Definir (VP-001 Cobro de Factura)
    t
        .state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first)
        .removeCurrentSnackBar(); // el aviso de abajo tapa el pie
    await t.pump(const Duration(milliseconds: 500));
    await t.tap(find.text('Procesar'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await foto(t, '16-factumovil-procesar');
    await t.tap(find.text('Definir'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await foto(t, '17-factumovil-cobro');
    await t.tap(find.text('CRC5,000'));
    await t.pump();
    await t.tap(find.text('Todo Tarjetas Bac'));
    await t.pump();
    await t.drag(find.byType(ListView).last, const Offset(0, -700));
    await t.pump(const Duration(milliseconds: 400));
    await foto(t, '18-factumovil-cobro-pagos');
    await t.tap(find.text('Cancelar'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    // Venta a crédito: con un cliente que tiene plazo
    await t.tap(find.text('Seleccionar cliente'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await t.enterText(campo('Buscar cliente'), 'super');
    await t.pump(const Duration(milliseconds: 400));
    await t.tap(find.text('Supermercado La Esquina S.A.').last);
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    t
        .state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first)
        .removeCurrentSnackBar();
    await t.pump(const Duration(milliseconds: 500));
    await t.tap(find.text('Procesar'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await t.tap(find.text('Facturar a crédito'));
    await t.pump();
    await t.pump(const Duration(seconds: 8));
    await foto(t, '19-factumovil-credito');
    await t.tap(find.text('Cancelar'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    // MFM-EDIT: editar una línea
    await t.tap(find.text('Arroz Tío Pelón 1,8 kg').first);
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    await foto(t, '20-factumovil-editar');
    await t.enterText(
      find
          .byWidgetPredicate((w) => w is TextField && w.controller?.text == '0')
          .first,
      '5',
    );
    await t.pump(const Duration(milliseconds: 300));
    await foto(t, '21-factumovil-editar-desc');
    await t.tap(find.text('Cancelar'));
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    // Cotizaciones (foto 12: en el celular salía en una columna de letras)
    Future<void> disco() async {
      for (var i = 0; i < 4; i++) {
        await t.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 200)),
        );
        await t.pump(const Duration(milliseconds: 300));
      }
    }

    await t.tap(find.text('Guardar').last);
    await disco();
    if (find.byType(AlertDialog).evaluate().isNotEmpty) {
      await t.enterText(find.byType(TextField).last, 'FIORELLA');
      await t.testTextInput.receiveAction(TextInputAction.done);
      await t.pump(const Duration(seconds: 2));
    }
    t
        .state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first)
        .removeCurrentSnackBar();
    await t.pump(const Duration(milliseconds: 500));
    await disco();
    t
        .state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first)
        .removeCurrentSnackBar();
    await t.pump(const Duration(milliseconds: 500));
    await disco();
    t
        .state<ScaffoldMessengerState>(find.byType(ScaffoldMessenger).first)
        .clearSnackBars();
    await t.pump(const Duration(seconds: 1));
    await foto(t, '22a-factumovil-vacia');
    await t.tap(find.text('Cotizaciones'));
    await disco();
    await disco();
    await disco();
    await t.pump(const Duration(seconds: 1));
    await foto(t, '22-factumovil-cotizaciones');
    await t.tap(find.text('Regresar').last);
    await t.pump();
    await t.pump(const Duration(seconds: 1));
    sabor = saborFactuSuper;
    t.view.resetPhysicalSize();
    tmp.deleteSync(recursive: true);
  }, skip: salida.isEmpty);
}

class _EstacionFalsa extends EstacionConfig {
  _EstacionFalsa()
    : super(
        ConfigCaja(
          llave: 'x',
          empresa: 'demoferre',
          empresaNombre: 'Demo',
          guardada: DateTime(2026),
        ),
        '00006',
      );
  @override
  Future<(DatosEstacion?, String)> cargar() async =>
      (DatosEstacion.desde(respuestaGet()), '');
}
