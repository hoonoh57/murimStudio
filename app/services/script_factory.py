"""스크립트 공장 — LLM으로 리캡 대본 생성 및 DB 관리 (포맷/장르 분기 지원)"""

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

# ═══════════════════════════════════════════════════════
#  포맷별 SYSTEM_PROMPT
# ═══════════════════════════════════════════════════════

SYSTEM_PROMPT_LONG = """당신은 유튜브 리캡 전문 작가입니다.

규칙:
1. 첫 5초 안에 가장 충격적인 장면으로 시작 (훅)
2. 매 2분마다 서스펜스 포인트를 배치하여 이탈 방지
3. 용어는 괄호 안에 영어 설명 추가 — 예: 화산파(Mount Hua Sect)
4. 각 장면마다 아래 태그를 반드시 포함:
   - [이미지 프롬프트: 영어로 Midjourney용 프롬프트, 16:9 가로 구도]
   - [BGM: 분위기 키워드]
5. 마지막 10초는 다음 영상으로 유도하는 클리프행어
6. 대사를 직접 인용할 때는 큰따옴표 사용
7. 자연스러운 구어체 내레이션 톤
8. 참고 자료가 제공된 경우, 반드시 실제 인물명과 사건을 사용하세요
9. 참고 자료에 없는 허구의 인물이나 기술명을 만들지 마세요

출력 형식:
[HOOK - 0:00~0:05]
(충격적 오프닝 한 줄)

[SCENE 1 - 0:05~2:00]
[이미지 프롬프트: ... --ar 16:9]
[BGM: ...]
(내레이션 본문)

... (장면 반복) ...

[OUTRO - 마지막 10초]
(다음 영상 유도 클리프행어)
"""

SYSTEM_PROMPT_SHORTS = """당신은 YouTube Shorts(15~59초) 바이럴 영상 전문 작가입니다.

■ 구조 (4단계 필수):
[HOOK - 0~3초]
- 결과/충격/질문으로 시작. 스크롤 멈추게 하는 첫 문장.
- [HOOK_TEXT: 화면에 표시할 대형 텍스트 (15자 이내)]

[PROBLEM - 3~10초]  
- 공감 유발. "왜 이런 일이 벌어졌나?"
- [이미지 프롬프트: 세로 구도, 인물 클로즈업, dramatic expression, vertical composition, 9:16 aspect ratio]

[SOLUTION - 10~25초]
- 핵심 내용 전달. 2-4초마다 장면 전환 느낌.
- [이미지 프롬프트: ...] 를 2-3개 포함

[CTA - 마지막 3초]
- 구독/댓글 유도: "이 다음이 진짜 충격이다. 구독 눌러라!"
- [이미지 프롬프트: ...]

■ 규칙:
1. 전체 나레이션 200자 이내 (한국어 기준)
2. 모든 문장은 15자 이내로 짧게 끊기
3. [이미지 프롬프트] 최소 3개, 최대 5개 포함
4. 모든 이미지 프롬프트에 "vertical composition, close-up, 9:16" 포함
5. [HOOK_TEXT: ...] 태그 반드시 1개 포함 (첫 화면 오버레이용)
6. [BGM: ...] 태그 1개 포함
7. 참고 자료가 제공된 경우, 실제 인물명과 사건 사용
8. 마지막 문장은 반드시 CTA (행동 유도)
9. 감탄사, 의문문으로 긴장감 유지
"""

# ═══════════════════════════════════════════════════════
#  장르별 스타일 지시
# ═══════════════════════════════════════════════════════

GENRE_STYLE_INSTRUCTIONS = {
    "wuxia": "무협/무림 세계관. 검술, 내공, 문파 대결. 용어는 괄호 안에 영어 설명 추가.",
    "anime": "일본 애니메이션/만화 스타일. 밝은 색감, 과장된 감정 표현.",
    "comedy": "코미디/개그. 유머러스한 톤, 반전과 웃음 포인트 배치.",
    "fantasy": "판타지 세계관. 마법, 던전, 레벨업 시스템.",
    "romance": "로맨스/감성. 감정선 중심, 설렘과 갈등.",
    "action": "액션/전투. 빠른 전개, 강렬한 전투 장면 묘사.",
    "horror": "호러/스릴러. 불안감 조성, 반전 공포.",
    "neutral": "장르 특화 없이 작품 내용에 맞게 자유롭게 작성.",
}


class ScriptFactory:
    def __init__(self):
        self.llm = get_llm_client()
        self.ref_collector = ReferenceCollector()
        if self.llm is None:
            logger.warning('No LLM API key — ScriptFactory will use placeholder')

    # ──────────────────────────────────────────────
    #  스크립트 생성 (포맷/장르 분기)
    # ──────────────────────────────────────────────
    async def generate_script(
        self, title: str, episodes: str = '', duration_min: int = 10,
        style: str = '긴장감+감동', language: str = 'ko',
        project_id: Optional[int] = None,
        format: str = 'long',
        genre: str = 'neutral',
    ) -> dict[str, Any]:

        # 포맷에 따른 설정
        if format == 'shorts':
            system_prompt = SYSTEM_PROMPT_SHORTS
            word_count = 200
            target_duration = duration_min  # shorts는 초 단위로 받음
        else:
            system_prompt = SYSTEM_PROMPT_LONG
            word_count = duration_min * 150
            target_duration = duration_min * 60

        # 장르 스타일 추가
        genre_instruction = GENRE_STYLE_INSTRUCTIONS.get(genre, GENRE_STYLE_INSTRUCTIONS["neutral"])
        system_prompt = system_prompt + f"\n\n■ 장르 스타일: {genre_instruction}"

        # ★ 레퍼런스 자동 수집
        reference_block = ""
        try:
            ref_data = await self.ref_collector.collect(title, episodes)
            if ref_data["summary"]:
                parts = []
                parts.append("=== 참고 자료 (실제 작품 정보 — 반드시 이 정보를 기반으로 작성) ===")
                parts.append(ref_data["summary"][:6000])
                if ref_data["characters"]:
                    parts.append("\n=== 등장인물 ===")
                    parts.append(ref_data["characters"][:2000])
                if ref_data["episode_info"]:
                    parts.append(f"\n=== 해당 회차 정보 ({episodes}) ===")
                    parts.append(ref_data["episode_info"][:2000])
                parts.append(f"\n위 참고 자료의 실제 캐릭터명·사건·줄거리를 정확히 반영하세요.")
                parts.append(f"참고 자료에 없는 허구의 인물·기술명·사건을 만들지 마세요.")
                if episodes:
                    parts.append(f"⚠ 반드시 {episodes} 범위의 내용만 다루세요.")
                reference_block = "\n".join(parts)
                logger.info(f'[ScriptFactory] 레퍼런스 {len(ref_data["sources"])}개 소스 수집 완료')
        except Exception as e:
            logger.warning(f'[ScriptFactory] 레퍼런스 수집 실패 (무시하고 계속): {e}')

        # 포맷별 프롬프트
        if format == 'shorts':
            prompt = f"""작품: {title}
회차 범위: {episodes if episodes else '전체'}
목표 길이: {duration_min}초 (YouTube Shorts)
스타일: {style}
언어: {language}

{reference_block}

위 작품의 YouTube Shorts용 스크립트를 작성해주세요.
15~59초 세로 영상에 맞게 짧고 임팩트 있게 작성하세요."""
        else:
            prompt = f"""작품: {title}
회차 범위: {episodes if episodes else '전체'}
목표 길이: {duration_min}분 (약 {word_count}단어)
스타일: {style}
언어: {language}

{reference_block}

위 작품의 유튜브 리캡 영상 스크립트를 작성해주세요."""

        script_text = ''
        cost_usd = 0.0
        status = 'generated'

        if self.llm is not None:
            try:
                resp = await self.llm.generate(
                    prompt=prompt, system=system_prompt,
                    max_tokens=4096 if format == 'long' else 1024,
                    temperature=0.3,
                )
                script_text = resp.text
                cost_usd = await log_llm_cost(
                    resp, action=f'script_generate_{format}',
                    project_id=str(project_id) if project_id else '',
                )
                logger.info(f'Script generated ({format}/{genre}) for "{title}" — ${cost_usd:.6f}')
            except Exception as e:
                logger.error(f'Script generation failed: {e}')
                status = 'error'
        else:
            script_text = self._placeholder_script(title, episodes, duration_min, format)

        if not script_text and status != 'error':
            script_text = self._placeholder_script(title, episodes, duration_min, format)

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
                (project_id, language, script_text, status, cost_usd,
                 format, genre, target_duration, now, now),
            )
            await db.commit()

            # shorts인 경우 shorts_metadata도 생성
            if format == 'shorts':
                # HOOK_TEXT 추출
                import re
                hook_match = re.search(r'\[HOOK_TEXT:\s*(.+?)\]', script_text)
                hook_text = hook_match.group(1).strip() if hook_match else ''

                async with db.execute(
                    'SELECT id FROM scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1',
                    (project_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        script_id = row[0]
                        await db.execute(
                            '''INSERT INTO shorts_metadata
                               (script_id, hook_type, hook_text, cta_text, loop_enabled, target_length, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                            (script_id, 'mystery', hook_text, '', 1, duration_min, now, now),
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

        return {'project_id': project_id, 'content': script_text, 'status': status, 'cost_usd': cost_usd}

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
            translated = await self._translate_single(
                original['content'], original['project_id'], lang,
                original.get('format', 'long'), original.get('genre', 'neutral'),
                original.get('target_duration', 600),
            )
            results.append(translated)
        return results

    async def _translate_single(self, content: str, project_id: int, target_lang: str,
                                 format: str = 'long', genre: str = 'neutral',
                                 target_duration: int = 600) -> dict:
        lang_names = {'en': 'English', 'ko': '한국어', 'id': 'Bahasa Indonesia', 'th': 'ภาษาไทย'}
        lang_name = lang_names.get(target_lang, target_lang)

        format_note = ""
        if format == 'shorts':
            format_note = "\n- 숏츠용이므로 200자 이내로 짧게 유지\n- [HOOK_TEXT] 태그도 번역\n- CTA도 해당 언어로 번역"

        prompt = f"""다음 유튜브 리캡 스크립트를 {lang_name}로 번역해주세요.

규칙:
- 용어는 현지에서 통용되는 표현 사용
- [이미지 프롬프트] 와 [BGM] 태그는 번역하지 말 것 (영어 유지)
- 자연스러운 구어체로 번역
- 감정의 강도를 유지{format_note}

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
                '''INSERT INTO scripts
                   (project_id, language, content, status, cost_usd, format, genre, target_duration, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (project_id, target_lang, translated_text, status, cost_usd,
                 format, genre, target_duration, now, now),
            )
            await db.commit()
        finally:
            await db.close()

        return {'project_id': project_id, 'language': target_lang, 'content': translated_text,
                'status': status, 'cost_usd': cost_usd}

    # ──────────────────────────────────────────────
    #  목록 조회
    # ──────────────────────────────────────────────
    async def list_scripts(self, limit: int = 30) -> List[dict[str, Any]]:
        db = await get_db()
        try:
            async with db.execute(
                '''SELECT s.id, s.project_id, p.title as project_title, s.language, s.status, s.cost_usd,
                          s.format, s.genre, s.target_duration,
                          s.created_at, s.updated_at, substr(s.content, 1, 200) as snippet
                   FROM scripts s LEFT JOIN projects p ON s.project_id = p.id ORDER BY s.created_at DESC LIMIT ?''',
                (limit,),
            ) as cursor:
                return [dict(r) for r in await cursor.fetchall()]
        finally:
            await db.close()

    # ──────────────────────────────────────────────
    #  플레이스홀더
    # ──────────────────────────────────────────────
    @staticmethod
    def _placeholder_script(title: str, episodes: str, duration: int, format: str = 'long') -> str:
        if format == 'shorts':
            return f"""[HOOK - 0~3초]
[HOOK_TEXT: {title}의 충격적 반전]
이 장면을 보고 소름이 돋았다...

[PROBLEM - 3~10초]
[이미지 프롬프트: dramatic close-up of warrior face, vertical composition, intense expression, dark background, 9:16 aspect ratio]
[BGM: tension_dark]
{title}에서 벌어진 일. 아무도 예상 못 했다.

[SOLUTION - 10~25초]
[이미지 프롬프트: epic battle scene, vertical composition, dynamic action pose, energy effects, 9:16 aspect ratio]
[이미지 프롬프트: emotional reunion scene, vertical composition, close-up tears, warm lighting, 9:16 aspect ratio]
{episodes if episodes else '최신 회차'}의 핵심은 바로 이거다.
(플레이스홀더 — LLM API 키를 설정하면 AI가 실제 대본을 생성합니다.)

[CTA - 마지막 3초]
[이미지 프롬프트: mysterious silhouette, vertical composition, cliffhanger mood, dark atmosphere, 9:16 aspect ratio]
이 다음이 진짜 충격이다. 구독 눌러라!
"""
        else:
            return f"""[HOOK - 0:00~0:05]
"전체가 뒤집어질 사건이 시작된다..."

[SCENE 1 - 0:05~2:00]
[이미지 프롬프트: young martial artist standing on mountain peak, dramatic lighting, --ar 16:9]
[BGM: tension_building]
{title}의 이야기가 시작됩니다. {episodes if episodes else '전 회차'}를 다룹니다.
(이 스크립트는 플레이스홀더입니다. CLAUDE_API_KEY 또는 GEMINI_API_KEY를 설정하면 AI가 실제 대본을 생성합니다.)

[OUTRO - 마지막 10초]
"다음 영상에서는 더 충격적인 전개가 기다리고 있습니다. 구독과 알림을 눌러주세요!"
"""
