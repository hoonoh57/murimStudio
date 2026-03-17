"""
이미지 생성 서비스 – Pollinations.ai (gen.pollinations.ai + API Key)
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

# ── 설정 ──────────────────────────────────────────────
OUTPUT_DIR = Path("static/images")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
BASE_URL = "https://gen.pollinations.ai/image"
DEFAULT_MODEL = "flux"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
REQUEST_TIMEOUT = 120
RETRY_COUNT = 3
RETRY_DELAY = 5
RATE_LIMIT_DELAY = 6           # Spore 티어: 5초+ 간격

STYLE_PREFIX = (
    "highly detailed digital painting, cinematic lighting, "
    "ancient Chinese martial arts, wuxia style, dramatic atmosphere, "
    "8k resolution, trending on artstation"
)

MAX_PROMPT_LENGTH = 800


class ImageGenerator:
    """Pollinations.ai 기반 이미지 생성기"""

    def __init__(self):
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        if API_KEY:
            logger.info(f"✅ Pollinations API 키 설정됨 ({API_KEY[:8]}...)")
        else:
            logger.warning("⚠️ POLLINATIONS_API_KEY 미설정 – .env에 추가하세요")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": "MurimStudio/1.3"}
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

        # URL 길이 체크
        if len(url) > 2048:
            logger.warning(f"⚠️ URL 너무 김 ({len(url)}자), 프롬프트 축소")
            short_prompt = prompt[:400].strip()
            full_prompt = f"{STYLE_PREFIX}, {short_prompt}" if add_style else short_prompt
            encoded = quote(full_prompt)
            url = f"{BASE_URL}/{encoded}?{param_str}"

        prompt_hash = hashlib.md5(full_prompt.encode()).hexdigest()[:8]
        filename = f"{scene_id}_{prompt_hash}.jpg"
        filepath = OUTPUT_DIR / filename

        if filepath.exists() and filepath.stat().st_size > 10_000:
            logger.info(f"⏩ 캐시 사용: {filepath}")
            return {
                "success": True,
                "path": str(filepath),
                "url": f"/static/images/{filename}",
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
                    logger.info(f"🎨 이미지 생성 중 [{scene_id}] (시도 {attempt}/{RETRY_COUNT})")
                    resp = await client.get(url)
                    self._last_request_time = time.time()

                    if resp.status_code == 200 and len(resp.content) > 5_000:
                        filepath.write_bytes(resp.content)
                        elapsed = time.time() - start
                        size_kb = len(resp.content) / 1024
                        logger.info(
                            f"✅ 이미지 저장: {filepath} "
                            f"({size_kb:.0f}KB, {elapsed:.1f}초)"
                        )
                        return {
                            "success": True,
                            "path": str(filepath),
                            "url": f"/static/images/{filename}",
                            "prompt": prompt,
                            "elapsed": elapsed,
                            "cached": False,
                        }
                    else:
                        body = resp.text[:200]
                        logger.warning(
                            f"⚠️ 응답 이상: status={resp.status_code}, "
                            f"size={len(resp.content)}, body={body}"
                        )
                except httpx.TimeoutException:
                    logger.warning(f"⏰ 타임아웃 (시도 {attempt})")
                except httpx.HTTPError as e:
                    logger.warning(f"❌ HTTP 에러: {e} (시도 {attempt})")

                if attempt < RETRY_COUNT:
                    await asyncio.sleep(RETRY_DELAY)

            elapsed = time.time() - start
            logger.error(f"❌ 이미지 생성 실패: {scene_id}")
            return {
                "success": False,
                "path": "",
                "url": "",
                "prompt": prompt,
                "elapsed": elapsed,
                "cached": False,
            }

    @staticmethod
    def extract_prompts(script_text: str) -> list[dict]:
        results = []

        # 패턴 1: [이미지 프롬프트: ... ]
        pattern1 = re.compile(
            r'\[이미지\s*프롬프트\s*[:：]\s*(.+?)\]',
            re.DOTALL
        )
        # 패턴 2: [이미지 프롬프트] 뒤 텍스트
        pattern2 = re.compile(
            r'\[이미지\s*프롬프트\]\s*(.+?)(?=\s*\[|$)',
            re.DOTALL
        )
        # 패턴 3: [Image Prompt: ... ]
        pattern3 = re.compile(
            r'\[Image\s*Prompt\s*[:：]\s*(.+?)\]',
            re.DOTALL | re.IGNORECASE
        )

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
                })

        logger.info(f"📝 {len(results)}개 이미지 프롬프트 추출")
        return results

    async def generate_all_from_script(
        self,
        script_text: str,
        *,
        model: str = DEFAULT_MODEL,
        seed_base: int | None = None,
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
                item["prompt"],
                scene_id=item["scene_id"],
                model=model,
                seed=seed,
            )
            results.append(result)

        success = sum(1 for r in results if r["success"])
        logger.info(f"🎨 이미지 생성 완료: {success}/{total} 성공")
        return results
