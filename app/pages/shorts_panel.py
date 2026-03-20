"""숏츠 제작 UI 패널 (v1.8.0 — AI 비디오 클립 + Ken Burns 10종 + 효과 확장)"""

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
    ui.label("15~59초 세로영상 | AI 비디오 클립 + Ken Burns | 자막 자동 생성").classes("text-gray-400 mb-4")

    with ui.expansion("💡 2026 숏츠 알고리즘 핵심 팁", icon="tips_and_updates").classes("w-full mb-4"):
        ui.markdown("""
**첫 1.5초가 전부입니다** — "Stayed to watch" 비율이 노출량을 결정  
**15~30초가 최적** — 리텐션 80%+ 달성 구간  
**자막 필수** — 무음 시청자 70% 이상  
**결과부터 보여주기** — 질문/충격/결과 먼저 → 설명은 뒤에  
**루프 구조** — 끝→시작이 자연스러우면 재시청 유도  
**AI 클립 사용 시** — 정적 슬라이드쇼를 벗어나 YouTube AI slop 판정 탈출!
        """)

    state = {
        "script_id": None,
        "images": [],
        "narration": "",
        "script_content": "",
        "genre": "neutral",
        "image_prompts": [],
    }

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
    script_genres = {}
    for row in rows:
        sid, title, lang, clen, fmt, genre = row
        imgs = generator.get_images_for_script(sid)
        img_badge = f"🖼️{len(imgs)}" if imgs else "🖼️0"
        fmt_badge = "📱" if fmt == "shorts" else "🎬"
        label = f"[ID:{sid}] {fmt_badge} {title} ({lang}/{genre}) {img_badge}"
        script_options[label] = sid
        script_genres[sid] = genre or "neutral"

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

    # === 2-1. AI 비디오 클립 설정 ===
    ui.separator().classes("my-2")
    with ui.row().classes("gap-4 items-center"):
        ai_clip_toggle = ui.switch("🎬 AI 비디오 클립 사용", value=False).classes("text-lg")
        ui.label("정적 이미지→움직이는 영상 변환 (AI slop 탈출)").classes("text-gray-400 text-sm")

    with ui.row().classes("gap-4 items-end").bind_visibility_from(ai_clip_toggle, "value"):
        from app.services.video_clip_service import VideoClipService
        model_options = {m["key"]: f'{m["name"]} (${m["cost"]}/s)' for m in VideoClipService.get_model_list()}
        ai_model_select = ui.select(
            options=model_options,
            value="grok-imagine",
            label="AI 비디오 모델"
        ).classes("w-64")
        ai_duration_select = ui.select(
            options={"3": "3초 (빠름)", "4": "4초 (권장)", "5": "5초 (고품질)"},
            value="4",
            label="클립 길이"
        ).classes("w-40")
        cost_label = ui.label("💰 현재 비용: $0.000").classes("text-yellow-300 text-sm")
    with ui.row().classes("gap-2").bind_visibility_from(ai_clip_toggle, "value"):
        ui.label("📌 Grok Imagine: $0.05/초 (월 $25 무료 크레딧) | 실패 시 자동 Ken Burns 폴백").classes("text-orange-300 text-xs")

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
    effect_info = ui.label("이미지 선택 후 효과를 지정하세요 (AI 클립 모드에서는 폴백용)").classes("text-gray-400")
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
        state["genre"] = script_genres.get(sid, "neutral")

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

            with effect_container:
                for i, img in enumerate(imgs):
                    auto_eff = ShortsMaker.AUTO_EFFECTS[i % len(ShortsMaker.AUTO_EFFECTS)]
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

                # 이미지 프롬프트 추출 (AI 클립용)
                prompts = generator.extract_prompts(content)
                state["image_prompts"] = [p["prompt"] for p in prompts]

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
    cost_label = ui.label("").classes("text-sm text-orange-300")
    result_container = ui.column().classes("w-full")

    async def generate_shorts():
        """숏츠 생성 — AI 클립 또는 Ken Burns"""
        if not state["images"]:
            _safe_ui(ui.notify, "이미지가 없습니다!", type="warning")
            return

        narration = narration_area.value.strip()
        if not narration or len(narration) < 10:
            _safe_ui(ui.notify, "나레이션을 입력하세요!", type="warning")
            return

        script_id = state["script_id"]
        images = list(state["images"])
        voice_id = voice_select.value
        rate = rate_select.value
        effects = [sel.value for sel in effect_selectors] if effect_selectors else None
        use_ai = ai_clip_toggle.value
        genre = state.get("genre", "neutral")
        img_prompts = state.get("image_prompts", [])

        mode_text = "AI 비디오 클립" if use_ai else "Ken Burns"
        _safe_ui(setattr, progress, 'visible', True)
        _safe_ui(setattr, progress, 'value', 0.1)
        _safe_ui(status_label.set_text, f"🔊 TTS 생성 중... (모드: {mode_text})")
        _safe_ui(cost_label.set_text, "")

        total_cost = 0.0

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

            # ── 2. 씬별 클립 생성 ──
            per_image = audio_duration / max(len(images), 1)
            clip_paths = []
            total_cost = 0.0

            if use_ai:
                # ── AI 비디오 클립 모드 ──
                selected_model = ai_model_select.value if ai_model_select else "wan"
                clip_dur = int(ai_duration_select.value) if ai_duration_select else 4
                _safe_ui(status_label.set_text, f"🎬 AI 비디오 클립 생성 중... ({selected_model})")

                from app.services.video_clip_service import VideoClipService
                clip_service = VideoClipService()

                try:
                    for i, img_path in enumerate(images):
                        # 프롬프트 생성 (안전 처리)
                        raw_prompt = ""
                        if img_prompts and i < len(img_prompts) and img_prompts[i]:
                            raw_prompt = str(img_prompts[i])
                        if not raw_prompt.strip():
                            raw_prompt = "cinematic scene"

                        prompt = VideoClipService.build_motion_prompt(
                            raw_prompt, genre or "default", i
                        )

                        try:
                            result = await clip_service.generate_clip(
                                image_path=img_path,
                                prompt=prompt,
                                script_id=str(script_id),
                                scene_id=f"scene_{i:02d}",
                                genre=genre or "default",
                                fmt="shorts",
                                duration=clip_dur,
                                model=selected_model,
                            )
                        except Exception as clip_err:
                            logger.error(f"❌ AI 클립 생성 예외 scene_{i}: {clip_err}")
                            result = {"success": False}

                        if result.get("success"):
                            clip_paths.append(result["path"])
                            total_cost += result.get("cost", 0.0)
                            model_used = result.get("model", "ken-burns")
                            _safe_ui(
                                status_label.set_text,
                                f"🎬 AI 클립 {i+1}/{len(images)} 완료 ({model_used})"
                            )
                        else:
                            # ── AI 전부 실패 → Ken Burns 폴백 ──
                            logger.warning(f"⚠️ AI 실패 scene_{i} → Ken Burns 폴백")
                            _safe_ui(
                                status_label.set_text,
                                f"⚠️ AI 실패 → Ken Burns 폴백 {i+1}/{len(images)}"
                            )
                            eff = "zoom_center"
                            if effects and i < len(effects):
                                eff = effects[i]

                            kb_path = str(SHORTS_DIR / f"clip_{i:02d}.mp4")
                            try:
                                kb_ok = await ShortsMaker.create_scene_clip(
                                    image_path=img_path,
                                    duration=per_image,
                                    effect=eff,
                                    output_path=kb_path,
                                )
                                if kb_ok:
                                    clip_paths.append(kb_path)
                                    logger.info(f"✅ Ken Burns 폴백 성공: scene_{i}")
                                else:
                                    logger.error(f"❌ Ken Burns도 실패: scene_{i}")
                            except Exception as kb_err:
                                logger.error(f"❌ Ken Burns 폴백 예외 scene_{i}: {kb_err}")

                        pct = 0.3 + (0.4 * (i + 1) / len(images))
                        _safe_ui(setattr, progress, 'value', pct)
                        if hasattr(cost_label, 'set_text'):
                            _safe_ui(
                                cost_label.set_text,
                                f"💰 현재 비용: ${total_cost:.3f}"
                            )

                except Exception as batch_err:
                    logger.error(f"❌ AI 클립 배치 에러: {batch_err}")
                    _safe_ui(status_label.set_text, f"⚠️ AI 클립 에러 → Ken Burns로 전환")

                    # 배치 레벨 에러 시 아직 안 만든 클립을 Ken Burns로 생성
                    for i, img_path in enumerate(images):
                        already = any(f"clip_{i:02d}" in str(p) for p in clip_paths)
                        if already:
                            continue
                        eff = effects[i] if effects and i < len(effects) else "zoom_center"
                        kb_path = str(SHORTS_DIR / f"clip_{i:02d}.mp4")
                        try:
                            kb_ok = await ShortsMaker.create_scene_clip(
                                image_path=img_path,
                                duration=per_image,
                                effect=eff,
                                output_path=kb_path,
                            )
                            if kb_ok:
                                clip_paths.append(kb_path)
                        except Exception:
                            pass

                finally:
                    try:
                        await clip_service.close()
                    except Exception:
                        pass

            else:
                # ── Ken Burns 모드 (기존) ──
                _safe_ui(status_label.set_text, "🎬 Ken Burns 클립 생성 중...")
                for i, img_path in enumerate(images):
                    eff = "zoom_center"
                    if effects and i < len(effects):
                        eff = effects[i]

                    clip_path = str(SHORTS_DIR / f"clip_{i:02d}.mp4")
                    try:
                        success = await ShortsMaker.create_scene_clip(
                            image_path=img_path,
                            duration=per_image,
                            effect=eff,
                            output_path=clip_path,
                        )
                        if success:
                            clip_paths.append(clip_path)
                    except Exception as e:
                        logger.error(f"❌ Ken Burns 클립 에러 scene_{i}: {e}")

                    pct = 0.3 + (0.4 * (i + 1) / len(images))
                    _safe_ui(setattr, progress, 'value', pct)
                    _safe_ui(status_label.set_text, f"🎬 씬 {i+1}/{len(images)} 완료")

            if not clip_paths:
                _safe_ui(ui.notify, "❌ 클립 생성 실패! 이미지를 확인하세요.", type="negative")
                _safe_ui(setattr, progress, 'visible', False)
                _safe_ui(status_label.set_text, "클립 생성 실패")
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

            # ── 5. 임시 클립 정리 (Ken Burns만, AI 클립은 캐시) ──
            if not use_ai:
                for clip in clip_paths:
                    try:
                        os.remove(clip)
                    except Exception:
                        pass

            _safe_ui(setattr, progress, 'value', 1.0)

            # ── 6. 결과 표시 ──
            if result["success"]:
                cost_text = f" | 💰 ${total_cost:.3f}" if total_cost > 0 else ""
                logger.info(
                    f"[숏츠 완성] script={script_id}, mode={mode_text}, "
                    f"{result['duration']:.1f}s, {result['file_size']/1024/1024:.1f}MB{cost_text}"
                )
                _safe_ui(
                    status_label.set_text,
                    f"✅ 완성! {result['duration']:.1f}초 | "
                    f"{result['file_size'] / 1024 / 1024:.1f}MB | "
                    f"모드: {mode_text}{cost_text}"
                )
                _safe_ui(ui.notify, f"숏츠 제작 완료! ({mode_text})", type="positive")

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
                                ui.label(f"🎬 {mode_text}")
                                if total_cost > 0:
                                    ui.label(f"💰 ${total_cost:.3f}").classes("text-orange-300")
                            ui.label(f"📂 {result['path']}").classes("text-xs text-gray-400")
                except RuntimeError:
                    pass
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

    with ui.row().classes("gap-4 items-center mt-2"):
        ui.button(
            "🎬 숏츠 제작 시작",
            on_click=generate_shorts,
            color="red"
        ).props("size=lg")
        ui.label("AI 클립 ON: Pollinations API 호출 | OFF: 기존 Ken Burns").classes("text-xs text-gray-400")

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
