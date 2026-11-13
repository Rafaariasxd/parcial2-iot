$Reg = Join-Path $PSScriptRoot 'registros'
foreach ($n in 'pasarela', 'dispositivos', 'plataforma', 'broker') {
    $f = Join-Path $Reg "$n.pid"
    if (Test-Path $f) {
        $id = [int](Get-Content $f)
        taskkill /T /F /PID $id 2>$null | Out-Null; "$n detenido"
        Remove-Item $f
    }
}
