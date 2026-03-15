"""중앙 설정 — 환경변수 로드"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    # ── AI Keys ──
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")

    # Gemini 키 최대 5개 로드
    GEMINI_API_KEYS: list[str] = [
        v for k in [
            "GEMINI_API_KEY_1",
            "GEMINI_API_KEY_2",
            "GEMINI_API_KEY_3",
            "GEMINI_API_KEY_4",
            "GEMINI_API_KEY_5",
        ]
        if (v := os.getenv(k, ""))
    ]

    # 하위 호환: 단일 키도 지원
    _single = os.getenv("GEMINI_API_KEY", "")
    if _single and _single not in GEMINI_API_KEYS:
        GEMINI_API_KEYS.insert(0, _single)

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