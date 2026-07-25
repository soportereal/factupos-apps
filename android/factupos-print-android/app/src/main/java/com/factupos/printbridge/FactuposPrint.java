package com.factupos.printbridge;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.IBinder;
import android.os.RemoteException;
import android.util.Log;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import woyou.aidlservice.jiuiv5.IWoyouService;
import woyou.aidlservice.jiuiv5.ICallback;

/**
 * FactuposPrint - Wrapper para la impresora interna SUNMI via AIDL
 *
 * SUNMI V2s usa el paquete "com.sunmi" (no "woyou.aidlservice.jiuiv5")
 * pero el servicio AIDL sigue siendo IWoyouService internamente.
 */
public class FactuposPrint {

    private static final String TAG = "FactuposPrint";
    private static FactuposPrint sInstance;

    private Context context;
    private IWoyouService printerService;
    private boolean serviceConnected = false;
    private String boundService = "ninguno";
    private String bindLog = "";

    // Callback generico para operaciones no-bloqueantes (init, alignment, lineWrap, cut)
    private final ICallback callback = new ICallback.Stub() {
        @Override
        public void onRunResult(boolean isSuccess) throws RemoteException {
            Log.d(TAG, "onRunResult: " + isSuccess);
        }

        @Override
        public void onReturnString(String result) throws RemoteException {
            Log.d(TAG, "onReturnString: " + result);
        }

        @Override
        public void onRaiseException(int code, String msg) throws RemoteException {
            Log.e(TAG, "onRaiseException: code=" + code + " msg=" + msg);
        }

        @Override
        public void onPrintResult(int code, String msg) throws RemoteException {
            Log.d(TAG, "onPrintResult: code=" + code + " msg=" + msg);
        }
    };

    /**
     * Callback bloqueante: espera a que la impresora confirme antes de continuar.
     * Usa CountDownLatch para sincronizar el hilo que llama con el callback AIDL.
     */
    private static class BlockingCallback extends ICallback.Stub {
        private final CountDownLatch latch = new CountDownLatch(1);
        private boolean success = false;

        @Override
        public void onRunResult(boolean isSuccess) throws RemoteException {
            success = isSuccess;
            latch.countDown();
        }

        @Override
        public void onReturnString(String result) throws RemoteException {
            latch.countDown();
        }

        @Override
        public void onRaiseException(int code, String msg) throws RemoteException {
            Log.e(TAG, "BlockingCallback exception: code=" + code + " msg=" + msg);
            success = false;
            latch.countDown();
        }

        @Override
        public void onPrintResult(int code, String msg) throws RemoteException {
            success = (code == 0);
            latch.countDown();
        }

        /** Esperar hasta que el callback dispare o se agote el timeout */
        public boolean await(long timeoutMs) {
            try {
                return latch.await(timeoutMs, TimeUnit.MILLISECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return false;
            }
        }
    }

    private final ServiceConnection serviceConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder service) {
            printerService = IWoyouService.Stub.asInterface(service);
            serviceConnected = true;
            boundService = name != null ? name.flattenToShortString() : "desconocido";
            Log.i(TAG, "Servicio SUNMI conectado: " + boundService);
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            printerService = null;
            serviceConnected = false;
            Log.w(TAG, "Servicio SUNMI desconectado");
        }
    };

    private FactuposPrint() {}

    public static synchronized FactuposPrint getInstance() {
        if (sInstance == null) {
            sInstance = new FactuposPrint();
        }
        return sInstance;
    }

    /**
     * Inicializar conexion al servicio AIDL de SUNMI
     * Intenta multiples variantes del servicio
     */
    public void init(Context ctx) {
        this.context = ctx.getApplicationContext();
        StringBuilder log = new StringBuilder();

        // === V2s: com.sunmi.sunmilopenservice (paquete detectado en debug) ===
        if (tryBind("com.sunmi.sunmilopenservice", "woyou.aidlservice.jiuiv5.IWoyouService", log)) return;
        if (tryBindComponent("com.sunmi.sunmilopenservice", "com.sunmi.sunmilopenservice.WoyouService", log)) return;
        if (tryBindComponent("com.sunmi.sunmilopenservice", "com.sunmi.sunmilopenservice.service.InnerPrinterService", log)) return;
        if (tryBindComponent("com.sunmi.sunmilopenservice", "com.sunmi.sunmilopenservice.service.WoyouService", log)) return;
        if (tryBindComponent("com.sunmi.sunmilopenservice", "woyou.aidlservice.jiuiv5.WoyouService", log)) return;

        // === com.sunmi ===
        if (tryBind("com.sunmi", "woyou.aidlservice.jiuiv5.IWoyouService", log)) return;
        if (tryBindComponent("com.sunmi", "com.sunmi.aidlservice.WoyouService", log)) return;

        // === V2 clasico: woyou.aidlservice.jiuiv5 ===
        if (tryBind("woyou.aidlservice.jiuiv5", "woyou.aidlservice.jiuiv5.IWoyouService", log)) return;
        if (tryBindComponent("woyou.aidlservice.jiuiv5", "woyou.aidlservice.jiuiv5.WoyouService", log)) return;

        // === Ext printer ===
        if (tryBind("com.sunmi.extprinterservice", "com.sunmi.extprinterservice.PrinterService", log)) return;

        bindLog = log.toString();
        Log.w(TAG, "Ningun servicio SUNMI encontrado. Log: " + bindLog);
    }

    private boolean tryBind(String pkg, String action, StringBuilder log) {
        try {
            Intent intent = new Intent();
            intent.setPackage(pkg);
            intent.setAction(action);
            boolean bound = context.bindService(intent, serviceConnection, Context.BIND_AUTO_CREATE);
            log.append(pkg).append("/action=").append(bound).append("; ");
            Log.i(TAG, "bind [" + pkg + " action] -> " + bound);
            return bound;
        } catch (Exception e) {
            log.append(pkg).append("/action_err=").append(e.getMessage()).append("; ");
            return false;
        }
    }

    private boolean tryBindComponent(String pkg, String cls, StringBuilder log) {
        try {
            Intent intent = new Intent();
            intent.setComponent(new ComponentName(pkg, cls));
            boolean bound = context.bindService(intent, serviceConnection, Context.BIND_AUTO_CREATE);
            log.append(pkg).append("/comp=").append(bound).append("; ");
            Log.i(TAG, "bind [" + pkg + " component " + cls + "] -> " + bound);
            return bound;
        } catch (Exception e) {
            log.append(pkg).append("/comp_err=").append(e.getMessage()).append("; ");
            return false;
        }
    }

    public void release() {
        if (context != null && serviceConnected) {
            try {
                context.unbindService(serviceConnection);
            } catch (Exception e) {
                Log.w(TAG, "Error al desenlazar servicio", e);
            }
        }
        serviceConnected = false;
        printerService = null;
    }

    public boolean isReady() {
        if (!serviceConnected || printerService == null) return false;
        try {
            int status = printerService.updatePrinterState();
            return status == 1;
        } catch (RemoteException e) {
            Log.e(TAG, "Error al verificar estado", e);
            return false;
        }
    }

    public String getServiceInfo() {
        return "connected=" + serviceConnected + ", service=" + boundService + ", log=" + bindLog;
    }

    public boolean hasPaper() {
        if (!serviceConnected || printerService == null) return false;
        try {
            int status = printerService.updatePrinterState();
            return status != 4;
        } catch (RemoteException e) {
            return true;
        }
    }

    public boolean printText(String text) {
        if (!serviceConnected || printerService == null) {
            Log.e(TAG, "Servicio no conectado (" + boundService + ") log: " + bindLog);
            return false;
        }

        try {
            printerService.printerInit(callback);
            printerService.setAlignment(0, callback);

            // Enviar en bloques con callback bloqueante (espera confirmación)
            final int BLOCK_SIZE = 1000;
            final long TIMEOUT_MS = 2000;

            int offset = 0;
            int blockNum = 0;
            while (offset < text.length()) {
                int end = Math.min(offset + BLOCK_SIZE, text.length());
                // No cortar a mitad de línea
                if (end < text.length()) {
                    int nl = text.lastIndexOf('\n', end);
                    if (nl > offset) end = nl + 1;
                }
                sendBlock(text.substring(offset, end), TIMEOUT_MS);
                offset = end;
                blockNum++;
            }

            Log.d(TAG, "Enviados " + blockNum + " bloques");

            printerService.lineWrap(4, callback);
            try {
                printerService.cutPaper(callback);
            } catch (Exception e) {
                Log.d(TAG, "Sin cuchilla (normal en V2s)");
            }
            Log.i(TAG, "Texto impreso correctamente (" + text.length() + " chars, " + blockNum + " bloques)");
            return true;
        } catch (RemoteException e) {
            Log.e(TAG, "Error al imprimir", e);
            return false;
        }
    }

    /**
     * Enviar un bloque de texto y esperar confirmación vía callback bloqueante.
     * @return true si el callback confirmó antes del timeout
     */
    private boolean sendBlock(String block, long timeoutMs) throws RemoteException {
        BlockingCallback bc = new BlockingCallback();
        printerService.printText(block, bc);
        boolean confirmed = bc.await(timeoutMs);
        if (!confirmed) {
            Log.w(TAG, "Timeout esperando confirmación (" + block.length() + " chars)");
        }
        return confirmed;
    }
}
