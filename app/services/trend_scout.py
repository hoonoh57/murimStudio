"""트렌드 스카우트 — 무협 웹툰 트렌드 수집 및 AI 랭킹"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, List

import httpx

from app.db import get_db
from app.services.utils import log_claude_cost

logger = logging.getLogger(__name__)

# ─── 검색 키워드 ───
YOUTUBE_KEYWORDS = [
    'murim manhwa recap',
    '무협 웹툰 리캡',
    'martial arts manhwa recap',
    'return of mount hua recap',
]

NAVER_WEBTOON_GENRES = ['무협', '판타지']  # 네이버 웹툰 장르 필터

REDDIT_SUBREDDITS = ['manhwa', 'manga']


class TrendScout:
    def __init__(self):
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            self.client = None
            logger.warning('CLAUDE_API_KEY not set — TrendScout will use fallback data')
        else:
            from anthropic import AsyncAnthropic
            self.client = AsyncAnthropic(api_key=api_key)

        self.youtube_api_key = os.getenv('YOUTUBE_API_KEY', '')

    # ══════════════════════════════════════════════
    #  실시간 데이터 수집
    # ══════════════════════════════════════════════

    async def collect_all_sources(self) -> List[dict[str, Any]]:
        """모든 소스에서 트렌드 데이터를 병렬 수집한 뒤 합산합니다."""

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

        # 수집 결과가 전혀 없으면 프로토타입 데이터 폴백
        if not merged:
            logger.info('No live data collected — using prototype fallback')
            merged = self._prototype_data()

        # 중복 제목 제거 (점수가 높은 쪽 유지)
        seen: dict[str, dict] = {}
        for item in merged:
            title = item.get('title', '').strip()
            if not title:
                continue
            existing = seen.get(title)
            if existing is None or item.get('trend_score', 0) > existing.get('trend_score', 0):
                seen[title] = item
        deduped = sorted(seen.values(), key=lambda x: x.get('trend_score', 0), reverse=True)

        # DB 캐시 저장
        await self._save_cache(deduped)

        return deduped

    # ── YouTube Data API v3 ──

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
                            'part': 'snippet',
                            'q': keyword,
                            'type': 'video',
                            'order': 'viewCount',
                            'publishedAfter': self._days_ago_iso(7),
                            'maxResults': 10,
                            'key': self.youtube_api_key,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    for entry in data.get('items', []):
                        snippet = entry.get('snippet', {})
                        title = snippet.get('title', '')
                        # 무협/manhwa 관련성 기반 점수 부여
                        score = self._youtube_relevance_score(title, keyword)
                        if score > 0:
                            items.append({
                                'title': self._clean_youtube_title(title),
                                'trend_score': score,
                                'source': 'YouTube',
                                'genre': 'murim',
                                'meta': {
                                    'video_id': entry.get('id', {}).get('videoId', ''),
                                    'channel': snippet.get('channelTitle', ''),
                                    'published': snippet.get('publishedAt', ''),
                                },
                            })
                except httpx.HTTPStatusError as e:
                    logger.warning(f'YouTube API error for "{keyword}": {e.response.status_code}')
                except Exception as e:
                    logger.warning(f'YouTube collection error for "{keyword}": {e}')

        logger.info(f'YouTube: collected {len(items)} items')
        return items

    # ── 네이버 웹툰 ──

    async def _collect_naver_webtoon(self) -> List[dict[str, Any]]:
        """네이버 웹툰 인기순 페이지를 크롤링하여 무협 장르 트렌드를 수집합니다."""
        items: List[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # 네이버 웹툰 요일별 인기 API (비공식, JSON 응답)
                resp = await client.get(
                    'https://comic.naver.com/api/webtoon/titlelist/weekday',
                    params={'order': 'ViewCount', 'week': 'dailyPlus'},
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; MurimFactory/1.0)'},
                )
                resp.raise_for_status()
                data = resp.json()

                webtoons = data.get('titleList', data.get('titleListMap', {}).get('dailyPlus', []))
                if isinstance(webtoons, dict):
                    # titleListMap 구조일 경우 모든 요일 합침
                    all_webtoons = []
                    for day_list in webtoons.values():
                        if isinstance(day_list, list):
                            all_webtoons.extend(day_list)
                    webtoons = all_webtoons

                for idx, wt in enumerate(webtoons[:50]):  # 상위 50개만
                    title = wt.get('titleName', wt.get('title', ''))
                    genre = wt.get('genre', wt.get('genreName', ''))

                    # 무협/판타지 장르 필터
                    is_murim = any(g in str(genre) for g in NAVER_WEBTOON_GENRES)
                    if not is_murim and not self._is_murim_keyword(title):
                        continue

                    score = max(90 - idx * 2, 50)  # 순위 기반 점수
                    items.append({
                        'title': title,
                        'trend_score': score,
                        'source': 'Naver',
                        'genre': 'murim',
                        'meta': {
                            'webtoon_id': str(wt.get('titleId', '')),
                            'star_score': wt.get('starScore', 0),
                        },
                    })

            except httpx.HTTPStatusError as e:
                logger.warning(f'Naver Webtoon API error: {e.response.status_code}')
            except Exception as e:
                logger.warning(f'Naver Webtoon collection error: {e}')

        logger.info(f'Naver: collected {len(items)} items')
        return items

    # ── Reddit ──

    async def _collect_reddit(self) -> List[dict[str, Any]]:
        """Reddit에서 무협 관련 인기 포스트를 수집합니다."""
        items: List[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for sub in REDDIT_SUBREDDITS:
                try:
                    resp = await client.get(
                        f'https://www.reddit.com/r/{sub}/hot.json',
                        params={'limit': 25},
                        headers={'User-Agent': 'MurimFactory/1.0'},
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    for post in data.get('data', {}).get('children', []):
                        post_data = post.get('data', {})
                        title = post_data.get('title', '')
                        ups = post_data.get('ups', 0)

                        if not self._is_murim_keyword(title):
                            continue

                        score = min(95, 60 + int(ups / 100))
                        items.append({
                            'title': self._extract_work_title(title),
                            'trend_score': score,
                            'source': 'Reddit',
                            'genre': 'murim',
                            'meta': {
                                'subreddit': sub,
                                'ups': ups,
                                'url': post_data.get('url', ''),
                            },
                        })
                except httpx.HTTPStatusError as e:
                    logger.warning(f'Reddit r/{sub} error: {e.response.status_code}')
                except Exception as e:
                    logger.warning(f'Reddit r/{sub} collection error: {e}')

        logger.info(f'Reddit: collected {len(items)} items')
        return items

    # ══════════════════════════════════════════════
    #  AI 랭킹
    # ══════════════════════════════════════════════

    async def ai_rank_topics(self, raw_data: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """Claude로 최적 리캡 대상 순위 매기기"""
        if self.client is None:
            return self._fallback_rank(raw_data)

        # meta 필드 제거 (직렬화 안전성)
        clean_data = [
            {k: v for k, v in item.items() if k != 'meta'}
            for item in raw_data[:20]  # 상위 20개만 전송
        ]

        prompt = f"""다음 웹툰/만화 트렌드 데이터를 분석하여
유튜브 리캡 영상으로 만들었을 때 가장 조회수가 높을 작품 TOP 5를 추천해줘.

평가 기준:
- 현재 검색량 트렌드 (40%)
- 경쟁 채널의 리캡 유무 (30%)
- 동남아+영어권 인지도 (20%)
- 스토리 리캡 적합성 (10%)

데이터: {json.dumps(clean_data, ensure_ascii=False)}

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

    # ══════════════════════════════════════════════
    #  캐시 & 유틸
    # ══════════════════════════════════════════════

    async def _save_cache(self, data: List[dict[str, Any]]) -> None:
        """수집 결과를 DB trend_cache 테이블에 저장합니다."""
        db = await get_db()
        try:
            await db.execute('''CREATE TABLE IF NOT EXISTS trend_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                trend_score INTEGER DEFAULT 0,
                source TEXT DEFAULT '',
                genre TEXT DEFAULT '',
                meta_json TEXT DEFAULT '{}',
                collected_at TEXT NOT NULL
            )''')
            now = datetime.now(timezone.utc).isoformat()
            for item in data:
                meta = item.get('meta', {})
                await db.execute(
                    '''INSERT INTO trend_cache
                       (title, trend_score, source, genre, meta_json, collected_at)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (
                        item.get('title', ''),
                        int(item.get('trend_score', 0)),
                        item.get('source', ''),
                        item.get('genre', ''),
                        json.dumps(meta, ensure_ascii=False),
                        now,
                    ),
                )
            await db.commit()
            logger.debug(f'Cached {len(data)} trend items')
        except Exception as e:
            logger.error(f'Failed to save trend cache: {e}')
        finally:
            await db.close()

    async def get_cached_trends(self, limit: int = 30) -> List[dict[str, Any]]:
        """최근 캐시된 트렌드 데이터를 반환합니다."""
        db = await get_db()
        try:
            await db.execute('''CREATE TABLE IF NOT EXISTS trend_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                trend_score INTEGER DEFAULT 0,
                source TEXT DEFAULT '',
                genre TEXT DEFAULT '',
                meta_json TEXT DEFAULT '{}',
                collected_at TEXT NOT NULL
            )''')
            async with db.execute(
                '''SELECT DISTINCT title, trend_score, source, genre, meta_json, collected_at
                   FROM trend_cache
                   ORDER BY collected_at DESC, trend_score DESC
                   LIMIT ?''',
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            await db.close()

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

    @staticmethod
    def _prototype_data() -> List[dict[str, Any]]:
        return [
            {'title': '화산귀환 51~100화', 'trend_score': 95, 'source': 'Naver', 'genre': 'murim'},
            {'title': '북검전기 시즌2', 'trend_score': 88, 'source': 'Reddit', 'genre': 'murim'},
            {'title': '나혼렙 시즌3 예고', 'trend_score': 85, 'source': 'MAL', 'genre': 'hunter'},
            {'title': '무림세가 장천재', 'trend_score': 79, 'source': 'Kakao', 'genre': 'murim'},
            {'title': '선협귀환기', 'trend_score': 72, 'source': 'Naver', 'genre': 'regression'},
        ]

    @staticmethod
    def _days_ago_iso(days: int) -> str:
        from datetime import timedelta
        dt = datetime.now(timezone.utc) - timedelta(days=days)
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    @staticmethod
    def _youtube_relevance_score(title: str, keyword: str) -> int:
        """YouTube 제목의 무협 리캡 관련성 점수를 반환합니다."""
        title_lower = title.lower()
        murim_keywords = [
            'murim', 'martial', '무협', '화산', 'mount hua', 'northern blade',
            '북검', 'manhwa', 'recap', '리캡', 'return of', 'regression',
            'reincarnation', '귀환', '회귀', 'cultivat', 'sect',
        ]
        matches = sum(1 for kw in murim_keywords if kw in title_lower)
        if matches == 0:
            return 0
        return min(95, 50 + matches * 10)

    @staticmethod
    def _is_murim_keyword(text: str) -> bool:
        """텍스트에 무협/웹툰 관련 키워드가 포함되어 있는지 확인합니다."""
        text_lower = text.lower()
        keywords = [
            'murim', 'martial', '무협', '무림', '화산', 'mount hua', '북검',
            'northern blade', 'manhwa', '만화', '웹툰', 'reincarnation',
            'regression', '회귀', '귀환', '전생', 'cultivat', 'sect',
            '문파', '강호', '검', 'sword', 'heavenly',
        ]
        return any(kw in text_lower for kw in keywords)

    @staticmethod
    def _extract_work_title(post_title: str) -> str:
        """Reddit 포스트 제목에서 작품명을 추출합니다."""
        # [제거 패턴] 접두사 제거
        import re
        cleaned = re.sub(r'^\[.*?\]\s*', '', post_title)
        # "Chapter xxx" 이후 제거
        cleaned = re.split(r'\s*(?:chapter|ch\.?|ep\.?)\s*\d+', cleaned, flags=re.IGNORECASE)[0]
        return cleaned.strip() or post_title.strip()

    @staticmethod
    def _clean_youtube_title(title: str) -> str:
        """YouTube 제목에서 불필요한 장식을 정리합니다."""
        import re
        cleaned = re.sub(r'\s*[\|\-–—]\s*(?:recap|리캡|explained|요약).*$', '', title, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*\(.*?(?:recap|리캡|part|파트).*?\)\s*$', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip() or title.strip()
