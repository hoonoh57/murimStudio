"""트렌드 스카우트 UI — 실시간 수집 + AI 랭킹 + 히스토리 (v1.8.2)"""

import logging
from urllib.parse import quote
from nicegui import ui
from app.services.trend_scout import TrendScout
from app.db import get_db

logger = logging.getLogger(__name__)


async def trend_page():
    ui.label('🔍 트렌드 스카우트').classes('text-xl font-bold')
    ui.label(
        '자동 수집 주기: 매 6시간 · YouTube + 네이버 + Reddit → Gemini AI 랭킹'
    ).classes('text-sm text-gray-500 mt-1')

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
    ui.label('💡 작품명을 클릭하면 상세 정보를 볼 수 있습니다').classes(
        'text-xs text-gray-500 mb-1'
    )

    ranking_container = ui.column().classes('w-full')

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

    def build_ranking_table(rows):
        """AI 랭킹을 클릭 가능한 테이블로 렌더링"""
        ranking_container.clear()
        with ranking_container:
            with ui.element('table').classes('w-full'):
                with ui.element('thead'):
                    with ui.element('tr').classes(
                        'text-left text-gray-400 text-sm'
                    ):
                        for col in [
                            '순위', '작품명', '점수', '근거', '추천 회차', '대상'
                        ]:
                            with ui.element('th').classes('p-2'):
                                ui.label(col)
                with ui.element('tbody'):
                    for row in rows:
                        with ui.element('tr').classes(
                            'border-t border-gray-700 hover:bg-gray-800 cursor-pointer'
                        ):
                            with ui.element('td').classes('p-2'):
                                ui.label(str(row.get('rank', '')))
                            with ui.element('td').classes('p-2'):
                                title = row.get('title', '')
                                ui.link(
                                    title, f'/trend/{quote(title)}'
                                ).classes(
                                    'text-blue-400 hover:text-blue-300 '
                                    'font-bold no-underline'
                                )
                            with ui.element('td').classes('p-2'):
                                ui.label(str(row.get('score', '')))
                            with ui.element('td').classes('p-2'):
                                ui.label(row.get('reason', ''))
                            with ui.element('td').classes('p-2'):
                                ui.label(row.get('episode_range', ''))
                            with ui.element('td').classes('p-2'):
                                ui.label(row.get('target_audience', ''))

    async def refresh_trends():
        status_label.text = '수집 중...'
        yt_status.text = '수집 중...'
        nv_status.text = '수집 중...'
        rd_status.text = '수집 중...'
        ui.notify('트렌드 수집 시작 (YouTube + 네이버 + Reddit)...', color='blue')

        try:
            raw_data = await scout.collect_all_sources()
        except Exception as e:
            logger.error(f'트렌드 수집 실패: {e}')
            ui.notify(f'수집 오류: {e}', color='red')
            status_label.text = f'수집 오류: {e}'
            return

        source_counts = {}
        for item in raw_data:
            src = item.get('source', 'Unknown')
            source_counts[src] = source_counts.get(src, 0) + 1

        yt_status.text = f"{source_counts.get('YouTube', 0)}건"
        nv_status.text = f"{source_counts.get('Naver', 0)}건"
        rd_status.text = f"{source_counts.get('Reddit', 0)}건"

        raw_table.rows = [
            {
                'title': item.get('title', ''),
                'trend_score': item.get('trend_score', 0),
                'source': item.get('source', ''),
                'genre': item.get('genre', ''),
            }
            for item in raw_data
        ]

        ui.notify('AI 랭킹 분석 중...', color='blue')

        try:
            ai_data = await scout.ai_rank_topics(raw_data)
        except Exception as e:
            logger.error(f'AI 랭킹 실패: {e}')
            ui.notify(f'AI 랭킹 오류 — 점수 기반 폴백 사용', color='orange')
            ai_data = TrendScout._fallback_rank(raw_data)

        ranking_rows = [
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
        build_ranking_table(ranking_rows)

        # AI 랭킹 결과를 DB에 저장
        await _save_ranking_results(ai_data)

        from datetime import datetime, timezone
        last_update.text = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
        total = len(raw_data)
        status_label.text = f'총 {total}개 수집 → AI TOP {len(ai_data)}개 선정'
        ui.notify(f'트렌드 업데이트 완료 ({total}건 수집)', color='green')

    async def load_history():
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
            await db.commit()

            async with db.execute(
                '''SELECT rank, title, score, reason, episode_range,
                          target_audience, collected_at
                   FROM trend_results
                   ORDER BY collected_at DESC, rank ASC
                   LIMIT 20'''
            ) as cursor:
                rows = [dict(r) for r in await cursor.fetchall()]

            if rows:
                ranking_rows = [
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
                build_ranking_table(ranking_rows)
                last_update.text = (rows[0].get('collected_at', '') or '')[:19]
                status_label.text = f'DB 히스토리에서 {len(rows)}개 로드됨'
            else:
                status_label.text = 'DB 히스토리 없음 — "지금 수집하기" 를 눌러주세요'
        except Exception as e:
            logger.error(f'히스토리 로드 실패: {e}')
            status_label.text = f'히스토리 로드 오류: {e}'
        finally:
            await db.close()

    with ui.row().classes('gap-2 mt-3'):
        ui.button(
            '🔄 지금 수집하기', on_click=refresh_trends
        ).props('color=primary')
        ui.button('📋 히스토리 보기', on_click=load_history)

    # 초기 로드: 히스토리 → 없으면 자동 수집
    await load_history()
    if not ranking_container.default_slot.children:
        await refresh_trends()


async def _save_ranking_results(ai_data: list) -> None:
    """AI 랭킹 결과를 trend_results 테이블에 저장"""
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

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        for i, row in enumerate(ai_data[:10]):
            await db.execute(
                '''INSERT INTO trend_results
                   (rank, title, score, reason, episode_range, target_audience, collected_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    i + 1,
                    row.get('title', ''),
                    int(row.get('score', 0)),
                    row.get('reason', ''),
                    row.get('episode_range', ''),
                    row.get('target_audience', ''),
                    now,
                ),
            )
        await db.commit()
        logger.info(f'AI 랭킹 {len(ai_data)}건 DB 저장 완료')
    except Exception as e:
        logger.error(f'AI 랭킹 DB 저장 실패: {e}')
    finally:
        await db.close()
