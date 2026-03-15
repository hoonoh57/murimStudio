import os
import json
from datetime import datetime
from typing import Any, Optional

from app.db import get_db
from app.services.cost_service import CostTracker


class ScriptFactory:
    def __init__(self):
        api_key = os.getenv('CLAUDE_API_KEY')
        if not api_key:
            self.client = None
        else:
            from anthropic import AsyncAnthropic
            self.client = AsyncAnthropic(api_key=api_key)

    async def generate_script(self, title: str, topic: str = '', project_id: Optional[int] = None, language: str = 'ko') -> dict[str, Any]:
        prompt = f"""당신은 유튜브 리캡 영상 스크립트 작성 도우미입니다.

주제: {title}
키워드: {topic}

한국어로 5분 분량 대본 형태로 작성해주세요.
"""

        script_text = ''
        estimated_cost = 0.0

        if self.client is not None:
            try:
                response = await self.client.messages.create(
                    model='claude-haiku-4-5-20250315',
                    max_tokens=1500,
                    temperature=0.3,
                    messages=[{'role': 'user', 'content': prompt}],
                )
                script_text = getattr(response.content[0], 'text', '') if hasattr(response, 'content') and response.content else ''

                usage = None
                if hasattr(response, 'usage'):
                    usage = response.usage
                elif isinstance(response, dict):
                    usage = response.get('usage')

                if usage:
                    input_tokens = int(getattr(usage, 'input_tokens', usage.get('input_tokens', 0)))
                    output_tokens = int(getattr(usage, 'output_tokens', usage.get('output_tokens', 0)))
                    estimated_cost = (input_tokens * 1.0 / 1_000_000) + (output_tokens * 5.0 / 1_000_000)
                    tracker = CostTracker()
                    await tracker.log_cost('claude', 'script_generate', input_tokens + output_tokens, estimated_cost, project_id=str(project_id) if project_id else '')
            except Exception as e:
                script_text = f'스크립트 생성 중 오류 발생: {e}'

        if not script_text:
            script_text = f'기본 텍스트: {title} / {topic}'

        db = await get_db()
        try:
            if project_id is None:
                now = datetime.utcnow().isoformat()
                cursor = await db.execute(
                    'INSERT INTO projects (title, episodes, language, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
                    (title, '', language, 'pending', now, now)
                )
                await db.commit()
                project_id = cursor.lastrowid

            now = datetime.utcnow().isoformat()
            await db.execute(
                'INSERT INTO scripts (project_id, language, content, status, cost_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (project_id, language, script_text, 'generated', estimated_cost, now, now)
            )
            await db.commit()

            async with db.execute('SELECT id, project_id, language, content, status, cost_usd, created_at, updated_at FROM scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1', (project_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)

        finally:
            await db.close()

        return {'project_id': project_id, 'content': script_text, 'cost_usd': estimated_cost}

    async def list_scripts(self, limit: int = 20) -> list[dict[str, Any]]:
        db = await get_db()
        try:
            async with db.execute('SELECT id, project_id, language, status, cost_usd, created_at, updated_at, substr(content, 1, 180) as snippet FROM scripts ORDER BY created_at DESC LIMIT ?', (limit,)) as cursor:
                rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await db.close()