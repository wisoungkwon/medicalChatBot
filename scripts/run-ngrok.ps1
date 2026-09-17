# ngrok 터널 2개(8080 Spring / 5050 Flask)를 띄운다.
#
#   - authtoken 은 프로젝트 밖의 기본 설정 파일에서 읽는다
#     (%LOCALAPPDATA%\ngrok\ngrok.yml - 저장소에 토큰을 두지 않기 위함)
#   - 터널 정의는 ngrok\ngrok.yml 에서 읽는다
#   - --config 를 여러 번 주면 두 설정이 병합된다
#
# 이 창은 터널이 살아 있는 동안 계속 떠 있어야 한다.
# 띄운 뒤 다른 창에서 scripts\ngrok-sync.cmd 를 실행할 것.
#
# 직접 부르지 말고 run-ngrok.cmd 를 쓰면 된다.

param(
    [Parameter(Mandatory = $true)][string]$Root
)

$exe = Join-Path $Root 'ngrok\ngrok.exe'
$tunnelCfg = Join-Path $Root 'ngrok\ngrok.yml'
$agentCfg = Join-Path $env:LOCALAPPDATA 'ngrok\ngrok.yml'

if (-not (Test-Path $exe)) {
    Write-Host ("[오류] ngrok 실행 파일이 없습니다: {0}" -f $exe) -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $agentCfg)) {
    Write-Host ("[오류] ngrok authtoken 설정이 없습니다: {0}" -f $agentCfg) -ForegroundColor Red
    Write-Host '       먼저 토큰을 저장하세요 (한 번만 하면 됩니다):'
    Write-Host ('         "{0}" config add-authtoken <토큰>' -f $exe)
    Write-Host '       토큰 발급: https://dashboard.ngrok.com/authtokens'
    exit 1
}

Write-Host '터널을 엽니다. 이 창을 닫으면 터널도 끊깁니다.' -ForegroundColor Cyan
Write-Host '주소가 뜨면 다른 창에서 scripts\ngrok-sync.cmd 를 실행하세요.'
Write-Host ''

& $exe start --all --config $agentCfg --config $tunnelCfg
