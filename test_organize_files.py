
import shutil, os
from pathlib import Path

src = Path('static/images')
dst = src / 'unassigned'
dst.mkdir(exist_ok=True)

moved = 0
for f in src.glob('scene_*.jpg'):
    if f.is_file():
        shutil.move(str(f), str(dst / f.name))
        moved += 1

print(f'미분류 이미지 {moved}장 → static/images/unassigned/ 이동 완료')
