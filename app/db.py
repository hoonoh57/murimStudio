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
    await conn.execute('CREATE TABLE IF NOT EXISTS api_costs (id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT, action TEXT, units REAL, cost_usd REAL, cost_krw REAL, project_id TEXT, timestamp TEXT)')
    await conn.commit()
    await conn.close()
