"""트렌드 스카우트 — 무협 웹툰 트렌드 수집 및 AI 랭킹"""

import os
import re
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, List

import httpx

from app.db import get_db
from app.services.llm_client import get_llm_client, has_llm_client
from app.services.utils import log_llm_cost

logger = logging.getLogger(__name__)

YOUTUBE_KEYWORDS = [
    'murim manhwa recap', '무협 웹툰 리캡',
    'martial arts manhwa recap', 'return of mount hua recap',
]
NAVER_WEBTOON_GENRES = ['무협', '판타지']
REDDIT_SUBREDDITS = ['manhwa', 'manga']


class TrendScout:
    def __init__(self):
        self.llm = get_llm_client()
        self.youtube_api_key = os.getenv('YOUTUBE_API_KEY', '')
        if self.llm is None:
            logger.warning('No LLM API key — TrendScout AI ranking disabled')

    async def collect_all_sources(self) -> List[dict[str, Any]]:
        tasks = [
            self._collect_youtube(),
            self._collect_naver_webtoon(),
            self._collect_reddit(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: List[dict[str, Any]] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f'Source collection failed: {result}')
                continue
            if isinstance(result, list):
                merged.extend(result)

        if not merged:
            logger.info('No live data collected — using prototype fallback')
            merged = self._prototype_data()

        seen: dict[str, dict] = {}
        for item in merged:
            title = item.get('title', '').strip()
            if not title:
                continue
            existing = seen.get(title)
            if existing is None or item.get('trend_score', 0) > existing.get('trend_score', 0):
                seen[title] = item
        deduped = sorted(seen.values(), key=lambda x: x.get('trend_score', 0), reverse=True)

        await self._save_cache(deduped)
        return deduped

    # ══════ AI 랭킹 (통합 LLM) ══════

    async def ai_rank_topics(self, raw_data: List[dict[str, Any]]) -> List[dict[str, Any]]:
        if self.llm is None:
            return self._fallback_rank(raw_data)

        clean_data = [
            {k: v for k, v in item.items() if k != 'meta'}
            for item in raw_data[:20]
        ]

        prompt = f"""다음 웹툰/만화 트렌드 데이터를 분석하여
유튜브 리캡 영상으로 만들었을 때 가장 조회수가 높을 작품 TOP 5를 추천해줘.

평가 기준:
- 현재 검색량 트렌드 (40%)
- 경쟁 채널의 리캡 유무 (30%)
- 동남아+영어권 인지도 (20%)
- 스토리 리캡 적합성 (10%)

데이터: {json.dumps(clean_data, ensure_ascii=False)}

반드시 아래 JSON 배열 형식으로만 응답하세요. 마크다운 코드블록 없이 순수 JSON만 출력. 5개 항목. reason은 20자 이내로 짧게:
[{{"title": "작품명", "score": 95, "reason": "짧은근거", "episode_range": "1~50화", "target_audience": "global"}}]"""

        try:
            resp = await self.llm.generate(prompt=prompt, max_tokens=4096, temperature=0.2)
            await log_llm_cost(resp, action='trend_rank')

            text = resp.text.strip()

            # 마크다운 코드블록 제거
            if text.startswith('```'):
                text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()

            # JSON 배열만 추출
            start = text.find('[')
            end = text.rfind(']')
            if start != -1 and end != -1:
                text = text[start:end + 1]

            result = json.loads(text)
            if isinstance(result, list) and len(result) > 0:
                logger.info(f'AI ranked {len(result)} topics via {resp.provider}/{resp.model}')
                return result

        except json.JSONDecodeError as e:
            logger.warning(f'LLM response JSON parse error: {e}')
        except Exception as e:
            logger.error(f'TrendScout AI ranking failed: {e}')

        return self._fallback_rank(raw_data)

    # ══════ 데이터 수집 ══════

    async def _collect_youtube(self) -> List[dict[str, Any]]:
        if not self.youtube_api_key:
            logger.info('YOUTUBE_API_KEY not set — skipping YouTube collection')
            return []
        items: List[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for keyword in YOUTUBE_KEYWORDS:
                try:
                    resp = await client.get(
                        'https://www.googleapis.com/youtube/v3/search',
                        params={
                            'part': 'snippet', 'q': keyword, 'type': 'video',
                            'order': 'viewCount', 'publishedAfter': self._days_ago_iso(7),
                            'maxResults': 10, 'key': self.youtube_api_key,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for entry in data.get('items', []):
                        snippet = entry.get('snippet', {})
                        title = snippet.get('title', '')
                        score = self._youtube_relevance_score(title, keyword)
                        if score > 0:
                            items.append({
                                'title': self._clean_youtube_title(title),
                                'trend_score': score, 'source': 'YouTube', 'genre': 'murim',
                                'meta': {
                                    'video_id': entry.get('id', {}).get('videoId', ''),
                                    'channel': snippet.get('channelTitle', ''),
                                    'published': snippet.get('publishedAt', ''),
                                },
                            })
                except Exception as e:
                    logger.warning(f'YouTube collection error for "{keyword}": {e}')
        logger.info(f'YouTube: collected {len(items)} items')
        return items

    async def _collect_naver_webtoon(self) -> List[dict[str, Any]]:
        items: List[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    'https://comic.naver.com/api/webtoon/titlelist/weekday',
                    params={'order': 'ViewCount', 'week': 'dailyPlus'},
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; MurimFactory/1.0)'},
                )
                resp.raise_for_status()
                data = resp.json()
                webtoons = data.get('titleList', data.get('titleListMap', {}).get('dailyPlus', []))
                if isinstance(webtoons, dict):
                    all_wt = []
                    for day_list in webtoons.values():
                        if isinstance(day_list, list):
                            all_wt.extend(day_list)
                    webtoons = all_wt
                for idx, wt in enumerate(webtoons[:50]):
                    title = wt.get('titleName', wt.get('title', ''))
                    genre = wt.get('genre', wt.get('genreName', ''))
                    is_murim = any(g in str(genre) for g in NAVER_WEBTOON_GENRES)
                    if not is_murim and not self._is_murim_keyword(title):
                        continue
                    score = max(90 - idx * 2, 50)
                    items.append({
                        'title': title, 'trend_score': score, 'source': 'Naver', 'genre': 'murim',
                        'meta': {'webtoon_id': str(wt.get('titleId', '')), 'star_score': wt.get('starScore', 0)},
                    })
            except Exception as e:
                logger.warning(f'Naver Webtoon collection error: {e}')
        logger.info(f'Naver: collected {len(items)} items')
        return items

    async def _collect_reddit(self) -> List[dict[str, Any]]:
        items: List[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for sub in REDDIT_SUBREDDITS:
                try:
                    resp = await client.get(
                        f'https://www.reddit.com/r/{sub}/hot.json',
                        params={'limit': 25}, headers={'User-Agent': 'MurimFactory/1.0'},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    for post in data.get('data', {}).get('children', []):
                        pd = post.get('data', {})
                        title = pd.get('title', '')
                        ups = pd.get('ups', 0)
                        if not self._is_murim_keyword(title):
                            continue
                        score = min(95, 60 + int(ups / 100))
                        items.append({
                            'title': self._extract_work_title(title),
                            'trend_score': score, 'source': 'Reddit', 'genre': 'murim',
                            'meta': {'subreddit': sub, 'ups': ups, 'url': pd.get('url', '')},
                        })
                except Exception as e:
                    logger.warning(f'Reddit r/{sub} collection error: {e}')
        logger.info(f'Reddit: collected {len(items)} items')
        return items

    # ══════ 캐시 & 유틸 ══════

    async def _save_cache(self, data: List[dict[str, Any]]) -> None:
        db = await get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            for item in data:
                meta = item.get('meta', {})
                await db.execute(
                    'INSERT INTO trend_cache (title, trend_score, source, genre, meta_json, collected_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (item.get('title', ''), int(item.get('trend_score', 0)), item.get('source', ''),
                     item.get('genre', ''), json.dumps(meta, ensure_ascii=False), now),
                )
            await db.commit()
        except Exception as e:
            logger.error(f'Failed to save trend cache: {e}')
        finally:
            await db.close()

    async def get_cached_trends(self, limit: int = 30) -> List[dict[str, Any]]:
        db = await get_db()
        try:
            async with db.execute(
                'SELECT DISTINCT title, trend_score, source, genre, meta_json, collected_at FROM trend_cache ORDER BY collected_at DESC, trend_score DESC LIMIT ?',
                (limit,),
            ) as cursor:
                return [dict(r) for r in await cursor.fetchall()]
        finally:
            await db.close()

    @staticmethod
    def _fallback_rank(raw_data):
        return [{'title': item.get('title', ''), 'score': int(item.get('trend_score', 0)),
                 'reason': f"source: {item.get('source', 'unknown')}", 'episode_range': 'N/A',
                 'target_audience': 'global'}
                for item in sorted(raw_data, key=lambda x: x.get('trend_score', 0), reverse=True)]

    @staticmethod
    def _prototype_data():
        return [
            {'title': '화산귀환 51~100화', 'trend_score': 95, 'source': 'Naver', 'genre': 'murim'},
            {'title': '북검전기 시즌2', 'trend_score': 88, 'source': 'Reddit', 'genre': 'murim'},
            {'title': '나혼렙 시즌3 예고', 'trend_score': 85, 'source': 'MAL', 'genre': 'hunter'},
            {'title': '무림세가 장천재', 'trend_score': 79, 'source': 'Kakao', 'genre': 'murim'},
            {'title': '선협귀환기', 'trend_score': 72, 'source': 'Naver', 'genre': 'regression'},
        ]

    @staticmethod
    def _days_ago_iso(days: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')

    @staticmethod
    def _youtube_relevance_score(title: str, keyword: str) -> int:
        tl = title.lower()
        kws = ['murim', 'martial', '무협', '화산', 'mount hua', 'northern blade', '북검',
               'manhwa', 'recap', '리캡', 'return of', 'regression', 'reincarnation', '귀환', '회귀', 'cultivat', 'sect']
        matches = sum(1 for k in kws if k in tl)
        return 0 if matches == 0 else min(95, 50 + matches * 10)

    @staticmethod
    def _is_murim_keyword(text: str) -> bool:
        tl = text.lower()
        return any(k in tl for k in ['murim', 'martial', '무협', '무림', '화산', 'mount hua', '북검',
            'northern blade', 'manhwa', '만화', '웹툰', 'reincarnation', 'regression', '회귀', '귀환',
            '전생', 'cultivat', 'sect', '문파', '강호', '검', 'sword', 'heavenly'])

    @staticmethod
    def _extract_work_title(post_title: str) -> str:
        cleaned = re.sub(r'^\[.*?\]\s*', '', post_title)
        cleaned = re.split(r'\s*(?:chapter|ch\.?|ep\.?)\s*\d+', cleaned, flags=re.IGNORECASE)[0]
        return cleaned.strip() or post_title.strip()

    @staticmethod
    def _clean_youtube_title(title: str) -> str:
        cleaned = re.sub(r'\s*[\|\-–—]\s*(?:recap|리캡|explained|요약).*$', '', title, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*\(.*?(?:recap|리캡|part|파트).*?\)\s*$', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip() or title.strip()
