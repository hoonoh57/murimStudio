from nicegui import ui

async def script_page():
    ui.label('스크립트 공장').classes('text-xl font-bold')
    ui.button('새 스크립트 생성', on_click=lambda: ui.notify('생성 요청'))
    ui.label('샘플 스크립트 상태: 0개').classes('mt-2')
