"""백그라운드 스케줄러 — DB 초기화 + 주기적 트렌드 수집"""

import asyncio
import logging
from datetime import datetime, timezone

from app.db import init_db, get_db

logger = logging.getLogger(__name__)

# 수집 주기 (초) — 6시간
TREND_INTERVAL_SECONDS = 6 * 60 * 60

# GC 방지용 태스크 참조 보관
_background_tasks: list = []


async def start_background_tasks():
    """앱 시작 시 호출: DB 초기화 → 스케줄러 루프 시작"""
    await init_db()
    logger.info('Database initialized — starting background scheduler')

    # 백그라운드 태스크로 실행 (참조를 리스트에 저장하여 GC 방지)
    task = asyncio.create_task(_trend_collection_loop())
    _background_tasks.append(task)
    logger.info('Trend collection task registered (GC-safe)')


async def _trend_collection_loop():
    """6시간마다 트렌드를 수집하고 AI 랭킹을 실행합니다."""

    # 시작 시 첫 수집 (5초 대기 후 — 앱 완전 로드 대기)
    await asyncio.sleep(5)
    await _run_trend_collection()

    # 이후 주기적 실행
    while True:
        try:
            await asyncio.sleep(TREND_INTERVAL_SECONDS)
            await _run_trend_collection()
        except asyncio.CancelledError:
            logger.info('Trend collection loop cancelled')
            break
        except Exception as e:
            logger.error(f'Trend collection loop error: {e}')
            # 에러 시 5분 후 재시도
            await asyncio.sleep(300)


async def _run_trend_collection():
    """단일 트렌드 수집+랭킹 사이클"""
    from app.services.trend_scout import TrendScout

    logger.info('=== Scheduled trend collection starting ===')
    scout = TrendScout()

    try:
        # 1) 소스 수집
        raw_data = await scout.collect_all_sources()
        logger.info(f'Collected {len(raw_data)} raw trend items')

        # 2) AI 랭킹
        ranked = await scout.ai_rank_topics(raw_data)
        logger.info(f'AI ranked {len(ranked)} items')

        # 3) 결과 DB 저장
        db = await get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            for i, item in enumerate(ranked):
                await db.execute(
                    '''INSERT INTO trend_results
                       (rank, title, score, reason, episode_range, target_audience, collected_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (
                        i + 1,
                        item.get('title', ''),
                        int(item.get('score', 0)),
                        item.get('reason', ''),
                        item.get('episode_range', ''),
                        item.get('target_audience', ''),
                        now,
                    ),
                )
            await db.commit()
            logger.info(f'Saved {len(ranked)} ranked results to trend_results')
        finally:
            await db.close()

        # 4) 오래된 데이터 정리 (30일 이상)
        await _cleanup_old_data()

    except Exception as e:
        logger.error(f'Trend collection failed: {e}')


async def _cleanup_old_data():
    """30일 이상 된 캐시/결과 데이터를 삭제합니다."""
    db = await get_db()
    try:
        await db.execute(
            "DELETE FROM trend_results WHERE collected_at < datetime('now', '-30 days')"
        )
        await db.execute(
            "DELETE FROM trend_cache WHERE collected_at < datetime('now', '-30 days')"
        )
        await db.commit()
        logger.debug('Cleaned up old trend data (>30 days)')
    except Exception as e:
        logger.warning(f'Trend data cleanup error: {e}')
    finally:
        await db.close()
