"""
AI 비디오 클립 생성 서비스 – 정적 이미지 → 3~5초 동영상
v1.8.0  2026-03-20

API 우선순위:
  1. Pollinations.ai (wan / ltx-2 / seedance)
  2. 로컬 FFmpeg Ken Burns (폴백)

정적 이미지를 AI 동영상 클립으로 변환하여 YouTube AI-slop 판정 탈출.
"""

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# ── 설정 ────────────────────────────────────────────
CLIP_DIR = Path("output/clips")
CLIP_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("POLLINATIONS_API_KEY", "")

# Pollinations.ai 비디오 엔드포인트 (gen.pollinations.ai 통합 API)
VIDEO_BASE_URL = "https://gen.pollinations.ai/video"

# 모델 설정: (모델명, 초당 비용 $, 최대 길이 초, 비고)
VIDEO_MODELS = {
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
        "desc": "고품질 모션, 자연스러운 움직임",
    },
    "veo": {
        "name": "Veo (Google)",
        "cost_per_sec": 0.08,
        "max_duration": 8,
        "supports_image": False,
        "desc": "텍스트→영상 전용",
    },
}

# 모델 폴백 순서
MODEL_FALLBACK_ORDER = ["wan", "ltx-2", "seedance", "veo"]

# 요청 설정
REQUEST_TIMEOUT = 300  # 비디오 생성은 오래 걸림
RETRY_COUNT = 2
RETRY_DELAY = 10
RATE_LIMIT_DELAY = 8  # 모델 간 최소 대기

# 모션 프롬프트 프리셋 (장르별)
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
        if API_KEY:
            logger.info(f"✅ VideoClipService: Pollinations API 키 설정됨")
        else:
            logger.warning("⚠️ VideoClipService: POLLINATIONS_API_KEY 미설정 — 무료 티어 사용")

    # ── HTTP 클라이언트 ───────────────────────────────

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

    # ── 모션 프롬프트 생성 ────────────────────────────

    @staticmethod
    def build_motion_prompt(
        image_prompt: str,
        genre: str = "default",
        scene_index: int = 0,
    ) -> str:
        """이미지 프롬프트 + 장르별 모션 힌트 → 비디오 프롬프트"""
        presets = MOTION_PRESETS.get(genre, MOTION_PRESETS["default"])
        motion = presets[scene_index % len(presets)]
        # 이미지 프롬프트에서 핵심 키워드 추출 (첫 200자)
        scene_desc = image_prompt[:200].strip()
        return f"{scene_desc}, {motion}, high quality cinematic video, smooth motion"

    # ── 핵심: 단일 클립 생성 ──────────────────────────

    async def generate_clip(
        self,
        *,
        image_path: Optional[str] = None,
        prompt: str = "",
        script_id: int = 0,
        scene_id: str = "clip",
        genre: str = "default",
        fmt: str = "shorts",
        duration: int = 4,
        model: Optional[str] = None,
        overwrite: bool = False,
    ) -> dict:
        """
        이미지 → AI 동영상 클립 생성

        Parameters
        ----------
        image_path : str, optional
            입력 이미지 경로. None이면 텍스트→비디오.
        prompt : str
            비디오 생성 프롬프트
        script_id : int
            스크립트 ID (폴더 관리용)
        scene_id : str
            씬 식별자 (예: scene_00)
        genre : str
            장르 (wuxia, anime, fantasy 등) — 모션 프리셋 선택용
        fmt : str
            'shorts' (9:16) 또는 'long' (16:9)
        duration : int
            클립 길이 (초, 기본 4)
        model : str, optional
            특정 모델 지정. None이면 폴백 체인 사용.
        overwrite : bool
            기존 파일 덮어쓰기

        Returns
        -------
        dict : {"success": bool, "path": str, "url": str, "model": str, ...}
        """
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
                cached = self._clip_cache[cache_key]
                logger.info(f"⏩ 클립 캐시 사용: {cached}")
                return {
                    "success": True,
                    "path": cached,
                    "url": web_url,
                    "model": "cache",
                    "elapsed": 0.0,
                    "cached": True,
                }
            if filepath.exists() and filepath.stat().st_size > 50_000:
                logger.info(f"⏩ 클립 디스크 캐시: {filepath}")
                self._clip_cache[cache_key] = str(filepath)
                return {
                    "success": True,
                    "path": str(filepath),
                    "url": web_url,
                    "model": "disk-cache",
                    "elapsed": 0.0,
                    "cached": True,
                }

        if overwrite and filepath.exists():
            filepath.unlink()
            self._clip_cache.pop(cache_key, None)

        # aspect ratio
        aspect_ratio = "9:16" if fmt == "shorts" else "16:9"

        # 모델 목록 결정
        if model:
            models_to_try = [model]
        else:
            models_to_try = list(MODEL_FALLBACK_ORDER)
            # 이미지가 없으면 image 지원 모델에서 veo 같은 text-only로 폴백
            if not image_path:
                pass  # 모든 모델이 text→video 지원
            # 이미지가 있으면 supports_image가 True인 모델 우선
            else:
                models_to_try = [
                    m for m in models_to_try
                    if VIDEO_MODELS.get(m, {}).get("supports_image", False)
                ] + [
                    m for m in models_to_try
                    if not VIDEO_MODELS.get(m, {}).get("supports_image", False)
                ]

        # API 요청 (폴백 체인)
        start = time.time()
        last_error = ""

        for model_name in models_to_try:
            model_info = VIDEO_MODELS.get(model_name, {})
            max_dur = model_info.get("max_duration", 10)
            clip_duration = min(duration, max_dur)

            result = await self._try_generate(
                model=model_name,
                prompt=prompt,
                image_path=image_path,
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
                    "success": True,
                    "path": str(filepath),
                    "url": web_url,
                    "model": model_name,
                    "duration": clip_duration,
                    "cost": cost,
                    "elapsed": elapsed,
                    "cached": False,
                }
            else:
                last_error = result.get("error", "unknown")
                logger.warning(
                    f"⚠️ {model_name} 실패: {last_error} → 다음 모델 시도"
                )

        # 모든 API 실패 → Ken Burns 폴백
        if image_path and Path(image_path).exists():
            logger.info(f"🔄 API 전부 실패 → FFmpeg Ken Burns 폴백: {scene_id}")
            kb_result = await self._fallback_ken_burns(
                image_path=image_path,
                duration=duration,
                fmt=fmt,
                filepath=filepath,
            )
            if kb_result:
                elapsed = time.time() - start
                self._clip_cache[cache_key] = str(filepath)
                return {
                    "success": True,
                    "path": str(filepath),
                    "url": web_url,
                    "model": "ken-burns-fallback",
                    "duration": duration,
                    "cost": 0.0,
                    "elapsed": elapsed,
                    "cached": False,
                }

        elapsed = time.time() - start
        logger.error(f"❌ 클립 생성 최종 실패: {scene_id} | {last_error}")
        return {
            "success": False,
            "path": "",
            "url": "",
            "model": "none",
            "error": last_error,
            "elapsed": elapsed,
            "cached": False,
        }

    # ── Pollinations API 호출 ─────────────────────────

    async def _try_generate(
        self,
        *,
        model: str,
        prompt: str,
        image_path: Optional[str],
        duration: int,
        aspect_ratio: str,
        filepath: Path,
    ) -> dict:
        """단일 모델로 비디오 생성 시도"""
        async with self._lock:
            # Rate limit
            elapsed_since = time.time() - self._last_request_time
            if elapsed_since < RATE_LIMIT_DELAY:
                wait = RATE_LIMIT_DELAY - elapsed_since
                logger.info(f"⏳ Rate limit 대기: {wait:.1f}s")
                await asyncio.sleep(wait)

            client = await self._get_client()

            # URL 구성
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
                    logger.info(
                        f"🎬 [{model}] 클립 생성 시도 {attempt}/{RETRY_COUNT} | "
                        f"{duration}s | {aspect_ratio}"
                    )

                    resp = await client.get(url)
                    self._last_request_time = time.time()

                    if resp.status_code == 200:
                        content = resp.content
                        content_type = resp.headers.get("content-type", "")

                        # 비디오 응답인지 확인
                        if len(content) > 50_000 and (
                            "video" in content_type
                            or content[:4] in (
                                b'\x00\x00\x00\x1c',  # ftyp (MP4)
                                b'\x00\x00\x00\x18',
                                b'\x00\x00\x00\x20',
                                b'\x1a\x45\xdf\xa3',  # WebM
                            )
                        ):
                            filepath.write_bytes(content)
                            size_mb = len(content) / 1024 / 1024
                            logger.info(
                                f"✅ [{model}] 비디오 저장: {filepath} ({size_mb:.1f}MB)"
                            )
                            return {"success": True}
                        else:
                            # 텍스트 응답 (에러 또는 진행 상태)
                            body = content[:300].decode("utf-8", errors="replace")
                            logger.warning(
                                f"⚠️ [{model}] 비디오가 아닌 응답: "
                                f"type={content_type}, size={len(content)}, body={body}"
                            )
                    elif resp.status_code == 202:
                        # 비동기 생성 (처리 중) — polling 필요할 수 있음
                        logger.info(f"⏳ [{model}] 비동기 처리 중 (202)")
                        await asyncio.sleep(30)
                        # 재시도 (같은 URL로)
                        continue
                    elif resp.status_code in (429, 503):
                        logger.warning(
                            f"⚠️ [{model}] Rate limit / 서비스 불가 ({resp.status_code})"
                        )
                        await asyncio.sleep(15)
                    else:
                        body = resp.text[:200]
                        logger.warning(
                            f"⚠️ [{model}] status={resp.status_code}, body={body}"
                        )

                except httpx.TimeoutException:
                    logger.warning(f"⏰ [{model}] 타임아웃 (시도 {attempt})")
                except httpx.HTTPError as e:
                    logger.warning(f"❌ [{model}] HTTP 에러: {e} (시도 {attempt})")

                if attempt < RETRY_COUNT:
                    await asyncio.sleep(RETRY_DELAY)

        return {"success": False, "error": f"{model}: 모든 시도 실패"}

    # ── Ken Burns 폴백 ────────────────────────────────

    @staticmethod
    async def _fallback_ken_burns(
        image_path: str,
        duration: float,
        fmt: str,
        filepath: Path,
    ) -> bool:
        """API 실패 시 FFmpeg Ken Burns 효과로 클립 생성 (기존 ShortsMaker 로직 강화)"""
        if fmt == "shorts":
            w, h = 1080, 1920
        else:
            w, h = 1920, 1080

        fps = 30
        frames = max(int(duration * fps), fps)
        fade_out = max(duration - 0.3, 0.1)

        # 다양한 Ken Burns 효과 중 랜덤 선택
        import random
        effects = [
            # 중앙 줌인
            f"zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
            # 줌아웃
            f"zoompan=z='if(eq(on,1),1.3,max(zoom-0.0015,1))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
            # 좌→우 패닝
            f"zoompan=z='1.2':x='if(eq(on,1),0,min(x+2,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}",
            # 상단 줌인 (인물 얼굴)
            f"zoompan=z='min(zoom+0.0015,1.3)':x='iw/2-(iw/zoom/2)':y='0':d={frames}:s={w}x{h}:fps={fps}",
            # 하단→상단 패닝
            f"zoompan=z='1.15':x='iw/2-(iw/zoom/2)':y='if(eq(on,1),ih-ih/zoom,max(y-1.5,0))':d={frames}:s={w}x{h}:fps={fps}",
            # 대각선 줌인
            f"zoompan=z='min(zoom+0.001,1.25)':x='if(eq(on,1),0,min(x+1,iw-iw/zoom))':y='if(eq(on,1),0,min(y+0.5,ih-ih/zoom))':d={frames}:s={w}x{h}:fps={fps}",
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
            "-loop", "1",
            "-t", str(duration + 1),
            "-i", image_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
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
                logger.info(f"✅ Ken Burns 폴백 성공: {filepath}")
                return True
            else:
                logger.error(f"❌ Ken Burns 폴백 실패: {stderr.decode()[-300:]}")
                return False
        except Exception as e:
            logger.error(f"❌ Ken Burns 에러: {e}")
            return False

    # ── 배치 생성 (스크립트 전체) ──────────────────────

    async def generate_clips_for_script(
        self,
        *,
        script_id: int,
        image_paths: list[str],
        image_prompts: list[str],
        genre: str = "default",
        fmt: str = "shorts",
        duration: int = 4,
        model: Optional[str] = None,
        overwrite: bool = False,
        semaphore_limit: int = 1,
    ) -> list[dict]:
        """
        스크립트의 모든 이미지 → AI 비디오 클립 배치 생성

        Parameters
        ----------
        script_id : int
        image_paths : list[str]
            이미지 파일 경로 목록
        image_prompts : list[str]
            각 이미지의 원본 프롬프트 (모션 프롬프트 생성용)
        genre : str
        fmt : str
        duration : int
            각 클립 길이 (초)
        model : str, optional
        overwrite : bool
        semaphore_limit : int
            동시 요청 수 (기본 1 — API rate limit 때문)

        Returns
        -------
        list[dict] : 각 클립의 생성 결과
        """
        if not image_paths:
            logger.warning("⚠️ 이미지가 없습니다.")
            return []

        total = len(image_paths)
        logger.info(
            f"🎬 배치 클립 생성 시작: script_{script_id} | "
            f"{total}장 | {genre} | {fmt} | {duration}s/clip"
        )

        sem = asyncio.Semaphore(semaphore_limit)
        results = []

        for i, img_path in enumerate(image_paths):
            async with sem:
                # 프롬프트 결정
                if i < len(image_prompts) and image_prompts[i]:
                    motion_prompt = self.build_motion_prompt(
                        image_prompts[i], genre, i
                    )
                else:
                    motion_prompt = self.build_motion_prompt(
                        "cinematic scene", genre, i
                    )

                logger.info(f"🖼️ [{i+1}/{total}] scene_{i:02d} 클립 생성")

                result = await self.generate_clip(
                    image_path=img_path,
                    prompt=motion_prompt,
                    script_id=script_id,
                    scene_id=f"scene_{i:02d}",
                    genre=genre,
                    fmt=fmt,
                    duration=duration,
                    model=model,
                    overwrite=overwrite,
                )
                results.append(result)

        success = sum(1 for r in results if r["success"])
        cached = sum(1 for r in results if r.get("cached"))
        total_cost = sum(r.get("cost", 0) for r in results)
        logger.info(
            f"🎬 배치 완료: {success}/{total} 성공 | "
            f"캐시 {cached}건 | 총 비용 ${total_cost:.3f}"
        )
        return results

    # ── 유틸리티 ──────────────────────────────────────

    @staticmethod
    def get_clips_for_script(script_id: int) -> list[str]:
        """스크립트 ID에 해당하는 클립 파일 목록"""
        clip_dir = CLIP_DIR / f"script_{script_id}"
        if not clip_dir.exists():
            return []
        clips = sorted(
            list(clip_dir.glob("*.mp4")) + list(clip_dir.glob("*.webm"))
        )
        return [str(c) for c in clips]

    def clear_cache(self, script_id: Optional[int] = None) -> int:
        """캐시 클리어"""
        if script_id is not None:
            prefix = f"s{script_id}:"
            keys = [k for k in self._clip_cache if k.startswith(prefix)]
        else:
            keys = list(self._clip_cache.keys())

        for k in keys:
            del self._clip_cache[k]
        logger.info(f"🧹 클립 캐시 {len(keys)}건 제거")
        return len(keys)

    @staticmethod
    def get_model_list() -> list[dict]:
        """UI용 모델 목록"""
        return [
            {
                "key": k,
                "name": v["name"],
                "cost": v["cost_per_sec"],
                "max_duration": v["max_duration"],
                "desc": v["desc"],
            }
            for k, v in VIDEO_MODELS.items()
        ]
