"""트렌드 스카우트 UI — 실시간 수집 + AI 랭킹 + 히스토리"""

from nicegui import ui
from app.services.trend_scout import TrendScout
from app.db import get_db


async def trend_page():
    ui.label('🔍 트렌드 스카우트').classes('text-xl font-bold')
    ui.label('자동 수집 주기: 매 6시간 · YouTube + 네이버 + Reddit → Claude AI 랭킹').classes(
        'text-sm text-gray-500 mt-1'
    )

    scout = TrendScout()

    # ─── 소스 상태 카드 ───
    with ui.row().classes('w-full gap-4 mt-4'):
        with ui.card().classes('flex-1'):
            ui.label('🎬 YouTube').classes('text-sm text-gray-500')
            yt_status = ui.label('대기 중').classes('text-lg font-bold')

        with ui.card().classes('flex-1'):
            ui.label('📗 네이버 웹툰').classes('text-sm text-gray-500')
            nv_status = ui.label('대기 중').classes('text-lg font-bold')

        with ui.card().classes('flex-1'):
            ui.label('💬 Reddit').classes('text-sm text-gray-500')
            rd_status = ui.label('대기 중').classes('text-lg font-bold')

        with ui.card().classes('flex-1'):
            ui.label('🕐 최근 수집').classes('text-sm text-gray-500')
            last_update = ui.label('—').classes('text-lg font-bold')

    # ─── AI 랭킹 테이블 ───
    ui.label('AI 추천 TOP 랭킹').classes('text-lg font-bold mt-6 mb-2')
    trend_table = ui.table(
        columns=[
            {'field': 'rank', 'label': '순위', 'sortable': True},
            {'field': 'title', 'label': '작품명', 'sortable': True},
            {'field': 'score', 'label': '점수', 'sortable': True},
            {'field': 'reason', 'label': '근거'},
            {'field': 'episode_range', 'label': '추천 회차'},
            {'field': 'target_audience', 'label': '대상'},
        ],
        rows=[],
    ).classes('w-full')

    # ─── 수집 원본 데이터 테이블 ───
    ui.label('수집 원본 데이터').classes('text-lg font-bold mt-6 mb-2')
    raw_table = ui.table(
        columns=[
            {'field': 'title', 'label': '제목', 'sortable': True},
            {'field': 'trend_score', 'label': '점수', 'sortable': True},
            {'field': 'source', 'label': '소스', 'sortable': True},
            {'field': 'genre', 'label': '장르'},
        ],
        rows=[],
    ).classes('w-full')

    status_label = ui.label('').classes('text-sm text-gray-500 mt-2')

    async def refresh_trends():
        status_label.text = '수집 중...'
        yt_status.text = '수집 중...'
        nv_status.text = '수집 중...'
        rd_status.text = '수집 중...'
        ui.notify('트렌드 수집 시작 (YouTube + 네이버 + Reddit)...', color='blue')

        # 수집
        raw_data = await scout.collect_all_sources()

        # 소스별 카운트
        source_counts = {}
        for item in raw_data:
            src = item.get('source', 'Unknown')
            source_counts[src] = source_counts.get(src, 0) + 1

        yt_status.text = f"{source_counts.get('YouTube', 0)}건"
        nv_status.text = f"{source_counts.get('Naver', 0)}건"
        rd_status.text = f"{source_counts.get('Reddit', 0)}건"

        # 원본 테이블 갱신
        raw_table.rows = [
            {
                'title': item.get('title', ''),
                'trend_score': item.get('trend_score', 0),
                'source': item.get('source', ''),
                'genre': item.get('genre', ''),
            }
            for item in raw_data
        ]

        # AI 랭킹
        ui.notify('AI 랭킹 분석 중...', color='blue')
        ai_data = await scout.ai_rank_topics(raw_data)

        trend_table.rows = [
            {
                'rank': i + 1,
                'title': row.get('title', ''),
                'score': row.get('score', ''),
                'reason': row.get('reason', ''),
                'episode_range': row.get('episode_range', ''),
                'target_audience': row.get('target_audience', ''),
            }
            for i, row in enumerate(ai_data)
        ]

        from datetime import datetime, timezone
        last_update.text = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
        total = len(raw_data)
        status_label.text = f'총 {total}개 수집 → AI TOP {len(ai_data)}개 선정'
        ui.notify(f'트렌드 업데이트 완료 ({total}건 수집)', color='green')

    async def load_history():
        """DB에 저장된 최근 AI 랭킹 히스토리를 불러옵니다."""
        db = await get_db()
        try:
            await db.execute('''CREATE TABLE IF NOT EXISTS trend_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rank INTEGER DEFAULT 0,
                title TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                reason TEXT DEFAULT '',
                episode_range TEXT DEFAULT '',
                target_audience TEXT DEFAULT '',
                collected_at TEXT NOT NULL
            )''')
            async with db.execute(
                '''SELECT rank, title, score, reason, episode_range, target_audience, collected_at
                   FROM trend_results
                   ORDER BY collected_at DESC, rank ASC
                   LIMIT 20'''
            ) as cursor:
                rows = [dict(r) for r in await cursor.fetchall()]

            if rows:
                trend_table.rows = [
                    {
                        'rank': r['rank'],
                        'title': r['title'],
                        'score': r['score'],
                        'reason': r['reason'],
                        'episode_range': r['episode_range'],
                        'target_audience': r['target_audience'],
                    }
                    for r in rows
                ]
                last_update.text = (rows[0].get('collected_at', '') or '')[:19]
                status_label.text = f'DB 히스토리에서 {len(rows)}개 로드됨'
        finally:
            await db.close()

    with ui.row().classes('gap-2 mt-3'):
        ui.button('🔄 지금 수집하기', on_click=refresh_trends).props('color=primary')
        ui.button('📋 히스토리 보기', on_click=load_history)

    # 페이지 로드 시: DB 히스토리 먼저 표시, 없으면 실시간 수집
    await load_history()
    if not trend_table.rows:
        await refresh_trends()
