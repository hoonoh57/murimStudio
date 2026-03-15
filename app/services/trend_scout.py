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
                'target_audience': 'global',
            }
            for x in raw_data
        ]
