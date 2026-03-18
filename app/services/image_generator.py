"""
이미지 생성 서비스 – Pollinations.ai (gen.pollinations.ai + API Key)
스크립트 ID별 폴더 관리
"""

import asyncio
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

BASE_IMAGE_DIR = Path("static/images")
BASE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
BASE_URL = "https://gen.pollinations.ai/image"
DEFAULT_MODEL = "flux"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
REQUEST_TIMEOUT = 120
RETRY_COUNT = 3
RETRY_DELAY = 5
RATE_LIMIT_DELAY = 6

STYLE_PREFIX = (
    "highly detailed digital painting, cinematic lighting, "
    "ancient Chinese martial arts, wuxia style, dramatic atmosphere, "
    "8k resolution, trending on artstation"
)

MAX_PROMPT_LENGTH = 800


class ImageGenerator:

    def __init__(self):
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        if API_KEY:
            logger.info(f"✅ Pollinations API 키 설정됨 ({API_KEY[:8]}...)")
        else:
            logger.warning("⚠️ POLLINATIONS_API_KEY 미설정")

    @staticmethod
    def get_script_dir(script_id: int) -> Path:
        """스크립트 ID별 이미지 폴더"""
        d = BASE_IMAGE_DIR / f"script_{script_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def list_script_folders() -> list[dict]:
        """모든 스크립트 이미지 폴더 목록"""
        results = []
        if not BASE_IMAGE_DIR.exists():
            return results
        for d in sorted(BASE_IMAGE_DIR.iterdir()):
            if d.is_dir() and d.name.startswith("script_"):
                images = sorted(
                    list(d.glob("*.jpg")) + list(d.glob("*.png"))
                )
                if images:
                    sid = d.name.replace("script_", "")
                    results.append({
                        "script_id": sid,
                        "folder": str(d),
                        "count": len(images),
                        "paths": [str(f) for f in images],
                    })
        return results

    @staticmethod
    def get_images_for_script(script_id: int) -> list[str]:
        """특정 스크립트의 이미지 경로 목록 (정렬)"""
        d = BASE_IMAGE_DIR / f"script_{script_id}"
        if not d.exists():
            return []
        files = sorted(
            list(d.glob("*.jpg")) + list(d.glob("*.png"))
        )
        return [str(f) for f in files]

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": "MurimStudio/1.4"}
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

    async def generate(
        self,
        prompt: str,
        *,
        script_id: int = 0,
        scene_id: str = "scene",
        model: str = DEFAULT_MODEL,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        seed: int | None = None,
        enhance: bool = True,
        add_style: bool = True,
    ) -> dict:
        prompt = prompt[:MAX_PROMPT_LENGTH].strip()
        full_prompt = f"{STYLE_PREFIX}, {prompt}" if add_style else prompt

        encoded = quote(full_prompt)
        params = {
            "model": model,
            "width": width,
            "height": height,
            "enhance": str(enhance).lower(),
            "nologo": "true",
        }
        if seed is not None:
            params["seed"] = seed
        if API_KEY:
            params["key"] = API_KEY

        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{BASE_URL}/{encoded}?{param_str}"

        if len(url) > 2048:
            short_prompt = prompt[:400].strip()
            full_prompt = f"{STYLE_PREFIX}, {short_prompt}" if add_style else short_prompt
            encoded = quote(full_prompt)
            url = f"{BASE_URL}/{encoded}?{param_str}"

        # 스크립트별 폴더에 저장
        output_dir = self.get_script_dir(script_id) if script_id else BASE_IMAGE_DIR
        prompt_hash = hashlib.md5(full_prompt.encode()).hexdigest()[:8]
        filename = f"{scene_id}_{prompt_hash}.jpg"
        filepath = output_dir / filename

        # 웹 접근 URL
        if script_id:
            web_url = f"/static/images/script_{script_id}/{filename}"
        else:
            web_url = f"/static/images/{filename}"

        if filepath.exists() and filepath.stat().st_size > 10_000:
            logger.info(f"⏩ 캐시 사용: {filepath}")
            return {
                "success": True,
                "path": str(filepath),
                "url": web_url,
                "prompt": prompt,
                "elapsed": 0.0,
                "cached": True,
            }

        async with self._lock:
            elapsed_since_last = time.time() - self._last_request_time
            if elapsed_since_last < RATE_LIMIT_DELAY:
                wait = RATE_LIMIT_DELAY - elapsed_since_last
                logger.info(f"⏳ Rate limit 대기: {wait:.1f}초")
                await asyncio.sleep(wait)

            start = time.time()
            client = await self._get_client()

            for attempt in range(1, RETRY_COUNT + 1):
                try:
                    logger.info(f"🎨 [{scene_id}] 생성 중 (시도 {attempt}/{RETRY_COUNT})")
                    resp = await client.get(url)
                    self._last_request_time = time.time()

                    if resp.status_code == 200 and len(resp.content) > 5_000:
                        filepath.write_bytes(resp.content)
                        elapsed = time.time() - start
                        size_kb = len(resp.content) / 1024
                        logger.info(f"✅ 저장: {filepath} ({size_kb:.0f}KB, {elapsed:.1f}초)")
                        return {
                            "success": True,
                            "path": str(filepath),
                            "url": web_url,
                            "prompt": prompt,
                            "elapsed": elapsed,
                            "cached": False,
                        }
                    else:
                        body = resp.text[:200]
                        logger.warning(f"⚠️ status={resp.status_code}, size={len(resp.content)}, body={body}")
                except httpx.TimeoutException:
                    logger.warning(f"⏰ 타임아웃 (시도 {attempt})")
                except httpx.HTTPError as e:
                    logger.warning(f"❌ HTTP 에러: {e} (시도 {attempt})")

                if attempt < RETRY_COUNT:
                    await asyncio.sleep(RETRY_DELAY)

            elapsed = time.time() - start
            logger.error(f"❌ 이미지 생성 실패: {scene_id}")
            return {"success": False, "path": "", "url": "", "prompt": prompt, "elapsed": elapsed, "cached": False}

    @staticmethod
    def extract_prompts(script_text: str) -> list[dict]:
        results = []

        pattern1 = re.compile(r'\[이미지\s*프롬프트\s*[:：]\s*(.+?)\]', re.DOTALL)
        pattern2 = re.compile(r'\[이미지\s*프롬프트\]\s*(.+?)(?=\s*\[|$)', re.DOTALL)
        pattern3 = re.compile(r'\[Image\s*Prompt\s*[:：]\s*(.+?)\]', re.DOTALL | re.IGNORECASE)

        matches = pattern1.findall(script_text)
        if not matches:
            matches = pattern2.findall(script_text)
        if not matches:
            matches = pattern3.findall(script_text)

        for i, raw in enumerate(matches):
            prompt = re.sub(r'--\w+\s+\S+', '', raw).strip()
            korean_cut = re.search(r'[가-힣]{3,}', prompt)
            if korean_cut:
                prompt = prompt[:korean_cut.start()].strip()
            prompt = re.sub(r'\s+', ' ', prompt).strip()
            prompt = prompt.rstrip('.],:;')
            if len(prompt) > 20:
                results.append({
                    "scene_id": f"scene_{i:02d}",
                    "prompt": prompt[:MAX_PROMPT_LENGTH],
                    "is_variant": False,
                })

        logger.info(f"📝 {len(results)}개 기본 프롬프트 추출")
        return results

    @staticmethod
    def expand_prompts(prompts: list[dict], target_count: int = 15) -> list[dict]:
        if not prompts or len(prompts) >= target_count:
            return prompts

        per_scene = max(2, target_count // len(prompts))
        remaining = target_count - len(prompts)

        VARIANTS = [
            "close-up shot, dramatic face expression, intense emotion",
            "wide angle panoramic view, establishing shot, epic scale",
            "low angle shot looking up, powerful and imposing, heroic pose",
            "over-the-shoulder perspective, depth of field, atmospheric",
            "bird's eye view, top-down perspective, environmental storytelling",
            "dutch angle, dynamic composition, tension and movement",
            "silhouette against dramatic sky, backlit, cinematic mood",
            "extreme close-up on hands or weapon, detail shot, texture focus",
        ]

        expanded = []
        variant_idx = 0

        for base in prompts:
            expanded.append(base)
            variants_for_this = min(per_scene - 1, remaining)
            for v in range(variants_for_this):
                variant_prompt = f"{base['prompt']}, {VARIANTS[variant_idx % len(VARIANTS)]}"
                expanded.append({
                    "scene_id": f"{base['scene_id']}_v{v+1}",
                    "prompt": variant_prompt[:MAX_PROMPT_LENGTH],
                    "is_variant": True,
                })
                variant_idx += 1
                remaining -= 1
                if remaining <= 0:
                    break
            if remaining <= 0:
                break

        logger.info(f"🔄 {len(prompts)}장 → {len(expanded)}장으로 확장")
        return expanded

    async def generate_all_from_script(
        self, script_text: str, *, script_id: int = 0,
        model: str = DEFAULT_MODEL, seed_base: int | None = None,
    ) -> list[dict]:
        prompts = self.extract_prompts(script_text)
        if not prompts:
            return []
        results = []
        total = len(prompts)
        for i, item in enumerate(prompts):
            logger.info(f"🖼️ [{i+1}/{total}] {item['scene_id']}")
            seed = (seed_base + i) if seed_base is not None else None
            result = await self.generate(
                item["prompt"], script_id=script_id,
                scene_id=item["scene_id"], model=model, seed=seed,
            )
            results.append(result)
        success = sum(1 for r in results if r["success"])
        logger.info(f"🎨 완료: {success}/{total} 성공")
        return results
