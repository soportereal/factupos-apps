package com.factupos.apps

import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

/**
 * FactuPOS Apps de ANDROID (#3957, dueño 25-nov-2026) — la gemela de la de Windows y la de Linux.
 * La lista y las descargas las hace Dart; acá solo lo que es de Android:
 *  - instalados(paquetes)   → qué versión de cada app hay en el teléfono
 *  - instalar(ruta, paquete) → abre el INSTALADOR de Android (el usuario confirma ahí). Antes compara la firma del APK con
 *                              la de la app instalada: si no coincide, Android diría «App no instalada» sin explicar nada.
 *  - abrir(paquete) · desinstalar(paquete) · es32()
 */
class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "factupos_apps/android")
            .setMethodCallHandler { call, result ->
                try {
                    when (call.method) {
                        "instalados" -> {
                            val salida = HashMap<String, Any>()
                            for (p in call.argument<List<String>>("paquetes") ?: emptyList()) {
                                val i = info(p, 0) ?: continue
                                @Suppress("DEPRECATION")
                                val code = if (Build.VERSION.SDK_INT >= 28) i.longVersionCode else i.versionCode.toLong()
                                salida[p] = hashMapOf("versionCode" to code, "version" to (i.versionName ?: ""))
                            }
                            result.success(salida)
                        }
                        "instalar" -> result.success(instalar(call.argument<String>("ruta") ?: "", call.argument<String>("paquete") ?: ""))
                        "abrir" -> {
                            val it = packageManager.getLaunchIntentForPackage(call.argument<String>("paquete") ?: "")
                            if (it == null) result.success(false) else {
                                startActivity(it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); result.success(true)
                            }
                        }
                        "desinstalar" -> {
                            @Suppress("DEPRECATION")
                            startActivity(
                                Intent(Intent.ACTION_DELETE, Uri.parse("package:" + (call.argument<String>("paquete") ?: "")))
                                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                            )
                            result.success(true)
                        }
                        "es32" -> result.success(Build.SUPPORTED_64_BIT_ABIS.isEmpty())
                        else -> result.notImplemented()
                    }
                } catch (e: Exception) {
                    result.error(call.method, e.message ?: "Error de Android", null)
                }
            }
    }

    private fun info(paquete: String, flags: Int): PackageInfo? = try {
        @Suppress("DEPRECATION")
        packageManager.getPackageInfo(paquete, flags)
    } catch (e: PackageManager.NameNotFoundException) {
        null
    }

    /** Las firmas (certificados) de un PackageInfo, como texto comparable. */
    @Suppress("DEPRECATION")
    private fun firmas(i: PackageInfo?): Set<String> {
        if (i == null) return emptySet()
        val s = if (Build.VERSION.SDK_INT >= 28) {
            val si = i.signingInfo ?: return emptySet()
            if (si.hasMultipleSigners()) si.apkContentsSigners else si.signingCertificateHistory
        } else i.signatures
        return (s ?: emptyArray()).map { it.toCharsString() }.toSet()
    }

    private fun instalar(ruta: String, paquete: String): String {
        val apk = File(ruta)
        // Solo archivos de la caché de ESTA app (lo que bajó Dart), nada de afuera.
        if (!apk.exists() || !apk.canonicalPath.startsWith(cacheDir.canonicalPath)) return "ruta"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !packageManager.canRequestPackageInstalls()) {
            startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            return "permiso"
        }
        // ¿La instalada tiene OTRA firma? (las versiones viejas de Print y FactuSuper salieron con llaves de prueba)
        @Suppress("DEPRECATION")
        val fl = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
        val instalada = firmas(info(paquete, fl))
        if (instalada.isNotEmpty()) {
            @Suppress("DEPRECATION")
            val nueva = firmas(packageManager.getPackageArchiveInfo(apk.path, fl))
            if (nueva.isNotEmpty() && instalada.intersect(nueva).isEmpty()) return "firma"
        }
        val uri = FileProvider.getUriForFile(this, "$packageName.archivos", apk)
        startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        return "ok"
    }
}
