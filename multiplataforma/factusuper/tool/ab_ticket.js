// tool/ab_ticket.js — A/B del TIQUETE (#3957): FSTicket.fipvivi002 REAL de factusuper_ticket.js (cargado en un vm)
// con documentos al azar (semilla fija) → test/ab_ticket.json para test/ticket_ab_test.dart.
// Uso: node tool/ab_ticket.js <factusuper_ticket.js> <salida.json> [casos]
// La salida va como base64 de las unidades UTF-16 (LE) del texto del JS: así viajan igual los controles ESC/POS,
// las tildes, los emoji y hasta un sustituto suelto (UTF-8 los cambiaría por U+FFFD).
'use strict';
const fs = require('fs');
const vm = require('vm');
const [, , ruta, salida, n = '4000'] = process.argv;
if (!ruta || !salida) { console.error('Uso: node tool/ab_ticket.js <factusuper_ticket.js> <salida.json> [casos]'); process.exit(1); }

const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(ruta, 'utf8'), ctx, { filename: ruta });
const FST = ctx.FSTicket;
// 🪤 el Date tiene que ser el DEL vm: uno de afuera no pasa `instanceof Date` y el JS usaría la hora del equipo
const DateVm = vm.runInContext('Date', ctx);
if (!FST || typeof FST.fipvivi002 !== 'function') { console.error('No encontré FSTicket.fipvivi002'); process.exit(1); }

// mulberry32 con semilla fija (un LCG de módulo 2^31 deja los sorteos seguidos correlacionados y ramas sin tocar)
let semilla = 3957;
const azar = () => {
  semilla = (semilla + 0x6D2B79F5) | 0;
  let x = Math.imul(semilla ^ (semilla >>> 15), 1 | semilla);
  x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
  return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
};
const elegir = (a) => a[Math.floor(azar() * a.length)];
const si = (p) => azar() < p;
const entre = (a, b) => a + Math.floor(azar() * (b - a + 1));
const digitos = (k) => { let s = ''; for (let i = 0; i < k; i++) s += String(entre(0, 9)); return s; };
const r2 = (x) => Math.round(x * 100) / 100;
const NADA = undefined; // «no existe» (JSON lo quita)

// --- vocabulario realista (con tildes, ñ, ß, emoji y nombres largos que envuelven) ---
const NOMBRES = ['Arroz Tío Pelón 1kg', 'Café Britt molido 500g', 'Leche Dos Pinos 1L', 'Pan Bimbo blanco', 'Azúcar Doña María',
  'Jabón Ñapa líquido', 'Pingüino de peluche', 'Atún Sardimar en aceite 160 g PAQUETE x3 unidades con regalo', 'Huevos', 'Cerveza Imperial lata 350ml',
  'Straße-Schokolade ß', 'Galletas Pozuelo María ü', 'Agua Cristal 🍾 600ml', 'ÁRBOL ÉXITO ÍNDICE ÓPTIMO ÚNICO', 'ﬁlete de pescado', 'Ωmega 3 µg', '', '0', 'Detergente Irex 5kg con suavizante aroma lavanda y bicarbonato'];
const CLIENTES = ['Juan Pérez Rodríguez', 'María José Ñúñez', 'Distribuidora La Económica S.A.', 'José Ángel Güell', 'cliente de contado', 'Corporación de Supermercados Unidos de Centroamérica Sociedad Anónima', '😀 Emoji Ltda', 'Ñandú', ''];
const EMPRESAS = ['Súper Ñeco', 'Mini Súper La Esquina', 'SoporteReal SRL', 'Abastecedor Hermanos Jiménez y Compañía Limitada', '', 'ferretería el martillo', 'café ß'];
const TEXTOS = ['Gracias por su compra', 'Tels 2229-0303', 'tel 8888-8888', 'Teléfono: 2222-2222', 'Autorizado mediante resolución DGT-R-033-2019 del 20/06/2019', 'Horario: lunes a sábado 7am–9pm, domingos y feriados de 8 a 6', 'TELS: 2', '', 'Línea con ñ y tildes áéíóú', 'telsX', 'Precios incluyen IVA 😀'];
const PRECIOS = [1.005, 2.675, 1234.565, 0.125, 999.995, 10.235, 1500, 850.5, 3333.33, 0.01, 12.345, 4999.99, 100, 1.115, 5.555, 1e6 + 0.005, 25000, 0.5, 19.99, 7.775];

function fecha() {
  return elegir([
    () => '2026-' + String(entre(1, 12)).padStart(2, '0') + '-' + String(entre(1, 28)).padStart(2, '0') + ' ' + String(entre(0, 23)).padStart(2, '0') + ':' + String(entre(0, 59)).padStart(2, '0') + ':' + String(entre(0, 59)).padStart(2, '0') + '.' + digitos(3),
    () => '2026-11-25 14:03:22',
    () => '2025-12-31 23:59:59',
    () => '2024-2-29',
    () => '2026-1-5T08:07',
    () => ' 2026-03-01 09:00',
    () => '0050-06-15 10:00:00',
    () => '2026-13-40 25:61:00',
    () => '25/11/2026',
    () => 20261125,
    () => '',
    () => NADA,
    () => null,
  ])();
}

function linea() {
  const cant = elegir([1, 1, 2, 3, 0.5, 1.25, 3.333, '2', '1.50', 10, 0, -1, 1000, 0.1 + 0.2, 7]);
  const c = typeof cant === 'string' ? Number(cant) : cant;
  const precio = elegir(PRECIOS);
  const tarifa = elegir([13, 13, 13, 1, 2, 4, 8, 0, 0, '13', '0.5', NADA]);
  const t = typeof tarifa === 'string' ? Math.trunc(Number(tarifa)) : (tarifa || 0);
  const pct = elegir([0, 0, 0, 5, 10, 12.5, 33.333, 100]);
  const sub1 = precio * c;
  const desc = pct ? elegir([r2(sub1 * pct / 100), sub1 * pct / 100, String(r2(sub1 * pct / 100))]) : elegir([0, 0, NADA, '0']);
  const dm = Number(desc) || 0;
  const sub3 = elegir([sub1 - dm, r2(sub1 - dm), 0, NADA, String(r2(sub1 - dm))]);
  const base = r2(sub1 - dm);
  const iva = t > 0 ? elegir([r2(base * t / 100), base * t / 100, 0]) : 0;
  const l = {
    ArticuloCantidad: si(0.05) ? NADA : cant,
    ArticuloCodigo: elegir(['7441001', '001', 'ABC-12', 'ñ1', digitos(13), '', 12345, NADA]),
    ArticuloVenta: si(0.05) ? elegir(['1,500.00', 'abc', NADA]) : elegir([precio, String(precio)]),
    ArticuloVentaSubTotal1: elegir([sub1, String(sub1), NADA]),
    ArticuloDescuentoPorcentage: pct ? elegir([pct, String(pct)]) : elegir([0, NADA]),
    ArticuloDescuentoMonto: desc,
    ArticuloVentaSubTotal3: sub3,
    ArticuloIvaMonto: iva,
    ArticuloBodegaCodigo: elegir([1, '2', '01', 'B', NADA, 3.7]),
  };
  if (si(0.9)) l[si(0.7) ? 'NombreArticulo' : 'ArticuloNombre'] = elegir(NOMBRES);
  if (si(0.6)) l.TarifaIva = tarifa; else l.ArticuloIvaPorcentage = tarifa;
  if (si(0.25)) l.ArticuloSerie = elegir(['SN-123456', 'Serie A\r\nSerie B', '  linea 1 \n\n  línea 2  \n', 'IMEI 356938035643809\nColor: rojo ñ', ' ', 'Detalle muy largo que tiene que partirse en varios renglones porque no cabe en el papel', ' con espacio duro']);
  if (si(0.2)) l.ArticuloVentaExento = elegir([base, 0, String(base)]);
  if (si(0.15)) l.ArticuloVentaExonerado = elegir([r2(base * 0.5), base, '0', 100.005]);
  if (si(0.1)) l.ArticuloIvaDevuelto = elegir([iva, r2(iva / 2), 0]);
  if (si(0.4)) l.ArticuloVentaTotal = elegir([r2(base + iva), base + iva, 0, String(r2(base + iva))]);
  if (si(0.5)) l.ArticuloCabys = elegir([digitos(13), '', ' 2399999000000 ']);
  if (si(0.5)) l.ArticuloUnidadMedida = elegir(['Unid', 'kg', 'Sp', '', 'Unid ']);
  return l;
}

function documento() {
  const tipo = elegir(['factura', 'factura', 'factura', 'proforma', 'proforma', NADA, 'tiquete']);
  const codCli = elegir(['SN', 'sn', 'S/N', '0', '00', ' sn ', '', 'C001', '1234', '0001', NADA, 77]);
  const cab = {
    TipoDocumento: elegir(['01', '04', '04', '02', '03', '09', '05', 1, NADA]),
    Numero: elegir(['00100001010000012345', '00100001040000000077', '0', '', NADA, 1234]),
    Clave: elegir(['506' + digitos(47), '506' + digitos(47), '', '  ' + digitos(50) + ' ', NADA, '506😀' + digitos(20)]),
    Fecha: fecha(),
    ClienteNombre: elegir(CLIENTES.concat([NADA])),
    ClienteCedula: elegir(['', '3-101-123456', '112340567', NADA, '0']),
    ClienteEmail: elegir(['', 'cliente@correo.com', 'un.correo.electronico.muy.largo.de.verdad@empresa-grande.co.cr', NADA, '0']),
    MonedaCodigo: elegir(['CRC', 'CRC', 'USD', 'usd', ' CRC', NADA]),
  };
  if (si(0.3)) cab.TipoDocumentoReferencia = elegir(['01', '02', '03']);
  if (si(0.85)) cab.ClienteCodigo = codCli; else if (si(0.5)) cab.ClienteID = codCli;
  if (si(0.4)) cab.ClienteNombreComercial = elegir(CLIENTES);
  if (si(0.3)) cab.ClienteNombreJuridico = elegir(CLIENTES);
  if (si(0.4)) cab.ClienteDireccion = elegir(['San José, Curridabat, 200 m sur de la iglesia católica, casa esquinera color beige con portón negro', 'Heredia', '', '  Cartago  ']);
  if (si(0.4)) cab.ClienteTelefono = elegir(['8888-8888', '', ' 2222-2222 ', '0']);
  if (si(0.85)) cab.FormaPagoCodigo = elegir(['01', '02', '02', '00', '', ' 02 ', '2', '04', NADA]); else cab.CondicionVenta = elegir(['01', '02']);
  if (si(0.4)) cab.DiasCredito = elegir([0, 15, 30, '30', 'abc', -5, 365, '8.9']);
  if (si(0.3)) cab.Referencia = elegir(['00100001010000000001', '', '  REF-9 ', 'Factura original con un texto muy largo de referencia']);
  if (si(0.3)) cab.ModEntregaCodigo = elegir(['1', '2', 1, 2, '01', '3', '', '2.0']);
  if (si(0.5)) cab[si(0.7) ? 'VendedorNombre' : 'AgenteNombre'] = elegir(['Ana Gómez', 'josé ñ', '', '0', 'Vendedor con un nombre larguísimo que no cabe']);
  if (si(0.5)) cab.AgenteCodigo = elegir(['A01', '', ' 7 ', '0']);
  if (si(0.5)) cab.UsuarioNombre = elegir(['Cajero Uno', 'maría', '', 'Úrsula Ñ']);
  if (si(0.5)) cab.UsuarioCodigo = elegir(['00001', '', '09029']);
  if (si(0.35)) cab.Detalle = elegir(['Entregar en bodega', 'Línea uno\r\nLínea dos\n\nLínea cuatro\rcinco', '  ', 'Nota con un texto bastante largo que se parte en varios renglones según el ancho', '0']);
  if (si(0.2)) cab.DetallePide = elegir(['Carlos', '', ' Pedro Ñ ']);

  const doc = { tipo, cabecera: cab, lineas: [] };
  if (si(0.3)) doc.origen = elegir(['cotiza', 'historico', 'venta', '']);
  const nl = elegir([0, 1, 1, 2, 3, 3, 4, 5, 8]);
  for (let i = 0; i < nl; i++) doc.lineas.push(linea());
  if (si(0.03)) delete doc.lineas;

  if (si(0.95)) {
    const nc = elegir(EMPRESAS);
    doc.empresa = {
      NombreComercial: nc,
      RazonSocial: elegir([nc, nc.toUpperCase(), 'Inversiones Ñeco del Valle S.A.', '', NADA, 'SÚPER ÑECO']),
      Cedula: elegir(['3-101-654321', '', '0', NADA]),
      Telefono: elegir(['2229-0303', '', NADA, ' 8888-0000 ']),
    };
    if (si(0.5)) doc.empresa.Resolucion = elegir(TEXTOS);
  }
  if (si(0.5)) doc.cliente = { DiasCredito: elegir([NADA, null, 0, 30, '15', '0', 'x']) };

  const m = elegir(['nada', 'null', 'vacio', 'lleno', 'lleno']);
  if (m === 'null') doc.mensajes = null;
  else if (m === 'vacio') doc.mensajes = {};
  else if (m === 'lleno') {
    doc.mensajes = { encabezado: [], pie: [] };
    for (let i = entre(0, 3); i > 0; i--) doc.mensajes.encabezado.push(elegir(TEXTOS));
    for (let i = entre(0, 3); i > 0; i--) doc.mensajes.pie.push(elegir(TEXTOS));
    if (si(0.1)) doc.mensajes.pie = null;
  }

  if (si(0.8)) {
    doc.pagos = [];
    for (let i = entre(0, 3); i > 0; i--) {
      const p = { Monto: elegir([1000, 5000.5, 12345.675, '2000', 0, 20000, 0.005]), MedioPagoCodigo: elegir(['01', '01', '02', '03', '04', '06', 1, '1']) };
      if (si(0.7)) p.MedioPagoNombre = elegir(['Efectivo', 'Tarjeta', 'SINPE Móvil', 'Transferencia bancaria al Banco Nacional de Costa Rica']); else if (si(0.5)) p.CuentaNombre = 'Banco BCR ñ';
      doc.pagos.push(p);
    }
    if (si(0.4)) doc.pagos.push(elegir([{ Monto: -elegir([500, 1234.56, 0.5]), MedioPagoCodigo: '01', MedioPagoNombre: 'Vuelto' }, { Monto: elegir([500, '750.25', -300]), MedioPagoCodigo: elegir(['00', '99', '0', 0, 99]) }]));
  }

  if (si(0.7)) {
    const tot = {};
    for (const k of ['merc_gravada', 'merc_exenta', 'serv_gravado', 'serv_exento', 'descuento', 'iva', 'iva_devuelto', 'impuesto_servicio', 'total']) {
      if (si(0.5)) tot[k] = elegir([0, 1500.005, 12345.67, '999.995', 0.1 + 0.2, 100, null, '', 'abc', 2.675, 1e3 - 1e-13]);
    }
    doc.totales = tot;
  }

  const b = elegir(['nada', 'nada', 'null', 'obj', 'obj', 'obj', 'arr']);
  if (b === 'null') doc.bd = null;
  else if (b === 'arr') doc.bd = [];
  else if (b === 'obj') {
    const bd = {};
    if (si(0.5)) bd.plazoCliente = elegir([0, 30, '15', null, 'x', -3]);
    if (si(0.6)) bd.tipoCambioVenta = elegir(['505.32', 520, 0, 1, null, '0', 1.5, '']);
    if (si(0.5)) bd.saldoFavor = elegir([0, 1500.5, '2500', null, -10, '0']);
    if (si(0.5)) bd.ordenCompra = elegir(['OC-2026-001', '', null, 0, '  OC 9  ', 12345]);
    if (si(0.5)) bd.otrosDatos = elegir([null, [], [{ NombreCampo: 'placa', ValorCampo: 'ABC-123' }, { NombreCampo: 'Kilómetros', ValorCampo: ' 12500 ' }, { NombreCampo: '', ValorCampo: 'x' }, { NombreCampo: 'Observación larga', ValorCampo: 'texto muy largo para que se tenga que partir en varios renglones del papel' }]]);
    if (si(0.5)) bd.sac = elegir([null, { Mesa: 5, Salon: 'Terraza' }, { Mesa: '12', Salon: '' }, { Mesa: 'Barra ñ' }, {}]);
    doc.bd = bd;
  }
  return doc;
}

const CLAVES = [15, 20, 21, 22, 26, 38, 43, 47, 89, 110, 137, 151, 192, 249, 291, 307, 343, 344, 346, 380, 381, 382, 391, 936];
const SI_NO = ['1', '1', '0', '0', 'S', 'si', 'SI', 'yes', 'Y', 'true', 'TRUE', '01', '1.0', ' 1 ', '00', 'N', '', 1, 0, null, 'x', 's ', '1e0', '+1', 'Sí'];
function parametros() {
  if (si(0.1)) return null;
  const p = {};
  for (const k of CLAVES) {
    if (si(0.3)) continue;
    if (k === 151) p[k] = elegir(['1', '2', '2', 2, '2.7', 'abc', '', null, 1, ' 2']);
    else if (k === 249) p[k] = elegir(['CRC', 'CRC', 'USD', 'crc', ' crc ', '', null]);
    else if (k === 291) p[k] = elegir(['', 'COTIZACION', 'cotización', ' Proforma ', '0', null]);
    else p[k] = elegir(SI_NO);
  }
  return p;
}

// --- casos ---
const AHORA = '25/11/2026 10:30:00';
const casos = [];
const cob = { ancho: {}, tipo: {}, provisional: {}, params: {}, ahora: {}, marcas: {} };
const sumar = (o, k) => { o[k] = (o[k] || 0) + 1; };
const MARCAS = ['FORMA PAGO: CREDITO', 'FORMA PAGO: CONTADO', 'PROVISIONAL', 'REF: ', 'CLAVE: ', 'ENTREGA: ', 'CODIGO: ', 'DIR: ', 'EMAIL: ',
  'Cabys: ', 'Precio de articulo ya incluye IVA', 'V. BRUTA', 'MERC GRAVADA', 'SERV GRAVADO', 'MERC EXONERADA', 'MERC EXENTA', 'SERV EXENTO',
  'IVA DEVUELTO', 'IMP. SERVICIO', 'RESUMEN IVA', 'SIN DEFINIR', 'PARA CANCELAR', 'PAGA CON', 'SALDO A FAVOR', 'AGEN: ', 'USUA: ', 'DETALLE: ',
  'OC: ', 'PEDIDO POR: ', 'MESA ', 'DOCUMENTO SIN VALOR FISCAL', 'ARCHIVADA', 'FIRMA CLIENTE', 'IDENTIFICACION: ', 'TELS ', '(D', '1970/01/01', 'USD ', '$'];
for (let i = 0; i < Number(n); i++) {
  // JSON de ida y vuelta: el JS ve EXACTAMENTE lo que va a ver Dart (sin undefined, -0 → 0)
  const doc = JSON.parse(JSON.stringify(documento()));
  const ancho = elegir([32, 40, 42, 48]);
  const params = JSON.parse(JSON.stringify(parametros()));
  const opciones = {};
  const ka = elegir(['texto', 'texto', 'texto', 'fecha', 'fecha']);
  if (ka === 'texto') opciones.ahora = AHORA;
  else opciones.ahoraFecha = [2026, entre(1, 12), entre(1, 28), entre(0, 23), entre(0, 59), entre(0, 59)];
  if (si(0.25)) opciones.provisional = elegir(['FS-20261125-0001', '  ', '', 'ñandú 123', 'ID-MUY-LARGO-' + digitos(30)]);
  const op = { ahora: opciones.ahoraFecha ? new DateVm(opciones.ahoraFecha[0], opciones.ahoraFecha[1] - 1, opciones.ahoraFecha[2], opciones.ahoraFecha[3], opciones.ahoraFecha[4], opciones.ahoraFecha[5]) : opciones.ahora };
  if (opciones.provisional !== undefined) op.provisional = opciones.provisional;
  const txt = FST.fipvivi002(doc, ancho, params, op);
  const u16 = Buffer.alloc(txt.length * 2);
  for (let k = 0; k < txt.length; k++) u16.writeUInt16LE(txt.charCodeAt(k), k * 2);
  casos.push({ doc, ancho, params, opciones, salida_base64: u16.toString('base64') });
  sumar(cob.ancho, ancho);
  sumar(cob.tipo, String(doc.tipo) + '/' + String(doc.cabecera.TipoDocumento));
  sumar(cob.provisional, opciones.provisional && opciones.provisional.trim() ? 'si' : 'no');
  sumar(cob.params, params === null ? 'null (sin BD)' : 'objeto');
  sumar(cob.ahora, ka);
  for (const mk of MARCAS) if (txt.includes(mk)) sumar(cob.marcas, mk);
}

// Math.log10 de V8 (lo usa el pre-redondeo de round): magnitudes al azar + vecinos de cada potencia de 10
const log10 = [];
const vecinos = (x, k) => { const f = new Float64Array([x]); const b = new BigInt64Array(f.buffer); const out = []; for (let d = -k; d <= k; d++) { const g = new BigInt64Array([b[0] + BigInt(d)]); out.push(new Float64Array(g.buffer)[0]); } return out; };
for (let p = -20; p <= 22; p++) for (const x of vecinos(Number('1e' + p), 6)) log10.push([x, Math.log10(x)]);
for (let i = 0; i < 20000; i++) { const x = Math.pow(10, azar() * 40 - 20) * (1 + azar()); log10.push([x, Math.log10(x)]); }
for (const x of [1.005, 2.675, 999.995, 0.30000000000000004, 5e-324, 1.7976931348623157e308, 2.2250738585072014e-308, 1e-310]) log10.push([x, Math.log10(x)]);

fs.writeFileSync(salida, JSON.stringify({ casos, log10 }));
console.log('A/B tiquete:', casos.length, 'casos +', log10.length, 'valores de log10 →', salida);
console.log('ancho:', cob.ancho);
console.log('tipo/TipoDocumento:', cob.tipo);
console.log('provisional:', cob.provisional, '· params:', cob.params, '· ahora:', cob.ahora);
console.log('marcas en la salida (casos):');
for (const mk of MARCAS) console.log('  ' + mk.padEnd(36) + (cob.marcas[mk] || 0));
