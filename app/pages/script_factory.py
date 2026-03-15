from nicegui import ui
from app.services.script_factory import ScriptFactory


async def script_page():
    ui.label('✍️ 스크립트 공장').classes('text-xl font-bold')
    ui.label('Claude Haiku 4.5 기반 무협 리캡 대본 생성').classes('text-sm text-gray-500 mt-1')

    factory = ScriptFactory()

    # ─── 생성 폼 ───
    with ui.card().classes('w-full mt-4'):
        ui.label('새 스크립트 생성').classes('font-bold')

        with ui.row().classes('w-full gap-4 items-end'):
            title_input = ui.input('작품명', value='화산귀환').classes('flex-1')
            episodes_input = ui.input('회차 범위', value='51~100화').classes('flex-1')

        with ui.row().classes('w-full gap-4 items-end'):
            duration_input = ui.number('길이(분)', value=10, min=3, max=30).classes('w-32')
            style_select = ui.select(
                ['긴장감+감동', '코미디+액션', '미스터리+반전', '감성+성장'],
                value='긴장감+감동',
                label='스타일',
            ).classes('flex-1')
            lang_select = ui.select(
                {'ko': '한국어', 'en': 'English', 'id': 'Indonesia', 'th': 'ไทย'},
                value='ko',
                label='언어',
            ).classes('w-40')

    # ─── 스크립트 목록 ───
    script_table = ui.table(
        columns=[
            {'field': 'id', 'label': 'ID', 'sortable': True},
            {'field': 'project_title', 'label': '작품명'},
            {'field': 'language', 'label': '언어'},
            {'field': 'status', 'label': '상태'},
            {'field': 'cost_usd', 'label': '비용'},
            {'field': 'created_at', 'label': '생성일'},
            {'field': 'snippet', 'label': '미리보기'},
        ],
        rows=[],
    ).classes('w-full mt-4')

    async def reload_scripts():
        scripts = await factory.list_scripts()
        script_table.rows = [
            {
                'id': s.get('id'),
                'project_title': s.get('project_title', ''),
                'language': s.get('language', ''),
                'status': s.get('status', ''),
                'cost_usd': f"${s.get('cost_usd', 0):.4f}",
                'created_at': (s.get('created_at', '') or '')[:19],
                'snippet': (s.get('snippet', '') or '').replace('\n', ' ')[:120],
            }
            for s in scripts
        ]

    async def create_script():
        ui.notify('스크립트 생성 중… (Claude API 호출)', color='blue')
        result = await factory.generate_script(
            title=title_input.value,
            episodes=episodes_input.value,
            duration_min=int(duration_input.value),
            style=style_select.value,
            language=lang_select.value,
        )
        await reload_scripts()

        if result.get('status') == 'error':
            ui.notify('스크립트 생성 실패 — 로그를 확인하세요', color='red')
        else:
            ui.notify(f'스크립트 생성 완료 (${result.get("cost_usd", 0):.4f})', color='green')

    with ui.row().classes('gap-2 mt-2'):
        ui.button('🤖 AI 스크립트 생성', on_click=create_script).props('color=primary')
        ui.button('🔄 목록 새로고침', on_click=reload_scripts)

    await reload_scripts()
