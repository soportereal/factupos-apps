// tool/ab_agregar.js — Prueba A/B de la CAJA (#3957): corre FSDoc REAL (agregar + paquete) con escenarios al azar
// (niveles, monedas, descuentos fijo/máximo/utilidad/caja, permisos 023/006, cliente con nivel/descuento/exento,
// artículos repetidos, fraccionables) y guarda lo que da; test/caja_ab_test.dart repite lo mismo con el Dart.
// Uso: node tool/ab_agregar.js <factusuper_documento.js> <salida.json> [escenarios]
'use strict';
const fs = require('fs');
const vm = require('vm');
const [, , rutaJs, salida, nEsc = '1500'] = process.argv;
let semilla = 1957;
const azar = () => { semilla = (semilla * 1103515245 + 12345) % 2147483648; return semilla / 2147483648; };
const elegir = (a) => a[Math.floor(azar() * a.length)];
const num = (max, dec) => Number((azar() * max).toFixed(dec));

let E = null;   // escenario actual
const FSLocal = {
    parametros: async () => new Map(Object.entries(E.params).map(([k, v]) => [Number(k), v])),
    configGuardar: async () => {}, configLeer: async () => null,
    estacion: async () => E.estacion,
    precios: async (a) => E.precios.filter((p) => p.articulo === a).map((p) => ({ ...p })),
    tipoCambio: async (m) => (m === 'CRC' ? 1 : (E.tc[m] || 0)),
    articuloExacto: async (c) => E.articulos.find((a) => a.codigo === c) || null,
    tienePermiso: async (p) => E.permisos.includes(p),
    actividadesEmpresa: async () => [{ codigo: '523101' }],
    cliente: async (c) => E.clientes.find((x) => x.codigo === c) || null,
    actividadesCliente: async () => [],
};
const ctx = { window: {}, FSLocal, console, crypto: require('crypto').webcrypto };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(rutaJs, 'utf8'), ctx);
const FSDoc = ctx.window.FSDoc;

function articulo(i) {
    return {
        codigo: 'A' + i, nombre: 'Artículo ' + i, barra: '7' + String(i).padStart(12, '0'),
        tarifa_iva: elegir([13, 13, 13, 1, 2, 4, 0]), codigo_tarifa_iva: elegir(['08', '01', '02', '04', '10']),
        cabys: elegir(['2399999000000', '1234567890123']), unidad: elegir(['Unid', 'kg']),
        naturaleza: elegir(['1', '1', '1', '2']), actividad_economica: elegir(['', '523101']),
        fraccionable: elegir([0, 0, 1]), costo: elegir([0, num(3000, 2), num(800, 4)]),
        unidades_x_medida: elegir([0, 0, 6, 12, 24]), moneda: 'CRC', cabys_ok: elegir([1, 1, null]),
    };
}
function preciosDe(a) {
    const out = [];
    const niveles = elegir([[1], [1, 2], [1, 2, 3], [2, 3], [1, 5, 6]]);
    for (const n of niveles) out.push({
        articulo: a.codigo, numero: n, precio: elegir([num(5000, 2), num(100000, 5), 0, 441.1765, num(30, 4)]),
        moneda: elegir(['CRC', 'CRC', 'CRC', 'USD']), descuento_fijo: elegir([0, 0, 5, 10, 50]),
        descuento_maximo: elegir([null, 100, 5, 20]), utilidad_minima: elegir([0, 0, 10, 30]), descuento_caja: elegir([0, 0, 7.5, 3]),
    });
    return out;
}

const escenarios = [];
(async () => {
    for (let k = 0; k < Number(nEsc); k++) {
        const articulos = Array.from({ length: 4 }, (_, i) => articulo(i));
        const params = { 345: '0', 40: '0' };
        for (const n of [25, 924, 197, 198, 195, 199]) if (azar() < 0.4) params[n] = String(Math.floor(azar() * 6));
        if (azar() < 0.3) params[57] = '1';
        for (const n of [153, 154, 155, 156, 157, 158]) if (azar() < 0.2) params[n] = '1';
        if (azar() < 0.3) params[16] = String(elegir([5, 15, 40]));
        const cliente = elegir([
            null,
            { codigo: 'C1', nombre: 'Juan', tipo_precio: elegir([0, 2, 3, 5]), descuento: elegir([0, 0, 8, 25]), exento: elegir([0, 0, 1]), cedula: '101110111', tipo_cedula: '01' },
        ]);
        E = {
            params, articulos, precios: articulos.flatMap(preciosDe), tc: { USD: elegir([0, 512.33, 498.1]) },
            permisos: [elegir(['', '023']), elegir(['', '006'])].filter(Boolean),
            estacion: { id: 7, nombre: 'CAJA 3', tipo_precio: elegir([1, 2, 6]), oficina: '002', caja: '3', bodega: '01', impresion: { contado: { ruta: elegir([2, 4]), impresora: 'EPSON', formato: 'FIPVIVI002', ancho: 80 } } },
            clientes: cliente ? [cliente] : [],
        };
        ctx.window.FS_USUARIO = '00006';
        FSDoc.nuevo();
        await FSDoc.recalcular();   // como la web al abrir (restaurar): carga los decimales de la empresa
        if (cliente) await FSDoc.cliente(cliente);
        const pasos = [];
        for (let j = 0; j < 1 + Math.floor(azar() * 6); j++) {
            const a = elegir(articulos), cant = String(elegir([1, 1, 2, 3, 0.5, 1.25, 12, 24, 0.225]));
            const r = await FSDoc.agregar(a, cant);
            pasos.push({ articulo: a.codigo, cantidad: cant, ok: !!r.ok, motivo: r.motivo || '', avisos: r.avisos || [] });
        }
        const medio = elegir(['01', '02']);
        FSDoc.medioPago(medio);
        const t = FSDoc.totales();
        const pq = await FSDoc.paquete({ tipoPago: 'contado', pagos: [{ medio, cuenta: '', monto: t.total, comprobante: '' }], vuelto: 0 });
        escenarios.push({ ...E, cliente, pasos, medio, paquete: JSON.parse(JSON.stringify(pq)) });
    }
    fs.writeFileSync(salida, JSON.stringify(escenarios));
    console.log(`A/B caja: ${escenarios.length} escenarios → ${salida}`);
})();
