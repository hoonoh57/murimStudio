from nicegui import ui
from app.services.cost_service import CostTracker

async def cost_page():
    ui.label('비용 트래커').classes('text-xl font-bold')
    summary = await CostTracker().get_monthly_summary()
    ui.markdown(f"- 총 비용: ₩{summary['total_krw']:.0f}\n- 예산 남음: ₩{summary['budget_remaining']*1300:.0f}")
