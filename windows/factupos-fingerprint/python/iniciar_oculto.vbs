' ============================================================
'  FactuPOS Biometria - arranque OCULTO (sin ventana negra)
' ============================================================
'  Arranca el servicio de huella en segundo plano (sin consola).
'  El servicio a su vez: limpia lo que acapara el lector, lanza
'  el kiosko (ventana normal en la barra de tareas) y queda corriendo.
'
'  Usado por el "Auto-inicio" del kiosko y por iniciar_autoinicio.
'  Para verlo con log usá iniciar_servicio.bat (ventana visible).
' ============================================================
Option Explicit
Dim sh, fso, here, svcExe, svcPy, pyw, cand, cmd
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here

svcExe = here & "\FactuposFpServicio.exe"
svcPy  = here & "\fingerprint_service.py"

If fso.FileExists(svcExe) Then
    cmd = """" & svcExe & """"
ElseIf fso.FileExists(svcPy) Then
    ' buscar pythonw
    pyw = ""
    cand = Array("pythonw.exe", "C:\Python38\pythonw.exe", "C:\Python38-32\pythonw.exe", _
                 sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python38\pythonw.exe", _
                 sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python38-32\pythonw.exe")
    Dim i
    For i = 0 To UBound(cand)
        If pyw = "" Then
            If i = 0 Then
                ' "pythonw.exe" a secas: confiar en el PATH
                pyw = cand(i)
            ElseIf fso.FileExists(cand(i)) Then
                pyw = cand(i)
            End If
        End If
    Next
    cmd = """" & pyw & """ """ & svcPy & """"
Else
    MsgBox "No se encontro FactuposFpServicio.exe ni fingerprint_service.py en:" & vbCrLf & here, 48, "FactuPOS Biometria"
    WScript.Quit 1
End If

' 0 = ventana oculta ; False = no esperar.
' El servicio mismo hace single-instance check por puerto 52181 — si ya hay uno corriendo, sale solo.
sh.Run cmd, 0, False
