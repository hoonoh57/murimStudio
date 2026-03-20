"""
AI 비디오 클립 생성 서비스 – 정적 이미지 → 3~5초 동영상
v1.8.1  2026-03-20

API 우선순위:
  1. Pollinations.ai (wan / ltx-2 / seedance) — 유료, pollen 필요
  2. FFmpeg Ken Burns 확장 (무료 로컬, 항상 동작)

※ Pollinations 비디오 모델은 2026-03 현재 모두 유료입니다.
  무료 티어(Spore)는 pollen 부족으로 402 에러 발생합니다.
  API 실패 시 자동으로 Ken Burns 폴백합니다.
"""

import asyncio
import hashlib
import logging
import os
import random
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote
import base64

import httpx

logger = logging.getLogger(__name__)

# ── 설정 ────────────────────────────────────────────
CLIP_DIR = Path("output/clips")
CLIP_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("POLLINATIONS_API_KEY", "")

# Pollinations.ai 비디오 엔드포인트
VIDEO_BASE_URL = "https://gen.pollinations.ai/video"

# 모델 설정
VIDEO_MODELS = {
    "grok-imagine": {
        "name": "Grok Imagine Video (xAI)",
        "cost_per_sec": 0.05,
        "max_duration": 15,
        "desc": "xAI 최상위 비디오 모델, 이미지→비디오+오디오, 720p",
        "free": False,
    },
    "wan": {
        "name": "Wan (Alibaba)",
        "cost_per_sec": 0.05,
        "max_duration": 10,
        "supports_image": True,
        "desc": "고품질 이미지→영상, 오디오 포함",
    },
    "ltx-2": {
        "name": "LTX-2 (Lightricks)",
        "cost_per_sec": 0.01,
        "max_duration": 10,
        "supports_image": True,
        "desc": "빠른 생성, 오디오 포함",
    },
    "seedance": {
        "name": "Seedance (ByteDance)",
        "cost_per_sec": 0.024,
        "max_duration": 10,
        "supports_image": True,
        "desc": "고품질 모션",
    },
    "veo": {
        "name": "Veo (Google)",
        "cost_per_sec": 0.08,
        "max_duration": 8,
        "supports_image": False,
        "desc": "텍스트→영상 전용",
    },
    "ken-burns": {
        "name": "Ken Burns (로컬 무료)",
        "cost_per_sec": 0.0,
        "max_duration": 60,
        "supports_image": True,
        "desc": "FFmpeg 로컬, 항상 동작, 무료",
    },
}

# 모델 폴백 순서
MODEL_FALLBACK_ORDER = ["grok-imagine", "wan", "ltx-2", "seedance", "ken-burns"]


# 요청 설정
REQUEST_TIMEOUT = 120
RETRY_COUNT = 1  # 402는 재시도해도 소용없으므로 1회
RETRY_DELAY = 5
RATE_LIMIT_DELAY = 3

# 모션 프롬프트 프리셋
MOTION_PRESETS = {
    "wuxia": [
        "cinematic slow zoom in, wind blowing through hair and robes, floating dust particles",
        "dramatic camera pan across ancient Chinese landscape, morning mist rising",
        "slow dolly forward, sword gleaming in moonlight, fabric rippling in wind",
        "parallax movement through bamboo forest, light rays shifting",
        "slow orbit around martial arts fighter, energy aura pulsing gently",
    ],
    "anime": [
        "gentle zoom in, sparkle effects, colorful light bloom",
        "slow pan right, cherry blossoms falling, soft wind movement",
        "camera slowly pulling back, dramatic reveal, lens flare",
        "subtle parallax, character hair moving slightly, atmosphere particles",
        "dolly forward into dramatic scene, speed lines fading in",
    ],
    "fantasy": [
        "slow zoom in, magical particles floating, ethereal glow pulsing",
        "dramatic camera rise revealing epic landscape, clouds moving",
        "orbit around mystical object, energy crackling, ambient light shifts",
        "dolly through enchanted forest, fireflies dancing, fog rolling",
        "parallax reveal of castle, storm clouds gathering, lightning flicker",
    ],
    "horror": [
        "very slow zoom in, shadows shifting, darkness encroaching",
        "subtle camera shake, flickering light, dust particles in beam",
        "slow push toward door, ambient shadows growing, tension building",
        "dolly backward revealing dark corridor, lights dimming",
        "slow orbit, fog thickening, something moving in background",
    ],
    "default": [
        "smooth slow zoom in, cinematic lighting, subtle atmosphere movement",
        "gentle camera pan left to right, soft focus transition",
        "slow dolly forward, depth of field shift, ambient particles",
        "subtle parallax movement, natural lighting change, soft wind effect",
        "slow pull back revealing wider scene, gentle camera movement",
    ],
}


class VideoClipService:
    """정적 이미지 → AI 동영상 클립 생성 서비스"""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()
        self._clip_cache: dict[str, str] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": "MurimStudio/1.8"}
            if API_KEY:
                headers["Authorization"] = f"Bearer {API_KEY}"
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
                follow_redirects=True,
                headers=headers,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def build_motion_prompt(
        base_prompt: str,
        genre: str = "default",
        scene_index: int = 0,
    ) -> str:
        """이미지 프롬프트 + 장르 모션 → 비디오 프롬프트 생성"""
        preset = MOTION_PRESETS.get(genre, MOTION_PRESETS.get("default", {}))

        # preset이 list인 경우 (["slow zoom in", "pan left", ...])
        if isinstance(preset, list):
            motions = preset
            style_suffix = ""
        # preset이 dict인 경우 ({"motions": [...], "style": "..."})
        elif isinstance(preset, dict):
            motions = preset.get("motions", ["slow zoom in"])
            style_suffix = preset.get("style", "")
        else:
            motions = ["slow zoom in"]
            style_suffix = ""

        motion = motions[scene_index % len(motions)] if motions else "slow zoom in"
        video_prompt = f"{base_prompt}, {motion}, cinematic, smooth motion"

        if style_suffix:
            video_prompt += f", {style_suffix}"

        return video_prompt

    # ── 핵심: 단일 클립 생성 ──────────────────────────

    async def generate_clip(
        self,
        *,
        image_path: Optional[str] = None,
        prompt: str = "",
        script_id: int | str = 0,
        scene_id: str = "clip",
        genre: str = "default",
        fmt: str = "shorts",
        duration: int = 4,
        model: Optional[str] = None,
        overwrite: bool = False,
    ) -> dict:
        """이미지 → AI 동영상 클립 생성. 실패 시 항상 Ken Burns 폴백."""

        # 출력 경로
        output_dir = CLIP_DIR / f"script_{script_id}" if script_id else CLIP_DIR
        output_dir.mkdir(parents=True, exist_ok=True)

        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        filename = f"{scene_id}_{prompt_hash}.mp4"
        filepath = output_dir / filename

        if script_id:
            web_url = f"/output/clips/script_{script_id}/{filename}"
        else:
            web_url = f"/output/clips/{filename}"

        # 캐시 확인
        cache_key = f"s{script_id}:{scene_id}:{prompt_hash}"
        if not overwrite:
            if cache_key in self._clip_cache and Path(self._clip_cache[cache_key]).exists():
                return {
                    "success": True, "path": self._clip_cache[cache_key],
                    "url": web_url, "model": "cache", "cost": 0.0,
                    "elapsed": 0.0, "cached": True,
                }
            if filepath.exists() and filepath.stat().st_size > 50_000:
                self._clip_cache[cache_key] = str(filepath)
                return {
                    "success": True, "path": str(filepath),
                    "url": web_url, "model": "disk-cache", "cost": 0.0,
                    "elapsed": 0.0, "cached": True,
                }

        if overwrite and filepath.exists():
            filepath.unlink()
            self._clip_cache.pop(cache_key, None)

        aspect_ratio = "9:16" if fmt == "shorts" else "16:9"
        start = time.time()

        # ── Ken Burns 직접 지정 시 바로 실행 ──
        if model == "ken-burns":
            if image_path and Path(image_path).exists():
                success = await self._ken_burns_clip(
                    image_path, duration, fmt, filepath
                )
                if success:
                    elapsed = time.time() - start
                    self._clip_cache[cache_key] = str(filepath)
                    return {
                        "success": True, "path": str(filepath),
                        "url": web_url, "model": "ken-burns",
                        "duration": duration, "cost": 0.0,
                        "elapsed": elapsed, "cached": False,
                    }
            return {
                "success": False, "path": "", "url": "",
                "model": "ken-burns", "error": "이미지 없음",
                "elapsed": time.time() - start, "cached": False,
            }

        # ── API 모델 시도 ──
        if model and model != "ken-burns":
            models_to_try = [model]
        else:
            models_to_try = [m for m in MODEL_FALLBACK_ORDER if m != "ken-burns"]

        last_error = ""
        for model_name in models_to_try:
            model_info = VIDEO_MODELS.get(model_name, {})
            max_dur = model_info.get("max_duration", 10)
            clip_duration = min(duration, max_dur)

            # Grok Imagine은 별도 메서드
            if model_name == "grok-imagine":
                grok_ok = await self._try_grok_imagine(
                    image_path=image_path or "",
                    prompt=prompt,
                    duration=clip_duration,
                    aspect_ratio=aspect_ratio,
                    filepath=filepath,
                )
                if grok_ok:
                    elapsed = time.time() - start
                    cost = clip_duration * 0.05
                    logger.info(f"✅ 클립 생성: {scene_id} | grok-imagine | {clip_duration}s | ${cost:.3f} | {elapsed:.1f}s")
                    self._clip_cache[cache_key] = str(filepath)
                    return {
                        "success": True, "path": str(filepath),
                        "url": web_url, "model": "grok-imagine-video",
                        "duration": clip_duration, "cost": cost,
                        "elapsed": elapsed, "cached": False,
                    }
                last_error = "grok-imagine: 실패"
                logger.warning("⚠️ grok-imagine 실패 → 다음 모델")
                continue

            result = await self._try_api(
                model=model_name,
                prompt=prompt,
                duration=clip_duration,
                aspect_ratio=aspect_ratio,
                filepath=filepath,
            )

            if result["success"]:

                elapsed = time.time() - start
                cost = model_info.get("cost_per_sec", 0) * clip_duration
                logger.info(
                    f"✅ 클립 생성: {scene_id} | {model_name} | "
                    f"{clip_duration}s | ${cost:.3f} | {elapsed:.1f}s"
                )
                self._clip_cache[cache_key] = str(filepath)
                return {
                    "success": True, "path": str(filepath),
                    "url": web_url, "model": model_name,
                    "duration": clip_duration, "cost": cost,
                    "elapsed": elapsed, "cached": False,
                }

            last_error = result.get("error", "unknown")
            is_payment = "402" in last_error or "PAYMENT" in last_error.upper()
            logger.warning(
                f"⚠️ {model_name} 실패: {last_error}"
                + (" (결제 필요 → 즉시 다음)" if is_payment else "")
            )

        # ── 모든 API 실패 → Ken Burns 폴백 (항상 실행) ──
        logger.info(f"🔄 API 전부 실패 → Ken Burns 폴백: {scene_id}")
        if image_path and Path(image_path).exists():
            success = await self._ken_burns_clip(
                image_path, duration, fmt, filepath
            )
            if success:
                elapsed = time.time() - start
                self._clip_cache[cache_key] = str(filepath)
                return {
                    "success": True, "path": str(filepath),
                    "url": web_url, "model": "ken-burns-fallback",
                    "duration": duration, "cost": 0.0,
                    "elapsed": elapsed, "cached": False,
                }

        elapsed = time.time() - start
        logger.error(f"❌ 클립 생성 최종 실패: {scene_id}")
        return {
            "success": False, "path": "", "url": "",
            "model": "none", "error": last_error,
            "elapsed": elapsed, "cached": False,
        }

    # ── Grok Imagine API 호출 ─────────────────────────
    async def _try_grok_imagine(
        self,
        image_path: str,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        filepath: Path,
    ) -> bool:
        """Grok Imagine Video API — 이미지→비디오 (완전 비동기)"""
        api_key = os.getenv("XAI_API_KEY", "")
        if not api_key:
            logger.warning("⚠️ XAI_API_KEY 미설정 → Grok Imagine 건너뜀")
            return False

        try:
            # 이미지 base64 변환
            img_path = Path(image_path)
            if not img_path.exists():
                logger.error(f"❌ 이미지 없음: {image_path}")
                return False

            suffix = img_path.suffix.lower()
            mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
            img_bytes = img_path.read_bytes()
            img_b64 = base64.b64encode(img_bytes).decode()
            image_url = f"data:{mime};base64,{img_b64}"

            # httpx 비동기 클라이언트 사용
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                # Step 1: 생성 요청
                logger.info(f"🎬 Grok Imagine 요청: duration={duration}s, aspect={aspect_ratio}")
                resp = await client.post(
                    "https://api.x.ai/v1/videos/generations",
                    headers=headers,
                    json={
                        "model": "grok-imagine-video",
                        "prompt": prompt,
                        "image_url": image_url,
                        "duration": duration,
                        "aspect_ratio": aspect_ratio,
                        "resolution": "480p",
                    },
                )

                if resp.status_code == 429:
                    logger.warning("⚠️ Grok Imagine 429: 크레딧 소진 또는 rate limit")
                    return False
                if resp.status_code != 200:
                    logger.warning(f"⚠️ Grok Imagine {resp.status_code}: {resp.text[:200]}")
                    return False

                data = resp.json()
                request_id = data.get("request_id")
                if not request_id:
                    logger.error("❌ Grok Imagine: request_id 없음")
                    return False

            # Step 2: 폴링 (비동기, 최대 5분)
            max_wait = 300
            poll_interval = 5
            elapsed = 0

            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as poll_client:
                while elapsed < max_wait:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

                    try:
                        poll_resp = await poll_client.get(
                            f"https://api.x.ai/v1/videos/{request_id}",
                            headers={"Authorization": f"Bearer {api_key}"},
                        )
                    except httpx.HTTPError as e:
                        logger.warning(f"⚠️ 폴링 에러: {e}")
                        continue

                    if poll_resp.status_code not in (200, 202):
                        logger.warning(f"⚠️ 폴링 HTTP {poll_resp.status_code}")
                        continue

                    poll_data = poll_resp.json()
                    status = poll_data.get("status", "")

                    if status == "done":
                        video_url = ""
                        vid_obj = poll_data.get("video", {})
                        if isinstance(vid_obj, dict):
                            video_url = vid_obj.get("url", "")
                        if not video_url:
                            video_url = poll_data.get("url", "")

                        if not video_url:
                            logger.error(f"❌ Grok Imagine: 비디오 URL 없음. 응답: {str(poll_data)[:300]}")
                            return False

                        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as dl_client:
                            vid_resp = await dl_client.get(video_url)

                        if vid_resp.status_code == 200 and len(vid_resp.content) > 10000:
                            filepath.parent.mkdir(parents=True, exist_ok=True)
                            filepath.write_bytes(vid_resp.content)
                            logger.info(
                                f"✅ Grok Imagine 성공: {filepath.name} "
                                f"({len(vid_resp.content) / 1024:.0f}KB, {elapsed}s 소요)"
                            )
                            return True
                        else:
                            logger.error(f"❌ 비디오 다운로드 실패: {vid_resp.status_code}, size={len(vid_resp.content)}")
                            return False

                    elif status == "failed":
                        logger.error(f"❌ Grok Imagine 생성 실패: {poll_data}")
                        return False
                    elif status == "expired":
                        logger.error("❌ Grok Imagine 요청 만료")
                        return False
                    else:
                        if elapsed % 15 == 0:
                            logger.info(f"⏳ Grok Imagine 생성 중... ({elapsed}s, status={status})")

            logger.error(f"❌ Grok Imagine 타임아웃 ({max_wait}s)")
            return False

        except Exception as e:
            logger.error(f"❌ Grok Imagine 예외: {e}")
            return False

    async def _try_api(
        self,
        *,
        model: str,
        prompt: str,
        duration: int,
        aspect_ratio: str,
        filepath: Path,
    ) -> dict:
        """단일 모델로 비디오 생성 시도"""
        async with self._lock:
            elapsed_since = time.time() - self._last_request_time
            if elapsed_since < RATE_LIMIT_DELAY:
                await asyncio.sleep(RATE_LIMIT_DELAY - elapsed_since)

            client = await self._get_client()

            encoded_prompt = quote(prompt[:500])
            params = {
                "model": model,
                "duration": str(duration),
                "aspectRatio": aspect_ratio,
                "nologo": "true",
            }
            if API_KEY:
                params["key"] = API_KEY

            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{VIDEO_BASE_URL}/{encoded_prompt}?{param_str}"

            for attempt in range(1, RETRY_COUNT + 1):
                try:
                    logger.info(f"🎬 [{model}] 시도 {attempt}/{RETRY_COUNT}")
                    resp = await client.get(url)
                    self._last_request_time = time.time()

                    if resp.status_code == 402:
                        # 결제 필요 — 재시도 불필요, 즉시 실패
                        body = resp.text[:200]
                        return {"success": False, "error": f"402 PAYMENT_REQUIRED ({model})"}

                    if resp.status_code == 200 and len(resp.content) > 50_000:
                        content_type = resp.headers.get("content-type", "")
                        if "video" in content_type or resp.content[:4] in (
                            b'\x00\x00\x00\x1c', b'\x00\x00\x00\x18',
                            b'\x00\x00\x00\x20', b'\x1a\x45\xdf\xa3',
                        ):
                            filepath.write_bytes(resp.content)
                            logger.info(f"✅ [{model}] 저장: {filepath}")
                            return {"success": True}
                        else:
                            body = resp.content[:200].decode("utf-8", errors="replace")
                            logger.warning(f"⚠️ [{model}] 비디오 아닌 응답: {body}")

                    elif resp.status_code in (429, 503):
                        logger.warning(f"⚠️ [{model}] {resp.status_code}")
                        await asyncio.sleep(10)
                    else:
                        body = resp.text[:200]
                        logger.warning(f"⚠️ [{model}] status={resp.status_code}, body={body}")

                except httpx.TimeoutException:
                    logger.warning(f"⏰ [{model}] 타임아웃")
                except httpx.HTTPError as e:
                    logger.warning(f"❌ [{model}] HTTP 에러: {e}")

                if attempt < RETRY_COUNT:
                    await asyncio.sleep(RETRY_DELAY)

        return {"success": False, "error": f"{model}: 실패"}

    # ── Ken Burns 로컬 클립 (항상 동작) ───────────────

    @staticmethod
    async def _ken_burns_clip(
        image_path: str,
        duration: float,
        fmt: str,
        filepath: Path,
    ) -> bool:
        """FFmpeg Ken Burns — 10종 효과 중 랜덤, 항상 무료 동작"""
        if fmt == "shorts":
            w, h = 1080, 1920
        else:
            w, h = 1920, 1080

        fps = 30
        frames = max(int(duration * fps), fps)
        fade_out = max(duration - 0.3, 0.1)

        effects = [
            f"zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='if(eq(on,1),1.3,max(zoom-0.0015,1))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='1.2':x='if(eq(on,1),0,min(x+2,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='0':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='1.15':x='iw/2-(iw/zoom/2)':y='if(eq(on,1),ih-ih/zoom,max(y-1.5,0))':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='min(zoom+0.001,1.25)':x='if(eq(on,1),0,min(x+1,iw-iw/zoom))':y='if(eq(on,1),0,min(y+0.5,ih-ih/zoom))':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='if(eq(on,1),1.5,max(zoom-0.002,1))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih-ih/zoom':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='1.15':x='iw/2-(iw/zoom/2)':y='if(eq(on,1),0,min(y+1.5,ih-ih/zoom))':d={frames}:s={w}x{h}:fps={fps}",
            f"zoompan=z='1.2':x='if(eq(on,1),iw-iw/zoom,max(x-2,0))':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
        ]
        zoompan = random.choice(effects)

        filter_complex = (
            f"[0:v]"
            f"scale=w='if(gt(iw/ih,{w}/{h}),{w}*4,-2)':h='if(gt(iw/ih,{w}/{h}),-2,{h}*4)',"
            f"pad=w='max(iw,{w}*4)':h='max(ih,{h}*4)':x='(ow-iw)/2':y='(oh-ih)/2':color=black,"
            f"setsar=1:1,"
            f"{zoompan},"
            f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out}:d=0.3"
            f"[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", str(duration + 1),
            "-i", image_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-t", str(duration),
            str(filepath),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info(f"✅ Ken Burns 클립: {filepath} ({duration:.1f}s)")
                return True
            else:
                logger.error(f"❌ Ken Burns 실패: {stderr.decode()[-300:]}")

                # 최종 폴백: 단순 스케일+크롭
                return await VideoClipService._simple_clip(
                    image_path, duration, w, h, fps, filepath
                )
        except Exception as e:
            logger.error(f"❌ Ken Burns 에러: {e}")
            return False

    @staticmethod
    async def _simple_clip(
        image_path: str, duration: float,
        w: int, h: int, fps: int, filepath: Path,
    ) -> bool:
        """최최종 폴백 — 단순 스케일+크롭 정적 클립"""
        fade_out = max(duration - 0.3, 0.1)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", str(duration + 1),
            "-i", image_path,
            "-vf", (
                f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},"
                f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out}:d=0.3"
            ),
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-t", str(duration),
            str(filepath),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info(f"✅ 단순 클립 폴백: {filepath}")
                return True
            logger.error(f"❌ 단순 클립도 실패: {stderr.decode()[-200:]}")
            return False
        except Exception as e:
            logger.error(f"❌ 단순 클립 에러: {e}")
            return False

    # ── 배치 생성 ───────────────────────────────────────────
    async def generate_clips_for_script(
        self,
        script_id: str,
        image_paths: list[str],
        duration: float = 4.0,
        genre: str = "default",
        image_prompts: list[str] | None = None,
        model: str = "wan",
        overwrite: bool = False,
        max_concurrent: int = 1,
    ) -> dict:
        """스크립트 전체 이미지에 대해 AI 비디오 클립 배치 생성"""
        sem = asyncio.Semaphore(max_concurrent)
        results: list[dict] = []
        total_cost = 0.0
        success_count = 0
        cache_count = 0
        fail_count = 0

        async def _gen(idx: int, img_path: str):
            nonlocal total_cost, success_count, cache_count, fail_count
            async with sem:
                prompt_hint = ""
                if image_prompts and idx < len(image_prompts):
                    prompt_hint = image_prompts[idx]

                result = await self.generate_clip(
                    image_path=img_path,
                    scene_id=f"scene_{idx + 1:03d}",
                    prompt=prompt_hint,
                    duration=duration,
                    genre=genre,
                    model=model,
                    script_id=script_id,
                    overwrite=overwrite,
                )
                results.append(result)

                if result.get("cached"):
                    cache_count += 1
                    success_count += 1
                elif result.get("success"):
                    success_count += 1
                    total_cost += result.get("cost", 0.0)
                else:
                    fail_count += 1

        tasks = [_gen(i, p) for i, p in enumerate(image_paths)]
        await asyncio.gather(*tasks)

        # 순서 정렬 (scene_001, scene_002, ...)
        results.sort(key=lambda r: r.get("scene_id", ""))

        summary = {
            "script_id": script_id,
            "total": len(image_paths),
            "success": success_count,
            "cached": cache_count,
            "failed": fail_count,
            "total_cost": round(total_cost, 4),
            "clips": results,
        }

        logger.info(
            f"📊 배치 완료: {script_id} | "
            f"성공 {success_count}/{len(image_paths)} | "
            f"캐시 {cache_count} | 실패 {fail_count} | "
            f"비용 ${total_cost:.4f}"
        )
        return summary

    # ── 유틸리티 ──────────────────────────────────────────
    def get_clips_for_script(self, script_id: str) -> list[Path]:
        """특정 스크립트의 생성된 클립 목록 반환"""
        script_dir = CLIP_DIR / f"script_{script_id}"
        if not script_dir.exists():
            return []
        clips = sorted(script_dir.glob("*.mp4"))
        return clips

    def clear_cache(self, script_id: str | None = None):
        """캐시 클리어 — script_id 지정 시 해당 폴더만, 없으면 전체"""
        import shutil
        if script_id:
            target = CLIP_DIR / f"script_{script_id}"
            if target.exists():
                shutil.rmtree(target)
                logger.info(f"🗑️ 캐시 삭제: {target}")
        else:
            if CLIP_DIR.exists():
                shutil.rmtree(CLIP_DIR)
                CLIP_DIR.mkdir(parents=True, exist_ok=True)
                logger.info("🗑️ 전체 클립 캐시 삭제")


    @staticmethod
    def get_model_list() -> list[dict]:
        """UI 드롭다운용 모델 목록 반환"""
        models = []
        for key, info in VIDEO_MODELS.items():
            models.append({
                "key": key,
                "name": info["name"],
                "cost": info.get("cost_per_sec", 0),
                "max_duration": info.get("max_duration", 10),
                "desc": info.get("desc", ""),
                "free": info.get("free", False),
            })
        return models
