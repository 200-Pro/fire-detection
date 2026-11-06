$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Get-Command node.exe -ErrorAction SilentlyContinue) -or -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js/npm first. The verified development runtime is Node 24.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe') -and -not (Get-Command py -ErrorAction SilentlyContinue)) { throw 'Install Python 3.12 with the Windows Python launcher first.' }
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { py -3.12 -m venv '.venv'; if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 first.' } }
& '.venv\Scripts\python.exe' -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'This project requires a Python 3.12 virtual environment. Do not copy a venv from another PC.' }
& '.venv\Scripts\python.exe' -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& '.venv\Scripts\python.exe' -m pip install torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
& '.venv\Scripts\python.exe' -m pip install -r 'backend\requirements.txt'
if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
Set-Location -LiteralPath $projectRoot
Write-Output 'Dependencies installed. Prepare .env, models/best.pt and optional private data; then run .venv\Scripts\python.exe scripts\check-local.py. See docs\GITHUB_SETUP.md.'
