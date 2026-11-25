// tool/ab_romana.js — A/B de la ROMANA (#3957): romanaLeer REAL de factusuper_local.js (extraída, con datos de mentira)
// con etiquetas al azar → test/romana_ab_test.dart. Uso: node tool/ab_romana.js <factusuper_local.js> <salida.json> [casos]
'use strict';
const fs = require('fs'); const vm = require('vm');
const [, , ruta, salida, n = '5000'] = process.argv;
let semilla = 7;
const azar = () => { semilla = (semilla * 1103515245 + 12345) % 2147483648; return semilla / 2147483648; };
const elegir = (a) => a[Math.floor(azar() * a.length)];
const src = fs.readFileSync(ruta, 'utf8');
const ini = src.indexOf('    async function romanaLeer(');
const fin = src.indexOf('\n    }\n', ini) + 6;
let E;
const ctx = {
  romanaConfig: async () => (E.cfg && Number(E.cfg.activo) === 1 ? E.cfg : null),
  articuloExacto: async (c) => E.articulos.find((a) => a.codigo.toUpperCase() === String(c).trim().toUpperCase() || (a.barra && a.barra === String(c).trim())) || null,
  estacion: async () => E.estacion, precios: async (a) => E.precios.filter((p) => p.articulo === a),
  tipoCambio: async (m) => (m === 'CRC' ? 1 : E.tc),
};
vm.createContext(ctx);
vm.runInContext('var romanaLeer = ' + src.slice(ini, fin).replace('async function romanaLeer', 'async function') + ';', ctx);
const casos = [];
(async () => {
  for (let i = 0; i < Number(n); i++) {
    const ci = elegir([1, 2, 3]), cf = ci + elegir([3, 4, 5, 6]), vi = cf + elegir([1, 2]), vf = vi + elegir([3, 4, 5]);
    const cfg = { clave: 'actual', activo: elegir([1, 1, 1, 0]), pos_codigo_ini: ci, pos_codigo_fin: cf, pos_valor_ini: vi, pos_valor_fin: vf, tipo: elegir(['cantidad', 'precio']) };
    const largoCod = cf - ci + 1;
    const codArt = String(Math.floor(azar() * 10 ** largoCod)).padStart(largoCod, '0');
    const articulos = [{ codigo: codArt, nombre: 'Carne ' + codArt, tarifa_iva: elegir([13, 1, 0]), barra: '' }, { codigo: 'X1', nombre: 'Otro', tarifa_iva: 13, barra: '' }];
    const precios = elegir([[], [{ articulo: codArt, numero: 1, precio: elegir([3500, 4999.99, 1250.5]), moneda: elegir(['CRC', 'CRC', 'USD']) }, { articulo: codArt, numero: 2, precio: elegir([0, 3300]), moneda: 'CRC' }]]);
    E = { cfg, articulos, precios, estacion: { tipo_precio: elegir([1, 2, 3]) }, tc: elegir([0, 505.5]) };
    let codigo = '';
    const largo = Math.max(cf, vf) + elegir([0, 0, 1, -1]);
    for (let k = 0; k < largo; k++) codigo += String(Math.floor(azar() * 10));
    // poner el código del artículo en su lugar (casi siempre)
    if (azar() < 0.85 && codigo.length >= cf) codigo = codigo.slice(0, ci - 1) + codArt + codigo.slice(cf);
    if (azar() < 0.05) codigo = 'A' + codigo.slice(1);
    const r = await ctx.romanaLeer(codigo);
    casos.push({ E, codigo, r: r === null ? null : r.error ? { error: r.error } : { articulo: r.articulo.codigo, cantidad: r.cantidad, tipo: r.tipo, valor: r.valor } });
  }
  fs.writeFileSync(salida, JSON.stringify(casos));
  const k = { nulos: 0, error: 0, cantidad: 0, precio: 0 }; casos.forEach((c) => { if (!c.r) k.nulos++; else if (c.r.error) k.error++; else k[c.r.tipo]++; });
  console.log('A/B romana:', casos.length, k);
})();
