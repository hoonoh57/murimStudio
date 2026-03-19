"""TTS 서비스 – Edge TTS 기반 다국어 음성 생성 (v1.7.1 — 제어문 필터링 + 씬별 오디오)"""

import os
import re
import json
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, List
from pathlib import Path

import edge_tts

logger = logging.getLogger(__name__)

# [번역 주석: 화산파=Mount Hua Sect, ...]
TRANSLATION_NOTE_PATTERN = re.compile(
    r'\[번역\s*주석[^\]]*\]',
    re.IGNORECASE
)

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


# ──────────────────────────────────────────────
# 제어문 패턴 (TTS가 읽으면 안 되는 모든 태그)
# ──────────────────────────────────────────────
# [HOOK - 0:00~0:05], [SCENE 1 - 0:05~2:00], [PROBLEM - 3~10초],
# [SOLUTION - 10~25초], [CTA - 마지막 3초], [OUTRO - 마지막 10초] 등
CONTROL_TAG_PATTERN = re.compile(
    r'\['
    r'(?:HOOK|SCENE\s*\d*|OUTRO|PROBLEM|SOLUTION|CTA|INTRO|BRIDGE|TRANSITION|CLIMAX|ENDING)'
    r'[^\]]*'
    r'\]',
    re.IGNORECASE
)

# [이미지 프롬프트: ...], [Image Prompt: ...], [BGM: ...], [SFX: ...],
# [자막: ...], [효과: ...], [음향: ...], [영상: ...]
PROMPT_TAG_PATTERN = re.compile(
    r'\['
    r'(?:이미지\s*프롬프트|Image\s*Prompt|BGM|bgm|SFX|sfx|SE|'
    r'자막|자막\s*스타일|효과|음향|영상|비디오|썸네일|thumbnail)'
    r'[^\]]*'
    r'\]',
    re.IGNORECASE
)

# **[HOOK]**, **[SCENE 1]** 형태의 볼드 태그
BOLD_TAG_PATTERN = re.compile(r'\*\*\[[^\]]*\]\*\*')

# 시간 표기만 있는 줄: 0:00~0:05, 00:00-00:05 등
TIME_ONLY_PATTERN = re.compile(r'^\s*\d{1,2}:\d{2}\s*[~\-–—]\s*\d{1,2}:\d{2}\s*$')


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

            # ffprobe로 정확한 길이 측정 (실패 시 추정값)
            duration_sec = await TTSService._get_audio_duration(str(output_path))
            if duration_sec <= 0:
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
    async def _get_audio_duration(audio_path: str) -> float:
        """ffprobe로 오디오 정확한 길이 측정"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", audio_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            data = json.loads(stdout.decode())
            return float(data["format"]["duration"])
        except Exception:
            return 0.0

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
        """스크립트에서 나레이션 텍스트만 추출
        — 제어문, 프롬프트 태그, 번역 주석, 괄호 영어 설명, 시간 표기 모두 제거
        — TTS가 읽을 순수 한국어 나레이션만 반환
        """
        lines = script.split('\n')
        narration_lines = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # 1) 볼드 태그 줄 전체 스킵: **[HOOK - 0:00~1.5초]**
            if BOLD_TAG_PATTERN.match(stripped):
                continue

            # 2) 제어문 태그 제거: [HOOK - 0:00~0:05], [PROBLEM - 3~10초] 등
            stripped = CONTROL_TAG_PATTERN.sub('', stripped)

            # 3) 프롬프트 태그가 포함된 줄 전체 스킵
            if PROMPT_TAG_PATTERN.search(line):
                continue

            # 4) 번역 주석 태그가 포함된 줄 전체 스킵
            if TRANSLATION_NOTE_PATTERN.search(line):
                continue

            # 5) 마크다운 헤더 스킵
            if stripped.startswith('#'):
                continue

            # 6) 시간만 있는 줄 스킵
            if TIME_ONLY_PATTERN.match(stripped):
                continue

            # 7) 괄호 안 영어 설명 제거 (다양한 패턴)
            #    화산파(Mount Hua Sect) → 화산파
            #    매화검법(Plum Blossom Sword Art) → 매화검법
            #    (Hidden Master) → 제거
            #    일반 괄호 한국어는 유지: (웃으며), (소리치며)
            cleaned = re.sub(r'\([A-Za-z][A-Za-z\s,\'\.~\-:;/&]*\)', '', stripped)
            # 혼합형 괄호도 제거: (Mount Hua 화산)
            cleaned = re.sub(r'\([A-Za-z][^\)]*[A-Za-z]\)', '', cleaned)
            cleaned = cleaned.replace('()', '')

            # 8) Midjourney 파라미터 제거: --ar 16:9, --v 5.2
            cleaned = re.sub(r'--\w+\s+\S+', '', cleaned)

            # 9) 인라인 태그 잔여물 제거: [BGM: xxx] 등이 줄 중간에 있을 수 있음
            cleaned = re.sub(r'\[[^\]]*\]', '', cleaned)

            # 10) 연속 공백 정리
            cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()

            # 11) 너무 짧으면 스킵
            if len(cleaned) < 2:
                continue

            narration_lines.append(cleaned)

        result = '\n'.join(narration_lines)
        logger.debug(f"[나레이션 추출] 원문 {len(script)}자 → 추출 {len(result)}자")
        return result


    # ──────────────────────────────────────────────
    # 씬별 나레이션 분리 (숏츠/롱폼 공용)
    # ──────────────────────────────────────────────
    @staticmethod
    def extract_scenes(script: str) -> List[dict]:
        """스크립트를 씬 단위로 분리하여 각 씬의 나레이션, 이미지프롬프트,
        BGM, SFX, 자막 스타일, 시간 정보를 딕셔너리 리스트로 반환.

        반환 예시:
        [
            {
                "section": "HOOK",
                "time_hint": "0~1.5초",
                "narration": "기타 천재 소녀의 충격적인 비밀!",
                "image_prompt": "close-up of girl playing guitar ...",
                "bgm": "tension_building",
                "sfx": "",
                "subtitle_style": "",
                "video_note": "",
            },
            ...
        ]
        """
        # 섹션 시작 패턴: [HOOK - 0:00~0:05] 또는 [SCENE 1 - 0:05~2:00] 등
        section_pattern = re.compile(
            r'\[?\*{0,2}\[?'
            r'(HOOK|SCENE\s*\d*|OUTRO|PROBLEM|SOLUTION|CTA|INTRO|BRIDGE|CLIMAX|ENDING)'
            r'(?:\s*[-–—]\s*(.+?))?'
            r'\]?\*{0,2}\]?'
            r'\s*$',
            re.IGNORECASE
        )

        image_prompt_pattern = re.compile(
            r'\[이미지\s*프롬프트\s*[:：]\s*(.+?)\]'
            r'|\[Image\s*Prompt\s*[:：]\s*(.+?)\]',
            re.DOTALL | re.IGNORECASE
        )
        bgm_pattern = re.compile(r'\[BGM\s*[:：]\s*(.+?)\]', re.IGNORECASE)
        sfx_pattern = re.compile(r'\[SFX\s*[:：]\s*(.+?)\]', re.IGNORECASE)
        subtitle_pattern = re.compile(r'\[자막(?:\s*스타일)?\s*[:：]\s*(.+?)\]', re.IGNORECASE)
        video_pattern = re.compile(r'\[영상\s*[:：]\s*(.+?)\]', re.IGNORECASE)

        scenes = []
        current = None

        for line in script.split('\n'):
            stripped = line.strip()
            if not stripped:
                continue

            # 새 섹션 시작?
            m = section_pattern.match(stripped)
            if m:
                if current is not None:
                    scenes.append(current)
                current = {
                    "section": m.group(1).strip().upper(),
                    "time_hint": (m.group(2) or "").strip(),
                    "narration": "",
                    "image_prompt": "",
                    "bgm": "",
                    "sfx": "",
                    "subtitle_style": "",
                    "video_note": "",
                }
                continue

            if current is None:
                # 섹션 헤더 전에 나온 내용은 기본 섹션으로
                current = {
                    "section": "INTRO",
                    "time_hint": "",
                    "narration": "",
                    "image_prompt": "",
                    "bgm": "",
                    "sfx": "",
                    "subtitle_style": "",
                    "video_note": "",
                }

            # 이미지 프롬프트
            img_m = image_prompt_pattern.search(stripped)
            if img_m:
                current["image_prompt"] = (img_m.group(1) or img_m.group(2) or "").strip()
                continue

            # BGM
            bgm_m = bgm_pattern.search(stripped)
            if bgm_m:
                current["bgm"] = bgm_m.group(1).strip()
                continue

            # SFX
            sfx_m = sfx_pattern.search(stripped)
            if sfx_m:
                current["sfx"] = sfx_m.group(1).strip()
                continue

            # 자막 스타일
            sub_m = subtitle_pattern.search(stripped)
            if sub_m:
                current["subtitle_style"] = sub_m.group(1).strip()
                continue

            # 영상 노트
            vid_m = video_pattern.search(stripped)
            if vid_m:
                current["video_note"] = vid_m.group(1).strip()
                continue

            # 볼드 태그 줄 스킵
            if BOLD_TAG_PATTERN.match(stripped):
                continue

            # 제어문 줄 스킵 (이미 section_pattern으로 캐치 안 된 것)
            if CONTROL_TAG_PATTERN.match(stripped):
                continue

            # 마크다운 헤더 스킵
            if stripped.startswith('#'):
                continue

            # 나머지 = 나레이션
            cleaned = re.sub(r'\([A-Za-z][A-Za-z\s,\'\.~\-]*\)', '', stripped)
            cleaned = cleaned.replace('()', '')
            cleaned = re.sub(r'--\w+\s+\S+', '', cleaned)
            cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
            if len(cleaned) >= 2:
                if current["narration"]:
                    current["narration"] += "\n" + cleaned
                else:
                    current["narration"] = cleaned

        if current is not None:
            scenes.append(current)

        logger.info(f"[씬 분리] {len(scenes)}개 씬 추출")
        return scenes
