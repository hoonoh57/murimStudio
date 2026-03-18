"""제작물 브라우저 – 스크립트별 이미지/오디오/영상 통합 조회"""

import os
import sqlite3
import subprocess
import logging
from pathlib import Path
from nicegui import ui

logger = logging.getLogger(__name__)

IMAGE_DIR = Path("static/images")
AUDIO_DIR = Path("output/audio")
VIDEO_DIR = Path("output/video")
DB_PATH = "app.db"


def get_audio_duration(path: str) -> float:
    """ffprobe로 오디오 길이(초) 반환"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=10
        )
        import json
        data = json.loads(r.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 0.0


def get_video_duration(path: str) -> float:
    """ffprobe로 영상 길이(초) 반환"""
    return get_audio_duration(path)


def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def get_scripts_from_db() -> list:
    """DB에서 스크립트 목록 조회"""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT s.id, COALESCE(p.title, '제목없음') as title, s.language,
                   LENGTH(s.content) as content_len
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


def get_assets_for_script(script_id: int) -> dict:
    """스크립트 ID별 모든 제작물 수집"""
    # 이미지
    img_dir = IMAGE_DIR / f"script_{script_id}"
    images = []
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.jpg")):
            images.append({
                "name": f.name,
                "path": str(f),
                "url": f"/static/images/script_{script_id}/{f.name}",
                "size": f.stat().st_size
            })
        for f in sorted(img_dir.glob("*.png")):
            images.append({
                "name": f.name,
                "path": str(f),
                "url": f"/static/images/script_{script_id}/{f.name}",
                "size": f.stat().st_size
            })

    # 오디오
    audios = []
    for f in sorted(AUDIO_DIR.glob(f"script_{script_id}_*.mp3")):
        dur = get_audio_duration(str(f))
        audios.append({
            "name": f.name,
            "path": str(f),
            "url": f"/output/audio/{f.name}",
            "size": f.stat().st_size,
            "duration": dur,
            "duration_str": format_duration(dur)
        })

    # 영상
    videos = []
    for f in sorted(VIDEO_DIR.glob(f"script_{script_id}_*.mp4")):
        dur = get_video_duration(str(f))
        videos.append({
            "name": f.name,
            "path": str(f),
            "url": f"/output/video/{f.name}",
            "size": f.stat().st_size,
            "duration": dur,
            "duration_str": format_duration(dur)
        })

    return {"images": images, "audios": audios, "videos": videos}


def get_unassigned_assets() -> dict:
    """미분류 이미지 + 기타 오디오/영상"""
    # 미분류 이미지
    unassigned_dir = IMAGE_DIR / "unassigned"
    images = []
    if unassigned_dir.exists():
        for f in sorted(unassigned_dir.glob("*.jpg")):
            images.append({
                "name": f.name,
                "path": str(f),
                "url": f"/static/images/unassigned/{f.name}",
                "size": f.stat().st_size
            })

    # 프리뷰/테스트 오디오
    audios = []
    for f in sorted(AUDIO_DIR.glob("*.mp3")):
        if f.name.startswith("script_"):
            continue  # 스크립트별 오디오는 제외
        audios.append({
            "name": f.name,
            "path": str(f),
            "url": f"/output/audio/{f.name}",
            "size": f.stat().st_size
        })

    # 기타 영상
    videos = []
    for f in sorted(VIDEO_DIR.glob("*.mp4")):
        if f.name.startswith("script_"):
            continue
        dur = get_video_duration(str(f))
        videos.append({
            "name": f.name,
            "path": str(f),
            "url": f"/output/video/{f.name}",
            "size": f.stat().st_size,
            "duration": dur,
            "duration_str": format_duration(dur)
        })

    return {"images": images, "audios": audios, "videos": videos}


def create():
    """제작물 브라우저 UI 생성"""

    ui.label("📦 전체 제작물 브라우저").classes("text-2xl font-bold mb-4")

    # === 통계 요약 ===
    scripts = get_scripts_from_db()

    total_images = sum(
        len(list((IMAGE_DIR / f"script_{s[0]}").glob("*.jpg")))
        for s in scripts if (IMAGE_DIR / f"script_{s[0]}").exists()
    )
    unassigned_count = len(list((IMAGE_DIR / "unassigned").glob("*.jpg"))) if (IMAGE_DIR / "unassigned").exists() else 0
    total_audios = len(list(AUDIO_DIR.glob("script_*.mp3")))
    total_videos = len(list(VIDEO_DIR.glob("*.mp4")))

    with ui.row().classes("gap-4 mb-6"):
        with ui.card().classes("p-3"):
            ui.label(f"📝 스크립트: {len(scripts)}개")
        with ui.card().classes("p-3"):
            ui.label(f"🖼️ 이미지: {total_images}장 (+미분류 {unassigned_count}장)")
        with ui.card().classes("p-3"):
            ui.label(f"🔊 오디오: {total_audios}개")
        with ui.card().classes("p-3"):
            ui.label(f"🎬 영상: {total_videos}개")

    # === 스크립트별 제작물 ===
    ui.label("📋 스크립트별 제작물").classes("text-xl font-bold mt-4 mb-2")

    asset_container = ui.column().classes("w-full gap-4")

    def render_assets():
        asset_container.clear()
        with asset_container:
            for sid, title, lang, content_len in scripts:
                assets = get_assets_for_script(sid)
                img_count = len(assets["images"])
                aud_count = len(assets["audios"])
                vid_count = len(assets["videos"])

                has_any = img_count + aud_count + vid_count > 0

                with ui.expansion(
                    f"{'✅' if has_any else '⬜'} ID:{sid} | {title} ({lang}) | "
                    f"🖼️{img_count} 🔊{aud_count} 🎬{vid_count}",
                    icon="folder" if has_any else "folder_open"
                ).classes("w-full"):

                    if not has_any:
                        ui.label("제작물이 아직 없습니다.").classes("text-gray-500 italic")
                        continue

                    # 이미지 섹션
                    if assets["images"]:
                        ui.label(f"🖼️ 이미지 ({img_count}장)").classes("font-bold mt-2")
                        with ui.row().classes("flex-wrap gap-2"):
                            for img in assets["images"]:
                                with ui.card().classes("p-1"):
                                    ui.image(img["url"]).classes("w-32 h-20 object-cover rounded")
                                    ui.label(f'{img["name"]} ({format_size(img["size"])})').classes("text-xs text-center")

                    # 오디오 섹션
                    if assets["audios"]:
                        ui.label(f"🔊 오디오 ({aud_count}개)").classes("font-bold mt-2")
                        for aud in assets["audios"]:
                            with ui.row().classes("items-center gap-2"):
                                ui.audio(aud["url"]).classes("w-64")
                                ui.label(
                                    f'{aud["name"]} | {aud["duration_str"]} | {format_size(aud["size"])}'
                                ).classes("text-sm")

                    # 영상 섹션
                    if assets["videos"]:
                        ui.label(f"🎬 영상 ({vid_count}개)").classes("font-bold mt-2")
                        for vid in assets["videos"]:
                            with ui.card().classes("p-2"):
                                ui.video(vid["url"]).classes("w-96")
                                ui.label(
                                    f'{vid["name"]} | {vid["duration_str"]} | {format_size(vid["size"])}'
                                ).classes("text-sm")

            # === 미분류 자료 ===
            unassigned = get_unassigned_assets()
            un_total = len(unassigned["images"]) + len(unassigned["audios"]) + len(unassigned["videos"])

            if un_total > 0:
                with ui.expansion(
                    f"📂 미분류 자료 | 🖼️{len(unassigned['images'])} 🔊{len(unassigned['audios'])} 🎬{len(unassigned['videos'])}",
                    icon="folder_special"
                ).classes("w-full"):

                    if unassigned["images"]:
                        ui.label(f"🖼️ 미분류 이미지 ({len(unassigned['images'])}장)").classes("font-bold mt-2")
                        with ui.row().classes("flex-wrap gap-2"):
                            for img in unassigned["images"]:
                                with ui.card().classes("p-1"):
                                    ui.image(img["url"]).classes("w-32 h-20 object-cover rounded")
                                    ui.label(f'{img["name"]}').classes("text-xs text-center")

                    if unassigned["audios"]:
                        ui.label(f"🔊 프리뷰/테스트 오디오 ({len(unassigned['audios'])}개)").classes("font-bold mt-2")
                        for aud in unassigned["audios"]:
                            with ui.row().classes("items-center gap-2"):
                                ui.label(f'{aud["name"]} ({format_size(aud["size"])})').classes("text-sm")

                    if unassigned["videos"]:
                        ui.label(f"🎬 기타 영상 ({len(unassigned['videos'])}개)").classes("font-bold mt-2")
                        for vid in unassigned["videos"]:
                            with ui.card().classes("p-2"):
                                ui.video(vid["url"]).classes("w-96")
                                ui.label(f'{vid["name"]} | {vid["duration_str"]}').classes("text-sm")

    render_assets()

    # 새로고침 버튼
    ui.button("🔄 새로고침", on_click=render_assets).classes("mt-4")
