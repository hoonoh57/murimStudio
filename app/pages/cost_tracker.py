from nicegui import ui
from app.services.cost_service import CostTracker


async def cost_page():
    ui.label('💰 비용 트래커').classes('text-xl font-bold')
    ui.label('API 사용량 모니터링 · 예산 관리').classes('text-sm text-gray-500 mt-1')

    tracker = CostTracker()

    # ─── 요약 카드 ───
    summary_container = ui.column().classes('w-full')

    # ─── 서비스별 breakdown ───
    breakdown_table = ui.table(
        columns=[
            {'field': 'service', 'label': '서비스'},
            {'field': 'action', 'label': '작업'},
            {'field': 'call_count', 'label': '호출 수'},
            {'field': 'total_units', 'label': '총 토큰'},
            {'field': 'total_usd', 'label': '비용(USD)'},
            {'field': 'total_krw', 'label': '비용(KRW)'},
        ],
        rows=[],
    ).classes('w-full mt-4')

    # ─── 최근 로그 ───
    ui.label('최근 API 호출 로그').classes('font-bold mt-6')
    log_table = ui.table(
        columns=[
            {'field': 'timestamp', 'label': '시간'},
            {'field': 'service', 'label': '서비스'},
            {'field': 'action', 'label': '작업'},
            {'field': 'units', 'label': '토큰'},
            {'field': 'cost_usd', 'label': 'USD'},
            {'field': 'cost_krw', 'label': 'KRW'},
            {'field': 'project_id', 'label': 'Project'},
        ],
        rows=[],
    ).classes('w-full mt-2')

    async def reload_costs():
        summary = await tracker.get_monthly_summary()
        alerts = await tracker.check_alerts()

        summary_container.clear()
        with summary_container:
            for alert in alerts:
                color = 'red' if alert['level'] == 'error' else 'orange'
                ui.label(f"⚠️ {alert['message']}").classes(f'text-{color}-500 font-bold')

            with ui.row().classes('w-full gap-4 mt-2'):
                with ui.card().classes('flex-1'):
                    ui.label('이번 달 총 비용').classes('text-sm text-gray-500')
                    ui.label(f"${summary['total_usd']:.4f}").classes('text-2xl font-bold')
                    ui.label(f"₩{summary['total_krw']:,.0f}").classes('text-sm')

                with ui.card().classes('flex-1'):
                    ui.label('예산 사용률').classes('text-sm text-gray-500')
                    pct = summary['budget_used_pct']
                    color = 'red' if pct >= 80 else 'green'
                    ui.label(f"{pct:.1f}%").classes(f'text-2xl font-bold text-{color}-500')
                    ui.label(f"남은 예산: ${summary['budget_remaining_usd']:.2f}").classes('text-sm')

                with ui.card().classes('flex-1'):
                    ui.label('총 API 호출').classes('text-sm text-gray-500')
                    ui.label(f"{summary['total_calls']}회").classes('text-2xl font-bold')

                with ui.card().classes('flex-1'):
                    ui.label('편당 평균 비용').classes('text-sm text-gray-500')
                    ui.label(f"₩{summary['per_video_krw']:,.0f}").classes('text-2xl font-bold')

        # Breakdown
        breakdown_table.rows = [
            {
                **item,
                'total_usd': f"${item['total_usd']:.4f}",
                'total_krw': f"₩{item['total_krw']:,.0f}",
                'total_units': f"{item['total_units']:,.0f}",
            }
            for item in summary.get('breakdown', [])
        ]

        # Recent logs
        logs = await tracker.get_recent_logs()
        log_table.rows = [
            {
                'timestamp': (log.get('timestamp', '') or '')[:19],
                'service': log.get('service', ''),
                'action': log.get('action', ''),
                'units': f"{log.get('units', 0):,.0f}",
                'cost_usd': f"${log.get('cost_usd', 0):.6f}",
                'cost_krw': f"₩{log.get('cost_krw', 0):,.1f}",
                'project_id': log.get('project_id', ''),
            }
            for log in logs
        ]

    with ui.row().classes('gap-2 mt-2'):
        ui.button('🔄 새로고침', on_click=reload_costs).props('color=primary')

    await reload_costs()
