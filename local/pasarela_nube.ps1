. (Join-Path (Split-Path $PSScriptRoot -Parent) 'scripts\comun.ps1')
$n = Nube
$Reg = Join-Path $PSScriptRoot 'registros'
New-Item -ItemType Directory -Force $Reg | Out-Null
$env:MQTT_HOST = $n.dominio
$env:MQTT_USUARIO = 'dispositivos'
$env:MQTT_CLAVE = $n.mqtt_clave_dispositivos
$env:SOLO = 'pasarela-finca'
$env:CARPETA_ESTADO = Join-Path $Raiz 'estado'
$env:PYTHONUTF8 = '1'
$py = Join-Path $Raiz '.venv\Scripts\python.exe'
$p = Start-Process -FilePath $py -ArgumentList @('-m', 'granja_dispositivos.principal') -WorkingDirectory (Join-Path $Raiz 'dispositivos') `
    -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Reg 'pasarela.out.log') -RedirectStandardError (Join-Path $Reg 'pasarela.log') -PassThru
Set-Content (Join-Path $Reg 'pasarela.pid') $p.Id
"Pasarela de la finca enviando a $($n.dominio) (PID $($p.Id))"
