"""스크립트 공장 — LLM으로 무협 리캡 대본 생성 및 DB 관리 (레퍼런스 자동 수집 포함)"""

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

SYSTEM_PROMPT = """당신은 무협 웹툰 유튜브 리캡 전문 작가입니다.

규칙:
1. 첫 5초 안에 가장 충격적인 장면으로 시작 (훅)
2. 매 2분마다 서스펜스 포인트를 배치하여 이탈 방지
3. 무림 용어는 괄호 안에 영어 설명 추가 — 예: 화산파(Mount Hua Sect)
4. 각 장면마다 아래 태그를 반드시 포함:
   - [이미지 프롬프트: 영어로 Midjourney용 프롬프트]
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
[이미지 프롬프트: ...]
[BGM: ...]
(내레이션 본문)

... (장면 반복) ...

[OUTRO - 마지막 10초]
(다음 영상 유도 클리프행어)
"""


class ScriptFactory:
    def __init__(self):
        self.llm = get_llm_client()
        self.ref_collector = ReferenceCollector()
        if self.llm is None:
            logger.warning('No LLM API key — ScriptFactory will use placeholder')

    # ──────────────────────────────────────────────
    #  스크립트 생성
    # ──────────────────────────────────────────────
    async def generate_script(
        self, title: str, episodes: str = '', duration_min: int = 10,
        style: str = '긴장감+감동', language: str = 'ko', project_id: Optional[int] = None,
    ) -> dict[str, Any]:
        word_count = duration_min * 150

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
                parts.append("\n위 참고 자료의 실제 캐릭터명·사건·줄거리를 정확히 반영하세요.")
                parts.append("참고 자료에 없는 허구의 인물·기술명·사건을 만들지 마세요.")
                reference_block = "\n".join(parts)
                logger.info(f'[ScriptFactory] 레퍼런스 {len(ref_data["sources"])}개 소스 수집 완료 ({len(reference_block)}자)')
        except Exception as e:
            logger.warning(f'[ScriptFactory] 레퍼런스 수집 실패 (무시하고 계속): {e}')

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
                    prompt=prompt, system=SYSTEM_PROMPT,
                    max_tokens=4096, temperature=0.3,
                )
                script_text = resp.text
                cost_usd = await log_llm_cost(
                    resp, action='script_generate',
                    project_id=str(project_id) if project_id else '',
                )
                logger.info(f'Script generated via {resp.provider}/{resp.model} for "{title}" — ${cost_usd:.6f}')
            except Exception as e:
                logger.error(f'Script generation failed: {e}')
                status = 'error'
        else:
            script_text = self._placeholder_script(title, episodes, duration_min)

        if not script_text and status != 'error':
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
                'INSERT INTO scripts (project_id, language, content, status, cost_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (project_id, language, script_text, status, cost_usd, now, now),
            )
            await db.commit()

            async with db.execute(
                'SELECT id, project_id, language, content, status, cost_usd, created_at, updated_at FROM scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1',
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
            translated = await self._translate_single(original['content'], original['project_id'], lang)
            results.append(translated)
        return results

    async def _translate_single(self, content: str, project_id: int, target_lang: str) -> dict:
        lang_names = {'en': 'English', 'ko': '한국어', 'id': 'Bahasa Indonesia', 'th': 'ภาษาไทย'}
        lang_name = lang_names.get(target_lang, target_lang)

        prompt = f"""다음 유튜브 리캡 스크립트를 {lang_name}로 번역해주세요.

규칙:
- 무협 용어는 현지에서 통용되는 표현 사용
- [이미지 프롬프트] 와 [BGM] 태그는 번역하지 말 것 (영어 유지)
- 자연스러운 구어체로 번역
- 감정의 강도를 유지

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

        return {'project_id': project_id, 'language': target_lang, 'content': translated_text, 'status': status, 'cost_usd': cost_usd}

    # ──────────────────────────────────────────────
    #  목록 조회
    # ──────────────────────────────────────────────
    async def list_scripts(self, limit: int = 30) -> List[dict[str, Any]]:
        db = await get_db()
        try:
            async with db.execute(
                '''SELECT s.id, s.project_id, p.title as project_title, s.language, s.status, s.cost_usd,
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
    def _placeholder_script(title: str, episodes: str, duration: int) -> str:
        return f"""[HOOK - 0:00~0:05]
"무림 전체가 뒤집어질 사건이 시작된다..."

[SCENE 1 - 0:05~2:00]
[이미지 프롬프트: young martial artist standing on mountain peak, Korean manhwa style, dramatic lighting, --ar 16:9]
[BGM: tension_building]
{title}의 이야기가 시작됩니다. {episodes if episodes else '전 회차'}를 다룹니다.
(이 스크립트는 플레이스홀더입니다. CLAUDE_API_KEY 또는 GEMINI_API_KEY를 설정하면 AI가 실제 대본을 생성합니다.)

[OUTRO - 마지막 10초]
"다음 영상에서는 더 충격적인 전개가 기다리고 있습니다. 구독과 알림을 눌러주세요!"
"""
