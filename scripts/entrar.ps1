. "$PSScriptRoot\comun.ps1"
az login --only-show-errors -o table
az account show --query "{Suscripcion:name, Usuario:user.name}" -o table
