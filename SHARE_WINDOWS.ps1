# Start an ephemeral HTTPS demo. No administrator privileges or inbound ports required.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { Write-Host 'Install Cloudflare Tunnel first: winget install --id Cloudflare.cloudflared'; exit 1 }
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { Write-Host 'Install Python 3.10+ first.'; exit 1 }
New-Item -ItemType Directory -Force -Path data | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $PSScriptRoot "data/tunnel-$stamp.log"
$tunnel = Start-Process -FilePath 'cloudflared' -ArgumentList @('tunnel','--url','http://127.0.0.1:8000','--no-autoupdate') -RedirectStandardError $log -PassThru -NoNewWindow
try {
    $url = $null
    for ($i=0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if ($tunnel.HasExited) { throw 'Tunnel exited. See local data/tunnel log.' }
        if (Test-Path $log) {
            $match = [regex]::Match((Get-Content $log -Raw), 'https://[a-z0-9-]+\.trycloudflare\.com')
            if ($match.Success) { $url = $match.Value; break }
        }
    }
    if (-not $url) { throw 'No HTTPS address after 60 seconds. Check internet and tunnel log.' }
    $env:JANA_PUBLIC_URL = $url
    $env:JANA_BIND = '127.0.0.1'
    Write-Host "DEMO URL: $url" -ForegroundColor Green
    Write-Host 'Only synthetic data. Keep this window open. URL changes after restart.'
    Write-Host 'Passwords: data/DEMO-ACCOUNTS.txt. Do not share the file publicly.'
    if ($py.Name -eq 'py.exe' -or $py.Name -eq 'py') { & $py.Source -3 server.py --port 8000 --no-browser } else { & $py.Source server.py --port 8000 --no-browser }
} finally {
    if (-not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue }
    Remove-Item Env:JANA_PUBLIC_URL -ErrorAction SilentlyContinue
}
