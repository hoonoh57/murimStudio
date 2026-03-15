"""중앙 설정 — 환경변수 로드"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _load_gemini_keys() -> list:
    """Gemini 키 1~5번 로드"""
    keys = []
    for i in range(1, 6):
        k = os.getenv(f"GEMINI_API_KEY_{i}", "")
        if k:
            keys.append(k)
    # 하위 호환: 단일 키도 지원
    single = os.getenv("GEMINI_API_KEY", "")
    if single and single not in keys:
        keys.insert(0, single)
    return keys


class Settings:
    # ── AI Keys ──
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")
    GEMINI_API_KEYS: list = _load_gemini_keys()

    # ── External Services ──
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    MIDJOURNEY_API_KEY: str = os.getenv("MIDJOURNEY_API_KEY", "")
    YOUTUBE_API_KEY: str = os.getenv("YOUTUBE_API_KEY", "")

    # ── App ──
    DB_PATH: str = os.getenv("DB_PATH", "app.db")
    STORAGE_SECRET: str = os.getenv("STORAGE_SECRET", "change-me")
    MONTHLY_BUDGET_USD: float = float(os.getenv("MONTHLY_BUDGET_USD", "200"))
    FASTAPI_HOST: str = os.getenv("FASTAPI_HOST", "0.0.0.0")
    FASTAPI_PORT: int = int(os.getenv("FASTAPI_PORT", "8080"))


settings = Settings()