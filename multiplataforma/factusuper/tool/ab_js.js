// tool/ab_js.js — Prueba A/B del motor (#3957): corre el FSDoc REAL de la web con miles de casos al azar y guarda
// lo que da, para que test/motor_ab_test.dart compruebe que el motor Dart da EXACTAMENTE lo mismo.
// Uso: node tool/ab_js.js <ruta a factusuper_documento.js> <salida.json> [casos]
'use strict';
const fs = require('fs');
const vm = require('vm');

const [, , rutaJs, salida, nCasos = '4000'] = process.argv;
let semilla = 3957;
const azar = () => { semilla = (semilla * 1103515245 + 12345) % 2147483648; return semilla / 2147483648; };
const elegir = (a) => a[Math.floor(azar() * a.length)];
const num = (max, dec) => Number((azar() * max).toFixed(dec));

let params = new Map(), guardado = null;
const FSLocal = {
    parametros: async () => params,
    configGuardar: async () => {},
    configLeer: async () => guardado,
};
const ctx = { window: {}, FSLocal, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(rutaJs, 'utf8'), ctx);
const FSDoc = ctx.window.FSDoc;

function lineaAlAzar() {
    const l = {
        codigo: 'A' + Math.floor(azar() * 1000),
        cantidad: elegir([1, 2, 3, 10, 12, 0.5, 0.225, 1.333, 7.125, 100, 0.001, 24]),
        precio: elegir([num(5000, 2), num(100000, 5), num(999, 4), 441.1765, 1, 0.5, 2212.38938, 17699.11504]),
        tarifa: elegir([0, 1, 2, 4, 8, 13, 13, 13]),
        naturaleza: elegir(['1', '1', '2']),
        costo: num(3000, 2),
    };
    const d = azar();
    if (d < 0.15) l.descMonto = elegir([num(500, 2), l.precio * l.cantidad, 1e9, 0]);
    else if (d < 0.6) l.descuento = elegir([0, 5, 10, 12.5, 33.333333, 100, num(50, 6)]);
    if (azar() < 0.2) l.exo = { porcentaje: elegir([13, 10, 4, 6.5, 0, 50]) };
    return l;
}

const casos = [];
(async () => {
    for (let i = 0; i < Number(nCasos); i++) {
        const p = {};
        for (const n of [25, 924, 197, 18, 198, 195, 199]) if (azar() < 0.5) p[n] = String(Math.floor(azar() * 6));
        if (azar() < 0.15) p[190] = '1';
        params = new Map(Object.entries(p).map(([k, v]) => [Number(k), v]));
        const lineas = Array.from({ length: 1 + Math.floor(azar() * 6) }, lineaAlAzar);
        const medioPago = elegir(['01', '01', '02', '04']);
        guardado = { lineas: JSON.parse(JSON.stringify(lineas)), medioPago };
        let tot = null;
        FSDoc.alCambiar((doc, t) => { tot = t; });
        const doc = await FSDoc.restaurar();
        casos.push({
            params: p, medioPago, entrada: lineas,
            lineas: doc.lineas.map((l) => ({
                ivaExonerado: l.ivaExonerado, ivaExoneradoMonto: l.ivaExoneradoMonto, subtotal1: l.subtotal1,
                descuento: l.descuento, descuentoMonto: l.descuentoMonto, subtotal2: l.subtotal2, subtotal3: l.subtotal3,
                exonerado: l.exonerado, gravado: l.gravado, exento: l.exento, iva: l.iva, ivaDevuelto: l.ivaDevuelto, total: l.total,
            })),
            totales: tot,
            cajaPct: lineas.map((l) => FSDoc.descuentoCajaPct({ ...l, uxm: 12, descCaja: 7.5 })),
        });
    }
    const redondeos = [];
    for (let i = 0; i < 20000; i++) {
        const v = elegir([num(100000, 6), num(10, 9), -num(5000, 5), 4411.765, 1.005, 2.675, 0.125, 1e-7, 123456789.125]);
        const d = Math.floor(azar() * 7);
        redondeos.push([v, d, FSDoc.redondear(v, d)]);
    }
    fs.writeFileSync(salida, JSON.stringify({ casos, redondeos }));
    console.log(`A/B: ${casos.length} documentos y ${redondeos.length} redondeos → ${salida}`);
})();
