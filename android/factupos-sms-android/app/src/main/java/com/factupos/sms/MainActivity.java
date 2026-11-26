package com.factupos.sms;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.pm.PackageManager;
import android.content.SharedPreferences;
import android.content.res.TypedArray;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.telephony.SubscriptionInfo;
import android.telephony.SubscriptionManager;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

import java.util.List;

/**
 * UI de FactuposSMS. El usuario define el nombre de la BD/empresa POR CADA SIM,
 * y arranca/detiene el servicio de captura. Endpoint y token son internos.
 * Desde la v1.1 (#1307) muestra el último mensaje y si se cargó, y la lista de los últimos.
 * Desde la 1.2 (#3035) relee los SMS del teléfono y avisa (e instala) cuando hay una versión nueva.
 * Desde la 1.4 (#3035) pantalla compacta: barra fija con el estado, tarjetas y acciones en cuadrícula.
 */
public class MainActivity extends Activity {

    // Paleta: la de FactuPOS (navy) sobre fondo gris claro, tarjetas blancas.
    private static final String NAVY = "#0047AB";
    private static final String FONDO = "#f1f5f9";
    private static final String BORDE = "#e2e8f0";
    private static final String TEXTO = "#0f172a";
    private static final String GRIS = "#64748b";
    private static final String VERDE = "#16a34a";
    private static final String ROJO = "#dc2626";
    private static final String AMBAR = "#d97706";

    private LinearLayout col;
    private LinearLayout ultimoMensaje;
    private LinearLayout listaMensajes;
    private LinearLayout avisoVersion;
    private Actualizar.Info versionNueva;
    private boolean versionBuscada = false;
    private boolean releyendo = false;
    private TextView pillEstado;
    private TextView btnServicio;
    private TextView estadoServicio;
    private TextView subSonido;
    private int pad;
    private float dp;
    private String firmaUltimo = null;

    // El receptor de SMS corre en este mismo proceso: cuando anota un mensaje, la pantalla se entera.
    private final SharedPreferences.OnSharedPreferenceChangeListener alCambiarLista =
            new SharedPreferences.OnSharedPreferenceChangeListener() {
                @Override
                public void onSharedPreferenceChanged(SharedPreferences sp, String key) {
                    if (!Aviso.KEY_HIST.equals(key)) return;
                    runOnUiThread(new Runnable() {
                        public void run() { pintarMensajes(); }
                    });
                }
            };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        dp = getResources().getDisplayMetrics().density;
        pad = (int) (12 * dp);
        getWindow().setStatusBarColor(Color.parseColor(NAVY));

        // Barra de arriba FIJA (no se va con el scroll) + el contenido que sí se desplaza.
        LinearLayout raiz = new LinearLayout(this);
        raiz.setOrientation(LinearLayout.VERTICAL);
        raiz.setBackgroundColor(Color.parseColor(FONDO));
        raiz.addView(cabecera());

        col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(pad, pad / 2, pad, pad * 2);
        ScrollView sv = new ScrollView(this);
        sv.addView(col);
        raiz.addView(sv, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(raiz);

        pedirPermisos();
        construirUI();
    }

    @Override
    protected void onResume() {
        super.onResume();
        Config.p(this).registerOnSharedPreferenceChangeListener(alCambiarLista);
        pintarMensajes();
        Aviso.reintentarEnFondo(this, 0);
        // Una vez por apertura: si hay versión nueva, se ofrece. Al volver de dar el permiso de
        // instalar tampoco se vuelve a preguntar: el aviso de arriba sigue ahí con su botón.
        if (!versionBuscada) {
            versionBuscada = true;
            buscarVersion(false);
        }
    }

    @Override
    protected void onPause() {
        Config.p(this).unregisterOnSharedPreferenceChangeListener(alCambiarLista);
        super.onPause();
    }

    private void pedirPermisos() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            requestPermissions(new String[]{
                    "android.permission.RECEIVE_SMS",
                    "android.permission.READ_SMS",
                    "android.permission.READ_PHONE_STATE",
                    "android.permission.POST_NOTIFICATIONS"
            }, 100);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        construirUI(); // reconstruir: ya con permiso podemos listar las SIM
    }

    /** Barra navy: logo de FactuPOS (como en FactuPOS Print, #2886) + nombre y versión + estado del servicio. */
    private View cabecera() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Color.parseColor(NAVY));
        bar.setPadding(pad, pad * 3 / 4, pad, pad * 3 / 4);

        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.logo_factupos);
        logo.setAdjustViewBounds(true);
        LinearLayout.LayoutParams lpLogo = new LinearLayout.LayoutParams((int) (40 * dp), (int) (40 * dp));
        lpLogo.setMargins(0, 0, pad * 3 / 4, 0);
        bar.addView(logo, lpLogo);

        LinearLayout nombre = new LinearLayout(this);
        nombre.setOrientation(LinearLayout.VERTICAL);
        TextView t = texto("FactuposSMS", 18, "#ffffff");
        t.setTypeface(Typeface.DEFAULT_BOLD);
        nombre.addView(t);
        nombre.addView(texto("Versión " + versionApp() + " · pagos SINPE", 12, "#c7d7f5"));
        bar.addView(nombre, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        pillEstado = texto("", 12, "#ffffff");
        pillEstado.setTypeface(Typeface.DEFAULT_BOLD);
        pillEstado.setPadding(pad * 3 / 4, pad / 3, pad * 3 / 4, pad / 3);
        bar.addView(pillEstado);
        return bar;
    }

    private void construirUI() {
        col.removeAllViews();

        // ---- Versión nueva (#3035): solo aparece si hay una ----
        avisoVersion = new LinearLayout(this);
        avisoVersion.setOrientation(LinearLayout.VERTICAL);
        col.addView(avisoVersion);
        pintarAvisoVersion();

        // ---- Primera ficha, al inicio: acciones en cuadrícula 2×2 (#3035) ----
        col.addView(seccion("Acciones"));
        col.addView(fila(
                accion("↻", "Releer SMS", "sin repetir pagos", new View.OnClickListener() {
                    public void onClick(View v) { elegirPeriodoReleer(); }
                }, null),
                accion("⬇", "Actualizar", "buscar versión nueva", new View.OnClickListener() {
                    public void onClick(View v) {
                        Toast.makeText(MainActivity.this, "Buscando versión nueva…", Toast.LENGTH_SHORT).show();
                        buscarVersion(true);
                    }
                }, null)));
        col.addView(fila(
                accion("🔔", "Sonido", "", new View.OnClickListener() {
                    public void onClick(View v) {
                        Config.setSonidoActivo(MainActivity.this, !Config.isSonidoActivo(MainActivity.this));
                        refrescarSonido();
                    }
                }, "sonido"),
                accion("▶", "Probar aviso", "no manda nada", new View.OnClickListener() {
                    public void onClick(View v) { Aviso.probar(MainActivity.this); }
                }, null)));
        refrescarSonido();
        TextView ayudaSonido = texto("El sonido usa el volumen de la ALARMA: se oye aunque el teléfono esté en "
                + "silencio. Si algo no se pudo cargar, suena un pitido de error distinto.", 11, GRIS);
        ayudaSonido.setPadding((int) (2 * dp), pad / 2, 0, 0);
        col.addView(ayudaSonido);


        // ---- Segunda ficha: los celulares (chips) y la configuración (#3035) ----
        col.addView(seccion("Celulares y configuración"));
        LinearLayout conf = tarjetaBlanca();
        LinearLayout serv = new LinearLayout(this);
        serv.setOrientation(LinearLayout.HORIZONTAL);
        serv.setGravity(Gravity.CENTER_VERTICAL);
        estadoServicio = texto("", 14, TEXTO);
        estadoServicio.setTypeface(Typeface.DEFAULT_BOLD);
        serv.addView(estadoServicio, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        btnServicio = boton("", NAVY, "#ffffff");
        btnServicio.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { toggleServicio(); }
        });
        serv.addView(btnServicio);
        conf.addView(serv);
        refrescarServicio();

        // una fila por SIM: la empresa de cada chip
        List<SubscriptionInfo> sims = null;
        try {
            SubscriptionManager sm = (SubscriptionManager) getSystemService(TELEPHONY_SUBSCRIPTION_SERVICE);
            if (sm != null) sims = sm.getActiveSubscriptionInfoList();
        } catch (SecurityException e) {
            // sin permiso aún
        }
        conf.addView(divisor());
        if (sims == null || sims.isEmpty()) {
            conf.addView(texto("Conceda los permisos de Teléfono y SMS y reabra la app para ver los chips.", 13, ROJO));
        } else {
            for (int i = 0; i < sims.size(); i++) {
                SubscriptionInfo info = sims.get(i);
                int slot = info.getSimSlotIndex();
                CharSequence carrier = info.getCarrierName();
                String numero = info.getNumber() != null ? info.getNumber() : "";
                String etiqueta = "SIM " + (slot + 1)
                        + (carrier != null && carrier.length() > 0 ? " · " + carrier : "")
                        + (!numero.isEmpty() ? " · " + numero : "");
                if (i > 0) conf.addView(divisor());
                agregarFichaSim(conf, slot, etiqueta);
            }
        }
        col.addView(conf);

        // ---- Último mensaje ----
        col.addView(seccion("Último mensaje"));
        ultimoMensaje = new LinearLayout(this);
        ultimoMensaje.setOrientation(LinearLayout.VERTICAL);
        col.addView(ultimoMensaje);


        // ---- Debajo del último: solo el aviso de pendientes. La lista de mensajes ya no va en la
        //      pantalla: se abre con «Ver mensajes SIM n» de cada celular (#3035). ----
        listaMensajes = new LinearLayout(this);
        listaMensajes.setOrientation(LinearLayout.VERTICAL);
        col.addView(listaMensajes);

        TextView salir = texto("Salir", 14, GRIS);
        salir.setGravity(Gravity.CENTER);
        salir.setPadding(0, pad, 0, pad);
        conToque(salir);
        salir.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { finishAndRemoveTask(); }
        });
        LinearLayout.LayoutParams lpSalir = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lpSalir.setMargins(0, pad, 0, 0);
        col.addView(salir, lpSalir);

        pintarMensajes();
    }

    // ------------------------------------------------------- releer (#3035)

    private void elegirPeriodoReleer() {
        if (releyendo) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M
                && checkSelfPermission("android.permission.READ_SMS") != PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(this, "Primero dele a la app el permiso para leer los SMS.", Toast.LENGTH_LONG).show();
            requestPermissions(new String[]{"android.permission.READ_SMS"}, 101);
            return;
        }
        final String[] opciones = {"Hoy", "Últimos 2 días", "Últimos 7 días", "Últimos 30 días"};
        final int[] dias = {0, 1, 6, 29};
        new AlertDialog.Builder(this)
                .setTitle("¿Qué SMS releer?")
                .setItems(opciones, new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int i) { releer(dias[i], opciones[i]); }
                })
                .setNegativeButton("Cancelar", null)
                .show();
    }

    /** Relee desde la medianoche de hace {@code dias} días. */
    private void releer(int dias, String periodo) {
        java.util.Calendar cal = java.util.Calendar.getInstance();
        cal.set(java.util.Calendar.HOUR_OF_DAY, 0);
        cal.set(java.util.Calendar.MINUTE, 0);
        cal.set(java.util.Calendar.SECOND, 0);
        cal.set(java.util.Calendar.MILLISECOND, 0);
        cal.add(java.util.Calendar.DAY_OF_MONTH, -dias);
        final long desde = cal.getTimeInMillis();

        releyendo = true;
        final AlertDialog progreso = new AlertDialog.Builder(this)
                .setTitle("Releyendo SMS · " + periodo)
                .setMessage("Leyendo los mensajes del teléfono…")
                .setCancelable(false)
                .show();
        new Thread(new Runnable() {
            public void run() {
                final Releer.Resultado r = Releer.releer(MainActivity.this, desde, new Releer.Avance() {
                    public void en(final int hechos, final int total) {
                        runOnUiThread(new Runnable() {
                            public void run() { progreso.setMessage("Mandando " + hechos + " de " + total + "…"); }
                        });
                    }
                });
                runOnUiThread(new Runnable() {
                    public void run() {
                        releyendo = false;
                        progreso.dismiss();
                        if (isFinishing()) return;
                        new AlertDialog.Builder(MainActivity.this)
                                .setTitle(r.sinRevisar > 0 ? "Releer SMS · incompleto" : "Releer SMS · listo")
                                .setMessage(Releer.resumen(r))
                                .setPositiveButton("Aceptar", null)
                                .show();
                    }
                });
            }
        }).start();
    }

    // ------------------------------------------------ versión nueva (#3035)

    /** Pregunta al servidor si hay versión nueva. {@code manual} = lo pidió el botón: se contesta siempre. */
    private void buscarVersion(final boolean manual) {
        new Thread(new Runnable() {
            public void run() {
                final Actualizar.Info i = Actualizar.publicada();
                runOnUiThread(new Runnable() {
                    public void run() {
                        if (isFinishing()) return;
                        if (i == null) {
                            if (manual) Toast.makeText(MainActivity.this, "No se pudo comprobar si hay versión nueva (sin conexión).", Toast.LENGTH_LONG).show();
                            return;
                        }
                        boolean hay = i.versionCode > Actualizar.versionInstalada(MainActivity.this);
                        versionNueva = hay ? i : null;
                        pintarAvisoVersion();
                        if (hay) {
                            ofrecerVersion();
                        } else if (manual) {
                            Toast.makeText(MainActivity.this, "Ya tiene la última versión (" + versionApp() + ").", Toast.LENGTH_LONG).show();
                        }
                    }
                });
            }
        }).start();
    }

    /** Franja naranja arriba mientras haya una versión nueva sin instalar: texto + botón en una fila. */
    private void pintarAvisoVersion() {
        if (avisoVersion == null) return;
        avisoVersion.removeAllViews();
        if (versionNueva == null) return;
        LinearLayout card = tarjeta("#fff7ed", "#fdba74");
        card.setOrientation(LinearLayout.HORIZONTAL);
        card.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout txt = new LinearLayout(this);
        txt.setOrientation(LinearLayout.VERTICAL);
        TextView t = texto("Versión nueva: " + versionNueva.version, 14, "#9a3412");
        t.setTypeface(Typeface.DEFAULT_BOLD);
        txt.addView(t);
        txt.addView(texto("Tiene la " + versionApp() + ". Se instala encima.", 12, "#9a3412"));
        card.addView(txt, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        TextView b = boton("Actualizar", "#ea580c", "#ffffff");
        b.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { instalar(); }
        });
        card.addView(b);
        avisoVersion.addView(card);
    }

    private void ofrecerVersion() {
        new AlertDialog.Builder(this)
                .setTitle("Versión nueva de FactuposSMS")
                .setMessage("Hay una versión nueva: " + versionNueva.version + " (tiene la " + versionApp() + ").\n\n"
                        + "Se instala encima: no se pierde la empresa de cada chip.")
                .setPositiveButton("Actualizar ahora", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface d, int w) { instalar(); }
                })
                .setNegativeButton("Más tarde", null)
                .show();
    }

    private void instalar() {
        final Actualizar.Info i = versionNueva;
        if (i == null) return;
        if (!Actualizar.puedeInstalar(this)) {
            // Android 8+: la primera vez hay que autorizar a la app a instalar. Se vuelve con «atrás».
            new AlertDialog.Builder(this)
                    .setTitle("Falta un permiso (solo la primera vez)")
                    .setMessage("Para que la app se actualice sola, Android pide autorizarla una vez.\n\n"
                            + "En la pantalla que se abre, active «Permitir de esta fuente», vuelva atrás y "
                            + "apriete otra vez «Actualizar ahora».")
                    .setPositiveButton("Dar el permiso", new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface d, int w) {
                            try {
                                startActivity(Actualizar.pantallaPermiso(MainActivity.this));
                            } catch (Exception e) {
                                Actualizar.abrirEnNavegador(MainActivity.this, i);
                            }
                        }
                    })
                    .setNeutralButton("Bajarla con el navegador", new DialogInterface.OnClickListener() {
                        public void onClick(DialogInterface d, int w) { Actualizar.abrirEnNavegador(MainActivity.this, i); }
                    })
                    .setNegativeButton("Cancelar", null)
                    .show();
            return;
        }
        Toast.makeText(this, "Descargando la versión " + i.version + "…", Toast.LENGTH_LONG).show();
        new Thread(new Runnable() {
            public void run() {
                final String error = Actualizar.descargarEInstalar(MainActivity.this, i);
                if (error == null) return; // el instalador de Android pide la confirmación
                runOnUiThread(new Runnable() {
                    public void run() {
                        if (isFinishing()) return;
                        new AlertDialog.Builder(MainActivity.this)
                                .setTitle("No se pudo actualizar")
                                .setMessage(error + ".")
                                .setPositiveButton("Bajarla con el navegador", new DialogInterface.OnClickListener() {
                                    public void onClick(DialogInterface d, int w) { Actualizar.abrirEnNavegador(MainActivity.this, i); }
                                })
                                .setNegativeButton("Cerrar", null)
                                .show();
                    }
                });
            }
        }).start();
    }

    /** Un chip: etiqueta, campo de la empresa con «Guardar» en la misma fila, y si esa empresa existe. */
    private void agregarFichaSim(LinearLayout destino, final int slot, String etiqueta) {
        LinearLayout cab = new LinearLayout(this);
        cab.setOrientation(LinearLayout.HORIZONTAL);
        cab.setGravity(Gravity.CENTER_VERTICAL);
        TextView lbl = texto(etiqueta, 13, TEXTO);
        lbl.setTypeface(Typeface.DEFAULT_BOLD);
        cab.addView(lbl, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        final String fEtiqueta = etiqueta;
        TextView ver = boton("Ver mensajes SIM " + (slot + 1), "#e8eefa", NAVY);
        ver.setTextSize(12);
        ver.setPadding(pad * 2 / 3, pad / 4, pad * 2 / 3, pad / 4);
        ver.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { verMensajesChip(slot, fEtiqueta); }
        });
        cab.addView(ver);
        destino.addView(cab);

        LinearLayout filaCampo = new LinearLayout(this);
        filaCampo.setOrientation(LinearLayout.HORIZONTAL);
        filaCampo.setGravity(Gravity.CENTER_VERTICAL);
        filaCampo.setPadding(0, pad / 3, 0, 0);

        final EditText et = new EditText(this);
        et.setSingleLine(true);
        et.setTextSize(15);
        et.setHint("nombre de la empresa");
        et.setText(Config.getEmpresaForSlot(this, slot));
        et.setPadding(pad * 3 / 4, pad / 2, pad * 3 / 4, pad / 2);
        GradientDrawable bgCampo = new GradientDrawable();
        bgCampo.setColor(Color.parseColor("#f8fafc"));
        bgCampo.setStroke((int) (1 * dp), Color.parseColor("#cbd5e1"));
        bgCampo.setCornerRadius(8 * dp);
        et.setBackground(bgCampo);
        LinearLayout.LayoutParams lpCampo = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        lpCampo.setMargins(0, 0, pad / 2, 0);
        filaCampo.addView(et, lpCampo);

        final TextView verif = texto("", 12, GRIS);
        verif.setPadding(0, pad / 3, 0, 0);

        TextView guardar = boton("Guardar", NAVY, "#ffffff");
        guardar.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                String empresa = et.getText().toString().trim();
                Config.setEmpresaForSlot(MainActivity.this, slot, empresa);
                Toast.makeText(MainActivity.this, "Guardado SIM " + (slot + 1), Toast.LENGTH_SHORT).show();
                verificarEmpresa(empresa, verif);
            }
        });
        filaCampo.addView(guardar);
        destino.addView(filaCampo);
        destino.addView(verif);

        verificarEmpresa(Config.getEmpresaForSlot(this, slot), verif);
    }

    /**
     * Pregunta al servidor si existe la empresa y lo dice debajo de la ficha del SIM (#1307).
     * Un nombre mal escrito (ej. el nombre comercial en vez de la BD) deja los pagos sin aparecerle a nadie.
     */
    private void verificarEmpresa(final String empresa, final TextView destino) {
        if (empresa.isEmpty()) {
            pintarVerificacion(destino, "⚠ Sin empresa: sus mensajes no le aparecen a nadie.", "#b45309");
            return;
        }
        pintarVerificacion(destino, "Comprobando el nombre…", GRIS);
        new Thread(new Runnable() {
            public void run() {
                final Boolean existe = Poster.verificarEmpresa(Config.getToken(MainActivity.this), empresa);
                runOnUiThread(new Runnable() {
                    public void run() {
                        if (existe == null) {
                            pintarVerificacion(destino, "No se pudo comprobar el nombre en este momento.", GRIS);
                        } else if (existe) {
                            pintarVerificacion(destino, "✓ La empresa «" + empresa + "» existe.", VERDE);
                        } else {
                            pintarVerificacion(destino, "✗ No existe ninguna empresa «" + empresa + "». Escriba el nombre "
                                    + "de la base de datos tal cual sale en amarillo al final del menú de FactuPOS "
                                    + "(pegado y en minúsculas).", "#b91c1c");
                        }
                    }
                });
            }
        }).start();
    }

    private void pintarVerificacion(TextView destino, String texto, String color) {
        destino.setText(texto);
        destino.setTextColor(Color.parseColor(color));
    }

    /** Pinta el último mensaje y, si hay mensajes sin cargar, el aviso con «Reintentar». */
    private void pintarMensajes() {
        if (ultimoMensaje == null || listaMensajes == null) return;
        List<JSONObject> lista = Aviso.leer(this);
        ultimoMensaje.removeAllViews();
        listaMensajes.removeAllViews();

        if (lista.isEmpty()) {
            LinearLayout vacio = tarjetaBlanca();
            vacio.addView(texto("Todavía no ha entrado ningún mensaje. Cuando entre, aparece aquí y suena.", 13, GRIS));
            ultimoMensaje.addView(vacio);
            return;
        }

        JSONObject ultimo = lista.get(0);
        View tarjeta = tarjetaMensaje(ultimo);
        ultimoMensaje.addView(tarjeta);
        // Parpadeo suave cuando entra un mensaje nuevo o cambia su estado, para que se note.
        String firma = ultimo.optString("clave") + "|" + ultimo.optString("estado");
        if (firmaUltimo != null && !firma.equals(firmaUltimo)) {
            tarjeta.setAlpha(0f);
            tarjeta.animate().alpha(1f).setDuration(700).start();
        }
        firmaUltimo = firma;

        int pendientes = 0;
        for (JSONObject it : lista) if (Aviso.esPendiente(it)) pendientes++;
        if (pendientes > 0) {
            LinearLayout aviso = tarjeta("#fef2f2", "#fca5a5");
            aviso.setOrientation(LinearLayout.HORIZONTAL);
            aviso.setGravity(Gravity.CENTER_VERTICAL);
            aviso.addView(texto("⚠ " + (pendientes == 1 ? "1 mensaje sin cargar" : pendientes + " mensajes sin cargar")
                    + ". Se mandan solos al volver la conexión.", 13, "#b91c1c"),
                    new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            TextView reintentar = boton("Reintentar", ROJO, "#ffffff");
            reintentar.setOnClickListener(new View.OnClickListener() {
                public void onClick(View v) {
                    Toast.makeText(MainActivity.this, "Reintentando…", Toast.LENGTH_SHORT).show();
                    Aviso.reintentarEnFondo(MainActivity.this, 0);
                }
            });
            aviso.addView(reintentar);
            listaMensajes.addView(aviso);
        }

    }

    /** El celular/chip por el que entró un mensaje: «SIM 1», «SIM 2»… (lo que guardó el receptor). */
    private String chipDe(JSONObject it) {
        String sim = it.optString("sim");
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("^SIM(\\d+)").matcher(sim);
        if (m.find()) return "SIM " + m.group(1);
        return sim.isEmpty() ? "Sin chip" : sim;
    }

    /** Botón «Ver mensajes» de un celular: abre la lista de los SMS que entraron por ese chip (#3035). */
    private void verMensajesChip(int slot, String etiqueta) {
        String chip = "SIM " + (slot + 1);
        LinearLayout filas = new LinearLayout(this);
        filas.setOrientation(LinearLayout.VERTICAL);
        int n = 0;
        for (JSONObject it : Aviso.leer(this)) {
            if (!chip.equals(chipDe(it))) continue;
            if (n++ > 0) filas.addView(divisor());
            filas.addView(filaMensaje(it));
        }
        if (n == 0) {
            TextView v = texto("Todavía no ha entrado ningún mensaje por este chip.", 13, GRIS);
            v.setPadding(pad, pad, pad, pad);
            filas.addView(v);
        }
        ScrollView sv = new ScrollView(this);
        sv.addView(filas);
        new AlertDialog.Builder(this)
                .setTitle(etiqueta + (n > 0 ? " · " + n + (n == 1 ? " mensaje" : " mensajes") : ""))
                .setView(sv)
                .setPositiveButton("Cerrar", null)
                .show();
    }

    /** Color de un mensaje según cómo le fue: rojo no cargado, gris enviando, ámbar sin empresa, verde bien. */
    private String colorDe(JSONObject it) {
        if (Aviso.esPendiente(it)) return ROJO;
        if (Aviso.ENVIANDO.equals(it.optString("estado"))) return GRIS;
        if (!Aviso.bien(it)) return AMBAR;
        return VERDE;
    }

    /** El último mensaje: tarjeta con franja de color a la izquierda. */
    private View tarjetaMensaje(JSONObject it) {
        String color = colorDe(it);
        LinearLayout card = tarjetaBlanca();
        card.setOrientation(LinearLayout.HORIZONTAL);
        card.setPadding(0, 0, 0, 0);
        View franja = new View(this);
        GradientDrawable bgF = new GradientDrawable();
        bgF.setColor(Color.parseColor(color));
        bgF.setCornerRadii(new float[]{10 * dp, 10 * dp, 0, 0, 0, 0, 10 * dp, 10 * dp});
        franja.setBackground(bgF);
        card.addView(franja, new LinearLayout.LayoutParams((int) (5 * dp), ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout cuerpo = new LinearLayout(this);
        cuerpo.setOrientation(LinearLayout.VERTICAL);
        cuerpo.setPadding(pad, pad * 3 / 4, pad, pad * 3 / 4);
        TextView t = texto(Aviso.titulo(it), 16, color);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        cuerpo.addView(t);
        cuerpo.addView(texto(Aviso.detalle(it), 13, "#334155"));
        cuerpo.addView(texto(pie(it), 11, GRIS));
        card.addView(cuerpo, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        return card;
    }

    /** Un mensaje anterior: punto de color, título y detalle en una línea, y la hora. */
    private View filaMensaje(JSONObject it) {
        LinearLayout fila = new LinearLayout(this);
        fila.setOrientation(LinearLayout.HORIZONTAL);
        fila.setPadding(pad, pad / 2, pad, pad / 2);

        TextView punto = texto("●", 11, colorDe(it));
        punto.setPadding(0, (int) (2 * dp), pad / 2, 0);
        fila.addView(punto);

        LinearLayout cuerpo = new LinearLayout(this);
        cuerpo.setOrientation(LinearLayout.VERTICAL);
        TextView t = texto(Aviso.titulo(it), 13, TEXTO);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        cuerpo.addView(t);
        TextView d = texto(Aviso.detalle(it), 12, "#475569");
        d.setMaxLines(2);
        d.setEllipsize(TextUtils.TruncateAt.END);
        cuerpo.addView(d);
        cuerpo.addView(texto(pie(it), 11, GRIS));
        fila.addView(cuerpo, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        return fila;
    }

    /** Fecha y qué API atendió el mensaje (navy o legacy): mientras convivan las dos, así se ve cuál trabajó. */
    private String pie(JSONObject it) {
        String ruta = it.optString("ruta");
        return it.optString("fecha") + (ruta.isEmpty() ? "" : " · API " + ruta);
    }

    // --------------------------------------------------------- piezas de la UI

    /** Título chico de cada bloque, en mayúsculas. */
    private TextView seccion(String s) {
        TextView tv = texto(s.toUpperCase(), 11, GRIS);
        tv.setTypeface(Typeface.DEFAULT_BOLD);
        tv.setLetterSpacing(0.06f);
        tv.setPadding((int) (2 * dp), pad, 0, pad / 3);
        return tv;
    }

    private LinearLayout tarjetaBlanca() {
        return tarjeta("#ffffff", BORDE);
    }

    private LinearLayout tarjeta(String fondo, String borde) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(pad, pad * 3 / 4, pad, pad * 3 / 4);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor(fondo));
        bg.setStroke((int) (1 * dp), Color.parseColor(borde));
        bg.setCornerRadius(10 * dp);
        card.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, pad / 3, 0, 0);
        card.setLayoutParams(lp);
        return card;
    }

    private View divisor() {
        View v = new View(this);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, (int) dp));
        lp.setMargins(0, pad / 2, 0, pad / 2);
        v.setLayoutParams(lp);
        v.setBackgroundColor(Color.parseColor(BORDE));
        return v;
    }

    /** Botón chico de pastilla (en vez del Button gris de Android). */
    private TextView boton(String s, String fondo, String color) {
        TextView b = texto(s, 13, color);
        b.setTypeface(Typeface.DEFAULT_BOLD);
        b.setGravity(Gravity.CENTER);
        b.setPadding(pad, pad / 2, pad, pad / 2);
        pintarBoton(b, fondo);
        conToque(b);
        return b;
    }

    private void pintarBoton(TextView b, String fondo) {
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.parseColor(fondo));
        bg.setCornerRadius(8 * dp);
        b.setBackground(bg);
    }

    /** Una acción de la cuadrícula, compacta: ícono a la izquierda, nombre y una línea de ayuda. */
    private View accion(String icono, String titulo, String sub, View.OnClickListener al, String clave) {
        LinearLayout a = tarjetaBlanca();
        a.setOrientation(LinearLayout.HORIZONTAL);
        a.setGravity(Gravity.CENTER_VERTICAL);
        a.setPadding(pad * 2 / 3, pad / 3, pad / 2, pad / 3);
        TextView i = texto(icono, 15, NAVY);
        i.setPadding(0, 0, pad / 2, 0);
        a.addView(i);
        LinearLayout txt = new LinearLayout(this);
        txt.setOrientation(LinearLayout.VERTICAL);
        TextView t = texto(titulo, 12, TEXTO);
        t.setTypeface(Typeface.DEFAULT_BOLD);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.END);
        txt.addView(t);
        TextView s = texto(sub, 10, GRIS);
        s.setSingleLine(true);
        s.setEllipsize(TextUtils.TruncateAt.END);
        txt.addView(s);
        a.addView(txt, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        if ("sonido".equals(clave)) subSonido = s;
        conToque(a);
        a.setOnClickListener(al);
        return a;
    }

    /** Dos vistas lado a lado, mitad y mitad. */
    private View fila(View izq, View der) {
        LinearLayout f = new LinearLayout(this);
        f.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams lpI = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f);
        lpI.setMargins(0, pad / 3, pad / 4, 0);
        LinearLayout.LayoutParams lpD = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f);
        lpD.setMargins(pad / 4, pad / 3, 0, 0);
        f.addView(izq, lpI);
        f.addView(der, lpD);
        return f;
    }

    /** El «brillo» de Android al tocar, para que se note que es un botón. */
    private void conToque(View v) {
        v.setClickable(true);
        try {
            TypedArray ta = obtainStyledAttributes(new int[]{android.R.attr.selectableItemBackground});
            v.setForeground(ta.getDrawable(0));
            ta.recycle();
        } catch (Exception ignored) { }
    }

    private TextView texto(String s, int sp, String color) {
        TextView tv = new TextView(this);
        tv.setText(s);
        tv.setTextSize(sp);
        tv.setTextColor(Color.parseColor(color));
        return tv;
    }

    private String versionApp() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "";
        }
    }

    private void toggleServicio() {
        if (Config.isServicioActivo(this)) {
            Config.setServicioActivo(this, false);
            stopService(new android.content.Intent(this, ForwardService.class));
        } else {
            Config.setServicioActivo(this, true);
            ForwardService.start(this);
        }
        refrescarServicio();
    }

    /** El estado del servicio sale en dos lados: la pastilla de la barra y la tarjeta Servicio. */
    private void refrescarServicio() {
        boolean activo = Config.isServicioActivo(this);
        if (pillEstado != null) {
            pillEstado.setText(activo ? "● En marcha" : "● Detenido");
            GradientDrawable bg = new GradientDrawable();
            bg.setColor(Color.parseColor(activo ? VERDE : ROJO));
            bg.setCornerRadius(20 * dp);
            pillEstado.setBackground(bg);
        }
        if (estadoServicio != null) {
            estadoServicio.setText(activo ? "✓ Capturando los SMS" : "Detenido: no se mandan los SMS");
            estadoServicio.setTextColor(Color.parseColor(activo ? VERDE : ROJO));
        }
        if (btnServicio != null) {
            btnServicio.setText(activo ? "Detener" : "Iniciar");
            pintarBoton(btnServicio, activo ? "#64748b" : VERDE);
        }
    }

    private void refrescarSonido() {
        if (subSonido != null) subSonido.setText(Config.isSonidoActivo(this) ? "ACTIVADO" : "DESACTIVADO");
    }
}
