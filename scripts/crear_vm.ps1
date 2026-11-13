param([string]$Region = 'eastus2', [string]$Tamano = 'Standard_B2s')
. "$PSScriptRoot\comun.ps1"

$etiqueta = 'galpon-conectado-' + (Nueva-Clave 5).ToLower()
Ejecutar az @('group', 'create', '-n', $Grupo, '-l', $Region, '-o', 'none')
Ejecutar az @('vm', 'create', '-g', $Grupo, '-n', $Vm, '--image', 'Ubuntu2404', '--size', $Tamano,
    '--admin-username', $Usuario, '--ssh-key-values', "$Llave.pub", '--public-ip-sku', 'Standard',
    '--public-ip-address-dns-name', $etiqueta, '--os-disk-size-gb', '64', '--storage-sku', 'StandardSSD_LRS',
    '--custom-data', (Join-Path $PSScriptRoot 'nube-init.yml'), '-o', 'none')
Ejecutar az @('vm', 'open-port', '-g', $Grupo, '-n', $Vm, '--port', '80,443,1883', '--priority', '900', '-o', 'none')

$ip = az vm show -d -g $Grupo -n $Vm --query publicIps -o tsv
$dominio = az network public-ip list -g $Grupo --query '[0].dnsSettings.fqdn' -o tsv
[ordered]@{
    dominio = $dominio
    ip = $ip
    region = $Region
    creada = (Get-Date -Format 'yyyy-MM-dd HH:mm')
    bd_clave = Nueva-Clave
    mqtt_clave_plataforma = Nueva-Clave
    mqtt_clave_dispositivos = Nueva-Clave
    panel_clave = Nueva-Clave 12
    dispositivos_clave = Nueva-Clave
    grafana_clave = Nueva-Clave 16
} | ConvertTo-Json | Set-Content (Join-Path $Secretos 'nube.json') -Encoding UTF8

Write-Host "VM lista: https://$dominio ($ip)" -ForegroundColor Green
Guardar '01-vm' {
    az vm show -d -g $Grupo -n $Vm --query '{Nombre:name, Tamano:hardwareProfile.vmSize, Region:location, IP:publicIps, Dominio:fqdns, Estado:powerState}' -o table
    az network nsg rule list -g $Grupo --nsg-name "${Vm}NSG" --query '[].{Regla:name, Puertos:destinationPortRange, Prioridad:priority}' -o table
}
