"""비용 추적 서비스 — API 호출 비용 기록·조회·알림"""

import logging
from datetime import datetime, timezone
from app.db import get_db

logger = logging.getLogger(__name__)


class CostTracker:
    def __init__(self, monthly_budget: float = 200.0):
        self.monthly_budget = monthly_budget

    # ─── 기록 ───

    async def log_cost(
        self,
        service: str,
        action: str,
        units: float,
        cost_usd: float,
        project_id: str = '',
    ) -> None:
        db = await get_db()
        try:
            await db.execute(
                '''INSERT INTO api_costs
                   (service, action, units, cost_usd, cost_krw, project_id, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    service,
                    action,
                    units,
                    round(cost_usd, 6),
                    round(cost_usd * 1300, 2),
                    project_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            await db.commit()
            logger.debug(f'Logged cost: {service}/{action} ${cost_usd:.6f}')
        finally:
            await db.close()

    # ─── 조회 ───

    async def get_monthly_summary(self) -> dict:
        db = await get_db()
        try:
            async with db.execute('''
                SELECT
                    COALESCE(SUM(cost_usd), 0) as total_usd,
                    COALESCE(SUM(cost_krw), 0) as total_krw,
                    COUNT(*) as total_calls,
                    COUNT(DISTINCT project_id) as project_count
                FROM api_costs
                WHERE timestamp >= date('now', 'start of month')
            ''') as cursor:
                row = await cursor.fetchone()

            total_usd = row['total_usd'] if row else 0.0
            total_krw = row['total_krw'] if row else 0.0
            total_calls = row['total_calls'] if row else 0
            project_count = row['project_count'] if row else 0

            return {
                'total_usd': total_usd,
                'total_krw': total_krw,
                'total_calls': total_calls,
                'project_count': project_count,
                'per_video_usd': total_usd / max(project_count, 1),
                'per_video_krw': total_krw / max(project_count, 1),
                'budget_usd': self.monthly_budget,
                'budget_remaining_usd': self.monthly_budget - total_usd,
                'budget_used_pct': (total_usd / self.monthly_budget * 100)
                                   if self.monthly_budget > 0 else 0,
                'breakdown': await self.get_breakdown(),
            }
        finally:
            await db.close()

    async def get_breakdown(self) -> list:
        db = await get_db()
        try:
            async with db.execute('''
                SELECT service, action,
                       SUM(units) as total_units,
                       SUM(cost_usd) as total_usd,
                       SUM(cost_krw) as total_krw,
                       COUNT(*) as call_count
                FROM api_costs
                WHERE timestamp >= date('now', 'start of month')
                GROUP BY service, action
                ORDER BY total_usd DESC
            ''') as cursor:
                rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await db.close()

    async def get_recent_logs(self, limit: int = 30) -> list:
        db = await get_db()
        try:
            async with db.execute('''
                SELECT service, action, units, cost_usd, cost_krw,
                       project_id, timestamp
                FROM api_costs
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,)) as cursor:
                rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await db.close()

    # ─── 알림 ───

    async def check_alerts(self) -> list:
        summary = await self.get_monthly_summary()
        alerts = []
        pct = summary['budget_used_pct']
        if pct >= 100:
            alerts.append({
                'level': 'error',
                'message': f'월 예산 초과! ({pct:.0f}% 사용, ${summary["total_usd"]:.2f}/${self.monthly_budget})',
            })
        elif pct >= 80:
            alerts.append({
                'level': 'warning',
                'message': f'월 예산 {pct:.0f}% 소진 (${summary["total_usd"]:.2f}/${self.monthly_budget})',
            })
        return alerts
