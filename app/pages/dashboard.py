from nicegui import ui
from app.services.cost_service import CostTracker
from app.db import get_db


async def dashboard_page():
    tracker = CostTracker()
    summary = await tracker.get_monthly_summary()
    alerts = await tracker.check_alerts()

    # 알림 배너
    for alert in alerts:
        color = 'red' if alert['level'] == 'error' else 'orange'
        ui.label(f"⚠️ {alert['message']}").classes(f'text-{color}-500 font-bold mb-2')

    # ─── KPI 카드 ───
    with ui.row().classes('w-full gap-4'):
        with ui.card().classes('flex-1'):
            ui.label('📺 프로젝트 수').classes('text-sm text-gray-500')
            ui.label(f"{summary['project_count']}개").classes('text-3xl font-bold')

        with ui.card().classes('flex-1'):
            ui.label('🔢 API 호출').classes('text-sm text-gray-500')
            ui.label(f"{summary['total_calls']}회").classes('text-3xl font-bold')

        with ui.card().classes('flex-1'):
            ui.label('💰 이번 달 비용').classes('text-sm text-gray-500')
            ui.label(f"₩{summary['total_krw']:,.0f}").classes('text-3xl font-bold')
            ui.label(f"${summary['total_usd']:.2f} / ${summary['budget_usd']}").classes('text-xs text-gray-500')

        with ui.card().classes('flex-1'):
            ui.label('💳 편당 비용').classes('text-sm text-gray-500')
            ui.label(f"₩{summary['per_video_krw']:,.0f}").classes('text-3xl font-bold')

    # ─── 채널 현황 ───
    ui.label('채널 현황').classes('text-lg font-bold mt-6 mb-2')
    db = await get_db()
    try:
        async with db.execute('SELECT code, name, timezone, peak_hour FROM channels ORDER BY code') as cursor:
            channels = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    ui.table(
        columns=[
            {'field': 'code', 'label': '코드', 'sortable': True},
            {'field': 'name', 'label': '채널명'},
            {'field': 'timezone', 'label': '시간대'},
            {'field': 'peak_hour', 'label': '피크 시간'},
        ],
        rows=channels,
    )

    # ─── 비용 breakdown ───
    if summary['breakdown']:
        ui.label('서비스별 비용').classes('text-lg font-bold mt-6 mb-2')
        ui.table(
            columns=[
                {'field': 'service', 'label': '서비스'},
                {'field': 'action', 'label': '작업'},
                {'field': 'call_count', 'label': '호출 수'},
                {'field': 'total_units', 'label': '총 토큰'},
                {'field': 'total_usd', 'label': '비용(USD)'},
                {'field': 'total_krw', 'label': '비용(KRW)'},
            ],
            rows=[
                {
                    **item,
                    'total_usd': f"${item['total_usd']:.4f}",
                    'total_krw': f"₩{item['total_krw']:,.0f}",
                    'total_units': f"{item['total_units']:,.0f}",
                }
                for item in summary['breakdown']
            ],
        )
