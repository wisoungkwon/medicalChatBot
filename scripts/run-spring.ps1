# Spring Boot 웹 서버를 띄운다.
#   - JAVA_HOME 이 깨져 있으면 설치된 JDK 로 바로잡는다
#   - 이 PC 의 DB 는 MariaDB 이므로 해당 드라이버로 전환한다
#   - ngrok-sync 가 만들어 둔 주소가 있으면 함께 적용한다
#
# 직접 부르지 말고 run-spring.cmd 를 쓰면 된다.

param(
    [Parameter(Mandatory = $true)][string]$Root
)

# ---- JDK -------------------------------------------------------------
# 전역 JAVA_HOME 이 없는 경로(jdk1.8.0_241)를 가리키고 있어
# mvnw 가 "JAVA_HOME ... not defined correctly" 로 죽는다.
function Test-Jdk([string]$Path) {
    return ($Path -and (Test-Path (Join-Path $Path 'bin\java.exe')))
}

if (-not (Test-Jdk $env:JAVA_HOME)) {
    $candidates = @(
        'C:\Program Files\Java\jdk-25.0.3',
        'C:\Program Files\Java\jdk-21',
        'C:\Program Files\Java\jdk-17'
    )
    $found = $candidates | Where-Object { Test-Jdk $_ } | Select-Object -First 1
    if (-not $found) {
        Write-Host '[오류] Java 17 이상의 JDK 를 찾지 못했습니다.' -ForegroundColor Red
        Write-Host '       설치한 뒤 이 스크립트의 $candidates 에 경로를 추가하세요.'
        exit 1
    }
    $env:JAVA_HOME = $found
}
Write-Host ("JDK      : {0}" -f $env:JAVA_HOME)

# ---- DB --------------------------------------------------------------
# MySQL Connector/J 는 MariaDB 12.x 의 메타데이터를 읽지 못해
# "Unknown column 'RESERVED' in 'WHERE'" 로 기동에 실패한다.
# MySQL 서버를 쓴다면 아래 세 줄을 지우면 기본값(MySQL)이 적용된다.
$env:DB_URL = 'jdbc:mariadb://localhost:3306/teamproject'
$env:DB_DRIVER = 'org.mariadb.jdbc.Driver'
$env:JPA_DIALECT = 'org.hibernate.dialect.MariaDBDialect'
Write-Host ("DB       : {0}" -f $env:DB_URL)

# ---- 접속 주소 (ngrok-sync / local-sync 가 만든다) ---------------------
$envJson = Join-Path $Root 'scripts\server-env.json'
if (Test-Path $envJson) {
    $cfg = Get-Content $envJson -Raw -Encoding UTF8 | ConvertFrom-Json
    $env:APP_BASE_URL = $cfg.appBaseUrl
    $env:APP_API_URL = $cfg.appApiUrl
    # HTTPS(ngrok)면 Secure 쿠키를 켜고, http(LAN)면 끈다.
    # http 에서 켜 두면 브라우저가 세션 쿠키를 저장하지 않아 로그인이 풀린다.
    $env:SESSION_COOKIE_SECURE = if ($cfg.cookieSecure) { 'true' } else { 'false' }
    Write-Host ("모드      : {0}  (생성 {1})" -f $cfg.mode, $cfg.generatedAt)
    Write-Host ("주소      : {0}" -f $env:APP_BASE_URL)
    Write-Host ("Flask     : {0}" -f $env:APP_API_URL)
    Write-Host ("쿠키Secure: {0}" -f $env:SESSION_COOKIE_SECURE)
}
else {
    Write-Host '주소     : 설정 없음 - localhost 기본값으로 실행합니다.' -ForegroundColor Yellow
    Write-Host '           같은 네트워크의 휴대폰에서 접속하려면 scripts\local-sync.cmd 를,'
    Write-Host '           인터넷 노출이 필요하면 scripts\ngrok-sync.cmd 를 먼저 실행하세요.'
}

# ---- 8080 점유 확인 --------------------------------------------------
# 예전에 띄워 둔 서버가 남아 있으면 "Port 8080 was already in use" 로 죽는다.
$holders = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pidValue in $holders) {
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host ("[경고] 8080 포트를 PID {0} ({1}) 가 이미 쓰고 있습니다." -f $pidValue, $proc.ProcessName) -ForegroundColor Yellow
    $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue" -ErrorAction SilentlyContinue).CommandLine
    if ($cmdLine) {
        Write-Host ("       {0}" -f $cmdLine.Substring(0, [Math]::Min(150, $cmdLine.Length)))
    }
    Write-Host ("       종료하려면:  taskkill /PID {0} /F" -f $pidValue)
}

# ---- 실행 ------------------------------------------------------------
Write-Host ''
Set-Location (Join-Path $Root 'medical_chatbot_web')
& .\mvnw.cmd spring-boot:run
