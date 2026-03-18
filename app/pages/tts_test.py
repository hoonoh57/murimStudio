"""TTS 보이스 테스트 페이지 – 스크립트 미리보기·편집 포함"""

import asyncio
from nicegui import ui
from app.services.tts_service import TTSService, VOICES
from app.db import get_db


def create():
    """TTS 테스트 UI"""
    tts = TTSService()

    ui.label("🔊 TTS 보이스 테스트").classes("text-2xl font-bold mb-4")
    ui.label("다양한 보이스로 미리 듣고 비교한 뒤, 스크립트에 적용할 보이스를 선택하세요.").classes("text-gray-400 mb-4")

    # ── 테스트 텍스트 입력 ──
    with ui.card().classes("w-full mb-4"):
        ui.label("✏️ 테스트 텍스트").classes("font-bold")
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
            {"-30%": "느리게(-30%)", "-15%": "약간 느리게", "+0%": "보통", "+15%": "약간 빠르게", "+30%": "빠르게"},
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

            # 네이티브 / 다국어 구분
            native = [v for v in voices if v.id.startswith(f"{lang[:2]}") or v.id.startswith("ko-KR")]
            multi = [v for v in voices if v not in native]

            if native:
                ui.label(f"🎤 네이티브 ({len(native)}개)").classes("font-semibold text-blue-300")
                for v in native:
                    _voice_card(v)

            if multi:
                ui.label(f"🌐 다국어 모델 ({len(multi)}개)").classes("font-semibold text-purple-300 mt-3")
                ui.label("한국어 읽기 가능한 해외 모델 – 독특한 억양과 톤").classes("text-xs text-gray-500")
                for v in multi:
                    _voice_card(v)

    def _voice_card(v):
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

    selected_lang.on_value_change(lambda _: build_voice_cards())
    build_voice_cards()

    # ── 스크립트 → 음성 변환 섹션 ──
    ui.separator().classes("my-6")
    ui.label("📄 스크립트 → 음성 변환").classes("text-xl font-bold mb-2")

    with ui.card().classes("w-full"):
        # 스크립트 선택
        ui.label("1️⃣ 스크립트 선택").classes("font-semibold mb-2")
        with ui.row().classes("gap-4 items-end"):
            script_id_input = ui.number("스크립트 ID", value=15, min=1).classes("w-32")
            load_btn_container = ui.row()

        # 나레이션 미리보기 & 편집
        ui.label("2️⃣ 나레이션 미리보기 (편집 가능)").classes("font-semibold mt-4 mb-2")
        ui.label(
            "TTS가 읽을 텍스트입니다. 불필요한 문장이나 단어를 여기서 수정하세요."
        ).classes("text-xs text-gray-500 mb-1")

        narration_area = ui.textarea(
            label="나레이션 텍스트",
            placeholder="스크립트를 불러오면 여기에 나레이션이 표시됩니다...",
        ).classes("w-full").props("rows=12")

        narration_info = ui.label("").classes("text-xs text-gray-400 mt-1")

        async def load_narration():
            """스크립트 로드 → 나레이션 추출 → 미리보기"""
            sid = int(script_id_input.value)
            try:
                db = await get_db()
                row = await db.execute(
                    "SELECT content, language, project_id FROM scripts WHERE id = ?",
                    (sid,)
                )
                result = await row.fetchone()

                if not result or not result[0]:
                    narration_area.value = ""
                    narration_info.text = f"❌ 스크립트 ID {sid}를 찾을 수 없습니다."
                    return

                content = result[0]
                narration = TTSService.extract_narration(content)
                narration_area.value = narration
                narration_area.update()

                char_count = len(narration)
                line_count = len([l for l in narration.split('\n') if l.strip()])
                est_duration = char_count / 5.5  # 한국어 약 5.5자/초
                narration_info.text = (
                    f"📊 {char_count}자 · {line_count}줄 · "
                    f"예상 길이: ~{est_duration:.0f}초 ({est_duration/60:.1f}분) · "
                    f"언어: {result[1]}"
                )
            except Exception as e:
                narration_info.text = f"❌ 로드 실패: {e}"

        with load_btn_container:
            ui.button("📂 스크립트 불러오기", on_click=load_narration).props("color=primary")

        # 보이스 선택 & 생성
        ui.label("3️⃣ 보이스 선택 & 생성").classes("font-semibold mt-4 mb-2")

        # 한국어 보이스만 필터 (네이티브 + 다국어)
        ko_voices = {v.id: f"{v.name} – {v.style}" for v in VOICES if v.lang == "ko"}

        with ui.row().classes("gap-4 items-end"):
            voice_select = ui.select(
                ko_voices,
                value="ko-KR-HyunsuMultilingualNeural",
                label="보이스 선택"
            ).classes("w-80")

        script_audio = ui.column().classes("w-full mt-3")
        script_status = ui.label("").classes("text-green-400 mt-2")

        async def on_generate_script_tts():
            narration = narration_area.value
            if not narration or len(narration.strip()) < 10:
                script_status.text = "❌ 나레이션 텍스트가 비어있습니다. 먼저 스크립트를 불러오세요."
                return

            sid = int(script_id_input.value)
            script_status.text = "🔄 음성 변환 중... (30초~1분 소요)"

            try:
                # 편집된 나레이션 직접 사용
                voice_id = voice_select.value
                voice_short = voice_id.split("-")[-1].replace("Neural", "")
                filename = f"script_{sid}_ko_{voice_short}.mp3"

                result = await TTSService.generate(
                    text=narration,
                    voice_id=voice_id,
                    language="ko",
                    rate=rate_select.value,
                    pitch=pitch_select.value,
                    output_filename=filename,
                )

                script_audio.clear()
                with script_audio:
                    ui.audio(result["path"]).classes("w-full")
                    ui.label(
                        f"파일: {result['filename']} | "
                        f"크기: {result['file_size']:,}B | "
                        f"길이: ~{result['duration_sec']}s | "
                        f"텍스트: {len(narration)}자"
                    ).classes("text-xs text-gray-400")

                script_status.text = f"✅ 음성 변환 완료 – {result['filename']}"
            except Exception as e:
                script_status.text = f"❌ 변환 실패: {e}"

        ui.button("🔊 음성 변환", on_click=on_generate_script_tts).props("color=positive size=lg")
