param(
    [string]$HostAlias = "yoplayer-ce"
)

$ErrorActionPreference = "Stop"
ssh -o BatchMode=yes -o ConnectTimeout=5 $HostAlias "
echo '=== DISK ==='
df -h /storage
echo '=== DATABASES ==='
ls -lh /storage/.kodi/userdata/Database/MyVideos* /storage/.kodi/userdata/Database/emby_* /storage/.kodi/userdata/Database/Textures* 2>/dev/null
echo '=== MEMORY / CPU ==='
top -bn1 | head -n 12
echo '=== EMBY VERSION ==='
grep '<addon ' /storage/.kodi/addons/plugin.service.emby-next-gen/addon.xml
echo '=== RECENT EMBY / ERROR LOGS ==='
grep -iE 'EMBY\.|traceback|error' /storage/.kodi/temp/kodi.log | tail -n 30
"
