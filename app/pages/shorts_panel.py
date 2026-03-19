"""숏츠 제작 UI 패널 (v1.7.1 — 클라이언트 안전 처리 + 씬 기반 파이프라인)"""

import os
import re
import sqlite3
import logging
from pathlib import Path
from nicegui import ui, context
from app.services.shorts_maker import ShortsMaker, ShortsScene, SHORTS_DIR, MAX_DURATION
from app.services.image_generator import ImageGenerator
from app.services.tts_service import TTSService

logger = logging.getLogger(__name__)
DB_PATH = "app.db"


def _normalize_images(raw_imgs, script_id):
    """get_images_for_script 반환값을 딕셔너리 리스트로 통일"""
    result = []
    for item in raw_imgs:
        if isinstance(item, str):
            p = Path(item)
            result.append({
                "path": str(p),
                "name": p.name,
                "url": f"/static/images/script_{script_id}/{p.name}"
            })
        elif isinstance(item, dict):
            result.append(item)
    return result


def _safe_ui(fn, *args, **kwargs):
    """NiceGUI UI 호출 시 클라이언트 삭제 여부를 체크하여 안전하게 실행"""
    try:
        return fn(*args, **kwargs)
    except RuntimeError as e:
        if 'deleted' in str(e):
            logger.warning(f"[UI] 클라이언트 이탈 — UI 업데이트 스킵: {fn.__name__}")
            return None
        raise


def create():
    ui.label("🎬 YouTube Shorts 제작기").classes("text-2xl font-bold")
    ui.label("15~59초 세로영상 | Ken Burns 효과 | 자막 자동 생성").classes("text-gray-400 mb-4")

    with ui.expansion("💡 2026 숏츠 알고리즘 핵심 팁", icon="tips_and_updates").classes("w-full mb-4"):
        ui.markdown("""
**첫 1.5초가 전부입니다** — "Stayed to watch" 비율이 노출량을 결정  
**15~30초가 최적** — 리텐션 80%+ 달성 구간  
**자막 필수** — 무음 시청자 70% 이상  
**결과부터 보여주기** — 질문/충격/결과 먼저 → 설명은 뒤에  
**루프 구조** — 끝→시작이 자연스러우면 재시청 유도  
        """)

    state = {"script_id": None, "images": [], "narration": "", "script_content": ""}

    # === 1. 스크립트 선택 ===
    ui.label("① 스크립트 선택").classes("text-lg font-bold mt-4")

    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT s.id, COALESCE(p.title, '제목없음') as title, s.language,
                   LENGTH(s.content), COALESCE(s.format, 'long') as format,
                   COALESCE(s.genre, 'neutral') as genre
            FROM scripts s LEFT JOIN projects p ON s.project_id = p.id
            WHERE s.content IS NOT NULL AND LENGTH(s.content) > 0
            ORDER BY s.id DESC
        """).fetchall()
        conn.close()
    except Exception:
        rows = []

    generator = ImageGenerator()
    script_options = {}
    for row in rows:
        sid, title, lang, clen, fmt, genre = row
        imgs = generator.get_images_for_script(sid)
        img_badge = f"🖼️{len(imgs)}" if imgs else "🖼️0"
        fmt_badge = "📱" if fmt == "shorts" else "🎬"
        label = f"[ID:{sid}] {fmt_badge} {title} ({lang}/{genre}) {img_badge}"
        script_options[label] = sid

    script_select = ui.select(
        options=list(script_options.keys()),
        label="스크립트 선택",
        with_input=True
    ).classes("w-full")

    # === 2. 숏츠 설정 ===
    ui.label("② 숏츠 설정").classes("text-lg font-bold mt-4")

    with ui.row().classes("gap-4 items-end"):
        hook_input = ui.input(
            "훅 텍스트 (첫 1.5초 화면 문구)",
            placeholder="숨겨진 고수의 운명은?",
            value=""
        ).classes("w-96")
        max_chars = ui.number("나레이션 최대 글자수", value=200, min=50, max=500, step=50).classes("w-40")

    with ui.row().classes("gap-4 items-end"):
        voice_select = ui.select(
            options={v["id"]: f'{v["name"]} ({v["lang"]})' for v in TTSService.list_voices("ko")},
            value="ko-KR-HyunsuMultilingualNeural",
            label="음성 모델"
        ).classes("w-64")
        rate_select = ui.select(
            options=["-10%", "+0%", "+10%", "+15%", "+20%", "+25%"],
            value="+10%",
            label="속도 (숏츠는 빠르게)"
        ).classes("w-32")

    # === 3. 나레이션 편집 ===
    ui.label("③ 나레이션 편집").classes("text-lg font-bold mt-4")
    narration_area = ui.textarea(
        label="숏츠용 나레이션 (자동 추출 후 편집 가능)",
        value=""
    ).classes("w-full").props("rows=6")
    subtitle_preview = ui.label("").classes("text-sm text-gray-400")

    # === 3-1. 씬 정보 미리보기 ===
    scene_info_label = ui.label("").classes("text-sm text-blue-300 mt-1")

    # === 4. 이미지 선택 ===
    ui.label("④ 이미지 선택").classes("text-lg font-bold mt-4")
    image_container = ui.row().classes("flex-wrap gap-2")
    image_info = ui.label("스크립트를 선택하면 이미지가 표시됩니다").classes("text-gray-400")

    # === 5. Ken Burns 효과 ===
    ui.label("⑤ Ken Burns 효과").classes("text-lg font-bold mt-4")
    effect_info = ui.label("이미지 선택 후 효과를 지정하세요").classes("text-gray-400")
    effect_container = ui.column().classes("w-full gap-1")
    effect_selectors = []

    # === 스크립트 선택 이벤트 ===
    async def on_script_select(e):
        if isinstance(e.args, dict):
            val = e.args.get("label", "")
        elif isinstance(e.args, str):
            val = e.args
        else:
            val = str(e.args)

        if not val or val not in script_options:
            return

        sid = script_options[val]
        state["script_id"] = sid

        raw = generator.get_images_for_script(sid)
        imgs = _normalize_images(raw, sid)
        state["images"] = [img["path"] for img in imgs]

        image_container.clear()
        effect_container.clear()
        effect_selectors.clear()

        if imgs:
            image_info.set_text(f"🖼️ {len(imgs)}장 사용 가능")
            with image_container:
                for img in imgs:
                    with ui.card().classes("p-1"):
                        ui.image(img["url"]).classes("w-24 h-32 object-cover rounded")
                        ui.label(img["name"]).classes("text-xs text-center")

            effects_list = ["zoom_center", "zoom_top", "pan_left", "zoom_out", "pan_right"]
            with effect_container:
                for i, img in enumerate(imgs):
                    auto_eff = effects_list[i % len(effects_list)]
                    sel = ui.select(
                        options={k: v["desc"] for k, v in ShortsMaker.EFFECTS.items()},
                        value=auto_eff,
                        label=f"씬 {i + 1}: {img['name']}"
                    ).classes("w-64")
                    effect_selectors.append(sel)
            effect_info.set_text(f"각 이미지별 카메라 효과 ({len(imgs)}장)")
        else:
            image_info.set_text("⚠️ 이미지가 없습니다. 이미지 탭에서 먼저 생성하세요.")

        try:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute("SELECT content FROM scripts WHERE id=?", (sid,)).fetchone()
            conn.close()
            if row:
                content = row[0]
                state["script_content"] = content

                # 나레이션 추출 (제어문 완전 제거)
                narration = TTSService._extract_narration(content)
                limit = int(max_chars.value)
                if len(narration) > limit:
                    sentences = re.split(r'(?<=[.!?。])\s*', narration)
                    trimmed = ""
                    for s in sentences:
                        if len(trimmed) + len(s) > limit:
                            break
                        trimmed += s + " "
                    narration = trimmed.strip()

                narration_area.value = narration
                state["narration"] = narration

                lines = ShortsMaker.split_narration_to_subtitle(narration)
                est_duration = sum(max(len(l) * 0.12, 1.5) for l in lines)
                subtitle_preview.set_text(
                    f"📝 {len(narration)}자 | 자막 {len(lines)}줄 | 예상 {est_duration:.0f}초"
                )

                # 씬 분석 정보 표시
                scenes = TTSService.extract_scenes(content)
                if scenes:
                    scene_parts = []
                    for sc in scenes:
                        parts = [sc["section"]]
                        if sc["image_prompt"]:
                            parts.append("🖼️")
                        if sc["bgm"]:
                            parts.append("🎵")
                        if sc["sfx"]:
                            parts.append("🔊")
                        scene_parts.append("".join(parts))
                    scene_info_label.set_text(
                        f"🎬 씬 구조: {' → '.join(scene_parts)} ({len(scenes)}씬)"
                    )
                else:
                    scene_info_label.set_text("")

        except Exception as ex:
            logger.error(f"나레이션 추출 실패: {ex}")

    script_select.on("update:model-value", on_script_select)

    # === 6. 제작 버튼 ===
    ui.label("⑥ 숏츠 제작").classes("text-lg font-bold mt-4")

    progress = ui.linear_progress(value=0, show_value=False).classes("w-full")
    progress.visible = False
    status_label = ui.label("").classes("text-sm")
    result_container = ui.column().classes("w-full")

    async def generate_shorts():
        """숏츠 생성 — 클라이언트 삭제 시에도 백그라운드 작업은 계속 진행"""
        if not state["images"]:
            _safe_ui(ui.notify, "이미지가 없습니다!", type="warning")
            return

        narration = narration_area.value.strip()
        if not narration or len(narration) < 10:
            _safe_ui(ui.notify, "나레이션을 입력하세요!", type="warning")
            return

        # 제작에 필요한 값을 미리 로컬 변수로 저장 (UI 접근 최소화)
        script_id = state["script_id"]
        images = list(state["images"])
        voice_id = voice_select.value
        rate = rate_select.value
        effects = [sel.value for sel in effect_selectors] if effect_selectors else None

        _safe_ui(setattr, progress, 'visible', True)
        _safe_ui(setattr, progress, 'value', 0.1)
        _safe_ui(status_label.set_text, "🔊 TTS 생성 중...")

        try:
            # ── 1. TTS 생성 ──
            tts_filename = f"shorts_script_{script_id}.mp3"
            tts_result = await TTSService.generate(
                text=narration,
                voice_id=voice_id,
                rate=rate,
                pitch="+0Hz",
                output_filename=tts_filename
            )
            audio_path = tts_result["path"]
            audio_duration = await ShortsMaker.get_audio_duration(audio_path)
            if audio_duration <= 0:
                audio_duration = tts_result.get("duration_sec", 30)

            _safe_ui(setattr, progress, 'value', 0.3)
            _safe_ui(status_label.set_text, f"🎬 Ken Burns 클립 생성 중... ({audio_duration:.1f}초)")

            # ── 2. 씬별 클립 생성 ──
            per_image = audio_duration / len(images)
            clip_paths = []
            for i, img_path in enumerate(images):
                eff = effects[i] if effects and i < len(effects) else "zoom_center"
                clip_path = str(SHORTS_DIR / f"clip_{i:02d}.mp4")
                success = await ShortsMaker.create_scene_clip(
                    image_path=img_path,
                    duration=per_image,
                    effect=eff,
                    output_path=clip_path
                )
                if success:
                    clip_paths.append(clip_path)

                pct = 0.3 + (0.4 * (i + 1) / len(images))
                _safe_ui(setattr, progress, 'value', pct)
                _safe_ui(status_label.set_text, f"🎬 씬 {i + 1}/{len(images)} 완료")

            if not clip_paths:
                _safe_ui(ui.notify, "클립 생성 실패!", type="negative")
                _safe_ui(setattr, progress, 'visible', False)
                return

            # ── 3. 자막 생성 ──
            _safe_ui(setattr, progress, 'value', 0.7)
            _safe_ui(status_label.set_text, "📝 자막 생성 중...")

            subtitle_lines = ShortsMaker.split_narration_to_subtitle(narration)
            lines_per_scene = max(1, len(subtitle_lines) // len(images))

            scene_objs = []
            for i, img in enumerate(images):
                start_l = i * lines_per_scene
                end_l = start_l + lines_per_scene if i < len(images) - 1 else len(subtitle_lines)
                scene_objs.append(ShortsScene(
                    image_path=img,
                    narration="",
                    duration=per_image,
                    subtitle_lines=subtitle_lines[start_l:end_l],
                    effect=effects[i] if effects and i < len(effects) else "zoom_center"
                ))

            ass_path = str(SHORTS_DIR / f"shorts_script_{script_id}.ass")
            ShortsMaker.generate_ass_subtitle(scene_objs, ass_path)

            # ── 4. 최종 조립 ──
            _safe_ui(setattr, progress, 'value', 0.8)
            _safe_ui(status_label.set_text, "🔗 최종 조립 중...")

            output_name = f"shorts_script_{script_id}.mp4"
            output_path = str(SHORTS_DIR / output_name)
            result = await ShortsMaker.assemble_shorts(
                scene_clips=clip_paths,
                audio_path=audio_path,
                subtitle_path=ass_path,
                output_path=output_path,
            )

            # ── 5. 임시 파일 정리 ──
            for clip in clip_paths:
                try:
                    os.remove(clip)
                except Exception:
                    pass

            _safe_ui(setattr, progress, 'value', 1.0)

            # ── 6. 결과 표시 ──
            if result["success"]:
                logger.info(
                    f"[숏츠 완성] script={script_id}, "
                    f"{result['duration']:.1f}s, {result['file_size']/1024/1024:.1f}MB"
                )
                _safe_ui(
                    status_label.set_text,
                    f"✅ 완성! {result['duration']:.1f}초 | "
                    f"{result['file_size'] / 1024 / 1024:.1f}MB"
                )
                _safe_ui(ui.notify, "숏츠 제작 완료!", type="positive")

                try:
                    result_container.clear()
                    with result_container:
                        with ui.card().classes("w-full p-4"):
                            ui.label("🎬 완성된 숏츠").classes("text-lg font-bold")
                            ui.video(result["url"]).classes("w-80")
                            with ui.row().classes("gap-4 mt-2"):
                                ui.label(f"⏱️ {result['duration']:.1f}초")
                                ui.label(f"📦 {result['file_size'] / 1024 / 1024:.1f}MB")
                                ui.label(f"🖼️ {result['scenes']}장면")
                            ui.label(f"📂 {result['path']}").classes("text-xs text-gray-400")
                except RuntimeError:
                    pass  # 클라이언트 이탈
            else:
                err_msg = result.get('error', '알 수 없는 오류')
                logger.error(f"[숏츠 실패] {err_msg}")
                _safe_ui(status_label.set_text, f"❌ 실패: {err_msg}")
                _safe_ui(ui.notify, "숏츠 제작 실패", type="negative")

        except Exception as e:
            logger.error(f"숏츠 제작 에러: {e}", exc_info=True)
            _safe_ui(status_label.set_text, f"❌ 에러: {e}")
            try:
                ui.notify(str(e), type="negative")
            except RuntimeError:
                pass
        finally:
            _safe_ui(setattr, progress, 'visible', False)

    ui.button(
        "🎬 숏츠 제작 시작",
        on_click=generate_shorts,
        color="red"
    ).classes("mt-2").props("size=lg")

    # === 기존 숏츠 목록 ===
    ui.label("📁 제작된 숏츠").classes("text-lg font-bold mt-6")
    existing = ui.column().classes("w-full")

    shorts_files = sorted(SHORTS_DIR.glob("shorts_*.mp4"))
    if shorts_files:
        with existing:
            for f in shorts_files:
                with ui.card().classes("p-2 w-full"):
                    with ui.row().classes("items-center gap-4"):
                        ui.video(f"/output/shorts/{f.name}").classes("w-48")
                        ui.label(f"{f.name} | {f.stat().st_size / 1024 / 1024:.1f}MB").classes("text-sm")
    else:
        with existing:
            ui.label("아직 제작된 숏츠가 없습니다").classes("text-gray-400 italic")
