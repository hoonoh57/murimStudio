"""영상 조립 UI 패널 – v3 (스크립트 ID별 관리)"""

import asyncio
import logging
from pathlib import Path

from nicegui import ui

from app.services.video_assembler import VideoAssembler
from app.services.image_generator import ImageGenerator
from app.db import get_db

logger = logging.getLogger(__name__)

assembler = VideoAssembler()
img_gen = ImageGenerator()


def create():
    state = {"script_id": 0, "audio_path": "", "audio_duration": 0}

    ui.label("🎬 영상 자동 조립").classes("text-2xl font-bold mb-2")
    ui.label("이미지 + TTS 오디오 → MP4 영상 자동 생성").classes("text-sm text-gray-400 mb-4")

    # ────────────────────────────────────────────
    # 1. 스크립트 선택 (영상 기준)
    # ────────────────────────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("📋 스크립트 선택").classes("text-lg font-semibold")
        ui.label("영상을 만들 스크립트를 선택하면 해당 이미지와 오디오를 자동으로 찾습니다.").classes("text-xs text-gray-500 mb-2")

        script_select = ui.select(options={}, label="스크립트 선택").classes("w-full")
        script_status = ui.label("").classes("text-sm mt-1")

        async def load_scripts():
            db = await get_db()
            rows = await db.execute("""
                SELECT s.id, COALESCE(p.title, '제목없음') as title,
                       s.language, substr(s.content, 1, 60) as preview
                FROM scripts s
                LEFT JOIN projects p ON s.project_id = p.id
                WHERE s.content IS NOT NULL AND s.content != ''
                ORDER BY s.id DESC LIMIT 20
            """)
            scripts = await rows.fetchall()
            options = {}
            for s in scripts:
                img_count = len(img_gen.get_images_for_script(s[0]))
                audio_exists = any(Path("output/audio").glob(f"script_{s[0]}_*")) if Path("output/audio").exists() else False
                badges = []
                if img_count > 0:
                    badges.append(f"🖼️{img_count}")
                if audio_exists:
                    badges.append("🔊")
                badge_str = f" [{' '.join(badges)}]" if badges else ""
                options[s[0]] = f"[ID:{s[0]}] {s[1]} ({s[2]}){badge_str} – {s[3]}..."
            script_select.options = options
            script_select.update()

        def on_script_change(e):
            sid = e.value if hasattr(e, 'value') else e
            if not sid:
                return
            state["script_id"] = int(sid)
            refresh_audio()
            refresh_images()

        script_select.on_value_change(on_script_change)
        ui.button("🔄 새로고침", on_click=load_scripts).props("outline size=sm")

    # ────────────────────────────────────────────
    # 2. 오디오 선택
    # ────────────────────────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("🔊 오디오").classes("text-lg font-semibold")
        audio_container = ui.column().classes("w-full")
        audio_player = ui.column().classes("w-full mt-2")
        selected_audio_label = ui.label("⚠️ 오디오를 선택하세요").classes("text-yellow-400 mt-2 font-semibold")

        def refresh_audio():
            audio_container.clear()
            sid = state["script_id"]
            audio_dir = Path("output/audio")

            with audio_container:
                if not audio_dir.exists():
                    ui.label("⚠️ 오디오 없음").classes("text-yellow-400")
                    return

                # 현재 스크립트 오디오 우선
                script_audios = sorted(audio_dir.glob(f"script_{sid}_*"), key=lambda f: f.stat().st_mtime, reverse=True)
                other_audios = sorted(
                    [f for f in audio_dir.glob("script_*.mp3") if not f.name.startswith(f"script_{sid}_") and f.stat().st_size > 100],
                    key=lambda f: f.stat().st_mtime, reverse=True,
                )

                if script_audios:
                    ui.label(f"📌 스크립트 ID:{sid} 오디오").classes("font-semibold text-green-300 mb-1")
                    for af in script_audios:
                        _render_audio_row(af, primary=True)

                if other_audios:
                    ui.label("📂 다른 스크립트 오디오").classes("font-semibold text-gray-400 mt-3 mb-1")
                    for af in other_audios[:5]:
                        _render_audio_row(af, primary=False)

                if not script_audios and not other_audios:
                    ui.label("⚠️ 오디오 파일이 없습니다. TTS 탭에서 먼저 생성하세요.").classes("text-yellow-400")

        def _render_audio_row(af: Path, primary: bool):
            size_kb = af.stat().st_size / 1024
            dur = assembler.get_audio_duration(str(af))
            parts = af.stem.split("_")
            s_id = parts[1] if len(parts) > 1 else "?"
            lang = parts[2] if len(parts) > 2 else "?"
            voice = parts[3] if len(parts) > 3 else "?"

            bg = "bg-gray-700" if primary else ""
            with ui.card().classes(f"w-full p-2 mb-1 {bg}"):
                with ui.row().classes("items-center justify-between w-full"):
                    with ui.column().classes("gap-0"):
                        ui.label(f"{'📌' if primary else '📄'} ID:{s_id} | {lang} | {voice}").classes("font-semibold text-sm")
                        ui.label(f"{af.name} · {size_kb:.0f}KB · {dur:.1f}초 ({dur/60:.1f}분)").classes("text-xs text-gray-400")
                    with ui.row().classes("gap-1"):
                        def make_play(path=str(af)):
                            def play():
                                audio_player.clear()
                                with audio_player:
                                    ui.audio(path).classes("w-full max-w-lg")
                            return play

                        def make_select(path=str(af), d=dur, name=af.name):
                            def select():
                                state["audio_path"] = path
                                state["audio_duration"] = d
                                selected_audio_label.text = f"✅ 선택됨: {name} ({d:.1f}초, {d/60:.1f}분)"
                                selected_audio_label.classes(replace="text-green-400 mt-2 font-semibold")
                                refresh_images()
                            return select

                        ui.button("▶", on_click=make_play()).props("dense flat size=sm")
                        ui.button("선택", on_click=make_select()).props("dense color=primary size=sm")

    # ────────────────────────────────────────────
    # 3. 이미지 확인
    # ────────────────────────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("🖼️ 사용할 이미지").classes("text-lg font-semibold")
        image_container = ui.column().classes("w-full")

        def refresh_images():
            image_container.clear()
            sid = state["script_id"]
            paths = img_gen.get_images_for_script(sid) if sid else []

            with image_container:
                if not sid:
                    ui.label("⚠️ 스크립트를 먼저 선택하세요.").classes("text-yellow-400")
                    return
                if not paths:
                    ui.label(f"⚠️ 스크립트 ID:{sid}의 이미지가 없습니다. 이미지 탭에서 생성하세요.").classes("text-yellow-400")
                    return

                ui.label(f"✅ {len(paths)}장 이미지 (script_{sid}/ 폴더)").classes("text-green-400 mb-2")

                if state["audio_duration"] > 0:
                    dur_per = state["audio_duration"] / len(paths)
                    if dur_per > 60:
                        ui.label(f"⚠️ 이미지당 {dur_per:.0f}초 – 이미지를 더 추가하세요!").classes("text-red-400 font-semibold")
                    elif dur_per > 30:
                        ui.label(f"⚠️ 이미지당 {dur_per:.0f}초 – 권장: 15~30초").classes("text-yellow-400")
                    else:
                        ui.label(f"✅ 이미지당 약 {dur_per:.1f}초").classes("text-gray-400")

                with ui.row().classes("gap-2 flex-wrap"):
                    for p in paths:
                        name = Path(p).name
                        with ui.column().classes("gap-0"):
                            ui.image(f"/static/images/script_{sid}/{name}").classes("w-32 h-20 rounded object-cover")
                            ui.label(name).classes("text-xs text-gray-500")

        ui.button("🔄 이미지 새로고침", on_click=refresh_images).props("outline size=sm")

    # ────────────────────────────────────────────
    # 4. 조립 설정 & 실행
    # ────────────────────────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("⚙️ 영상 설정").classes("text-lg font-semibold")
        with ui.row().classes("gap-4 items-end"):
            transition_select = ui.select(
                options={"fade": "페이드 전환", "none": "전환 없음 (빠름)"},
                value="fade", label="전환 효과",
            ).classes("w-48")
            fade_input = ui.number(label="페이드 시간(초)", value=0.5, min=0.1, max=2.0, step=0.1).classes("w-36")

        progress_label = ui.label("").classes("text-sm text-gray-400 mt-2")
        progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full mt-1")
        progress_bar.visible = False

    result_container = ui.column().classes("w-full gap-3 mt-2")

    async def do_assemble():
        sid = state["script_id"]
        if not sid:
            ui.notify("스크립트를 선택하세요", type="warning")
            return
        if not state["audio_path"]:
            ui.notify("오디오 파일을 선택하세요", type="warning")
            return

        images = img_gen.get_images_for_script(sid)
        if not images:
            ui.notify("이미지가 없습니다", type="warning")
            return

        output_name = f"script_{sid}_video.mp4"

        progress_bar.visible = True
        progress_bar.value = 0.1
        progress_label.text = f"🎬 영상 조립 중... ({len(images)}장 이미지, 1~5분 소요)"

        result = await assembler.assemble(
            audio_path=state["audio_path"],
            image_paths=images,
            output_name=output_name,
            transition=transition_select.value,
            fade_duration=fade_input.value or 0.5,
        )

        progress_bar.value = 1.0

        result_container.clear()
        with result_container:
            if result["success"]:
                size_mb = result["file_size"] / 1024 / 1024
                with ui.card().classes("w-full p-4 bg-gray-800"):
                    ui.label("✅ 영상 생성 완료!").classes("text-xl font-bold text-green-400")
                    ui.label(
                        f"📁 {result['path']}\n"
                        f"⏱️ {result['duration']:.1f}초 ({result['duration']/60:.1f}분) | "
                        f"📦 {size_mb:.1f}MB | "
                        f"🖼️ {result['num_images']}장 (장당 {result['duration_per_image']}초)"
                    ).classes("text-sm text-gray-300 mt-2 whitespace-pre-line")
                    ui.video(result["url"]).classes("w-full max-w-3xl mt-4")
                progress_label.text = f"🎉 완료!"
                ui.notify(f"영상 생성 완료: {size_mb:.1f}MB", type="positive")
            else:
                ui.label(f"❌ 실패: {result.get('error')}").classes("text-red-400 text-lg")
                progress_label.text = "❌ 실패"

        progress_bar.visible = False

    ui.button("🚀 영상 조립 시작", on_click=do_assemble).props("color=positive size=lg")

    asyncio.ensure_future(load_scripts())
