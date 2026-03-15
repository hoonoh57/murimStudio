"""미디어 서비스 — 이미지 생성 · TTS 합성 · 영상 조립"""

import os
import re
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from app.db import get_db
from app.services.cost_service import CostTracker

logger = logging.getLogger(__name__)


class MediaService:
    def __init__(self):
        self.midjourney_url = os.getenv('MIDJOURNEY_API_URL', '')
        self.elevenlabs_key = os.getenv('ELEVENLABS_API_KEY', '')
        self.output_dir = os.getenv('OUTPUT_DIR', 'output')
        os.makedirs(self.output_dir, exist_ok=True)
        self.cost_tracker = CostTracker()

    # ═══════════════════════════════════════════
    #  1) 이미지 프롬프트 추출
    # ═══════════════════════════════════════════

    async def extract_prompts(self, project_id: int) -> List[str]:
        """스크립트에서 [이미지 프롬프트: ...] 태그를 추출하여 media_items에 등록"""
        db = await get_db()
        try:
            async with db.execute(
                'SELECT content FROM scripts WHERE project_id = ? ORDER BY created_at DESC LIMIT 1',
                (project_id,),
            ) as cursor:
                row = await cursor.fetchone()

            if not row or not row['content']:
                return []

            prompts = re.findall(r'\[이미지 프롬프트:\s*(.+?)\]', row['content'])
            now = datetime.now(timezone.utc).isoformat()

            for p in prompts:
                await db.execute(
                    '''INSERT INTO media_items
                       (project_id, type, prompt, status, path, created_at, updated_at)
                       VALUES (?, 'image', ?, 'pending', '', ?, ?)''',
                    (project_id, p.strip(), now, now),
                )
            await db.commit()
            logger.info(f'Extracted {len(prompts)} image prompts for project {project_id}')
            return prompts
        finally:
            await db.close()

    # ═══════════════════════════════════════════
    #  2) 이미지 생성 (Midjourney Proxy)
    # ═══════════════════════════════════════════

    async def generate_images(self, project_id: int) -> dict:
        """pending 상태의 이미지 프롬프트를 Midjourney API로 생성"""
        db = await get_db()
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        try:
            async with db.execute(
                "SELECT id, prompt FROM media_items WHERE project_id = ? AND type = 'image' AND status = 'pending'",
                (project_id,),
            ) as cursor:
                items = [dict(r) for r in await cursor.fetchall()]

            if not items:
                return results

            if not self.midjourney_url:
                logger.warning('MIDJOURNEY_API_URL not set — creating placeholders')
                now = datetime.now(timezone.utc).isoformat()
                for item in items:
                    placeholder_path = os.path.join(self.output_dir, f"img_{item['id']}_placeholder.png")
                    with open(placeholder_path, 'w') as f:
                        f.write(f"[PLACEHOLDER] {item['prompt']}")
                    await db.execute(
                        "UPDATE media_items SET status = 'placeholder', path = ?, updated_at = ? WHERE id = ?",
                        (placeholder_path, now, item['id']),
                    )
                    results['skipped'] += 1
                await db.commit()
                return results

            async with httpx.AsyncClient(timeout=120.0) as client:
                for item in items:
                    try:
                        resp = await client.post(
                            f"{self.midjourney_url}/imagine",
                            json={'prompt': item['prompt']},
                        )
                        resp.raise_for_status()
                        data = resp.json()

                        image_url = data.get('imageUrl', data.get('url', ''))
                        if image_url:
                            img_resp = await client.get(image_url)
                            img_path = os.path.join(self.output_dir, f"img_{item['id']}.png")
                            with open(img_path, 'wb') as f:
                                f.write(img_resp.content)

                            now = datetime.now(timezone.utc).isoformat()
                            await db.execute(
                                "UPDATE media_items SET status = 'done', path = ?, updated_at = ? WHERE id = ?",
                                (img_path, now, item['id']),
                            )
                            results['success'] += 1

                            await self.cost_tracker.log_cost(
                                service='midjourney', action='imagine',
                                units=1, cost_usd=0.05,
                                project_id=str(project_id),
                            )
                        else:
                            raise ValueError('No image URL in response')

                    except Exception as e:
                        logger.error(f"Image generation failed for item {item['id']}: {e}")
                        now = datetime.now(timezone.utc).isoformat()
                        await db.execute(
                            "UPDATE media_items SET status = 'error', updated_at = ? WHERE id = ?",
                            (now, item['id']),
                        )
                        results['failed'] += 1

            await db.commit()
        finally:
            await db.close()
        return results

    # ═══════════════════════════════════════════
    #  3) TTS 음성 합성 (ElevenLabs)
    # ═══════════════════════════════════════════

    async def generate_tts(self, project_id: int, language: str = 'ko') -> dict:
        """프로젝트의 최신 스크립트를 TTS로 변환"""
        db = await get_db()
        results = {'status': 'pending', 'path': '', 'cost_usd': 0.0}
        try:
            async with db.execute(
                'SELECT id, content FROM scripts WHERE project_id = ? AND language = ? ORDER BY created_at DESC LIMIT 1',
                (project_id, language),
            ) as cursor:
                row = await cursor.fetchone()

            if not row or not row['content']:
                results['status'] = 'no_script'
                return results

            # 태그 제거하여 순수 나레이션 텍스트 추출
            content = row['content']
            clean_text = re.sub(r'\[.*?\]', '', content)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()

            if not self.elevenlabs_key:
                logger.warning('ELEVENLABS_API_KEY not set — creating placeholder TTS')
                placeholder_path = os.path.join(self.output_dir, f"tts_{project_id}_{language}.txt")
                with open(placeholder_path, 'w', encoding='utf-8') as f:
                    f.write(clean_text)

                now = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    '''INSERT INTO media_items
                       (project_id, type, prompt, status, path, created_at, updated_at)
                       VALUES (?, 'audio', ?, 'placeholder', ?, ?, ?)''',
                    (project_id, f'TTS-{language}', placeholder_path, now, now),
                )
                await db.commit()
                results['status'] = 'placeholder'
                results['path'] = placeholder_path
                return results

            # ElevenLabs API 호출
            voice_map = {'ko': 'pNInz6obpgDQGcFmaJgB', 'en': '21m00Tcm4TlvDq8ikWAM',
                         'id': 'pNInz6obpgDQGcFmaJgB', 'th': 'pNInz6obpgDQGcFmaJgB'}
            voice_id = voice_map.get(language, voice_map['en'])

            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}',
                    headers={'xi-api-key': self.elevenlabs_key, 'Content-Type': 'application/json'},
                    json={'text': clean_text[:5000], 'model_id': 'eleven_multilingual_v2'},
                )
                resp.raise_for_status()

                audio_path = os.path.join(self.output_dir, f"tts_{project_id}_{language}.mp3")
                with open(audio_path, 'wb') as f:
                    f.write(resp.content)

            char_count = len(clean_text[:5000])
            cost = char_count * 0.00003  # 대략적 ElevenLabs 비용
            now = datetime.now(timezone.utc).isoformat()

            await db.execute(
                '''INSERT INTO media_items
                   (project_id, type, prompt, status, path, created_at, updated_at)
                   VALUES (?, 'audio', ?, 'done', ?, ?, ?)''',
                (project_id, f'TTS-{language}', audio_path, now, now),
            )
            await db.commit()

            await self.cost_tracker.log_cost(
                service='elevenlabs', action='tts',
                units=char_count, cost_usd=cost,
                project_id=str(project_id),
            )

            results['status'] = 'done'
            results['path'] = audio_path
            results['cost_usd'] = cost

        except Exception as e:
            logger.error(f'TTS generation failed: {e}')
            results['status'] = 'error'
        finally:
            await db.close()
        return results

    # ═══════════════════════════════════════════
    #  4) 영상 조립 (FFmpeg)
    # ═══════════════════════════════════════════

    async def assemble_video(self, project_id: int) -> dict:
        """이미지 + 오디오를 FFmpeg로 결합하여 영상 생성"""
        db = await get_db()
        results = {'status': 'pending', 'path': '', 'images': 0, 'audio': ''}
        try:
            # 이미지 목록
            async with db.execute(
                "SELECT path FROM media_items WHERE project_id = ? AND type = 'image' AND status IN ('done', 'placeholder') ORDER BY id",
                (project_id,),
            ) as cursor:
                images = [dict(r)['path'] for r in await cursor.fetchall()]

            # 오디오
            async with db.execute(
                "SELECT path FROM media_items WHERE project_id = ? AND type = 'audio' AND status IN ('done', 'placeholder') ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            ) as cursor:
                audio_row = await cursor.fetchone()

            results['images'] = len(images)
            results['audio'] = dict(audio_row)['path'] if audio_row else ''

            if not images:
                results['status'] = 'no_images'
                return results

            # FFmpeg 존재 확인
            try:
                subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
                has_ffmpeg = True
            except (subprocess.CalledProcessError, FileNotFoundError):
                has_ffmpeg = False

            if not has_ffmpeg:
                logger.warning('FFmpeg not found — creating manifest JSON')
                manifest_path = os.path.join(self.output_dir, f"video_manifest_{project_id}.json")
                manifest = {
                    'project_id': project_id,
                    'images': images,
                    'audio': results['audio'],
                    'note': 'FFmpeg not installed. Install FFmpeg to assemble video.',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                }
                with open(manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
                results['status'] = 'manifest_created'
                results['path'] = manifest_path
                return results

            # FFmpeg 영상 조립
            video_path = os.path.join(self.output_dir, f"video_{project_id}.mp4")

            # 이미지 리스트 파일 생성
            list_path = os.path.join(self.output_dir, f"imglist_{project_id}.txt")
            duration_per_image = 5  # 이미지당 5초
            with open(list_path, 'w') as f:
                for img in images:
                    f.write(f"file '{os.path.abspath(img)}'\n")
                    f.write(f"duration {duration_per_image}\n")
                # 마지막 이미지 한 번 더 (FFmpeg concat 요구사항)
                if images:
                    f.write(f"file '{os.path.abspath(images[-1])}'\n")

            cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_path]

            if results['audio'] and os.path.exists(results['audio']):
                cmd.extend(['-i', results['audio'], '-c:a', 'aac', '-shortest'])

            cmd.extend(['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-r', '30', video_path])

            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                results['status'] = 'done'
                results['path'] = video_path

                now = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    '''INSERT INTO media_items
                       (project_id, type, prompt, status, path, created_at, updated_at)
                       VALUES (?, 'video', 'assembled', 'done', ?, ?, ?)''',
                    (project_id, video_path, now, now),
                )
                await db.commit()
                logger.info(f'Video assembled: {video_path}')
            else:
                logger.error(f'FFmpeg error: {proc.stderr[:500]}')
                results['status'] = 'error'

        except Exception as e:
            logger.error(f'Video assembly failed: {e}')
            results['status'] = 'error'
        finally:
            await db.close()
        return results
