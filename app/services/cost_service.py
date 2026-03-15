from datetime import datetime
from app.db import get_db

class CostTracker:
    def __init__(self):
        self.monthly_budget = 200.0

    async def log_cost(self, service: str, action: str,
                       units: float, cost_usd: float,
                       project_id: str = ''):
        db = await get_db()
        try:
            await db.execute(
                'INSERT INTO api_costs (service, action, units, cost_usd, cost_krw, project_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (service, action, units, cost_usd, cost_usd * 1300, project_id, datetime.utcnow().isoformat())
            )
            await db.commit()
        finally:
            await db.close()

    async def get_video_count(self) -> int:
        db = await get_db()
        try:
            async with db.execute('SELECT COUNT(DISTINCT project_id) AS total FROM api_costs') as cursor:
                row = await cursor.fetchone()
            return row['total'] if row and row['total'] is not None else 0
        finally:
            await db.close()

    async def get_monthly_summary(self) -> dict:
        db = await get_db()
        try:
            async with db.execute('''
                SELECT COALESCE(SUM(cost_usd), 0) as total_usd,
                       COALESCE(SUM(cost_usd * 1300), 0) as total_krw
                FROM api_costs
                WHERE timestamp >= date('now', 'start of month')
            ''') as cursor:
                row = await cursor.fetchone()
            total_usd = row['total_usd'] if row else 0.0
            total_krw = row['total_krw'] if row else 0.0
        finally:
            await db.close()

        video_count = await self.get_video_count()
        return {
            'total_usd': total_usd,
            'total_krw': total_krw,
            'per_video_krw': (total_krw / max(video_count, 1)),
            'breakdown': await self.get_breakdown(),
            'budget_remaining': self.monthly_budget - total_usd,
        }

    async def get_breakdown(self) -> list:
        db = await get_db()
        try:
            async with db.execute('''
                SELECT service, action, SUM(units) as total_units,
                       SUM(cost_usd) as total_usd, COUNT(*) as call_count
                FROM api_costs WHERE timestamp >= date('now', 'start of month')
                GROUP BY service, action ORDER BY total_usd DESC
            ''') as cursor:
                rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await db.close()

    async def check_alerts(self) -> list:
        summary = await self.get_monthly_summary()
        alerts = []
        if summary['total_usd'] > self.monthly_budget * 0.8:
            alerts.append({'level': 'warning', 'message': f'월 예산의 {summary["total_usd"]/self.monthly_budget*100:.0f}% 소진'})
        return alerts
