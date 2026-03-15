import asyncio
import logging
from app.db import init_db

logger = logging.getLogger(__name__)


async def start_background_tasks():
    await init_db()
    logger.info('Background tasks started — DB ready')
    # 향후 주기적 트렌드 수집 등 추가
    await asyncio.sleep(0)
