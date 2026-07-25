/*
 * FactuPOS Fingerprint Service for Windows
 * Expone REST API en https://127.0.0.1:52181
 * Compatible con popup_huella.php (misma API que servicio Linux)
 *
 * Usa DigitalPersona One Touch SDK .NET
 * Compilar con: csc.exe /target:exe /reference:DPFPDevNET.dll;DPFPShrNET.dll;DPFPEngNET.dll;DPFPVerNET.dll;DPFPGuiNET.dll FingerprintService.cs
 */

using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Drawing;
using System.Windows.Forms;
using DPFP;
using DPFP.Capture;
using DPFP.Processing;

namespace FactuPOS.Fingerprint
{
    class FingerprintService : DPFP.Capture.EventHandler
    {
        const string VERSION = "1.0.0";
        const int PORT = 52181;
        const int CAPTURE_TIMEOUT_MS = 15000;
        const int ENROLL_TOUCH_TIMEOUT_MS = 30000;

        static string PrintsDir;
        static string BaseDir;

        HttpListener listener;
        DPFP.Capture.Capture capturer;
        bool deviceConnected = false;
        string readerSerial = "";

        // Sync capture
        ManualResetEvent captureEvent = new ManualResetEvent(false);
        DPFP.Sample lastSample = null;
        DPFP.Sample lastCompletedSample = null;
        long lastCompletedTicks = 0;
        DPFP.Capture.CaptureFeedback lastFeedback = CaptureFeedback.None;
        object captureLock = new object();
        bool capturing = false;

        // Templates en memoria: user_id -> {finger -> Template}
        Dictionary<string, Dictionary<string, DPFP.Template>> templates = new Dictionary<string, Dictionary<string, DPFP.Template>>();

        [STAThread]
        static void Main(string[] args)
        {
            BaseDir = AppDomain.CurrentDomain.BaseDirectory;
            PrintsDir = Path.Combine(BaseDir, "prints");

            if (!Directory.Exists(PrintsDir))
                Directory.CreateDirectory(PrintsDir);

            Console.WriteLine("============================================");
            Console.WriteLine(" FactuPOS Fingerprint Service v" + VERSION);
            Console.WriteLine(" Puerto: " + PORT);
            Console.WriteLine("============================================");

            try
            {
                var service = new FingerprintService();

                // Init DPFP
                service.InitCapture();
                service.LoadAllTemplates();

                // Init HTTP (no bloqueante con BeginGetContext)
                service.StartHttpListener();

                Console.WriteLine("[OK] Templates cargados: " + service.templates.Count + " usuarios");
                Console.WriteLine("Servicio corriendo. Cierre esta ventana para detener.\n");

                // Tray icon con ApplicationContext — message pump real sin necesidad de foco
                var ctx = new ApplicationContext();

                var trayIcon = new NotifyIcon();
                trayIcon.Text = "FactuPOS Fingerprint";
                trayIcon.Visible = true;

                // Crear icono programáticamente (cuadrado verde)
                var bmp = new Bitmap(16, 16);
                using (var g = Graphics.FromImage(bmp))
                {
                    g.Clear(Color.FromArgb(124, 58, 237)); // Morado biometría
                    g.FillEllipse(Brushes.White, 3, 3, 10, 10);
                }
                trayIcon.Icon = Icon.FromHandle(bmp.GetHicon());

                // Menú del tray
                var menu = new ContextMenuStrip();
                menu.Items.Add("FactuPOS Fingerprint v" + VERSION).Enabled = false;
                menu.Items.Add("-");
                menu.Items.Add("Salir", null, (s, e) => {
                    trayIcon.Visible = false;
                    ctx.ExitThread();
                    Environment.Exit(0);
                });
                trayIcon.ContextMenuStrip = menu;

                // Application.Run con context — pump real que funciona sin foco
                System.Windows.Forms.Application.Run(ctx);
            }
            catch (Exception ex)
            {
                Console.WriteLine("[ERROR FATAL] " + ex.Message);
                Console.WriteLine(ex.StackTrace);
                Console.WriteLine("\nPresione una tecla para salir...");
                Console.ReadKey();
            }
        }

        void StartHttpListener()
        {
            // Intentar HTTPS primero, fallback a HTTP
            bool httpsOk = false;
            try
            {
                listener = new HttpListener();
                listener.Prefixes.Add(string.Format("https://127.0.0.1:{0}/", PORT));
                listener.Prefixes.Add(string.Format("https://localhost:{0}/", PORT));
                listener.Start();
                Console.WriteLine("[OK] Servidor HTTPS escuchando en puerto " + PORT);
                httpsOk = true;
            }
            catch
            {
                try { if (listener != null) listener.Close(); } catch {}
                listener = null;
            }

            if (!httpsOk)
            {
                try
                {
                    listener = new HttpListener();
                    listener.Prefixes.Add(string.Format("http://127.0.0.1:{0}/", PORT));
                    listener.Prefixes.Add(string.Format("http://localhost:{0}/", PORT));
                    listener.Start();
                    Console.WriteLine("[OK] Servidor HTTP escuchando en puerto " + PORT);
                }
                catch (Exception ex)
                {
                    Console.WriteLine("[ERROR] No se pudo iniciar servidor: " + ex.Message);
                    return;
                }
            }

            // Async: no bloquea el thread — callback cuando llega request
            listener.BeginGetContext(OnHttpRequest, null);
        }

        void OnHttpRequest(IAsyncResult ar)
        {
            try
            {
                var context = listener.EndGetContext(ar);

                // Inmediatamente empezar a escuchar la siguiente request
                listener.BeginGetContext(OnHttpRequest, null);

                // Procesar esta request
                HandleRequest(context);
            }
            catch (Exception ex)
            {
                Console.WriteLine("[ERROR] HTTP: " + ex.Message);
                // Seguir escuchando
                try { listener.BeginGetContext(OnHttpRequest, null); } catch {}
            }
        }

        #region HTTP Router

        void HandleRequest(HttpListenerContext ctx)
        {
            var req = ctx.Request;
            var res = ctx.Response;

            // CORS
            res.Headers.Add("Access-Control-Allow-Origin", "*");
            res.Headers.Add("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
            res.Headers.Add("Access-Control-Allow-Headers", "Content-Type");

            if (req.HttpMethod == "OPTIONS")
            {
                SendJson(res, 200, "{\"ok\":true}");
                return;
            }

            string path = req.Url.AbsolutePath.TrimEnd('/');
            string method = req.HttpMethod;

            try
            {
                if (path == "/status" && method == "GET")
                    HandleStatus(res);
                else if (path == "/get_connection" && method == "GET")
                    HandleGetConnection(res);
                else if (path == "/prints" && method == "GET")
                    HandleListPrints(res);
                else if (path == "/fingerprint/identify" && method == "POST")
                    HandleIdentify(req, res);
                else if (path == "/fingerprint/enroll" && method == "POST")
                    HandleEnroll(req, res);
                else if (path.StartsWith("/prints/") && method == "DELETE")
                    HandleDeletePrints(path, res);
                else
                    SendJson(res, 404, "{\"ok\":false,\"error\":\"Not found\"}");
            }
            catch (Exception ex)
            {
                Console.WriteLine("[ERROR] " + path + ": " + ex.Message);
                try { SendJson(res, 500, string.Format("{{\"ok\":false,\"error\":\"{0}\"}}", EscapeJson(ex.Message))); } catch {}
            }
        }

        #endregion

        #region Endpoints

        void HandleStatus(HttpListenerResponse res)
        {
            int totalPrints = 0;
            foreach (var u in templates)
                totalPrints += u.Value.Count;

            string json = string.Format(
                "{{\"ok\":true,\"connected\":{0},\"version\":\"{1}\",\"platform\":\"windows\",\"reader_serial\":\"{2}\",\"users_enrolled\":{3},\"total_prints\":{4},\"device_ready\":{5}}}",
                B(deviceConnected), VERSION, EscapeJson(readerSerial), templates.Count, totalPrints, B(deviceConnected && !capturing)
            );
            SendJson(res, 200, json);
        }

        void HandleGetConnection(HttpListenerResponse res)
        {
            string json = string.Format(
                "{{\"ok\":true,\"connected\":{0},\"reader_serial\":\"{1}\",\"enroll_stages\":4,\"matching_type\":\"minutiae\"}}",
                B(deviceConnected), EscapeJson(readerSerial)
            );
            SendJson(res, 200, json);
        }

        void HandleListPrints(HttpListenerResponse res)
        {
            var sb = new StringBuilder();
            sb.Append("{\"ok\":true,\"users\":{");
            bool first = true;
            foreach (var kv in templates)
            {
                if (!first) sb.Append(",");
                sb.AppendFormat("\"{0}\":{1}", EscapeJson(kv.Key), kv.Value.Count);
                first = false;
            }
            sb.Append("}}");
            SendJson(res, 200, sb.ToString());
        }

        void HandleIdentify(HttpListenerRequest req, HttpListenerResponse res)
        {
            if (!deviceConnected)
            {
                SendJson(res, 503, "{\"ok\":false,\"error\":\"Lector no conectado\"}");
                return;
            }

            if (templates.Count == 0)
            {
                SendJson(res, 200, "{\"ok\":true,\"matched\":false,\"error\":\"No hay huellas registradas\",\"users_enrolled\":0}");
                return;
            }

            // NO BLOQUEANTE: chequear si hay una muestra reciente (< 10 segundos)
            DPFP.Sample sample = null;
            long ageTicks = DateTime.UtcNow.Ticks - lastCompletedTicks;
            long maxAge = 10 * TimeSpan.TicksPerSecond;
            double ageMs = ageTicks / (double)TimeSpan.TicksPerMillisecond;

            if (lastCompletedSample != null && ageTicks < maxAge)
            {
                sample = lastCompletedSample;
                lastCompletedSample = null; // Consumir la muestra
                Console.WriteLine("[IDENTIFY] Usando muestra reciente (age: " + (int)ageMs + "ms)");
            }
            else
            {
                // No hay muestra — retornar "waiting" para que el popup haga polling
                Console.WriteLine("[IDENTIFY] Esperando dedo... (sample=" + (lastCompletedSample != null ? "si" : "no") + " age=" + (int)ageMs + "ms)");
                SendJson(res, 200, "{\"ok\":true,\"matched\":false,\"waiting\":true}");
                return;
            }

            // Extraer features para verificacion
            DPFP.FeatureSet features = ExtractFeatures(sample, DataPurpose.Verification);
            if (features == null)
            {
                SendJson(res, 200, "{\"ok\":true,\"matched\":false,\"error\":\"Calidad de muestra insuficiente\"}");
                return;
            }

            // Verificar contra todos los templates
            var verificator = new DPFP.Verification.Verification();
            foreach (var userKv in templates)
            {
                foreach (var fingerKv in userKv.Value)
                {
                    var result = new DPFP.Verification.Verification.Result();
                    verificator.Verify(features, fingerKv.Value, ref result);
                    if (result.Verified)
                    {
                        Console.WriteLine("[IDENTIFY] Match: usuario=" + userKv.Key + " dedo=" + fingerKv.Key);
                        string json = string.Format(
                            "{{\"ok\":true,\"matched\":true,\"user_id\":\"{0}\",\"finger\":\"{1}\",\"far\":{2}}}",
                            EscapeJson(userKv.Key), EscapeJson(fingerKv.Key), result.FARAchieved
                        );
                        SendJson(res, 200, json);
                        return;
                    }
                }
            }

            Console.WriteLine("[IDENTIFY] No match");
            SendJson(res, 200, "{\"ok\":true,\"matched\":false}");
        }

        void HandleEnroll(HttpListenerRequest req, HttpListenerResponse res)
        {
            if (!deviceConnected)
            {
                SendJson(res, 503, "{\"ok\":false,\"error\":\"Lector no conectado\"}");
                return;
            }

            // Leer body JSON
            string body = ReadBody(req);
            string userId = GetJsonValue(body, "user_id");
            string finger = GetJsonValue(body, "finger");

            if (string.IsNullOrEmpty(userId))
            {
                SendJson(res, 400, "{\"ok\":false,\"error\":\"user_id requerido\"}");
                return;
            }
            if (string.IsNullOrEmpty(finger))
                finger = "right_index";

            Console.WriteLine("[ENROLL] Iniciando para usuario=" + userId + " dedo=" + finger);

            var enroller = new DPFP.Processing.Enrollment();
            int touchCount = 0;
            int totalNeeded = 4; // DigitalPersona necesita 4 muestras

            while (enroller.FeaturesNeeded > 0)
            {
                DPFP.Sample sample = CaptureSample(ENROLL_TOUCH_TIMEOUT_MS);
                if (sample == null)
                {
                    SendJson(res, 408, string.Format(
                        "{{\"ok\":false,\"error\":\"Timeout esperando toque {0}/{1}\"}}", touchCount + 1, totalNeeded
                    ));
                    return;
                }

                DPFP.FeatureSet features = ExtractFeatures(sample, DataPurpose.Enrollment);
                if (features == null)
                {
                    Console.WriteLine("[ENROLL] Muestra de mala calidad, repetir toque " + (touchCount + 1));
                    continue;
                }

                try
                {
                    enroller.AddFeatures(features);
                    touchCount++;
                    Console.WriteLine("[ENROLL] Toque " + touchCount + "/" + totalNeeded + " OK (faltan: " + enroller.FeaturesNeeded + ")");
                }
                catch (Exception ex)
                {
                    Console.WriteLine("[ENROLL] Error AddFeatures: " + ex.Message);
                }

                if (enroller.TemplateStatus == DPFP.Processing.Enrollment.Status.Failed)
                {
                    SendJson(res, 200, "{\"ok\":false,\"error\":\"Enrollment fallido, intente de nuevo\"}");
                    return;
                }
            }

            if (enroller.TemplateStatus == DPFP.Processing.Enrollment.Status.Ready)
            {
                // Guardar template
                SaveTemplate(userId, finger, enroller.Template);
                LoadUserTemplates(userId);

                Console.WriteLine("[ENROLL] Completado para " + userId + "/" + finger);
                SendJson(res, 200, string.Format(
                    "{{\"ok\":true,\"enrolled\":true,\"user_id\":\"{0}\",\"finger\":\"{1}\",\"touches\":{2}}}",
                    EscapeJson(userId), EscapeJson(finger), touchCount
                ));
            }
            else
            {
                SendJson(res, 200, "{\"ok\":false,\"error\":\"Enrollment no completado\"}");
            }
        }

        void HandleDeletePrints(string path, HttpListenerResponse res)
        {
            // /prints/{user_id}
            string userId = path.Substring("/prints/".Length);
            if (string.IsNullOrEmpty(userId))
            {
                SendJson(res, 400, "{\"ok\":false,\"error\":\"user_id requerido\"}");
                return;
            }

            string userDir = Path.Combine(PrintsDir, userId);
            if (Directory.Exists(userDir))
            {
                Directory.Delete(userDir, true);
            }

            if (templates.ContainsKey(userId))
                templates.Remove(userId);

            Console.WriteLine("[DELETE] Prints eliminados: " + userId);
            SendJson(res, 200, "{\"ok\":true,\"deleted\":true}");
        }

        #endregion

        #region DPFP Capture

        void InitCapture()
        {
            try
            {
                capturer = new DPFP.Capture.Capture();
                if (capturer != null)
                {
                    capturer.EventHandler = this;
                    capturer.StartCapture();
                    Console.WriteLine("[OK] Captura inicializada y escuchando lector");
                }
                else
                {
                    Console.WriteLine("[WARN] No se pudo crear objeto Capture");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("[ERROR] InitCapture: " + ex.Message);
            }
        }

        DPFP.Sample CaptureSample(int timeoutMs)
        {
            lock (captureLock)
            {
                capturing = true;
                lastSample = null;
                captureEvent.Reset();

                // Esperar en intervalos cortos para no bloquear el message pump
                int waited = 0;
                int interval = 200;
                while (waited < timeoutMs)
                {
                    if (captureEvent.WaitOne(interval))
                    {
                        capturing = false;
                        if (lastSample != null)
                            return lastSample;
                        return null;
                    }
                    waited += interval;
                }

                capturing = false;
                return null;
            }
        }

        DPFP.FeatureSet ExtractFeatures(DPFP.Sample sample, DataPurpose purpose)
        {
            var extractor = new DPFP.Processing.FeatureExtraction();
            CaptureFeedback feedback = CaptureFeedback.None;
            DPFP.FeatureSet features = new DPFP.FeatureSet();
            extractor.CreateFeatureSet(sample, purpose, ref feedback, ref features);
            if (feedback == CaptureFeedback.Good)
                return features;
            return null;
        }

        // DPFP.Capture.EventHandler
        public void OnComplete(object Capture, string ReaderSerialNumber, DPFP.Sample Sample)
        {
            Console.WriteLine("[CAPTURE] OnComplete - muestra recibida");
            lastSample = Sample;
            lastCompletedSample = Sample;
            lastCompletedTicks = DateTime.UtcNow.Ticks;
            captureEvent.Set();

            // Reiniciar captura para la siguiente lectura
            try { capturer.StartCapture(); } catch {}
        }

        public void OnFingerGone(object Capture, string ReaderSerialNumber) { }

        public void OnFingerTouch(object Capture, string ReaderSerialNumber)
        {
            Console.WriteLine("[TOUCH] Dedo detectado");
        }

        public void OnReaderConnect(object Capture, string ReaderSerialNumber)
        {
            deviceConnected = true;
            readerSerial = ReaderSerialNumber ?? "";
            Console.WriteLine("[READER] Conectado: " + readerSerial);
        }

        public void OnReaderDisconnect(object Capture, string ReaderSerialNumber)
        {
            deviceConnected = false;
            Console.WriteLine("[READER] Desconectado");
        }

        public void OnSampleQuality(object Capture, string ReaderSerialNumber, CaptureFeedback CaptureFeedback)
        {
            lastFeedback = CaptureFeedback;
            if (CaptureFeedback != CaptureFeedback.Good)
                Console.WriteLine("[QUALITY] Muestra de mala calidad");
        }

        #endregion

        #region Template Storage

        void LoadAllTemplates()
        {
            templates.Clear();
            if (!Directory.Exists(PrintsDir)) return;

            foreach (string userDir in Directory.GetDirectories(PrintsDir))
            {
                string userId = Path.GetFileName(userDir);
                LoadUserTemplates(userId);
            }
        }

        void LoadUserTemplates(string userId)
        {
            string userDir = Path.Combine(PrintsDir, userId);
            if (!Directory.Exists(userDir)) return;

            var userTemplates = new Dictionary<string, DPFP.Template>();

            foreach (string file in Directory.GetFiles(userDir, "*.fpt"))
            {
                try
                {
                    byte[] data = File.ReadAllBytes(file);
                    DPFP.Template template;
                    using (var ms = new MemoryStream(data))
                    {
                        template = new DPFP.Template(ms);
                    }
                    string finger = Path.GetFileNameWithoutExtension(file);
                    userTemplates[finger] = template;
                }
                catch (Exception ex)
                {
                    Console.WriteLine("[WARN] Error cargando template " + file + ": " + ex.Message);
                }
            }

            if (userTemplates.Count > 0)
                templates[userId] = userTemplates;
            else if (templates.ContainsKey(userId))
                templates.Remove(userId);
        }

        void SaveTemplate(string userId, string finger, DPFP.Template template)
        {
            string userDir = Path.Combine(PrintsDir, userId);
            if (!Directory.Exists(userDir))
                Directory.CreateDirectory(userDir);

            string filePath = Path.Combine(userDir, finger + ".fpt");
            byte[] data = null;
            template.Serialize(ref data);
            File.WriteAllBytes(filePath, data);

            Console.WriteLine("[SAVE] Template guardado: " + filePath);
        }

        #endregion

        #region Helpers

        void SendJson(HttpListenerResponse res, int statusCode, string json)
        {
            try
            {
                res.StatusCode = statusCode;
                res.ContentType = "application/json; charset=utf-8";
                byte[] buf = Encoding.UTF8.GetBytes(json);
                res.ContentLength64 = buf.Length;
                res.OutputStream.Write(buf, 0, buf.Length);
                res.OutputStream.Close();
            }
            catch (Exception ex)
            {
                Console.WriteLine("[WARN] SendJson: " + ex.Message);
            }
        }

        string ReadBody(HttpListenerRequest req)
        {
            using (var reader = new StreamReader(req.InputStream, req.ContentEncoding))
            {
                return reader.ReadToEnd();
            }
        }

        // Mini JSON parser (sin dependencias externas)
        string GetJsonValue(string json, string key)
        {
            string search = "\"" + key + "\"";
            int idx = json.IndexOf(search);
            if (idx < 0) return null;

            idx = json.IndexOf(':', idx + search.Length);
            if (idx < 0) return null;
            idx++;

            // Skip whitespace
            while (idx < json.Length && (json[idx] == ' ' || json[idx] == '\t')) idx++;

            if (idx >= json.Length) return null;

            if (json[idx] == '"')
            {
                // String value
                int start = idx + 1;
                int end = json.IndexOf('"', start);
                if (end < 0) return null;
                return json.Substring(start, end - start);
            }
            else
            {
                // Number or other
                int start = idx;
                while (idx < json.Length && json[idx] != ',' && json[idx] != '}' && json[idx] != ' ')
                    idx++;
                return json.Substring(start, idx - start);
            }
        }

        string EscapeJson(string s)
        {
            if (s == null) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r");
        }

        string B(bool v) { return v ? "true" : "false"; }

        #endregion
    }
}
