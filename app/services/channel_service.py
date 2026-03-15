"""채널 서비스 — 메타데이터 생성 · 업로드 스케줄링 · YouTube 업로드"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import httpx

from app.db import get_db
from app.services.utils import log_claude_cost
from app.services.cost_service import CostTracker

logger = logging.getLogger(__name__)


class ChannelService:
    def __init__(self):
        self.youtube_api_key = os.getenv('YOUTUBE_API_KEY', '')
        self.cost_tracker = CostTracker()

        api_key = os.getenv('CLAUDE_API_KEY')
        if api_key:
            from anthropic import AsyncAnthropic
            self.claude_client = AsyncAnthropic(api_key=api_key)
        else:
            self.claude_client = None

    # ═══════════════════════════════════════════
    #  1) AI 메타데이터 생성 (Claude)
    # ═══════════════════════════════════════════

    async def generate_metadata(self, project_id: int, channel_code: str) -> dict:
        """Claude로 YouTube 업로드용 제목/설명/태그를 생성"""
        db = await get_db()
        try:
            async with db.execute(
                'SELECT title, episodes FROM projects WHERE id = ?', (project_id,)
            ) as cursor:
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
            language = script['language'] if script else 'en'
            snippet = script['content'][:500] if script else ''

        finally:
            await db.close()

        if not self.claude_client:
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
            response = await self.claude_client.messages.create(
                model='claude-haiku-4-5-20250315',
                max_tokens=800,
                temperature=0.5,
                messages=[{'role': 'user', 'content': prompt}],
            )
            await log_claude_cost(response, action='generate_metadata', project_id=str(project_id))

            text = response.content[0].text.strip()
            if '```' in text:
                text = text.split('```')[1]
                if text.startswith('json'):
                    text = text[4:]
                text = text.strip()

            metadata = json.loads(text)
            return metadata

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

    # ═══════════════════════════════════════════
    #  2) 업로드 스케줄링
    # ═══════════════════════════════════════════

    async def schedule_uploads(
        self, project_id: int, channel_codes: Optional[List[str]] = None, use_ai_metadata: bool = True
    ) -> List[dict]:
        """선택한 채널에 업로드 예약 (피크 시간 기반)"""
        db = await get_db()
        scheduled = []
        try:
            if channel_codes:
                placeholders = ','.join(['?'] * len(channel_codes))
                query = f'SELECT * FROM channels WHERE code IN ({placeholders})'
                async with db.execute(query, channel_codes) as cursor:
                    channels = [dict(r) for r in await cursor.fetchall()]
            else:
                async with db.execute('SELECT * FROM channels ORDER BY code') as cursor:
                    channels = [dict(r) for r in await cursor.fetchall()]

            async with db.execute(
                'SELECT id, title FROM projects WHERE id = ?', (project_id,)
            ) as cursor:
                project = await cursor.fetchone()

            if not project:
                return scheduled

            now = datetime.now(timezone.utc)

            for ch in channels:
                # 메타데이터 생성
                if use_ai_metadata:
                    metadata = await self.generate_metadata(project_id, ch['code'])
                else:
                    metadata = self._placeholder_metadata(project['title'], ch['code'])

                # 피크 시간 기반 스케줄 계산
                peak = ch.get('peak_hour', 18)
                scheduled_time = now.replace(hour=peak, minute=0, second=0, microsecond=0)
                if scheduled_time <= now:
                    scheduled_time += timedelta(days=1)

                await db.execute(
                    '''INSERT INTO uploads
                       (project_id, channel_code, title, description, tags, status, scheduled_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?, ?)''',
                    (
                        project_id,
                        ch['code'],
                        metadata.get('title', ''),
                        metadata.get('description', ''),
                        json.dumps(metadata.get('tags', []), ensure_ascii=False),
                        scheduled_time.isoformat(),
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                scheduled.append({
                    'channel': ch['code'],
                    'title': metadata.get('title', ''),
                    'scheduled_at': scheduled_time.isoformat(),
                })

            await db.commit()
            logger.info(f'Scheduled {len(scheduled)} uploads for project {project_id}')
        finally:
            await db.close()
        return scheduled

    # ═══════════════════════════════════════════
    #  3) YouTube 업로드 실행
    # ═══════════════════════════════════════════

    async def execute_uploads(self, project_id: Optional[int] = None) -> dict:
        """pending/scheduled 상태의 업로드를 실행"""
        db = await get_db()
        results = {'uploaded': 0, 'failed': 0, 'simulated': 0}
        try:
            if project_id:
                query = "SELECT * FROM uploads WHERE project_id = ? AND status IN ('pending', 'scheduled') ORDER BY scheduled_at"
                async with db.execute(query, (project_id,)) as cursor:
                    uploads = [dict(r) for r in await cursor.fetchall()]
            else:
                query = "SELECT * FROM uploads WHERE status IN ('pending', 'scheduled') ORDER BY scheduled_at LIMIT 20"
                async with db.execute(query) as cursor:
                    uploads = [dict(r) for r in await cursor.fetchall()]

            if not uploads:
                return results

            if not self.youtube_api_key:
                logger.warning('YOUTUBE_API_KEY not set — simulating uploads')
                now = datetime.now(timezone.utc).isoformat()
                for u in uploads:
                    await db.execute(
                        "UPDATE uploads SET status = 'simulated', youtube_video_id = 'SIM_' || id, uploaded_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, u['id']),
                    )
                    results['simulated'] += 1
                await db.commit()
                return results

            # 실제 YouTube API 업로드 (OAuth2 필요 — 여기서는 구조만 제공)
            now = datetime.now(timezone.utc).isoformat()
            for u in uploads:
                try:
                    # TODO: google-api-python-client로 실제 업로드 구현
                    # 현재는 시뮬레이션
                    await db.execute(
                        "UPDATE uploads SET status = 'simulated', youtube_video_id = 'PENDING_OAUTH', uploaded_at = ?, updated_at = ? WHERE id = ?",
                        (now, now, u['id']),
                    )
                    results['simulated'] += 1
                    logger.info(f"Upload {u['id']} for channel {u['channel_code']} — awaiting OAuth2 setup")

                except Exception as e:
                    logger.error(f"Upload failed for {u['id']}: {e}")
                    await db.execute(
                        "UPDATE uploads SET status = 'error', updated_at = ? WHERE id = ?",
                        (now, u['id']),
                    )
                    results['failed'] += 1

            await db.commit()
        finally:
            await db.close()
        return results

    # ═══════════════════════════════════════════
    #  4) 업로드 큐 조회
    # ═══════════════════════════════════════════

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
