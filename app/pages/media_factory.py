from nicegui import ui
from app.db import get_db
from app.services.media_service import MediaService


async def media_page():
    ui.label('🎨 미디어 공장').classes('text-xl font-bold')
    ui.label('이미지 생성 · 음성 합성 · 영상 조립').classes('text-sm text-gray-500 mt-1')

    media_svc = MediaService()

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

    # ─── API 상태 카드 ───
    with ui.row().classes('w-full gap-4 mt-4'):
        with ui.card().classes('flex-1'):
            ui.label('🖼️ Midjourney').classes('font-bold')
            mj_status = ui.label('API URL: ' + ('설정됨 ✅' if media_svc.midjourney_url else '미설정 ⚠️'))
            mj_status.classes('text-sm')
        with ui.card().classes('flex-1'):
            ui.label('🔊 ElevenLabs').classes('font-bold')
            el_status = ui.label('API Key: ' + ('설정됨 ✅' if media_svc.elevenlabs_key else '미설정 ⚠️'))
            el_status.classes('text-sm')
        with ui.card().classes('flex-1'):
            ui.label('🎬 FFmpeg').classes('font-bold')
            import subprocess
            try:
                subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
                ff_label = '설치됨 ✅'
            except (subprocess.CalledProcessError, FileNotFoundError):
                ff_label = '미설치 ⚠️ (매니페스트로 대체)'
            ui.label(ff_label).classes('text-sm')

    # ─── 미디어 테이블 ───
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

    status_label = ui.label('').classes('text-sm text-gray-500 mt-2')

    async def reload_media():
        if not project_select.value:
            return
        db = await get_db()
        try:
            async with db.execute(
                '''SELECT id, type, status, substr(prompt, 1, 80) as prompt,
                          substr(path, -30) as path, created_at
                   FROM media_items WHERE project_id = ?
                   ORDER BY created_at DESC''',
                (int(project_select.value),),
            ) as cursor:
                rows = [dict(r) for r in await cursor.fetchall()]
            media_table.rows = rows
            status_label.text = f'총 {len(rows)}개 미디어 아이템'
        finally:
            await db.close()

    async def step1_extract():
        if not project_select.value:
            ui.notify('프로젝트를 선택하세요', color='orange')
            return
        ui.notify('이미지 프롬프트 추출 중...', color='blue')
        prompts = await media_svc.extract_prompts(int(project_select.value))
        if prompts:
            ui.notify(f'{len(prompts)}개 이미지 프롬프트 등록 완료', color='green')
        else:
            ui.notify('스크립트에서 이미지 프롬프트를 찾을 수 없습니다', color='orange')
        await reload_media()

    async def step2_images():
        if not project_select.value:
            ui.notify('프로젝트를 선택하세요', color='orange')
            return
        ui.notify('이미지 생성 중... (API 키 없으면 플레이스홀더)', color='blue')
        results = await media_svc.generate_images(int(project_select.value))
        ui.notify(
            f"이미지: 성공 {results['success']}, 실패 {results['failed']}, 스킵 {results['skipped']}",
            color='green' if results['failed'] == 0 else 'orange',
        )
        await reload_media()

    async def step3_tts():
        if not project_select.value:
            ui.notify('프로젝트를 선택하세요', color='orange')
            return
        ui.notify('TTS 음성 합성 중...', color='blue')
        results = await media_svc.generate_tts(int(project_select.value))
        if results['status'] in ('done', 'placeholder'):
            ui.notify(f"TTS 완료: {results['path']}", color='green')
        else:
            ui.notify(f"TTS 실패: {results['status']}", color='red')
        await reload_media()

    async def step4_video():
        if not project_select.value:
            ui.notify('프로젝트를 선택하세요', color='orange')
            return
        ui.notify('영상 조립 중...', color='blue')
        results = await media_svc.assemble_video(int(project_select.value))
        msg = f"상태: {results['status']}, 이미지: {results['images']}장"
        if results['path']:
            msg += f", 출력: {results['path']}"
        ui.notify(msg, color='green' if results['status'] in ('done', 'manifest_created') else 'orange')
        await reload_media()

    # ─── 4단계 파이프라인 버튼 ───
    ui.label('미디어 파이프라인').classes('font-bold mt-6')
    with ui.row().classes('gap-2 mt-2'):
        ui.button('① 프롬프트 추출', on_click=step1_extract).props('color=primary')
        ui.button('② 이미지 생성', on_click=step2_images).props('color=secondary')
        ui.button('③ TTS 음성', on_click=step3_tts).props('color=accent')
        ui.button('④ 영상 조립', on_click=step4_video).props('color=positive')

    with ui.row().classes('gap-2 mt-2'):
        ui.button('🔄 새로고침', on_click=reload_media)

    ui.label('').classes('mt-2')
    ui.label('⚠️ API 키가 미설정인 서비스는 플레이스홀더로 대체됩니다.').classes('text-xs text-gray-500')

    project_select.on('update:model-value', lambda: reload_media())
    await reload_media()
