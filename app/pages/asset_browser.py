"""
제작물 브라우저 – 스크립트별 이미지/오디오/영상 통합 조회 + 삭제/오버라이트
v1.7.2  2026-03-19
"""

import json
import sqlite3
import subprocess
import logging
import shutil
from pathlib import Path
from nicegui import ui

from app.services.image_generator import ImageGenerator

logger = logging.getLogger(__name__)

# ── 디렉토리 ──────────────────────────────────────────────
IMAGE_DIR  = Path("static/images")
AUDIO_DIR  = Path("output/audio")
VIDEO_DIR  = Path("output/video")
SHORTS_DIR = Path("output/shorts")
DB_PATH    = "app.db"

for d in [IMAGE_DIR, AUDIO_DIR, VIDEO_DIR, SHORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

_generator = ImageGenerator()


# ── 유틸리티 ──────────────────────────────────────────────
def _ffprobe_duration(path: str) -> float:
    """ffprobe 로 오디오/영상 길이(초) 반환"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


# ── DB 조회 ───────────────────────────────────────────────
def get_scripts_from_db() -> list:
    """DB 에서 스크립트 목록 조회 (format·genre 포함)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT s.id,
                   COALESCE(p.title, '제목없음') AS title,
                   s.language,
                   LENGTH(s.content)              AS content_len,
                   COALESCE(s.format, 'long')     AS format,
                   COALESCE(s.genre,  'neutral')   AS genre
            FROM scripts s
            LEFT JOIN projects p ON s.project_id = p.id
            WHERE s.content IS NOT NULL AND LENGTH(s.content) > 0
            ORDER BY s.id DESC
        """).fetchall()
        conn.close()
        return rows
    except Exception as e:
        logger.error(f"DB 조회 실패: {e}")
        return []


# ── 제작물 수집 ───────────────────────────────────────────
def get_assets_for_script(script_id: int) -> dict:
    """스크립트 ID 에 매핑된 이미지·오디오·영상 수집"""

    # ── 이미지 ──
    img_dir = IMAGE_DIR / f"script_{script_id}"
    images: list[dict] = []
    if img_dir.exists():
        for f in sorted(
            list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png"))
        ):
            images.append({
                "name": f.name,
                "path": str(f),
                "url": f"/static/images/script_{script_id}/{f.name}",
                "size": f.stat().st_size,
            })

    # ── 오디오 ──
    audios: list[dict] = []
    patterns = [f"script_{script_id}_*.mp3", f"shorts_script_{script_id}*.mp3"]
    for pat in patterns:
        for f in sorted(AUDIO_DIR.glob(pat)):
            dur = _ffprobe_duration(str(f))
            audios.append({
                "name": f.name,
                "path": str(f),
                "url": f"/output/audio/{f.name}",
                "size": f.stat().st_size,
                "duration": dur,
                "duration_str": format_duration(dur),
            })

    # ── 영상 (일반 + 숏츠) ──
    videos: list[dict] = []
    for vdir in [VIDEO_DIR, SHORTS_DIR]:
        for f in sorted(vdir.glob(f"*script_{script_id}*.mp4")):
            dur = _ffprobe_duration(str(f))
            rel = f"output/{vdir.name}/{f.name}"
            videos.append({
                "name": f.name,
                "path": str(f),
                "url": f"/{rel}",
                "size": f.stat().st_size,
                "duration": dur,
                "duration_str": format_duration(dur),
            })

    return {"images": images, "audios": audios, "videos": videos}


def get_unassigned_assets() -> dict:
    """미분류(스크립트 미매핑) 자료 수집"""
    images: list[dict] = []
    un_dir = IMAGE_DIR / "unassigned"
    if un_dir.exists():
        for f in sorted(
            list(un_dir.glob("*.jpg")) + list(un_dir.glob("*.png"))
        ):
            images.append({
                "name": f.name,
                "path": str(f),
                "url": f"/static/images/unassigned/{f.name}",
                "size": f.stat().st_size,
            })

    audios: list[dict] = []
    for f in sorted(AUDIO_DIR.glob("*.mp3")):
        if f.name.startswith("script_") or f.name.startswith("shorts_script_"):
            continue
        audios.append({
            "name": f.name,
            "path": str(f),
            "url": f"/output/audio/{f.name}",
            "size": f.stat().st_size,
        })

    videos: list[dict] = []
    for f in sorted(VIDEO_DIR.glob("*.mp4")):
        if "script_" in f.name:
            continue
        dur = _ffprobe_duration(str(f))
        videos.append({
            "name": f.name,
            "path": str(f),
            "url": f"/output/video/{f.name}",
            "size": f.stat().st_size,
            "duration": dur,
            "duration_str": format_duration(dur),
        })

    return {"images": images, "audios": audios, "videos": videos}


# ── 삭제 헬퍼 ─────────────────────────────────────────────
def _delete_file(path: str, name: str, refresh_fn):
    """단일 파일 삭제 후 UI 갱신"""
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
            logger.info(f"🗑️  삭제: {path}")
            ui.notify(f"🗑️ {name} 삭제됨", type="positive")
        else:
            ui.notify(f"⚠️ 파일 없음: {name}", type="warning")
    except Exception as e:
        logger.error(f"삭제 실패: {e}")
        ui.notify(f"❌ 삭제 실패: {e}", type="negative")
    refresh_fn()


def _delete_all_images_for_script(script_id: int, refresh_fn):
    """스크립트 이미지 폴더 전체 삭제"""
    img_dir = IMAGE_DIR / f"script_{script_id}"
    if img_dir.exists():
        cnt = sum(1 for _ in img_dir.iterdir())
        shutil.rmtree(img_dir)
        img_dir.mkdir(parents=True, exist_ok=True)   # 빈 폴더 재생성
        logger.info(f"🗑️  script_{script_id} 이미지 {cnt}장 전체 삭제")
        ui.notify(f"🗑️ script_{script_id} 이미지 {cnt}장 전체 삭제", type="positive")
    else:
        ui.notify("⚠️ 이미지 폴더 없음", type="warning")
    # 캐시도 제거
    try:
        _generator.clear_cache_for_script(script_id)
    except Exception:
        pass
    refresh_fn()


# ── 메인 UI ───────────────────────────────────────────────
def create():
    """제작물 브라우저 페이지 생성"""

    ui.label("📦 전체 제작물 브라우저").classes("text-2xl font-bold mb-4")
    ui.label(
        "스크립트별 이미지·오디오·영상을 조회하고, 개별 또는 일괄 삭제할 수 있습니다."
    ).classes("text-gray-600 mb-2")

    # ── 통계 카드 ──
    scripts = get_scripts_from_db()

    total_images = sum(
        len(
            list((IMAGE_DIR / f"script_{s[0]}").glob("*.jpg"))
            + list((IMAGE_DIR / f"script_{s[0]}").glob("*.png"))
        )
        for s in scripts
        if (IMAGE_DIR / f"script_{s[0]}").exists()
    )
    unassigned_count = (
        len(
            list((IMAGE_DIR / "unassigned").glob("*.jpg"))
            + list((IMAGE_DIR / "unassigned").glob("*.png"))
        )
        if (IMAGE_DIR / "unassigned").exists()
        else 0
    )
    total_audios = len(list(AUDIO_DIR.glob("script_*.mp3"))) + len(
        list(AUDIO_DIR.glob("shorts_script_*.mp3"))
    )
    total_videos = len(list(VIDEO_DIR.glob("*.mp4"))) + len(
        list(SHORTS_DIR.glob("*.mp4"))
    )

    shorts_count = sum(1 for s in scripts if s[4] == "shorts")
    long_count = len(scripts) - shorts_count

    with ui.row().classes("gap-4 mb-6 flex-wrap"):
        with ui.card().classes("p-3"):
            ui.label(
                f"📝 스크립트: {len(scripts)}개 "
                f"(📱숏츠 {shorts_count} / 🎬롱폼 {long_count})"
            )
        with ui.card().classes("p-3"):
            ui.label(f"🖼️ 이미지: {total_images}장 (+미분류 {unassigned_count}장)")
        with ui.card().classes("p-3"):
            ui.label(f"🔊 오디오: {total_audios}개")
        with ui.card().classes("p-3"):
            ui.label(f"🎬 영상: {total_videos}개")

    # ── 스크립트별 제작물 ──
    ui.label("📋 스크립트별 제작물").classes("text-xl font-bold mt-4 mb-2")

    asset_container = ui.column().classes("w-full gap-4")

    def render_assets():
        """전체 자산 목록 (재)렌더링"""
        asset_container.clear()
        with asset_container:
            for sid, title, lang, content_len, fmt, genre in scripts:
                assets = get_assets_for_script(sid)
                img_c = len(assets["images"])
                aud_c = len(assets["audios"])
                vid_c = len(assets["videos"])
                has_any = (img_c + aud_c + vid_c) > 0
                fmt_badge = "📱" if fmt == "shorts" else "🎬"

                with ui.expansion(
                    f"{'✅' if has_any else '⬜'} {fmt_badge} ID:{sid} │ "
                    f"{title} ({lang}/{genre}) │ "
                    f"🖼️{img_c}  🔊{aud_c}  🎬{vid_c}",
                    icon="folder" if has_any else "folder_open",
                ).classes("w-full"):

                    if not has_any:
                        ui.label("제작물이 아직 없습니다.").classes(
                            "text-gray-500 italic"
                        )
                        continue

                    # ───── 이미지 ─────
                    if assets["images"]:
                        with ui.row().classes("items-center gap-2 mt-2"):
                            ui.label(f"🖼️ 이미지 ({img_c}장)").classes("font-bold")
                            ui.button(
                                "🗑️ 이미지 전체삭제",
                                on_click=lambda _sid=sid: _delete_all_images_for_script(
                                    _sid, render_assets
                                ),
                            ).props("dense flat size=xs color=red")

                        with ui.row().classes("flex-wrap gap-2"):
                            for img in assets["images"]:
                                with ui.card().classes("p-1 relative"):
                                    ui.image(img["url"]).classes(
                                        "w-32 h-20 object-cover rounded"
                                    )
                                    ui.label(
                                        f"{img['name']} ({format_size(img['size'])})"
                                    ).classes("text-xs text-center")
                                    ui.button(
                                        "✕",
                                        on_click=lambda _p=img["path"], _n=img[
                                            "name"
                                        ]: _delete_file(_p, _n, render_assets),
                                    ).props(
                                        "dense flat size=xs color=red"
                                    ).classes("absolute top-0 right-0")

                    # ───── 오디오 ─────
                    if assets["audios"]:
                        ui.label(f"🔊 오디오 ({aud_c}개)").classes(
                            "font-bold mt-2"
                        )
                        for aud in assets["audios"]:
                            with ui.row().classes("items-center gap-2"):
                                ui.audio(aud["url"]).classes("w-64")
                                ui.label(
                                    f"{aud['name']} │ {aud['duration_str']} │ "
                                    f"{format_size(aud['size'])}"
                                ).classes("text-sm")
                                ui.button(
                                    "🗑️",
                                    on_click=lambda _p=aud["path"], _n=aud[
                                        "name"
                                    ]: _delete_file(_p, _n, render_assets),
                                ).props("dense flat size=xs color=red")

                    # ───── 영상 ─────
                    if assets["videos"]:
                        ui.label(f"🎬 영상 ({vid_c}개)").classes(
                            "font-bold mt-2"
                        )
                        for vid in assets["videos"]:
                            with ui.card().classes("p-2"):
                                with ui.row().classes("items-start gap-4"):
                                    ui.video(vid["url"]).classes("w-96")
                                    with ui.column():
                                        ui.label(
                                            f"{vid['name']} │ "
                                            f"{vid['duration_str']} │ "
                                            f"{format_size(vid['size'])}"
                                        ).classes("text-sm")
                                        ui.button(
                                            "🗑️ 삭제",
                                            on_click=lambda _p=vid["path"], _n=vid[
                                                "name"
                                            ]: _delete_file(
                                                _p, _n, render_assets
                                            ),
                                        ).props("dense flat size=sm color=red")

            # ───── 미분류 자료 ─────
            unassigned = get_unassigned_assets()
            un_total = (
                len(unassigned["images"])
                + len(unassigned["audios"])
                + len(unassigned["videos"])
            )

            if un_total > 0:
                with ui.expansion(
                    f"📂 미분류 자료 │ 🖼️{len(unassigned['images'])} "
                    f"🔊{len(unassigned['audios'])} 🎬{len(unassigned['videos'])}",
                    icon="folder_special",
                ).classes("w-full"):

                    if unassigned["images"]:
                        ui.label(
                            f"🖼️ 미분류 이미지 ({len(unassigned['images'])}장)"
                        ).classes("font-bold mt-2")
                        with ui.row().classes("flex-wrap gap-2"):
                            for img in unassigned["images"]:
                                with ui.card().classes("p-1 relative"):
                                    ui.image(img["url"]).classes(
                                        "w-32 h-20 object-cover rounded"
                                    )
                                    ui.label(img["name"]).classes(
                                        "text-xs text-center"
                                    )
                                    ui.button(
                                        "✕",
                                        on_click=lambda _p=img["path"], _n=img[
                                            "name"
                                        ]: _delete_file(_p, _n, render_assets),
                                    ).props(
                                        "dense flat size=xs color=red"
                                    ).classes("absolute top-0 right-0")

                    if unassigned["audios"]:
                        ui.label(
                            f"🔊 기타 오디오 ({len(unassigned['audios'])}개)"
                        ).classes("font-bold mt-2")
                        for aud in unassigned["audios"]:
                            with ui.row().classes("items-center gap-2"):
                                ui.label(
                                    f"{aud['name']} ({format_size(aud['size'])})"
                                ).classes("text-sm")
                                ui.button(
                                    "🗑️",
                                    on_click=lambda _p=aud["path"], _n=aud[
                                        "name"
                                    ]: _delete_file(_p, _n, render_assets),
                                ).props("dense flat size=xs color=red")

                    if unassigned["videos"]:
                        ui.label(
                            f"🎬 기타 영상 ({len(unassigned['videos'])}개)"
                        ).classes("font-bold mt-2")
                        for vid in unassigned["videos"]:
                            with ui.card().classes("p-2"):
                                with ui.row().classes("items-start gap-4"):
                                    ui.video(vid["url"]).classes("w-96")
                                    with ui.column():
                                        ui.label(
                                            f"{vid['name']} │ "
                                            f"{vid['duration_str']}"
                                        ).classes("text-sm")
                                        ui.button(
                                            "🗑️ 삭제",
                                            on_click=lambda _p=vid[
                                                "path"
                                            ], _n=vid["name"]: _delete_file(
                                                _p, _n, render_assets
                                            ),
                                        ).props("dense flat size=sm color=red")

    render_assets()

    # ── 하단 버튼 ──
    ui.button("🔄 새로고침", on_click=render_assets).classes("mt-4")
