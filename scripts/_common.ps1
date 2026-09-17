# ngrok-sync / local-sync 가 함께 쓰는 헬퍼.
# 단독 실행용이 아니라 dot-source(. 경로) 해서 쓴다.

function Write-Utf8NoBom([string]$Path, [string[]]$Lines) {
    # Windows PowerShell 5.1 의 Set-Content -Encoding utf8 은 BOM 을 붙인다.
    # .env 와 .json 은 BOM 이 없는 편이 안전하다.
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($Path, $Lines, $enc)
}

<#
 Flask_API\.env 의 ALLOWED_ORIGINS 를 바꾼다.

 브라우저가 Flask 를 직접 부를 때(비로그인 상태)의 Origin 은 '페이지를 띄운 쪽',
 즉 Spring 주소다. Flask 자기 주소가 아니다.
#>
function Update-AllowedOrigins([string]$Root, [string]$Origins) {
    $envPath = Join-Path $Root 'Flask_API\.env'
    if (-not (Test-Path $envPath)) {
        Write-Host "[경고] $envPath 가 없습니다. .env.example 을 복사해 만드세요." -ForegroundColor Yellow
        return
    }
    $lines = [System.IO.File]::ReadAllLines($envPath)
    $done = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*ALLOWED_ORIGINS\s*=') {
            $lines[$i] = "ALLOWED_ORIGINS=$Origins"
            $done = $true
        }
    }
    if (-not $done) { $lines += "ALLOWED_ORIGINS=$Origins" }

    Write-Utf8NoBom $envPath $lines
    Write-Host "갱신: Flask_API\.env" -ForegroundColor Green
    Write-Host "  ALLOWED_ORIGINS=$Origins"
}

<#
 run-spring 이 읽는 주소 파일을 쓴다.

 ngrok 모드와 local 모드가 같은 파일에 쓰므로, 마지막으로 실행한 sync 가
 곧 '현재 설정'이 된다. 어느 쪽이 적용 중인지 헷갈릴 일이 없다.
#>
function Write-ServerEnv([string]$Root, [string]$Mode, [string]$BaseUrl, [string]$ApiUrl, [bool]$CookieSecure) {
    $path = Join-Path $Root 'scripts\server-env.json'
    $payload = [ordered]@{
        mode          = $Mode
        generatedAt   = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        appBaseUrl    = $BaseUrl
        appApiUrl     = $ApiUrl
        cookieSecure  = $CookieSecure
    }
    Write-Utf8NoBom $path @($payload | ConvertTo-Json)
    Write-Host "갱신: scripts\server-env.json  (mode=$Mode)" -ForegroundColor Green
    Write-Host "  APP_BASE_URL=$BaseUrl"
    Write-Host "  APP_API_URL=$ApiUrl"
    Write-Host "  SESSION_COOKIE_SECURE=$($CookieSecure.ToString().ToLower())"
}
