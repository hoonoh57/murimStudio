from nicegui import ui
from app.db import get_db


async def media_page():
    ui.label('🎨 미디어 공장').classes('text-xl font-bold')
    ui.label('이미지 생성 · 음성 합성 · 영상 조립').classes('text-sm text-gray-500 mt-1')

    # ─── 프로젝트 선택 ───
    db = await get_db()
    try:
        async with db.execute(
            'SELECT id, title FROM projects ORDER BY created_at DESC LIMIT 20'
        ) as cursor:
            projects = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    project_options = {str(p['id']): f"#{p['id']} {p['title']}" for p in projects}

    if not project_options:
        ui.label('프로젝트가 없습니다. 먼저 스크립트를 생성하세요.').classes('text-gray-500 mt-4')
        return

    with ui.card().classes('w-full mt-4'):
        ui.label('프로젝트 선택').classes('font-bold')
        project_select = ui.select(
            project_options,
            value=str(projects[0]['id']) if projects else None,
            label='프로젝트',
        ).classes('w-full')

    # ─── 미디어 현황 ───
    media_table = ui.table(
        columns=[
            {'field': 'id', 'label': 'ID'},
            {'field': 'type', 'label': '유형'},
            {'field': 'status', 'label': '상태'},
            {'field': 'prompt', 'label': '프롬프트'},
            {'field': 'path', 'label': '경로'},
            {'field': 'created_at', 'label': '생성일'},
        ],
        rows=[],
    ).classes('w-full mt-4')

    async def reload_media():
        if not project_select.value:
            return
        db = await get_db()
        try:
            async with db.execute(
                '''SELECT id, type, status, substr(prompt, 1, 100) as prompt,
                          path, created_at
                   FROM media_items WHERE project_id = ?
                   ORDER BY created_at DESC''',
                (int(project_select.value),),
            ) as cursor:
                rows = [dict(r) for r in await cursor.fetchall()]
            media_table.rows = rows
        finally:
            await db.close()

    async def generate_placeholder_images():
        """스크립트에서 이미지 프롬프트를 추출하여 media_items로 등록 (실제 생성은 TODO)"""
        if not project_select.value:
            ui.notify('프로젝트를 선택하세요', color='orange')
            return

        pid = int(project_select.value)
        db = await get_db()
        try:
            async with db.execute(
                'SELECT content FROM scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1',
                (pid,),
            ) as cursor:
                row = await cursor.fetchone()

            if not row or not row['content']:
                ui.notify('스크립트가 없습니다', color='orange')
                return

            content = row['content']
            # [이미지 프롬프트: ...] 태그 추출
            import re
            prompts = re.findall(r'\[이미지 프롬프트:\s*(.+?)\]', content)

            if not prompts:
                ui.notify('스크립트에서 이미지 프롬프트를 찾을 수 없습니다', color='orange')
                return

            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            for p in prompts:
                await db.execute(
                    '''INSERT INTO media_items
                       (project_id, type, prompt, status, path, created_at, updated_at)
                       VALUES (?, 'image', ?, 'pending', '', ?, ?)''',
                    (pid, p.strip(), now, now),
                )
            await db.commit()
            ui.notify(f'{len(prompts)}개 이미지 프롬프트 등록 완료', color='green')
        finally:
            await db.close()

        await reload_media()

    with ui.row().classes('gap-2 mt-2'):
        ui.button('🖼️ 이미지 프롬프트 추출', on_click=generate_placeholder_images).props('color=primary')
        ui.button('🔄 새로고침', on_click=reload_media)

    ui.label('').classes('mt-4')
    ui.label('※ 실제 이미지 생성(Midjourney/ComfyUI), 음성 합성(ElevenLabs), 영상 조립(FFmpeg)은 향후 구현 예정').classes('text-xs text-gray-500')

    project_select.on('update:model-value', lambda: reload_media())
    await reload_media()
