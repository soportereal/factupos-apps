// #3957 — A/B del TIQUETE: fipvivi002() de Dart contra FSTicket.fipvivi002 REAL de la web
// (node tool/ab_ticket.js <factusuper_ticket.js> test/ab_ticket.json). Tiene que dar 0 diferencias.
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:factusuper/impresion/ticket.dart';
import 'package:flutter_test/flutter_test.dart';

/// La salida del JS viene como base64 de sus unidades UTF-16 (LE).
String _desdeUtf16(String b64) {
  final b = base64Decode(b64);
  final u = ByteData.sublistView(Uint8List.fromList(b));
  return String.fromCharCodes([
    for (var i = 0; i < b.length; i += 2) u.getUint16(i, Endian.little),
  ]);
}

/// Texto escapado para leer la diferencia (controles ESC/POS y no ASCII a la vista).
String _escapar(String s) {
  final b = StringBuffer();
  for (final c in s.codeUnits) {
    if (c == 0x0A) {
      b.write(r'\n');
    } else if (c < 0x20 || c == 0x7F || c > 0x7E) {
      b.write('\\u{${c.toRadixString(16).padLeft(2, '0')}}');
    } else {
      b.writeCharCode(c);
    }
  }
  return b.toString();
}

String _diferencia(int i, String web, String app) {
  var k = 0;
  while (k < web.length &&
      k < app.length &&
      web.codeUnitAt(k) == app.codeUnitAt(k)) {
    k++;
  }
  final ini = k < 60 ? 0 : k - 60;
  String trozo(String s) =>
      _escapar(s.substring(ini, (k + 60).clamp(0, s.length)));
  return 'caso $i: primera diferencia en la posición $k (largo web ${web.length}, app ${app.length})\n'
      '  web: …${trozo(web)}…\n'
      '  app: …${trozo(app)}…';
}

void main() {
  final f = File('test/ab_ticket.json');
  final datos = f.existsSync()
      ? jsonDecode(f.readAsStringSync()) as Map<String, dynamic>
      : const {};

  test('tiquete FIPVIVI002 = la web', () {
    final casos = (datos['casos'] as List).cast<Map<String, dynamic>>();
    final malos = <String>[];
    var nMalos = 0;
    for (var i = 0; i < casos.length; i++) {
      final k = casos[i];
      final op = k['opciones'] as Map<String, dynamic>;
      final fecha = (op['ahoraFecha'] as List?)?.cast<int>();
      final app = fipvivi002(
        k['doc'] as Map<String, dynamic>,
        k['ancho'] as int,
        k['params'] as Map<String, dynamic>?,
        ahoraTexto: op['ahora'] as String?,
        ahora: fecha == null
            ? null
            : DateTime(
                fecha[0],
                fecha[1],
                fecha[2],
                fecha[3],
                fecha[4],
                fecha[5],
              ),
        provisional: op['provisional'] as String?,
      );
      final web = _desdeUtf16(k['salida_base64'] as String);
      if (app != web) {
        nMalos++;
        if (malos.length < 5) malos.add(_diferencia(i, web, app));
      }
    }
    // ignore: avoid_print
    print('${casos.length} casos, $nMalos con diferencias');
    expect(nMalos, 0, reason: malos.join('\n'));
  }, skip: f.existsSync() ? false : 'falta test/ab_ticket.json');

  test('Math.log10 de V8 (pre-redondeo de round)', () {
    final valores = (datos['log10'] as List).cast<List>();
    final malos = <String>[];
    for (final v in valores) {
      final x = (v[0] as num).toDouble(), esperado = (v[1] as num).toDouble();
      final r = log10Js(x);
      if (r != esperado) malos.add('log10($x): web=$esperado app=$r');
    }
    // ignore: avoid_print
    print(
      '${valores.length} valores de log10, ${malos.length} con diferencias',
    );
    expect(malos, isEmpty, reason: malos.take(6).join('\n'));
  }, skip: f.existsSync() ? false : 'falta test/ab_ticket.json');
}
