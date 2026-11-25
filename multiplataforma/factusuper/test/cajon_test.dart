// #3957 — los bytes del cajón = los de factusuper_cajon.js (base64 latin-1 sacado de la función real de la web).
import 'package:factusuper/caja/cajon.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('comando del cajón byte a byte igual a la web', () {
    expect(
      base64Latin1(
        comandoCajon(
          '7',
          '00006 Ana Rodriguez',
          '',
          DateTime(2026, 11, 25, 9, 5),
        ),
      ),
      WEB[0],
    );
    expect(
      base64Latin1(
        comandoCajon('12', '', 'Carlos Mora', DateTime(2026, 1, 3, 23, 59)),
      ),
      WEB[1],
    );
  });
  test('sin tildes y cola', () {
    expect(sinTildes('Ana Rodríguez Peña'), 'Ana Rodriguez Pena');
    expect(empresaCola('Demo-Ferre 2'), 'demoferre2');
  });
}

const WEB = [
  'G3AAGfobYQEbRQEdIRFDQUpPTiBBQklFUlRPCh0hABtFABthATI1LzExLzIwMjYgMDk6MDUKG2EAVXN1YXJpbyA6IDAwMDA2IEFuYSBSb2RyaWd1ZXoKRXN0YWNpb246IDcKCgoKHVYB',
  'G3AAGfobYQEbRQEdIRFDQUpPTiBBQklFUlRPCh0hABtFABthATAzLzAxLzIwMjYgMjM6NTkKG2EARXN0YWNpb246IDEyCkF1dG9yaXphOiBDYXJsb3MgTW9yYQoKCgodVgE=',
];
