package com.factupos.factusuper

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

/**
 * #3957 — Actualización con aviso en Android: la app (Dart) baja el APK nuevo a su caché y llama a «instalar»; acá se
 * abre el INSTALADOR de Android con ese archivo. El cajero confirma ahí (Android nunca instala sin que alguien acepte).
 * Si el equipo no deja instalar apps de esta fuente, se abre el ajuste para permitirlo y se devuelve "permiso".
 */
class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "factusuper/actualizar")
            .setMethodCallHandler { call, result ->
                if (call.method != "instalar") {
                    result.notImplemented()
                    return@setMethodCallHandler
                }
                try {
                    val ruta = call.argument<String>("ruta") ?: ""
                    val apk = File(ruta)
                    // Solo archivos de la caché de ESTA app (lo que bajó Dart), nada de afuera.
                    if (!apk.exists() || !apk.canonicalPath.startsWith(cacheDir.canonicalPath)) {
                        result.error("ruta", "El archivo de la versión nueva no está", null)
                        return@setMethodCallHandler
                    }
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !packageManager.canRequestPackageInstalls()) {
                        startActivity(
                            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName"))
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        )
                        result.success("permiso")
                        return@setMethodCallHandler
                    }
                    val uri = FileProvider.getUriForFile(this, "$packageName.archivos", apk)
                    startActivity(
                        Intent(Intent.ACTION_VIEW)
                            .setDataAndType(uri, "application/vnd.android.package-archive")
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                    result.success("ok")
                } catch (e: Exception) {
                    result.error("instalar", e.message ?: "No se pudo abrir el instalador", null)
                }
            }
    }
}
