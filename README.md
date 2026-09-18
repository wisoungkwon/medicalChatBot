# 🩺 MedChatBot

**MedChatBot**은 환자의 증상과 기본정보를 바탕으로 AI가 참고용 진단 가이드를 제공하는
**Spring Boot(웹) + Flask(RAG/LLM) + MySQL** 구성의 웹 애플리케이션입니다.

> ⚠️ **의료 면책**: 본 서비스는 의료행위가 아닌 정보 제공 서비스이며, 의료진의 진단을
> 대체하지 않습니다. 응급이 의심되면 즉시 119 또는 가까운 응급실을 이용하세요.

---

## 🏗 아키텍처

```
브라우저
  │
  ├─ (1) 화면/회원/이력 ──────────►  Spring Boot  :8080  ──►  MySQL
  │                                  (세션 인증)
  └─ (2) 증상 질의 ───────────────►  Flask        :5050  ──►  LLM (OpenAI 호환 API)
                                     (FAISS 검색)
```

**로그인 상태에서는 (2)가 Spring 의 `POST /api/chat` 을 경유합니다.** 그래서:

- 환자 정보(나이/성별/기저질환)를 **서버가 DB에서** 채웁니다 — 브라우저가 보낸
  값은 위조할 수 있으므로 신뢰하지 않습니다.
- 세션으로 본인을 판별하므로 `patientId` 를 클라이언트가 지정할 수 없습니다.
- 진단 결과 저장까지 한 번의 왕복으로 끝납니다.

비로그인 상태에서는 저장할 대상이 없으므로 Flask 를 직접 호출합니다
(이때는 `app.api-url` 이 쓰입니다).

---

## 🚀 주요 기능

- **증상 입력 & 진단** — 증상을 FAISS로 검색해 관련 질병 문서를 찾고, LLM이 6개 항목
  (예상 병명 / 주요 원인 / 추천 진료과 / 예방·관리 / 주의사항 / 상비약)으로 답변
- **되묻기** — 검색 확신도가 낮으면 추가 증상을 먼저 요청 (`needs_more_info`)
- **비의료 질문 라우팅** — 유사도가 낮으면 일반 대화로 응답
- **과거 진단 조회** — 로그인한 본인의 기록만 조회
- **음성 입력** — Web Speech API (Chrome + HTTPS/localhost)
- **다크 모드 / 글씨 크기 조절**
- **QR 접속** — 같은 네트워크의 모바일에서 접속용 QR 생성

---

## 🛠 기술 스택

| 영역 | 기술 |
|------|------|
| **Frontend** | HTML, CSS, JavaScript, Thymeleaf, marked + DOMPurify |
| **Web Backend** | Spring Boot 3.1.4 (Java 17), Spring Data JPA |
| **Database** | MySQL 8.0 |
| **AI Backend** | Python 3.10+, Flask |
| **LLM** | OpenAI 호환 API — 기본값 Google Gemini `gemini-3.5-flash` |
| **임베딩** | `jhgan/ko-sroberta-multitask` (SBERT) |
| **벡터 검색** | FAISS + LangChain |

[![Java](https://img.shields.io/badge/Java-17-orange?logo=java)](https://www.oracle.com/java/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.1.4-brightgreen?logo=springboot)](https://spring.io/projects/spring-boot)
[![MySQL](https://img.shields.io/badge/MySQL-8.0-blue?logo=mysql)](https://www.mysql.com/)
![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-OpenAI%20compatible-red)
![FAISS](https://img.shields.io/badge/FAISS-yellowgreen?logo=facebook&logoColor=white)

---

## 📂 프로젝트 구조

```plaintext
medchatbot-main/
├── Flask_API/                          # AI 백엔드 (RAG + LLM)
│   ├── Backend_Flask_API.py            #   Flask 앱 (POST /ask_symptoms)
│   ├── requirements.txt
│   ├── .env.example                    #   → .env 로 복사해서 사용
│   ├── json_diseases_final_ver/        #   인덱싱 대상 질병 JSON (100건)
│   ├── test_jsons/                     #   테스트용 샘플
│   └── vector_unified_.../             #   FAISS 인덱스 (자동 생성)
│
├── medical_chatbot_web/                # 웹 백엔드 (Spring Boot)
│   ├── pom.xml
│   └── src/main/
│       ├── java/com/medbot/
│       │   ├── config/                #   SecurityConfig (CSRF)
│       │   ├── controller/             #   Chat, Patient, DiagnosisHistory, Home, Qr
│       │   ├── domain/                 #   Patient, DiagnosisHistory (JPA 엔티티)
│       │   └── repository/
│       └── resources/
│           ├── application.properties
│           ├── static/{css,js}/
│           └── templates/              #   home, chatbot, qr (Thymeleaf)
│
├── json_diseases_final/                # 전체 질병 JSON (2,374건) — 미사용
├── vector_db/                          # 과거 실험용 FAISS 인덱스 — 미사용
└── *.xlsx, *.png                       # DB 테이블 명세서
```

---

## ⚙️ 실행 방법

### 0) 사전 준비

MySQL에 데이터베이스를 만들어 둡니다. 테이블은 JPA가 자동 생성합니다.

```sql
CREATE DATABASE teamproject DEFAULT CHARACTER SET utf8mb4;
```

### 1) Flask AI 백엔드

```bash
cd Flask_API
python -m venv .venv
.venv\Scripts\activate            # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

cp .env.example .env              # 그리고 LLM_API_KEY 를 채웁니다
python Backend_Flask_API.py
```

첫 실행 때 FAISS 인덱스를 생성합니다(수 분 소요). 이후에는 기존 인덱스를 불러옵니다.

**인덱스를 다시 만들어야 하는 경우** — 임베딩 방식이나 모델을 바꿨을 때:

```bash
FORCE_REBUILD=1 python Backend_Flask_API.py     # Windows: set FORCE_REBUILD=1
```

> 인덱스 자동 재생성은 JSON 파일의 수정 시각만 비교합니다. **코드**에서 임베딩
> 방식을 바꾼 경우에는 자동으로 감지되지 않으므로 `FORCE_REBUILD=1`이 필요합니다.

**LLM 제공자** — OpenAI 호환 엔드포인트면 어디든 붙습니다. `.env` 의 세 줄만
바꾸면 되고 코드는 건드릴 필요가 없습니다:

```bash
LLM_API_KEY=...
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/   # 기본값
LLM_MODEL=gemini-3.5-flash                                              # 기본값
```

> **Gemini 를 쓸 때 `LLM_REASONING_EFFORT=none` 을 유지하세요.** Gemini 3.x 는
> 내부 추론(thinking)에 출력 토큰을 쓰고 그 양이 `max_tokens` 에 함께 계산됩니다.
> 실측(`gemini-3.5-flash`, 6개 항목 프롬프트)에서 추론을 켠 채 `max_tokens=1024`
> 로 두면 추론이 약 980토큰을 소모해 답변이 `finish_reason=length` 로 끊기고
> **6개 항목 중 1개만 채워졌습니다.** `none` + `2048` 이면 504토큰에 전부 정상입니다.

| 제공자 | `LLM_BASE_URL` |
|--------|----------------|
| Google Gemini (기본) | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| OpenAI | `https://api.openai.com/v1` |
| Ollama (로컬) | `http://localhost:11434/v1` |
| FriendliAI | `https://api.friendli.ai/serverless/v1` |

> 원래는 FriendliAI 의 EXAONE 을 썼으나, 2026-09 기준 EXAONE 이 서버리스
> 카탈로그에서 빠져 더 이상 쓸 수 없습니다.

**CORS** — 이 API 에는 인증이 없습니다. 기본 허용 출처는 `http://localhost:8080`
(+ `127.0.0.1`) 뿐이며, 다른 주소(예: ngrok)에서 브라우저가 직접 호출하려면
`.env` 에 적어 주어야 합니다:

```bash
ALLOWED_ORIGINS=http://localhost:8080,https://xxxx.ngrok-free.app
```

**상태 확인** — `GET /health` 가 인덱스 로드 여부를 알려줍니다
(정상 200 / 인덱스 없음 503).

**운영 실행** — 개발 서버(`app.run`)는 요청을 사실상 순차 처리합니다:

```bash
waitress-serve --host=0.0.0.0 --port=5050 Backend_Flask_API:app
```

### 2) Spring Boot 웹

`src/main/resources/application.properties`에서 DB 접속 정보와 AI 서버 주소를
환경에 맞게 설정한 뒤:

```bash
cd medical_chatbot_web
./mvnw spring-boot:run            # Windows: mvnw.cmd spring-boot:run
```

**DB 서버가 MariaDB 라면** 환경변수로 드라이버를 전환하세요
(MySQL Connector/J 는 MariaDB 12.x 에서 기동 실패):

```bash
set DB_URL=jdbc:mariadb://localhost:3306/teamproject
set DB_DRIVER=org.mariadb.jdbc.Driver
set JPA_DIALECT=org.hibernate.dialect.MariaDBDialect
mvnw.cmd spring-boot:run
```

- 랜딩: http://localhost:8080/home
- 챗봇: http://localhost:8080/chatbot
- QR: http://localhost:8080/qr?target=/chatbot

### 3) 실행 스크립트 (`scripts/`)

매번 같은 환경변수를 치는 대신 아래를 쓰면 됩니다. 접속 방식은 두 가지이고,
**둘 중 나중에 실행한 sync 가 현재 설정**이 됩니다(둘 다 `scripts/server-env.json`
한 파일에 씁니다).

| 파일 | 하는 일 |
|------|---------|
| `local-sync.cmd` | **LAN 모드.** 이 PC 의 LAN IP 로 설정을 맞춘다. 터널 불필요 |
| `run-ngrok.cmd` | 터널 2개(8080/5050)를 연다. 이 창은 계속 떠 있어야 한다 |
| `ngrok-sync.cmd` | **ngrok 모드.** 현재 터널 주소로 설정을 맞춘다 |
| `run-flask.cmd` | Flask 기동 (`.venv` 있으면 사용, 없으면 전역 Python) |
| `run-spring.cmd` | Spring 기동 (JDK·MariaDB·주소 자동 설정) |

두 sync 가 맞춰 주는 것: Flask 의 `ALLOWED_ORIGINS`, Spring 의 `APP_BASE_URL` /
`APP_API_URL` / `SESSION_COOKIE_SECURE`.

**LAN 모드 (권장)** — 같은 네트워크의 휴대폰에서 접속하며 인터넷에 노출되지 않습니다:

```
1. scripts/local-sync.cmd     (주소 반영 후 종료)
2. scripts/run-flask.cmd      (계속 떠 있음)
3. scripts/run-spring.cmd     (계속 떠 있음)
```

**ngrok 모드** — 외부 인터넷 노출이 필요할 때만. 창 4개를 쓰게 됩니다:

```
1. scripts/run-ngrok.cmd      (계속 떠 있음)
2. scripts/ngrok-sync.cmd     (주소 반영 후 종료)
3. scripts/run-flask.cmd      (계속 떠 있음)
4. scripts/run-spring.cmd     (계속 떠 있음)
```

> ngrok 은 백신이 `HackTool/Win.Ngrok` 으로 분류해 차단할 수 있습니다. 오탐이
> 아니라 방화벽을 우회하는 이중용도 도구라서 정책적으로 막는 것입니다. 회사 PC
> 라면 예외 등록 전에 IT 팀과 상의하세요. 같은 네트워크 시연이면 LAN 모드로
> 충분합니다.

주소를 바꾼 뒤에는 **Flask 와 Spring 을 모두 재시작해야 합니다** — 설정은 기동할
때 한 번만 읽습니다.

`run-spring.cmd` 가 해 주는 것:
- `JAVA_HOME` 이 없는 경로를 가리키면 설치된 JDK 로 바로잡습니다
- 이 PC 의 DB 는 MariaDB 이므로 해당 드라이버/Dialect 로 전환합니다
- 8080 을 이미 쓰는 프로세스가 있으면 PID 와 종료 명령을 알려줍니다

> **`.cmd` 파일은 ASCII 전용으로 두세요.** 실제 로직과 한글 메시지는 같은 이름의
> `.ps1` 에 있습니다. cmd 는 UTF-8 배치파일을 덩어리 단위로 읽다가 멀티바이트
> 문자를 잘라먹어 엉뚱한 줄을 명령으로 실행하는 문제가 있습니다.
> 반대로 `.ps1` 은 **UTF-8 BOM 이 있어야** 합니다 — Windows PowerShell 5.1 은
> BOM 이 없으면 파일을 시스템 ANSI(한국어 Windows 는 cp949)로 읽어 한글이 깨집니다.

---

### 4) 테스트

```bash
cd medical_chatbot_web
./mvnw test                       # Windows: mvnw.cmd test
```

테스트는 **H2 인메모리 DB**(`src/test/resources/application.properties`)를 쓰므로
MySQL/MariaDB 가 없어도 돌아갑니다. CSRF·IDOR·입력검증·QR 오픈리다이렉트 시나리오가
`SecurityAndValidationTests` 에 고정되어 있습니다.

> `mvnw` 는 `JAVA_HOME` 을 봅니다. 설치된 JDK 를 가리키지 않으면
> "JAVA_HOME ... not defined correctly" 로 즉시 실패합니다.
> 이 저장소는 Java 17 문법으로 컴파일하며, JDK 17 이상(JDK 25 포함)에서 빌드됩니다.

---

## 🔌 API

### Flask (`:5050`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/ask_symptoms` | 증상 질의 (`symptom` 최대 2,000자) |
| GET | `/health` | 인덱스 로드 상태 |

```jsonc
// 요청
{
  "symptom": "어제부터 기침이 나고 미열이 있어요",
  "additional_symptoms": "목도 따갑습니다",          // 선택
  "patient": { "age": 30, "gender": "m", "conditions": "없음" }
}

// 응답 (A) 확신 있는 진단
{ "answer": { "predictedDiagnosis": "...", "diagnosisDefinition": "...",
              "recommendedDepartment": "...", "preventionManagement": "...",
              "additionalInfo": "...", "medicine": "...", "rawResponse": "..." } }

// 응답 (B) 추가 정보 필요
{ "status": "needs_more_info", "message": "증상을 조금 더 구체적으로..." }

// 응답 (C) 비의료 질문 또는 항목 분리 실패 — 문자열 answer
//     (문자열일 때는 진단으로 취급하지 않으므로 DB 에 저장되지 않습니다)
{ "answer": "..." }

// 응답 (D) 요청 제한 초과 — HTTP 429
{ "error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요." }
```

`/health` 는 요청 제한에서 제외됩니다(감시 스크립트용).

### Spring Boot (`:8080`)

| 메서드 | 경로 | 인증 | 설명 |
|--------|------|:----:|------|
| POST | `/patient/register` | – | 회원가입 |
| POST | `/patient/login` | – | 로그인 (세션 발급) |
| POST | `/patient/logout` | – | 로그아웃 |
| GET | `/patient/me` | ✅ | 본인 프로필 + 진단 이력 |
| GET | `/patient/me/history` | ✅ | 본인 진단 이력 |
| GET | `/patient/{id}` | ✅ | 본인만 조회 가능 (레거시) |
| POST | `/api/chat` | ✅ | Flask 중계 (로그인 시 사용). 진단 결과 저장까지 이 경로가 처리합니다 |
| GET | `/qrcode?url=` | – | QR 이미지 (base-url 하위만 허용) |

**응답 형식** — 모든 응답은 JSON 객체입니다. 조회 계열은 데이터를 그대로 주고,
그 밖에는 아래 두 가지 중 하나입니다.

```jsonc
{ "error":   "아이디 또는 비밀번호가 올바르지 않습니다." }  // 실패 (4xx/5xx)
{ "message": "회원가입이 완료되었습니다." }                  // 성공 안내 (2xx)
```

`error` / `message` 의 값은 **사용자가 그대로 읽는 안내문**입니다. 예외 메시지나
스택트레이스를 여기에 넣지 마세요 — 내부 구조가 화면에 노출되고 사용자에게는
도움이 되지 않습니다. 원인은 서버 로그에만 남깁니다.

---

## 🔐 보안 주의사항

- **`.env`, `ngrok/ngrok.yml`은 커밋하지 마세요.** 토큰이 들어갑니다.
  (`.gitignore`에 등록되어 있습니다.)
- **DB 비밀번호를 `application.properties`에 평문으로 두지 마세요.** 환경변수
  치환을 권장합니다:
  ```properties
  spring.datasource.username=${DB_USER:root}
  spring.datasource.password=${DB_PASSWORD}
  ```
- **`FLASK_DEBUG=1`로 공개 실행하지 마세요.** Werkzeug 디버거는 임의 코드 실행
  경로입니다.
- **CSRF 보호는 적용되어 있습니다** (`config/SecurityConfig.java`).
  서버가 `XSRF-TOKEN` 쿠키를 내려주고, 클라이언트는 `X-XSRF-TOKEN` 헤더로
  되돌려 보냅니다. `chatbot.js` 의 `postJson()` 이 자동 처리하므로, 새로 POST 를
  추가할 때는 `fetch` 대신 **`postJson()` 을 사용하세요.** 직접 `fetch` 로
  POST 하면 403 이 납니다.
- 인증/인가는 여전히 각 컨트롤러가 `HttpSession` 으로 직접 확인합니다.
  Spring Security 의 인가 기능은 사용하지 않습니다(`permitAll`).
- **세션 쿠키**는 `HttpOnly` + `SameSite=Lax` + 30분 만료로 설정되어 있습니다.
  **HTTPS 로 서비스할 때는 `SESSION_COOKIE_SECURE=true` 를 반드시 켜세요.**
  (로컬 http 에서 켜면 쿠키가 저장되지 않으므로 기본값은 `false` 입니다.)
- **회원가입 입력은 서버에서도 검증합니다** — 아이디 4~50자(공백 불가),
  나이 1~120, 성별 `m`/`f`, 비밀번호 영문·숫자·특수문자 포함 8~20자.
  브라우저 검증만 두면 `curl` 한 줄로 우회됩니다. 규칙을 바꿀 때는
  `PatientController` 와 `chatbot.js` 양쪽을 함께 고치세요.
- **Flask 의 CORS 는 화이트리스트입니다**(`ALLOWED_ORIGINS`). 이 API 에는
  인증이 없으므로 전체 허용(`*`)으로 두면 아무나 호출해 LLM 토큰을 태울 수
  있습니다.
- **Flask `/ask_symptoms` 에는 요청 제한이 걸려 있습니다**(기본 분당 10회 +
  하루 200회, `RATE_LIMIT_ASK` / `RATE_LIMIT_DAY`). CORS 는 브라우저만 막아
  줄 뿐 `curl` 은 그대로 통과하므로, 제한이 없으면 반복 호출로 LLM 크레딧이
  소진됩니다. `RATE_LIMIT_ENABLED=0` 은 로컬 작업에서만 쓰세요.
  - 프록시(ngrok, Spring 중계) 뒤에서는 접속 주소가 전부 프록시 것으로 찍혀
    **모든 사용자가 한도를 공유**합니다. `TRUSTED_PROXIES` 에 적은 주소에서
    온 요청에 한해 `X-Forwarded-For` 를 호출자 주소로 인정해 사용자별로
    셉니다. 아무한테나 이 헤더를 믿으면 헤더를 지어내 우회할 수 있으므로
    실제 프록시 주소만 적으세요.
  - 저장소가 메모리라 **단일 프로세스에서만 정확합니다.** 워커를 여러 개로
    띄우면 워커마다 따로 셉니다.
- **외부 스크립트(marked / DOMPurify)는 버전 고정 + SRI** 로 불러옵니다.
  LLM 출력을 `innerHTML` 로 넣는 페이지이므로 정화기가 바꿔치기되면 곧바로
  XSS 가 됩니다. CDN 주소를 바꿀 때는 `integrity` 해시도 함께 갱신하세요.

---

## 📌 TODO / 알려진 제약

- [x] ~~CSRF 보호~~ — `SecurityConfig` + `postJson()` 적용
- [x] ~~프론트엔드를 `/api/chat` 경유로 전환~~ — 로그인 상태에서 프록시 사용
- [x] ~~Lombok 정리~~ — 미사용이라 제거 (JDK 24+ 호환 문제도 함께 해소)
- [x] ~~자동화 테스트 부재~~ — 회귀 테스트 23개. CSRF/IDOR/입력검증/QR/응답형식과,
      `/api/chat` 의 Flask 실패 처리(타임아웃 504·연결실패 502·오류본문 미유출)까지
      덮습니다. H2 인메모리 DB를 쓰므로 MySQL 없이도 `mvnw test` 가 됩니다
- [x] ~~세션 복원 없음~~ — 새로고침해도 로그인 상태가 유지됩니다
- [x] ~~회원가입 서버측 검증 없음~~ — 잘못된 입력이 500 대신 400 으로 거절됩니다
- [x] ~~Flask CORS 전체 허용~~ — `ALLOWED_ORIGINS` 화이트리스트
- [x] ~~Flask 요청 제한 없음~~ — `flask-limiter` 적용. 프록시 뒤에서도 사용자별로
      세도록 `TRUSTED_PROXIES` + `X-Forwarded-For` 를 함께 씁니다
- [ ] **질병 커버리지 결정** — 아래 "데이터셋" 항목 참고
- [ ] **임베딩 가중치** — 증상 텍스트를 3회 반복해 가중하고 있어, 512토큰을 넘으면
      뒤쪽(병명·원인·치료)이 잘림. 필드별 분리 임베딩(멀티벡터) 검토
- [ ] **LLM 응답 파싱** — 번호 목록 파싱은 형식 변화에 취약. JSON 출력 강제 검토.
      (지금은 분리에 실패하면 빈 진단을 저장하는 대신 원문을 그대로 보여줍니다)
- [ ] **스트리밍 응답(SSE)** 으로 체감 지연 감소
- [ ] `ddl-auto=update` → `validate` + Flyway 마이그레이션
- [ ] **Flask 요청 제한(rate limit)** — 인증이 없어 호출량을 제어할 수단이 없음

---

## 🗂 데이터셋: 왜 100건인가

두 폴더는 **스키마가 거의 같지만 `supplement` 유무가 다릅니다.**

| 폴더 | 질병 수 | `증상` 하위 키 |
|------|--------:|----------------|
| `Flask_API/json_diseases_final_ver` (**현재 사용**) | 100 | Amc, Snu, Kdca, Final, 1200, **supplement** |
| `json_diseases_final` (미사용) | 2,374 | Amc, Snu, Kdca, Final, 1200 |

`supplement` 는 구어체 증상 표현(예: "몸이 너무 피곤하고…")이 담긴 보강 필드로,
사용자가 실제로 입력하는 말투와 매칭시키는 데 핵심적인 역할을 합니다.
100건 쪽에만 전량 존재합니다.

즉 현재 구성은 **커버리지(2,374건)를 포기하고 매칭 품질(supplement)을 택한**
상태로 보입니다. 선택지:

1. **현행 유지** — 100개 질병만 정확히 답변. 나머지는 유사도가 낮아
   일반 대화로 라우팅됩니다.
2. **전체 전환** — `JSON_FOLDER=json_diseases_final` + `FORCE_REBUILD=1`.
   커버리지는 23배 늘지만 구어체 매칭이 약해지고 인덱싱 시간/메모리가 증가합니다.
3. **권장** — 2,374건을 쓰면서 자주 검색되는 질병에 `supplement` 를 점진적으로
   추가. 두 폴더를 병합하는 스크립트가 필요합니다.

---

## 🧪 개발 환경 주의사항

이 저장소를 그대로 받아 실행할 때 걸릴 수 있는 것들:

- **`JAVA_HOME` 확인** — 없는 JDK 를 가리키면 `mvnw` 가 "JAVA_HOME ... not
  defined correctly" 로 즉시 실패합니다. Java 17 이상을 가리켜야 합니다.
- **Lombok 과 최신 JDK** — Lombok 1.18.33 이하는 JDK 24+ 에서
  `TypeTag :: UNKNOWN` 컴파일 오류를 냅니다. 이 프로젝트는 Lombok 을 쓰지
  않으므로 해당 없지만, 다시 도입한다면 1.18.34 이상을 쓰세요.
- **MariaDB 를 쓰는 경우** — MySQL Connector/J 는 MariaDB 10.6+/12.x 의
  메타데이터를 읽지 못해 `Unknown column 'RESERVED' in 'WHERE'` 로 기동에
  실패합니다. 위 "실행 방법"의 MariaDB 환경변수를 사용하세요.
- **Windows 콘솔 인코딩** — Flask 쪽은 stdout 을 UTF-8 로 재설정하므로
  cp949 콘솔에서도 이모지 로그가 깨지거나 죽지 않습니다.
