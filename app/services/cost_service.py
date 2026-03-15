from datetime import datetime

class CostTracker:
    def __init__(self):
        self.monthly_budget = 200.0

    async def get_monthly_summary(self) -> dict:
        now = datetime.utcnow()
        return {
            'total_usd': 25.0,
            'total_krw': 25.0 * 1300,
            'per_video_krw': 1730.0,
            'breakdown': [],
            'budget_remaining': self.monthly_budget - 25.0,
        }

    async def check_alerts(self) -> list:
        summary = await self.get_monthly_summary()
        alerts = []
        if summary['total_usd'] > self.monthly_budget * 0.8:
            alerts.append({'level': 'warning', 'message': '월 예산 80% 초과'})
        return alerts
