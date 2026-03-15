import os
import json
import asyncio
from typing import Any, List

from app.services.cost_service import CostTracker

class TrendScout:
    def __init__(self):
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            self.client = None
        else:
            from anthropic import AsyncAnthropic
            self.client = AsyncAnthropic(api_key=api_key)

    async def collect_all_sources(self) -> List[dict[str, Any]]:
        # TODO: 실제 크롤링/API 연동
        return [
            {'title': '화산귀환 51~100화', 'trend_score': 95, 'source': 'Naver'},
            {'title': '북검전기 시즌2', 'trend_score': 88, 'source': 'Reddit'},
            {'title': '나혼렙 시즌3 예고', 'trend_score': 85, 'source': 'MAL'},
        ]

    async def ai_rank_topics(self, raw_data: List[dict[str, Any]]) -> List[dict[str, Any]]:
        if self.client is None:
            return [
                {
                    'title': item.get('title', ''),
                    'score': int(item.get('trend_score', 0)),
                    'reason': f"source: {item.get('source', 'unknown')}",
                    'episode_range': 'N/A',
                    'target_audience': 'global',
                }
                for item in raw_data
            ]

        prompt = f"""다음 웹툰/만화 트렌드 데이터를 분석하여
유튜브 리캡 영상으로 만들었을 때 가장 조회수가 높을 작품 TOP 5를 추천해줘.

평가 기준:
- 현재 검색량 트렌드 (40%)
- 경쟁 채널의 리캡 유무 (30%)
- 동남아+영어권 인지도 (20%)
- 스토리 리캡 적합성 (10%)

데이터: {json.dumps(raw_data, ensure_ascii=False)}

JSON 배열로만 응답 (마크다운 없이):
[{{"title": "", "score": 0, "reason": "", "episode_range": "", "target_audience": ""}}]"""

        try:
            response = await self.client.messages.create(
                model='claude-haiku-4-5-20250315',
                max_tokens=2000,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )

            # 비용 로그 기록: Claude API 토큰 사용량 기반
            usage = None
            if hasattr(response, 'usage'):
                usage = response.usage
            elif isinstance(response, dict):
                usage = response.get('usage')

            if usage:
                input_tokens = int(getattr(usage, 'input_tokens', usage.get('input_tokens', 0))) if usage else 0
                output_tokens = int(getattr(usage, 'output_tokens', usage.get('output_tokens', 0))) if usage else 0
                cost = (input_tokens * 1.0 / 1_000_000) + (output_tokens * 5.0 / 1_000_000)
                tracker = CostTracker()
                await tracker.log_cost('claude', 'trend_rank', input_tokens + output_tokens, cost)

            text = response.content[0].text
            result = json.loads(text.strip())
            if isinstance(result, list):
                return result
        except Exception:
            pass

        return [
            {
                'title': x.get('title', ''),
                'score': x.get('trend_score', 0),
                'reason': x.get('source', ''),
                'episode_range': 'N/A',
                'target_audie"""트렌드 스카우트 — 무협 웹툰 트렌드 수집 및 AI 랭킹"""

import os
import json
import logging
from typing import Any, List

from app.services.utils import log_claude_cost

logger = logging.getLogger(__name__)


class TrendScout:
    def __init__(self):
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            self.client = None
            logger.warning('CLAUDE_API_KEY not set — TrendScout will use fallback data')
        else:
            from anthropic import AsyncAnthropic
            self.client = AsyncAnthropic(api_key=api_key)

    async def collect_all_sources(self) -> List[dict[str, Any]]:
        """모든 소스에서 트렌드 데이터 수집.

        TODO: 실제 구현 시 아래를 병렬 호출
        - 네이버 웹툰 랭킹 크롤링
        - 카카오 웹툰 랭킹 크롤링
        - YouTube Data API 검색 ('murim manhwa recap')
        - Reddit r/manhwa hot posts
        - MyAnimeList trending
        """
        # 프로토타입 데이터
        return [
            {'title': '화산귀환 51~100화', 'trend_score': 95, 'source': 'Naver', 'genre': 'murim'},
            {'title': '북검전기 시즌2', 'trend_score': 88, 'source': 'Reddit', 'genre': 'murim'},
            {'title': '나혼렙 시즌3 예고', 'trend_score': 85, 'source': 'MAL', 'genre': 'hunter'},
            {'title': '무림세가 장천재', 'trend_score': 79, 'source': 'Kakao', 'genre': 'murim'},
            {'title': '선협귀환기', 'trend_score': 72, 'source': 'Naver', 'genre': 'regression'},
        ]

    async def ai_rank_topics(self, raw_data: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """Claude로 최적 리캡 대상 순위 매기기"""

        if self.client is None:
            return self._fallback_rank(raw_data)

        prompt = f"""다음 웹툰/만화 트렌드 데이터를 분석하여
유튜브 리캡 영상으로 만들었을 때 가장 조회수가 높을 작품 TOP 5를 추천해줘.

평가 기준:
- 현재 검색량 트렌드 (40%)
- 경쟁 채널의 리캡 유무 (30%)
- 동남아+영어권 인지도 (20%)
- 스토리 리캡 적합성 (10%)

데이터: {json.dumps(raw_data, ensure_ascii=False)}

아래 JSON 배열 형식으로만 응답하세요. 마크다운이나 설명 없이 순수 JSON만:
[{{"title": "작품명", "score": 95, "reason": "순위 근거", "episode_range": "1~50화", "target_audience": "global"}}]"""

        try:
            response = await self.client.messages.create(
                model='claude-haiku-4-5-20250315',
                max_tokens=2000,
                temperature=0.2,
                messages=[{'role': 'user', 'content': prompt}],
            )

            await log_claude_cost(response, action='trend_rank')

            text = response.content[0].text.strip()
            # JSON 블록이 ```json ... ``` 으로 감싸진 경우 처리
            if text.startswith('```'):
                text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

            result = json.loads(text)
            if isinstance(result, list) and len(result) > 0:
                logger.info(f'AI ranked {len(result)} topics')
                return result

        except json.JSONDecodeError as e:
            logger.warning(f'Claude response JSON parse error: {e}')
        except Exception as e:
            logger.error(f'TrendScout AI ranking failed: {e}')

        return self._fallback_rank(raw_data)

    @staticmethod
    def _fallback_rank(raw_data: List[dict[str, Any]]) -> List[dict[str, Any]]:
        return [
            {
                'title': item.get('title', ''),
                'score': int(item.get('trend_score', 0)),
                'reason': f"source: {item.get('source', 'unknown')}",
                'episode_range': 'N/A',
                'target_audience': 'global',
            }
            for item in sorted(raw_data, key=lambda x: x.get('trend_score', 0), reverse=True)
        ]

            for x in raw_data
        ]
