import os
import aiosqlite

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///app.db')

async def get_db():
    db_path = os.getenv('DB_PATH', 'app.db')
    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row
    return conn

async def init_db():
    conn = await get_db()
    try:
        await conn.execute('''CREATE TABLE IF NOT EXISTS api_costs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT, action TEXT,
            units REAL, cost_usd REAL, cost_krw REAL, project_id TEXT, timestamp TEXT)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, episodes TEXT,
            language TEXT DEFAULT 'en', status TEXT DEFAULT 'pending',
            created_at TEXT, updated_at TEXT)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
            language TEXT DEFAULT 'en', content TEXT, status TEXT DEFAULT 'generated',
            cost_usd REAL DEFAULT 0, created_at TEXT, updated_at TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id))''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, name TEXT,
            youtube_channel_id TEXT, timezone TEXT, peak_hour INTEGER DEFAULT 18,
            created_at TEXT, updated_at TEXT)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS media_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
            type TEXT DEFAULT 'image', path TEXT, status TEXT DEFAULT 'pending',
            created_at TEXT, updated_at TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id))''')
        await conn.commit()
    finally:
        await conn.close()
