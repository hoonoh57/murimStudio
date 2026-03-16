import os
from dotenv import load_dotenv
load_dotenv()

from nicegui import ui, app
from app.pages import (
    dashboard, trend_scout, script_factory, media_factory,
    channel_hub, cost_tracker, trend_detail, script_detail, tts_test
)
from app.pages import image_panel  # ← 추가


@ui.page('/')
async def index():
    with ui.header().classes('bg-gray-900 text-white items-center'):
        ui.label('⚔️ 무협 팩토리').classes('text-xl font-bold')
        ui.space()
        ui.label('v1.3').classes('text-sm text-gray-400')  # 버전 업

    with ui.tabs().classes('w-full') as tabs:
        tab_dash    = ui.tab('📊 대시보드')
        tab_trend   = ui.tab('🔍 트렌드')
        tab_script  = ui.tab('✍️ 스크립트')
        tab_tts     = ui.tab('🔊 TTS')
        tab_image   = ui.tab('🎨 이미지')   # ← 새 탭
        tab_media   = ui.tab('🎬 미디어')
        tab_channel = ui.tab('📺 채널')
        tab_cost    = ui.tab('💰 비용')

    with ui.tab_panels(tabs, value=tab_dash).classes('w-full'):
        with ui.tab_panel(tab_dash):
            await dashboard.dashboard_page()
        with ui.tab_panel(tab_trend):
            await trend_scout.trend_page()
        with ui.tab_panel(tab_script):
            await script_factory.script_page()
        with ui.tab_panel(tab_tts):
            tts_test.create()
        with ui.tab_panel(tab_image):     # ← 이미지 패널 연결
            image_panel.create()
        with ui.tab_panel(tab_media):
            await media_factory.media_page()
        with ui.tab_panel(tab_channel):
            await channel_hub.channel_page()
        with ui.tab_panel(tab_cost):
            await cost_tracker.cost_page()


@app.on_startup
async def startup():
    from app.scheduler import start_background_tasks
    await start_background_tasks()


# static 폴더 마운트 (이미지 서빙)
app.add_static_files('/static', 'static')


if __name__ == '__main__':
    ui.run(
        title='무협 팩토리', port=8080, favicon='⚔️',
        dark=True, reload=False,
        storage_secret=os.getenv('STORAGE_SECRET', 'change-me')
    )
