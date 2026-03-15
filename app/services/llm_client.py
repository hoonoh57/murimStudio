"""통합 LLM 클라이언트 — Claude 우선, Gemini 5-키 라운드로빈 폴백"""

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# ── 가격표 (USD per 1M tokens) ──
PRICING = {
    "claude-haiku-4-5-20250315": {"input": 1.00, "output": 5.00},
    "gemini-2.5-flash":          {"input": 0.15, "output": 0.60},
    "gemini-2.0-flash":          {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash-lite":     {"input": 0.075, "output": 0.30},
}

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-flash-lite"]


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str            # "claude" | "gemini"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


class LLMClient:
    """싱글턴 — Claude 우선, Gemini 멀티키 라운드로빈 폴백"""

    _instance: Optional["LLMClient"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._http = httpx.AsyncClient(timeout=120)

        # Claude
        self._claude_key = settings.CLAUDE_API_KEY

        # Gemini 키 순환 이터레이터
        self._gemini_keys = settings.GEMINI_API_KEYS
        self._gemini_cycle = (
            itertools.cycle(self._gemini_keys) if self._gemini_keys else iter([])
        )
        self._gemini_lock = asyncio.Lock()

        provider = "Claude" if self._claude_key else (
            f"Gemini ({len(self._gemini_keys)}키)" if self._gemini_keys else "없음"
        )
        logger.info(f"[LLMClient] 활성 프로바이더: {provider}")

    # ── 내부: 다음 Gemini 키 가져오기 ──
    async def _next_gemini_key(self) -> str:
        async with self._gemini_lock:
            return next(self._gemini_cycle)

    # ── 공개 API ──
    async def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Claude → Gemini 순으로 시도, Gemini는 키·모델 폴백"""

        # 1) Claude 시도
        if self._claude_key:
            try:
                return await self._call_claude(prompt, system, max_tokens, temperature)
            except Exception as e:
                logger.warning(f"[LLM] Claude 실패: {e}, Gemini 폴백 시도")

        # 2) Gemini 폴백 — 모델 × 키 조합 시도
        if not self._gemini_keys:
            raise RuntimeError("사용 가능한 AI API 키가 없습니다. .env를 확인하세요.")

        last_err = None
        for model in GEMINI_MODELS:
            for _ in range(len(self._gemini_keys)):
                key = await self._next_gemini_key()
                try:
                    return await self._call_gemini(
                        prompt, system, max_tokens, temperature, model, key
                    )
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    if status == 429:
                        logger.warning(
                            f"[LLM] Gemini {model} 키 ...{key[-6:]} 429 한도 초과, 다음 키 시도"
                        )
                        last_err = e
                        continue
                    elif status == 400:
                        logger.warning(
                            f"[LLM] Gemini {model} 400 Bad Request, 다음 모델 시도"
                        )
                        last_err = e
                        break  # 다음 모델로
                    elif status in (500, 503):
                        logger.warning(f"[LLM] Gemini {model} 서버 오류 {status}")
                        last_err = e
                        break
                    else:
                        raise
                except Exception as e:
                    logger.warning(f"[LLM] Gemini {model} 오류: {e}")
                    last_err = e
                    break

        raise RuntimeError(f"모든 Gemini 모델/키 소진. 마지막 오류: {last_err}")

    # ── Claude 호출 ──
    async def _call_claude(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> LLMResponse:
        model = "claude-haiku-4-5-20250315"
        t0 = time.monotonic()
        messages = [{"role": "user", "content": prompt}]
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        if system:
            body["system"] = system

        resp = await self._http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self._claude_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        text = data["content"][0]["text"]
        usage = data.get("usage", {})
        inp_tok = usage.get("input_tokens", 0)
        out_tok = usage.get("output_tokens", 0)
        price = PRICING[model]
        cost = (inp_tok * price["input"] + out_tok * price["output"]) / 1_000_000

        return LLMResponse(
            text=text, model=model, provider="claude",
            input_tokens=inp_tok, output_tokens=out_tok,
            cost_usd=round(cost, 6),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    # ── Gemini 호출 ──
    async def _call_gemini(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
        model: str,
        api_key: str,
    ) -> LLMResponse:
        t0 = time.monotonic()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:generateContent?key={api_key}"
        )

        # 사용자 메시지만 contents에 넣기
        contents = [{"role": "user", "parts": [{"text": prompt}]}]

        body = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        # system prompt는 systemInstruction 필드로 전달
        if system:
            body["systemInstruction"] = {
                "parts": [{"text": system}]
            }

        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {})
        inp_tok = usage.get("promptTokenCount", 0)
        out_tok = usage.get("candidatesTokenCount", 0)
        price = PRICING.get(model, {"input": 0.15, "output": 0.60})
        cost = (inp_tok * price["input"] + out_tok * price["output"]) / 1_000_000

        return LLMResponse(
            text=text, model=model, provider="gemini",
            input_tokens=inp_tok, output_tokens=out_tok,
            cost_usd=round(cost, 6),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )


# 싱글턴 접근
llm_client = LLMClient()


# ── 헬퍼 함수 ──
def get_llm_client() -> LLMClient:
    """싱글턴 LLMClient 인스턴스 반환"""
    return llm_client


def has_llm_client() -> bool:
    """사용 가능한 AI API 키가 하나라도 있는지 확인"""
    return bool(settings.CLAUDE_API_KEY or settings.GEMINI_API_KEYS)
