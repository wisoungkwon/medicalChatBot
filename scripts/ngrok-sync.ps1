# 실행 중인 ngrok 에서 현재 터널 주소를 읽어와 설정 두 곳을 맞춘다.
#
#   1) Flask_API\.env 의 ALLOWED_ORIGINS  -> Spring 주소 (브라우저 Origin)
#   2) scripts\server-env.json            -> Spring 실행용 주소 (run-spring 이 읽음)
#
# ngrok 무료 플랜은 재시작할 때마다 주소가 바뀌므로 그때마다 실행한다.
# 직접 부르지 말고 ngrok-sync.cmd 를 쓰면 된다.

param(
    [Parameter(Mandatory = $true)][string]$Root
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot '_common.ps1')

# ---- 1) ngrok 로컬 API 에서 터널 목록 읽기 ----
$api = 'http://127.0.0.1:4040/api/tunnels'
try {
    $tunnels = (Invoke-RestMethod -Uri $api -TimeoutSec 5).tunnels
}
catch {
    Write-Host ''
    Write-Host '[오류] ngrok 에 연결할 수 없습니다 ($api).' -ForegroundColor Red
    Write-Host '       ngrok 을 먼저 실행하세요:'
    Write-Host '         ngrok\ngrok.exe start --all --config "%LOCALAPPDATA%\ngrok\ngrok.yml" --config ngrok\ngrok.yml'
    exit 1
}

function Get-PublicUrl([int]$LocalPort) {
    $t = $tunnels |
        Where-Object { $_.proto -eq 'https' -and $_.config.addr -match ":$LocalPort$" } |
        Select-Object -First 1
    if ($t) { return $t.public_url }
    return $null
}

$springUrl = Get-PublicUrl 8080
$flaskUrl = Get-PublicUrl 5050

if (-not $springUrl -or -not $flaskUrl) {
    Write-Host ''
    Write-Host '[오류] 8080/5050 터널을 모두 찾지 못했습니다.' -ForegroundColor Red
    Write-Host '       현재 열린 터널:'
    foreach ($t in $tunnels) {
        Write-Host ("         {0,-12} {1,-6} {2} -> {3}" -f $t.name, $t.proto, $t.config.addr, $t.public_url)
    }
    Write-Host '       ngrok\ngrok.yml 의 tunnels 정의를 확인하세요 (springboot: 8080, flask: 5050).'
    exit 1
}

Write-Host ''
Write-Host '현재 ngrok 주소' -ForegroundColor Cyan
Write-Host ("  Spring (8080) : {0}" -f $springUrl)
Write-Host ("  Flask  (5050) : {0}" -f $flaskUrl)
Write-Host ''

# ---- 2) Flask_API\.env 의 ALLOWED_ORIGINS 갱신 ----
Update-AllowedOrigins -Root $Root -Origins "http://localhost:8080,http://127.0.0.1:8080,$springUrl"

# ---- 3) Spring 실행용 주소 파일 ----
# HTTPS(ngrok)로 서비스하므로 세션 쿠키에 Secure 를 켠다.
# 이 값이 true 면 http://localhost:8080 직접 접속에서는 로그인이 유지되지 않는다.
Write-ServerEnv -Root $Root -Mode 'ngrok' -BaseUrl $springUrl -ApiUrl $flaskUrl/ask_symptoms -CookieSecure $true

Write-Host ''
Write-Host '다음 순서로 재시작하세요 (설정은 기동할 때만 읽습니다)' -ForegroundColor Cyan
Write-Host '  1) Flask  : scripts\run-flask.cmd'
Write-Host '  2) Spring : scripts\run-spring.cmd'
Write-Host ''
