$installDir = "C:\FactuPOS\FingerprintService"
$port = 52181
$appId = "{a1b2c3d4-e5f6-7890-abcd-ef1234567890}"

# Borrar cert anterior si existe
netsh http delete sslcert ipport=0.0.0.0:$port 2>$null | Out-Null

# Buscar cert existente
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.FriendlyName -eq "FactuPOS Fingerprint" } | Select-Object -First 1

if (-not $cert) {
    Write-Host "Generando certificado autofirmado..."
    $cert = New-SelfSignedCertificate -DnsName "localhost","127.0.0.1" -CertStoreLocation "Cert:\LocalMachine\My" -NotAfter (Get-Date).AddYears(10) -FriendlyName "FactuPOS Fingerprint"
    Write-Host "Certificado generado: $($cert.Thumbprint)"
} else {
    Write-Host "Certificado existente: $($cert.Thumbprint)"
}

$thumbprint = $cert.Thumbprint

# Vincular cert al puerto
netsh http add sslcert ipport=0.0.0.0:$port certhash=$thumbprint appid=$appId
Write-Host "SSL vinculado al puerto $port"

# Reservar URLs
netsh http delete urlacl url=https://127.0.0.1:$port/ 2>$null | Out-Null
netsh http delete urlacl url=https://localhost:$port/ 2>$null | Out-Null
netsh http add urlacl url=https://127.0.0.1:$port/ user=Everyone
netsh http add urlacl url=https://localhost:$port/ user=Everyone
Write-Host "URLs reservadas"
