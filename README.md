# Sillage · 향의 아틀리에

> 향이 지나간 자리에 남는 것 — *The trace a scent leaves*

향을 잘 몰라도 노트를 골라 섞거나, 장면을 말하거나, 사진을 올리면
**병 속 액체와 배경의 색이 함께 바뀌고**, 실제로 노트가 겹치는 시판 향수를 근거와 함께 추천하는 교육용 웹 서비스입니다.

## 주요 기능

| 기능 | 설명 |
| --- | --- |
| 스크롤 스토리 | 노트란? → 탑·미들·베이스 → 향의 계열 → 향료 → 농도 → 시향하는 법을 순서대로 배워요. 스크롤에 맞춰 글과 병, 배경 색이 움직여요. |
| 노트 블렌딩 | 단계별 10개, 총 30개 노트(실사 재료 사진)에서 단계마다 최대 3개를 골라 섞어요. 색은 OKLab 공간에서 섞여 병 속에 층을 이뤄요. |
| AI 큐레이션 (RAG) | 실제 상품 페이지에서 검증한 향수 55종 DB에서 노트가 겹치는 후보를 찾고, LLM이 그 후보 안에서만 3개를 골라 이유를 써요. 겹치는 노트는 코드가 계산해요. |
| 대화로 노트 바꾸기 | "너무 달아요, 비 온 뒤 숲처럼"이라고 말하면 LLM이 지금 선택을 짚고 노트를 직접 바꿔요. 실제 변경은 −/+ 표시로 보여 줘요. |
| 사진으로 향 찾기 | 사진을 올리면 장면의 색, 빛, 계절을 읽어 노트를 골라요. 사진은 저장하지 않아요. |
| 효과음 | 실제 녹음한 유리잔, 크리스털, 물소리. 기본은 꺼짐이고 오른쪽 위 *Sound* 버튼으로 켜요. |

## 바로 실행하기 (Windows)

**Python 3.10 이상**만 있으면 됩니다. 화면은 이미 빌드되어 `dist/`에 들어 있어요.

1. 폴더 안의 **`실행.bat`**을 더블클릭해요. 처음 한 번은 필요한 패키지를 설치하느라 1~2분 걸려요.
2. 브라우저에서 **http://127.0.0.1:8765** 가 열려요.

직접 실행하려면 아래 명령을 차례로 입력해요.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8765
```

macOS·Linux에서는 `sh run.sh`를 실행해요.

## OpenAI API 키 (선택)

키가 없어도 **데모 모드**로 화면, 노트 블렌딩, 규칙 기반 추천이 모두 동작해요. LLM 상담, AI 큐레이션, 사진 분석을 쓰려면 둘 중 하나를 해요.

- **화면에서 입력 (간편)**: 상담 화면 오른쪽 위 **Demo** 버튼 → OpenAI 키(`sk-...`) 입력 → 저장. 키는 그 브라우저 탭에만 보관되고, 탭을 닫으면 지워져요. 서버는 키를 저장하거나 기록하지 않고 OpenAI 호출에만 써요.
- **`.env` 파일**: `.env.example`을 `.env`로 복사하고 `LLM_API_KEY`를 채운 뒤 서버를 다시 켜요.

사용 모델은 `gpt-4o-mini`(Responses API)와 `text-embedding-3-small`이에요. 한 번 상담할 때 드는 비용은 1센트에도 한참 못 미쳐요.

## 동작 원리

```
[브라우저 React]  노트 선택 · 대화 · 사진
       │
       ▼
[FastAPI server.py]
  ├─ /api/blend      규칙 점수로 즉시 추천
  ├─ /api/recommend  RAG: rag.py가 노트 겹침(단계 가중) + 계열 + 임베딩 유사도로 후보 8개
  │                  → gpt-4o-mini가 후보 id 안에서만 3개 선택 + 이유(JSON 스키마 enum으로 강제)
  └─ /api/chat       대화·사진 → gpt-4o-mini가 노트 변경(changes)을 구조화 출력 → 서버가 적용
       │
       ▼
[data/perfumes.json]  검증된 향수 55종 (노트마다 출처 URL)
```

**향수 DB를 만든 방법** (`scripts/build_catalog.py`)
1. 웹 검색으로 각 향수의 공식(또는 대형 판매처) 상품 페이지를 찾아요.
2. 페이지를 직접 내려받아 **본문에서만** 노트를 추출해요.
3. 추출된 노트가 원문에 실제로 있는지 코드로 다시 대조하고, 없는 노트는 버려요.

봇 차단으로 받을 수 없는 페이지는 브라우저로 노트 부분을 저장해(`data/pages/`) 같은 검증을 거쳤어요. LLM만으로 추천하면 실제와 다른 노트를 지어내는 문제가 있어서 이렇게 설계했어요.

## 폴더 구조

```
server.py            FastAPI 서버 (API + 빌드된 화면 제공)
rag.py               향수 검색: 노트 사전, 점수, 임베딩
blend-notes.json     노트 30개 (이름, 느낌, 색, 계열)
data/perfumes.json   검증된 향수 55종
data/pages/          브라우저로 저장한 원문 조각 (검증 입력)
src/                 React 화면 (main.jsx, 셰이더 배경, 액체, 효과음)
public/notes/        노트 재료 사진 (배경 제거 webp)
public/sounds/       효과음
scripts/             DB 구축, 노트 사진 수집·배경 제거 스크립트
dist/                빌드된 화면 (npm run build 결과)
```

화면을 수정하려면 Node.js 20 이상에서 `npm ci` 후 `npm run build`를 실행해요.

## 자료 출처와 라이선스

- **노트 재료 사진 30장**: Wikimedia Commons (CC0, 퍼블릭 도메인, CC BY, CC BY-SA). 배경 제거, 자르기, 크기 조정을 했어요. 사진별 저작자와 라이선스는 `public/notes/CREDITS.json`과 상담 화면 맨 아래 '재료 사진 출처'에서 볼 수 있어요.
- **효과음 4개**: Freesound, 모두 CC0 1.0. 목록은 `public/sounds/CREDITS.json`에 있어요.
- **향수 노트 정보**: 각 브랜드 공식 사이트와 판매처 상품 페이지. 향수마다 출처 URL을 `data/perfumes.json`의 `source`에 남겼어요. 브랜드명과 향수명은 각 브랜드의 상표예요.
- **폰트**: Cormorant Garamond, Noto Serif KR (Google Fonts, OFL), Pretendard (OFL).
- **라이브러리**: React, Vite, GSAP, Lenis, lottie-web, Meta Astryx(입력창·버튼), FastAPI.

## 알려진 한계

- 일부 향수(조말론, 메종 마르지엘라, 디올 등)는 공식 페이지에 대표 노트 2~3개만 공개되어 있어 DB에도 그만큼만 있어요.
- 노트를 판단하는 질은 gpt-4o-mini 수준이에요. LLM이 답변에서 노트의 단계를 잘못 말할 때가 있지만, 실제 적용은 올바른 단계로 되고 화면의 −/+ 표시가 정확한 결과를 보여 줘요.
- 시향 추천은 노트 겹침을 기준으로 한 참고용이에요. 실제 향은 피부와 환경에 따라 달라요.
