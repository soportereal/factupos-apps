package woyou.aidlservice.jiuiv5;

import woyou.aidlservice.jiuiv5.ICallback;

interface IWoyouService {

    /**
     * Inicializar impresora (resetear configuracion)
     */
    void printerInit(in ICallback callback);

    /**
     * Imprimir texto
     * @param text Texto a imprimir
     * @param callback Callback de resultado
     */
    void printText(String text, in ICallback callback);

    /**
     * Imprimir texto con tamanio
     * @param text Texto a imprimir
     * @param typeface Fuente (null = default)
     * @param fontsize Tamanio de fuente
     * @param callback Callback
     */
    void printTextWithFont(String text, String typeface, float fontsize, in ICallback callback);

    /**
     * Establecer alineacion
     * @param alignment 0=izquierda, 1=centro, 2=derecha
     * @param callback Callback
     */
    void setAlignment(int alignment, in ICallback callback);

    /**
     * Avanzar N lineas
     * @param n Numero de lineas
     * @param callback Callback
     */
    void lineWrap(int n, in ICallback callback);

    /**
     * Cortar papel (solo modelos con cuchilla)
     * @param callback Callback
     */
    void cutPaper(in ICallback callback);

    /**
     * Obtener estado de la impresora
     * @return 1=normal, 2=preparando, 3=error comunicacion,
     *         4=sin papel, 5=sobrecalentada, 505=sin impresora
     */
    int updatePrinterState();

    /**
     * Imprimir codigo de barras
     */
    void printBarCode(String data, int symbology, int height, int width, int textposition, in ICallback callback);

    /**
     * Imprimir codigo QR
     */
    void printQRCode(String data, int modulesize, int errorlevel, in ICallback callback);

    /**
     * Establecer tamanio de fuente
     */
    void setFontSize(float fontsize, in ICallback callback);

    /**
     * Establecer negrita
     */
    void printerSelfChecking(in ICallback callback);
}
