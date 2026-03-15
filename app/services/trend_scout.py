import os
import json
from typing import Any, List
from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT

class TrendScout:
    def __init__(self):
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            self.client = None
        else:
            self.client = Anthropic(api_key=api_key)

    async def collect_all_sources(self) -> List[dict[str, Any]]:
        # 실제 구현에서는 웹 크롤링/YouTube API/Reddit/MAL 등을 병렬 호출
        # 여기서는 프로토타입 데이터 리턴
        return [
            {'title': '화산귀환 51~100화', 'trend_score': 95, 'source': 'Naver'},
            {'title': '북검전기 시즌2', 'trend_score': 88, 'source': 'Reddit'},
            {'title': '나혼렙 시즌3 예고', 'trend_score': 85, 'source': 'MAL'},
        ]

    async def ai_rank_topics(self, raw_data: List[dict[str, Any]]) -> List[dict[str, Any]]:
        prompt = (
            """다음 웹툰/만화 트렌드 데이터를 분석하여\n"
            "유튜브 리캡 영상으로 만들었을 때 가장 조회수가 높을 작품 TOP 5를 추천해줘.\n"
            "평가 기준:\n"
            "- 현재 검색량 트렌드 (40%)\n"
            "- 경쟁 채널의 리캡 유무 (30%)\n"
            "- 동남아+영어권 인지도 (20%)\n"
            "- 스토리 리캡 적합성 (10%)\n\n"
            f"데이터: {json.dumps(raw_data, ensure_ascii=False)}\n\n"
            "JSON 형식으로 응답:\n"
            "[{\"title\": \"\", \"score\": 0, \"reason\": \"\", \"episode_range\": \"\", \"target_audience\": \"\"}]"
            """
        )

        if self.client is None:
            # API 키가 없으면 기본 데이터 순서로 리턴
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

        response = await self.client.completions.create(
            model='claude-3.5',
            max_tokens=400,
            temperature=0.2,
            prompt=HUMAN_PROMPT + prompt + AI_PROMPT,
        )

        text = response['completion'] if isinstance(response, dict) else response
        try:
            result = json.loads(text.strip())
            if isinstance(result, list):
                return result
        except Exception:
            pass

        return [
            {
                'title': x.get('title', ''),
                'score': x.get('score', 0),
                'reason': x.get('reason', ''),
                'episode_range': x.get('episode_range', ''),
                'target_audience': x.get('target_audience', ''),
            }
            for x in raw_data
        ]
