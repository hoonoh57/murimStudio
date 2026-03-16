"""레퍼런스 수집기 v3 — 위키피디아 REST API 기반 + 에피소드 아크 정밀 필터링
   
   데이터 소스:
   1. 영문 위키피디아 rest_v1/page/summary  — 줄거리 요약
   2. 영문 위키피디아 rest_v1/page/html     — 캐릭터·상세 (HTML→텍스트 변환)
   3. 한국어 위키피디아 rest_v1/page/summary — 있으면 사용
   4. 한국어/영문 작품명 매핑 테이블        — 위키피디아 검색용
"""

import re
import logging
from html.parser import HTMLParser
from typing import Optional, List
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  작품명 → 위키피디아 제목 매핑
# ──────────────────────────────────────────────
TITLE_MAP = {
    "화산귀환": "Return_of_the_Blossoming_Blade",
    "나 혼자만 레벨업": "Solo_Leveling",
    "전지적 독자 시점": "Omniscient_Reader%27s_Viewpoint",
    "재혼 황후": "The_Remarried_Empress",
    "외모지상주의": "Lookism",
    "갓 오브 하이스쿨": "The_God_of_High_School",
    "노블레스": "Noblesse_(manhwa)",
    "신의 탑": "Tower_of_God",
    "바른연애 길잡이": "A_Guide_to_Proper_Dating",
    "템빨": "Overgeared_(web_novel)",
}

# ──────────────────────────────────────────────
#  아크(편) 에피소드 DB — 나무위키 데이터 기반 오프라인 매핑
#  나무위키 Cloudflare 차단 대응: 주요 작품 에피소드 구조를 내장
# ──────────────────────────────────────────────
EPISODE_ARCS = {
    "화산귀환": [
        {"name": "매화검존, 100년 후의 환생", "start": 1, "end": 45,
         "summary": "매화검존 청명이 천마를 베고 100년 뒤 아이의 몸으로 환생. 몰락한 화산파 발견, 제자들(윤종·조걸·백천·유이설) 훈련 시작, 종남파와 충돌",
         "episodes": [
             "001~005 서(序), 이게 뭐가 어떻게 돌아가는 상황이야?",
             "006~010 세상에, 화산이 망하네.",
             "011~015 파산이 가당키나 하냐, 이놈들아!",
             "016~020 화산이 박살이 난 게 나 때문이라고?",
             "021~025 종남에서 오셨습니까?",
             "026~030 화산이 복덩이를 얻었구나.",
             "031~035 너 이 새끼? 종남파 놈이냐?",
             "036~040 거지도 안 주워 갈 문파 같으니!",
             "041~045 화산이기 때문입니다.",
         ]},
        {"name": "은하상단", "start": 46, "end": 65,
         "summary": "화산파 재정난 해결 위해 은하상단과 거래 시도. 청명의 재능이 드러나며 '재신(財神)' 별명 획득",
         "episodes": [
             "046~050 잘못되더라도 원망 마시고.",
             "051~055 하핫, 뭐 대단한 사람 오셨다고.",
             "056~060 소도장은 정말 도사인가?",
             "061~065 장문인! 저놈은 재신(財神)입니다!",
         ]},
        {"name": "화종지회", "start": 66, "end": 115,
         "summary": "화산파 제자들이 화종지회 비무대회에 참가. 치열한 대련을 통해 실력 증명, 화산파의 존재를 강호에 알림",
         "episodes": [
             "066~070 걱정하지 마! 내가 이기게 해 줄 테니까!",
             "071~075 화산이 뭔가 달라진 것 같은데.",
             "076~080 구르는 사람에겐 이끼가 끼지 않아!",
             "081~085 누가 비무래? 넌 이제 뒈졌다.",
             "086~090 뭔 개소리야. 내가 제일 세지!",
             "091~095 저 새끼들한테 지면 다 뒈지는 거야.",
             "096~100 별것도 아닌 게 깝치고 있어.",
             "101~105 영원히 잊지 못할 날을 만들어 주지.",
             "106~110 화산은 사라지지 않는다.",
             "111~115 네가 화산의 제자라면 그걸로 됐다.",
         ]},
        {"name": "화영문", "start": 116, "end": 135,
         "summary": "화영문 세력과의 갈등. 화산파의 검이 강호에 이름을 알리기 시작",
         "episodes": [
             "116~120 언젠가는 천하에 매화가 피어나리라.",
             "121~125 화산을 건드리면 어떻게 되는지 알려 주지!",
             "126~130 화산의 검은 강하다.",
             "131~135 내 일은 이제 시작이야!",
         ]},
        {"name": "검총, 약선의 무덤", "start": 136, "end": 170,
         "summary": "오검(청명·백천·윤종·조걸·유이설)이 검총과 약선의 무덤을 탐험. 무당파와의 긴장, 동료애 성장",
         "episodes": [
             "136~140 이건 죽어도 내가 먹어야 해!",
             "141~145 당신, 나랑 일 하나 같이 합시다.",
             "146~150 내 물건 건드리는 놈들은 다 뒈지는 거야!",
             "151~155 진짜 무정함이 뭔지 알려 주지.",
             "156~160 이제 무당 놈들 잡으러 가자!",
             "161~165 아니! 해도 해도 너무하잖아!",
             "165~170 그래도 나는 함께 걸어간다.",
         ]},
        {"name": "운남행", "start": 171, "end": 185,
         "summary": "운남으로 이동하며 겪는 사건들. 혼원단 복용 전 여정",
         "episodes": [
             "171~175 처맞으면 비키게 되어 있어!",
             "176~180 속 터져 죽는 것보다는 낫잖습니까.",
             "181~185 어머나, 세상에. 이게 뭔 일이야.",
         ]},
        {"name": "사천당가", "start": 186, "end": 215,
         "summary": "사천당가 방문. 당가의 독과 암기 문화 체험, 새로운 동맹 형성",
         "episodes": [
             "186~190 그 실력으로 말입니까?",
             "191~195 갑자기 너무 거물이 나오시는데?",
             "196~200 억울하면 너도 살아나든가.",
             "201~205 그냥 제 변덕이라고 해 두죠.",
             "206~210 조상님의 회초리는 좀 아픈 법이거든.",
             "211~215 잘 가게나, 친구들.",
         ]},
        {"name": "남만야수궁", "start": 216, "end": 240,
         "summary": "남만야수궁에서의 모험과 위기",
         "episodes": [
             "216~221 지금 화산이라 했느냐?",
             "222~225 왜 너희가 그걸 모르느냐?",
             "226~230 뭔 놈의 연못에 용이 살아!",
             "231~235 그쪽이 왜 그러세요?",
             "236~240 여기가 지옥이구나.",
         ]},
        {"name": "혼원단 제조", "start": 241, "end": 255,
         "summary": "혼원단 제조 과정과 그로 인한 위기",
         "episodes": [
             "241~245 이렇게 아낌없이 주시다니!",
             "246~250 아직은 그리 말하지 마라.",
             "251~255 내가 내 무덤을 팠구나.",
         ]},
        {"name": "천하제일 비무대회", "start": 256, "end": 350,
         "summary": "천하제일 비무대회 참가. 화산파 제자들이 정파 문파들과 겨루며 명성 확립, 청명이 삼대제자임을 드러냄",
         "episodes": [
             "256~260 뭐가 열린다고?",
             "261~265 아니, 근데 저 새끼들이?",
             "266~270 진짜 사고가 뭔지 보여 줘?",
             "271~275 명문은 대가리가 없대?",
             "276~280 저는 화산의 장문인이 될 사람입니다.",
             "281~285 인생은 원래 불공평한 거야.",
             "286~290 끝은 또 다른 시작이지.",
             "291~295 나는 여전히 너의 벽이다.",
             "296~300 네가 불씨가 될 수 있을까?",
             "347~350 내가 화산의 삼대제자 청명이시다.",
         ]},
        {"name": "화영문의 서안 이주", "start": 351, "end": 385,
         "summary": "화영문이 서안으로 이주하며 벌어지는 사건들"},
        {"name": "만인방의 화산 침공", "start": 386, "end": 415,
         "summary": "만인방이 화산을 침공. 화산파 사활을 건 방어전"},
        {"name": "만년한철 매화검", "start": 416, "end": 450,
         "summary": "청명의 검술이 한 단계 성장하는 과정"},
        {"name": "북해빙궁, 마교의 발호", "start": 451, "end": 555,
         "summary": "북해빙궁 방문과 마교 세력 확장에 대응"},
        {"name": "녹림왕의 방문, 녹림채 반란 진압", "start": 556, "end": 605,
         "summary": "녹림채 반란 진압 작전"},
        {"name": "무당과의 비무", "start": 606, "end": 655,
         "summary": "무당파와의 공식 비무. 화산파의 검술을 증명"},
        {"name": "천우맹 개파식", "start": 656, "end": 690,
         "summary": "천우맹(정파 연합) 결성. 화산파가 중심이 됨"},
        {"name": "청진의 유해, 그리고 화산으로의 귀환", "start": 691, "end": 725,
         "summary": "청진의 유해를 찾아 화산으로 귀환"},
        {"name": "장강수로십팔채, 장강참변", "start": 741, "end": 845,
         "summary": "장강에서 벌어지는 대규모 전투"},
        {"name": "화산파 봉문", "start": 846, "end": 915,
         "summary": "화산파 봉문(폐쇄) 수련기"},
        {"name": "매화도 참변, 남궁세가 구출", "start": 916, "end": 985,
         "summary": "매화도 참변 사건과 남궁세가 구출 작전"},
        {"name": "남궁세가, 천우맹 합류", "start": 986, "end": 1015,
         "summary": "남궁세가가 천우맹에 합류"},
        {"name": "항주마화", "start": 1016, "end": 1090,
         "summary": "항주에서 벌어지는 마화(魔禍) 사건"},
        {"name": "천우맹 공동 수련", "start": 1091, "end": 1150,
         "summary": "천우맹 소속 문파들의 합동 수련"},
        {"name": "정사대전", "start": 1526, "end": 1650,
         "summary": "정파와 사파의 대전쟁"},
    ],
}

# ──────────────────────────────────────────────
#  HTML → 텍스트 변환기
# ──────────────────────────────────────────────
class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'sup', 'link', 'meta'):
            self._skip = True
        elif tag in ('p', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'tr'):
            self._parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'sup', 'link', 'meta'):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        text = ''.join(self._parts)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        return text.strip()


def html_to_text(html: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


# ──────────────────────────────────────────────
#  메인 클래스
# ──────────────────────────────────────────────
class ReferenceCollector:
    """작품명으로 줄거리·캐릭터·설정 등 레퍼런스를 수집 (회차 정밀 필터링)"""

    USER_AGENT = "MurimStudio/1.0 (contact@example.com)"

    def __init__(self):
        self._http = httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": self.USER_AGENT},
            follow_redirects=True,
        )

    async def collect(self, title: str, episode_range: str = "") -> dict:
        result = {
            "title": title,
            "sources": [],
            "summary": "",
            "characters": "",
            "episode_info": "",
        }

        req_start, req_end = self._parse_range(episode_range)

        # 1) 위키피디아 (영문)
        en_slug = TITLE_MAP.get(title, "")
        if en_slug:
            summary_data = await self._wiki_summary(en_slug, "en")
            if summary_data:
                result["sources"].append({
                    "name": "English Wikipedia (summary)",
                    "url": summary_data.get("url", ""),
                    "content": summary_data.get("extract", ""),
                })
            html_text = await self._wiki_html(en_slug, "en")
            if html_text:
                result["sources"].append({
                    "name": "English Wikipedia (full)",
                    "url": f"https://en.wikipedia.org/wiki/{en_slug}",
                    "content": html_text[:12000],
                })
        else:
            # 매핑이 없으면 제목 그대로 시도
            for lang in ("en", "ko"):
                slug = quote(title, safe="")
                summary_data = await self._wiki_summary(slug, lang)
                if summary_data:
                    result["sources"].append({
                        "name": f"Wikipedia/{lang} (summary)",
                        "url": summary_data.get("url", ""),
                        "content": summary_data.get("extract", ""),
                    })
                    break

        # 2) 내장 아크 데이터 (나무위키 대체)
        arcs = EPISODE_ARCS.get(title, [])
        filtered_arcs = [
            a for a in arcs
            if self._arc_overlaps(a, req_start, req_end)
        ] if (req_start or req_end) else arcs

        if filtered_arcs:
            result["sources"].append({
                "name": "에피소드 아크 DB",
                "url": "",
                "content": self._format_arcs(filtered_arcs, req_start, req_end),
            })

        # 3) 조합
        result["episode_info"] = self._build_episode_info(filtered_arcs, req_start, req_end)
        result["characters"] = self._extract_characters(result["sources"])
        result["summary"] = self._build_summary(result["sources"], filtered_arcs, req_start, req_end)

        logger.info(
            f"[RefCollector] '{title}' ({episode_range}) 수집 완료: "
            f"{len(result['sources'])}개 소스, "
            f"전체 {len(arcs)}개 아크 중 {len(filtered_arcs)}개 해당, "
            f"요약 {len(result['summary'])}자"
        )
        return result

    # ──────────────────────────────────────────
    #  위키피디아 API
    # ──────────────────────────────────────────
    async def _wiki_summary(self, slug: str, lang: str = "en") -> Optional[dict]:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{slug}"
        try:
            resp = await self._http.get(url)
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
            logger.debug(f"[RefCollector] Wiki summary({lang}) 에러: {e}")
            return None

    async def _wiki_html(self, slug: str, lang: str = "en") -> Optional[str]:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/html/{slug}"
        try:
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return None
            return html_to_text(resp.text)
        except Exception as e:
            logger.debug(f"[RefCollector] Wiki html({lang}) 에러: {e}")
            return None

    # ──────────────────────────────────────────
    #  아크 필터링
    # ──────────────────────────────────────────
    @staticmethod
    def _arc_overlaps(arc: dict, start: int, end: int) -> bool:
        if start == 0 and end == 0:
            return True
        a_start = arc.get("start", 0)
        a_end = arc.get("end", 0)
        return a_end >= start and a_start <= end

    @staticmethod
    def _parse_range(episode_range: str) -> tuple:
        if not episode_range:
            return (0, 0)
        nums = re.findall(r'\d+', episode_range)
        if len(nums) >= 2:
            return (int(nums[0]), int(nums[1]))
        elif len(nums) == 1:
            n = int(nums[0])
            return (n, n)
        return (0, 0)

    # ──────────────────────────────────────────
    #  출력 포맷팅
    # ──────────────────────────────────────────
    @staticmethod
    def _format_arcs(arcs: list, start: int, end: int) -> str:
        parts = []
        for arc in arcs:
            parts.append(f"\n■ {arc['name']} (소설 {arc['start']}~{arc['end']}화)")
            if arc.get("summary"):
                parts.append(f"  줄거리: {arc['summary']}")
            for ep in arc.get("episodes", []):
                # 에피소드 범위 필터링
                m = re.match(r'(\d+)~(\d+)', ep)
                if m:
                    es, ee = int(m.group(1)), int(m.group(2))
                    if (start and end) and (ee < start or es > end):
                        continue
                parts.append(f"  {ep}")
        return "\n".join(parts)

    @staticmethod
    def _build_episode_info(arcs: list, start: int, end: int) -> str:
        if not arcs:
            return ""
        parts = []
        for arc in arcs:
            parts.append(f"■ {arc['name']} ({arc['start']}~{arc['end']}화): {arc.get('summary', '')}")
            for ep in arc.get("episodes", []):
                m = re.match(r'(\d+)~(\d+)', ep)
                if m:
                    es, ee = int(m.group(1)), int(m.group(2))
                    if (start and end) and (ee < start or es > end):
                        continue
                parts.append(f"  {ep}")
        return "\n".join(parts)

    @staticmethod
    def _build_summary(sources: list, arcs: list, start: int, end: int) -> str:
        parts = []

        # 범위 경고
        if start > 0 and end > 0:
            arc_names = [a["name"] for a in arcs]
            parts.append(
                f"[스크립트 대상 범위: {start}~{end}화]\n"
                f"해당 아크: {', '.join(arc_names)}\n"
                f"⚠ 반드시 이 범위({start}~{end}화)의 내용만 다루세요.\n"
                f"⚠ {end+1}화 이후의 사건·인물·설정은 절대 포함하지 마세요.\n"
                f"⚠ 특히 '천우맹', '정사대전' 등 후반부 아크는 언급 금지입니다."
            )

        # 소스 추가
        for src in sources:
            if src["content"]:
                parts.append(f"[{src['name']}]\n{src['content'][:4000]}")

        return "\n\n---\n\n".join(parts)

    @staticmethod
    def _extract_characters(sources: list) -> str:
        """위키피디아 HTML 본문에서 캐릭터 섹션 추출"""
        for src in sources:
            content = src.get("content", "")
            # "Cheongmyeong" 등 캐릭터명 주변 텍스트 추출
            char_patterns = [
                r'(Cheongmyeong.*?)(?:\n\n|\Z)',
                r'(Yunjong.*?)(?:\n\n|\Z)',
                r'(Jo Gul.*?)(?:\n\n|\Z)',
                r'(Yoo Iseol.*?)(?:\n\n|\Z)',
                r'(Baek Cheon.*?)(?:\n\n|\Z)',
            ]
            chars = []
            for pattern in char_patterns:
                match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if match:
                    text = match.group(1).strip()[:800]
                    chars.append(text)
            if chars:
                return "\n\n".join(chars)
        return ""
