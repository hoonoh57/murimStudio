"""레퍼런스 수집기 – 나무위키/위키피디아에서 작품 정보를 수집하여 AI 스크립트 품질 향상"""

import re
import logging
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# 나무위키 → 한국어 위키피디아 → 영어 위키피디아 순으로 시도
NAMUWIKI_URL = "https://namu.wiki/w/{title}"
KO_WIKI_API = "https://ko.wikipedia.org/api/rest_v1/page/summary/{title}"
EN_WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

# 나무위키 마크업 정리용 정규식
NAMU_CLEANUP_PATTERNS = [
    (r'\[\[파일:.*?\]\]', ''),           # 파일 첨부
    (r'\[\[(.*?\|)?(.*?)\]\]', r'\2'),    # 링크 → 텍스트만
    (r'\{{{.*?\}}}', ''),                 # 문법 블록
    (r'<[^>]+>', ''),                     # HTML 태그
    (r'\[include.*?\]', ''),              # include 문법
    (r'\[목차\]', ''),                    # 목차 태그
    (r'\[각주\]', ''),                    # 각주 태그
    (r'분류\n.*?\n', ''),                 # 분류 라인
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


class ReferenceCollector:
    """작품명으로 줄거리·캐릭터·설정 등 레퍼런스를 수집"""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True)

    async def collect(self, title: str, episode_range: str = "") -> dict:
        """
        여러 소스에서 레퍼런스를 수집하고 통합 dict 반환.
        {
            "title": str,
            "sources": [{"name": "나무위키", "url": str, "content": str}, ...],
            "summary": str,       # 통합 요약 (AI 프롬프트에 삽입할 텍스트)
            "characters": str,    # 등장인물 정보
            "episode_info": str,  # 에피소드/회차 정보
        }
        """
        result = {
            "title": title,
            "sources": [],
            "summary": "",
            "characters": "",
            "episode_info": "",
        }

        # 1) 나무위키
        namu = await self._fetch_namuwiki(title)
        if namu:
            result["sources"].append({
                "name": "나무위키",
                "url": NAMUWIKI_URL.format(title=quote(title, safe="")),
                "content": namu[:8000],  # 토큰 절약: 8000자 제한
            })

        # 2) 나무위키 하위 문서 (등장인물, 줄거리)
        for sub in ["/등장인물", "/줄거리"]:
            sub_content = await self._fetch_namuwiki(title + sub)
            if sub_content:
                result["sources"].append({
                    "name": f"나무위키({sub.strip('/')})",
                    "url": NAMUWIKI_URL.format(title=quote(title + sub, safe="")),
                    "content": sub_content[:6000],
                })

        # 3) 한국어 위키피디아
        ko_wiki = await self._fetch_wikipedia(title, lang="ko")
        if ko_wiki:
            result["sources"].append({
                "name": "한국어 위키피디아",
                "url": ko_wiki.get("url", ""),
                "content": ko_wiki.get("extract", "")[:4000],
            })

        # 4) 영어 위키피디아 (한영 매핑이 필요할 수 있음)
        en_wiki = await self._fetch_wikipedia(title, lang="en")
        if en_wiki:
            result["sources"].append({
                "name": "English Wikipedia",
                "url": en_wiki.get("url", ""),
                "content": en_wiki.get("extract", "")[:4000],
            })

        # 통합 요약 생성
        result["summary"] = self._build_summary(result["sources"])
        result["characters"] = self._extract_characters(result["sources"])
        result["episode_info"] = self._extract_episodes(result["sources"], episode_range)

        logger.info(
            f"[RefCollector] '{title}' 수집 완료: "
            f"{len(result['sources'])}개 소스, "
            f"요약 {len(result['summary'])}자"
        )
        return result

    # ── 나무위키 ──
    async def _fetch_namuwiki(self, title: str) -> Optional[str]:
        url = NAMUWIKI_URL.format(title=quote(title, safe=""))
        try:
            resp = await self._http.get(url)
            if resp.status_code != 200:
                logger.debug(f"[RefCollector] 나무위키 {resp.status_code}: {title}")
                return None
            text = resp.text
            # 나무위키 마크업 정리
            for pattern, repl in NAMU_CLEANUP_PATTERNS:
                text = re.sub(pattern, repl, text, flags=re.DOTALL)
            # 빈 줄 정리
            text = re.sub(r'\n{3,}', '\n\n', text).strip()
            if len(text) < 100:
                return None
            return text
        except Exception as e:
            logger.debug(f"[RefCollector] 나무위키 에러: {e}")
            return None

    # ── 위키피디아 REST API ──
    async def _fetch_wikipedia(self, title: str, lang: str = "ko") -> Optional[dict]:
        api_url = (KO_WIKI_API if lang == "ko" else EN_WIKI_API).format(
            title=quote(title, safe="")
        )
        try:
            resp = await self._http.get(api_url)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get("type") == "disambiguation":
                return None
            return {
                "extract": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            }
        except Exception as e:
            logger.debug(f"[RefCollector] Wikipedia({lang}) 에러: {e}")
            return None

    # ── 통합 요약 ──
    @staticmethod
    def _build_summary(sources: list) -> str:
        parts = []
        for src in sources:
            if src["content"]:
                parts.append(f"[{src['name']}]\n{src['content'][:3000]}")
        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _extract_characters(sources: list) -> str:
        for src in sources:
            if "등장인물" in src["name"]:
                return src["content"][:4000]
        # 본문에서 등장인물 섹션 찾기
        for src in sources:
            content = src["content"]
            match = re.search(r'(?:등장인물|Characters?)(.*?)(?:\n##|\Z)', content, re.DOTALL | re.IGNORECASE)
            if match and len(match.group(1).strip()) > 50:
                return match.group(1).strip()[:4000]
        return ""

    @staticmethod
    def _extract_episodes(sources: list, episode_range: str) -> str:
        """에피소드 범위에 해당하는 회차 정보 추출"""
        if not episode_range:
            return ""
        # "1~50화" → 1, 50
        nums = re.findall(r'\d+', episode_range)
        if len(nums) < 2:
            return ""
        start, end = int(nums[0]), int(nums[1])

        for src in sources:
            content = src["content"]
            lines = content.split('\n')
            relevant = []
            for line in lines:
                # 회차 번호가 포함된 줄 찾기
                ep_nums = re.findall(r'(\d{1,4})(?:~(\d{1,4}))?', line)
                for ep_match in ep_nums:
                    ep_start = int(ep_match[0])
                    ep_end = int(ep_match[1]) if ep_match[1] else ep_start
                    if ep_end >= start and ep_start <= end:
                        relevant.append(line.strip())
                        break
            if relevant:
                return "\n".join(relevant[:50])
        return ""
