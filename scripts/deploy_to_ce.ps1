param(
    [string]$HostAlias = "yoplayer-ce",
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$AddonDir = Join-Path $RepoRoot "plugin.service.emby-next-gen"
$TempZip  = Join-Path $env:TEMP "yoemby-deploy.zip"
$GuardrailScript = Join-Path $PSScriptRoot "verify_guardrails.py"

Write-Host "[1/5] Running YoEmby guardrails, syntax check & unit tests..." -ForegroundColor Cyan
python $GuardrailScript
if ($LASTEXITCODE -ne 0) { throw "YoEmby guardrail check failed. Deployment aborted." }

Write-Host "[2/5] Packaging $AddonDir (POSIX paths, excluding __pycache__) ..." -ForegroundColor Cyan
if (Test-Path $TempZip) { Remove-Item $TempZip -Force }
python -c @"
import os, sys, zipfile
src = sys.argv[1]
dst = sys.argv[2]
base = os.path.dirname(src)
with zipfile.ZipFile(dst, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            if name.endswith(('.pyc', '.pyo')):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, base).replace(os.sep, '/')
            zf.write(full, rel)
print('Packaged:', dst)
"@ $AddonDir $TempZip
if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }

Write-Host "[3/5] Stopping Kodi and creating remote backup on $HostAlias ..." -ForegroundColor Cyan
if ($SkipBackup) {
    ssh -o BatchMode=yes -o ConnectTimeout=5 $HostAlias "systemctl stop kodi && sleep 2"
} else {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    ssh -o BatchMode=yes -o ConnectTimeout=5 $HostAlias "systemctl stop kodi && sleep 2 && mkdir -p /storage/backup/emby-dev && cp -a /storage/.kodi/addons/plugin.service.emby-next-gen /storage/backup/emby-dev/plugin.service.emby-next-gen.$ts"
}
if ($LASTEXITCODE -ne 0) { throw "Failed to stop Kodi / create backup." }

Write-Host "[4/5] Uploading and installing addon..." -ForegroundColor Cyan
scp -o BatchMode=yes $TempZip "${HostAlias}:/tmp/yoemby-deploy.zip"
if ($LASTEXITCODE -ne 0) { throw "SCP upload failed." }
@'
import zipfile, shutil, os
z = "/tmp/yoemby-deploy.zip"
ext = "/tmp/yoemby-ext"
dst = "/storage/.kodi/addons/plugin.service.emby-next-gen"
if os.path.exists(ext): shutil.rmtree(ext)
with zipfile.ZipFile(z) as zf:
    zf.extractall(ext)
src = os.path.join(ext, "plugin.service.emby-next-gen")
assert os.path.isdir(src), f"Missing {src}"
if os.path.exists(dst): shutil.rmtree(dst)
shutil.move(src, dst)
shutil.rmtree(ext)
os.remove(z)
print("Deployed ->", dst)
'@ | ssh -o BatchMode=yes -o ConnectTimeout=5 $HostAlias "python3 -"
if ($LASTEXITCODE -ne 0) { throw "Remote extract/install failed." }
Remove-Item $TempZip -Force -ErrorAction SilentlyContinue

Write-Host "[5/5] Starting Kodi..." -ForegroundColor Cyan
ssh -o BatchMode=yes -o ConnectTimeout=5 $HostAlias "systemctl start kodi"
if ($LASTEXITCODE -ne 0) { throw "Failed to start Kodi." }
Write-Host "Done! Run .\scripts\inspect_ce.ps1 in ~10s to verify logs." -ForegroundColor Green
