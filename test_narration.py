import sqlite3

conn = sqlite3.connect('app.db')
r = conn.execute('SELECT content FROM scripts WHERE id=10').fetchone()
content = r[0]

# 현재 추출 로직
lines = content.split('\n')
for i, line in enumerate(lines[:40]):
    stripped = line.strip()
    skip = False
    for tag in ['[이미지', '[Image', '[BGM', '[bgm', '[HOOK', '[SCENE', '[OUTRO', '**[', '#']:
        if stripped.startswith(tag):
            skip = True
            break
    marker = '⛔ SKIP' if skip else ('  EMPTY' if not stripped else '✅ READ')
    print(f'{i:3d} {marker} | {stripped[:100]}')