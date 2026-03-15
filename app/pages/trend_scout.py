from nicegui import ui
from app.services.trend_scout import TrendScout


async def trend_page():
    ui.label('🔍 트렌드 스카우트').classes('text-xl font-bold')
    ui.label('자동 수집 주기: 매 6시간 · Claude Haiku 4.5 분석').classes('text-sm text-gray-500 mt-1')

    scout = TrendScout()

    # 테이블 (빈 상태로 시작)
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
    ).classes('w-full mt-4')

    status_label = ui.label('').classes('text-sm text-gray-500 mt-2')

    async def refresh_trends():
        status_label.text = '수집 중...'
        ui.notify('트렌드 수집/AI 랭킹 시작...', color='blue')

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

        status_label.text = f'최종 업데이트: {len(ai_data)}개 작품 분석 완료'
        ui.notify('트렌드 업데이트 완료', color='green')

    with ui.row().classes('gap-2 mt-2'):
        ui.button('🔄 지금 수집하기', on_click=refresh_trends).props('color=primary')

    # 페이지 로드 시 자동 실행
    await refresh_trends()
