# Flask(RAG/LLM) 서버를 띄운다.
#
# 설정은 Flask_API\.env 에서 기동할 때 한 번만 읽는다.
# ALLOWED_ORIGINS 를 바꿨다면 이 서버를 다시 띄워야 반영된다.
#
# 직접 부르지 말고 run-flask.cmd 를 쓰면 된다.

param(
    [Parameter(Mandatory = $true)][string]$Root
)

$flaskDir = Join-Path $Root 'Flask_API'
$envFile = Join-Path $flaskDir '.env'

if (-not (Test-Path $envFile)) {
    Write-Host '[오류] Flask_API\.env 가 없습니다.' -ForegroundColor Red
    Write-Host '       .env.example 을 복사한 뒤 LLM_API_KEY 를 채우세요:'
    Write-Host '         copy Flask_API\.env.example Flask_API\.env'
    exit 1
}

# LLM_API_KEY 가 비어 있으면 임베딩 모델을 다 읽고 나서야 죽는다(수십 초 낭비).
# 먼저 확인해서 바로 알려준다.
$tokenLine = Select-String -Path $envFile -Pattern '^\s*LLM_API_KEY\s*=\s*(\S+)' -ErrorAction SilentlyContinue
if (-not $tokenLine) {
    Write-Host '[오류] Flask_API\.env 의 LLM_API_KEY 가 비어 있습니다.' -ForegroundColor Red
    Write-Host '       Google AI Studio 에서 발급: https://aistudio.google.com/apikey'
    exit 1
}

Set-Location $flaskDir

# 가상환경이 있으면 쓰고, 없으면 전역 Python 으로 실행한다.
$venv = Join-Path $flaskDir '.venv\Scripts\python.exe'
if (Test-Path $venv) {
    Write-Host 'Python   : .venv'
    & $venv Backend_Flask_API.py
}
else {
    Write-Host 'Python   : 전역 (.venv 없음)'
    & python Backend_Flask_API.py
}
