"""이미지 생성 UI 패널 – 오버라이트/추가/개별 삭제 지원 (v1.7.2)"""

import asyncio
import logging
from pathlib import Path

from nicegui import ui

from app.services.image_generator import ImageGenerator
from app.db import get_db

logger = logging.getLogger(__name__)

generator = ImageGenerator()


def create():
    state = {"prompts": [], "results": [], "generating": False, "script_id": 0}

    ui.label("🎨 AI 이미지 생성").classes("text-2xl font-bold mb-2")
    ui.label("Pollinations.ai (FLUX 모델) – 스크립트별 이미지 관리").classes("text-sm text-gray-400 mb-4")

    # ── 스크립트 선택 ─────────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("📋 스크립트 선택").classes("text-lg font-semibold")

        script_select = ui.select(options={}, label="스크립트를 선택하세요").classes("w-full")
        script_info_label = ui.label("").classes("text-sm text-gray-400 mt-1")

        script_text_area = ui.textarea(
            label="스크립트 내용 (또는 직접 입력)",
            placeholder="[이미지 프롬프트: A lone warrior...]",
        ).classes("w-full").props("rows=8")

        # ── 기존 이미지 미리보기 + 개별 삭제 ──
        existing_container = ui.column().classes("w-full mt-2")

        def render_existing_images():
            """선택된 스크립트의 기존 이미지를 미리보기와 삭제 버튼과 함께 표시"""
            existing_container.clear()
            sid = state["script_id"]
            if not sid:
                return
            existing = generator.get_images_for_script(sid)
            if not existing:
                with existing_container:
                    ui.label("📭 기존 이미지 없음").classes("text-gray-500 italic")
                return

            with existing_container:
                ui.label(f"📁 기존 이미지 ({len(existing)}장) — 클릭하여 개별 삭제").classes(
                    "font-semibold text-yellow-300 mb-1"
                )
                with ui.row().classes("flex-wrap gap-2"):
                    for img_path in existing:
                        p = Path(img_path)
                        img_url = f"/static/images/script_{sid}/{p.name}"

                        with ui.card().classes("p-1 relative"):
                            ui.image(img_url).classes("w-32 h-20 object-cover rounded")
                            ui.label(p.name).classes("text-xs text-center")

                            async def delete_single(fname=p.name, s=sid):
                                ok = generator.delete_image(s, fname)
                                if ok:
                                    ui.notify(f"🗑️ {fname} 삭제됨", type="positive")
                                else:
                                    ui.notify(f"⚠️ {fname} 삭제 실패", type="warning")
                                render_existing_images()
                                # 스크립트 목록 새로고침 (이미지 수 반영)
                                await load_scripts()

                            ui.button("✕", on_click=delete_single).props(
                                "dense flat size=xs color=red"
                            ).classes("absolute top-0 right-0")

                # 전체 삭제 버튼
                async def delete_all():
                    sid = state["script_id"]
                    count = generator.delete_all_images(sid)
                    ui.notify(f"🗑️ script_{sid} 이미지 {count}장 전체 삭제", type="positive")
                    render_existing_images()
                    await load_scripts()

                ui.button("🗑️ 이 스크립트 이미지 전체 삭제", on_click=delete_all).props(
                    "outline color=red size=sm"
                ).classes("mt-2")

        async def load_scripts():
            db = await get_db()
            try:
                rows = await db.execute("""
                    SELECT s.id, COALESCE(p.title, '제목없음') as title,
                           s.language, substr(s.content, 1, 80) as preview,
                           COALESCE(s.format, 'long') as format,
                           COALESCE(s.genre, 'neutral') as genre
                    FROM scripts s
                    LEFT JOIN projects p ON s.project_id = p.id
                    WHERE s.content IS NOT NULL AND s.content != ''
                    ORDER BY s.id DESC LIMIT 30
                """)
                scripts = await rows.fetchall()
            finally:
                await db.close()

            options = {}
            for s in scripts:
                existing = len(generator.get_images_for_script(s[0]))
                img_badge = f" [🖼️{existing}장]" if existing > 0 else ""
                fmt_badge = "📱" if s[4] == "shorts" else "🎬"
                label = f"[ID:{s[0]}] {fmt_badge} {s[1]} ({s[2]}/{s[5]}){img_badge}"
                options[s[0]] = label
            script_select.options = options
            script_select.update()

        async def on_script_select(e):
            script_id = e.value if hasattr(e, 'value') else e
            if not script_id:
                return
            state["script_id"] = int(script_id)
            db = await get_db()
            try:
                row = await db.execute("SELECT content FROM scripts WHERE id = ?", (script_id,))
                result = await row.fetchone()
            finally:
                await db.close()

            if result and result[0]:
                script_text_area.value = result[0]
                script_text_area.update()

            existing = generator.get_images_for_script(int(script_id))
            script_info_label.text = (
                f"📁 스크립트 ID: {script_id} | 기존 이미지: {len(existing)}장"
            )
            render_existing_images()

        script_select.on_value_change(on_script_select)

        with ui.row().classes("gap-2 mt-2"):
            ui.button("📂 스크립트 목록 새로고침", on_click=load_scripts).props("outline")

    # ── 프롬프트 추출 & 편집 ───────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("🖼️ 이미지 프롬프트").classes("text-lg font-semibold")
        prompt_container = ui.column().classes("w-full gap-2")

        def render_prompts():
            prompt_container.clear()
            prompts = state["prompts"]
            if not prompts:
                with prompt_container:
                    ui.label("⚠️ [이미지 프롬프트] 태그를 찾을 수 없습니다.").classes("text-yellow-400")
                return
            with prompt_container:
                base_count = sum(1 for p in prompts if not p.get("is_variant"))
                variant_count = sum(1 for p in prompts if p.get("is_variant"))
                ui.label(
                    f"✅ {len(prompts)}개 프롬프트 (기본 {base_count}장 + 변형 {variant_count}장)"
                ).classes("text-green-400 mb-2")

                for i, p in enumerate(prompts):
                    is_v = p.get("is_variant", False)
                    bg = "bg-gray-700" if is_v else "bg-gray-800"
                    badge = "🔄 변형" if is_v else "🎬 기본"
                    with ui.card().classes(f"w-full p-3 {bg}"):
                        ui.label(f"{badge} {p['scene_id']}").classes(
                            "font-semibold text-purple-300" if is_v else "font-semibold text-blue-300"
                        )
                        inp = ui.textarea(value=p["prompt"]).classes("w-full").props("rows=2 dense")
                        idx = i

                        def update_prompt(e, _idx=idx):
                            if _idx < len(state["prompts"]):
                                state["prompts"][_idx]["prompt"] = e.value

                        inp.on("update:model-value", update_prompt)

        def extract_prompts():
            text = script_text_area.value or ""
            prompts = generator.extract_prompts(text)
            state["prompts"] = prompts
            render_prompts()

        def expand_prompts():
            if not state["prompts"]:
                ui.notify("먼저 프롬프트를 추출하세요", type="warning")
                return
            expanded = generator.expand_prompts(state["prompts"], target_count=15)
            state["prompts"] = expanded
            render_prompts()
            ui.notify(f"✅ {len(expanded)}장으로 확장됨", type="positive")

        with ui.row().classes("gap-2"):
            ui.button("🔍 프롬프트 추출", on_click=extract_prompts).props("color=primary")
            ui.button("🔄 15장으로 확장", on_click=expand_prompts).props("outline color=purple")

    # ── 생성 설정 & 실행 ──────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("⚙️ 생성 설정").classes("text-lg font-semibold")
        with ui.row().classes("gap-4 items-end"):
            model_select = ui.select(options=["flux", "turbo"], value="flux", label="모델").classes("w-40")
            seed_input = ui.number(label="시드 (빈칸=랜덤)", value=None, format="%.0f").classes("w-40")

        # ★ 생성 모드 선택 ★
        with ui.row().classes("gap-4 items-center mt-2"):
            gen_mode = ui.toggle(
                {
                    "skip": "⏩ 기존 유지 (캐시)",
                    "overwrite": "🔄 전체 덮어쓰기",
                    "add": "➕ 추가 생성 (새 시드)",
                },
                value="skip"
            ).classes("w-full")
            ui.label(
                "⏩ 기존 유지: 이미 있는 이미지는 스킵 | "
                "🔄 덮어쓰기: 기존 이미지 삭제 후 재생성 | "
                "➕ 추가: 새 시드로 추가 이미지 생성"
            ).classes("text-xs text-gray-500")

        progress_label = ui.label("").classes("text-sm text-gray-400 mt-2")
        progress_bar = ui.linear_progress(value=0, show_value=False).classes("w-full mt-1")
        progress_bar.visible = False

        result_container = ui.column().classes("w-full gap-3 mt-4")

        async def generate_all():
            if state["generating"]:
                ui.notify("이미 생성 중입니다", type="warning")
                return
            if not state["prompts"]:
                ui.notify("먼저 프롬프트를 추출하세요", type="warning")
                return
            if not state["script_id"]:
                ui.notify("스크립트를 선택하세요", type="warning")
                return

            mode = gen_mode.value or "skip"
            overwrite = (mode == "overwrite")

            # "추가" 모드: 시드를 변경하여 다른 해시 → 다른 파일명
            add_mode = (mode == "add")

            # 덮어쓰기 모드에서는 전체 이미지 먼저 삭제
            if overwrite:
                count = generator.delete_all_images(state["script_id"])
                ui.notify(f"🗑️ 기존 이미지 {count}장 삭제 후 재생성합니다", type="info")

            state["generating"] = True
            state["results"] = []
            result_container.clear()
            progress_bar.visible = True
            total = len(state["prompts"])

            try:
                for i, item in enumerate(state["prompts"]):
                    progress_bar.value = i / total
                    progress_label.text = f"🎨 생성 중... [{i + 1}/{total}] {item['scene_id']}"
                    await asyncio.sleep(0.1)

                    if add_mode:
                        # 추가 모드: 시드에 오프셋을 줘서 새 해시 생성
                        import time as _time
                        seed = int(_time.time() * 1000) % 999999 + i
                        scene_id = f"{item['scene_id']}_v{seed % 100:02d}"
                    else:
                        seed = int(seed_input.value) + i if seed_input.value is not None else None
                        scene_id = item["scene_id"]

                    result = await generator.generate(
                        item["prompt"],
                        script_id=state["script_id"],
                        scene_id=scene_id,
                        model=model_select.value,
                        seed=seed,
                        overwrite=overwrite,
                    )
                    state["results"].append(result)

                    with result_container:
                        with ui.card().classes(
                            "w-full p-3 " + ("bg-gray-800" if result["success"] else "bg-red-900")
                        ):
                            with ui.row().classes("gap-4 items-start"):
                                if result["success"]:
                                    # 캐시 방지를 위한 타임스탬프 쿼리 추가
                                    import time as _time
                                    cache_bust = f"?t={int(_time.time())}"
                                    ui.image(result["url"] + cache_bust).classes(
                                        "w-80 rounded shadow-lg"
                                    )
                                with ui.column().classes("flex-1"):
                                    status = "✅ 성공" if result["success"] else "❌ 실패"
                                    cached = " (캐시)" if result.get("cached") else ""
                                    ui.label(f"{scene_id}: {status}{cached}").classes("font-semibold")
                                    ui.label(f"⏱️ {result['elapsed']:.1f}초").classes(
                                        "text-sm text-gray-400"
                                    )
                                    ui.label(result["prompt"][:120] + "...").classes(
                                        "text-xs text-gray-500"
                                    )

                success_count = sum(1 for r in state["results"] if r["success"])
                progress_bar.value = 1.0
                progress_label.text = (
                    f"🎉 완료! {success_count}/{total}개 이미지 → "
                    f"script_{state['script_id']}/ 폴더 (모드: {mode})"
                )
                ui.notify(f"이미지 생성 완료: {success_count}/{total}", type="positive")

                # 기존 이미지 갱신
                render_existing_images()

            except Exception as e:
                logger.exception("이미지 생성 오류")
                progress_label.text = f"❌ 오류: {e}"
                ui.notify(f"생성 오류: {e}", type="negative")
            finally:
                state["generating"] = False

        with ui.row().classes("gap-2 mt-3"):
            ui.button("🚀 전체 이미지 생성", on_click=generate_all).props("color=positive size=lg")
            ui.button("🗑️ 결과 초기화", on_click=lambda: (
                result_container.clear(),
                progress_label.set_text(""),
                setattr(progress_bar, "visible", False),
            )).props("outline color=red")

    # ── 커스텀 프롬프트 ──────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("✏️ 커스텀 프롬프트 (단일 이미지)").classes("text-lg font-semibold")
        custom_prompt = ui.textarea(
            label="이미지 프롬프트를 영어로 입력하세요",
            placeholder="A powerful martial arts master...",
        ).classes("w-full").props("rows=3")
        custom_result = ui.column().classes("w-full mt-2")

        async def generate_custom():
            prompt = custom_prompt.value or ""
            if not prompt.strip():
                ui.notify("프롬프트를 입력하세요", type="warning")
                return
            seed = int(seed_input.value) if seed_input.value is not None else None
            result = await generator.generate(
                prompt.strip(), script_id=state["script_id"],
                scene_id="custom", model=model_select.value, seed=seed,
                overwrite=True,  # 커스텀은 항상 덮어쓰기
            )
            custom_result.clear()
            with custom_result:
                if result["success"]:
                    import time as _time
                    ui.image(result["url"] + f"?t={int(_time.time())}").classes(
                        "w-full max-w-xl rounded shadow-lg"
                    )
                    ui.label(f"✅ 생성 완료 ({result['elapsed']:.1f}초)").classes("text-green-400")
                else:
                    ui.label("❌ 이미지 생성 실패").classes("text-red-400")

        ui.button("🎨 이미지 생성", on_click=generate_custom).props("color=primary")

    asyncio.ensure_future(load_scripts())
