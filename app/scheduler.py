import asyncio
from app.db import init_db

async def start_background_tasks():
    await init_db()
    # 스케줄된 백그라운드 작업을 이곳에 추가
    await asyncio.sleep(0)
