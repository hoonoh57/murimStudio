1. docs/PROJECT_OVERVIEW.md — 프로젝트 전체 개요

Copy# ⚔️ 무협 팩토리 (MurimStudio) — 프로젝트 개요

> AI 기반 웹툰/웹소설 유튜브 콘텐츠 자동 생산 파이프라인

## 1. 프로젝트 목표

웹툰·웹소설 원작의 유튜브 리캡 영상(롱폼) 및 YouTube Shorts(숏폼)를
**트렌드 수집 → 스크립트 생성 → TTS → 이미지 → 영상 조립 → 업로드**까지
하나의 대시보드에서 자동화하는 시스템.

## 2. 기술 스택

| 분류 | 기술 |
|---|---|
| **프레임워크** | Python 3.13 + NiceGUI (웹 UI) |
| **AI / LLM** | Google Gemini, Anthropic Claude (LLM), Pollinations.ai FLUX (이미지) |
| **TTS** | Microsoft Edge TTS (20+ 음성 모델, 다국어) |
| **영상** | FFmpeg (슬라이드쇼, Ken Burns, ASS 자막 번인) |
| **DB** | SQLite (aiosqlite) — `app.db` |
| **배포** | Docker / docker-compose (선택) |

## 3. 디렉토리 구조

murimStudio/ ├── main.py # 엔트리포인트 (NiceGUI 서버) ├── app.db # SQLite 데이터베이스 ├── requirements.txt ├── Dockerfile / docker-compose.yml │ ├── app/ │ ├── config.py # 환경 설정 │ ├── db.py # DB 초기화 & 커넥션 │ ├── scheduler.py # 백그라운드 태스크 (트렌드 수집) │ │ │ ├── models/ │ │ └── script.py # 데이터 모델 │ │ │ ├── pages/ # UI 패널 (NiceGUI) │ │ ├── dashboard.py # 📊 대시보드 │ │ ├── trend_scout.py # 🔍 트렌드 │ │ ├── trend_detail.py # 트렌드 상세 │ │ ├── script_factory.py # ✍️ 스크립트 생성/번역 │ │ ├── script_detail.py # 스크립트 상세/편집 │ │ ├── tts_test.py # 🔊 TTS │ │ ├── image_panel.py # 🎨 이미지 생성 │ │ ├── video_panel.py # 🎬 영상 조립 │ │ ├── shorts_panel.py # 📱 숏츠 제작 │ │ ├── asset_browser.py # 📦 제작물 브라우저 │ │ ├── channel_hub.py # 📺 채널 관리 │ │ ├── cost_tracker.py # 💰 비용 추적 │ │ └── media_factory.py # 미디어 통합 (레거시) │ │ │ └── services/ # 비즈니스 로직 │ ├── trend_scout.py # 트렌드 수집 (네이버/Reddit/MAL) │ ├── reference_collector.py # 작품 레퍼런스 수집 │ ├── llm_client.py # LLM 클라이언트 (Gemini/Claude) │ ├── script_factory.py # 스크립트 생성/번역 엔진 │ ├── tts_service.py # Edge TTS 서비스 │ ├── image_generator.py # Pollinations.ai 이미지 생성 │ ├── video_assembler.py # FFmpeg 영상 조립 │ ├── shorts_maker.py # YouTube Shorts 제작 │ ├── channel_service.py # 채널 관리 │ ├── cost_service.py # 비용 집계 │ ├── media_service.py # 미디어 통합 │ └── utils.py # 공통 유틸 │ ├── static/images/ # 생성된 이미지 │ ├── script_10/ # 스크립트별 폴더 │ ├── script_14/ │ ├── script_18/ │ ├── script_19/ │ └── unassigned/ # 미분류 │ ├── output/ │ ├── audio/ # TTS MP3 │ ├── video/ # 롱폼 영상 MP4 │ └── shorts/ # 숏츠 MP4 │ └── docs/ # 프로젝트 문서 ├── PROJECT_OVERVIEW.md # 이 파일 └── todo_2026-03-19.md # 일일 TODO


## 4. 파이프라인 흐름

[1] 트렌드 수집 → 네이버 웹툰, Reddit, MAL에서 인기작 수집 ↓ AI가 점수 매기고 랭킹 [2] 스크립트 생성 → LLM이 리캡 대본 작성 (레퍼런스 자동 수집) ↓ 다국어 번역 (ko/en/id/th) [3] TTS 음성 생성 → Edge TTS, 20+ 음성 모델 ↓ 속도/피치 조절 [4] AI 이미지 생성 → Pollinations.ai FLUX 모델 ↓ 스크립트별 폴더 관리, 장르별 스타일 [5] 영상 조립 → FFmpeg 슬라이드쇼 + 페이드 전환 ↓ [6] 숏츠 제작 → 9:16 세로, Ken Burns 효과, ASS 자막 ↓ [7] 제작물 관리 → 스크립트별 이미지/오디오/영상 통합 브라우저 ↓ [8] 유튜브 업로드 → (예정)


## 5. DB 스키마 (현재)

### projects
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INTEGER PK | |
| title | TEXT | 작품명 |
| episodes | TEXT | 회차 범위 |
| language | TEXT | 원본 언어 |
| status | TEXT | pending/active |
| created_at | TEXT | |
| updated_at | TEXT | |

### scripts
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INTEGER PK | |
| project_id | INTEGER FK | projects.id |
| language | TEXT | ko/en/id/th |
| content | TEXT | 스크립트 전문 |
| status | TEXT | generated/error |
| cost_usd | REAL | LLM 비용 |
| created_at | TEXT | |
| updated_at | TEXT | |

### trends
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INTEGER PK | |
| title | TEXT | 작품명 |
| source | TEXT | naver/reddit/mal |
| score | REAL | AI 점수 |
| data | TEXT (JSON) | 상세 데이터 |
| created_at | TEXT | |

## 6. UI 탭 구성 (v1.6.1)

| 탭 | 기능 | 파일 |
|---|---|---|
| 📊 대시보드 | 프로젝트 현황, 비용 요약 | dashboard.py |
| 🔍 트렌드 | 실시간 인기작 수집/랭킹 | trend_scout.py |
| ✍️ 스크립트 | AI 대본 생성, 번역 | script_factory.py |
| 🔊 TTS | 음성 생성, 미리듣기, 모델 비교 | tts_test.py |
| 🎨 이미지 | AI 이미지 생성, 프롬프트 편집 | image_panel.py |
| 🎬 영상 | 이미지+오디오 → MP4 조립 | video_panel.py |
| 📱 숏츠 | YouTube Shorts 제작 | shorts_panel.py |
| 📦 제작물 | 전체 자산 브라우저 | asset_browser.py |
| 📺 채널 | 유튜브 채널 관리 | channel_hub.py |
| 💰 비용 | LLM/API 비용 추적 | cost_tracker.py |

## 7. 버전 히스토리

| 버전 | 날짜 | 주요 내용 |
|---|---|---|
| v1.0 | 2026-03 | 초기 구조: 트렌드, 스크립트, 대시보드 |
| v1.1 | 2026-03 | LLM 클라이언트, 레퍼런스 수집기 |
| v1.2 | 2026-03 | TTS 서비스 (Edge TTS, 3모델) |
| v1.3 | 2026-03 | 이미지 생성 (Pollinations.ai), 영상 조립 (FFmpeg) |
| v1.4 | 2026-03 | TTS 확장 (12→20 모델), 이미지 15장 확장, 나레이션 정제 |
| v1.5 | 2026-03 | 제작물 브라우저 (asset_browser) |
| v1.6 | 2026-03 | 숏츠 패널, 장르별 이미지 스타일, Ken Burns 효과 |
| v1.6.1 | 2026-03-19 | 숏츠 FFmpeg 필터 수정, 폴백 클립, 이벤트 핸들러 수정 |

## 8. 환경 변수 (.env)

```env
GEMINI_API_KEY=          # Google Gemini API
CLAUDE_API_KEY=          # Anthropic Claude API (선택)
POLLINATIONS_API_KEY=    # Pollinations.ai (선택, 없어도 동작)
STORAGE_SECRET=          # NiceGUI 세션 시크릿

## 9. 실행 방법
Copy# 의존성 설치
pip install -r requirements.txt

# FFmpeg 필요 (시스템 PATH에 등록)
# https://ffmpeg.org/download.html

# 실행
python main.py
# → http://localhost:8080

## 10. 알려진 이슈
Reddit 403 — 트렌드 수집 시 Reddit API가 User-Agent 없이 차단됨
LLM JSON 파싱 — 대시보드 로드 시 간헐적 JSON 파싱 에러
숏츠/롱폼 미분리 — 스크립트 생성 시 포맷(숏츠/롱폼) 선택 불가, 이미지 해상도 분기 없음
장르 하드코딩 — SYSTEM_PROMPT가 무협 전용, 다른 장르 지원 제한적