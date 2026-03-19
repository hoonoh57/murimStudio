"""
이미지 생성 서비스 – Pollinations.ai (gen.pollinations.ai + API Key)
스크립트 ID별 폴더 관리, 장르별 스타일 자동 감지
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
# 기본 설정 (롱폼)
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_MODEL = "flux"

# 포맷별 해상도
FORMAT_SETTINGS = {
    "long": {
        "width": 1920,
        "height": 1080,
        "composition_suffix": "",  # 기존 그대로
    },
    "shorts": {
        "width": 1080,
        "height": 1920,
        "composition_suffix": ", vertical composition, close-up portrait, dramatic expression, mobile-optimized, 9:16 aspect ratio",
    },
}

REQUEST_TIMEOUT = 120
RETRY_COUNT = 3
RETRY_DELAY = 5
RATE_LIMIT_DELAY = 6
MAX_PROMPT_LENGTH = 800

# ──────────────────────────────────────────────
# 장르별 이미지 스타일 프리셋
# ──────────────────────────────────────────────
GENRE_STYLES = {
    "wuxia": {
        "name": "무협",
        "prefix": (
            "highly detailed digital painting, cinematic lighting, "
            "ancient Chinese martial arts, wuxia style, dramatic atmosphere, "
            "8k resolution, trending on artstation"
        ),
        "keywords": [
            "화산", "무림", "검", "귀환", "천마", "협객", "무공", "장문인",
            "사파", "정파", "마교", "비급", "내공", "검기", "도법", "권법",
            "wuxia", "martial arts", "murim", "cultivation"
        ],
    },
    "anime": {
        "name": "애니/웹툰",
        "prefix": (
            "anime style illustration, vibrant colors, detailed character art, "
            "Japanese animation aesthetic, clean linework, expressive eyes, "
            "high quality anime key visual, trending on pixiv"
        ),
        "keywords": [
            "봇치", "록", "애니", "웹툰", "학교", "밴드", "마법소녀",
            "아이돌", "하렘", "이세계", "anime", "manga", "webtoon",
            "isekai", "school", "shounen", "shoujo"
        ],
    },
    "comedy": {
        "name": "코미디/일상",
        "prefix": (
            "colorful cartoon style illustration, expressive characters, "
            "comedic tone, bright warm lighting, fun atmosphere, "
            "clean digital art, vibrant palette"
        ),
        "keywords": [
            "놓지마", "개그", "코미디", "일상", "웃긴", "톡", "gag",
            "comedy", "slice of life", "daily", "funny", "sitcom"
        ],
    },
    "fantasy": {
        "name": "판타지",
        "prefix": (
            "epic fantasy art, magical atmosphere, detailed world-building, "
            "cinematic lighting, mystical glow, high fantasy illustration, "
            "8k resolution, trending on artstation"
        ),
        "keywords": [
            "마법", "던전", "용사", "이세계", "마왕", "레벨", "헌터",
            "소환", "정령", "드래곤", "fantasy", "dungeon", "dragon",
            "magic", "sorcery", "hunter", "guild", "mana"
        ],
    },
    "romance": {
        "name": "로맨스",
        "prefix": (
            "soft romantic illustration, warm pastel tones, gentle lighting, "
            "emotional mood, beautiful character art, dreamy atmosphere, "
            "high quality digital painting"
        ),
        "keywords": [
            "로맨스", "사랑", "연애", "고백", "첫사랑", "러브",
            "romance", "love", "dating", "confession", "heartfelt"
        ],
    },
    "action": {
        "name": "액션/배틀",
        "prefix": (
            "dynamic action scene, intense cinematic lighting, high contrast, "
            "powerful composition, explosive energy, motion blur effects, "
            "manhwa action style, 8k resolution"
        ),
        "keywords": [
            "배틀", "전투", "격투", "싸움", "능력자", "히어로",
            "action", "battle", "fight", "combat", "hero", "villain",
            "superhero", "power"
        ],
    },
    "horror": {
        "name": "호러/스릴러",
        "prefix": (
            "dark horror atmosphere, eerie lighting, unsettling mood, "
            "detailed shadows, creepy composition, psychological tension, "
            "cinematic horror art style"
        ),
        "keywords": [
            "공포", "호러", "귀신", "좀비", "저주", "괴담",
            "horror", "thriller", "ghost", "zombie", "curse", "dark"
        ],
    },
    "neutral": {
        "name": "기본 (장르 자동)",
        "prefix": (
            "high quality digital illustration, cinematic lighting, "
            "detailed art, vivid colors, professional composition, "
            "8k resolution, trending on artstation"
        ),
        "keywords": [],
    },
}


def detect_genre(title: str, content: str = "") -> str:
    """프로젝트 제목과 스크립트 내용으로 장르 자동 감지"""
    text = (title + " " + content[:500]).lower()

    best_genre = "neutral"
    best_score = 0

    for genre_key, genre_info in GENRE_STYLES.items():
        if genre_key == "neutral":
            continue
        score = sum(1 for kw in genre_info["keywords"] if kw.lower() in text)
        if score > best_score:
            best_score = score
            best_genre = genre_key

    logger.info(f"🎭 장르 감지: '{title}' → {best_genre} ({GENRE_STYLES[best_genre]['name']}, 점수={best_score})")
    return best_genre


def get_style_prefix(genre: str = "neutral") -> str:
    """장르에 맞는 스타일 프리픽스 반환"""
    if genre in GENRE_STYLES:
        return GENRE_STYLES[genre]["prefix"]
    return GENRE_STYLES["neutral"]["prefix"]


def get_genre_list() -> list[dict]:
    """UI용 장르 목록 반환"""
    return [
        {"key": k, "name": v["name"]}
        for k, v in GENRE_STYLES.items()
    ]


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
        d = BASE_IMAGE_DIR / f"script_{script_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def list_script_folders() -> list[dict]:
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
        d = BASE_IMAGE_DIR / f"script_{script_id}"
        if not d.exists():
            return []
        files = sorted(
            list(d.glob("*.jpg")) + list(d.glob("*.png"))
        )
        return [str(f) for f in files]

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"User-Agent": "MurimStudio/1.6"}
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
        genre: str = "neutral",
        format: str = "long",           # ← 추가
        model: str = DEFAULT_MODEL,
        width: int = 0,                 # ← 0이면 format에서 자동 결정
        height: int = 0,                # ← 0이면 format에서 자동 결정
        seed: int | None = None,
        enhance: bool = True,
        add_style: bool = True,
    ) -> dict:
        """이미지 생성 (포맷에 따라 해상도/구도 자동 분기)"""

        # ── 포맷별 해상도/구도 자동 결정 ──
        fmt_settings = FORMAT_SETTINGS.get(format, FORMAT_SETTINGS["long"])
        if width == 0:
            width = fmt_settings["width"]
        if height == 0:
            height = fmt_settings["height"]
        composition_suffix = fmt_settings.get("composition_suffix", "")

        prompt = prompt[:MAX_PROMPT_LENGTH].strip()

        # 장르별 스타일 적용
        style = get_style_prefix(genre)
        if add_style:
            full_prompt = f"{style}, {prompt}{composition_suffix}"
        else:
            full_prompt = f"{prompt}{composition_suffix}"

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
            if add_style:
                full_prompt = f"{style}, {short_prompt}{composition_suffix}"
            else:
                full_prompt = f"{short_prompt}{composition_suffix}"
            encoded = quote(full_prompt)
            url = f"{BASE_URL}/{encoded}?{param_str}"

        output_dir = self.get_script_dir(script_id) if script_id else BASE_IMAGE_DIR
        prompt_hash = hashlib.md5(full_prompt.encode()).hexdigest()[:8]
        filename = f"{scene_id}_{prompt_hash}.jpg"
        filepath = output_dir / filename

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
                "genre": genre,
                "format": format,
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
                    logger.info(
                        f"🎨 [{scene_id}] 생성 중 (시도 {attempt}/{RETRY_COUNT}, "
                        f"장르={GENRE_STYLES.get(genre, {}).get('name', genre)}, "
                        f"포맷={format}, {width}x{height})"
                    )
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
                            "genre": genre,
                            "format": format,
                            "elapsed": elapsed,
                            "cached": False,
                        }
                    else:
                        body = resp.text[:200]
                        logger.warning(
                            f"⚠️ status={resp.status_code}, size={len(resp.content)}, body={body}"
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
                "success": False, "path": "", "url": "",
                "prompt": prompt, "genre": genre, "format": format,
                "elapsed": elapsed, "cached": False,
            }


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
        genre: str = "neutral",
        format: str = "long",           # ← 파라미터 추가 (버그 수정)
        model: str = DEFAULT_MODEL, seed_base: int | None = None,
    ) -> list[dict]:
        prompts = self.extract_prompts(script_text)
        if not prompts:
            return []

        # 장르 자동 감지 (neutral이면)
        if genre == "neutral":
            genre = detect_genre("", script_text)

        # 포맷별 설정 로그
        fmt_settings = FORMAT_SETTINGS.get(format, FORMAT_SETTINGS["long"])
        logger.info(
            f"📐 포맷: {format} → {fmt_settings['width']}×{fmt_settings['height']}"
        )

        results = []
        total = len(prompts)
        for i, item in enumerate(prompts):
            logger.info(f"🖼️ [{i+1}/{total}] {item['scene_id']} (장르: {genre}, 포맷: {format})")
            seed = (seed_base + i) if seed_base is not None else None
            result = await self.generate(
                item["prompt"], script_id=script_id,
                scene_id=item["scene_id"], genre=genre,
                format=format,
                model=model, seed=seed,
            )
            results.append(result)

        success = sum(1 for r in results if r["success"])
        logger.info(f"🎨 완료: {success}/{total} 성공 (장르: {genre}, 포맷: {format})")
        return results
