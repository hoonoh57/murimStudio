from nicegui import ui
from app.services.trend_scout import TrendScout

async def trend_page():
    ui.label('트렌드 스카우트').classes('text-xl font-bold')
    ui.label('자동 수집 주기: 매 6시간').classes('mt-2')
    scout = TrendScout()
    raw_data = await scout.collect_all_sources()
    ai_data = await scout.ai_rank_topics(raw_data)

    ui.button('지금 수집하기', on_click=lambda: ui.notify('수집 시작'))

    ui.table(
        columns=[
            {'field': 'rank', 'label': '순위'},
            {'field': 'title', 'label': '작품명'},
            {'field': 'score', 'label': '점수'},
            {'field': 'reason', 'label': '근거'},
        ],
        rows=[
            {'rank': i + 1, 'title': row.get('title', ''), 'score': row.get('score', ''), 'reason': row.get('reason', '')}
            for i, row in enumerate(ai_data)
        ]
    )
