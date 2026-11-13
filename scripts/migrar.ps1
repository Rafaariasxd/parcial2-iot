. "$PSScriptRoot\comun.ps1"
$n = Nube
$destino = "$Usuario@$($n.dominio)"
$python = Join-Path $Raiz '.venv\Scripts\python.exe'

$tunel = Start-Process ssh.exe -ArgumentList @('-i', $Llave, '-N', '-L', '15432:127.0.0.1:5432', $destino) -PassThru -WindowStyle Hidden
Start-Sleep 5
try {
    & (Join-Path $Raiz 'local\detener.ps1')
    Ejecutar $python @((Join-Path $PSScriptRoot 'migrar_datos.py'), (Join-Path $Raiz 'local\granja_iot.db'),
        "postgresql://granja:$($n.bd_clave)@127.0.0.1:15432/granja")
} finally {
    Stop-Process -Id $tunel.Id -ErrorAction SilentlyContinue
}

Ejecutar scp.exe @('-i', $Llave, '-r', (Join-Path $Raiz 'estado'), "${destino}:~/estado-local")
Remoto 'cd ~/galpon/nube && docker compose create dispositivos && docker compose cp ~/estado-local/. dispositivos:/app/estado/ && docker compose up -d dispositivos && docker compose restart plataforma'
Write-Host 'Datos locales copiados a la nube y dispositivos corriendo allá' -ForegroundColor Green
