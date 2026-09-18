# -*- coding: utf-8 -*-
"""
현재 인덱스의 검색 성능을 잰다.

Backend_Flask_API 를 그대로 import 해서 **실제 서비스가 쓰는 인덱스와 검색
함수**를 쓴다. 평가용으로 로직을 베껴 쓰면 본체가 바뀔 때 조용히 어긋난다.

재는 것:
  Recall@k  - 정답 병명이 상위 k개 병명 안에 있는가
  MRR       - 정답이 몇 번째로 나왔는가(역순위 평균)

그리고 검색 점수가 라우팅에 어떻게 걸리는지도 함께 본다. 이게 사용자에게
실제로 보이는 결과다:
  1위 점수 < LOW_CONF_THRESHOLD  -> 비의료 질문으로 보고 일반 잡담 응답
                                     (진짜 증상 질문인데 잡담으로 처리 = 최악)
  확신 조건 미달                 -> 되묻기(needs_more_info)

실행:
  python Flask_API/eval/eval_retrieval.py
  python Flask_API/eval/eval_retrieval.py --limit 200     (빠른 확인용)
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent))

# Backend_Flask_API 는 LLM_API_KEY 가 없으면 import 단계에서 멈춘다.
# 평가는 LLM 을 전혀 호출하지 않으므로(검색만 쓴다) 자리만 채운다.
os.environ.setdefault("LLM_API_KEY", "dummy-key-for-eval-no-calls-made")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import Backend_Flask_API as app  # noqa: E402

EVAL_SET = BASE_DIR / "eval_set.json"
KS = (1, 3, 5)


def retrieved_diseases(query: str, k: int):
    """서비스와 **같은 검색 함수**로 질병 후보를 얻는다.

    평가용으로 검색 로직을 따로 쓰면 본체가 바뀔 때 점수가 조용히 실제
    동작과 달라진다. search_diseases() 가 조각 중복 제거와 유사도 변환까지
    해서 (문서, 유사도) 를 돌려주므로 병명만 꺼내 쓴다.
    """
    return [
        (app.get_disease_from_doc(doc), sim)
        for doc, sim in app.search_diseases(app.disease_db, query, k=k)
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="질의 수 제한(빠른 확인용)")
    ap.add_argument("--k", type=int, default=app.K_DISEASE, help="검색 개수")
    ap.add_argument("--label", default="현재 인덱스", help="결과에 표시할 이름")
    ap.add_argument("--tune", action="store_true",
                    help="임계값 후보별 결과를 함께 출력한다(인덱스를 바꾼 뒤 재측정용)")
    args = ap.parse_args()

    if app.disease_db is None:
        print("인덱스를 불러오지 못했다. 먼저 서버를 한 번 띄워 인덱스를 만들어야 한다.")
        sys.exit(1)

    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    items = data["items"]
    if args.limit:
        items = items[: args.limit]

    # 임계값 재측정용으로 질의별 (1위점수, 1위정답여부, 1-3위 격차) 를 모아 둔다.
    tuning_rows = []

    hits = {k: 0 for k in KS}
    rr_sum = 0.0
    by_pos = defaultdict(lambda: {"n": 0, "hit1": 0, "hit5": 0})
    routed_chat = 0        # 비의료로 오분류되어 잡담 응답으로 갈 질의
    routed_more_info = 0   # 되묻기로 갈 질의
    top1_scores = []

    for i, item in enumerate(items, 1):
        names = retrieved_diseases(item["query"], args.k)
        gold = item["disease"]

        rank = next((r for r, (n, _) in enumerate(names, 1) if n == gold), None)
        for k in KS:
            if rank is not None and rank <= k:
                hits[k] += 1
        if rank:
            rr_sum += 1.0 / rank

        # 위치 구간별 (0-4 / 5-9 / 10-19)
        p = item["position"]
        bucket = "0-4" if p < 5 else ("5-9" if p < 10 else "10+")
        by_pos[bucket]["n"] += 1
        if rank == 1:
            by_pos[bucket]["hit1"] += 1
        if rank is not None and rank <= 5:
            by_pos[bucket]["hit5"] += 1

        # 라우팅 판정 (ask_symptoms 의 분기와 동일)
        if names:
            top1 = names[0][1]
            top1_scores.append(top1)
            tuning_rows.append(
                (top1, rank == 1, top1 - names[2][1] if len(names) >= 3 else 1.0)
            )
            if top1 < app.LOW_CONF_THRESHOLD:
                routed_chat += 1
            else:
                confident = top1 >= app.HIGH_CONF_THRESHOLD and (
                    len(names) < 3 or (names[0][1] - names[2][1]) >= app.SCORE_DIFF_THRESHOLD
                )
                if not confident:
                    routed_more_info += 1

        if i % 200 == 0:
            print(f"  ... {i}/{len(items)}", file=sys.stderr)

    n = len(items)
    print()
    print("=" * 62)
    print(f"  {args.label}  (질의 {n}건 / 질병 {data['disease_count']}종)")
    print("=" * 62)
    print(f"  임베딩 모델 : {app.EMBED_MODEL_NAME}")
    print(f"  인덱스 벡터 : {app.disease_db.index.ntotal}개")
    print()
    print("  [검색 정확도]")
    for k in KS:
        print(f"    Recall@{k} : {hits[k]/n:6.1%}   ({hits[k]}/{n})")
    print(f"    MRR       : {rr_sum/n:6.3f}")
    print()
    print("  [supplement 위치 구간별]  뒤쪽일수록 문서 뒷부분에서 온 발화다")
    for bucket in ("0-4", "5-9", "10+"):
        b = by_pos.get(bucket)
        if not b or not b["n"]:
            continue
        print(f"    위치 {bucket:>4} (n={b['n']:4d}) : "
              f"Recall@1 {b['hit1']/b['n']:6.1%}   Recall@5 {b['hit5']/b['n']:6.1%}")
    print()
    print("  [라우팅 - 사용자에게 실제로 보이는 결과]")
    print(f"    비의료로 오분류(잡담 응답) : {routed_chat/n:6.1%}  ({routed_chat}/{n})"
          f"   * 1위점수 < {app.LOW_CONF_THRESHOLD}")
    print(f"    되묻기(needs_more_info)    : {routed_more_info/n:6.1%}  ({routed_more_info}/{n})")
    print(f"    바로 진단                  : {(n-routed_chat-routed_more_info)/n:6.1%}")
    if top1_scores:
        s = sorted(top1_scores)
        print()
        print(f"  [1위 유사도 분포]  최소 {s[0]:.3f}  25% {s[len(s)//4]:.3f}  "
              f"중앙 {s[len(s)//2]:.3f}  75% {s[3*len(s)//4]:.3f}  최대 {s[-1]:.3f}")
        print(f"    현재 임계값: LOW={app.LOW_CONF_THRESHOLD}  HIGH={app.HIGH_CONF_THRESHOLD}")
    print("=" * 62)

    if args.tune:
        tune(tuning_rows)


def tune(rows) -> None:
    """임계값 후보별로 어떤 결과가 나오는지 표로 보여준다.

    임계값은 인덱싱 방식에 종속된 경험값이라, 인덱스를 바꾸면 그대로 쓸 수 없다.
    감으로 고르지 않도록 숫자를 깔아 준다.
    """
    neg_path = BASE_DIR / "negative_queries.json"
    negatives = []
    if neg_path.exists():
        negatives = json.loads(neg_path.read_text(encoding="utf-8"))["queries"]

    neg_top1 = []
    for q in negatives:
        got = retrieved_diseases(q, app.K_DISEASE)
        if got:
            neg_top1.append(got[0][1])

    print()
    print("=" * 62)
    print("  임계값 재측정")
    print("=" * 62)

    print()
    print("  [LOW_CONF_THRESHOLD] 이 아래면 '비의료 질문' 으로 보고 잡담 응답")
    print("    증상 질의를 잡담으로 보내면(놓침) 최악이고,")
    print("    잡담을 증상으로 보면(오인) 엉뚱한 진단을 내놓는다.")
    print(f"    {'임계값':>8} {'증상질의 놓침':>14} {'비의료 걸러냄':>14}")
    sym = [r[0] for r in rows]
    for t in (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
        miss = sum(1 for s in sym if s < t) / len(sym)
        caught = (sum(1 for s in neg_top1 if s < t) / len(neg_top1)) if neg_top1 else float("nan")
        print(f"    {t:8.2f} {miss:13.1%} {caught:14.1%}")
    if neg_top1:
        ns = sorted(neg_top1)
        print(f"    비의료 질의 1위점수: 최소 {ns[0]:.3f}  중앙 {ns[len(ns)//2]:.3f}  최대 {ns[-1]:.3f}"
              f"  (n={len(ns)})")

    print()
    print("  [HIGH_CONF_THRESHOLD] 이 위 + 격차 조건이면 바로 진단, 아니면 되묻기")
    print("    바로 진단하는 비율을 올리면 되묻기가 줄지만, 그중 틀린 답이 는다.")
    print(f"    {'임계값':>8} {'바로 진단':>12} {'그중 1위 정답률':>16} {'되묻기':>10}")
    for t in (0.70, 0.74, 0.78, 0.80, 0.82, 0.85, 0.90):
        direct = [r for r in rows if r[0] >= t and r[2] >= app.SCORE_DIFF_THRESHOLD]
        if not direct:
            continue
        acc = sum(1 for r in direct if r[1]) / len(direct)
        print(f"    {t:8.2f} {len(direct)/len(rows):11.1%} {acc:16.1%} "
              f"{1 - len(direct)/len(rows):10.1%}")
    print("=" * 62)


if __name__ == "__main__":
    main()
