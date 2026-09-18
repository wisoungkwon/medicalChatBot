# -*- coding: utf-8 -*-
"""
검색 평가셋을 만든다.

질병 JSON 의 `증상.supplement` 는 질병당 10~20개의 **사용자 말투 발화**다
("요즘 너무 피곤하고 밥맛도 없는데, ..."). 발화마다 어느 질병의 것인지가
이미 정해져 있으므로, 그대로 (질의, 정답) 쌍이 된다.

확인한 것:
  - 총 1,920개 발화 (92개 질병이 20개, 8개 질병이 10개)
  - 두 질병에 겹치는 발화 0건  -> 정답이 모호하지 않다
  - 병명 중복 0건

**평가셋은 인덱싱 방식과 무관해야 한다.** 그래서 "이 발화가 지금 인덱스에
들어갔는지" 같은 정보는 넣지 않고, supplement 안에서의 위치(`position`)만
기록한다. 문서를 조립할 때 supplement 가 앞에서부터 들어가므로, 위치가
뒤일수록 현재 방식에서는 인덱싱될 가능성이 낮다. 인덱싱 방식을 바꾸면
그 관계가 달라지는데, 위치 자체는 변하지 않으므로 전후 비교가 가능하다.

주의 - 이 평가셋의 한계:
  질의로 쓰는 발화가 색인 대상 문서 안에도 그대로 들어 있다(누설). 따라서
  점수는 실제 사용자가 다른 말로 물었을 때보다 낙관적이다. 절대값보다
  **같은 평가셋에서의 전후 비교**와 **위치 구간별 격차**를 보는 용도다.

실행:
  python Flask_API/eval/build_eval_set.py
"""
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
JSON_FOLDER = Path(
    os.getenv("JSON_FOLDER_ABS", str(BASE_DIR.parent / "json_diseases_final_ver"))
)
OUT = BASE_DIR / "eval_set.json"


def main() -> None:
    items = []
    diseases = []

    for filename in sorted(f for f in os.listdir(JSON_FOLDER) if f.endswith(".json")):
        with open(JSON_FOLDER / filename, encoding="utf-8") as f:
            data = json.load(f)

        disease = (data.get("병명") or "").strip()
        if not disease:
            continue
        diseases.append(disease)

        supplement = (data.get("증상") or {}).get("supplement") or []
        for position, raw in enumerate(supplement):
            text = str(raw).strip()
            if not text or text == "None":
                continue
            items.append(
                {
                    "query": text,
                    "disease": disease,
                    "file": filename,
                    "position": position,
                }
            )

    payload = {
        "description": "질병 JSON 의 증상.supplement 발화를 (질의, 정답 병명) 으로 쓴 검색 평가셋",
        "source": str(JSON_FOLDER.name),
        "disease_count": len(diseases),
        "query_count": len(items),
        "items": items,
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"질병 {len(diseases)}건, 질의 {len(items)}건 -> {OUT}")


if __name__ == "__main__":
    main()
