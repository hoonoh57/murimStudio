from nicegui import ui
from app.services.script_factory import ScriptFactory

async def script_page():
    ui.label('스크립트 공장').classes('text-xl font-bold')
    factory = ScriptFactory()

    script_table = ui.table(
        columns=[
            {'field': 'id', 'label': 'ID'},
            {'field': 'project_id', 'label': 'Project ID'},
            {'field': 'language', 'label': '언어'},
            {'field': 'status', 'label': '상태'},
            {'field': 'cost_usd', 'label': '비용(USD)'},
            {'field': 'created_at', 'label': '생성일'},
            {'field': 'snippet', 'label': '내용 미리보기'},
        ],
        rows=[],
    )

    async def reload_scripts():
        scripts = await factory.list_scripts()
        script_table.rows = [
            {
                'id': s.get('id'),
                'project_id': s.get('project_id'),
                'language': s.get('language'),
                'status': s.get('status'),
                'cost_usd': s.get('cost_usd'),
                'created_at': s.get('created_at'),
                'snippet': s.get('snippet', '').replace('\n', ' ')[:160],
            }
            for s in scripts
        ]

    async def create_script():
        ui.notify('스크립트 생성 중…', color='blue')
        await factory.generate_script('트렌드 스카우트 기반 무협 스크립트', topic='현재 트렌드 작품 상위 5개')
        await reload_scripts()
        ui.notify('스크립트 생성 완료', color='green')

    ui.button('새 스크립트 생성', on_click=create_script)
    await reload_scripts()
