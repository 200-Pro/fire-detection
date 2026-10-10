param([switch]$NoBrowser, [string]$LanAddress = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$nodePath = (Get-Command node.exe).Source
$vitePath = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$runRoot = Join-Path $projectRoot 'runtime'
$caddyPath = Join-Path $runRoot 'tools\caddy\caddy.exe'
function Test-Port([string]$Address, [int]$Port) {
    try { $socket = [System.Net.Sockets.TcpClient]::new($Address, $Port); $socket.Dispose(); return $true } catch { return $false }
}
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath $vitePath)) { throw 'Run scripts\setup-local.ps1 first.' }
if ((Test-Port '127.0.0.1' 8000) -or (Test-Port '127.0.0.1' 5173)) { throw 'Port 8000 or 5173 is already used. Stop the previous instance first.' }
if ($LanAddress) {
    $ip = $null
    if (-not [System.Net.IPAddress]::TryParse($LanAddress, [ref]$ip) -or $ip.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw 'Use a private IPv4 LAN address.' }
    $octets = $ip.GetAddressBytes()
    if (-not ($octets[0] -eq 10 -or ($octets[0] -eq 192 -and $octets[1] -eq 168) -or ($octets[0] -eq 172 -and $octets[1] -ge 16 -and $octets[1] -le 31))) { throw 'Only RFC1918 private addresses are supported. Public exposure is not allowed.' }
    if (-not (Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -eq $LanAddress)) { throw 'The LAN address is not assigned to this PC.' }
    if (Test-Port $LanAddress 8443) { throw 'LAN port 8443 is already used.' }
    if (-not (Test-Path -LiteralPath $caddyPath) -or -not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) { throw 'Prepare verified Caddy and run npm.cmd run build first.' }
}
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null
$records = [System.Collections.Generic.List[object]]::new()
function Start-Tracked([string]$Role, [string]$Executable, [string]$Arguments, [string]$Directory) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot "$Role.stdout.log") -RedirectStandardError (Join-Path $runRoot "$Role.stderr.log")
    $records.Add(@{role=$Role; id=$process.Id; created=$process.StartTime.ToUniversalTime().ToString('o'); executable=$Executable})
    @{version=2; processes=$records.ToArray()} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runRoot 'processes.json') -Encoding utf8
}
$previousOrigin = $env:EMBER_PUBLIC_ORIGIN
$previousHost = $env:EMBER_HOST
$previousCaddy = $env:EMBER_CADDY_DATA
$previousWeb = $env:EMBER_WEB_ROOT
try {
    Push-Location (Join-Path $projectRoot 'backend')
    try { & $pythonPath -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Database migration failed; server not started.' } } finally { Pop-Location }
    if ($LanAddress) { $env:EMBER_PUBLIC_ORIGIN = "https://${LanAddress}:8443" }
    Start-Tracked 'backend' $pythonPath '-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log' (Join-Path $projectRoot 'backend')
    Start-Tracked 'frontend' $nodePath ('"{0}" --host 127.0.0.1 --port 5173 --strictPort' -f $vitePath) (Join-Path $projectRoot 'frontend')
    if ($LanAddress) {
        $env:EMBER_HOST = $LanAddress
        $env:EMBER_CADDY_DATA = (Join-Path $runRoot 'caddy').Replace('\','/')
        $env:EMBER_WEB_ROOT = (Join-Path $projectRoot 'frontend\dist').Replace('\','/')
        $configPath = Join-Path $projectRoot 'infra\Caddyfile.example'
        & $caddyPath validate --config $configPath --adapter caddyfile
        if ($LASTEXITCODE -ne 0) { throw 'Caddy configuration validation failed.' }
        Start-Tracked 'caddy' $caddyPath ('run --config "{0}" --adapter caddyfile' -f $configPath) $projectRoot
    }
    $deadline = (Get-Date).AddSeconds(30)
    $ready = $false
    do {
        try { $ready = (Invoke-RestMethod 'http://127.0.0.1:8000/health/ready' -TimeoutSec 2).ready } catch {}
        if ($ready -and (Test-Port '127.0.0.1' 5173)) { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    if (-not $ready -or -not (Test-Port '127.0.0.1' 5173)) { throw 'Backend model or frontend not ready. Inspect runtime logs.' }
    Write-Output 'PC console: http://localhost:5173'
    if ($LanAddress) {
        & $pythonPath (Join-Path $PSScriptRoot 'export-lan-certificate.py') --address $LanAddress
        if ($LASTEXITCODE -ne 0) { throw 'Certificate export or verified HTTPS check failed.' }
        Write-Output "Phone camera: https://${LanAddress}:8443/camera"
        Write-Output 'OS certificate trust and firewall settings were not changed. See docs\PHONE_TEST.md.'
    }
    if (-not $NoBrowser) { Start-Process 'http://localhost:5173' }
} catch {
    & (Join-Path $PSScriptRoot 'stop-local.ps1')
    throw
} finally {
    $env:EMBER_PUBLIC_ORIGIN = $previousOrigin
    $env:EMBER_HOST = $previousHost
    $env:EMBER_CADDY_DATA = $previousCaddy
    $env:EMBER_WEB_ROOT = $previousWeb
}
