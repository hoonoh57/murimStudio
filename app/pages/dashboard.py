from nicegui import ui
from app.services.cost_service import CostTracker

async def dashboard_page():
    with ui.row().classes('w-full gap-4'):
        with ui.card().classes('flex-1'):
            ui.label('📺 오늘 생산').classes('text-sm text-gray-500')
            ui.label('0/0편').classes('text-3xl font-bold')
        with ui.card().classes('flex-1'):
            ui.label('📤 업로드 대기').classes('text-sm text-gray-500')
            ui.label('0편').classes('text-3xl font-bold')
        with ui.card().classes('flex-1'):
            ui.label('💰 이번 달 비용').classes('text-sm text-gray-500')
            summary = await CostTracker().get_monthly_summary()
            ui.label(f"₩{summary['total_krw']:.0f}").classes('text-3xl font-bold')

    ui.label('채널별 실시간 현황 (샘플)').classes('mt-4')
    ui.table(
        columns=[
            {'field': 'channel', 'label': '채널'},
            {'field': 'subs', 'label': '구독자'},
            {'field': 'today', 'label': '오늘'},
            {'field': 'delta', 'label': '증감'},
        ],
        rows=[
            {'channel': 'EN', 'subs': '12.3K', 'today': '+127', 'delta': '2.1%'},
            {'channel': 'KR', 'subs': '8.7K', 'today': '+89', 'delta': '1.8%'},
            {'channel': 'ID', 'subs': '21.5K', 'today': '+312', 'delta': '3.4%'},
            {'channel': 'TH', 'subs': '5.2K', 'today': '+67', 'delta': '2.7%'},
        ]
    )
