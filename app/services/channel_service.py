"""채널 서비스 — 메타데이터 생성 · 업로드 스케줄링 · YouTube 업로드"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import httpx

from app.db import get_db
from app.services.llm_client import get_llm_client
from app.services.utils import log_llm_cost
from app.services.cost_service import CostTracker

logger = logging.getLogger(__name__)


class ChannelService:
    def __init__(self):
        self.youtube_api_key = os.getenv('YOUTUBE_API_KEY', '')
        self.cost_tracker = CostTracker()
        self.llm = get_llm_client()

    async def generate_metadata(self, project_id: int, channel_code: str) -> dict:
        db = await get_db()
        try:
            async with db.execute('SELECT title, episodes FROM projects WHERE id = ?', (project_id,)) as cursor:
                project = await cursor.fetchone()
            async with db.execute(
                'SELECT content, language FROM scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1',
                (project_id,),
            ) as cursor:
                script = await cursor.fetchone()

            if not project:
                return self._placeholder_metadata(f'Project {project_id}', channel_code)

            title = project['title']
            episodes = project['episodes']
            snippet = script['content'][:500] if script else ''
        finally:
            await db.close()

        if not self.llm:
            return self._placeholder_metadata(title, channel_code)

        lang_labels = {'ko': '한국어', 'en': 'English', 'id': 'Bahasa Indonesia', 'th': 'ภาษาไทย'}
        target_lang = lang_labels.get(channel_code, 'English')

        prompt = f"""다음 무협 웹툰 리캡 영상의 YouTube 메타데이터를 생성해주세요.
작품: {title}
에피소드: {episodes}
채널 언어: {target_lang} ({channel_code})
스크립트 일부: {snippet}

다음 형식의 JSON만 반환하세요:
{{
    "title": "YouTube 영상 제목 (70자 이내, 클릭 유도 후크 포함)",
    "description": "영상 설명 (300자 이내, SEO 최적화, 해시태그 포함)",
    "tags": ["태그1", "태그2", "태그3", "태그4", "태그5"]
}}"""

        try:
            resp = await self.llm.generate(prompt=prompt, max_tokens=800, temperature=0.5)
            await log_llm_cost(resp, action='generate_metadata', project_id=str(project_id))

            text = resp.text.strip()
            if '```' in text:
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
                text = text.strip()

            return json.loads(text)
        except Exception as e:
            logger.error(f'Metadata generation failed: {e}')
            return self._placeholder_metadata(title, channel_code)

    @staticmethod
    def _placeholder_metadata(title: str, channel_code: str) -> dict:
        return {
            'title': f'{title} - Murim Recap ({channel_code.upper()})',
            'description': f'{title} 무협 웹툰 리캡 영상입니다. #무협 #웹툰 #리캡 #manhwa',
            'tags': ['murim', 'manhwa', 'recap', 'webtoon', channel_code],
        }

    async def schedule_uploads(
        self, project_id: int, channel_codes: Optional[List[str]] = None, use_ai_metadata: bool = True
    ) -> List[dict]:
        db = await get_db()
        scheduled = []
        try:
            if channel_codes:
                placeholders = ','.join(['?'] * len(channel_codes))
                async with db.execute(f'SELECT * FROM channels WHERE code IN ({placeholders})', channel_codes) as cursor:
                    channels = [dict(r) for r in await cursor.fetchall()]
            else:
                async with db.execute('SELECT * FROM channels ORDER BY code') as cursor:
                    channels = [dict(r) for r in await cursor.fetchall()]

            async with db.execute('SELECT id, title FROM projects WHERE id = ?', (project_id,)) as cursor:
                project = await cursor.fetchone()

            if not project:
                return scheduled

            now = datetime.now(timezone.utc)
            for ch in channels:
                if use_ai_metadata:
                    metadata = await self.generate_metadata(project_id, ch['code'])
                else:
                    metadata = self._placeholder_metadata(project['title'], ch['code'])

                peak = ch.get('peak_hour', 18)
                scheduled_time = now.replace(hour=peak, minute=0, second=0, microsecond=0)
                if scheduled_time <= now:
                    scheduled_time += timedelta(days=1)

                await db.execute(
                    '''INSERT INTO uploads (project_id, channel_code, title, description, tags, status, scheduled_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?, ?)''',
                    (project_id, ch['code'], metadata.get('title', ''), metadata.get('description', ''),
                     json.dumps(metadata.get('tags', []), ensure_ascii=False),
                     scheduled_time.isoformat(), now.isoformat(), now.isoformat()),
                )
                scheduled.append({'channel': ch['code'], 'title': metadata.get('title', ''), 'scheduled_at': scheduled_time.isoformat()})

            await db.commit()
            logger.info(f'Scheduled {len(scheduled)} uploads for project {project_id}')
        finally:
            await db.close()
        return scheduled

    async def execute_uploads(self, project_id: Optional[int] = None) -> dict:
        db = await get_db()
        results = {'uploaded': 0, 'failed': 0, 'simulated': 0}
        try:
            q = "SELECT * FROM uploads WHERE status IN ('pending', 'scheduled')"
            if project_id:
                q += " AND project_id = ?"
                async with db.execute(q + " ORDER BY scheduled_at", (project_id,)) as cursor:
                    uploads = [dict(r) for r in await cursor.fetchall()]
            else:
                async with db.execute(q + " ORDER BY scheduled_at LIMIT 20") as cursor:
                    uploads = [dict(r) for r in await cursor.fetchall()]

            if not uploads:
                return results

            now = datetime.now(timezone.utc).isoformat()
            for u in uploads:
                try:
                    await db.execute(
                        "UPDATE uploads SET status = 'simulated', youtube_video_id = 'SIM_' || id, uploaded_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, u['id']),
                    )
                    results['simulated'] += 1
                except Exception as e:
                    logger.error(f"Upload failed for {u['id']}: {e}")
                    await db.execute("UPDATE uploads SET status = 'error', updated_at = ? WHERE id = ?", (now, u['id']))
                    results['failed'] += 1

            await db.commit()
        finally:
            await db.close()
        return results

    async def get_upload_queue(self, limit: int = 30) -> List[dict]:
        db = await get_db()
        try:
            async with db.execute(
                'SELECT id, project_id, channel_code, title, status, scheduled_at, uploaded_at FROM uploads ORDER BY created_at DESC LIMIT ?',
                (limit,),
            ) as cursor:
                return [dict(r) for r in await cursor.fetchall()]
        finally:
            await db.close()