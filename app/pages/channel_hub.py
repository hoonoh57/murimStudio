from nicegui import ui
from app.db import get_db
from app.services.channel_service import ChannelService


async def channel_page():
    ui.label('📺 채널 관리 허브').classes('text-xl font-bold')
    ui.label('4개국 채널 관리 · 업로드 스케줄링').classes('text-sm text-gray-500 mt-1')

    channel_svc = ChannelService()

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

    # ─── 업로드 스케줄링 폼 ───
    ui.label('업로드 예약').classes('font-bold mt-6')

    db = await get_db()
    try:
        async with db.execute(
            'SELECT id, title FROM projects ORDER BY created_at DESC LIMIT 20'
        ) as cursor:
            projects = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    project_options = {str(p['id']): f"#{p['id']} {p['title']}" for p in projects}

    with ui.card().classes('w-full mt-2'):
        with ui.row().classes('w-full gap-4 items-end'):
            schedule_project = ui.select(
                project_options,
                value=str(projects[0]['id']) if projects else None,
                label='프로젝트',
            ).classes('flex-1')

            channel_codes = [ch['code'] for ch in channels]
            schedule_channels = ui.select(
                channel_codes,
                value=channel_codes,
                label='채널 (다중 선택)',
                multiple=True,
            ).classes('flex-1')

            ai_metadata = ui.checkbox('AI 메타데이터', value=True)

    # ─── 업로드 큐 테이블 ───
    ui.label('업로드 큐').classes('font-bold mt-6')

    upload_table = ui.table(
        columns=[
            {'field': 'id', 'label': 'ID'},
            {'field': 'project_id', 'label': 'Project'},
            {'field': 'channel_code', 'label': '채널'},
            {'field': 'title', 'label': '제목'},
            {'field': 'status', 'label': '상태'},
            {'field': 'scheduled_at', 'label': '예약시간'},
            {'field': 'uploaded_at', 'label': '업로드'},
        ],
        rows=[],
    ).classes('w-full mt-2')

    queue_status = ui.label('').classes('text-sm text-gray-500 mt-1')

    async def reload_uploads():
        rows = await channel_svc.get_upload_queue(30)
        upload_table.rows = rows
        queue_status.text = f'총 {len(rows)}개 업로드 항목'

    async def schedule_upload():
        if not schedule_project.value:
            ui.notify('프로젝트를 선택하세요', color='orange')
            return
        if not schedule_channels.value:
            ui.notify('채널을 선택하세요', color='orange')
            return

        ui.notify('업로드 예약 중...', color='blue')
        selected = schedule_channels.value if isinstance(schedule_channels.value, list) else [schedule_channels.value]

        result = await channel_svc.schedule_uploads(
            project_id=int(schedule_project.value),
            channel_codes=selected,
            use_ai_metadata=ai_metadata.value,
        )
        ui.notify(f'{len(result)}개 채널에 업로드 예약 완료', color='green')
        await reload_uploads()

    async def execute_pending():
        ui.notify('업로드 실행 중... (API 키 없으면 시뮬레이션)', color='blue')
        results = await channel_svc.execute_uploads()
        msg = f"업로드: {results['uploaded']}, 시뮬레이션: {results['simulated']}, 실패: {results['failed']}"
        ui.notify(msg, color='green' if results['failed'] == 0 else 'orange')
        await reload_uploads()

    with ui.row().classes('gap-2 mt-4'):
        ui.button('📤 업로드 예약', on_click=schedule_upload).props('color=primary')
        ui.button('🚀 대기 업로드 실행', on_click=execute_pending).props('color=positive')
        ui.button('🔄 새로고침', on_click=reload_uploads)

    ui.label('').classes('mt-2')
    ui.label('⚠️ YouTube API Key 미설정 시 시뮬레이션 모드로 동작합니다. OAuth2 설정은 별도 필요.').classes('text-xs text-gray-500')

    await reload_uploads()
