package com.factupos.kiosk;

import javax.sound.sampled.AudioFormat;
import javax.sound.sampled.AudioSystem;
import javax.sound.sampled.SourceDataLine;

/** Tonos de feedback (equivalente a winsound del kiosk.py). Best-effort. */
public final class Sound {

    public static void ok() {
        new Thread(() -> {
            tone(660, 110); tone(880, 110); tone(1175, 130);
        }, "beep-ok").start();
    }

    public static void err() {
        new Thread(() -> tone(220, 350), "beep-err").start();
    }

    private static void tone(int hz, int ms) {
        try {
            float rate = 44100f;
            int n = (int) (rate * ms / 1000f);
            byte[] buf = new byte[n * 2];   // 16-bit -> 2 bytes por muestra
            int fade = (int) (rate * 0.006);
            for (int i = 0; i < n; i++) {
                double env = 1.0;
                if (i < fade) env = i / (double) fade;
                else if (i > n - fade) env = (n - i) / (double) fade;
                short s = (short) (Math.sin(2.0 * Math.PI * i * hz / rate) * 12000 * env);
                buf[i * 2]     = (byte) (s & 0xff);          // little-endian
                buf[i * 2 + 1] = (byte) ((s >> 8) & 0xff);
            }
            // 16-bit, mono, signed, little-endian: lo más compatible con ALSA/PulseAudio
            AudioFormat fmt = new AudioFormat(rate, 16, 1, true, false);
            SourceDataLine line = AudioSystem.getSourceDataLine(fmt);
            try {
                line.open(fmt);
                line.start();
                line.write(buf, 0, buf.length);
                line.drain();
                line.stop();
            } finally {
                line.close();
            }
        } catch (Exception e) {
            // sin audio disponible -> beep del toolkit
            try { java.awt.Toolkit.getDefaultToolkit().beep(); } catch (Exception ignored) {}
        }
    }

    private Sound() {}
}
