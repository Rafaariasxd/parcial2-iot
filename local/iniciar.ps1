$Raiz = Split-Path $PSScriptRoot -Parent
$Py = Join-Path $Raiz '.venv\Scripts\python.exe'
$Reg = Join-Path $PSScriptRoot 'registros'
New-Item -ItemType Directory -Force $Reg | Out-Null
$clave = Join-Path $Raiz '.secretos\azure_maps.txt'
if (Test-Path $clave) { $env:AZURE_MAPS_CLAVE = (Get-Content $clave -Raw).Trim() }
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $PSScriptRoot 'granja_iot.db').Replace('\', '/')
$env:CARPETA_ESTADO = Join-Path $Raiz 'estado'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:MQTT_HOST = '127.0.0.1'
$env:API_URL = 'http://127.0.0.1:8000'

function Lanzar($nombre, $argumentos, $carpeta) {
    $p = Start-Process -FilePath $Py -ArgumentList $argumentos -WorkingDirectory $carpeta -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Reg "$nombre.out.log") -RedirectStandardError (Join-Path $Reg "$nombre.log") -PassThru
    Set-Content -Path (Join-Path $Reg "$nombre.pid") -Value $p.Id
    "$nombre -> PID $($p.Id)"
}

Lanzar 'broker' @('local\broker.py') $Raiz
Start-Sleep 3
Lanzar 'plataforma' @('-m', 'uvicorn', 'granja_iot.api:app', '--host', '0.0.0.0', '--log-level', 'warning', '--port', '8000') (Join-Path $Raiz 'plataforma')
Start-Sleep 4
Lanzar 'dispositivos' @('-m', 'granja_dispositivos.principal') (Join-Path $Raiz 'dispositivos')
