"""스크립트 공장 — 숏츠/롱폼 분기, 장르 선택, 캐릭터 보호, 멀티 프롬프트 (v1.7.2)"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional, List

from app.db import get_db
from app.services.llm_client import get_llm_client, has_llm_client
from app.services.reference_collector import ReferenceCollector
from app.services.utils import log_llm_cost

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════
#  롱폼 시스템 프롬프트
# ══════════════════════════════════════════════════
SYSTEM_PROMPT_LONG = """당신은 웹툰/웹소설 유튜브 리캡 전문 작가입니다.

⚠️ 최우선 규칙 (절대 위반 금지):
- 참고 자료에 제공된 캐릭터명·성별·외모·관계를 절대 변경하지 마세요
- 이름의 성(姓)과 이름을 정확히 사용하세요 (예: 청명은 청명, 매화검존은 매화검존)
- 캐릭터 성별을 바꾸거나 다른 캐릭터와 합치지 마세요
- 원작에 없는 캐릭터를 추가하지 마세요
- 이미지 프롬프트에 캐릭터 묘사 시 반드시 성별(male/female), 나이대, 외모 특징을 영어로 명시하세요

나레이션 작성 규칙:
- 나레이션 본문에는 한국어만 사용하세요
- 고유명사의 외국어 병기는 나레이션에 절대 포함하지 마세요
  ✗ 틀린 예: "화산파(Mount Hua Sect)가 무림을 장악했다"
  ✓ 맞는 예: "화산파가 무림을 장악했다"
- 외국어 병기가 필요한 경우 별도의 [번역 주석] 태그를 사용하세요
  예: [번역 주석: 화산파=Mount Hua Sect, 매화검법=Plum Blossom Sword Art]
- 나레이션은 자연스러운 구어체 한국어로만 작성

스크립트 구조 규칙:
1. 첫 5초 안에 가장 충격적인 장면으로 시작 (훅)
2. 매 2분마다 서스펜스 포인트를 배치하여 이탈 방지
3. 각 장면마다 아래 태그를 반드시 포함:
   - [이미지 프롬프트: 영어로 Midjourney용 프롬프트, 16:9 가로 구도, 캐릭터 성별/외모 명시]
   - [BGM: 분위기 키워드]
   - [SFX: 효과음 키워드] (필요시)
   - [자막: 자막 스타일 지시] (필요시)
   - [번역 주석: 용어=English] (해당 장면의 고유명사 번역, 나레이션 밖에 배치)
4. 마지막 10초는 다음 영상으로 유도하는 클리프행어
5. 대사를 직접 인용할 때는 큰따옴표 사용

출력 형식:
[HOOK - 0:00~0:05]
[이미지 프롬프트: epic dramatic opening scene, young male martial artist with black long hair, 16:9]
[BGM: tension_building]
[번역 주석: 화산파=Mount Hua Sect]
(충격적 오프닝 나레이션 — 한국어만)

[SCENE 1 - 0:05~2:00]
[이미지 프롬프트: ...]
[BGM: ...]
[SFX: ...]
[번역 주석: ...]
(내레이션 본문 — 한국어만, 괄호 영어 설명 금지)

... (장면 반복) ...

[OUTRO - 마지막 10초]
[이미지 프롬프트: ...]
[BGM: ...]
(다음 영상 유도 클리프행어)
"""

# ══════════════════════════════════════════════════
#  숏츠 시스템 프롬프트
# ══════════════════════════════════════════════════
SYSTEM_PROMPT_SHORTS = """당신은 15~30초 YouTube Shorts 전문 작가입니다.
바이럴 숏츠의 핵심: 첫 1.5초 = 결과/충격 먼저, 루프 구조, 임팩트 나레이션.

⚠️ 최우선 규칙 (절대 위반 금지):
- 참고 자료에 제공된 캐릭터명·성별·외모·관계를 절대 변경하지 마세요
- 이름의 성(姓)과 이름을 정확히 사용하세요
- 캐릭터 성별을 바꾸거나 다른 캐릭터와 합치지 마세요
- 이미지 프롬프트에 캐릭터 묘사 시 반드시 성별(male/female), 나이대, 외모 특징을 영어로 명시하세요

나레이션 작성 규칙:
- 나레이션 본문에는 순수 한국어만 사용 (괄호 영어 설명 금지)
  ✗ 틀린 예: "화산파(Mount Hua Sect)의 장문인이"
  ✓ 맞는 예: "화산파의 장문인이"
- 외국어 병기가 필요하면 [번역 주석] 태그를 별도 줄에 작성
- 나레이션은 짧고 임팩트 있게, 6학년 수준 어휘, 문장당 15자 이내 권장

숏츠 구조 규칙:
1. 총 나레이션 150~250자 (한국어 기준)
2. 이미지는 세로(9:16) 클로즈업 구도 — 3~5장이 최적
3. 각 섹션마다 아래 태그를 반드시 모두 포함:
   - [이미지 프롬프트: 영어, vertical composition, close-up, 9:16, 캐릭터 성별/외모 명시]
   - [BGM: 분위기 키워드]
   - [SFX: 효과음 키워드]
   - [자막: 크기/위치/강조 지시]
   - [영상: Ken Burns 효과 지시]
   - [번역 주석: 용어=English] (필요시)
4. 훅에는 반드시 화면에 표시할 텍스트를 큰따옴표로 작성
5. CTA는 마지막 2~3초, 구독/좋아요 유도
6. 시간 제어문에 초 단위 명시: [HOOK - 0~1.5초], [PROBLEM - 1.5~10초] 등

출력 형식 (반드시 이 구조):

[HOOK - 0~1.5초]
[이미지 프롬프트: vertical close-up, young male martial artist with black hair, shocked expression, dark background, 9:16 mobile]
[BGM: dramatic_impact]
[SFX: whoosh]
[자막: 큰 글씨 중앙, 노란색 강조]
[영상: zoom_center]
[번역 주석: 화산파=Mount Hua Sect]
"화면 표시 훅 텍스트"
충격적 한 줄 나레이션 (한국어만)

[PROBLEM - 1.5~10초]
[이미지 프롬프트: ...]
[BGM: ...]
[SFX: ...]
[자막: ...]
[영상: ...]
문제/갈등 나레이션 (한국어만, 3~5문장)

[SOLUTION - 10~25초]
[이미지 프롬프트: ...]
[BGM: ...]
[SFX: ...]
[자막: ...]
[영상: ...]
해결/전개 나레이션 (한국어만, 3~5문장)

[CTA - 마지막 3초]
[이미지 프롬프트: ...]
[BGM: upbeat_ending]
[SFX: notification_bell]
[자막: 큰 글씨 중앙]
[영상: zoom_out]
"이 다음이 진짜 충격이다. 구독 꾹!"
"""

# ══════════════════════════════════════════════════
#  장르별 추가 지시
# ══════════════════════════════════════════════════
GENRE_INSTRUCTIONS = {
    "wuxia": "무협/무림 세계관. 검술, 내공, 파벌 갈등 중심. 이미지는 동양 판타지 무협 스타일. 무림 용어는 나레이션에서 한국어만 사용하고, [번역 주석] 태그에 영어 병기.",
    "anime": "애니/웹툰 스타일. 밝고 생동감 있는 캐릭터 중심. 이미지는 일본 애니메이션 풍.",
    "fantasy": "판타지 세계관. 마법, 던전, 레벨업 요소. 이미지는 에픽 판타지 스타일. 판타지 용어는 나레이션에서 한국어만 사용.",
    "romance": "로맨스 중심. 감성적 톤, 따뜻한 분위기. 이미지는 부드러운 파스텔톤.",
    "action": "액션/배틀 중심. 강렬한 동작, 긴장감. 이미지는 다이나믹 구도.",
    "comedy": "코미디/일상. 밝고 유머러스. 이미지는 밝은 컬러, 재미있는 표정.",
    "horror": "호러/스릴러. 어둡고 불안한 분위기. 이미지는 어두운 색감, 공포 연출.",
    "neutral": "장르 특화 없음. 콘텐츠에 맞는 일반적 스타일.",
}


class ScriptFactory:
    def __init__(self):
        self.llm = get_llm_client()
        self.ref_collector = ReferenceCollector()
        if self.llm is None:
            logger.warning('No LLM API key — ScriptFactory will use placeholder')

    # ──────────────────────────────────────────────
    #  스크립트 생성 (숏츠/롱폼 분기)
    # ──────────────────────────────────────────────
    async def generate_script(
        self,
        title: str,
        episodes: str = '',
        duration_min: int = 10,
        style: str = '긴장감+감동',
        language: str = 'ko',
        project_id: Optional[int] = None,
        format: str = 'long',
        genre: str = 'neutral',
        target_duration: int = 0,
    ) -> dict[str, Any]:

        # 포맷에 따라 시스템 프롬프트 선택
        if format == 'shorts':
            system_prompt = SYSTEM_PROMPT_SHORTS
            if target_duration <= 0:
                target_duration = 30
            word_count = target_duration * 5  # 숏츠: 초당 ~5자
        else:
            system_prompt = SYSTEM_PROMPT_LONG
            if target_duration <= 0:
                target_duration = duration_min * 60
            word_count = duration_min * 150

        # 장르 추가 지시
        genre_instruction = GENRE_INSTRUCTIONS.get(genre, GENRE_INSTRUCTIONS["neutral"])

        # ★ 레퍼런스 자동 수집
        reference_block = ""
        try:
            ref_data = await self.ref_collector.collect(title, episodes)
            if ref_data["summary"]:
                parts = []
                parts.append("=== 참고 자료 (실제 작품 정보 — 반드시 이 정보를 기반으로 작성) ===")
                parts.append(ref_data["summary"][:6000])
                if ref_data["characters"]:
                    parts.append("\n=== 등장인물 (이름·성별·외모를 절대 변경하지 마세요) ===")
                    parts.append(ref_data["characters"][:2000])
                if ref_data["episode_info"]:
                    parts.append(f"\n=== 해당 회차 정보 ({episodes}) ===")
                    parts.append(ref_data["episode_info"][:2000])
                parts.append(f"\n위 참고 자료의 실제 캐릭터명·사건·줄거리를 정확히 반영하세요.")
                parts.append(f"참고 자료에 없는 허구의 인물·기술명·사건을 만들지 마세요.")
                parts.append(f"⚠ 반드시 {episodes} 범위의 내용만 다루세요. 이후 회차 내용은 절대 포함하지 마세요.")
                parts.append(f"⚠ 나레이션에 괄호 영어 설명을 넣지 마세요. [번역 주석] 태그를 사용하세요.")
                reference_block = "\n".join(parts)
                logger.info(f'[ScriptFactory] 레퍼런스 {len(ref_data["sources"])}개 소스 수집 완료')
        except Exception as e:
            logger.warning(f'[ScriptFactory] 레퍼런스 수집 실패 (무시하고 계속): {e}')

        # 포맷별 프롬프트
        if format == 'shorts':
            prompt = f"""작품: {title}
회차 범위: {episodes if episodes else '전체'}
장르: {genre_instruction}
목표 길이: {target_duration}초 (약 {word_count}자)
스타일: {style}
언어: {language}

{reference_block}

위 작품의 YouTube Shorts 스크립트를 작성해주세요.
반드시 [이미지 프롬프트], [BGM], [SFX], [자막], [영상] 태그를 각 섹션에 포함하세요.
나레이션은 {word_count}자 이내, 순수 한국어만 사용, 괄호 영어 설명 금지.
고유명사 번역이 필요하면 [번역 주석: 용어=English] 태그를 별도 줄에 작성하세요."""
        else:
            prompt = f"""작품: {title}
회차 범위: {episodes if episodes else '전체'}
장르: {genre_instruction}
목표 길이: {duration_min}분 (약 {word_count}단어)
스타일: {style}
언어: {language}

{reference_block}

위 작품의 유튜브 리캡 영상 스크립트를 작성해주세요.
반드시 [이미지 프롬프트], [BGM] 태그를 각 장면에 포함하세요.
나레이션은 순수 한국어만 사용, 괄호 안 영어 설명 금지.
고유명사 번역이 필요하면 [번역 주석: 용어=English] 태그를 별도 줄에 작성하세요."""

        script_text = ''
        cost_usd = 0.0
        status = 'generated'

        if self.llm is not None:
            try:
                resp = await self.llm.generate(
                    prompt=prompt, system=system_prompt,
                    max_tokens=4096, temperature=0.3,
                )
                script_text = resp.text
                cost_usd = await log_llm_cost(
                    resp, action='script_generate',
                    project_id=str(project_id) if project_id else '',
                )
                logger.info(
                    f'Script generated ({format}/{genre}) via {resp.provider}/{resp.model} '
                    f'for "{title}" — ${cost_usd:.6f}'
                )
            except Exception as e:
                logger.error(f'Script generation failed: {e}')
                status = 'error'
        else:
            if format == 'shorts':
                script_text = self._placeholder_shorts(title, episodes, target_duration)
            else:
                script_text = self._placeholder_script(title, episodes, duration_min)

        if not script_text and status != 'error':
            if format == 'shorts':
                script_text = self._placeholder_shorts(title, episodes, target_duration)
            else:
                script_text = self._placeholder_script(title, episodes, duration_min)

        # DB 저장
        db = await get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            if project_id is None:
                cursor = await db.execute(
                    'INSERT INTO projects (title, episodes, language, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (title, episodes, language, 'pending', now, now),
                )
                await db.commit()
                project_id = cursor.lastrowid

            await db.execute(
                '''INSERT INTO scripts
                   (project_id, language, content, status, cost_usd, format, genre, target_duration, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (project_id, language, script_text, status, cost_usd, format, genre, target_duration, now, now),
            )
            await db.commit()

            # shorts_metadata 저장
            if format == 'shorts':
                async with db.execute(
                    'SELECT id FROM scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1',
                    (project_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        script_id = row[0]
                        await db.execute(
                            '''INSERT INTO shorts_metadata
                               (script_id, hook_type, target_length, created_at, updated_at)
                               VALUES (?, 'mystery', ?, ?, ?)''',
                            (script_id, target_duration, now, now),
                        )
                        await db.commit()

            async with db.execute(
                '''SELECT id, project_id, language, content, status, cost_usd,
                          format, genre, target_duration, created_at, updated_at
                   FROM scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1''',
                (project_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
        finally:
            await db.close()

        return {
            'project_id': project_id, 'content': script_text,
            'status': status, 'cost_usd': cost_usd,
            'format': format, 'genre': genre,
        }

    # ──────────────────────────────────────────────
    #  번역
    # ──────────────────────────────────────────────
    async def translate_script(self, script_id: int, target_languages: List[str]) -> List[dict[str, Any]]:
        db = await get_db()
        try:
            async with db.execute('SELECT * FROM scripts WHERE id = ?', (script_id,)) as cursor:
                original = await cursor.fetchone()
            if not original:
                return []
            original = dict(original)
        finally:
            await db.close()

        results = []
        for lang in target_languages:
            translated = await self._translate_single(original['content'], original['project_id'], lang)
            results.append(translated)
        return results

    async def _translate_single(self, content: str, project_id: int, target_lang: str) -> dict:
        lang_names = {'en': 'English', 'ko': '한국어', 'id': 'Bahasa Indonesia', 'th': 'ภาษาไทย'}
        lang_name = lang_names.get(target_lang, target_lang)

        prompt = f"""다음 유튜브 리캡 스크립트를 {lang_name}로 번역해주세요.

규칙:
- [이미지 프롬프트], [BGM], [SFX], [자막], [영상], [번역 주석] 태그는 번역하지 말 것 (영어 유지)
- 나레이션 본문만 번역하세요
- 자연스러운 구어체로 번역
- 감정의 강도를 유지
- [번역 주석] 태그의 용어 번역을 참고하여 해당 언어에 맞는 고유명사 표기를 사용하세요

원본:
{content}"""

        translated_text = ''
        cost_usd = 0.0
        status = 'generated'

        if self.llm is not None:
            try:
                resp = await self.llm.generate(prompt=prompt, max_tokens=4096, temperature=0.2)
                translated_text = resp.text
                cost_usd = await log_llm_cost(resp, action='script_translate', project_id=str(project_id))
            except Exception as e:
                logger.error(f'Translation to {target_lang} failed: {e}')
                status = 'error'
        else:
            translated_text = f'[번역 미지원 — LLM API 키 필요] {target_lang}'

        db = await get_db()
        try:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                'INSERT INTO scripts (project_id, language, content, status, cost_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (project_id, target_lang, translated_text, status, cost_usd, now, now),
            )
            await db.commit()
        finally:
            await db.close()

        return {
            'project_id': project_id, 'language': target_lang,
            'content': translated_text, 'status': status, 'cost_usd': cost_usd,
        }

    # ──────────────────────────────────────────────
    #  목록 조회
    # ──────────────────────────────────────────────
    async def list_scripts(self, limit: int = 30) -> List[dict[str, Any]]:
        db = await get_db()
        try:
            async with db.execute(
                '''SELECT s.id, s.project_id, p.title as project_title, s.language,
                          s.status, s.cost_usd, s.format, s.genre, s.target_duration,
                          s.created_at, s.updated_at, substr(s.content, 1, 200) as snippet
                   FROM scripts s LEFT JOIN projects p ON s.project_id = p.id
                   ORDER BY s.created_at DESC LIMIT ?''',
                (limit,),
            ) as cursor:
                return [dict(r) for r in await cursor.fetchall()]
        finally:
            await db.close()

    # ──────────────────────────────────────────────
    #  플레이스홀더
    # ──────────────────────────────────────────────
    @staticmethod
    def _placeholder_script(title: str, episodes: str, duration: int) -> str:
        return f"""[HOOK - 0:00~0:05]
[이미지 프롬프트: young male martial artist standing on mountain peak, black long hair, white robe, Korean manhwa style, dramatic lighting, cinematic, 16:9]
[BGM: tension_building]
[번역 주석: 화산파=Mount Hua Sect, 매화검존=Plum Blossom Sword Master]
"무림 전체가 뒤집어질 사건이 시작된다..."

[SCENE 1 - 0:05~2:00]
[이미지 프롬프트: dark martial arts training hall, ancient Chinese architecture, moody atmosphere, 16:9]
[BGM: mysterious_ambient]
[SFX: wind_howl]
{title}의 이야기가 시작됩니다. {episodes if episodes else '전 회차'}를 다룹니다.
(플레이스홀더 — GEMINI_API_KEY 또는 CLAUDE_API_KEY 설정 시 AI가 실제 대본 생성)

[OUTRO - 마지막 10초]
[이미지 프롬프트: silhouette of male warrior against sunset, cliffhanger mood, 16:9]
[BGM: epic_cliffhanger]
"다음 영상에서는 더 충격적인 전개가 기다리고 있습니다. 구독과 알림을 눌러주세요!"
"""

    @staticmethod
    def _placeholder_shorts(title: str, episodes: str, duration: int) -> str:
        return f"""[HOOK - 0~1.5초]
[이미지 프롬프트: vertical close-up, young male martial artist with black hair, shocked expression, dark background, 9:16 mobile]
[BGM: dramatic_impact]
[SFX: whoosh]
[자막: 큰 글씨 중앙, 노란색 강조]
[영상: zoom_center]
[번역 주석: 화산파=Mount Hua Sect]
"{title}의 숨겨진 비밀!"

[PROBLEM - 1.5~10초]
[이미지 프롬프트: vertical composition, intense battle scene, two male warriors clashing swords, close-up action, 9:16]
[BGM: rising_tension]
[SFX: sword_clash]
[자막: 하단 자막, 흰색]
[영상: pan_left]
{episodes if episodes else '핵심 장면'}의 갈등이 터집니다.
모두가 불가능하다고 했던 그 순간.
(플레이스홀더 — API 키 설정 시 AI 생성)

[SOLUTION - 10~25초]
[이미지 프롬프트: vertical, triumphant young male hero, glowing aura, epic composition, 9:16]
[BGM: epic_victory]
[SFX: power_surge]
[자막: 하단 자막, 흰색, 키네틱]
[영상: zoom_top]
하지만 결국 반전이 일어납니다.
아무도 예상 못한 결말.

[CTA - 마지막 3초]
[이미지 프롬프트: vertical subscribe button animation style, bright colors, 9:16]
[BGM: upbeat_ending]
[SFX: notification_bell]
[자막: 큰 글씨 중앙]
[영상: zoom_out]
"이 다음이 진짜 충격이다. 구독 꾹!"
"""
