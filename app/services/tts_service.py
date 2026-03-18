"""TTS 서비스 – Edge TTS 기반 다국어 음성 생성 (확장판)"""

import os
import re
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path

import edge_tts

logger = logging.getLogger(__name__)


@dataclass
class Voice:
    id: str
    name: str
    lang: str
    gender: str
    style: str

VOICES: List[Voice] = [
    # ── 한국어 네이티브 ──
    Voice("ko-KR-HyunsuMultilingualNeural", "현수 (남, 다국어)", "ko", "남성", "차분·내레이션"),
    Voice("ko-KR-InJoonNeural",             "인준 (남)",          "ko", "남성", "안정·에너지"),
    Voice("ko-KR-SunHiNeural",              "선히 (여)",          "ko", "여성", "밝음·명확"),
    # ── 다국어 모델 (한국어 가능) ──
    Voice("en-US-AndrewMultilingualNeural",  "Andrew 다국어 (남)", "ko", "남성", "따뜻·자신감"),
    Voice("en-US-BrianMultilingualNeural",   "Brian 다국어 (남)",  "ko", "남성", "캐주얼·진중"),
    Voice("en-US-AvaMultilingualNeural",     "Ava 다국어 (여)",    "ko", "여성", "표현력·감성"),
    Voice("en-US-EmmaMultilingualNeural",    "Emma 다국어 (여)",   "ko", "여성", "부드럽·자연"),
    Voice("en-AU-WilliamMultilingualNeural", "William 다국어 (남)","ko", "남성", "깊은·안정"),
    Voice("fr-FR-VivienneMultilingualNeural","Vivienne 다국어 (여)","ko","여성", "우아·세련"),
    Voice("fr-FR-RemyMultilingualNeural",    "Remy 다국어 (남)",   "ko", "남성", "중후·클래식"),
    Voice("de-DE-SeraphinaMultilingualNeural","Seraphina 다국어 (여)","ko","여성","또렷·전문"),
    Voice("de-DE-FlorianMultilingualNeural", "Florian 다국어 (남)","ko", "남성", "힘·권위"),
    Voice("it-IT-GiuseppeMultilingualNeural","Giuseppe 다국어 (남)","ko","남성", "열정·드라마"),
    # ── 영어 전용 ──
    Voice("en-US-AriaNeural",               "Aria (여, EN)",      "en", "Female", "Positive·Confident"),
    Voice("en-US-GuyNeural",                "Guy (남, EN)",       "en", "Male", "Passion·News"),
    Voice("en-US-JennyNeural",              "Jenny (여, EN)",     "en", "Female", "Friendly·Comfort"),
    # ── 인도네시아어 ──
    Voice("id-ID-ArdiNeural",               "Ardi (남, ID)",      "id", "Male", "Friendly"),
    Voice("id-ID-GadisNeural",              "Gadis (여, ID)",     "id", "Female", "Friendly"),
    # ── 태국어 ──
    Voice("th-TH-NiwatNeural",              "Niwat (남, TH)",     "th", "Male", "Friendly"),
    Voice("th-TH-PremwadeeNeural",          "Premwadee (여, TH)", "th", "Female", "Friendly"),
]

DEFAULT_VOICE = {
    "ko": "ko-KR-HyunsuMultilingualNeural",
    "en": "en-US-AndrewMultilingualNeural",
    "id": "id-ID-ArdiNeural",
    "th": "th-TH-NiwatNeural",
}

AUDIO_DIR = Path("output/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


class TTSService:
    """Edge TTS 기반 음성 생성 서비스"""

    @staticmethod
    def list_voices(lang: str = "") -> List[dict]:
        voices = VOICES
        if lang:
            voices = [v for v in voices if v.lang == lang]
        return [
            {"id": v.id, "name": v.name, "lang": v.lang,
             "gender": v.gender, "style": v.style}
            for v in voices
        ]

    @staticmethod
    async def generate(
        text: str,
        voice_id: str = "",
        language: str = "ko",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        output_filename: str = "",
    ) -> dict:
        if not text or not text.strip():
            raise ValueError("TTS 변환할 텍스트가 비어있습니다.")

        text = text.strip()

        if not voice_id:
            voice_id = DEFAULT_VOICE.get(language, DEFAULT_VOICE["ko"])

        if not output_filename:
            safe_name = re.sub(r'[^\w가-힣]', '_', text[:30])
            output_filename = f"tts_{safe_name}_{voice_id.split('-')[0]}.mp3"

        output_path = AUDIO_DIR / output_filename

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice_id,
                rate=rate,
                pitch=pitch,
            )
            await communicate.save(str(output_path))

            file_size = output_path.stat().st_size

            if file_size < 100:
                raise ValueError(
                    f"생성된 오디오 파일이 너무 작습니다 ({file_size}B). "
                    f"텍스트나 보이스 설정을 확인하세요."
                )

            duration_sec = round(file_size / (128 * 1024 / 8), 1)

            logger.info(
                f"[TTS] 생성 완료: {output_filename} "
                f"({file_size:,}B, ~{duration_sec}s, voice={voice_id})"
            )

            return {
                "path": str(output_path),
                "filename": output_filename,
                "voice": voice_id,
                "duration_sec": duration_sec,
                "file_size": file_size,
                "rate": rate,
                "pitch": pitch,
            }

        except Exception as e:
            logger.error(f"[TTS] 생성 실패: {e}")
            raise

    @staticmethod
    async def generate_preview(
        text: str,
        voice_id: str,
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ) -> str:
        if not text or not text.strip():
            raise ValueError("미리듣기할 텍스트가 비어있습니다.")

        safe_id = voice_id.replace("-", "_")
        filename = f"preview_{safe_id}.mp3"
        result = await TTSService.generate(
            text=text[:200],
            voice_id=voice_id,
            rate=rate,
            pitch=pitch,
            output_filename=filename,
        )
        return result["path"]

    @staticmethod
    async def generate_from_script(
        script_content: str,
        voice_id: str = "",
        language: str = "ko",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        project_id: int = 0,
        script_id: int = 0,
    ) -> dict:
        if not script_content or not script_content.strip():
            raise ValueError("스크립트 내용이 비어있습니다.")

        narration = TTSService._extract_narration(script_content)
        if not narration or len(narration.strip()) < 10:
            raise ValueError(
                f"스크립트에서 나레이션 텍스트를 추출할 수 없습니다. "
                f"(추출된 텍스트: {len(narration)}자)"
            )

        if not voice_id:
            voice_id = DEFAULT_VOICE.get(language, DEFAULT_VOICE["ko"])
        voice_short = voice_id.split("-")[-1].replace("Neural", "")
        filename = f"script_{script_id}_{language}_{voice_short}.mp3"

        result = await TTSService.generate(
            text=narration,
            voice_id=voice_id,
            language=language,
            rate=rate,
            pitch=pitch,
            output_filename=filename,
        )
        result["narration_length"] = len(narration)
        result["script_id"] = script_id
        return result

    @staticmethod
    def extract_narration(script: str) -> str:
        """외부에서도 호출 가능한 나레이션 추출 (미리보기용)"""
        return TTSService._extract_narration(script)

    @staticmethod
    def _extract_narration(script: str) -> str:
        """스크립트에서 나레이션 텍스트만 추출 (태그·프롬프트·영어 주석 제거)"""
        lines = script.split('\n')
        narration_lines = []

        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(tag) for tag in [
                '[이미지 프롬프트', '[이미지프롬프트', '[Image Prompt',
                '[image prompt', '[BGM', '[bgm',
                '[HOOK', '[SCENE', '[OUTRO',
            ]):
                continue
            if not stripped:
                continue
            if stripped.startswith('**[') and stripped.endswith(']**'):
                continue
            if stripped.startswith('#'):
                continue

            # 괄호 안 영어 설명 제거: (Hidden Master), (Martial Arts) 등
            cleaned = re.sub(r'\([A-Za-z][A-Za-z\s,\'\.~\-]*\)', '', stripped)
            cleaned = cleaned.replace('()', '')
            cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
            cleaned = re.sub(r'--\w+\s+\S+', '', cleaned).strip()

            if cleaned:
                narration_lines.append(cleaned)

        return '\n'.join(narration_lines)
