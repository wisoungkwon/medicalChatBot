# 이 PC 의 LAN IP 를 찾아 설정 두 곳을 맞춘다 (터널 없이 같은 네트워크에서 접속).
#
#   1) Flask_API\.env 의 ALLOWED_ORIGINS
#   2) scripts\server-env.json  (run-spring 이 읽음)
#
# ngrok 을 쓰지 않으므로 인터넷에 노출되지 않는다. 같은 네트워크(사무실 유선/
# 와이파이가 서로 라우팅되는 경우)의 휴대폰에서 접속할 수 있다.
#
# 직접 부르지 말고 local-sync.cmd 를 쓰면 된다.

param(
    [Parameter(Mandatory = $true)][string]$Root
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

# ---- 1) LAN IP 찾기 ----
# 기본 게이트웨이가 달린 인터페이스의 주소를 쓴다.
# (VirtualBox/WSL/VPN 같은 가상 어댑터를 골라 버리면 휴대폰에서 접속되지 않는다.)
$defaultRoute = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Sort-Object RouteMetric |
    Select-Object -First 1

$ip = $null
if ($defaultRoute) {
    $ip = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $defaultRoute.InterfaceIndex -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1
}

if (-not $ip) {
    Write-Host ''
    Write-Host '[오류] LAN IP 를 찾지 못했습니다. 네트워크 연결을 확인하세요.' -ForegroundColor Red
    exit 1
}

$lanIp = $ip.IPAddress
$springUrl = "http://${lanIp}:8080"
$flaskUrl = "http://${lanIp}:5050"

Write-Host ''
Write-Host '이 PC 의 LAN 주소' -ForegroundColor Cyan
Write-Host ("  인터페이스 : {0}" -f $ip.InterfaceAlias)
Write-Host ("  IP         : {0}/{1}" -f $lanIp, $ip.PrefixLength)
Write-Host ("  게이트웨이 : {0}" -f $defaultRoute.NextHop)
Write-Host ''

# ---- 2) 설정 반영 ----
Update-AllowedOrigins -Root $Root -Origins "http://localhost:8080,http://127.0.0.1:8080,$springUrl"

# http 로 접속하므로 Secure 쿠키를 끈다.
# 켜 두면 브라우저가 세션 쿠키를 저장하지 않아 로그인이 유지되지 않는다.
Write-ServerEnv -Root $Root -Mode 'local' -BaseUrl $springUrl -ApiUrl "$flaskUrl/ask_symptoms" -CookieSecure $false

# ---- 3) 접속 안내 ----
Write-Host ''
Write-Host '접속 주소' -ForegroundColor Cyan
Write-Host ("  이 PC   : http://localhost:8080/home")
Write-Host ("  휴대폰  : {0}/chatbot" -f $springUrl)
Write-Host ("  QR      : {0}/qr?target=/chatbot" -f $springUrl)
Write-Host ''
Write-Host '휴대폰이 연결되지 않으면 - 같은 네트워크가 아닐 수 있습니다.' -ForegroundColor Yellow
Write-Host ("  휴대폰 와이파이 IP 가 {0}.x 대역인지 확인하세요." -f ($lanIp -replace '\.\d+$', ''))
Write-Host '  게스트 와이파이는 보통 유선망과 격리되어 접속되지 않습니다.'
Write-Host ''
Write-Host '다음 순서로 재시작하세요 (설정은 기동할 때만 읽습니다)' -ForegroundColor Cyan
Write-Host '  1) Flask  : scripts\run-flask.cmd'
Write-Host '  2) Spring : scripts\run-spring.cmd'
Write-Host ''
