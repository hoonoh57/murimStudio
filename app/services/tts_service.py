"""TTS 서비스 — Edge TTS 기반 다국어 음성 생성"""

import os
import re
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path

import edge_tts

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  보이스 설정
# ──────────────────────────────────────────────
@dataclass
class Voice:
    id: str
    name: str
    lang: str
    gender: str
    style: str

VOICES: List[Voice] = [
    # 한국어
    Voice("ko-KR-HyunsuMultilingualNeural", "현수 (남, 다국어)", "ko", "남성", "차분·내레이션"),
    Voice("ko-KR-InJoonNeural",             "인준 (남)",          "ko", "남성", "젊은·에너지"),
    Voice("ko-KR-SunHiNeural",              "선희 (여)",          "ko", "여성", "밝은·명확"),
    # 영어
    Voice("en-US-AndrewMultilingualNeural",  "Andrew (Male, Multilingual)", "en", "Male", "Warm·Confident"),
    Voice("en-US-BrianMultilingualNeural",   "Brian (Male, Multilingual)",  "en", "Male", "Casual·Sincere"),
    Voice("en-US-AvaMultilingualNeural",     "Ava (Female, Multilingual)",  "en", "Female", "Expressive·Caring"),
    Voice("en-US-AriaNeural",               "Aria (Female)",               "en", "Female", "Positive·Confident"),
    Voice("en-US-GuyNeural",                "Guy (Male)",                  "en", "Male", "Passion·News"),
    Voice("en-US-JennyNeural",              "Jenny (Female)",              "en", "Female", "Friendly·Comfort"),
    # 인도네시아어
    Voice("id-ID-ArdiNeural",               "Ardi (Male)",   "id", "Male", "Friendly"),
    Voice("id-ID-GadisNeural",              "Gadis (Female)", "id", "Female", "Friendly"),
    # 태국어
    Voice("th-TH-NiwatNeural",              "Niwat (Male)",      "th", "Male", "Friendly"),
    Voice("th-TH-PremwadeeNeural",          "Premwadee (Female)", "th", "Female", "Friendly"),
]

# 언어별 기본 보이스
DEFAULT_VOICE = {
    "ko": "ko-KR-HyunsuMultilingualNeural",
    "en": "en-US-AndrewMultilingualNeural",
    "id": "id-ID-ArdiNeural",
    "th": "th-TH-NiwatNeural",
}

# 출력 디렉터리
AUDIO_DIR = Path("output/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


class TTSService:
    """Edge TTS 기반 음성 생성 서비스"""

    @staticmethod
    def list_voices(lang: str = "") -> List[dict]:
        """사용 가능한 보이스 목록 반환"""
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
        """
        텍스트를 음성으로 변환하여 MP3 파일로 저장.
        
        Returns:
            {"path": str, "voice": str, "duration_sec": float, "file_size": int}
        """
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
            # 대략적 길이 추정 (MP3 128kbps 기준)
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
        """짧은 미리듣기 생성. 파일 경로 반환."""
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
    ) -> dict:
        """
        스크립트 전체를 음성으로 변환.
        [이미지 프롬프트], [BGM] 등 태그는 제거하고 내레이션만 추출.
        """
        # 태그 제거
        narration = TTSService._extract_narration(script_content)
        if not narration.strip():
            raise ValueError("스크립트에서 내레이션 텍스트를 추출할 수 없습니다.")

        filename = f"script_{project_id}_{language}.mp3"
        result = await TTSService.generate(
            text=narration,
            voice_id=voice_id,
            language=language,
            rate=rate,
            pitch=pitch,
            output_filename=filename,
        )
        result["narration_length"] = len(narration)
        return result

    @staticmethod
    def _extract_narration(script: str) -> str:
        """스크립트에서 내레이션 텍스트만 추출 (태그·프롬프트 제거)"""
        lines = script.split('\n')
        narration_lines = []

        for line in lines:
            stripped = line.strip()
            # 태그 라인 제거
            if any(stripped.startswith(tag) for tag in [
                '[이미지 프롬프트', '[이미지프롬프트', '[Image Prompt',
                '[image prompt', '[BGM', '[bgm',
                '[HOOK', '[SCENE', '[OUTRO',
            ]):
                continue
            # 빈 줄 스킵
            if not stripped:
                continue
            # **볼드** 제목 라인은 스킵
            if stripped.startswith('**[') and stripped.endswith(']**'):
                continue
            # ## 마크다운 헤더 스킵
            if stripped.startswith('#'):
                continue

            narration_lines.append(stripped)

        return '\n'.join(narration_lines)
