"""
이미지 생성 서비스 – Pollinations.ai (무료, API키 불필요)
- image.pollinations.ai  레거시 엔드포인트 사용
- FLUX 모델 기본 (고품질)
- 16:9 비율 (1920x1080) – YouTube 영상용
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

BASE_URL = "https://image.pollinations.ai/prompt"
DEFAULT_MODEL = "flux"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
REQUEST_TIMEOUT = 120          # 이미지 생성 최대 대기
RETRY_COUNT = 3
RETRY_DELAY = 5                # 재시도 간격(초)
RATE_LIMIT_DELAY = 16          # Anonymous tier: 15초당 1회 → 16초 간격

# 무협 스타일 공통 접두어 (프롬프트 품질 향상)
STYLE_PREFIX = (
    "highly detailed digital painting, cinematic lighting, "
    "ancient Chinese martial arts, wuxia style, dramatic atmosphere, "
    "8k resolution, trending on artstation"
)


class ImageGenerator:
    """Pollinations.ai 기반 이미지 생성기"""

    def __init__(self):
        self._last_request_time = 0.0
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT),
                follow_redirects=True,
                headers={"User-Agent": "MurimStudio/1.2"}
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── 핵심: 단일 이미지 생성 ──────────────────────────
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
        """
        프롬프트로 이미지를 생성하고 로컬에 저장.
        Returns: {"success": bool, "path": str, "url": str, "prompt": str, "elapsed": float}
        """
        # 스타일 접두어 추가
        full_prompt = f"{STYLE_PREFIX}, {prompt}" if add_style else prompt

        # URL 구성
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

        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{BASE_URL}/{encoded}?{param_str}"

        # 파일명 생성
        prompt_hash = hashlib.md5(full_prompt.encode()).hexdigest()[:8]
        filename = f"{scene_id}_{prompt_hash}.jpg"
        filepath = OUTPUT_DIR / filename

        # 이미 존재하면 스킵
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

        # Rate limit 준수
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
                        logger.warning(
                            f"⚠️ 응답 이상: status={resp.status_code}, "
                            f"size={len(resp.content)}"
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

    # ── 스크립트에서 프롬프트 추출 ──────────────────────
    @staticmethod
    def extract_prompts(script_text: str) -> list[dict]:
        """
        스크립트에서 [이미지 프롬프트] 태그를 파싱하여
        scene_id와 prompt 목록을 반환.
        """
        results = []
        # 패턴: [이미지 프롬프트] 뒤의 텍스트 (다음 태그 또는 줄 끝까지)
        pattern = re.compile(
            r'\[이미지\s*프롬프트\]\s*(.+?)(?=\n\s*\[|\n\s*$|\Z)',
            re.DOTALL
        )
        matches = pattern.findall(script_text)

        for i, raw in enumerate(matches):
            # Midjourney 파라미터 제거
            prompt = re.sub(r'--\w+\s+\S+', '', raw).strip()
            # 줄바꿈 정리
            prompt = re.sub(r'\s+', ' ', prompt).strip()
            if prompt:
                results.append({
                    "scene_id": f"scene_{i:02d}",
                    "prompt": prompt,
                })

        logger.info(f"📝 {len(results)}개 이미지 프롬프트 추출")
        return results

    # ── 스크립트 전체 이미지 일괄 생성 ─────────────────
    async def generate_all_from_script(
        self,
        script_text: str,
        *,
        model: str = DEFAULT_MODEL,
        seed_base: int | None = None,
    ) -> list[dict]:
        """
        스크립트에서 프롬프트를 추출하고 전체 이미지를 순차 생성.
        (Rate limit 준수를 위해 순차 실행)
        """
        prompts = self.extract_prompts(script_text)
        if not prompts:
            logger.warning("⚠️ 스크립트에서 이미지 프롬프트를 찾을 수 없습니다")
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
