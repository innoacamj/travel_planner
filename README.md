# 국내 여행지 추천 프로그램 (API 활용)

## 1. 프로그램 개요
여행 날짜를 입력하면 아래 3단계를 거쳐 여행 리포트를 만들어 주는 CLI 프로그램입니다.

| 단계 | 사용 API | 하는 일 | 결과 |
|---|---|---|---|
| 1/3 | Google Gemini (POST) | 해당 시기에 좋은 국내 도시 추천 | JSON (도시·날씨·행사·이유) |
| 2/3 | Kakao Local (GET) | 추천 도시의 맛집 5곳 검색 | 맛집 리스트 (0건 가능) |
| 3/3 | Google Gemini (POST) | 1·2단계 결과로 최종 리포트 작성 | Markdown 리포트 |

## 2. 폴더 구성
```
travel_planner/
├─ travel_planner.py   # 메인 프로그램
├─ requirements.txt    # 필요한 라이브러리 목록
├─ .env.example        # API 키 설정 예시 (실제 키 없음)
├─ .gitignore          # .env 파일이 업로드되지 않도록 설정
├─ README.md
└─ results/            # 실행하면 자동 생성
```

## 3. 실행 환경
- Python 3.10 이상
- 터미널(macOS/Linux) 또는 PowerShell(Windows)

## 4. 설치 방법
```bash
pip install -r requirements.txt
```

## 5. API 키 설정
API 키는 **코드에 직접 쓰지 않고** `.env` 파일(또는 환경변수)로 관리합니다.

1. `.env.example` 파일을 복사해 이름을 `.env` 로 바꿉니다.
2. `.env` 안에 발급받은 키를 입력합니다.
   ```
   GEMINI_API_KEY=발급받은_키
   KAKAO_REST_API_KEY=발급받은_키
   ```
3. (`.env` 대신) 환경변수로 설정해도 됩니다. 현재 터미널 창에만 적용됩니다.
   - macOS/Linux: `export GEMINI_API_KEY="발급받은_키"`
   - Windows PowerShell: `$env:GEMINI_API_KEY="발급받은_키"`
3. (`.env` 대신) 환경변수로 설정해도 됩니다. 현재 터미널 창에만 적용됩니다.
   - macOS/Linux: `export GEMINI_API_KEY="발급받은_키"`
   - Windows PowerShell: `$env:GEMINI_API_KEY="발급받은_키"`
4. (선택) 사용할 Gemini 모델을 바꾸려면 `.env`에 `GEMINI_MODEL=모델명`을 추가합니다. 기본값은 `gemini-flash-lite-latest`입니다.

### 키 발급처
- Gemini: Google AI Studio (https://aistudio.google.com) → API 키 발급
- Kakao: Kakao Developers (https://developers.kakao.com) → 내 애플리케이션 → 앱 추가 → **REST API 키** 사용
  - 403 오류가 나면 앱 설정에서 카카오맵(로컬) API 사용 설정이 켜져 있는지 확인

## 6. 실행 방법
```bash
python travel_planner.py --date "2026-03-15"
# 또는
python travel_planner.py -date "2026-03-15"
```
- (보너스) 같은 날짜로 다시 실행하면 저장된 결과를 재사용해 1·2단계 API 호출을 생략합니다.
- 새로 호출하고 싶으면 `--refresh` 옵션을 붙입니다.

## 7. 결과물 확인 방법
실행이 끝나면 `results/` 폴더에 두 파일이 생깁니다.

| 파일 | 내용 |
|---|---|
| `results/YYYY-MM-DD_raw.json` | 원본 데이터: 1차 추천 JSON, 맛집 검색 결과, 오류 목록(errors) |
| `results/YYYY-MM-DD_travel_plan.md` | 최종 여행 리포트 |

## 8. 오류 처리 정책
| 상황 | 프로그램 동작 |
|---|---|
| 날짜 형식 오류 | 사용법 출력 후 종료 |
| API 키 미설정 | 즉시 종료 + 설정 방법 안내 |
| LLM JSON 파싱 실패 | 필수 키만 다시 요청하여 1회만 재시도 |
| 지도 API 실패(인증/쿼터/네트워크) 또는 0건 | 맛집 = "데이터 없음" 처리 후 계속 진행 |
| 리포트 생성 실패 | 기본 양식으로 리포트 작성 |
| 모든 오류 | `errors` 목록에 기록 → JSON과 리포트에 요약 |

## 9. ⚠️ API 키 유출 주의사항
- API 키를 코드, README, 결과 파일, 캡처 화면에 **절대** 넣지 않습니다.
- `.env` 파일은 제출·공유하지 않습니다. (`.gitignore`에 등록되어 있음)
- 키가 노출되었다면 즉시 발급처에서 해당 키를 삭제하고 새로 발급받습니다.
