import 'package:factupos_apps/catalogo.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const json = '''{"apps":[
    {"id":"apps","nombre":"FactuPOS Apps","grupo":"","paquete":"com.factupos.apps","versionCode":1,"version":"1.0.0","url":"u0"},
    {"id":"brave","nombre":"Brave","grupo":"Otras apps","paquete":"com.brave.browser","versionCode":5,"version":"1.9","url":"u64","url_32":"u32"},
    {"id":"print","nombre":"FactuPOS Print","grupo":"Impresión","paquete":"com.factupos.printbridge","versionCode":56,"version":"3.9.6","url":"u2"},
    {"id":"malo","nombre":"Sin paquete","url":"x"}
  ]}''';

  test('lee la lista y descarta lo que no trae paquete', () {
    final l = leerCatalogo(json);
    expect(l.map((a) => a.id), ['apps', 'brave', 'print']);
    expect(l[1].urlPara(es32: true), 'u32');
    expect(l[1].urlPara(es32: false), 'u64');
    expect(l[2].urlPara(es32: true), 'u2');
  });

  test('estado por versionCode', () {
    final p = leerCatalogo(json)[2];
    expect(estadoDe(p, null), Estado.noInstalada);
    expect(estadoDe(p, const Instalada(55, '3.9.5')), Estado.actualizar);
    expect(estadoDe(p, const Instalada(56, '3.9.6')), Estado.alDia);
    expect(estadoDe(p, const Instalada(60, '4.0')), Estado.alDia);
  });

  test('grupos en orden, la propia arriba', () {
    final g = agrupar(leerCatalogo(json));
    expect(g.map((e) => e.key), ['', 'Impresión', 'Otras apps']);
  });
}
