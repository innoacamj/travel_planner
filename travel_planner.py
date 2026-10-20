"""
국내 여행지 추천 프로그램 (Python 응용: API 활용 미션)

전체 흐름
  날짜 입력
    → [1/3] LLM(Gemini)에게 1차 추천 요청 → JSON으로 받기
    → [2/3] 지도 API(Kakao Local)로 추천 도시의 맛집 검색
    → [3/3] LLM에게 최종 여행 리포트(Markdown) 작성 요청
    → results/ 폴더에 원본 JSON + 리포트 .md 저장

실행 예시
  python travel_planner.py --date "2026-03-15"
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# ------------------------------------------------------------
# 기본 설정
# ------------------------------------------------------------
RESULTS_DIR = Path("results")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
TIMEOUT = 120  # API 응답을 기다리는 최대 시간(초)

# 1차 추천 JSON에 반드시 있어야 하는 키와 타입
REQUIRED_KEYS = {
    "recommended_city": str,
    "weather": str,
    "events": list,
    "reason": str,
}


# ------------------------------------------------------------
# 0. 준비: 입력값 확인 + API 키 확인
# ------------------------------------------------------------
def parse_args():
    """CLI 옵션을 읽고 날짜 형식을 검사한다."""
    parser = argparse.ArgumentParser(
        description="여행 날짜를 입력하면 국내 여행지와 맛집을 추천해 주는 프로그램"
    )
    parser.add_argument(
        "-date", "--date", dest="date", required=True,
        help='여행 날짜 (형식: "YYYY-MM-DD")',
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="(보너스) 저장된 결과를 무시하고 API를 새로 호출",
    )
    args = parser.parse_args()

    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        parser.print_usage()
        print(f'오류: 날짜 형식이 올바르지 않습니다 → "{args.date}" (예: "2026-03-15")')
        sys.exit(1)
    return args


def load_keys():
    """.env 파일 또는 환경변수에서 API 키를 읽는다. 없으면 안내 후 즉시 종료."""
    load_dotenv()
    keys = {
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),
        "KAKAO_REST_API_KEY": os.getenv("KAKAO_REST_API_KEY"),
    }
    missing = [name for name, value in keys.items() if not value]
    if missing:
        print("오류: API 키가 설정되지 않았습니다 →", ", ".join(missing))
        print("설정 방법:")
        print("  1) 이 파일과 같은 폴더에 .env 파일을 만들고 아래처럼 적어 주세요.")
        for name in missing:
            print(f"     {name}=발급받은_키_값")
        print("  2) 자세한 방법은 README.md의 'API 키 설정' 항목을 참고하세요.")
        sys.exit(1)
    return keys


# ------------------------------------------------------------
# 공통 도구: 오류 기록 / 오류 분류 / 파일 저장
# ------------------------------------------------------------
def add_error(errors, step, err_type, message):
    errors.append({"step": step, "type": err_type, "message": message})


def classify_error(e):
    """예외(e)를 보고 오류 종류와 짧은 메시지를 돌려준다."""
    if isinstance(e, requests.exceptions.HTTPError):
        code = e.response.status_code if e.response is not None else None
        if code in (401, 403):
            return "AUTH_ERROR", f"HTTP {code}"
        if code == 429:
            return "QUOTA_ERROR", "HTTP 429"
        return "HTTP_ERROR", f"HTTP {code}"
    if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return "NETWORK_ERROR", type(e).__name__
    if isinstance(e, (KeyError, IndexError, ValueError)):
        return "PARSE_ERROR", str(e)
    return "UNKNOWN_ERROR", str(e)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_cache(path):
    """(보너스) 같은 날짜로 저장된 원본 JSON이 있으면 불러온다."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not data.get("recommendation"):  # 실패했던 실행 결과는 캐시로 쓰지 않음
        return None
    return data


# ------------------------------------------------------------
# LLM 호출 (Gemini REST API, POST 방식)
# ------------------------------------------------------------
def call_gemini(api_key, prompt, want_json=False):
    """Gemini에 질문(prompt)을 보내고 답변 텍스트를 돌려준다."""
    model = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if want_json:
        # JSON 형태로만 답하도록 요청하는 옵션
        body["generationConfig"] = {"responseMimeType": "application/json"}

    res = requests.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=body,
        timeout=TIMEOUT,
    )
    res.raise_for_status()  # 4xx/5xx 응답이면 HTTPError 발생
    parts = res.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


# ------------------------------------------------------------
# [1/3] 1차 추천 (LLM → JSON)
# ------------------------------------------------------------
def build_recommend_prompt(date):
    return f"""당신은 국내 여행 전문가입니다.
여행 날짜: {date}
이 시기에 여행하기 좋은 대한민국 도시 1곳을 추천해 주세요.

반드시 아래 형식의 JSON 하나만 출력하세요. 다른 설명 문장이나 ``` 기호는 쓰지 마세요.
{{
  "recommended_city": "도시 이름 (예: 제주, 강릉)",
  "weather": "해당 시기의 일반적인 날씨 요약 1문장",
  "events": ["행사 또는 축제 후보 (1~3개)"],
  "reason": "추천 근거 2~4문장"
}}"""


def build_retry_prompt(date):
    return f"""앞선 응답을 JSON으로 읽을 수 없었습니다.
다른 말 없이 아래 4개 키만 가진 JSON 객체 하나만 출력하세요.
- recommended_city: 문자열 (대한민국 도시 이름)
- weather: 문자열
- events: 문자열 배열 (1~3개)
- reason: 문자열
여행 날짜: {date}"""


def extract_json(text):
    """LLM 답변에서 JSON을 꺼내고, 필수 키/타입을 검사한다."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("답변에서 JSON 객체를 찾을 수 없음")
    data = json.loads(text[start:end + 1])
    for key, typ in REQUIRED_KEYS.items():
        if not isinstance(data.get(key), typ):
            raise ValueError(f"필수 키 누락 또는 타입 오류: {key}")
    return data


def step1_recommend(api_key, date, errors):
    """1차 추천을 받는다. JSON 파싱 실패 시 1회만 재시도."""
    prompts = [build_recommend_prompt(date), build_retry_prompt(date)]
    for attempt, prompt in enumerate(prompts, start=1):
        try:
            text = call_gemini(api_key, prompt, want_json=True)
            return extract_json(text)
        except (ValueError, KeyError, IndexError) as e:
            add_error(errors, "recommend", "PARSE_ERROR", f"{attempt}차 시도 파싱 실패: {e}")
            if attempt == 1:
                print("    - JSON 파싱 실패 → 필수 키만 다시 요청합니다(재시도 1회).")
        except requests.exceptions.RequestException as e:
            err_type, msg = classify_error(e)
            add_error(errors, "recommend", err_type, msg)
            print(f"    - 오류: LLM 호출 실패({err_type}, {msg})")
            break  # 인증/네트워크 오류는 재시도해도 같으므로 중단
    return None


# ------------------------------------------------------------
# [2/3] 맛집 검색 (Kakao Local REST API, GET 방식)
# ------------------------------------------------------------
def step2_search_restaurants(api_key, city, errors, size=5):
    """추천 도시의 맛집을 검색한다. 실패해도 빈 리스트를 돌려주고 계속 진행."""
    params = {
        "query": f"{city} 맛집",
        "category_group_code": "FD6",  # FD6 = 음식점 카테고리
        "size": size,
    }
    headers = {"Authorization": f"KakaoAK {api_key}"}

    try:
        res = requests.get(KAKAO_URL, headers=headers, params=params, timeout=TIMEOUT)
        res.raise_for_status()
        documents = res.json().get("documents", [])
    except Exception as e:
        err_type, msg = classify_error(e)
        add_error(errors, "place_search", err_type, msg)
        if err_type == "AUTH_ERROR":
            print(f"    - 오류: 인증 실패({msg.split()[-1]}). 키 설정을 확인하세요.")
        else:
            print(f"    - 오류: 장소 검색 실패({err_type}, {msg})")
        print("    - 맛집 섹션은 '데이터 없음'으로 처리하고 계속 진행합니다.")
        return []

    if not documents:
        add_error(errors, "place_search", "EMPTY_RESULT", f"0 results for query={params['query']}")
        print("    - 검색 결과 0건 (재시도하지 않고 다음 단계로 진행)")
        return []

    restaurants = []
    for d in documents:
        restaurants.append({
            "name": d.get("place_name", ""),
            "address": d.get("road_address_name") or d.get("address_name", ""),
            "category": d.get("category_name", ""),
            "url": d.get("place_url", ""),
            "lng": float(d["x"]) if d.get("x") else None,  # 카카오의 x = 경도
            "lat": float(d["y"]) if d.get("y") else None,  # 카카오의 y = 위도
        })
    print(f"    - 맛집 {len(restaurants)}곳 검색 완료")
    return restaurants


# ------------------------------------------------------------
# [3/3] 최종 리포트 (LLM → Markdown)
# ------------------------------------------------------------
def empty_note(errors):
    """맛집이 0건일 때 리포트에 적을 사유."""
    for e in errors:
        if e["step"] == "place_search":
            if e["type"] == "EMPTY_RESULT":
                return "장소 검색 결과 0건"
            return f"장소 검색 API 오류: {e['type']}"
    return "장소 검색 결과 없음"


def build_report_prompt(date, rec, restaurants, note):
    restaurant_text = (
        json.dumps(restaurants, ensure_ascii=False, indent=2) if restaurants else "데이터 없음"
    )
    return f"""당신은 국내 여행 플래너입니다. 아래 데이터만 근거로 여행 리포트를 Markdown으로 작성하세요.

[여행 날짜]
{date}

[1차 추천 정보]
{json.dumps(rec, ensure_ascii=False, indent=2)}

[맛집 목록]
{restaurant_text}

작성 규칙:
- 첫 줄은 "# {date} 국내 여행 추천 리포트"
- 아래 소제목(##)을 이 순서대로 모두 사용: 추천 지역 / 추천 이유 / 날씨 요약 / 행사/축제 / 맛집 추천 / 1일 일정 제안
- 맛집 추천: 목록에 있는 가게만 사용하고 이름, 주소, 카테고리, 링크를 표기
- 맛집 목록이 "데이터 없음"이면 맛집 추천 아래에 "- 데이터 없음 ({note})" 한 줄만 쓰기
- 1일 일정 제안: 오전 / 오후 / 저녁으로 나누어 간단히
- 오류 요약 섹션은 쓰지 마세요 (프로그램이 자동으로 붙입니다)
- Markdown 본문만 출력하고 ``` 기호로 감싸지 마세요"""


def clean_markdown(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]  # 첫 줄(```markdown) 제거
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def build_fallback_report(date, rec, restaurants, note):
    """LLM 리포트 생성이 실패했을 때 쓰는 기본 양식."""
    lines = [
        f"# {date} 국내 여행 추천 리포트",
        "", "## 추천 지역", f"- {rec['recommended_city']}",
        "", "## 추천 이유", rec["reason"],
        "", "## 날씨 요약", rec["weather"],
        "", "## 행사/축제",
    ]
    lines += [f"- {ev}" for ev in rec["events"]] or ["- 정보 없음"]
    lines += ["", "## 맛집 추천"]
    if restaurants:
        for r in restaurants:
            lines.append(f"- **{r['name']}** | {r['category']} | {r['address']} | {r['url']}")
    else:
        lines.append(f"- 데이터 없음 ({note})")
    lines += ["", "## 1일 일정 제안", "- (LLM 리포트 생성 실패로 일정 제안을 생략합니다)"]
    return "\n".join(lines)


def errors_section(errors):
    lines = ["", "## 오류 요약(errors)"]
    if not errors:
        lines.append("- 없음")
    for e in errors:
        lines.append(f"- [{e['step']}] {e['type']}: {e['message']}")
    return "\n".join(lines) + "\n"


def step3_report(api_key, date, rec, restaurants, errors):
    note = empty_note(errors)
    try:
        text = call_gemini(api_key, build_report_prompt(date, rec, restaurants, note))
        report = clean_markdown(text)
        if not report:
            raise ValueError("빈 응답")
        print("    - 리포트 생성 완료")
    except Exception as e:
        err_type, msg = classify_error(e)
        add_error(errors, "report", err_type, msg)
        print(f"    - 오류: 리포트 생성 실패({err_type}). 기본 양식으로 리포트를 만듭니다.")
        report = build_fallback_report(date, rec, restaurants, note)
    return report.rstrip() + "\n" + errors_section(errors)


# ------------------------------------------------------------
# 메인: 전체 순서 실행
# ------------------------------------------------------------
def main():
    args = parse_args()
    keys = load_keys()

    RESULTS_DIR.mkdir(exist_ok=True)
    raw_path = RESULTS_DIR / f"{args.date}_raw.json"
    report_path = RESULTS_DIR / f"{args.date}_travel_plan.md"

    cached = None if args.refresh else load_cache(raw_path)
    if cached:
        print(f"[캐시] {raw_path} 의 저장된 결과를 사용합니다. (1·2단계 API 호출 생략)")
        rec = cached["recommendation"]
        restaurants = cached.get("restaurants", [])
        errors = [e for e in cached.get("errors", []) if e.get("step") != "report"]
    else:
        errors = []

        print("[1/3] 1차 추천 생성 중(LLM)...")
        rec = step1_recommend(keys["GEMINI_API_KEY"], args.date, errors)
        if rec is None:
            save_json(raw_path, {
                "date": args.date, "recommendation": None,
                "restaurants": [], "errors": errors,
            })
            print(f"1차 추천을 받지 못해 종료합니다. 오류 내용은 {raw_path} 를 확인하세요.")
            sys.exit(1)
        print(f'    - recommended_city: "{rec["recommended_city"]}"')

        print("[2/3] 맛집 검색 중(지도/장소 API)...")
        restaurants = step2_search_restaurants(
            keys["KAKAO_REST_API_KEY"], rec["recommended_city"], errors
        )

    print("[3/3] 최종 리포트 생성 중(LLM)...")
    report = step3_report(keys["GEMINI_API_KEY"], args.date, rec, restaurants, errors)

    save_json(raw_path, {
        "date": args.date,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "recommendation": rec,
        "restaurants": restaurants,
        "errors": errors,
    })
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print()
    print(f"완료! {report_path} 를 확인하세요.")
    print(f"      (원본 데이터: {raw_path})")


if __name__ == "__main__":
    main()
