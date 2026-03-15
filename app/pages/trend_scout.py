from nicegui import ui

async def trend_page():
    ui.label('트렌드 스카우트').classes('text-xl font-bold')
    ui.label('자동 수집 주기: 매 6시간').classes('mt-2')
    ui.button('지금 수집하기', on_click=lambda: ui.notify('수집 시작'))
    ui.table(
        columns=[
            {'field': 'rank', 'label': '순위'},
            {'field': 'title', 'label': '작품명'},
            {'field': 'score', 'label': '점수'},
            {'field': 'reason', 'label': '근거'},
        ],
        rows=[
            {'rank': 1, 'title': '화산귀환 51~100화', 'score': '95', 'reason': '네이버 1위+'},
            {'rank': 2, 'title': '북검전기 시즌2', 'score': '88', 'reason': 'Reddit 핫토픽+'},
            {'rank': 3, 'title': '나혼렙 시즌3 예고', 'score': '85', 'reason': 'MAL 트렌딩 1위+'},
        ]
    )
