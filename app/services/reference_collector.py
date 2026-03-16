"""레퍼런스 수집기 — 나무위키/위키피디아에서 작품 정보를 수집하여 AI 스크립트 품질 향상
   v2: 회차 필터링 정밀화 — 아크 단위 파싱, 범위 밖 데이터 제거"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, List
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

NAMUWIKI_URL = "https://namu.wiki/w/{title}"
KO_WIKI_API  = "https://ko.wikipedia.org/api/rest_v1/page/summary/{title}"
EN_WIKI_API  = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

NAMU_CLEANUP_PATTERNS = [
    (r'\[\[파일:.*?\]\]', ''),
    (r'\[\[(.*?\|)?(.*?)\]\]', r'\2'),
    (r'\{{{.*?\}}}', ''),
    (r'<[^>]+>', ''),
    (r'\[include.*?\]', ''),
    (r'\[목차\]', ''),
    (r'\[각주\]', ''),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# 회차 번호 패턴: "001~005", "046~050", "1016~1025" 등
EP_RANGE_RE = re.compile(r'^(\d{1,4})~(\d{1,4})\s+(.+)$')
# 아크 제목 패턴: 한글로만 이루어지고 숫자가 없는 줄 (예: "은하상단", "화종지회")
ARC_TITLE_RE = re.compile(r'^[가-힣\s,()（）·\-~의]+$')


@dataclass
class Arc:
    """하나의 스토리 아크 (편)"""
    name: str
    ep_start: int = 0
    ep_end: int = 0
    episodes: List[str] = field(default_factory=list)  # "001~005  제목" 형태의 원문

    def overlaps(self, start: int, end: int) -> bool:
        """요청 범위와 이 아크가 겹치는지 확인"""
        if self.ep_start == 0 and self.ep_end == 0:
            return False
        return self.ep_end >= start and self.ep_start <= end

    def filtered_episodes(self, start: int, end: int) -> List[str]:
        """요청 범위 내의 에피소드만 반환"""
        result = []
        for ep_line in self.episodes:
            m = EP_RANGE_RE.match(ep_line.strip())
            if m:
                es, ee = int(m.group(1)), int(m.group(2))
                if ee >= start and es <= end:
                    result.append(ep_line.strip())
            else:
                result.append(ep_line.strip())
        return result


class ReferenceCollector:
    """작품명으로 줄거리·캐릭터·설정 등 레퍼런스를 수집"""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True)

    async def collect(self, title: str, episode_range: str = "") -> dict:
        result = {
            "title": title,
            "sources": [],
            "summary": "",
            "characters": "",
            "episode_info": "",
        }

        # 요청 범위 파싱
        req_start, req_end = self._parse_range(episode_range)

        # 1) 나무위키 본문
        namu_raw = await self._fetch_namuwiki(title)
        if namu_raw:
            result["sources"].append({
                "name": "나무위키",
                "url": NAMUWIKI_URL.format(title=quote(title, safe="")),
                "content": namu_raw[:8000],
            })

        # 2) 나무위키 하위 문서
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

        # 4) 영어 위키피디아
        en_wiki = await self._fetch_wikipedia(title, lang="en")
        if en_wiki:
            result["sources"].append({
                "name": "English Wikipedia",
                "url": en_wiki.get("url", ""),
                "content": en_wiki.get("extract", "")[:4000],
            })

        # ★ 아크 파싱 및 회차 필터링
        arcs = self._parse_arcs(namu_raw or "")
        filtered_arcs = self._filter_arcs(arcs, req_start, req_end)

        # 통합 출력 생성 — 범위 내 정보만 사용
        result["episode_info"] = self._build_episode_info(filtered_arcs, req_start, req_end)
        result["characters"] = self._extract_characters(result["sources"])
        result["summary"] = self._build_filtered_summary(
            result["sources"], filtered_arcs, req_start, req_end
        )

        logger.info(
            f"[RefCollector] '{title}' ({episode_range}) 수집 완료: "
            f"{len(result['sources'])}개 소스, "
            f"{len(arcs)}개 아크 중 {len(filtered_arcs)}개 해당, "
            f"요약 {len(result['summary'])}자"
        )
        return result

    # ──────────────────────────────────────────────
    #  아크(편) 파싱 — 나무위키 에피소드 목록 구조 분석
    # ──────────────────────────────────────────────
    @staticmethod
    def _parse_arcs(raw_text: str) -> List[Arc]:
        """나무위키 본문에서 아크 단위로 에피소드를 파싱"""
        arcs = []
        current_arc = Arc(name="(프롤로그)")
        lines = raw_text.split('\n')

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # 에피소드 범위 줄인지 확인 (예: "001~005  서(序)...")
            ep_match = EP_RANGE_RE.match(stripped)
            if ep_match:
                es, ee = int(ep_match.group(1)), int(ep_match.group(2))
                current_arc.episodes.append(stripped)
                if current_arc.ep_start == 0 or es < current_arc.ep_start:
                    current_arc.ep_start = es
                if ee > current_arc.ep_end:
                    current_arc.ep_end = ee
                continue

            # 아크 제목인지 확인 (한글만, 숫자 없음, 4자 이상)
            if (ARC_TITLE_RE.match(stripped)
                    and len(stripped) >= 2
                    and not stripped.startswith('회차')
                    and stripped not in ('제목',)):
                # 이전 아크 저장
                if current_arc.episodes:
                    arcs.append(current_arc)
                current_arc = Arc(name=stripped)
                continue

        # 마지막 아크 저장
        if current_arc.episodes:
            arcs.append(current_arc)

        return arcs

    @staticmethod
    def _filter_arcs(arcs: List[Arc], start: int, end: int) -> List[Arc]:
        """요청 범위와 겹치는 아크만 필터링"""
        if start == 0 and end == 0:
            return arcs  # 범위 미지정 시 전체 반환
        return [arc for arc in arcs if arc.overlaps(start, end)]

    @staticmethod
    def _parse_range(episode_range: str) -> tuple:
        """'1~50화' → (1, 50), '' → (0, 0)"""
        if not episode_range:
            return (0, 0)
        nums = re.findall(r'\d+', episode_range)
        if len(nums) >= 2:
            return (int(nums[0]), int(nums[1]))
        elif len(nums) == 1:
            n = int(nums[0])
            return (n, n)
        return (0, 0)

    # ──────────────────────────────────────────────
    #  필터링된 요약 생성
    # ──────────────────────────────────────────────
    @staticmethod
    def _build_episode_info(arcs: List[Arc], start: int, end: int) -> str:
        """필터링된 아크의 에피소드 정보를 구조화된 텍스트로 생성"""
        if not arcs:
            return ""
        parts = []
        for arc in arcs:
            eps = arc.filtered_episodes(start, end) if (start or end) else arc.episodes
            if eps:
                parts.append(f"\n■ {arc.name} (소설 {arc.ep_start}~{arc.ep_end}화)")
                for ep in eps:
                    parts.append(f"  {ep}")
        return "\n".join(parts)

    @staticmethod
    def _build_filtered_summary(sources: list, filtered_arcs: List[Arc],
                                start: int, end: int) -> str:
        """범위 내 아크 이름을 명시하고, 범위 밖 정보는 제외하는 요약 생성"""
        parts = []

        # 1) 범위 안내
        if filtered_arcs:
            arc_names = [a.name for a in filtered_arcs]
            parts.append(
                f"[스크립트 대상 범위: {start}~{end}화]\n"
                f"해당 아크: {', '.join(arc_names)}\n"
                f"⚠ 이 범위 밖의 내용(예: {end+1}화 이후)은 스크립트에 포함하지 마세요."
            )

        # 2) 소스 요약 — 범위 밖 아크명을 경고로 표시
        exclude_arcs = []
        for src in sources:
            content = src["content"]
            # 범위 밖 아크를 제거하거나 축약
            if start > 0 and end > 0:
                content = ReferenceCollector._trim_content_to_range(content, start, end)
            if content:
                parts.append(f"[{src['name']}]\n{content[:3000]}")

        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _trim_content_to_range(content: str, start: int, end: int) -> str:
        """본문에서 범위 밖 에피소드 라인을 제거"""
        lines = content.split('\n')
        filtered = []
        skip_section = False

        for line in lines:
            stripped = line.strip()
            # 에피소드 라인이면 범위 체크
            ep_match = EP_RANGE_RE.match(stripped)
            if ep_match:
                es, ee = int(ep_match.group(1)), int(ep_match.group(2))
                if ee < start or es > end:
                    continue  # 범위 밖 에피소드 제거
                else:
                    skip_section = False
                    filtered.append(line)
                    continue

            # 아크 제목이면 일단 포함 (다음 에피소드에서 판단)
            if ARC_TITLE_RE.match(stripped) and len(stripped) >= 2:
                filtered.append(line)
                continue

            # 일반 텍스트는 포함
            if not skip_section:
                filtered.append(line)

        return '\n'.join(filtered)

    # ──────────────────────────────────────────────
    #  캐릭터 추출
    # ──────────────────────────────────────────────
    @staticmethod
    def _extract_characters(sources: list) -> str:
        for src in sources:
            if "등장인물" in src["name"]:
                return src["content"][:4000]
        for src in sources:
            content = src["content"]
            match = re.search(
                r'(?:등장인물|Characters?)(.*?)(?:\n##|\Z)',
                content, re.DOTALL | re.IGNORECASE
            )
            if match and len(match.group(1).strip()) > 50:
                return match.group(1).strip()[:4000]
        return ""

    # ──────────────────────────────────────────────
    #  나무위키 / 위키피디아 페치
    # ──────────────────────────────────────────────
    async def _fetch_namuwiki(self, title: str) -> Optional[str]:
        url = NAMUWIKI_URL.format(title=quote(title, safe=""))
        try:
            resp = await self._http.get(url)
            if resp.status_code != 200:
                logger.debug(f"[RefCollector] 나무위키 {resp.status_code}: {title}")
                return None
            text = resp.text
            for pattern, repl in NAMU_CLEANUP_PATTERNS:
                text = re.sub(pattern, repl, text, flags=re.DOTALL)
            text = re.sub(r'\n{3,}', '\n\n', text).strip()
            if len(text) < 100:
                return None
            return text
        except Exception as e:
            logger.debug(f"[RefCollector] 나무위키 에러: {e}")
            return None

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
