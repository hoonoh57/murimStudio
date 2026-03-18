"""영상 조립 UI 패널"""

import asyncio
import logging
from pathlib import Path

from nicegui import ui

from app.services.video_assembler import VideoAssembler

logger = logging.getLogger(__name__)

assembler = VideoAssembler()


def create():
    """영상 조립 탭 패널"""

    ui.label("🎬 영상 자동 조립").classes("text-2xl font-bold mb-2")
    ui.label("이미지 + TTS 오디오 → MP4 영상 자동 생성").classes("text-sm text-gray-400 mb-4")

    # ── 소스 파일 확인 ─────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("📁 소스 파일 현황").classes("text-lg font-semibold")
        file_status = ui.column().classes("w-full gap-1 mt-2")

        def refresh_files():
            file_status.clear()
            with file_status:
                # 이미지 파일
                images = assembler.get_image_count()
                if images:
                    ui.label(f"🖼️ 이미지: {len(images)}장").classes("text-green-400")
                    for img in images:
                        size_kb = Path(img).stat().st_size / 1024
                        ui.label(f"  · {Path(img).name} ({size_kb:.0f}KB)").classes("text-xs text-gray-500 ml-4")
                else:
                    ui.label("🖼️ 이미지: 없음 (먼저 이미지 탭에서 생성하세요)").classes("text-yellow-400")

                # 오디오 파일
                audio_dir = Path("output/audio")
                audio_files = sorted(audio_dir.glob("*.mp3")) if audio_dir.exists() else []
                if audio_files:
                    ui.label(f"🔊 오디오: {len(audio_files)}개").classes("text-green-400 mt-2")
                    for af in audio_files:
                        size_kb = af.stat().st_size / 1024
                        dur = assembler.get_audio_duration(str(af))
                        ui.label(f"  · {af.name} ({size_kb:.0f}KB, {dur:.1f}초)").classes("text-xs text-gray-500 ml-4")
                else:
                    ui.label("🔊 오디오: 없음 (먼저 TTS 탭에서 생성하세요)").classes("text-yellow-400 mt-2")

                # 기존 영상 파일
                video_dir = Path("output/video")
                video_files = sorted(video_dir.glob("*.mp4")) if video_dir.exists() else []
                if video_files:
                    ui.label(f"🎬 영상: {len(video_files)}개").classes("text-blue-400 mt-2")
                    for vf in video_files:
                        size_mb = vf.stat().st_size / 1024 / 1024
                        ui.label(f"  · {vf.name} ({size_mb:.1f}MB)").classes("text-xs text-gray-500 ml-4")

        refresh_files()
        ui.button("🔄 새로고침", on_click=refresh_files).props("outline size=sm").classes("mt-2")

    # ── 오디오 선택 ──────────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("⚙️ 조립 설정").classes("text-lg font-semibold")

        audio_dir = Path("output/audio")
        audio_options = {}
        if audio_dir.exists():
            for af in sorted(audio_dir.glob("*.mp3")):
                size_kb = af.stat().st_size / 1024
                audio_options[str(af)] = f"{af.name} ({size_kb:.0f}KB)"

        audio_select = ui.select(
            options=audio_options,
            label="🔊 오디오 파일 선택",
        ).classes("w-full")

        with ui.row().classes("gap-4 items-end mt-2"):
            transition_select = ui.select(
                options={"fade": "페이드 전환", "none": "전환 없음 (빠름)"},
                value="fade",
                label="전환 효과",
            ).classes("w-48")

            fade_input = ui.number(
                label="페이드 시간(초)",
                value=0.5,
                min=0.1,
                max=2.0,
                step=0.1,
            ).classes("w-36")

            output_name = ui.input(
                label="출력 파일명",
                value="murim_recap.mp4",
            ).classes("w-60")

    # ── 조립 실행 ────────────────────────────────
    progress_label = ui.label("").classes("text-sm text-gray-400 mt-2")
    result_container = ui.column().classes("w-full gap-3 mt-4")

    async def do_assemble():
        if not audio_select.value:
            ui.notify("오디오 파일을 선택하세요", type="warning")
            return

        progress_label.text = "🎬 영상 조립 중... (1~2분 소요)"
        ui.notify("영상 조립을 시작합니다", type="info")

        result = await assembler.assemble(
            audio_path=audio_select.value,
            output_name=output_name.value or "murim_recap.mp4",
            transition=transition_select.value,
            fade_duration=fade_input.value or 0.5,
        )

        result_container.clear()
        with result_container:
            if result["success"]:
                size_mb = result["file_size"] / 1024 / 1024
                with ui.card().classes("w-full p-4 bg-gray-800"):
                    ui.label("✅ 영상 생성 완료!").classes("text-xl font-bold text-green-400")
                    ui.label(
                        f"📁 {result['path']}\n"
                        f"⏱️ {result['duration']:.1f}초 | "
                        f"📦 {size_mb:.1f}MB | "
                        f"🖼️ {result['num_images']}장 (장당 {result['duration_per_image']}초)"
                    ).classes("text-sm text-gray-300 mt-2 whitespace-pre-line")

                    ui.video(result["url"]).classes("w-full max-w-3xl mt-4")

                progress_label.text = f"🎉 완료! {result['path']}"
                ui.notify(f"영상 생성 완료: {size_mb:.1f}MB", type="positive")
            else:
                ui.label(f"❌ 실패: {result.get('error', '알 수 없는 오류')}").classes("text-red-400")
                progress_label.text = "❌ 영상 생성 실패"
                ui.notify(f"실패: {result.get('error')}", type="negative")

    ui.button(
        "🚀 영상 조립 시작",
        on_click=do_assemble,
    ).props("color=positive size=lg")

    # ── 빠른 테스트 ──────────────────────────────
    ui.separator().classes("my-6")
    ui.label("⚡ 빠른 테스트 (5초 샘플)").classes("text-lg font-semibold mb-2")

    test_result = ui.column().classes("w-full")

    async def quick_test():
        """첫 번째 이미지 + 짧은 오디오로 5초 테스트 영상 생성"""
        images = assembler.get_image_count()
        if not images:
            ui.notify("이미지가 없습니다", type="warning")
            return

        # 테스트용 짧은 TTS 생성
        from app.services.tts_service import TTSService
        progress_label.text = "⚡ 테스트 오디오 생성 중..."

        try:
            tts_result = await TTSService.generate(
                text="무협 팩토리 영상 테스트입니다. 화산귀환 리캡 영상을 시작합니다.",
                voice_id="ko-KR-HyunsuMultilingualNeural",
                output_filename="test_quick.mp3",
            )
        except Exception as e:
            ui.notify(f"TTS 오류: {e}", type="negative")
            return

        progress_label.text = "⚡ 테스트 영상 조립 중..."
        result = await assembler.assemble(
            audio_path=tts_result["path"],
            image_paths=images[:3],
            output_name="quick_test.mp4",
            transition="fade",
            fade_duration=0.3,
        )

        test_result.clear()
        with test_result:
            if result["success"]:
                ui.video(result["url"]).classes("w-full max-w-2xl")
                ui.label(f"✅ 테스트 성공 ({result['duration']:.1f}초)").classes("text-green-400")
            else:
                ui.label(f"❌ 실패: {result.get('error')}").classes("text-red-400")

        progress_label.text = ""

    ui.button("⚡ 빠른 테스트", on_click=quick_test).props("outline color=warning")
