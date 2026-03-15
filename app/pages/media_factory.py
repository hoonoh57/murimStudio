from nicegui import ui

async def media_page():
    ui.label('미디어 공장').classes('text-xl font-bold')
    ui.label('알림: 이미지/음성 생성 대기 중').classes('mt-2')
    ui.button('미디어 처리 시작', on_click=lambda: ui.notify('미디어 처리 시작'))
