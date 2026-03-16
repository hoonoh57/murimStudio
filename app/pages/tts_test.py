"""TTS 테스트 페이지 — 보이스 미리듣기 및 비교"""

import asyncio
from nicegui import ui
from app.services.tts_service import TTSService, VOICES


def create():
    """TTS 테스트 UI"""
    tts = TTSService()

    ui.label("🔊 TTS 보이스 테스트").classes("text-2xl font-bold mb-4")
    ui.label("다양한 보이스로 미리 듣고 비교한 뒤, 스크립트에 적용할 보이스를 선택하세요.").classes("text-gray-400 mb-4")

    # ── 테스트 텍스트 입력 ──
    with ui.card().classes("w-full mb-4"):
        ui.label("테스트 텍스트").classes("font-bold")
        test_text = ui.textarea(
            value="천하를 호령했던 매화검존 청명이 백 년 만에 아이의 몸으로 환생했다. "
                  "몰락한 화산파를 다시 일으켜 세우기 위한 그의 험난한 여정이 시작된다!",
        ).classes("w-full").props("rows=3")

    # ── 언어 선택 ──
    lang_options = {"ko": "🇰🇷 한국어", "en": "🇺🇸 English", "id": "🇮🇩 Indonesia", "th": "🇹🇭 ไทย"}
    selected_lang = ui.select(
        lang_options, value="ko", label="언어 선택"
    ).classes("w-48 mb-4")

    # ── 속도·피치 조절 ──
    with ui.row().classes("mb-4 gap-4"):
        rate_select = ui.select(
            {"-30%": "느리게 (-30%)", "-15%": "약간 느리게", "+0%": "보통", "+15%": "약간 빠르게", "+30%": "빠르게"},
            value="+0%", label="속도"
        ).classes("w-40")
        pitch_select = ui.select(
            {"-50Hz": "낮게 (-50Hz)", "-25Hz": "약간 낮게", "+0Hz": "보통", "+25Hz": "약간 높게", "+50Hz": "높게"},
            value="+0Hz", label="피치"
        ).classes("w-40")

    # ── 보이스 카드 그리드 ──
    voice_container = ui.column().classes("w-full gap-2")
    status_label = ui.label("").classes("text-green-400")

    def build_voice_cards():
        voice_container.clear()
        lang = selected_lang.value
        voices = [v for v in VOICES if v.lang == lang]

        with voice_container:
            if not voices:
                ui.label("선택한 언어에 사용 가능한 보이스가 없습니다.").classes("text-yellow-400")
                return

            for v in voices:
                with ui.card().classes("w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        with ui.column().classes("gap-0"):
                            ui.label(v.name).classes("font-bold text-lg")
                            ui.label(f"{v.id}").classes("text-xs text-gray-500")
                            ui.label(f"{v.gender} · {v.style}").classes("text-sm text-gray-400")

                        with ui.row().classes("gap-2"):
                            audio_container = ui.column()

                            async def on_preview(voice=v, container=audio_container):
                                status_label.text = f"🔄 {voice.name} 생성 중..."
                                try:
                                    path = await tts.generate_preview(
                                        text=test_text.value,
                                        voice_id=voice.id,
                                        rate=rate_select.value,
                                        pitch=pitch_select.value,
                                    )
                                    container.clear()
                                    with container:
                                        ui.audio(path).classes("w-64")
                                    status_label.text = f"✅ {voice.name} 생성 완료"
                                except Exception as e:
                                    status_label.text = f"❌ {voice.name} 실패: {e}"

                            ui.button("▶ 미리듣기", on_click=on_preview).props("dense color=primary")

    # 언어 변경 시 카드 재생성
    selected_lang.on_value_change(lambda _: build_voice_cards())
    build_voice_cards()

    # ── 스크립트 전체 TTS 변환 섹션 ──
    ui.separator().classes("my-6")
    ui.label("📝 스크립트 → 음성 변환").classes("text-xl font-bold mb-2")

    with ui.card().classes("w-full"):
        with ui.row().classes("gap-4 items-end"):
            script_id_input = ui.number("스크립트 ID", value=7, min=1).classes("w-32")
            voice_select = ui.select(
                {v.id: v.name for v in VOICES},
                value="ko-KR-HyunsuMultilingualNeural",
                label="보이스 선택"
            ).classes("w-64")

            script_audio = ui.column()
            script_status = ui.label("").classes("text-green-400")

            async def on_generate_script_tts():
                script_status.text = "🔄 스크립트 음성 변환 중... (30초~1분 소요)"
                try:
                    from app.services.script_factory import ScriptFactory
                    factory = ScriptFactory()
                    scripts = await factory.list_scripts()
                    target = next(
                        (s for s in scripts if s["id"] == int(script_id_input.value)),
                        None
                    )
                    if not target:
                        script_status.text = f"❌ 스크립트 ID {int(script_id_input.value)}를 찾을 수 없습니다."
                        return

                    # 전체 content 가져오기
                    import aiosqlite
                    async with aiosqlite.connect("app.db") as db:
                        db.row_factory = aiosqlite.Row
                        async with db.execute(
                            "SELECT content, language, project_id FROM scripts WHERE id = ?",
                            (int(script_id_input.value),)
                        ) as cursor:
                            row = await cursor.fetchone()

                    if not row:
                        script_status.text = "❌ 스크립트 내용을 찾을 수 없습니다."
                        return

                    result = await tts.generate_from_script(
                        script_content=row["content"],
                        voice_id=voice_select.value,
                        language=row["language"],
                        rate=rate_select.value,
                        pitch=pitch_select.value,
                        project_id=row["project_id"],
                    )

                    script_audio.clear()
                    with script_audio:
                        ui.audio(result["path"]).classes("w-full")
                        ui.label(
                            f"파일: {result['filename']} | "
                            f"크기: {result['file_size']:,}B | "
                            f"길이: ~{result['duration_sec']}s | "
                            f"텍스트: {result['narration_length']}자"
                        ).classes("text-xs text-gray-400")

                    script_status.text = "✅ 음성 변환 완료"
                except Exception as e:
                    script_status.text = f"❌ 변환 실패: {e}"

            ui.button("🔊 음성 변환", on_click=on_generate_script_tts).props("color=positive")

        script_audio
        script_status
