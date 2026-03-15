from nicegui import ui
from app.db import get_db


async def channel_page():
    ui.label('📺 채널 관리 허브').classes('text-xl font-bold')
    ui.label('4개국 채널 관리 · 업로드 스케줄링').classes('text-sm text-gray-500 mt-1')

    # ─── 채널 목록 ───
    db = await get_db()
    try:
        async with db.execute('SELECT * FROM channels ORDER BY code') as cursor:
            channels = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    ui.label('등록된 채널').classes('font-bold mt-4')
    ui.table(
        columns=[
            {'field': 'code', 'label': '코드'},
            {'field': 'name', 'label': '채널명'},
            {'field': 'timezone', 'label': '시간대'},
            {'field': 'peak_hour', 'label': '피크시간'},
            {'field': 'youtube_channel_id', 'label': 'YouTube ID'},
        ],
        rows=channels,
    ).classes('w-full')

    # ─── 업로드 큐 ───
    ui.label('업로드 큐').classes('font-bold mt-6')

    upload_table = ui.table(
        columns=[
            {'field': 'id', 'label': 'ID'},
            {'field': 'project_id', 'label': 'Project'},
            {'field': 'channel_code', 'label': '채널'},
            {'field': 'title', 'label': '제목'},
            {'field': 'status', 'label': '상태'},
            {'field': 'scheduled_at', 'label': '예약시간'},
        ],
        rows=[],
    ).classes('w-full mt-2')

    async def reload_uploads():
        db = await get_db()
        try:
            async with db.execute(
                'SELECT id, project_id, channel_code, title, status, scheduled_at FROM uploads ORDER BY created_at DESC LIMIT 30'
            ) as cursor:
                rows = [dict(r) for r in await cursor.fetchall()]
            upload_table.rows = rows
        finally:
            await db.close()

    async def schedule_upload():
        """선택한 프로젝트를 4개 채널에 업로드 예약"""
        db = await get_db()
        try:
            async with db.execute(
                'SELECT id, title FROM projects ORDER BY created_at DESC LIMIT 1'
            ) as cursor:
                project = await cursor.fetchone()

            if not project:
                ui.notify('프로젝트가 없습니다', color='orange')
                return

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()

            for ch in channels:
                await db.execute(
                    '''INSERT INTO uploads
                       (project_id, channel_code, title, status, created_at, updated_at)
                       VALUES (?, ?, ?, 'pending', ?, ?)''',
                    (project['id'], ch['code'], f"{project['title']} ({ch['code'].upper()})", now, now),
                )
            await db.commit()
            ui.notify(f'{len(channels)}개 채널에 업로드 예약 완료', color='green')
        finally:
            await db.close()
        await reload_uploads()

    with ui.row().classes('gap-2 mt-2'):
        ui.button('📤 최신 프로젝트 일괄 예약', on_click=schedule_upload).props('color=primary')
        ui.button('🔄 새로고침', on_click=reload_uploads)

    ui.label('').classes('mt-4')
    ui.label('※ 실제 YouTube Data API 업로드는 향후 구현 예정').classes('text-xs text-gray-500')

    await reload_uploads()
