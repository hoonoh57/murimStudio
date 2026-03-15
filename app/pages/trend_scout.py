from nicegui import ui
from app.services.trend_scout import TrendScout


async def trend_page():
    ui.label('🔍 트렌드 스카우트').classes('text-xl font-bold')
    ui.label('자동 수집 주기: 매 6시간').classes('mt-2')

    scout = TrendScout()

    trend_table = ui.table(
        columns=[
            {'field': 'rank', 'label': '순위'},
            {'field': 'title', 'label': '작품명'},
            {'field': 'score', 'label': '점수'},
            {'field': 'reason', 'label': '근거'},
            {'field': 'episode_range', 'label': '회차 범위'},
            {'field': 'target_audience', 'label': '대상'},
        ],
        rows=[],
    ).classes('w-full mt-4')

    async def refresh_trends():
        ui.notify('트렌드 수집/AI 랭킹 실행 중...', color='blue')
        raw_data = await scout.collect_all_sources()
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
        ui.notify('트렌드가 업데이트되었습니다.', color='green')

    with ui.row().classes('gap-2 mt-3'):
        ui.button('지금 수집하기', on_click=refresh_trends).props('color=primary')
        ui.button('새로고침', on_click=refresh_trends)

    await refresh_trends()
