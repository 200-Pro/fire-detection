$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $projectRoot 'runtime\processes.json'
if (-not (Test-Path -LiteralPath $pidPath)) { throw 'No tracked launcher processes. Stop your foreground terminal with Ctrl+C instead.' }
$tracked = Get-Content -LiteralPath $pidPath -Raw | ConvertFrom-Json
if ($tracked.version -ne 2) { throw 'Old process metadata cannot be safely stopped by this launcher.' }
$all = @(Get-CimInstance Win32_Process)
foreach ($record in @($tracked.processes | Sort-Object @{Expression={switch ($_.role) {'caddy'{0} 'frontend'{1} 'backend'{2} default{3}}}})) {
    $role = $record.role
    $rootId = [int]$record.id
    $root = $all | Where-Object ProcessId -eq $rootId
    if (-not $root) { continue }
    # PowerShell 7.5 may deserialize ISO dates into DateTime automatically.
    # Re-parsing its localized string would drop the UTC suffix and shift 9h.
    $launched = if ($record.created -is [DateTime]) { $record.created.ToUniversalTime() } else { [DateTimeOffset]::Parse($record.created).UtcDateTime }
    if ([Math]::Abs(($root.CreationDate.ToUniversalTime() - $launched).TotalSeconds) -gt 2 -or $root.ExecutablePath -ne $record.executable) { throw "PID $rootId no longer matches this launch. Refusing to stop it." }
    $expected = switch ($role) { 'backend' {'app\.main:app'} 'frontend' {[regex]::Escape((Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'))} 'caddy' {[regex]::Escape((Join-Path $projectRoot 'infra\Caddyfile.example'))} default {throw 'Unknown process role.'} }
    if ($root.CommandLine -notmatch $expected) { throw 'Unexpected command line. Refusing to stop it.' }
    $ids = [System.Collections.Generic.List[int]]::new()
    $ids.Add($rootId)
    for ($depth = 0; $depth -lt 10; $depth++) {
        $children = @($all | Where-Object { $ids.Contains([int]$_.ParentProcessId) -and -not $ids.Contains([int]$_.ProcessId) -and $_.CreationDate -ge $root.CreationDate })
        if (-not $children.Count) { break }
        foreach ($child in $children) { $ids.Add([int]$child.ProcessId) }
    }
    $ids.Reverse()
    foreach ($id in $ids) { Stop-Process -Id $id -ErrorAction SilentlyContinue }
}
Write-Output 'Tracked Ember processes stopped. Database, evidence and certificates were preserved.'
