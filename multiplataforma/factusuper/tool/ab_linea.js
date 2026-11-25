// tool/ab_linea.js — A/B de la EDICIÓN DE LÍNEA (#3957): FSLinea.validar REAL (reglas de FactuDesk: 024, 004, 023, 006,
// precio mínimo, 021, montos altos, bonificación) con casos al azar → test/linea_ab_test.dart repite con el Dart.
// Uso: node tool/ab_linea.js <carpeta js de factusuper> <salida.json> [casos]
'use strict';
const fs = require('fs'); const vm = require('vm'); const path = require('path');
const [, , carpeta, salida, nCasos = '6000'] = process.argv;
let semilla = 3958;
const azar = () => { semilla = (semilla * 1103515245 + 12345) % 2147483648; return semilla / 2147483648; };
const elegir = (a) => a[Math.floor(azar() * a.length)];
const num = (max, dec) => Number((azar() * max).toFixed(dec));

// DOM de mentira: FSLinea engancha eventos al cargar.
const nodo = () => new Proxy(function () {}, { get: (t, k) => (k === 'classList' ? { add() {}, remove() {}, contains: () => false, toggle() {} } : k === 'value' || k === 'textContent' ? '' : nodo()), apply: () => nodo(), set: () => true });
let permisos = [];
const FSLocal = { tienePermiso: async (p) => permisos.includes(p), parametros: async () => new Map(), configGuardar: async () => {}, configLeer: async () => null };
const ctx = { window: {}, FSLocal, console, document: { getElementById: () => nodo(), querySelectorAll: () => [], addEventListener() {}, body: nodo() } };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(carpeta, 'factusuper_documento.js'), 'utf8'), ctx);
ctx.FSDoc = ctx.window.FSDoc;
vm.runInContext(fs.readFileSync(path.join(carpeta, 'factusuper_linea.js'), 'utf8'), ctx);
// validar es interno: se expone leyendo el módulo (FSLinea no lo exporta) → se evalúa la función sola.
const src = fs.readFileSync(path.join(carpeta, 'factusuper_linea.js'), 'utf8');
const ini = src.indexOf('    async function validar(');
const fin = src.indexOf('\n    }\n', ini) + 6;
const pre = src.slice(src.indexOf('    const fmt ='), src.indexOf('    /**', src.indexOf('    const monto =')));
vm.runInContext(`var FSDoc = window.FSDoc; ${pre.replace(/const /g, 'var ')}\nvar validar = ${src.slice(ini, fin).replace('async function validar', 'async function')};`, ctx);

const casos = [];
(async () => {
    for (let i = 0; i < Number(nCasos); i++) {
        permisos = ['024', '004', '023', '006', '021'].filter(() => azar() < 0.4);
        const precio = elegir([num(5000, 2), 1000, 441.1765, num(200, 4)]);
        const l = {
            precio, descuento: elegir([0, 0, 5, 10]), nivel: elegir([1, 2, 6]), nivelBloqueado: azar() < 0.1,
            descMax: elegir([100, 5, 20, 50]), costo: elegir([0, precio * 0.6, precio * 0.9, num(3000, 2)]), utilMin: elegir([0, 10, 30]),
        };
        const c = {
            cantidad: elegir([1, 2, 0, 3.5, 1000, 9000, 120000]), precio: elegir([precio, precio, precio * 1.1, precio * 0.7, 0, num(9000, 2)]),
            modo: elegir(['pct', 'pct', 'monto']), valor: elegir([0, 5, 10, 25, 60, 101, num(800, 2)]),
            bonificacion: azar() < 0.08, montoConfirmado: azar() < 0.3,
        };
        const auth = {}; ['024', '004', '023', '006'].forEach((p) => { if (azar() < 0.1) auth[p] = { usuario: '00001' }; });
        const r = await ctx.validar(l, c, auth);
        const tipo = r.ok ? 'ok' : r.error ? 'error' : r.confirmar ? 'confirmar' : 'requiere:' + r.requiere.permiso;
        const alt = r.requiere && r.requiere.alternativa ? r.requiere.alternativa.cambios : null;
        casos.push({ permisos, l, c, auth: Object.keys(auth), tipo, alt: alt ? { precio: Number(alt.precio), modo: alt.modo, valor: Number(alt.valor) } : null });
    }
    fs.writeFileSync(salida, JSON.stringify(casos));
    const n = {}; casos.forEach((x) => { n[x.tipo] = (n[x.tipo] || 0) + 1; });
    console.log(`A/B línea: ${casos.length} casos →`, n);
})();
