"""
이미지 생성 UI 패널 – NiceGUI
- 스크립트에서 자동 프롬프트 추출
- 개별/일괄 이미지 생성
- 실시간 진행 상황 표시
- 생성된 이미지 미리보기
"""

import asyncio
import logging

from nicegui import ui

from app.services.image_generator import ImageGenerator
from app.services.db import get_db

logger = logging.getLogger(__name__)

generator = ImageGenerator()


def create():
    """이미지 생성 탭 패널"""

    # ── 상태 변수 ───────────────────────────────
    state = {"prompts": [], "results": [], "generating": False}

    # ── 헤더 ────────────────────────────────────
    ui.label("🎨 AI 이미지 생성").classes("text-2xl font-bold mb-2")
    ui.label(
        "Pollinations.ai (FLUX 모델) – 무료, API 키 불필요"
    ).classes("text-sm text-gray-400 mb-4")

    # ── 스크립트 선택 ─────────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("📋 스크립트 선택").classes("text-lg font-semibold")

        script_select = ui.select(
            options={},
            label="스크립트를 선택하세요",
        ).classes("w-full")

        script_text_area = ui.textarea(
            label="스크립트 내용 (또는 직접 입력)",
            placeholder="[이미지 프롬프트] A lone warrior...",
        ).classes("w-full").props("rows=8")

        async def load_scripts():
            """DB에서 스크립트 목록 로드"""
            db = await get_db()
            rows = await db.execute(
                "SELECT id, title, lang, substr(content, 1, 80) as preview "
                "FROM scripts ORDER BY id DESC LIMIT 20"
            )
            scripts = await rows.fetchall()
            options = {}
            for s in scripts:
                label = f"[ID:{s[0]}] {s[1] or '제목없음'} ({s[2]}) – {s[3]}..."
                options[s[0]] = label
            script_select.options = options
            script_select.update()

        async def on_script_select(e):
            """선택한 스크립트 내용 로드"""
            if not e.value:
                return
            db = await get_db()
            row = await db.execute(
                "SELECT content FROM scripts WHERE id = ?", (e.value,)
            )
            result = await row.fetchone()
            if result:
                script_text_area.value = result[0]

        script_select.on("update:model-value", on_script_select)

        with ui.row().classes("gap-2 mt-2"):
            ui.button("📂 스크립트 목록 새로고침", on_click=load_scripts).props(
                "outline"
            )

    # ── 프롬프트 추출 & 편집 ───────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("🖼️ 이미지 프롬프트").classes("text-lg font-semibold")

        prompt_container = ui.column().classes("w-full gap-2")

        def extract_prompts():
            text = script_text_area.value or ""
            prompts = generator.extract_prompts(text)
            state["prompts"] = prompts
            prompt_container.clear()

            if not prompts:
                with prompt_container:
                    ui.label("⚠️ [이미지 프롬프트] 태그를 찾을 수 없습니다").classes(
                        "text-yellow-400"
                    )
                return

            with prompt_container:
                for i, p in enumerate(prompts):
                    with ui.card().classes("w-full p-3 bg-gray-800"):
                        ui.label(f"🎬 {p['scene_id']}").classes(
                            "font-semibold text-blue-300"
                        )
                        # 편집 가능한 텍스트 입력
                        inp = ui.textarea(value=p["prompt"]).classes("w-full").props(
                            "rows=3 dense"
                        )
                        # 클로저에서 인덱스 캡처
                        idx = i

                        def update_prompt(e, _idx=idx):
                            if _idx < len(state["prompts"]):
                                state["prompts"][_idx]["prompt"] = e.value

                        inp.on("update:model-value", update_prompt)

                ui.label(f"✅ {len(prompts)}개 프롬프트 추출됨").classes(
                    "text-green-400 mt-2"
                )

        ui.button("🔍 프롬프트 추출", on_click=extract_prompts).props("color=primary")

    # ── 생성 설정 & 실행 ──────────────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("⚙️ 생성 설정").classes("text-lg font-semibold")

        with ui.row().classes("gap-4 items-end"):
            model_select = ui.select(
                options=["flux", "turbo"],
                value="flux",
                label="모델",
            ).classes("w-40")

            seed_input = ui.number(
                label="시드 (빈칸=랜덤)",
                value=None,
                format="%.0f",
            ).classes("w-40")

        progress_label = ui.label("").classes("text-sm text-gray-400 mt-2")
        progress_bar = ui.linear_progress(value=0, show_value=False).classes(
            "w-full mt-1"
        )
        progress_bar.visible = False

        # ── 결과 표시 영역 ─────────────────────────
        result_container = ui.column().classes("w-full gap-3 mt-4")

        async def generate_all():
            """전체 이미지 일괄 생성"""
            if state["generating"]:
                ui.notify("이미 생성 중입니다", type="warning")
                return
            if not state["prompts"]:
                ui.notify("먼저 프롬프트를 추출하세요", type="warning")
                return

            state["generating"] = True
            state["results"] = []
            result_container.clear()
            progress_bar.visible = True
            total = len(state["prompts"])

            try:
                for i, item in enumerate(state["prompts"]):
                    progress_bar.value = i / total
                    progress_label.text = (
                        f"🎨 생성 중... [{i+1}/{total}] {item['scene_id']}"
                    )
                    await asyncio.sleep(0.1)  # UI 업데이트 허용

                    seed = (
                        int(seed_input.value) + i
                        if seed_input.value is not None
                        else None
                    )

                    result = await generator.generate(
                        item["prompt"],
                        scene_id=item["scene_id"],
                        model=model_select.value,
                        seed=seed,
                    )
                    state["results"].append(result)

                    # 결과를 즉시 표시
                    with result_container:
                        with ui.card().classes(
                            "w-full p-3 "
                            + ("bg-gray-800" if result["success"] else "bg-red-900")
                        ):
                            with ui.row().classes("gap-4 items-start"):
                                if result["success"]:
                                    ui.image(result["url"]).classes(
                                        "w-80 rounded shadow-lg"
                                    )
                                with ui.column().classes("flex-1"):
                                    status = (
                                        "✅ 성공" if result["success"] else "❌ 실패"
                                    )
                                    cached = (
                                        " (캐시)" if result.get("cached") else ""
                                    )
                                    ui.label(
                                        f"{item['scene_id']}: {status}{cached}"
                                    ).classes("font-semibold")
                                    ui.label(
                                        f"⏱️ {result['elapsed']:.1f}초"
                                    ).classes("text-sm text-gray-400")
                                    ui.label(result["prompt"][:120] + "...").classes(
                                        "text-xs text-gray-500"
                                    )

                # 완료
                success_count = sum(1 for r in state["results"] if r["success"])
                progress_bar.value = 1.0
                progress_label.text = (
                    f"🎉 완료! {success_count}/{total}개 이미지 생성 성공"
                )
                ui.notify(
                    f"이미지 생성 완료: {success_count}/{total}",
                    type="positive" if success_count == total else "warning",
                )

            except Exception as e:
                logger.exception("이미지 생성 오류")
                progress_label.text = f"❌ 오류: {e}"
                ui.notify(f"생성 오류: {e}", type="negative")
            finally:
                state["generating"] = False

        async def generate_single(index: int):
            """개별 이미지 1장 생성"""
            if index >= len(state["prompts"]):
                return
            item = state["prompts"][index]
            seed = (
                int(seed_input.value) + index
                if seed_input.value is not None
                else None
            )
            result = await generator.generate(
                item["prompt"],
                scene_id=item["scene_id"],
                model=model_select.value,
                seed=seed,
            )
            if result["success"]:
                ui.notify(f"✅ {item['scene_id']} 생성 완료!", type="positive")
            else:
                ui.notify(f"❌ {item['scene_id']} 실패", type="negative")

        with ui.row().classes("gap-2 mt-3"):
            ui.button(
                "🚀 전체 이미지 생성",
                on_click=generate_all,
            ).props("color=positive size=lg")

            ui.button(
                "🗑️ 결과 초기화",
                on_click=lambda: (
                    result_container.clear(),
                    progress_label.set_text(""),
                    setattr(progress_bar, "visible", False),
                ),
            ).props("outline color=red")

    # ── 커스텀 프롬프트 (단일 생성) ──────────────────
    with ui.card().classes("w-full mb-4"):
        ui.label("✏️ 커스텀 프롬프트 (단일 이미지)").classes("text-lg font-semibold")

        custom_prompt = ui.textarea(
            label="이미지 프롬프트를 영어로 입력하세요",
            placeholder="A powerful martial arts master standing on a mountain peak, dramatic sunset...",
        ).classes("w-full").props("rows=3")

        custom_result = ui.column().classes("w-full mt-2")

        async def generate_custom():
            prompt = custom_prompt.value or ""
            if not prompt.strip():
                ui.notify("프롬프트를 입력하세요", type="warning")
                return

            ui.notify("생성 중...", type="info")
            seed = int(seed_input.value) if seed_input.value is not None else None
            result = await generator.generate(
                prompt.strip(),
                scene_id="custom",
                model=model_select.value,
                seed=seed,
            )
            custom_result.clear()
            with custom_result:
                if result["success"]:
                    ui.image(result["url"]).classes("w-full max-w-xl rounded shadow-lg")
                    ui.label(f"✅ 생성 완료 ({result['elapsed']:.1f}초)").classes(
                        "text-green-400"
                    )
                else:
                    ui.label("❌ 이미지 생성 실패").classes("text-red-400")

        ui.button("🎨 이미지 생성", on_click=generate_custom).props("color=primary")

    # 페이지 로드 시 스크립트 목록 불러오기
    asyncio.ensure_future(load_scripts())
