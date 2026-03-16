"""스크립트 상세 보기 · 편집 페이지"""

from nicegui import ui
from app.db import get_db


@ui.page('/script/{script_id}')
async def script_detail_page(script_id: int):
    with ui.header().classes('bg-gray-900 text-white items-center'):
        ui.label('⚔️ 무협 팩토리').classes('text-xl font-bold')
        ui.space()
        ui.button('← 스크립트 목록', on_click=lambda: ui.navigate.to('/')).props('flat color=white')

    # DB에서 스크립트 조회
    db = await get_db()
    try:
        async with db.execute(
            'SELECT s.id, s.project_id, s.language, s.content, s.status, s.cost_usd, '
            's.created_at, s.updated_at, p.title as project_title, p.episodes '
            'FROM scripts s LEFT JOIN projects p ON s.project_id = p.id '
            'WHERE s.id = ?',
            (script_id,),
        ) as cursor:
            row = await cursor.fetchone()

        # 같은 프로젝트의 다른 스크립트 (번역본 등)
        other_scripts = []
        if row:
            r = dict(row)
            async with db.execute(
                'SELECT s.id, s.language, s.status, s.cost_usd, s.created_at '
                'FROM scripts s WHERE s.project_id = ? AND s.id != ? '
                'ORDER BY s.created_at DESC',
                (r['project_id'], script_id),
            ) as cursor:
                other_scripts = [dict(x) for x in await cursor.fetchall()]
    finally:
        await db.close()

    if not row:
        ui.label(f'스크립트 #{script_id}를 찾을 수 없습니다.').classes('text-red-400 text-lg mt-4')
        return

    r = dict(row)

    # ─── 헤더 정보 ───
    ui.label(f'📝 스크립트 #{r["id"]}').classes('text-2xl font-bold mt-4')

    with ui.row().classes('w-full gap-4 mt-2'):
        with ui.card().classes('flex-1'):
            ui.label('작품명').classes('text-sm text-gray-500')
            ui.label(r.get('project_title', '알 수 없음')).classes('text-lg font-bold')
        with ui.card().classes('flex-1'):
            ui.label('언어').classes('text-sm text-gray-500')
            lang_names = {'ko': '한국어', 'en': 'English', 'id': 'Indonesia', 'th': 'ไทย'}
            ui.label(lang_names.get(r['language'], r['language'])).classes('text-lg font-bold')
        with ui.card().classes('flex-1'):
            ui.label('상태').classes('text-sm text-gray-500')
            color = 'text-green-400' if r['status'] == 'generated' else 'text-red-400'
            ui.label(r['status']).classes(f'text-lg font-bold {color}')
        with ui.card().classes('flex-1'):
            ui.label('비용').classes('text-sm text-gray-500')
            ui.label(f'${r["cost_usd"]:.4f}').classes('text-lg font-bold')
        with ui.card().classes('flex-1'):
            ui.label('생성일').classes('text-sm text-gray-500')
            ui.label(r.get('created_at', '')[:19]).classes('text-lg font-bold')

    # ─── 스크립트 내용 (편집 가능) ───
    ui.label('스크립트 내용').classes('text-lg font-bold mt-6 mb-2')
    ui.label('내용을 수정한 후 "저장" 버튼을 클릭하세요.').classes('text-xs text-gray-500 mb-1')

    editor = ui.textarea(
        value=r.get('content', ''),
    ).classes('w-full').style('min-height: 500px; font-family: monospace; font-size: 14px;')

    save_status = ui.label('').classes('text-sm mt-1')

    async def save_script():
        new_content = editor.value
        if not new_content.strip():
            ui.notify('내용이 비어있습니다.', color='red')
            return

        db2 = await get_db()
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            await db2.execute(
                'UPDATE scripts SET content = ?, updated_at = ? WHERE id = ?',
                (new_content, now, script_id),
            )
            await db2.commit()
            save_status.text = f'✅ 저장 완료 ({now[:19]})'
            save_status.classes('text-green-400', remove='text-red-400')
            ui.notify('스크립트가 저장되었습니다.', color='green')
        except Exception as e:
            save_status.text = f'❌ 저장 실패: {e}'
            save_status.classes('text-red-400', remove='text-green-400')
            ui.notify(f'저장 실패: {e}', color='red')
        finally:
            await db2.close()

    async def copy_to_clipboard():
        ui.run_javascript(f'navigator.clipboard.writeText({repr(editor.value)})')
        ui.notify('클립보드에 복사되었습니다.', color='blue')

    with ui.row().classes('gap-2 mt-2'):
        ui.button('💾 저장', on_click=save_script).props('color=primary')
        ui.button('📋 복사', on_click=copy_to_clipboard).props('color=grey')
        ui.button('← 목록으로', on_click=lambda: ui.navigate.to('/')).props('color=grey')

    # ─── 같은 프로젝트의 다른 버전 ───
    if other_scripts:
        ui.label('📚 같은 작품의 다른 스크립트').classes('text-lg font-bold mt-6 mb-2')
        for s in other_scripts:
            with ui.row().classes('items-center gap-3 mb-1'):
                lang_name = lang_names.get(s['language'], s['language'])
                ui.link(
                    f'#{s["id"]} — {lang_name} ({s["status"]}, ${s["cost_usd"]:.4f})',
                    f'/script/{s["id"]}',
                ).classes('text-blue-400')
                ui.label(s.get('created_at', '')[:19]).classes('text-sm text-gray-500')
