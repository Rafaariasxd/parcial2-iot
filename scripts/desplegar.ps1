param([switch]$ConDispositivos)
. "$PSScriptRoot\comun.ps1"
$n = Nube
if (-not $n) { throw 'Primero corre scripts\crear_vm.ps1' }

$ErrorActionPreference = 'Continue'
for ($i = 0; $i -lt 40; $i++) {
    ssh.exe -i $Llave -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$Usuario@$($n.dominio)" 'docker compose version' 2>$null
    if ($LASTEXITCODE -eq 0) { break }
    Write-Host 'Esperando a que la VM termine de instalar Docker...'
    Start-Sleep 15
}
$ErrorActionPreference = 'Stop'

$temporal = 'D:\Temp\galpon-despliegue'
New-Item -ItemType Directory -Force $temporal | Out-Null
$paquete = Join-Path $temporal 'galpon.tgz'
$lista = Join-Path $temporal 'archivos.txt'
Push-Location $Raiz
git ls-files --cached --others --exclude-standard | Set-Content $lista -Encoding ascii
Ejecutar tar @('-czf', $paquete, '-T', $lista)
Pop-Location

$azure = (Get-Content (Join-Path $Secretos 'azure_maps.txt') -Raw).Trim()
$entorno = Join-Path $temporal '.env'
@(
    "DOMINIO=$($n.dominio)"
    "BD_CLAVE=$($n.bd_clave)"
    "MQTT_CLAVE_PLATAFORMA=$($n.mqtt_clave_plataforma)"
    "MQTT_CLAVE_DISPOSITIVOS=$($n.mqtt_clave_dispositivos)"
    "PANEL_CLAVE=$($n.panel_clave)"
    "DISPOSITIVOS_CLAVE=$($n.dispositivos_clave)"
    "GRAFANA_CLAVE=$($n.grafana_clave)"
    "AZURE_MAPS_CLAVE=$azure"
) -join "`n" | Set-Content $entorno -NoNewline -Encoding ascii

$destino = "$Usuario@$($n.dominio)"
Ejecutar scp.exe @('-i', $Llave, $paquete, $entorno, "${destino}:~/")
Remoto 'rm -rf ~/galpon.nuevo && mkdir -p ~/galpon.nuevo && tar -xzf ~/galpon.tgz -C ~/galpon.nuevo && mkdir -p ~/galpon && cp -r ~/galpon.nuevo/. ~/galpon/ && mv ~/.env ~/galpon/nube/.env && chmod 600 ~/galpon/nube/.env && rm -rf ~/galpon.nuevo ~/galpon.tgz'

$servicios = 'bd mosquitto plataforma grafana caddy'
if ($ConDispositivos) { $servicios += ' dispositivos' }
Remoto "cd ~/galpon/nube && docker compose up -d --build $servicios"
Remove-Item $entorno

Write-Host "Panel: https://$($n.dominio)" -ForegroundColor Green
Write-Host "Grafana: https://$($n.dominio)/grafana" -ForegroundColor Green
Guardar '02-despliegue' { Remoto 'cd ~/galpon/nube && docker compose ps --format "table {{.Service}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"' }
