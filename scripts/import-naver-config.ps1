param([string]$SourcePath='G:\내 드라이브\api 키 저장\api 저장.txt')
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$sourceText=Get-Content -LiteralPath $SourcePath -Raw -Encoding UTF8
function Read-Key([string]$Label){
    $pattern='(?im)^\s*'+[regex]::Escape($Label)+'\s*\r?\n[^\r\n]*\)\s+([A-Za-z0-9_+/=.-]+)\s*$'
    $match=[regex]::Match($sourceText,$pattern)
    if(-not $match.Success){throw ('Cannot safely parse '+$Label+'; source file was not changed.')}
    return $match.Groups[1].Value
}
$mapId=Read-Key 'Client ID'
$mapSecret=Read-Key 'Client Secret'
if($mapId.Length -lt 5 -or $mapSecret.Length -lt 8){throw 'Incomplete NAVER credentials.'}
$envPath=Join-Path $projectRoot '.env'
$envText=[System.IO.File]::ReadAllText($envPath)
$backupPath=Join-Path $projectRoot ('runtime\config-backup-'+[guid]::NewGuid().ToString('N')+'.env')
Copy-Item -LiteralPath $envPath -Destination $backupPath
foreach($entry in @(@('NAVER_MAPS_CLIENT_ID',$mapId),@('NAVER_MAPS_CLIENT_SECRET',$mapSecret))){
    $pattern='(?m)^'+$entry[0]+'=.*$'
    $replacement=$entry[0]+'='+$entry[1]
    if([regex]::IsMatch($envText,$pattern)){$envText=[regex]::Replace($envText,$pattern,[System.Text.RegularExpressions.MatchEvaluator]{param($m)$replacement})}
    else{$envText=$envText.TrimEnd()+"`r`n"+$replacement+"`r`n"}
}
[System.IO.File]::WriteAllText($envPath,$envText,[System.Text.UTF8Encoding]::new($false))
Remove-Variable sourceText,mapId,mapSecret,envText,replacement -ErrorAction SilentlyContinue
Write-Output 'NAVER ID/Secret imported into server .env. Values were not printed. Source unchanged. Backup under ignored runtime/.'
