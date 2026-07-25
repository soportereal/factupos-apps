package com.factupos.printbridge;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.os.Build;
import android.os.ParcelUuid;
import android.util.Log;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * BlePrinter - Impresora BLE con scan + GATT
 * v3.1.0: Hace BLE scan para descubrir el dispositivo antes de conectar GATT
 */
public class BlePrinter {

    private static final String TAG = "BlePrinter";

    private static final UUID[] KNOWN_SERVICES = {
        UUID.fromString("000018f0-0000-1000-8000-00805f9b34fb"),
        UUID.fromString("49535343-fe7d-4ae5-8fa9-9fafd205e455"),
        UUID.fromString("e7810a71-73ae-499d-8c15-faa9aef0c3f2"),
        UUID.fromString("0000ff00-0000-1000-8000-00805f9b34fb"),
        UUID.fromString("0000ffe0-0000-1000-8000-00805f9b34fb"),
        UUID.fromString("0000fff0-0000-1000-8000-00805f9b34fb"),
        UUID.fromString("0000ae30-0000-1000-8000-00805f9b34fb"),
        UUID.fromString("0000ae3a-0000-1000-8000-00805f9b34fb"),
        UUID.fromString("0000feea-0000-1000-8000-00805f9b34fb"),
        UUID.fromString("0000fee7-0000-1000-8000-00805f9b34fb"),
        UUID.fromString("6e400001-b5a3-f393-e0a9-e50e24dcca9e"),
        UUID.fromString("0000ffe1-0000-1000-8000-00805f9b34fb"),
    };

    private final Context context;
    private final BluetoothAdapter bluetoothAdapter;
    private String lastError = "";

    private BluetoothGatt connectedGatt = null;
    private BluetoothGattCharacteristic writeCharacteristic = null;
    private String connectedAddress = "";

    public BlePrinter(Context context) {
        this.context = context.getApplicationContext();
        this.bluetoothAdapter = BluetoothAdapter.getDefaultAdapter();
    }

    public String getLastError() { return lastError; }

    public boolean isConnected() {
        return connectedGatt != null && writeCharacteristic != null;
    }

    public void disconnect() {
        if (connectedGatt != null) {
            try { connectedGatt.disconnect(); } catch (Exception ignored) {}
            try { connectedGatt.close(); } catch (Exception ignored) {}
            connectedGatt = null;
            writeCharacteristic = null;
            connectedAddress = "";
        }
    }

    /**
     * Escanear BLE para encontrar el dispositivo por MAC
     * Esto es necesario en Android 16+ donde connectGatt directo no funciona
     */
    // Todos los dispositivos encontrados en el último scan (para diagnóstico)
    private String lastScanDevices = "";
    public String getLastScanDevices() { return lastScanDevices; }

    private BluetoothDevice scanForDevice(String address, int timeoutSecs) {
        BluetoothLeScanner scanner = bluetoothAdapter.getBluetoothLeScanner();
        if (scanner == null) {
            lastError = "BLE scanner no disponible";
            return null;
        }

        final CountDownLatch latch = new CountDownLatch(1);
        final BluetoothDevice[] foundDevice = {null};
        final StringBuilder allDevices = new StringBuilder();
        final java.util.Set<String> seen = new java.util.HashSet<>();

        // Extraer nombre de la impresora del address pareado para buscar por nombre
        String targetName = "";
        try {
            BluetoothDevice paired = bluetoothAdapter.getRemoteDevice(address);
            if (paired != null && paired.getName() != null) {
                targetName = paired.getName().toUpperCase();
            }
        } catch (Exception ignored) {}
        final String searchName = targetName;

        ScanCallback scanCallback = new ScanCallback() {
            @Override
            public void onScanResult(int callbackType, ScanResult result) {
                BluetoothDevice dev = result.getDevice();
                if (dev == null) return;

                String devAddr = dev.getAddress();
                String devName = dev.getName() != null ? dev.getName() : "?";

                // Log cada dispositivo encontrado (sin duplicados)
                if (seen.add(devAddr)) {
                    allDevices.append(devName).append("=").append(devAddr).append("; ");
                    Log.i(TAG, "BLE scan vio: " + devName + " " + devAddr + " rssi=" + result.getRssi());
                }

                // Buscar por MAC exacta
                if (address.equalsIgnoreCase(devAddr)) {
                    foundDevice[0] = dev;
                    latch.countDown();
                    return;
                }

                // Buscar por nombre base (sin sufijo MAC, ej: PT210_D8CA → PT210)
                if (!searchName.isEmpty() && devName.toUpperCase().startsWith(searchName.split("_")[0])) {
                    Log.i(TAG, "BLE scan: encontrado por nombre " + devName + " MAC=" + devAddr + " (buscaba " + address + ")");
                    foundDevice[0] = dev;
                    latch.countDown();
                }
            }

            @Override
            public void onScanFailed(int errorCode) {
                lastError = "BLE scan falló, código: " + errorCode;
                Log.e(TAG, lastError);
                latch.countDown();
            }
        };

        try {
            ScanSettings settings = new ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                .build();

            Log.i(TAG, "BLE scan buscando " + address + " (nombre:" + searchName + ")...");
            scanner.startScan(null, settings, scanCallback);

            latch.await(timeoutSecs, TimeUnit.SECONDS);
            scanner.stopScan(scanCallback);

            lastScanDevices = allDevices.toString();

            if (foundDevice[0] != null) {
                Log.i(TAG, "BLE scan encontró: " + foundDevice[0].getName() + " " + foundDevice[0].getAddress());
            } else {
                lastError = "BLE scan: no encontrado en " + timeoutSecs + "s. Dispositivos vistos: " + (lastScanDevices.isEmpty() ? "NINGUNO" : lastScanDevices);
            }

            return foundDevice[0];
        } catch (Exception e) {
            lastError = "BLE scan error: " + e.getMessage();
            try { scanner.stopScan(scanCallback); } catch (Exception ignored) {}
            return null;
        }
    }

    /**
     * Conectar GATT a un dispositivo ya descubierto por scan
     */
    private boolean connectGatt(BluetoothDevice device, boolean autoConnect, int timeoutSecs) {
        writeCharacteristic = null;

        final CountDownLatch connectLatch = new CountDownLatch(1);
        final CountDownLatch servicesLatch = new CountDownLatch(1);
        final boolean[] ok = {false};
        final int[] gattStatus = {-1};

        BluetoothGattCallback cb = new BluetoothGattCallback() {
            @Override
            public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {
                gattStatus[0] = status;
                if (newState == BluetoothProfile.STATE_CONNECTED) {
                    ok[0] = true;
                    connectLatch.countDown();
                    try { gatt.discoverServices(); } catch (Exception e) { servicesLatch.countDown(); }
                } else {
                    ok[0] = false;
                    connectLatch.countDown();
                    servicesLatch.countDown();
                }
            }

            @Override
            public void onServicesDiscovered(BluetoothGatt gatt, int status) {
                if (status == BluetoothGatt.GATT_SUCCESS) {
                    writeCharacteristic = findWriteCharacteristic(gatt);
                }
                servicesLatch.countDown();
            }
        };

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                connectedGatt = device.connectGatt(context, autoConnect, cb, BluetoothDevice.TRANSPORT_LE);
            } else {
                connectedGatt = device.connectGatt(context, autoConnect, cb);
            }

            if (connectedGatt == null) {
                lastError = "connectGatt null";
                return false;
            }

            if (!connectLatch.await(timeoutSecs, TimeUnit.SECONDS) || !ok[0]) {
                lastError = "GATT timeout (status=" + gattStatus[0] + ")";
                disconnect();
                return false;
            }

            if (!servicesLatch.await(5, TimeUnit.SECONDS) || writeCharacteristic == null) {
                lastError = "Sin característica escribible";
                // Log servicios para diagnóstico
                if (connectedGatt != null) {
                    StringBuilder sb = new StringBuilder();
                    for (BluetoothGattService s : connectedGatt.getServices()) {
                        sb.append(s.getUuid()).append("[");
                        for (BluetoothGattCharacteristic c : s.getCharacteristics()) {
                            sb.append(c.getUuid()).append("/p").append(c.getProperties()).append(",");
                        }
                        sb.append("] ");
                    }
                    lastError += " Servicios:" + sb.toString();
                }
                disconnect();
                return false;
            }

            return true;
        } catch (Exception e) {
            lastError = "GATT: " + e.getMessage();
            disconnect();
            return false;
        }
    }

    /**
     * Conectar: scan BLE + GATT
     */
    public boolean connect(String address) {
        lastError = "";
        if (bluetoothAdapter == null || !bluetoothAdapter.isEnabled()) {
            lastError = "BLE: Bluetooth apagado";
            return false;
        }

        if (connectedGatt != null && address.equals(connectedAddress) && writeCharacteristic != null) {
            return true;
        }

        try { bluetoothAdapter.cancelDiscovery(); } catch (Exception ignored) {}

        // Intento 1: directo sin scan (puede funcionar en algunos dispositivos)
        Log.i(TAG, "BLE intento 1: directo");
        BluetoothDevice pairedDevice = bluetoothAdapter.getRemoteDevice(address);
        if (connectGatt(pairedDevice, false, 5)) {
            connectedAddress = address;
            Log.i(TAG, "BLE conectado directo, char=" + writeCharacteristic.getUuid());
            return true;
        }
        Log.w(TAG, "Directo falló: " + lastError);

        // Intento 2: BLE scan para descubrir el dispositivo
        Log.i(TAG, "BLE intento 2: scan + connect");
        BluetoothDevice scannedDevice = scanForDevice(address, 8);
        if (scannedDevice != null) {
            if (connectGatt(scannedDevice, false, 8)) {
                connectedAddress = address;
                Log.i(TAG, "BLE conectado post-scan, char=" + writeCharacteristic.getUuid());
                return true;
            }
            Log.w(TAG, "Post-scan GATT falló: " + lastError);

            // Intento 3: autoConnect después del scan
            Log.i(TAG, "BLE intento 3: scan + autoConnect");
            if (connectGatt(scannedDevice, true, 12)) {
                connectedAddress = address;
                Log.i(TAG, "BLE conectado autoConnect, char=" + writeCharacteristic.getUuid());
                return true;
            }
            Log.w(TAG, "AutoConnect falló: " + lastError);
        }

        lastError = "BLE: todos los intentos fallaron. " + lastError;
        return false;
    }

    private BluetoothGattCharacteristic findWriteCharacteristic(BluetoothGatt gatt) {
        for (UUID serviceUuid : KNOWN_SERVICES) {
            BluetoothGattService service = gatt.getService(serviceUuid);
            if (service != null) {
                for (BluetoothGattCharacteristic c : service.getCharacteristics()) {
                    int props = c.getProperties();
                    if ((props & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0 ||
                        (props & BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0) {
                        Log.i(TAG, "BLE char " + c.getUuid() + " en " + serviceUuid);
                        return c;
                    }
                }
            }
        }

        for (BluetoothGattService service : gatt.getServices()) {
            for (BluetoothGattCharacteristic c : service.getCharacteristics()) {
                int props = c.getProperties();
                if ((props & BluetoothGattCharacteristic.PROPERTY_WRITE) != 0 ||
                    (props & BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0) {
                    Log.i(TAG, "BLE fallback char " + c.getUuid() + " en " + service.getUuid());
                    return c;
                }
            }
        }
        return null;
    }

    /**
     * Imprimir texto via BLE GATT
     */
    public boolean printText(String address, String text) {
        lastError = "";

        if (!isConnected() || !address.equals(connectedAddress)) {
            if (!connect(address)) return false;
        }

        try {
            writeBytes(new byte[]{0x1B, 0x40}); // ESC @ Reset
            Thread.sleep(50);

            byte[] data = text.getBytes("UTF-8");
            final int CHUNK = 20;
            int offset = 0;
            while (offset < data.length) {
                int end = Math.min(offset + CHUNK, data.length);
                byte[] chunk = new byte[end - offset];
                System.arraycopy(data, offset, chunk, 0, chunk.length);
                writeBytes(chunk);
                offset = end;
                Thread.sleep(30);
            }

            writeBytes(new byte[]{0x0A, 0x0A, 0x0A, 0x0A});
            Thread.sleep(100);

            Log.i(TAG, "BLE impreso " + data.length + " bytes en " + address);
            return true;

        } catch (Exception e) {
            lastError = "BLE print: " + e.getMessage();
            Log.e(TAG, lastError, e);
            disconnect();
            return false;
        }
    }

    private void writeBytes(byte[] data) throws Exception {
        if (connectedGatt == null || writeCharacteristic == null) {
            throw new Exception("BLE no conectado");
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            int result = connectedGatt.writeCharacteristic(writeCharacteristic, data,
                BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE);
            if (result != BluetoothGatt.GATT_SUCCESS) {
                connectedGatt.writeCharacteristic(writeCharacteristic, data,
                    BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            }
        } else {
            writeCharacteristic.setValue(data);
            writeCharacteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE);
            if (!connectedGatt.writeCharacteristic(writeCharacteristic)) {
                writeCharacteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                connectedGatt.writeCharacteristic(writeCharacteristic);
            }
        }
    }
}
