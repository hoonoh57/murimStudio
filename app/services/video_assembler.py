"""
영상 자동 조립 서비스 – FFmpeg
이미지 + TTS 오디오 → MP4 영상 생성
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("output/video")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TEMP_DIR = Path("output/temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


class VideoAssembler:
    """이미지 + 오디오 → MP4 영상 조립"""

    @staticmethod
    def get_audio_duration(audio_path: str) -> float:
        """FFprobe로 오디오 길이(초) 측정"""
        if not Path(audio_path).exists() or Path(audio_path).stat().st_size < 100:
            return 0.0
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    audio_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0))
        except Exception as e:
            logger.warning(f"오디오 길이 측정 실패: {e}")
            return 0.0


    @staticmethod
    def get_image_count(image_dir: str = "static/images", prefix: str = "scene_") -> list[str]:
        """scene_XX 이미지 파일 목록 (정렬)"""
        p = Path(image_dir)
        files = sorted(
            [str(f) for f in p.glob(f"{prefix}*.jpg")]
            + [str(f) for f in p.glob(f"{prefix}*.png")]
        )
        return files

    async def assemble(
        self,
        *,
        audio_path: str,
        image_paths: list[str] | None = None,
        output_name: str = "final_video.mp4",
        transition: str = "fade",
        fade_duration: float = 0.5,
        resolution: str = "1920:1080",
        fps: int = 30,
    ) -> dict:
        """
        이미지 + 오디오 → MP4 조립

        Args:
            audio_path: TTS MP3 파일 경로
            image_paths: 이미지 파일 경로 목록 (None이면 자동 탐색)
            output_name: 출력 파일명
            transition: 전환 효과 (fade, none)
            fade_duration: 페이드 시간(초)
            resolution: 출력 해상도
            fps: 프레임레이트

        Returns:
            {"success": bool, "path": str, "duration": float, "file_size": int}
        """
        # 오디오 확인
        if not Path(audio_path).exists():
            return {"success": False, "error": "오디오 파일을 찾을 수 없습니다.", "path": ""}

        # 이미지 목록
        if not image_paths:
            image_paths = self.get_image_count()
        if not image_paths:
            return {"success": False, "error": "이미지 파일을 찾을 수 없습니다.", "path": ""}

        # 유효한 이미지만 필터링
        valid_images = [p for p in image_paths if Path(p).exists() and Path(p).stat().st_size > 1000]
        if not valid_images:
            return {"success": False, "error": "유효한 이미지 파일이 없습니다.", "path": ""}

        # 오디오 길이 측정
        total_duration = self.get_audio_duration(audio_path)
        if total_duration <= 0:
            return {"success": False, "error": "오디오 길이를 측정할 수 없습니다.", "path": ""}

        # 이미지당 표시 시간 계산
        num_images = len(valid_images)
        duration_per_image = total_duration / num_images

        logger.info(
            f"🎬 영상 조립 시작: {num_images}장 이미지, "
            f"오디오 {total_duration:.1f}초, "
            f"이미지당 {duration_per_image:.1f}초"
        )

        output_path = OUTPUT_DIR / output_name

        try:
            if transition == "fade" and num_images > 1:
                result = await self._assemble_with_fade(
                    valid_images, audio_path, str(output_path),
                    duration_per_image, fade_duration, resolution, fps,
                )
            else:
                result = await self._assemble_simple(
                    valid_images, audio_path, str(output_path),
                    duration_per_image, resolution, fps,
                )

            if result and output_path.exists():
                file_size = output_path.stat().st_size
                logger.info(
                    f"✅ 영상 생성 완료: {output_path} "
                    f"({file_size / 1024 / 1024:.1f}MB, {total_duration:.1f}초)"
                )
                return {
                    "success": True,
                    "path": str(output_path),
                    "url": f"/output/video/{output_name}",
                    "duration": total_duration,
                    "file_size": file_size,
                    "num_images": num_images,
                    "duration_per_image": round(duration_per_image, 1),
                }
            else:
                return {"success": False, "error": "FFmpeg 실행 실패", "path": ""}

        except Exception as e:
            logger.exception("영상 조립 오류")
            return {"success": False, "error": str(e), "path": ""}

    async def _assemble_simple(
        self,
        images: list[str],
        audio: str,
        output: str,
        duration_per: float,
        resolution: str,
        fps: int,
    ) -> bool:
        """단순 슬라이드쇼 (전환 효과 없음)"""
        # concat 파일 생성
        concat_file = TEMP_DIR / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for img in images:
                abs_path = str(Path(img).resolve()).replace("\\", "/")
                f.write(f"file '{abs_path}'\n")
                f.write(f"duration {duration_per:.2f}\n")
            # 마지막 이미지 한 번 더 (FFmpeg concat 요구사항)
            abs_path = str(Path(images[-1]).resolve()).replace("\\", "/")
            f.write(f"file '{abs_path}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-i", audio,
            "-vf", f"scale={resolution}:force_original_aspect_ratio=decrease,"
                   f"pad={resolution}:(ow-iw)/2:(oh-ih)/2:black,"
                   f"setsar=1",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-shortest",
            "-movflags", "+faststart",
            output,
        ]

        return await self._run_ffmpeg(cmd)

    async def _assemble_with_fade(
        self,
        images: list[str],
        audio: str,
        output: str,
        duration_per: float,
        fade_dur: float,
        resolution: str,
        fps: int,
    ) -> bool:
        """페이드 전환 효과 포함 슬라이드쇼"""
        width, height = resolution.split(":")
        num = len(images)

        # 1단계: 각 이미지를 개별 영상 클립으로 변환
        clip_paths = []
        for i, img in enumerate(images):
            clip_path = TEMP_DIR / f"clip_{i:03d}.mp4"
            clip_paths.append(str(clip_path))

            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", img,
                "-t", f"{duration_per:.2f}",
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                       f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
                       f"setsar=1,"
                       f"fade=t=in:st=0:d={fade_dur},"
                       f"fade=t=out:st={max(0, duration_per - fade_dur):.2f}:d={fade_dur}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
                clip_path,
            ]

            success = await self._run_ffmpeg(cmd)
            if not success:
                logger.error(f"클립 {i} 생성 실패")
                return False

            logger.info(f"  클립 {i+1}/{num} 생성 완료")

        # 2단계: 클립 병합
        merge_list = TEMP_DIR / "merge_list.txt"
        with open(merge_list, "w", encoding="utf-8") as f:
            for cp in clip_paths:
                abs_path = str(Path(cp).resolve()).replace("\\", "/")
                f.write(f"file '{abs_path}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(merge_list),
            "-i", audio,
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-movflags", "+faststart",
            output,
        ]

        success = await self._run_ffmpeg(cmd)

        # 임시 클립 정리
        for cp in clip_paths:
            try:
                Path(cp).unlink(missing_ok=True)
            except Exception:
                pass

        return success

    @staticmethod
    async def _run_ffmpeg(cmd: list[str]) -> bool:
        """FFmpeg 비동기 실행"""
        logger.info(f"FFmpeg: {' '.join(cmd[:6])}...")
        try:
            process = await asyncio.create_subprocess_exec(
                *[str(c) for c in cmd],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=300
            )

            if process.returncode == 0:
                return True
            else:
                error_msg = stderr.decode("utf-8", errors="replace")[-500:]
                logger.error(f"FFmpeg 에러 (code={process.returncode}): {error_msg}")
                return False

        except asyncio.TimeoutError:
            logger.error("FFmpeg 타임아웃 (300초)")
            process.kill()
            return False
        except Exception as e:
            logger.error(f"FFmpeg 실행 오류: {e}")
            return False

    async def assemble_from_project(
        self,
        project_id: int,
        audio_path: str,
        transition: str = "fade",
    ) -> dict:
        """프로젝트 ID 기반으로 이미지 탐색 + 영상 조립"""
        images = self.get_image_count()
        if not images:
            return {"success": False, "error": "이미지가 없습니다.", "path": ""}

        return await self.assemble(
            audio_path=audio_path,
            image_paths=images,
            output_name=f"project_{project_id}.mp4",
            transition=transition,
        )
