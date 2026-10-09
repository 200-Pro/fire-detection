$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { py -3.12 -m venv '.venv'; if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 first.' } }
& '.venv\Scripts\python.exe' -m pip install --upgrade pip
& '.venv\Scripts\python.exe' -m pip install torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
& '.venv\Scripts\python.exe' -m pip install -r 'backend\requirements.txt'
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
Write-Output 'Setup complete. Run scripts\start-local.ps1 from the project folder.'
