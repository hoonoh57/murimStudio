"""스크립트 공장 UI — 생성 + 번역 + 목록 관리"""

from nicegui import ui
from app.services.script_factory import ScriptFactory


async def script_page():
    ui.label('✍️ 스크립트 공장').classes('text-xl font-bold')
    ui.label('Gemini AI 기반 무협 리캡 대본 생성 · 다국어 번역').classes(
        'text-sm text-gray-500 mt-1'
    )

    factory = ScriptFactory()

    # ══════════════════════════════════════
    #  생성 폼
    # ══════════════════════════════════════
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

    # ══════════════════════════════════════
    #  번역 폼
    # ══════════════════════════════════════
    with ui.card().classes('w-full mt-4'):
        ui.label('스크립트 번역').classes('font-bold')
        ui.label('기존 스크립트를 선택한 후, 번역할 언어를 지정하세요.').classes(
            'text-sm text-gray-500'
        )

        with ui.row().classes('w-full gap-4 items-end'):
            translate_id_input = ui.number(
                '스크립트 ID', value=0, min=0, format='%d'
            ).classes('w-40')

            translate_lang_select = ui.select(
                {
                    'en': 'English',
                    'ko': '한국어',
                    'id': 'Bahasa Indonesia',
                    'th': 'ภาษาไทย',
                },
                value=['en'],
                multiple=True,
                label='번역 대상 언어 (복수 선택)',
            ).classes('flex-1')

    # ══════════════════════════════════════
    #  스크립트 목록 (클릭 가능)
    # ══════════════════════════════════════
    ui.label('스크립트 목록').classes('text-lg font-bold mt-6 mb-2')
    ui.label('💡 ID를 클릭하면 전체 내용을 보고 편집할 수 있습니다').classes('text-xs text-gray-500 mb-1')

    script_container = ui.column().classes('w-full')

    status_label = ui.label('').classes('text-sm text-gray-500 mt-2')

    def build_script_table(scripts):
        """스크립트 목록을 클릭 가능한 테이블로 렌더링"""
        script_container.clear()
        with script_container:
            with ui.element('table').classes('w-full'):
                with ui.element('thead'):
                    with ui.element('tr').classes('text-left text-gray-400 text-sm'):
                        for col in ['ID', '작품명', '언어', '상태', '비용', '생성일', '미리보기']:
                            with ui.element('th').classes('p-2'):
                                ui.label(col)
                with ui.element('tbody'):
                    for s in scripts:
                        sid = s.get('id', 0)
                        with ui.element('tr').classes('border-t border-gray-700 hover:bg-gray-800'):
                            with ui.element('td').classes('p-2'):
                                ui.link(
                                    f'#{sid}',
                                    f'/script/{sid}',
                                ).classes('text-blue-400 hover:text-blue-300 font-bold no-underline')
                            with ui.element('td').classes('p-2'):
                                ui.label(s.get('project_title', ''))
                            with ui.element('td').classes('p-2'):
                                ui.label(s.get('language', ''))
                            with ui.element('td').classes('p-2'):
                                status = s.get('status', '')
                                color = 'text-green-400' if status == 'generated' else 'text-red-400'
                                ui.label(status).classes(color)
                            with ui.element('td').classes('p-2'):
                                ui.label(f"${s.get('cost_usd', 0):.4f}")
                            with ui.element('td').classes('p-2'):
                                ui.label((s.get('created_at', '') or '')[:19]).classes('text-sm')
                            with ui.element('td').classes('p-2 max-w-xs truncate'):
                                snippet = (s.get('snippet', '') or '').replace('\n', ' ')[:100]
                                ui.label(snippet).classes('text-sm text-gray-400')

    async def reload_scripts():
        scripts = await factory.list_scripts()
        build_script_table(scripts)
        status_label.text = f'총 {len(scripts)}개 스크립트'

    async def create_script():
        ui.notify('스크립트 생성 중… (AI API 호출)', color='blue')
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
            cost = result.get('cost_usd', 0)
            ui.notify(f'스크립트 생성 완료 (${cost:.4f})', color='green')

    async def translate_scripts():
        script_id = int(translate_id_input.value)
        target_langs = translate_lang_select.value

        if script_id <= 0:
            ui.notify('유효한 스크립트 ID를 입력하세요.', color='orange')
            return
        if not target_langs:
            ui.notify('번역할 언어를 1개 이상 선택하세요.', color='orange')
            return

        ui.notify(
            f'스크립트 #{script_id} → {", ".join(target_langs)} 번역 중…',
            color='blue',
        )

        results = await factory.translate_script(
            script_id=script_id,
            target_languages=target_langs,
        )

        if not results:
            ui.notify('스크립트를 찾을 수 없습니다. ID를 확인하세요.', color='red')
            return

        total_cost = sum(r.get('cost_usd', 0) for r in results)
        errors = [r for r in results if r.get('status') == 'error']

        await reload_scripts()

        if errors:
            ui.notify(
                f'{len(results) - len(errors)}개 완료, {len(errors)}개 실패 (${total_cost:.4f})',
                color='orange',
            )
        else:
            ui.notify(
                f'{len(results)}개 언어 번역 완료 (${total_cost:.4f})',
                color='green',
            )

    with ui.row().classes('gap-2 mt-3'):
        ui.button('🤖 AI 스크립트 생성', on_click=create_script).props('color=primary')
        ui.button('🌐 번역 실행', on_click=translate_scripts).props('color=secondary')
        ui.button('🔄 목록 새로고침', on_click=reload_scripts)

    await reload_scripts()
