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
import logging
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

# ------------------------------------------------------------
# 0-1) 로깅 설정
# ------------------------------------------------------------
# 예전에는 전부 print() 였다. 두 가지가 문제였다.
#
#   1) 끌 수가 없다. 이 서버는 요청마다 환자의 나이·성별·기저질환·증상과
#      생성된 진단 결과를 콘솔에 찍고 있었다. 의료정보가 통제 없이 로그에
#      쌓이는 셈이라, 운영에서 켜 둘 수 없는 내용이다.
#   2) 수준 구분이 없다. 오류와 디버그 출력이 같은 스트림에 섞인다.
#
# 그래서 규칙을 이렇게 둔다:
#   INFO  - 무슨 일이 일어났는지만 (건수, 유사도, 소요 시간 등 메타데이터)
#   DEBUG - 환자 정보·증상 원문·생성된 진단처럼 내용 자체가 담기는 것
#
# 기본이 INFO 이므로 그냥 띄우면 개인정보는 로그에 남지 않는다.
# 문제를 추적해야 할 때만 LOG_LEVEL=DEBUG 로 잠깐 올린다.
#   예) set LOG_LEVEL=DEBUG   (Windows)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("medbot")

from flask import Flask, request, jsonify
from flask_cors import CORS  # CORS 임포트
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

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

# 질병 하나가 여러 조각으로 인덱싱되므로, 서로 다른 질병 K_DISEASE 개를 채우려면
# 조각을 그보다 넉넉히 가져와야 한다. 배수가 작으면 상위권이 한두 질병으로
# 채워져 후보가 모자라고, 너무 크면 검색 비용만 는다.
CHUNK_OVERSAMPLE = int(os.getenv("CHUNK_OVERSAMPLE", "6"))
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
# 2026-09-18 재측정. 질병 JSON 의 증상 발화 1,920건(eval/eval_set.json)과
# 비의료 질의 30건(eval/negative_queries.json)으로 잰 값이다.
# 다시 재려면: python Flask_API/eval/eval_retrieval.py --tune
#
# LOW 0.5 -> 0.55: 증상 질의를 잡담으로 놓치는 비율은 0.1% -> 0.7% 로만 늘고,
#   비의료 질의를 걸러내는 비율은 86.7% -> 96.7% 로 오른다.
#   (0.60 이면 비의료를 100% 걸러내지만 증상 놓침이 3.2% 로 뛴다.)
LOW_CONF_THRESHOLD = float(os.getenv("LOW_CONF_THRESHOLD", "0.55"))

# HIGH 0.74 -> 0.82 (정확도 우선). 근거는 두 가지다.
#
# 1) 되묻기는 실제로 검색을 크게 개선한다. 추가 증상이 붙으면 1위 정답률이
#    65.4% -> 87.3%, 정답이 후보(top-5) 안에 들 확률이 86.2% -> 96.9% 가 된다.
#
# 2) 0.80 아래에서는 **되물은 쪽이 바로 답한 쪽보다 성적이 좋았다.**
#    (0.74 기준 바로답함 93.6% vs 되물음 95.0%) 즉 답하지 말았어야 할 질의에
#    답하고 있었다. 두 값이 교차하는 지점이 0.80 근처다.
#
#    임계값   되묻기   바로답한쪽   되물은쪽   최종 1위   최종 후보
#      0.74   48.9%      93.6%      95.0%     82.4%     94.3%
#      0.80   69.7%      96.4%      95.9%     84.7%     96.0%
#      0.82   79.0%      97.0%      96.2%     85.6%     96.4%   <- 선택
#      0.85   90.8%      99.4%      96.6%     87.0%     96.8%
#
# 0.85 이상은 사실상 '항상 한 번 되묻기'(되묻기 91%)인데 최종 정확도는
# 0.4%p 더 얻는 데 그친다. 0.82 는 확신이 확실한 21% 는 바로 통과시키면서
# 최종 정확도의 대부분을 가져온다.
# 되묻기 비율이 부담되면 0.80 으로 내려도 최종 정확도 손실은 0.4%p 다.
HIGH_CONF_THRESHOLD = float(os.getenv("HIGH_CONF_THRESHOLD", "0.82"))
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
        log.warning(
            "답변이 max_tokens(%s)에서 잘렸다. 항목이 일부 비어 있을 수 있다.",
            kwargs["max_tokens"],
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


def _embedding_token_limit(default: int = 128) -> int:
    """임베딩 모델이 실제로 받아들이는 토큰 수."""
    client = getattr(embedding_model, "_client", None) or getattr(
        embedding_model, "client", None
    )
    limit = getattr(client, "max_seq_length", None)
    return int(limit) if limit else default


def _chunk_text(text: str, max_tokens: int) -> List[str]:
    """
    긴 텍스트를 임베딩 한계 안에 들어가는 조각들로 나눈다.

    <p>왜 필요한가 - 예전에는 질병 1건을 통째로 벡터 1개에 넣었다. 그런데
    이 모델의 한계는 128토큰인데 문서는 중앙값 5,700토큰이었다. 100건 전부가
    한계를 넘어, 각 문서의 **앞 4%만** 벡터가 되고 나머지는 버려졌다.
    병명/원인/치료는 어느 문서에서도 임베딩된 적이 없었고, 증상을 3회 반복해
    가중한 것도 첫 128토큰이 같으므로 아무 효과가 없었다.

    <p>줄 단위로 끊어 담는다. extract_any() 가 항목을 줄바꿈으로 이어 붙이고
    supplement 는 발화 하나가 한 줄이라, 줄 경계가 의미 경계와 거의 일치한다.
    한 줄이 통째로 한계를 넘으면 그 줄만 토큰 단위로 강제 분할한다.
    """
    tokenizer = None
    client = getattr(embedding_model, "_client", None) or getattr(
        embedding_model, "client", None
    )
    if client is not None:
        tokenizer = getattr(client, "tokenizer", None)

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []

    def n_tokens(s: str) -> int:
        if tokenizer is None:
            # 토크나이저를 못 얻는 경우의 보수적 근사(한국어는 대략 1토큰 <= 2자).
            return (len(s) + 1) // 2
        return len(tokenizer.encode(s, add_special_tokens=False))

    # 특수 토큰([CLS]/[SEP]) 자리를 남겨 둔다.
    budget = max(16, max_tokens - 8)

    chunks: List[str] = []
    current: List[str] = []
    current_n = 0

    for line in lines:
        ln = n_tokens(line)
        if ln > budget:
            # 한 줄이 예산을 넘는다. 담고 있던 것을 먼저 비우고 이 줄을 쪼갠다.
            if current:
                chunks.append("\n".join(current))
                current, current_n = [], 0
            if tokenizer is None:
                step = budget * 2  # 위 근사의 역수(토큰 -> 글자)
                for i in range(0, len(line), step):
                    chunks.append(line[i : i + step])
            else:
                ids = tokenizer.encode(line, add_special_tokens=False)
                for i in range(0, len(ids), budget):
                    piece = tokenizer.decode(ids[i : i + budget], skip_special_tokens=True).strip()
                    if piece:
                        chunks.append(piece)
            continue

        if current_n + ln > budget:
            chunks.append("\n".join(current))
            current, current_n = [line], ln
        else:
            current.append(line)
            current_n += ln

    if current:
        chunks.append("\n".join(current))
    return chunks


def build_or_load_unified_disease_db():
    if _needs_rebuild(UNIFIED_DB_PATH, JSON_FOLDER):
        token_limit = _embedding_token_limit()
        log.info("[Rebuild] 통합 질병 인덱스를 새로 생성한다. (조각 한계 %d토큰)", token_limit)
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
            symptom_text = extract_any(symptom_data)

            other_info_parts = [f"[병명] {disease_name}"]
            for key, value in data.items():
                if key not in ["병명", "증상"]:
                    content = extract_any(value)
                    if content:
                        other_info_parts.append(f"[{key}] {content}")
            other_info_part = "\n".join(other_info_parts)

            # LLM 에게 줄 원문. 검색은 조각으로 하지만 답변 생성에는 질병 정보가
            # 통째로 필요하므로, 모든 조각이 이 전체 텍스트를 함께 들고 다닌다.
            clean_document_text = (
                f"[증상] {symptom_text}\n" + other_info_part
            ).strip()

            # 검색용 조각.
            #   - 증상을 3회 반복하던 가중치는 없앴다. 어차피 첫 128토큰만
            #     임베딩되므로 반복은 결과에 영향을 주지 못하면서 인덱스 크기만
            #     3배로 불렸다.
            #   - 증상 서술이 검색의 핵심이라 조각으로 나누고, 병명/원인/치료
            #     등은 따로 한 덩어리로 넣는다. 예전에는 이 부분이 잘려나가
            #     아예 검색되지 않았다.
            pieces = _chunk_text(symptom_text, token_limit)
            pieces += _chunk_text(other_info_part, token_limit)

            for order, piece in enumerate(pieces):
                texts_for_embedding.append(piece)
                metas.append(
                    {
                        "병명": disease_name,
                        "파일": filename,
                        "clean_text": clean_document_text,
                        "chunk": order,
                    }
                )

        if not texts_for_embedding:
            raise RuntimeError("통합 인덱스를 만들 텍스트가 없습니다.")

        log.info("질병 %d건 -> 조각 %d개", len(files), len(texts_for_embedding))
        db = faiss_from_texts(texts_for_embedding, embedding_model, metadatas=metas)
        db.save_local(UNIFIED_DB_PATH)
        return db
    else:
        log.info("[Load] 기존 통합 질병 인덱스를 불러온다.")
        return faiss_load_local(UNIFIED_DB_PATH, embedding_model)


# ------------------------------------------------------------
# 7) 단일 검색 함수
# ------------------------------------------------------------
def search_unified_db_with_scores(
    db, user_query: str, k: int
) -> List[Tuple[any, float]]:
    """조각(청크) 단위 검색. 반환값은 (문서, 거리)."""
    # 'query: ' 프리픽스는 E5/BGE 계열 규약이다. 현재 모델
    # (jhgan/ko-sroberta-multitask)은 이 규약을 쓰지 않고 문서도
    # 프리픽스 없이 인덱싱했으므로, 붙이면 쿼리/문서 비대칭만 생긴다.
    if not db:
        return []
    return db.similarity_search_with_score(user_query, k)


def search_diseases(db, user_query: str, k: int) -> List[Tuple[any, float]]:
    """
    질병 단위 상위 k개. 반환값은 (문서, 유사도) - 유사도는 1/(1+거리).

    <p>질병 하나가 여러 조각으로 인덱싱되어 있으므로 잘 맞는 질병이 상위권을
    여러 칸 차지한다. 조각을 넉넉히 가져와 병명으로 중복을 없애야 서로 다른
    질병 k개가 채워진다. 중복을 그대로 두면 두 가지가 깨진다.
      - 확신도 판단이 "1위와 3위의 격차" 를 보는데, 셋 다 같은 질병이면
        격차가 늘 0에 가까워 항상 '확신 없음' 으로 떨어진다.
      - LLM 에 넘길 후보에 같은 질병만 반복해서 들어간다.

    <p>평가 스크립트(eval/eval_retrieval.py)도 이 함수를 쓴다. 검색 경로가
    갈라지면 평가 점수가 실제 동작과 달라진다.
    """
    if not db:
        return []
    raw = search_unified_db_with_scores(db, user_query, k * CHUNK_OVERSAMPLE)
    out, seen = [], set()
    for doc, distance in raw:
        name = get_disease_from_doc(doc)
        if name in seen:
            continue
        seen.add(name)
        out.append((doc, 1 / (1 + distance)))
        if len(out) >= k:
            break
    return out


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
    log.warning("ALLOWED_ORIGINS=* : 모든 출처에서 호출할 수 있다. 운영에서는 쓰지 말 것.")
    CORS(app, resources={r"/*": {"origins": "*"}})
else:
    log.info("CORS 허용 출처: %s", ALLOWED_ORIGINS)
    CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}})

# ------------------------------------------------------------
# 8-1) 요청 제한(rate limit)
# ------------------------------------------------------------
# 이 API 에는 인증이 없다. CORS 는 브라우저만 막아 줄 뿐이라 curl 한 줄이면
# 그대로 호출된다. 요청 하나가 임베딩 검색 + LLM 생성을 돌리므로, 제한이
# 없으면 누구든 반복 호출로 LLM 크레딧을 태울 수 있다.
#
# 한 번에 두 창을 본다:
#   RATE_LIMIT_ASK  - 짧은 구간의 연타 (기본 분당 10회)
#   RATE_LIMIT_DAY  - 하루 총량 (기본 200회). 분당 제한만 두면 종일 천천히
#                     두드려서 크레딧을 말릴 수 있다.
RATE_LIMIT_ASK = os.getenv("RATE_LIMIT_ASK", "10 per minute").strip()
RATE_LIMIT_DAY = os.getenv("RATE_LIMIT_DAY", "200 per day").strip()
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") == "1"

# 프록시(ngrok, nginx, Spring 중계) 뒤에 있으면 remote_addr 이 전부 프록시
# 주소로 찍힌다. 그러면 모든 사용자가 한 바구니를 공유해서, 한 명이 한도를
# 채우면 나머지가 같이 막힌다.
#
# 그래서 "믿을 수 있는 프록시가 직접 연결한 경우에만" X-Forwarded-For 의
# 첫 주소를 키로 쓴다. 아무한테나 이 헤더를 믿으면 헤더를 지어내서 제한을
# 무한정 우회할 수 있으므로, 반드시 주소를 한정한다.
#   TRUSTED_PROXIES="127.0.0.1,::1"   <- 기본값 (같은 PC 의 Spring 중계)
_proxies_raw = os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1")
TRUSTED_PROXIES = {p.strip() for p in _proxies_raw.split(",") if p.strip()}


def _client_key() -> str:
    """요청 제한을 셀 기준이 되는 호출자 식별값."""
    peer = get_remote_address() or "unknown"
    if peer in TRUSTED_PROXIES:
        forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return peer


limiter = Limiter(
    key_func=_client_key,
    app=app,
    storage_uri="memory://",  # 단일 프로세스 전용. 여러 워커로 띄우면 워커마다 따로 센다.
    enabled=RATE_LIMIT_ENABLED,
)
if RATE_LIMIT_ENABLED:
    log.info("요청 제한: %s, %s (신뢰 프록시 %s)",
             RATE_LIMIT_ASK, RATE_LIMIT_DAY, sorted(TRUSTED_PROXIES))
else:
    log.warning("요청 제한이 꺼져 있다(RATE_LIMIT_ENABLED=0). 외부에 노출하지 말 것.")


@app.errorhandler(429)
def rate_limit_exceeded(_e):
    """
    한도 초과 응답.

    flask-limiter 기본 응답은 HTML 이라 호출부가 JSON 으로 읽지 못한다.
    chatbot.js 는 error 키를 그대로 말풍선에 띄우고, Spring 중계도 JSON 을
    기대하므로 다른 오류와 같은 형식으로 맞춘다.
    """
    return jsonify({"error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."}), 429


@app.route("/health", methods=["GET"])
@limiter.exempt  # 감시 스크립트가 주기적으로 두드리는 곳이라 제한에서 뺀다.
def health():
    """기동/인덱스 상태 확인용. 로드밸런서·감시 스크립트가 쓴다."""
    ready = disease_db is not None
    return jsonify({"status": "ok" if ready else "degraded", "index_loaded": ready}), (
        200 if ready else 503
    )

try:
    disease_db = build_or_load_unified_disease_db()
    log.info("통합 인덱스 준비 완료")
except Exception:
    # 인덱스가 없어도 기동은 계속한다(/health 가 degraded 로 알린다).
    # log.exception 이 트레이스백까지 남기므로 traceback 을 따로 부르지 않는다.
    log.exception("통합 인덱스 로드/빌드 실패")
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
    except Exception:
        log.exception("일반 답변 생성 실패")
        return jsonify({"error": "AI 응답 생성에 실패했습니다."}), 502


@app.route("/ask_symptoms", methods=["POST"])
@limiter.limit(RATE_LIMIT_ASK)
@limiter.limit(RATE_LIMIT_DAY)
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

    # 요청 로그.
    # INFO 에는 길이만 남긴다 - 요청이 들어왔다는 사실과 규모는 알 수 있으면서
    # 증상 내용은 로그에 남지 않는다. 내용은 DEBUG 로 내린다.
    # (% 포맷을 쓰는 이유: DEBUG 가 꺼져 있으면 문자열 자체를 만들지 않는다.
    #  f-string 으로 쓰면 레벨과 무관하게 개인정보가 메모리에 조립된다.)
    log.info(
        "새 요청 (증상 %d자, 추가증상 %d자, 환자정보 %s)",
        len(user_input),
        len(additional_symptoms),
        "있음" if patient_prefix else "없음",
    )
    log.debug("  환자 정보: 나이=%s, 성별=%s, 기저질환='%s'", age, gender, conditions)
    log.debug(
        "  입력된 증상: '%s'%s",
        user_input,
        f" + 추가 증상: '{additional_symptoms}'" if additional_symptoms else "",
    )
    log.debug("  최종 검색 쿼리: '%s'", search_query)
    log.debug("  LLM 입력: '%s'", combined_input)

    # 1) 검색 수행 (질병 단위. 조각 중복 제거와 유사도 변환은 함수 안에서 한다)
    scored_docs = search_diseases(disease_db, search_query, k=K_DISEASE)

    # 2) 검색 실패 시 일반 응답 라우팅
    if not scored_docs:
        log.info("관련 질병 정보를 찾을 수 없다. 일반 답변으로 넘긴다.")
        return _general_answer(combined_input)

    # 4) 상위 1개 유사도 점수로 라우팅 판단
    top1_score = scored_docs[0][1]

    # (A) 비의료/잡담 라우팅
    if top1_score < LOW_CONF_THRESHOLD:
        log.info("[판단] 비의료 질문 (유사도 %.2f < %s)", top1_score, LOW_CONF_THRESHOLD)
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
        log.info("[판단] 확신도 낮음 (유사도 %.2f). 추가 증상 요청.", top1_score)
        return jsonify(
            {
                "status": "needs_more_info",
                "message": "증상을 조금 더 구체적으로 알려주시겠어요? 추가적인 증상이 있다면 함께 입력해주세요.",
            }
        )

    # (C) 확신도가 높거나, 추가 증상이 이미 있다면 최종 답변 생성
    log.info("[판단] 확신도 높음 또는 추가 정보로 재검색 (유사도 %.2f)", top1_score)
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
        except Exception:
            log.exception("최종 답변 생성 실패")
            return jsonify({"error": "AI 응답 생성에 실패했습니다."}), 502

        structured_answer = extract_diagnosis_parts(answer)

        # LLM 이 번호 목록 형식을 벗어나면 모든 항목이 빈 문자열이 된다.
        # 그대로 돌려주면 Spring 이 '빈 진단' 한 줄을 DB 에 저장하고
        # 사용자는 이력에서 빈 행을 보게 된다. 형식이 깨졌을 때는
        # 구조화 결과 대신 원문을 문자열로 돌려준다(= 저장 대상이 아님).
        # 이력 화면의 중심 항목이 '예측 진단'이므로 이것이 비면 분리 실패로 본다.
        if not structured_answer["predictedDiagnosis"].strip():
            log.warning("항목 분리 실패 - 원문을 그대로 반환한다(저장하지 않음).")
            return jsonify({"answer": answer})

        # 생성된 진단 결과는 그 자체가 의료정보다. DEBUG 로만 남긴다.
        log.debug("분리된 답변: %s", structured_answer)
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
