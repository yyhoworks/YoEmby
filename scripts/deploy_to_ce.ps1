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

Write-Host "[2/5] Packaging $AddonDir ..." -ForegroundColor Cyan
if (Test-Path $TempZip) { Remove-Item $TempZip -Force }
python -c "import os, zipfile; src=r'$AddonDir'; dst=r'$TempZip'; base=os.path.dirname(src); zf=zipfile.ZipFile(dst,'w',zipfile.ZIP_DEFLATED,compresslevel=1); [zf.write(os.path.join(r,f), os.path.relpath(os.path.join(r,f), base)) for r,d,fs in os.walk(src) if '__pycache__' not in r.split(os.sep) for f in fs if not f.endswith('.pyc')]; zf.close()"
if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }

Write-Host "[3/5] Stopping Kodi and creating remote backup on $HostAlias ..." -ForegroundColor Cyan
if ($SkipBackup) {
    ssh -o BatchMode=yes -o ConnectTimeout=5 $HostAlias "systemctl stop kodi && sleep 2"
} else {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    ssh -o BatchMode=yes -o ConnectTimeout=5 $HostAlias "systemctl stop kodi && sleep 2 && mkdir -p /storage/backup/emby-dev && cp -a /storage/.kodi/addons/plugin.service.emby-next-gen /storage/backup/emby-dev/plugin.service.emby-next-gen.$ts"
}

Write-Host "[4/5] Uploading and installing addon..." -ForegroundColor Cyan
scp -o BatchMode=yes $TempZip "${HostAlias}:/tmp/yoemby-deploy.zip"
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
Remove-Item $TempZip -Force -ErrorAction SilentlyContinue

Write-Host "[5/5] Starting Kodi..." -ForegroundColor Cyan
ssh -o BatchMode=yes -o ConnectTimeout=5 $HostAlias "systemctl start kodi"
Write-Host "Done! Run .\scripts\inspect_ce.ps1 in ~10s to verify logs." -ForegroundColor Green
