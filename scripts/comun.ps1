$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Raiz = Split-Path $PSScriptRoot -Parent
$Secretos = Join-Path $Raiz '.secretos'
$Evidencias = Join-Path $Raiz 'evidencias'
New-Item -ItemType Directory -Force -Path $Secretos, $Evidencias | Out-Null

if (Test-Path 'D:\Herramientas\azcli\Scripts\az.bat') {
    $env:PATH = 'D:\Herramientas\azcli\Scripts;' + $env:PATH
    $env:AZURE_CONFIG_DIR = 'D:\Herramientas\azure-config'
}

$Grupo = 'rg-parcial2-iot'
$Vm = 'vm-galpon'
$Usuario = 'galpon'
$Llave = Join-Path $HOME '.ssh\id_ed25519_iotvm'

function Ejecutar([string]$Programa, [string[]]$Argumentos) {
    & $Programa @Argumentos
    if ($LASTEXITCODE -ne 0) { throw "Falló: $Programa $($Argumentos -join ' ')" }
}

function Nueva-Clave([int]$Largo = 24) {
    $letras = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    $bytes = New-Object byte[] $Largo
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $letras[$_ % $letras.Length] })
}

function Nube {
    $archivo = Join-Path $Secretos 'nube.json'
    if (Test-Path $archivo) { return Get-Content $archivo -Raw | ConvertFrom-Json }
    return $null
}

function Remoto([string]$Comando) {
    $n = Nube
    Ejecutar 'ssh.exe' @('-i', $Llave, '-o', 'StrictHostKeyChecking=accept-new', "$Usuario@$($n.dominio)", $Comando)
}

function Guardar([string]$Nombre, [scriptblock]$Comandos) {
    $archivo = Join-Path $Evidencias "$Nombre.txt"
    $salida = @("# $Nombre - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')", '') + (& $Comandos 2>&1 | Out-String -Width 200)
    $salida | Set-Content -Path $archivo -Encoding UTF8
    Write-Host ($salida -join "`n")
}
