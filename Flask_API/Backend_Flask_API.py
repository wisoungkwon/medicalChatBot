# -*- coding: utf-8 -*-
"""
medical_server.py
- 기존 medical_main.py의 기능을 Flask RESTful API로 변환
- API 엔드포인트: /ask_symptoms
"""

# ------------------------------------------------------------
# 0) 표준/서드파티 모듈 임포트
# ------------------------------------------------------------
import os, json, re
import sys
from pathlib import Path
from typing import List, Tuple

# Windows 기본 콘솔 인코딩(cp949)에서는 이 파일의 진단 출력에 쓰인 이모지를
# 인쇄할 수 없어 UnicodeEncodeError 로 서버가 시작조차 못 하는 일이 있었다.
# 출력 스트림을 UTF-8 로 바꾸고, 그래도 안 되는 문자는 대체 문자로 흘린다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from flask import Flask, request, jsonify
from flask_cors import CORS  # CORS 임포트

# LangChain, OpenAI 등 라이브러리 임포트
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from openai import OpenAI

# .env 파일 로드 (선택)
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

# GPU 설정: torch가 있으면 CUDA 사용, 없으면 CPU 사용
try:
    import torch

    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
except Exception:
    DEVICE = "cpu"

# ------------------------------------------------------------
# 1) 경로/DB 기본 설정
# ------------------------------------------------------------
# 이 파일이 있는 디렉터리를 기준으로 경로를 해석한다.
# (이전에는 상대경로여서 CWD가 Flask_API/ 가 아니면 인덱스를 찾지 못했다.)
BASE_DIR = Path(__file__).resolve().parent

JSON_FOLDER = str(
    (BASE_DIR / os.getenv("JSON_FOLDER", "json_diseases_final_ver").strip()).resolve()
)
_default_dbdir = f"vector_unified_{os.path.basename(JSON_FOLDER) or 'db'}"
DB_DIR = str((BASE_DIR / os.getenv("DB_DIR", _default_dbdir).strip()).resolve())

UNIFIED_DB_PATH = os.path.join(DB_DIR, "faiss_unified_disease_db")
os.makedirs(DB_DIR, exist_ok=True)

# ------------------------------------------------------------
# 2) 실행 옵션 및 기준값(Threshold) 설정
# ------------------------------------------------------------
FORCE_REBUILD = os.getenv("FORCE_REBUILD", "0") == "1"
K_DISEASE = int(os.getenv("K_DISEASE", "10"))
MAX_DISEASES = int(os.getenv("MAX_DISEASES", "5"))
CTX_CHARS = int(os.getenv("CTX_CHARS", "4000"))

# 사용자 입력 길이 상한.
# 증상 설명에 2000자를 넘길 일은 없고, 상한이 없으면 긴 본문이 그대로
# 임베딩과 LLM 호출로 흘러가 응답 지연과 토큰 비용을 부른다.
MAX_SYMPTOM_CHARS = int(os.getenv("MAX_SYMPTOM_CHARS", "2000"))

# 아래 임계값은 sim = 1/(1+거리) 스케일에 종속된 경험값이다.
#   - 임베딩 모델(EMBED_MODEL_NAME)이나 인덱스 구성을 바꾸면 반드시 재측정해야 한다.
#   - LangChain FAISS 의 기본 인덱스는 IndexFlatL2 이고, 반환하는 값은
#     L2 거리가 아니라 "제곱" L2 거리다(d2). 임베딩을 정규화했으므로
#     d2 = 2 - 2*cos 이고 범위는 [0, 4] 이다.
#       sim 0.74 ~= d2 0.35 ~= cos 0.82 (매우 가까움)
#       sim 0.50 ~= d2 1.0  ~= cos 0.50 (느슨한 관련)
#   - 코사인 유사도를 직접 쓰고 싶다면 인덱스를 MAX_INNER_PRODUCT 로 만들고
#     임계값을 다시 잡아야 한다(인덱스 재생성 필요).
# 기본값 0.5 는 최신 저장소(master)에서 0.4 -> 0.5 로 튜닝된 값을 따른 것이다.
# 비의료 질문을 일반 대화로 보내는 기준을 더 엄격하게 잡는다.
LOW_CONF_THRESHOLD = float(os.getenv("LOW_CONF_THRESHOLD", "0.5"))
HIGH_CONF_THRESHOLD = float(os.getenv("HIGH_CONF_THRESHOLD", "0.74"))
SCORE_DIFF_THRESHOLD = float(os.getenv("SCORE_DIFF_THRESHOLD", "0.03"))

# ------------------------------------------------------------
# 3) 임베딩 모델 준비
# ------------------------------------------------------------
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "jhgan/ko-sroberta-multitask").strip()
embedding_model = HuggingFaceEmbeddings(
    model_name=EMBED_MODEL_NAME,
    model_kwargs={"device": DEVICE},
    encode_kwargs={"normalize_embeddings": True, "batch_size": 64},
)

# ------------------------------------------------------------
# 4) LLM 클라이언트 준비 (OpenAI 호환 API)
# ------------------------------------------------------------
# 제공자를 이름에 박아두지 않는다. OpenAI 호환 엔드포인트를 주는 곳이면
# 아래 세 값만 바꿔서 옮길 수 있다.
#   LLM_BASE_URL : 호환 엔드포인트 주소
#   LLM_MODEL    : 모델 이름
#   LLM_API_KEY  : API 키
#
# 기본값은 Google Gemini 의 OpenAI 호환 엔드포인트다.
# (이전에는 FriendliAI + EXAONE 이었으나, EXAONE 이 서버리스 카탈로그에서
#  빠지고 계정 크레딧도 소진되어 2026-09 에 옮겼다.)
#
# 다른 곳으로 옮길 때 참고:
#   OpenAI      LLM_BASE_URL=https://api.openai.com/v1
#   Ollama      LLM_BASE_URL=http://localhost:11434/v1   (LLM_API_KEY 는 아무 값)
#   FriendliAI  LLM_BASE_URL=https://api.friendli.ai/serverless/v1
LLM_BASE_URL = os.getenv(
    "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
).strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash").strip()

# 6개 항목 답변은 500토큰 안팎이 나온다. 1024 로 두면 아래 추론 토큰과 합쳐
# 한도를 넘겨 답변이 중간에 끊긴다(finish_reason=length).
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))

# 내부 추론(thinking)에 쓰는 출력 토큰을 제어한다.
#
# Gemini 3.x 계열은 기본적으로 추론을 하는데, 그 토큰이 max_tokens 에 함께
# 계산된다. 실측(gemini-3.5-flash, 6개 항목 프롬프트):
#   추론 기본 + max_tokens=1024 -> 추론이 약 980토큰을 소모,
#                                  finish_reason=length, 6개 항목 중 1개만 채워짐
#   "none"   + max_tokens=2048 -> 응답 504토큰, 6개 항목 전부 정상
#
# 이 작업은 검색된 질병 문서를 형식에 맞춰 정리하는 일이라 추론이 필요하지 않다.
# 추론을 쓰고 싶으면 "low"/"medium"/"high" 로 두고 LLM_MAX_TOKENS 를 함께 올린다.
# 빈 값이나 "auto" 면 파라미터를 보내지 않는다(이 옵션이 없는 제공자용).
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "none").strip()

LLM_API_KEY = os.getenv("LLM_API_KEY")
if not LLM_API_KEY:
    raise RuntimeError(
        "환경변수 LLM_API_KEY 가 비었습니다. "
        "Flask_API/.env 또는 OS 환경변수에 설정하세요. "
        "(예전 이름인 FRIENDLI_TOKEN 을 쓰고 있다면 LLM_API_KEY 로 바꾸세요.)"
    )

llm_client = OpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    timeout=float(os.getenv("LLM_TIMEOUT", "60")),
)


def chat_with_llm(messages, **gen_opts) -> str:
    kwargs = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": gen_opts.get(
            "temperature", 0.3
        ),  # 숫자를 늘리면 늘릴수록 창의적인 답변이 나옴.
        "max_tokens": gen_opts.get("max_tokens", LLM_MAX_TOKENS),
    }
    if LLM_REASONING_EFFORT and LLM_REASONING_EFFORT.lower() != "auto":
        kwargs["reasoning_effort"] = LLM_REASONING_EFFORT

    completion = llm_client.chat.completions.create(**kwargs)
    choice = completion.choices[0]
    content = (choice.message.content or "").strip()

    # 추론 토큰이 한도를 다 쓰면 content 가 비고 finish_reason 이 length 로 온다.
    # 예전에는 None 에 .strip() 을 불러 AttributeError 로 터졌다.
    if not content:
        raise RuntimeError(
            f"LLM 이 빈 응답을 반환했습니다 (finish_reason={choice.finish_reason}). "
            f"LLM_MAX_TOKENS({LLM_MAX_TOKENS})를 올리거나 "
            f"LLM_REASONING_EFFORT(현재 '{LLM_REASONING_EFFORT}')를 none 으로 두세요."
        )
    if choice.finish_reason == "length":
        print(
            f"[경고] 답변이 max_tokens({kwargs['max_tokens']})에서 잘렸습니다. "
            "항목이 일부 비어 있을 수 있습니다."
        )
    return content


# ------------------------------------------------------------
# 5) LLM 보조 유틸리티 함수들
# ------------------------------------------------------------
def extract_any(section_val) -> str:
    if section_val is None:
        return ""
    if isinstance(section_val, dict):
        texts = []
        if "supplement" in section_val:
            supp = section_val.get("supplement")
            if supp and isinstance(supp, list):
                texts.append("\n".join(str(x) for x in supp if x and str(x) != "None"))
        for k, v in section_val.items():
            if k == "supplement":
                continue
            if isinstance(v, list):
                texts.append("\n".join(str(x) for x in v if x and str(x) != "None"))
            elif v and str(v) != "None":
                texts.append(str(v))
        return "\n".join(texts).strip()
    if isinstance(section_val, list):
        return "\n".join(str(x) for x in section_val if x and str(x) != "None").strip()
    return str(section_val).strip()


def get_disease_from_doc(doc):
    return getattr(doc, "metadata", {}).get("병명", "알 수 없는 질병")


def _strip_md(line: str) -> str:
    """제목 줄에서 마크다운 강조/머리기호를 제거한다."""
    line = re.sub(r"[*_`#]+", "", line)  # **1. 병명** -> 1. 병명
    line = re.sub(r"^\s*[-•]\s*", "", line)  # 머리기호 제거
    return line.strip()


def extract_diagnosis_parts(answer: str) -> dict:
    """
    LLM의 답변을 항목별로 분리하여 딕셔너리로 반환.

    주의: SYSTEM_PROMPT가 1번 항목을 굵게 쓰라고 지시하므로 LLM이
    '**1. 예상되는 병명**' 형태로 답하는 경우가 있다. 그대로 분리하면
    모든 항목이 빈 문자열이 되어 DB에 빈 행이 저장되므로,
    분리 전에 줄머리의 마크다운 기호를 먼저 제거한다.
    """
    out = {
        "predictedDiagnosis": "",
        "diagnosisDefinition": "",
        "recommendedDepartment": "",
        "preventionManagement": "",
        "additionalInfo": "",
        "medicine": "",  # ✅ 추가: 상비약 추천을 위한 새로운 필드
        "rawResponse": answer,
    }

    # 줄머리 마크다운을 먼저 걷어내야 '**1. ...**' 도 항목으로 인식된다.
    normalized = "\n".join(
        _strip_md(ln) if re.match(r"^\s*[*_`#\-•\s]*\d+\.\s", ln) else ln
        for ln in answer.strip().split("\n")
    )

    blocks = re.split(r"\n\s*(?=\d+\.\s)", normalized.strip())

    for block in blocks:
        lines = block.strip().split("\n", 1)
        title = _strip_md(lines[0]).replace(":", "").replace("：", "")
        body = lines[1].strip() if len(lines) > 1 else ""

        if "예상되는 병명" in title or "예측 병명" in title:
            out["predictedDiagnosis"] = body
        elif "주요 원인" in title:
            out["diagnosisDefinition"] = body
        elif "추천 진료과" in title:
            out["recommendedDepartment"] = body
        elif "예방 및 관리 방법" in title:
            out["preventionManagement"] = body
        elif "생활 시 주의사항" in title:
            out["additionalInfo"] = body
        elif "상비약 추천" in title:
            out["medicine"] = body  # ✅ 수정: additionalInfo 대신 medicine에 저장

    return out


# ------------------------------------------------------------
# 6) FAISS 헬퍼 및 단일 인덱스 구축 함수
# ------------------------------------------------------------
def faiss_from_texts(texts, embedding_model, metadatas=None):
    try:
        return FAISS.from_texts(texts, embedding=embedding_model, metadatas=metadatas)
    except TypeError:
        return FAISS.from_texts(texts, embeddings=embedding_model, metadatas=metadatas)


def faiss_load_local(path, embedding_model):
    try:
        return FAISS.load_local(
            path, embedding=embedding_model, allow_dangerous_deserialization=True
        )
    except TypeError:
        return FAISS.load_local(
            path, embeddings=embedding_model, allow_dangerous_deserialization=True
        )


def _index_file(path: str) -> str:
    return os.path.join(path, "index.faiss")


def _latest_json_mtime(folder: str) -> float:
    times = []
    if not os.path.isdir(folder):
        return 0.0
    for f in os.listdir(folder):
        if f.lower().endswith(".json"):
            times.append(os.path.getmtime(os.path.join(folder, f)))
    return max(times) if times else 0.0


def _needs_rebuild(index_path: str, source_folder: str) -> bool:
    if FORCE_REBUILD:
        return True
    idx = _index_file(index_path)
    if not os.path.exists(idx):
        return True
    return os.path.getmtime(idx) < _latest_json_mtime(source_folder)


def build_or_load_unified_disease_db():
    if _needs_rebuild(UNIFIED_DB_PATH, JSON_FOLDER):
        print("[Rebuild] 통합 질병 인덱스 (검색용/LLM용 분리)를 새로 생성합니다.")
        texts_for_embedding, metas = [], []
        files = sorted([f for f in os.listdir(JSON_FOLDER) if f.endswith(".json")])

        for filename in files:
            with open(os.path.join(JSON_FOLDER, filename), encoding="utf-8") as f:
                data = json.load(f)

            disease_name = (data.get("병명") or "").strip()
            if not disease_name:
                continue

            symptom_data = data.get("증상", {})
            # extract_any() 는 supplement 를 이미 포함해서 반환한다.
            # 이전에는 supplement 를 여기서 한 번 더 붙여 총 6회 반복되어,
            # 보조 설명이 본 증상보다 과하게 가중되고 있었다.
            symptom_text = extract_any(symptom_data)

            weighted_symptom_part = f"[증상] {symptom_text}\n" * 3

            other_info_parts = [f"[병명] {disease_name}"]
            for key, value in data.items():
                if key not in ["병명", "증상"]:
                    content = extract_any(value)
                    if content:
                        other_info_parts.append(f"[{key}] {content}")
            other_info_part = "\n".join(other_info_parts)
            weighted_document_text = (weighted_symptom_part + other_info_part).strip()
            texts_for_embedding.append(weighted_document_text)

            clean_symptom_part = f"[증상] {symptom_text}"
            clean_document_text = (clean_symptom_part + "\n" + other_info_part).strip()
            metas.append(
                {
                    "병명": disease_name,
                    "파일": filename,
                    "clean_text": clean_document_text,
                }
            )

        if not texts_for_embedding:
            raise RuntimeError("통합 인덱스를 만들 텍스트가 없습니다.")

        db = faiss_from_texts(texts_for_embedding, embedding_model, metadatas=metas)
        db.save_local(UNIFIED_DB_PATH)
        return db
    else:
        print("[Load] 기존 통합 질병 인덱스를 불러옵니다.")
        return faiss_load_local(UNIFIED_DB_PATH, embedding_model)


# ------------------------------------------------------------
# 7) 단일 검색 함수
# ------------------------------------------------------------
def search_unified_db_with_scores(
    db, user_query: str, k: int
) -> List[Tuple[any, float]]:
    # 'query: ' 프리픽스는 E5/BGE 계열 규약이다. 현재 모델
    # (jhgan/ko-sroberta-multitask)은 이 규약을 쓰지 않고 문서도
    # 프리픽스 없이 인덱싱했으므로, 붙이면 쿼리/문서 비대칭만 생긴다.
    if not db:
        return []
    return db.similarity_search_with_score(user_query, k)


# ------------------------------------------------------------
# 8) 프롬프트(SYSTEM) 및 Flask 앱
# ------------------------------------------------------------
SYSTEM_PROMPT = """
당신은 의료 상담 챗봇입니다.
사용자 질문이 건강/증상/의학 관련이면, 아래 [질병 정보]를 참고하여 '출력 형식'에 맞춰 답변하세요.
'상비약 추천'은 당신의 의료 지식을 바탕으로 답변해야 합니다.
불필요한 서론/결론 없이 '출력 형식'의 항목만 간결하게 답변하세요.

출력 형식:
1. 예상되는 병명 (2~3가지):
    - 첫 번째 병명은 **굵게** 표기하고 간단한 설명도 포함하세요.
2. 주요 원인:
3. 추천 진료과 (2~3과):
4. 예방 및 관리 방법:
5. 생활 시 주의사항:
6. 상비약 추천(실제 제품):
""".strip()

app = Flask(__name__)

# 요청 본문 크기 상한(기본 1MB). 없으면 거대한 본문을 그대로 메모리에 읽는다.
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", str(1024 * 1024)))

# CORS 는 필요한 출처만 연다.
# 예전에는 CORS(app) 로 모든 출처를 허용했다. 이 API 는 인증이 없으므로
# 누구나 남의 페이지에서 호출해 LLM 토큰을 태울 수 있었다.
#   ALLOWED_ORIGINS="https://xxxx.ngrok-free.app,http://localhost:8080"
#   ALLOWED_ORIGINS="*"  <- 개발 중 임시로만 사용할 것
_origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080")
ALLOWED_ORIGINS = [o.strip() for o in _origins_raw.split(",") if o.strip()]
if ALLOWED_ORIGINS == ["*"]:
    print("[WARN] ALLOWED_ORIGINS=* : 모든 출처에서 호출할 수 있습니다. 운영에서는 쓰지 마세요.")
    CORS(app, resources={r"/*": {"origins": "*"}})
else:
    print(f"[Info] CORS 허용 출처: {ALLOWED_ORIGINS}")
    CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})


@app.route("/health", methods=["GET"])
def health():
    """기동/인덱스 상태 확인용. 로드밸런서·감시 스크립트가 쓴다."""
    ready = disease_db is not None
    return jsonify({"status": "ok" if ready else "degraded", "index_loaded": ready}), (
        200 if ready else 503
    )

try:
    disease_db = build_or_load_unified_disease_db()
    print("✅ 통합 인덱스 준비 완료")
except Exception as e:
    # print 자체가 실패해도 기동은 계속되어야 하므로 traceback 으로 남긴다.
    import traceback

    print(f"[ERROR] 통합 인덱스 로드/빌드 실패: {e}")
    traceback.print_exc()
    disease_db = None


def _general_answer(user_text: str):
    """의료 질문이 아닐 때의 일반 대화 응답. 두 군데에서 같은 코드를 쓰고 있었다."""
    general_messages = [
        {
            "role": "system",
            "content": "당신은 사용자에게 친절하게 답변하는 AI 어시스턴트입니다.",
        },
        {"role": "user", "content": user_text},
    ]
    try:
        return jsonify({"answer": chat_with_llm(general_messages)})
    except Exception as e:
        print(f"[ERROR] 일반 답변 생성 실패: {e}")
        return jsonify({"error": "AI 응답 생성에 실패했습니다."}), 502


@app.route("/ask_symptoms", methods=["POST"])
def ask_symptoms():
    if disease_db is None:
        return jsonify({"error": "백엔드 시스템이 준비되지 않았습니다."}), 503

    # silent=True: Content-Type 이 없거나 본문이 깨져도 예외 대신 None 을 받는다.
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON 본문이 필요합니다."}), 400

    user_input = data.get("symptom")
    additional_symptoms = data.get("additional_symptoms") or ""
    if not isinstance(additional_symptoms, str):
        additional_symptoms = ""

    # ⭐ 수정: 환자 기본 정보를 파싱
    patient_info = data.get("patient")
    if not isinstance(patient_info, dict):
        patient_info = {}
    age = patient_info.get("age")
    gender = patient_info.get("gender")
    conditions = patient_info.get("conditions")

    if not user_input or not isinstance(user_input, str) or not user_input.strip():
        return jsonify({"error": "symptom 필드가 요청 본문에 필요합니다."}), 400
    user_input = user_input.strip()

    # 상한을 넘는 입력은 거절한다. 잘라서 처리하면 사용자가 보낸 내용과
    # 답변의 근거가 달라지는데 그 사실이 드러나지 않는다.
    if len(user_input) > MAX_SYMPTOM_CHARS:
        return (
            jsonify({"error": f"증상은 {MAX_SYMPTOM_CHARS}자 이내로 입력해주세요."}),
            400,
        )
    additional_symptoms = additional_symptoms.strip()[:MAX_SYMPTOM_CHARS]

    # ⭐ 수정: 환자 정보를 포함하여 검색 쿼리 및 프롬프트에 활용할 문자열 생성
    patient_prefix = ""
    if age or gender or conditions:
        info_parts = []
        if age:
            info_parts.append(f"{age}세")
        if gender == "m":
            info_parts.append("남자")
        if gender == "f":
            info_parts.append("여자")
        if conditions and conditions != "없음":
            info_parts.append(f"기저질환: {conditions}")
        if info_parts:
            patient_prefix = f"환자 정보: {' '.join(info_parts)}. "

    # 검색 쿼리에는 증상만 넣는다. 환자 정보(나이/성별/기저질환)를 함께 넣으면
    # 증상 임베딩이 희석되어 검색 품질이 떨어진다.
    search_query = (
        f"{user_input}\n추가 정보: {additional_symptoms}"
        if additional_symptoms
        else user_input
    )
    # LLM 에게는 환자 정보를 앞에 붙여 전달한다.
    combined_input = f"{patient_prefix}{search_query}"

    # ⭐ 추가: 디버그를 위해 입력받은 증상과 환자 정보 출력
    print("\n" + "=" * 50)
    print("⭐ 새 요청 처리 시작")
    print(f"  환자 정보: 나이={age}, 성별={gender}, 기저질환='{conditions}'")
    print(
        f"  입력된 증상: '{user_input}'"
        + (f" + 추가 증상: '{additional_symptoms}'" if additional_symptoms else "")
    )
    print(f"  최종 검색 쿼리: '{search_query}'")
    print(f"  LLM 입력: '{combined_input}'")
    print("-" * 50)

    # 1) 검색 수행 (combined_input 사용)
    docs_with_scores = search_unified_db_with_scores(
        disease_db, search_query, k=K_DISEASE
    )

    # 2) 검색 실패 시 일반 응답 라우팅
    if not docs_with_scores:
        print("[Info] 관련 질병 정보를 찾을 수 없습니다. 일반적인 답변을 시도합니다.")
        return _general_answer(combined_input)

    # 3) 거리 -> 간이 유사도 변환
    # 문서 1건 = 질병 1건 구조이므로 별도 중복 제거는 하지 않는다.
    # (예전 변수명이 unique_docs 였으나 실제로는 dedup 을 하지 않아 오해를 유발했다.)
    scored_docs = [(doc, 1 / (1 + score)) for doc, score in docs_with_scores]

    # 4) 상위 1개 유사도 점수로 라우팅 판단
    top1_score = scored_docs[0][1]

    # (A) 비의료/잡담 라우팅
    if top1_score < LOW_CONF_THRESHOLD:
        print(f"[판단] 비의료 질문 (유사도: {top1_score:.2f} < {LOW_CONF_THRESHOLD})")
        return _general_answer(combined_input)

    # (B) 확신도 판단
    # 1위가 충분히 높고, 3위와의 격차도 있어야 '확신'으로 본다.
    # (2위가 아니라 3위와 비교하는 것은 의도된 동작 - 1,2위가 비슷한 감별진단
    #  쌍인 경우를 확신 없음으로 떨어뜨리지 않기 위함)
    is_confident = top1_score >= HIGH_CONF_THRESHOLD and (
        len(scored_docs) < 3
        or (scored_docs[0][1] - scored_docs[2][1]) >= SCORE_DIFF_THRESHOLD
    )

    if not is_confident and not additional_symptoms:
        print(f"[판단] 확신도 낮음 (유사도: {top1_score:.2f}). 추가 증상 요청.")
        return jsonify(
            {
                "status": "needs_more_info",
                "message": "증상을 조금 더 구체적으로 알려주시겠어요? 추가적인 증상이 있다면 함께 입력해주세요.",
            }
        )

    # (C) 확신도가 높거나, 추가 증상이 이미 있다면 최종 답변 생성
    print(f"[판단] 확신도 높음 또는 추가 정보로 재검색. (유사도: {top1_score:.2f})")
    final_docs = [doc for doc, score in scored_docs[:MAX_DISEASES]]

    # 5) LLM 생성
    if final_docs:
        final_context = "\n---\n".join(
            [doc.metadata.get("clean_text", doc.page_content) for doc in final_docs]
        )

        # ⭐ 수정: 환자 정보를 LLM 프롬프트에 추가
        # combined_input 에 이미 patient_prefix 가 포함되어 있으므로
        # 여기서 다시 붙이지 않는다 (예전에는 환자 정보가 두 번 들어갔다).
        llm_user_query = f"사용자 질문: {combined_input}"
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"[질병 참고]\n{final_context[:CTX_CHARS]}"},
            {"role": "user", "content": llm_user_query},
        ]
        try:
            answer = chat_with_llm(messages)
        except Exception as e:
            print(f"[ERROR] 최종 답변 생성 실패: {e}")
            return jsonify({"error": "AI 응답 생성에 실패했습니다."}), 502

        structured_answer = extract_diagnosis_parts(answer)

        # LLM 이 번호 목록 형식을 벗어나면 모든 항목이 빈 문자열이 된다.
        # 그대로 돌려주면 Spring 이 '빈 진단' 한 줄을 DB 에 저장하고
        # 사용자는 이력에서 빈 행을 보게 된다. 형식이 깨졌을 때는
        # 구조화 결과 대신 원문을 문자열로 돌려준다(= 저장 대상이 아님).
        # 이력 화면의 중심 항목이 '예측 진단'이므로 이것이 비면 분리 실패로 본다.
        if not structured_answer["predictedDiagnosis"].strip():
            print("[경고] 항목 분리 실패 - 원문을 그대로 반환한다(저장하지 않음).")
            return jsonify({"answer": answer})

        print(f"[디버그] 분리된 답변: {structured_answer}")
        return jsonify({"answer": structured_answer})

    return jsonify({"error": "알 수 없는 오류가 발생했습니다."}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    # debug=True 는 Werkzeug 디버거를 노출해 임의 코드 실행이 가능해진다.
    # 공개 터널(ngrok) 뒤에서 실행되므로 절대 켜지 않는다.
    # 로컬 디버깅이 필요하면 FLASK_DEBUG=1 로만 일시 활성화한다.
    debug = os.getenv("FLASK_DEBUG", "0") == "1"

    # 개발 서버는 요청을 사실상 순차 처리한다. 임베딩+LLM 호출로 요청당
    # 수 초가 걸리므로, 운영에서는 waitress/gunicorn 을 사용해야 한다.
    #   예) waitress-serve --host=0.0.0.0 --port=5050 Backend_Flask_API:app
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
