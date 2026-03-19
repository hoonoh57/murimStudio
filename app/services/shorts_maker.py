"""YouTube Shorts 제작기 – 9:16 세로 영상, Ken Burns, 자막 오버레이"""

import os
import re
import json
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SHORTS_DIR = Path("output/shorts")
SHORTS_DIR.mkdir(parents=True, exist_ok=True)

# 숏츠 사양
WIDTH = 1080
HEIGHT = 1920
FPS = 30
MAX_DURATION = 59  # 안전하게 59초


@dataclass
class ShortsScene:
    """숏츠 한 장면"""
    image_path: str
    narration: str
    duration: float = 0.0  # TTS 후 결정
    subtitle_lines: List[str] = field(default_factory=list)
    effect: str = "zoom_center"  # zoom_center, zoom_top, pan_left, pan_right


@dataclass
class ShortsProject:
    """숏츠 프로젝트"""
    title: str
    hook_text: str  # 첫 1.5초 텍스트
    scenes: List[ShortsScene] = field(default_factory=list)
    bgm_path: Optional[str] = None
    output_filename: str = "short.mp4"


class ShortsMaker:
    """숏츠 영상 제작기"""

    # Ken Burns 효과 프리셋 (9:16 세로)
    EFFECTS = {
        "zoom_center": {
            "desc": "중앙 줌인",
            "filter": "zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
        },
        "zoom_top": {
            "desc": "상단 줌인 (인물 얼굴)",
            "filter": "zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='0':d={frames}:s={w}x{h}:fps={fps}"
        },
        "pan_left": {
            "desc": "좌→우 패닝",
            "filter": "zoompan=z='1.2':x='if(eq(on,1),0,x+2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
        },
        "pan_right": {
            "desc": "우→좌 패닝",
            "filter": "zoompan=z='1.2':x='if(eq(on,1),iw,x-2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
        },
        "zoom_out": {
            "desc": "줌아웃 (전체 공개)",
            "filter": "zoompan=z='if(eq(on,1),1.3,max(zoom-0.0015,1))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
        },
    }

    # 자막 스타일
    SUBTITLE_STYLE = (
        "FontName=NanumSquareRoundEB,"
        "FontSize=22,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=3,"
        "Outline=2,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=80"
    )

    @staticmethod
    async def get_audio_duration(audio_path: str) -> float:
        """ffprobe로 오디오 길이"""
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
        except Exception as e:
            logger.error(f"오디오 길이 측정 실패: {e}")
            return 0.0

    @staticmethod
    def generate_ass_subtitle(scenes: List[ShortsScene], output_path: str) -> str:
        """ASS 자막 파일 생성 — 큰 글씨, 하단 배치, 2줄씩"""
        ass_content = f"""[Script Info]
Title: Shorts Subtitle
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,NanumSquareRoundEB,28,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,3,3,0,2,20,20,100,1
Style: Hook,NanumSquareRoundEB,36,&H0000FFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,3,4,0,2,20,20,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        current_time = 0.0
        for i, scene in enumerate(scenes):
            style = "Hook" if i == 0 else "Default"
            for line in scene.subtitle_lines:
                line_duration = max(len(line) * 0.12, 1.5)  # 글자당 0.12초, 최소 1.5초
                start = ShortsMaker._format_ass_time(current_time)
                end = ShortsMaker._format_ass_time(current_time + line_duration)
                # 줄바꿈 처리
                safe_line = line.replace("\n", "\\N")
                ass_content += f"Dialogue: 0,{start},{end},{style},,0,0,0,,{safe_line}\n"
                current_time += line_duration

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        logger.info(f"[자막] ASS 생성: {output_path}")
        return output_path

    @staticmethod
    def _format_ass_time(seconds: float) -> str:
        """초 → ASS 시간 형식 (H:MM:SS.CC)"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    @staticmethod
    def split_narration_to_subtitle(narration: str, max_chars: int = 18) -> List[str]:
        """나레이션을 자막용 짧은 줄로 분할 (한국어 기준 18자)"""
        # 문장 단위 분리
        sentences = re.split(r'(?<=[.!?。])\s*', narration.strip())
        lines = []
        for sent in sentences:
            if not sent.strip():
                continue
            # 긴 문장은 쪼개기
            while len(sent) > max_chars:
                # 조사/접속사 기준 분할
                cut = max_chars
                for sep in [', ', '에 ', '은 ', '는 ', '을 ', '를 ', '이 ', '가 ', '의 ', '와 ', '과 ', ' ']:
                    idx = sent[:max_chars + 5].rfind(sep)
                    if idx > 5:
                        cut = idx + len(sep)
                        break
                lines.append(sent[:cut].strip())
                sent = sent[cut:].strip()
            if sent:
                lines.append(sent)
        return lines

    @staticmethod
    async def create_scene_clip(
        image_path: str,
        duration: float,
        effect: str,
        output_path: str,
    ) -> bool:
        """이미지 1장 → Ken Burns 효과 적용 세로 클립 생성"""
        frames = max(int(duration * FPS), FPS)  # 최소 1초 분량

        effect_template = ShortsMaker.EFFECTS.get(effect, ShortsMaker.EFFECTS["zoom_center"])
        zoompan = effect_template["filter"].format(
            frames=frames, w=WIDTH, h=HEIGHT, fps=FPS
        )

        # 핵심 수정: 이미지를 먼저 세로 비율(9:16)에 맞게 확대/크롭 후 zoompan 적용
        # 1) scale: 가로 기준으로 넓게 스케일 (zoompan이 줌할 여유 확보)
        # 2) pad: 세로가 부족하면 패딩
        # 3) crop: 정확히 필요한 크기로 자르기
        # 4) zoompan: Ken Burns 효과 (출력 크기 1080x1920)
        # 5) fade: 인/아웃
        fade_out_start = max(duration - 0.3, 0.1)
        filter_complex = (
            f"[0:v]"
            f"scale=w='if(gt(iw/ih,{WIDTH}/{HEIGHT}),{WIDTH}*4,-2)':h='if(gt(iw/ih,{WIDTH}/{HEIGHT}),-2,{HEIGHT}*4)',"
            f"pad=w='max(iw,{WIDTH}*4)':h='max(ih,{HEIGHT}*4)':x='(ow-iw)/2':y='(oh-ih)/2':color=black,"
            f"setsar=1:1,"
            f"{zoompan},"
            f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out_start}:d=0.3"
            f"[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-t", str(duration + 1),  # 입력을 duration보다 약간 길게
            "-i", image_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            "-t", str(duration),
            output_path
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_text = stderr.decode()[-500:]
                logger.error(f"[씬 클립 실패] {err_text}")
                # 폴백: 간단한 스케일만 적용
                return await ShortsMaker._create_simple_clip(image_path, duration, output_path)
            logger.info(f"[씬 클립] {output_path} ({duration:.1f}s, {effect})")
            return True
        except Exception as e:
            logger.error(f"[씬 클립 에러] {e}")
            return False

    @staticmethod
    async def _create_simple_clip(
        image_path: str, duration: float, output_path: str
    ) -> bool:
        """Ken Burns 실패 시 폴백 — 단순 스케일+크롭으로 정적 클립 생성"""
        logger.warning(f"[폴백] 단순 클립 생성: {image_path}")
        fade_out = max(duration - 0.3, 0.1)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-t", str(duration + 1),
            "-i", image_path,
            "-vf", (
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={WIDTH}:{HEIGHT},"
                f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out}:d=0.3"
            ),
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            "-t", str(duration),
            output_path
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"[폴백도 실패] {stderr.decode()[-300:]}")
                return False
            logger.info(f"[폴백 클립] {output_path} ({duration:.1f}s)")
            return True
        except Exception as e:
            logger.error(f"[폴백 에러] {e}")
            return False


    @staticmethod
    async def assemble_shorts(
        scene_clips: List[str],
        audio_path: str,
        subtitle_path: Optional[str],
        output_path: str,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.15,
    ) -> dict:
        """씬 클립들 + 오디오 + 자막 → 최종 숏츠 MP4"""

        # concat 파일 생성
        concat_file = SHORTS_DIR / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for clip in scene_clips:
                f.write(f"file '{os.path.abspath(clip)}'\n")

        # 기본 명령
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file)]

        # 오디오 추가
        cmd.extend(["-i", audio_path])

        # BGM 추가
        if bgm_path and os.path.exists(bgm_path):
            cmd.extend(["-i", bgm_path])

        # 필터 구성
        filters = []

        if bgm_path and os.path.exists(bgm_path):
            # TTS + BGM 믹싱
            filters.append(f"[1:a]volume=1.0[tts];[2:a]volume={bgm_volume}[bgm];[tts][bgm]amix=inputs=2:duration=shortest[aout]")
            audio_map = "[aout]"
        else:
            audio_map = "1:a"

        # 자막 burn-in
        if subtitle_path and os.path.exists(subtitle_path):
            safe_sub = subtitle_path.replace("\\", "/").replace(":", "\\:")
            if filters:
                filters.insert(0, f"[0:v]ass='{safe_sub}'[vout]")
                video_map = "[vout]"
            else:
                cmd.extend(["-vf", f"ass='{safe_sub}'"])
                video_map = None
        else:
            video_map = None

        if filters:
            cmd.extend(["-filter_complex", ";".join(filters)])

        if video_map:
            cmd.extend(["-map", video_map])
        else:
            cmd.extend(["-map", "0:v"])

        if "[aout]" in str(filters):
            cmd.extend(["-map", audio_map])
        else:
            cmd.extend(["-map", audio_map])

        cmd.extend([
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-r", str(FPS),
            "-shortest",
            output_path
        ])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr.decode()[-800:]
                logger.error(f"[숏츠 조립 실패] {error_msg}")
                return {"success": False, "error": error_msg}

            # 결과 확인
            file_size = os.path.getsize(output_path)
            duration = await ShortsMaker.get_audio_duration(output_path)

            logger.info(f"[숏츠 완성] {output_path} | {duration:.1f}s | {file_size / 1024 / 1024:.1f}MB")

            return {
                "success": True,
                "path": output_path,
                "url": f"/output/shorts/{Path(output_path).name}",
                "duration": duration,
                "file_size": file_size,
                "scenes": len(scene_clips),
            }

        except Exception as e:
            logger.error(f"[숏츠 조립 에러] {e}")
            return {"success": False, "error": str(e)}
        finally:
            # 임시 파일 정리
            if concat_file.exists():
                concat_file.unlink()

    @staticmethod
    async def make_shorts_from_script(
        script_content: str,
        images: List[str],
        voice_id: str = "ko-KR-HyunsuMultilingualNeural",
        rate: str = "+10%",
        effects: Optional[List[str]] = None,
        output_name: str = "shorts_output.mp4",
    ) -> dict:
        """스크립트 → TTS → 자막 → Ken Burns → 숏츠 원스톱 제작"""
        from app.services.tts_service import TTSService

        # 1. 나레이션 추출
        narration = TTSService._extract_narration(script_content)
        if not narration or len(narration.strip()) < 10:
            return {"success": False, "error": "나레이션 텍스트가 부족합니다"}

        # 숏츠는 짧게 — 최대 300자로 제한
        if len(narration) > 300:
            sentences = re.split(r'(?<=[.!?。])\s*', narration)
            trimmed = ""
            for s in sentences:
                if len(trimmed) + len(s) > 300:
                    break
                trimmed += s + " "
            narration = trimmed.strip()

        # 2. TTS 생성
        tts_filename = f"shorts_{output_name.replace('.mp4', '')}.mp3"
        try:
            tts_result = await TTSService.generate(
                text=narration,
                voice_id=voice_id,
                rate=rate,
                pitch="+0Hz",
                output_filename=tts_filename
            )
            audio_path = tts_result["path"]
        except Exception as e:
            return {"success": False, "error": f"TTS 실패: {e}"}

        # 3. 오디오 길이 확인
        audio_duration = await ShortsMaker.get_audio_duration(audio_path)
        if audio_duration <= 0:
            return {"success": False, "error": "오디오 길이 측정 실패"}

        if audio_duration > MAX_DURATION:
            logger.warning(f"숏츠 길이 초과: {audio_duration:.1f}s > {MAX_DURATION}s")

        # 4. 이미지별 시간 배분
        num_images = len(images)
        if num_images == 0:
            return {"success": False, "error": "이미지가 없습니다"}

        per_image = audio_duration / num_images

        # 5. 자막 생성
        subtitle_lines = ShortsMaker.split_narration_to_subtitle(narration)
        scenes = []
        lines_per_scene = max(1, len(subtitle_lines) // num_images)

        for i, img in enumerate(images):
            start_line = i * lines_per_scene
            end_line = start_line + lines_per_scene if i < num_images - 1 else len(subtitle_lines)
            scene_lines = subtitle_lines[start_line:end_line]

            eff = "zoom_center"
            if effects and i < len(effects):
                eff = effects[i]
            else:
                # 자동 효과 순환
                auto_effects = ["zoom_center", "zoom_top", "pan_left", "zoom_out", "pan_right"]
                eff = auto_effects[i % len(auto_effects)]

            scenes.append(ShortsScene(
                image_path=img,
                narration="",
                duration=per_image,
                subtitle_lines=scene_lines,
                effect=eff
            ))

        # 6. ASS 자막 파일 생성
        ass_path = str(SHORTS_DIR / f"{output_name.replace('.mp4', '')}.ass")
        ShortsMaker.generate_ass_subtitle(scenes, ass_path)

        # 7. 씬별 Ken Burns 클립 생성
        clip_paths = []
        for i, scene in enumerate(scenes):
            clip_path = str(SHORTS_DIR / f"clip_{i:02d}.mp4")
            success = await ShortsMaker.create_scene_clip(
                image_path=scene.image_path,
                duration=scene.duration,
                effect=scene.effect,
                output_path=clip_path
            )
            if success:
                clip_paths.append(clip_path)
            else:
                return {"success": False, "error": f"씬 {i} 클립 생성 실패"}

        # 8. 최종 조립
        output_path = str(SHORTS_DIR / output_name)
        result = await ShortsMaker.assemble_shorts(
            scene_clips=clip_paths,
            audio_path=audio_path,
            subtitle_path=ass_path,
            output_path=output_path,
        )

        # 9. 임시 클립 정리
        for clip in clip_paths:
            try:
                os.remove(clip)
            except Exception:
                pass

        return result
