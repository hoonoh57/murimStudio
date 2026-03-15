무협 다국어 유튜브 자동화 — 마스터 컨트롤 UI 설계
기술 스택 선정
┌─────────────────────────────────────────────────┐
│  추천 스택: FastAPI (백엔드) + NiceGUI (프론트)    │
│                                                 │
│  왜?                                            │
│  ├─ 100% 파이썬만으로 풀스택 완성                 │
│  ├─ JavaScript/React 몰라도 됨                   │
│  ├─ 실시간 상태 업데이트 (웹소켓 내장)             │
│  ├─ 비동기(async) 지원으로 API 병렬 호출 가능      │
│  └─ 1인 운영자가 유지보수하기 가장 쉬움            │
│                                                 │
│  대안: Reflex (더 예쁜 UI, 러닝커브 약간 높음)     │
│  대안: Streamlit (가장 쉽지만 커스텀 한계)         │
└─────────────────────────────────────────────────┘
전체 시스템 아키텍처
브라우저 (어디서든 접속)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│                  🖥️ 마스터 UI (NiceGUI)                   │
│                  http://localhost:8080                    │
│                                                          │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
│  │대시보드││트렌드 ││스크립트││미디어 ││채널관리││비용   │ │
│  │ 홈   ││스카우트││ 공장  ││ 공장  ││ 허브  ││트래커 │ │
│  └──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘ │
│     │       │       │       │       │       │      │
└─────┼───────┼───────┼───────┼───────┼───────┼──────┘
      │       │       │       │       │       │
      ▼       ▼       ▼       ▼       ▼       ▼
┌──────────────────────────────────────────────────────────┐
│              ⚙️ FastAPI 백엔드 엔진                        │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ 작업 큐   │ │ API 게이트│ │ DB       │ │ 파일 저장소│   │
│  │ (Celery/  │ │ 웨이      │ │(SQLite/  │ │ (로컬/    │   │
│  │  RQ)      │ │          │ │ Postgres)│ │  S3)     │   │
│  └─────┬────┘ └─────┬────┘ └─────┬────┘ └─────┬────┘   │
│        │            │            │            │         │
└────────┼────────────┼────────────┼────────────┼─────────┘
         │            │            │            │
         ▼            ▼            ▼            ▼
┌──────────────────────────────────────────────────────────┐
│              🌐 외부 API 연결                              │
│                                                          │
│  Claude   ElevenLabs  Midjourney  YouTube   웹 크롤러    │
│  API      API         API        Data API               │
│  (스크립트) (음성/더빙)  (이미지)    (업로드)   (트렌드)     │
└──────────────────────────────────────────────────────────┘
화면별 상세 설계
📊 TAB 1: 대시보드 (홈)
열면 바로 보이는 "작전 상황판"입니다.

┌─────────────────────────────────────────────────────────┐
│  🏠 무협 팩토리 — 대시보드                     [2026-03-15] │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐      │
│  │ 📺 오늘 생산  │ │ 📤 업로드 대기 │ │ 💰 이번 달 비용│      │
│  │             │ │             │ │             │      │
│  │   12편/9편   │ │    3편      │ │  ₩187,200   │      │
│  │  (목표/완료)  │ │  (자동예약됨)  │ │  (예산 대비 87%)│      │
│  └─────────────┘ └─────────────┘ └─────────────┘      │
│                                                         │
│  ┌─────────────────────────────────────────────┐       │
│  │  📈 채널별 실시간 현황                         │       │
│  │                                             │       │
│  │  🇺🇸 EN채널    12.3K구독  +127오늘  ▲2.1%    │       │
│  │  🇰🇷 KR채널     8.7K구독   +89오늘  ▲1.8%    │       │
│  │  🇮🇩 ID채널    21.5K구독  +312오늘  ▲3.4%    │       │
│  │  🇹🇭 TH채널     5.2K구독   +67오늘  ▲2.7%    │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  ┌──────────────────┐ ┌────────────────────────┐       │
│  │ 🔄 파이프라인 상태  │ │ 🏆 이번 주 TOP 영상      │       │
│  │                  │ │                        │       │
│  │ ● 트렌드 수집  ✅  │ │ 1. 화산귀환 51~100화    │       │
│  │ ● 스크립트 #47 🔄 │ │    EN 85K조회 / ID 127K │       │
│  │ ● 음성생성 #46 🔄 │ │                        │       │
│  │ ● 이미지 #45  ⏳  │ │ 2. 전독시 무림편 요약    │       │
│  │ ● 편집 #44    ✅  │ │    EN 52K조회 / KR 41K  │       │
│  │ ● 업로드 #44  ✅  │ │                        │       │
│  └──────────────────┘ └────────────────────────┘       │
│                                                         │
│  ┌─────────────────────────────────────────────┐       │
│  │  ⚡ 빠른 실행                                  │       │
│  │                                             │       │
│  │  [🚀 새 영상 제작 시작]  [📋 오늘의 큐 확인]    │       │
│  │  [🔄 전체 파이프라인 실행]  [📊 주간 리포트]     │       │
│  └─────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
핵심 파이썬 구조:

Copy# app/pages/dashboard.py

from nicegui import ui
from app.services.youtube_api import get_channel_stats
from app.services.pipeline import get_pipeline_status
from app.services.cost_tracker import get_monthly_cost

async def dashboard_page():
    # 상단 KPI 카드
    with ui.row().classes('w-full gap-4'):
        with ui.card().classes('flex-1'):
            ui.label('📺 오늘 생산').classes('text-sm text-gray-500')
            stats = await get_daily_production()
            ui.label(f'{stats["completed"]}/{stats["target"]}편')
                .classes('text-3xl font-bold')

        with ui.card().classes('flex-1'):
            ui.label('📤 업로드 대기').classes('text-sm text-gray-500')
            queue = await get_upload_queue()
            ui.label(f'{len(queue)}편').classes('text-3xl font-bold')

        with ui.card().classes('flex-1'):
            ui.label('💰 이번 달 비용').classes('text-sm text-gray-500')
            cost = await get_monthly_cost()
            ui.label(f'₩{cost:,.0f}').classes('text-3xl font-bold')

    # 채널 현황 테이블 (1분마다 자동 새로고침)
    channel_table = ui.table(
        columns=[...],
        rows=await get_all_channel_stats()
    )
    ui.timer(60.0, lambda: channel_table.update_rows(
        get_all_channel_stats()
    ))
Copy
🔍 TAB 2: 트렌드 스카우트
어떤 무협 작품을 리캡할지 AI가 추천하는 화면입니다.

┌─────────────────────────────────────────────────────────┐
│  🔍 트렌드 스카우트                                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  자동 수집 주기: [매 6시간 ▼]  마지막 수집: 14:30        │
│  [🔄 지금 수집하기]                                      │
│                                                         │
│  ┌─────────────────────────────────────────────┐       │
│  │  🏆 이번 주 추천 작품 (AI 분석)                 │       │
│  │                                             │       │
│  │  순위  작품명          점수   근거              │       │
│  │  ──────────────────────────────────────     │       │
│  │  1️⃣   화산귀환 51~100화  95점  네이버 1위+      │       │
│  │       [리캡하기▶]              YouTube검색↑38% │       │
│  │                                             │       │
│  │  2️⃣   북검전기 시즌2    88점  Reddit 핫토픽+    │       │
│  │       [리캡하기▶]              경쟁채널 리캡無  │       │
│  │                                             │       │
│  │  3️⃣   나혼렙 시즌3 예고  85점  MAL 트렌딩 1위+ │       │
│  │       [리캡하기▶]              글로벌 검색↑220%│       │
│  │                                             │       │
│  │  4️⃣   무림세가 장천재    79점  카카오 신작TOP+  │       │
│  │       [리캡하기▶]              3040남성 타겟   │       │
│  │                                             │       │
│  │  5️⃣   선협귀환기        72점  중국풍 트렌드+   │       │
│  │       [리캡하기▶]              동남아 인기↑    │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  ┌──────────────────┐ ┌────────────────────────┐       │
│  │ 📊 키워드 트렌드   │ │ 🌏 국가별 인기 작품      │       │
│  │                  │ │                        │       │
│  │ "murim" ▲ 38%    │ │ 🇺🇸 Solo Leveling S3   │       │
│  │ "화산귀환" ▲ 22%  │ │ 🇮🇩 Hwasan Gwihwan     │       │
│  │ "regression      │ │ 🇰🇷 화산귀환             │       │
│  │  manhwa" ▲ 15%   │ │ 🇹🇭 Return of Mount Hua │       │
│  └──────────────────┘ └────────────────────────┘       │
│                                                         │
│  ┌─────────────────────────────────────────────┐       │
│  │  📝 수동 추가                                  │       │
│  │  작품명: [_______________]                     │       │
│  │  회차범위: [__]화 ~ [__]화                      │       │
│  │  우선순위: [높음 ▼]                             │       │
│  │  [+ 큐에 추가하기]                              │       │
│  └─────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
핵심 파이썬 구조:

Copy# app/services/trend_scout.py

import httpx
from anthropic import AsyncAnthropic

class TrendScout:
    def __init__(self):
        self.claude = AsyncAnthropic()
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")

    async def collect_all_sources(self):
        """모든 소스에서 병렬로 트렌드 수집"""
        results = await asyncio.gather(
            self.scrape_naver_webtoon_ranking(),
            self.scrape_kakao_webtoon_ranking(),
            self.search_youtube_trending("murim manhwa recap"),
            self.search_youtube_trending("무협 웹툰 리뷰"),
            self.scrape_reddit_manhwa_hot(),
            self.scrape_myanimelist_trending(),
        )
        return self.merge_results(results)

    async def ai_rank_topics(self, raw_data: list) -> list:
        """Claude로 최적 리캡 대상 순위 매기기"""
        response = await self.claude.messages.create(
            model="claude-haiku-4-5-20250315",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": f"""다음 웹툰/만화 트렌드 데이터를 분석하여
                유튜브 리캡 영상으로 만들었을 때 가장 조회수가 
                높을 작품 TOP 5를 추천해줘.

                평가 기준:
                - 현재 검색량 트렌드 (40%)
                - 경쟁 채널의 리캡 유무 (30%)
                - 동남아+영어권 인지도 (20%)  
                - 스토리 리캡 적합성 (10%)

                데이터: {json.dumps(raw_data, ensure_ascii=False)}

                JSON 형식으로 응답:
                [{{"title": "", "score": 0, "reason": "", 
                  "episode_range": "", "target_audience": ""}}]"""
            }]
        )
        return json.loads(response.content[0].text)
Copy
✍️ TAB 3: 스크립트 공장
대본 생성부터 번역까지의 전 과정을 관리합니다.

┌─────────────────────────────────────────────────────────┐
│  ✍️ 스크립트 공장                                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─ 새 스크립트 생성 ──────────────────────────────┐    │
│  │                                                │    │
│  │  작품: [화산귀환 ▼]     회차: [51]화 ~ [100]화   │    │
│  │  길이: [10]분   스타일: [긴장감+감동 ▼]          │    │
│  │  언어: ☑영어 ☑한국어 ☑인도네시아어 ☑태국어       │    │
│  │                                                │    │
│  │  AI 모델: [Claude Haiku 4.5 — $0.013/편 ▼]     │    │
│  │                                                │    │
│  │  [🤖 AI 스크립트 생성]  예상 비용: ₩78          │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─ 스크립트 에디터 ──────────────────────────────┐    │
│  │                                                │    │
│  │  📄 화산귀환 51~100화 리캡 (EN) — v2            │    │
│  │  상태: [✅생성완료] → [🔄검수중]                  │    │
│  │                                                │    │
│  │  ┌─────────────────────────────────────┐      │    │
│  │  │ [HOOK - 0:00~0:05]                  │      │    │
│  │  │ "A sword sect that was laughed at   │      │    │
│  │  │  by the entire Murim... just        │      │    │
│  │  │  produced the greatest swordsman    │      │    │
│  │  │  in history."                       │      │    │
│  │  │                                     │      │    │
│  │  │ [SCENE 1 - 0:05~1:30]              │      │    │
│  │  │ 🖼️이미지 프롬프트: "young swordsman │      │    │
│  │  │  standing on mountain peak..."      │      │    │
│  │  │ 🎵BGM: tension_building_01          │      │    │
│  │  │                                     │      │    │
│  │  │ After fifty episodes of grueling... │      │    │
│  │  │ ▎← 여기를 직접 수정 (인간 터치)       │      │    │
│  │  └─────────────────────────────────────┘      │    │
│  │                                                │    │
│  │  [💾 저장] [🌏 번역 시작] [👁️ 미리보기] [✅ 승인] │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─ 번역 상태 ────────────────────────────────────┐    │
│  │                                                │    │
│  │  🇺🇸 EN 원본    ✅ 완료   2,847 단어            │    │
│  │  🇰🇷 KR 번역    ✅ 완료   1,923 글자  [편집]    │    │
│  │  🇮🇩 ID 번역    🔄 진행중  67%...              │    │
│  │  🇹🇭 TH 번역    ⏳ 대기                        │    │
│  │                                                │    │
│  │  번역 비용: ₩47 (Claude Haiku)                 │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  ┌─ 스크립트 큐 ──────────────────────────────────┐    │
│  │  #47 화산귀환 51~100   🔄 검수중    15분전       │    │
│  │  #46 북검전기 S2 1~30  ✅ 승인완료   2시간전      │    │
│  │  #45 전독시 무림편      ✅ 음성생성중  3시간전      │    │
│  │  #44 나혼렙 S3 예고    ✅ 업로드완료  5시간전      │    │
│  └────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
핵심 파이썬 구조:

Copy# app/services/script_factory.py

from anthropic import AsyncAnthropic
from app.models.script import Script, ScriptStatus
from app.db import database

class ScriptFactory:
    
    SYSTEM_PROMPT = """당신은 무협 웹툰 유튜브 리캡 전문 작가입니다.
    규칙:
    - 첫 5초 안에 가장 충격적인 장면으로 시작 (훅)
    - 매 2분마다 서스펜스 포인트 배치
    - 무림 용어는 괄호로 영어 설명 추가
    - 각 장면마다 [이미지 프롬프트]와 [BGM 분위기] 태그 포함
    - 마지막 10초는 다음 영상 유도 클리프행어
    - 전체 {duration}분 분량, 약 {word_count}단어"""

    async def generate(self, title: str, episodes: str, 
                       duration: int = 10, style: str = "tension") -> Script:
        
        # 1단계: 원작 줄거리 수집
        plot_data = await self.fetch_plot_summary(title, episodes)
        
        # 2단계: AI 스크립트 생성
        word_count = duration * 150  # 분당 약 150단어
        
        response = await self.claude.messages.create(
            model="claude-haiku-4-5-20250315",
            max_tokens=4000,
            system=self.SYSTEM_PROMPT.format(
                duration=duration, word_count=word_count
            ),
            messages=[{
                "role": "user",
                "content": f"작품: {title}\n회차: {episodes}\n"
                          f"스타일: {style}\n줄거리:\n{plot_data}"
            }]
        )
        
        script = Script(
            title=title,
            episodes=episodes,
            content_en=response.content[0].text,
            status=ScriptStatus.GENERATED,
            cost_usd=self._calc_cost(response.usage)
        )
        await database.save(script)
        return script

    async def translate(self, script: Script, 
                        languages: list[str]) -> dict:
        """다국어 번역 병렬 실행"""
        tasks = []
        for lang in languages:
            tasks.append(self._translate_single(script, lang))
        
        results = await asyncio.gather(*tasks)
        return dict(zip(languages, results))

    async def _translate_single(self, script: Script, 
                                 target_lang: str) -> str:
        response = await self.claude.messages.create(
            model="claude-haiku-4-5-20250315",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": f"""다음 유튜브 리캡 스크립트를 
                {target_lang}로 번역해줘.
                
                규칙:
                - 무협 용어는 현지에서 통용되는 표현 사용
                - [이미지 프롬프트]와 [BGM] 태그는 번역하지 말 것
                - 자연스러운 구어체로 번역
                - 감정의 강도를 유지
                
                원본:\n{script.content_en}"""
            }]
        )
        return response.content[0].text
Copy
🎨 TAB 4: 미디어 공장
이미지, 음성, 영상 편집을 통합 관리합니다.

┌─────────────────────────────────────────────────────────┐
│  🎨 미디어 공장                                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─ 진행중인 프로젝트: 화산귀환 51~100 (EN) ────────┐    │
│  │                                                │    │
│  │  전체 진행률: ████████████░░░░ 73%              │    │
│  │                                                │    │
│  │  🖼️ 이미지   ████████████████ 100% (28/28장)   │    │
│  │  🔊 음성     ████████████░░░░  78% (EN,KR완료)  │    │
│  │  🎬 편집     ████████░░░░░░░░  52% (EN 초벌)    │    │
│  │  🌏 더빙     ░░░░░░░░░░░░░░░░   0% (대기중)     │    │
│  └────────────────────────────────────────────────┘    │
│                                                         │
│  ═══════════════════════════════════════════════════    │
│  🖼️ 이미지 갤러리                                       │
│  ═══════════════════════════════════════════════════    │
│                                                         │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐   │
│  │ S1 │ │ S2 │ │ S3 │ │ S4 │ │ S5 │ │ S6 │ │ S7 │   │
│  │ ✅ │ │ ✅ │ │ ✅ │ │ ⚠️ │ │ ✅ │ │ ✅ │ │ ✅ │   │
│  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘ └────┘   │
│                                                         │
│  선택된 이미지: Scene 4 — "검황과의 대결"                   │
│  ┌──────────────────────────┐                          │
│  │                          │ 상태: ⚠️ 손가락 오류      │
│  │    [AI 생성 이미지 미리보기]  │                          │
│  │                          │ [🔄 재생성]               │
│  │                          │ [✏️ 프롬프트 수정]         │
│  │                          │ [✅ 승인]                  │
│  └──────────────────────────┘                          │
│                                                         │
│  프롬프트: "Two martial artists clashing swords on a     │
│  cliff edge, dramatic lighting, Korean manhwa style,     │
│  dynamic action pose, energy effects, --ar 16:9"        │
│  [수정하기]                                              │
│                                                         │
│  ═══════════════════════════════════════════════════    │
│  🔊 음성 컨트롤                                          │
│  ═══════════════════════════════════════════════════    │
│                                                         │
│  보이스 프로필: [MurimNarrator_v3 ▼]                     │
│  속도: [1.0x ▼]  감정: [드라마틱 ▼]  피치: [중간 ▼]      │
│                                                         │
│  🇺🇸 EN ▶ ■■■■■■■■■■■■■■ 10:23  ✅ [재생] [재생성]     │
│  🇰🇷 KR ▶ ■■■■■■■■■■■■■  9:47  ✅ [재생] [재생성]     │
│  🇮🇩 ID ▶ ■■■■■■■■░░░░░  7:12  🔄 생성중...           │
│  🇹🇭 TH ▶ ░░░░░░░░░░░░░  0:00  ⏳ 대기                │
│                                                         │
│  ═══════════════════════════════════════════════════    │
│  🎬 편집 & 조립                                          │
│  ═══════════════════════════════════════════════════    │
│                                                         │
│  [▶ 자동 편집 실행]  [🎵 BGM 자동 매칭]  [📝 자막 생성]   │
│                                                         │
│  타임라인 미리보기:                                       │
│  |인트로|S1  |S2  |S3    |S4  |S5    |S6|S7  |아웃트로|   │
│  |0:05 |1:30|1:20|1:45  |1:15|1:40  |1:|1:25|0:15  |   │
│                                                         │
│  [👁️ 전체 미리보기]  [✅ 편집 승인 → 더빙 단계로]          │
└─────────────────────────────────────────────────────────┘
핵심 파이썬 구조:

Copy# app/services/media_factory.py

import httpx
from elevenlabs import AsyncElevenLabs

class MediaFactory:
    
    def __init__(self):
        self.elevenlabs = AsyncElevenLabs(
            api_key=os.getenv("ELEVENLABS_API_KEY")
        )
        self.midjourney_api = os.getenv("MIDJOURNEY_API_URL")

    # ─── 이미지 생성 ───
    async def generate_scene_images(self, script: Script) -> list:
        """스크립트에서 이미지 프롬프트를 추출하여 배치 생성"""
        prompts = self._extract_image_prompts(script.content_en)
        
        tasks = [self._generate_image(p) for p in prompts]
        images = await asyncio.gather(*tasks)
        
        return [
            {"scene": i+1, "prompt": p, "image_path": img, 
             "status": "generated"}
            for i, (p, img) in enumerate(zip(prompts, images))
        ]

    async def _generate_image(self, prompt: str) -> str:
        """Midjourney API 호출 (또는 로컬 ComfyUI)"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.midjourney_api}/imagine",
                json={
                    "prompt": f"{prompt}, korean manhwa style, "
                             f"cinematic, --ar 16:9 --v 6.1",
                    "process_mode": "relax"  # 절약 모드
                }
            )
            return resp.json()["image_url"]

    # ─── 음성 생성 ───
    async def generate_voice(self, text: str, 
                              language: str) -> str:
        """ElevenLabs로 내레이션 음성 생성"""
        voice_map = {
            "en": "MurimNarrator_EN_v3",
            "ko": "MurimNarrator_KR_v3",
            "id": "MurimNarrator_ID_v3",
            "th": "MurimNarrator_TH_v3",
        }
        
        audio = await self.elevenlabs.text_to_speech.convert(
            voice_id=voice_map[language],
            text=text,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            voice_settings={
                "stability": 0.5,
                "similarity_boost": 0.8,
                "style": 0.7,  # 드라마틱
            }
        )
        
        path = f"output/audio/{script_id}_{language}.mp3"
        with open(path, "wb") as f:
            async for chunk in audio:
                f.write(chunk)
        return path

    # ─── 영상 자동 조립 ───
    async def auto_assemble(self, project_id: str) -> str:
        """이미지 + 음성 + 자막 + BGM → 영상 자동 조립"""
        project = await database.get_project(project_id)
        
        # FFmpeg 명령어 자동 생성
        cmd = self._build_ffmpeg_command(
            images=project.images,
            audio=project.audio_path,
            subtitles=project.subtitle_path,
            bgm=project.bgm_path,
            intro_template="templates/intro_murim.mp4",
            outro_template="templates/outro_subscribe.mp4",
        )
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE
        )
        await process.wait()
        
        return f"output/video/{project_id}_final.mp4"
Copy
📺 TAB 5: 채널 관리 허브
4개 채널의 업로드, 스케줄링, 성과 분석을 통합 관리합니다.

┌─────────────────────────────────────────────────────────┐
│  📺 채널 관리 허브                                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  채널 선택: [🇺🇸 EN] [🇰🇷 KR] [🇮🇩 ID] [🇹🇭 TH] [전체]  │
│                                                         │
│  ═══ 업로드 큐 ═══════════════════════════════════════   │
│                                                         │
│  ┌─────────────────────────────────────────────┐       │
│  │ #  제목              채널  예약시간    상태    │       │
│  │ ── ─────────────── ──── ────────── ─────── │       │
│  │ 47 화산귀환 51~100  🇺🇸   오늘 18:00  ⏰예약  │       │
│  │ 47 화산귀환 51~100  🇰🇷   오늘 20:00  ⏰예약  │       │
│  │ 47 화산귀환 51~100  🇮🇩   오늘 19:00  ⏰예약  │       │
│  │ 47 화산귀환 51~100  🇹🇭   내일 18:00  ⏰예약  │       │
│  │ 46 북검전기 S2      🇺🇸   어제 18:00  ✅완료  │       │
│  │                                             │       │
│  │ [📤 선택 항목 즉시 업로드]  [⏰ 스케줄 일괄 변경] │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  ═══ 자동 스케줄 설정 ════════════════════════════════   │
│                                                         │
│  🇺🇸 EN: 매일 [18:00] EST  (미국 저녁 피크)              │
│  🇰🇷 KR: 매일 [20:00] KST  (한국 저녁 피크)              │
│  🇮🇩 ID: 매일 [19:00] WIB  (인도네시아 저녁 피크)         │
│  🇹🇭 TH: 매일 [18:00] ICT  (태국 저녁 피크)              │
│                                                         │
│  ═══ A/B 테스트 현황 ════════════════════════════════    │
│                                                         │
│  #46 북검전기 S2 (🇺🇸 EN)                               │
│  ┌──────────────────────────────────────┐              │
│  │ 🅰 "This Swordsman Was BANNED..."     │ CTR: 8.2%   │
│  │ 🅱 "They Called Him Weak..."          │ CTR: 11.4%  │ ⭐승리
│  │ 🅲 "The Sword Nobody Could Stop"     │ CTR: 6.7%   │
│  └──────────────────────────────────────┘              │
│                                                         │
│  ═══ 성과 분석 ═══════════════════════════════════════   │
│                                                         │
│  기간: [최근 7일 ▼]                                      │
│                                                         │
│  📊 [조회수 차트]  [구독자 차트]  [수익 차트]              │
│  ┌─────────────────────────────────────────────┐       │
│  │         조회수 추이 (7일)                      │       │
│  │  15K ┤                          ╭──          │       │
│  │  10K ┤              ╭───╮ ╭────╯             │       │
│  │   5K ┤    ╭────────╯   ╰╯                   │       │
│  │    0 ┤────╯                                  │       │
│  │      └─월──화──수──목──금──토──일──           │       │
│  │      🇺🇸── 🇰🇷── 🇮🇩── 🇹🇭──                 │       │
│  └─────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
핵심 파이썬 구조:

Copy# app/services/channel_hub.py

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

class ChannelHub:
    
    CHANNELS = {
        "en": {"id": "UC...", "timezone": "US/Eastern",
               "peak_hour": 18},
        "ko": {"id": "UC...", "timezone": "Asia/Seoul",
               "peak_hour": 20},
        "id": {"id": "UC...", "timezone": "Asia/Jakarta",
               "peak_hour": 19},
        "th": {"id": "UC...", "timezone": "Asia/Bangkok",
               "peak_hour": 18},
    }

    async def upload_video(self, video_path: str, 
                           metadata: dict, channel: str,
                           schedule_time: datetime = None):
        """YouTube Data API로 영상 업로드"""
        youtube = build('youtube', 'v3', 
                       credentials=self.get_creds(channel))
        
        body = {
            'snippet': {
                'title': metadata['title'],
                'description': metadata['description'],
                'tags': metadata['tags'],
                'categoryId': '24',  # Entertainment
                'defaultLanguage': metadata['language'],
            },
            'status': {
                'privacyStatus': 'private' if schedule_time 
                                 else 'public',
                'publishAt': schedule_time.isoformat() 
                            if schedule_time else None,
                'selfDeclaredMadeForKids': False,
            }
        }
        
        media = MediaFileUpload(video_path, 
                               mimetype='video/mp4',
                               resumable=True)
        
        request = youtube.videos().insert(
            part='snippet,status',
            body=body, media_body=media
        )
        
        # 업로드 진행률 콜백
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                await self.update_progress(
                    channel, int(status.progress() * 100)
                )
        
        return response['id']

    async def batch_upload_all_languages(self, 
                                          project_id: str):
        """4개국어 영상을 각 채널에 최적 시간으로 예약 업로드"""
        project = await database.get_project(project_id)
        
        for lang, config in self.CHANNELS.items():
            video_path = f"output/video/{project_id}_{lang}.mp4"
            metadata = await self.generate_seo_metadata(
                project, lang
            )
            schedule = self.get_next_peak_time(config)
            
            video_id = await self.upload_video(
                video_path, metadata, lang, schedule
            )
            
            # 썸네일 업로드
            await self.upload_thumbnail(
                video_id, 
                f"output/thumb/{project_id}_{lang}.jpg",
                lang
            )
Copy
💰 TAB 6: 비용 트래커
모든 API 호출의 비용을 실시간 추적합니다.

┌─────────────────────────────────────────────────────────┐
│  💰 비용 트래커                                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  이번 달: 2026년 3월     [일별▼]  [주별] [월별]          │
│                                                         │
│  ┌─────────────────────────────────────────────┐       │
│  │  💳 총 비용      ₩187,200 / ₩215,000 예산    │       │
│  │  ████████████████████████████░░░  87%        │       │
│  └─────────────────────────────────────────────┘       │
│                                                         │
│  ┌─ API별 비용 내역 ─────────────────────────────┐      │
│  │                                               │      │
│  │  서비스          사용량          비용    비중    │      │
│  │  ──────────── ──────────── ─────── ─────── │      │
│  │  🔊 ElevenLabs  387,000크레딧  ₩128,700  69%  │      │
│  │     ├ 음성생성   280,000        ₩93,100       │      │
│  │     └ 더빙       107,000        ₩35,600       │      │
│  │                                               │      │
│  │  🖼️ Midjourney   847장 생성     ₩39,000  21%  │      │
│  │     ├ Fast모드    127장          ₩31,200       │      │
│  │     └ Relax모드   720장          ₩7,800(고정)  │      │
│  │                                               │      │
│  │  🤖 Claude API   1.2M 토큰     ₩2,600    1%  │      │
│  │     ├ 스크립트    400K           ₩780         │      │
│  │     ├ 번역       700K           ₩1,560        │      │
│  │     └ SEO메타    100K           ₩260          │      │
│  │                                               │      │
│  │  🎬 CapCut Pro   고정           ₩10,400   6%  │      │
│  │  🎨 Canva Pro    고정           ₩16,900   5%  │      │  
│  │  📊 TubeBuddy   고정           ₩10,400       │      │
│  │  🔧 VPS (n8n)   고정           ₩6,500        │      │
│  │                                               │      │
│  │  ────────────────────────────────────────    │      │
│  │  합계                          ₩187,200      │      │
│  │  영상 1편당 평균 비용             ₩1,730       │      │
│  └───────────────────────────────────────────────┘      │
│                                                         │
│  ┌─ 비용 트렌드 ─────────────────────────────────┐      │
│  │      일별 비용 추이                             │      │
│  │  15K ┤          ╭╮                             │      │
│  │  10K ┤  ╭╮ ╭╮╭╯╰╮╭╮                          │      │
│  │   5K ┤╭╯╰─╯╰╯   ╰╯╰╮                        │      │
│  │    0 ┤              ╰──  (오늘)               │      │
│  │      └─1──5──10──15──                         │      │
│  │      🔊음성── 🖼️이미지── 🤖AI──               │      │
│  └───────────────────────────────────────────────┘      │
│                                                         │
│  ⚠️ 알림: ElevenLabs 크레딧 78% 소진. 잔여 113,000      │
│  💡 추천: 이번 주 남은 영상 5편은 Relax 이미지 모드 사용   │
└─────────────────────────────────────────────────────────┘
핵심 파이썬 구조:

Copy# app/services/cost_tracker.py

from dataclasses import dataclass
from datetime import datetime

@dataclass
class APICall:
    service: str        # "claude", "elevenlabs", "midjourney"
    action: str         # "script", "translate", "tts", "image"
    units_used: float   # 토큰, 크레딧, 이미지 수
    cost_usd: float
    project_id: str
    timestamp: datetime

class CostTracker:
    """모든 API 호출을 자동으로 로깅하는 미들웨어"""
    
    RATES = {
        "claude_haiku_input":    1.00 / 1_000_000,  # $/token
        "claude_haiku_output":   5.00 / 1_000_000,
        "elevenlabs_tts":        0.30 / 1_000,      # $/1K credits
        "elevenlabs_dubbing":    0.30 / 1_000,
        "midjourney_fast":       0.15,               # $/image (추정)
        "midjourney_relax":      0.01,               # $/image (고정비 배분)
    }

    async def log_call(self, call: APICall):
        """모든 API 호출 시 자동으로 기록"""
        await database.insert("api_costs", {
            "service": call.service,
            "action": call.action,
            "units": call.units_used,
            "cost_usd": call.cost_usd,
            "cost_krw": call.cost_usd * 1300,  # 환율
            "project_id": call.project_id,
            "timestamp": call.timestamp,
        })

    async def get_monthly_summary(self) -> dict:
        """월간 비용 요약"""
        rows = await database.query("""
            SELECT service, action, 
                   SUM(units) as total_units,
                   SUM(cost_usd) as total_usd,
                   COUNT(*) as call_count
            FROM api_costs 
            WHERE timestamp >= date('now', 'start of month')
            GROUP BY service, action
            ORDER BY total_usd DESC
        """)
        
        total = sum(r['total_usd'] for r in rows)
        per_video = total / max(1, await self.get_video_count())
        
        return {
            "total_usd": total,
            "total_krw": total * 1300,
            "per_video_krw": per_video * 1300,
            "breakdown": rows,
            "budget_remaining": self.monthly_budget - total,
        }

    async def check_alerts(self) -> list:
        """예산 초과 위험 알림"""
        alerts = []
        summary = await self.get_monthly_summary()
        
        if summary['total_usd'] > self.monthly_budget * 0.8:
            alerts.append({
                "level": "warning",
                "message": f"월 예산의 {summary['total_usd']/self.monthly_budget*100:.0f}% 소진"
            })
        
        # ElevenLabs 크레딧 잔여량 체크
        el_remaining = await self.elevenlabs.get_remaining_credits()
        if el_remaining < 50_000:
            alerts.append({
                "level": "warning", 
                "message": f"ElevenLabs 크레딧 잔여: {el_remaining:,}"
            })
        
        return alerts
Copy
메인 앱 진입점
Copy# main.py

from nicegui import ui, app
from fastapi import FastAPI
from app.pages import dashboard, trend_scout, script_factory
from app.pages import media_factory, channel_hub, cost_tracker

# FastAPI 백엔드
api = FastAPI()

# NiceGUI 프론트엔드 
@ui.page('/')
async def index():
    with ui.header().classes('bg-gray-900 text-white'):
        ui.label('⚔️ 무협 팩토리').classes('text-xl font-bold')
        with ui.row().classes('ml-auto'):
            ui.label('v1.0').classes('text-sm text-gray-400')
    
    with ui.tabs().classes('w-full') as tabs:
        tab_dash   = ui.tab('📊 대시보드')
        tab_trend  = ui.tab('🔍 트렌드')
        tab_script = ui.tab('✍️ 스크립트')
        tab_media  = ui.tab('🎨 미디어')
        tab_channel= ui.tab('📺 채널')
        tab_cost   = ui.tab('💰 비용')
    
    with ui.tab_panels(tabs, value=tab_dash).classes('w-full'):
        with ui.tab_panel(tab_dash):
            await dashboard.dashboard_page()
        with ui.tab_panel(tab_trend):
            await trend_scout.trend_page()
        with ui.tab_panel(tab_script):
            await script_factory.script_page()
        with ui.tab_panel(tab_media):
            await media_factory.media_page()
        with ui.tab_panel(tab_channel):
            await channel_hub.channel_page()
        with ui.tab_panel(tab_cost):
            await cost_tracker.cost_page()

# 백그라운드 스케줄러 (트렌드 자동 수집 등)
@app.on_startup
async def start_scheduler():
    from app.scheduler import start_background_tasks
    await start_background_tasks()

ui.run(
    title='무협 팩토리',
    port=8080,
    favicon='⚔️',
    dark=True,           # 다크모드
    reload=False,        # 프로덕션
    storage_secret='your-secret-key',
)
Copy
프로젝트 폴더 구조
murim-factory/
├── main.py                    ← 앱 진입점
├── requirements.txt           ← 의존성 목록
├── .env                       ← API 키 (절대 Git에 올리지 않기)
│
├── app/
│   ├── __init__.py
│   │
│   ├── pages/                 ← UI 화면들
│   │   ├── dashboard.py       ← TAB 1: 대시보드
│   │   ├── trend_scout.py     ← TAB 2: 트렌드 스카우트
│   │   ├── script_factory.py  ← TAB 3: 스크립트 공장
│   │   ├── media_factory.py   ← TAB 4: 미디어 공장
│   │   ├── channel_hub.py     ← TAB 5: 채널 관리
│   │   └── cost_tracker.py    ← TAB 6: 비용 트래커
│   │
│   ├── services/              ← 핵심 비즈니스 로직
│   │   ├── trend_service.py   ← 트렌드 수집 + AI 분석
│   │   ├── script_service.py  ← 스크립트 생성 + 번역
│   │   ├── image_service.py   ← Midjourney/Flux 이미지
│   │   ├── voice_service.py   ← ElevenLabs 음성/더빙
│   │   ├── video_service.py   ← FFmpeg 영상 조립
│   │   ├── youtube_service.py ← YouTube API 업로드
│   │   ├── seo_service.py     ← 메타데이터/SEO 자동생성
│   │   └── cost_service.py    ← 비용 추적 미들웨어
│   │
│   ├── models/                ← 데이터 모델
│   │   ├── project.py         ← 프로젝트 (영상 1세트)
│   │   ├── script.py          ← 스크립트
│   │   ├── media.py           ← 이미지/음성/영상 파일
│   │   └── cost.py            ← API 비용 기록
│   │
│   ├── db.py                  ← SQLite/PostgreSQL 연결
│   ├── config.py              ← 환경 설정
│   └── scheduler.py           ← 백그라운드 작업 스케줄러
│
├── templates/                 ← 영상 템플릿
│   ├── intro_murim.mp4        ← 인트로 애니메이션
│   ├── outro_subscribe.mp4    ← 아웃트로 (구독 유도)
│   └── thumbnail_base.psd     ← 썸네일 템플릿
│
├── output/                    ← 생성된 파일들
│   ├── scripts/
│   ├── images/
│   ├── audio/
│   ├── video/
│   └── thumbnails/
│
└── docker-compose.yml         ← 원클릭 배포용
원클릭 설치 & 실행
Copy# docker-compose.yml

version: '3.8'
services:
  murim-factory:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./output:/app/output
      - ./.env:/app/.env
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped

  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
Copy# 설치 & 실행 (3줄이면 끝)
git clone https://github.com/your-repo/murim-factory.git
cd murim-factory
docker-compose up -d

# 브라우저에서 접속
# http://localhost:8080
# requirements.txt

nicegui>=3.0
fastapi>=0.115
uvicorn>=0.34
anthropic>=0.45          # Claude API
elevenlabs>=1.20         # ElevenLabs API
google-api-python-client  # YouTube API
google-auth-oauthlib
httpx>=0.28              # 비동기 HTTP
aiosqlite                # 비동기 SQLite
celery[redis]            # 백그라운드 작업 큐
Pillow                   # 이미지 처리
pydantic>=2.0            # 데이터 검증
python-dotenv            # 환경변수
apscheduler              # 스케줄러
개발 로드맵
📅 Week 1~2: 뼈대 구축
   ├── NiceGUI 기본 레이아웃 + 탭 구조
   ├── SQLite DB 스키마 설계
   ├── .env 기반 API 키 관리
   └── 대시보드 화면 (더미 데이터)

📅 Week 3~4: 스크립트 엔진
   ├── Claude API 연동 (스크립트 생성)
   ├── 다국어 번역 파이프라인
   ├── 스크립트 에디터 UI
   └── 비용 로깅 미들웨어

📅 Week 5~6: 미디어 엔진
   ├── Midjourney API 연동 (이미지 생성)
   ├── ElevenLabs 연동 (음성 생성)
   ├── FFmpeg 자동 편집 파이프라인
   └── 미디어 갤러리 UI

📅 Week 7~8: 배포 엔진
   ├── YouTube Data API 연동 (업로드)
   ├── 자동 스케줄링 시스템
   ├── SEO 메타데이터 자동생성
   └── A/B 테스트 추적

📅 Week 9~10: 자동화 & 최적화
   ├── 트렌드 자동 수집 봇
   ├── 원클릭 전체 파이프라인 실행
   ├── 비용 트래커 + 알림
   └── Docker 배포 패키징