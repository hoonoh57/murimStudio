from nicegui import ui

async def channel_page():
    ui.label('채널 관리 허브').classes('text-xl font-bold')
    ui.table(
        columns=[
            {'field': 'id', 'label': '#'},
            {'field': 'title', 'label': '제목'},
            {'field': 'channel', 'label': '채널'},
            {'field': 'schedule', 'label': '예약시간'},
            {'field': 'status', 'label': '상태'},
        ],
        rows=[
            {'id': 47, 'title': '화산귀환 51~100', 'channel': 'EN', 'schedule': '오늘 18:00', 'status': '예약'},
            {'id': 46, 'title': '북검전기 S2', 'channel': 'KR', 'schedule': '어제 18:00', 'status': '완료'},
        ]
    )
