"""데이터베이스 유틸리티 — SQLite 연결 · 초기화"""

import os
import logging
import aiosqlite

logger = logging.getLogger(__name__)


async def get_db():
    db_path = os.getenv('DB_PATH', 'app.db')
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    await conn.execute('PRAGMA journal_mode=WAL')
    await conn.execute('PRAGMA foreign_keys=ON')
    return conn


async def init_db():
    conn = await get_db()
    try:
        # ── 기존 테이블 ──
        await conn.execute('''CREATE TABLE IF NOT EXISTS api_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service TEXT NOT NULL,
            action TEXT NOT NULL,
            units REAL DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            cost_krw REAL DEFAULT 0,
            project_id TEXT DEFAULT '',
            timestamp TEXT NOT NULL
        )''')

        await conn.execute('''CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            episodes TEXT DEFAULT '',
            language TEXT DEFAULT 'en',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )''')

        await conn.execute('''CREATE TABLE IF NOT EXISTS scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            language TEXT DEFAULT 'en',
            content TEXT DEFAULT '',
            status TEXT DEFAULT 'generated',
            cost_usd REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )''')

        await conn.execute('''CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT DEFAULT '',
            youtube_channel_id TEXT DEFAULT '',
            timezone TEXT DEFAULT 'UTC',
            peak_hour INTEGER DEFAULT 18,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )''')

        await conn.execute('''CREATE TABLE IF NOT EXISTS media_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            type TEXT DEFAULT 'image',
            path TEXT DEFAULT '',
            prompt TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )''')

        await conn.execute('''CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            channel_code TEXT NOT NULL,
            video_path TEXT DEFAULT '',
            youtube_video_id TEXT DEFAULT '',
            title TEXT DEFAULT '',
            description TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            scheduled_at TEXT,
            uploaded_at TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )''')

        await conn.execute('''CREATE TABLE IF NOT EXISTS trend_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            trend_score INTEGER DEFAULT 0,
            source TEXT DEFAULT '',
            genre TEXT DEFAULT '',
            meta_json TEXT DEFAULT '{}',
            collected_at TEXT NOT NULL
        )''')

        await conn.execute('''CREATE TABLE IF NOT EXISTS trend_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rank INTEGER DEFAULT 0,
            title TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            reason TEXT DEFAULT '',
            episode_range TEXT DEFAULT '',
            target_audience TEXT DEFAULT '',
            collected_at TEXT NOT NULL
        )''')

        # ── P0-1: scripts 테이블에 format, genre, target_duration 컬럼 추가 ──
        for col, col_type, default in [
            ('format', 'TEXT', "'long'"),
            ('genre', 'TEXT', "'neutral'"),
            ('target_duration', 'INTEGER', '600'),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE scripts ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
                logger.info(f"[DB 마이그레이션] scripts.{col} 컬럼 추가됨")
            except Exception:
                pass  # 이미 존재하면 무시

        # ── P0-1: shorts_metadata 테이블 신규 ──
        await conn.execute('''CREATE TABLE IF NOT EXISTS shorts_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id INTEGER NOT NULL,
            hook_type TEXT DEFAULT 'mystery',
            hook_text TEXT DEFAULT '',
            cta_text TEXT DEFAULT '',
            loop_enabled INTEGER DEFAULT 1,
            bgm_id TEXT DEFAULT '',
            target_length INTEGER DEFAULT 30,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (script_id) REFERENCES scripts(id)
        )''')

        # 기본 채널 데이터 시드
        for code, name, tz, hour in [
            ('en', 'Murim Recap EN', 'US/Eastern', 18),
            ('ko', '무협 팩토리 KR', 'Asia/Seoul', 20),
            ('id', 'Murim Recap ID', 'Asia/Jakarta', 19),
            ('th', 'Murim Recap TH', 'Asia/Bangkok', 18),
        ]:
            await conn.execute('''INSERT OR IGNORE INTO channels
                (code, name, timezone, peak_hour, created_at, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))''',
                (code, name, tz, hour))

        await conn.commit()
        logger.info('Database initialized with 9 tables + seed data (v1.7 schema)')
    finally:
        await conn.close()
