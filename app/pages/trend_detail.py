"""트렌드 상세 페이지 — 작품별 수집 소스·AI 분석·스크립트 생성"""

import json
from nicegui import ui, app
from app.db import get_db


@ui.page('/trend/{title}')
async def trend_detail_page(title: str):
    from urllib.parse import unquote
    title = unquote(title)

    with ui.header().classes('bg-gray-900 text-white items-center'):
        ui.label('⚔️ 무협 팩토리').classes('text-xl font-bold')
        ui.space()
        ui.button('← 트렌드 목록', on_click=lambda: ui.navigate.to('/')).props('flat color=white')

    ui.label(f'📖 {title}').classes('text-2xl font-bold mt-4')

    # ─── AI 랭킹 정보 ───
    db = await get_db()
    try:
        async with db.execute(
            'SELECT rank, score, reason, episode_range, target_audience, collected_at '
            'FROM trend_results WHERE title = ? ORDER BY collected_at DESC LIMIT 1',
            (title,),
        ) as cursor:
            ai_row = await cursor.fetchone()

        # ─── 수집 소스 데이터 ───
        async with db.execute(
            'SELECT title, trend_score, source, genre, meta_json, collected_at '
            'FROM trend_cache WHERE title = ? ORDER BY collected_at DESC LIMIT 10',
            (title,),
        ) as cursor:
            cache_rows = [dict(r) for r in await cursor.fetchall()]

        # ─── 같은 키워드가 포함된 다른 수집 데이터 ───
        keywords = title.split()
        like_clauses = ' OR '.join(['title LIKE ?' for _ in keywords])
        like_params = [f'%{kw}%' for kw in keywords if len(kw) > 1]

        related_rows = []
        if like_params:
            like_clauses = ' OR '.join(['title LIKE ?' for _ in like_params])
            async with db.execute(
                f'SELECT DISTINCT title, trend_score, source, genre, meta_json, collected_at '
                f'FROM trend_cache WHERE ({like_clauses}) AND title != ? '
                f'ORDER BY trend_score DESC LIMIT 10',
                (*like_params, title),
            ) as cursor:
                related_rows = [dict(r) for r in await cursor.fetchall()]

        # ─── 스크립트 존재 여부 ───
        async with db.execute(
            'SELECT s.id, s.language, s.status, s.cost_usd, s.created_at, '
            'substr(s.content, 1, 300) as preview '
            'FROM scripts s JOIN projects p ON s.project_id = p.id '
            'WHERE p.title LIKE ? ORDER BY s.created_at DESC',
            (f'%{title}%',),
        ) as cursor:
            script_rows = [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()

    # ─── AI 분석 카드 ───
    ui.label('🤖 AI 분석').classes('text-lg font-bold mt-4 mb-2')
    if ai_row:
        ai = dict(ai_row)
        with ui.row().classes('w-full gap-4'):
            with ui.card().classes('flex-1'):
                ui.label('순위').classes('text-sm text-gray-500')
                ui.label(f'#{ai["rank"]}').classes('text-2xl font-bold text-blue-400')
            with ui.card().classes('flex-1'):
                ui.label('점수').classes('text-sm text-gray-500')
                ui.label(f'{ai["score"]}점').classes('text-2xl font-bold text-green-400')
            with ui.card().classes('flex-1'):
                ui.label('추천 회차').classes('text-sm text-gray-500')
                ui.label(ai.get('episode_range', 'N/A')).classes('text-lg font-bold')
            with ui.card().classes('flex-1'):
                ui.label('대상').classes('text-sm text-gray-500')
                ui.label(ai.get('target_audience', 'global')).classes('text-lg font-bold')
        with ui.card().classes('w-full mt-2'):
            ui.label('AI 추천 근거').classes('text-sm text-gray-500')
            ui.label(ai.get('reason', '—')).classes('text-base')
    else:
        ui.label('AI 랭킹 데이터가 없습니다. 트렌드 탭에서 수집을 먼저 실행하세요.').classes('text-gray-500')

    # ─── 수집 소스 상세 ───
    ui.label('📡 수집 소스 상세').classes('text-lg font-bold mt-6 mb-2')
    if cache_rows:
        for row in cache_rows:
            source = row.get('source', '')
            score = row.get('trend_score', 0)
            collected = row.get('collected_at', '')[:19]
            meta = {}
            try:
                meta = json.loads(row.get('meta_json', '{}'))
            except Exception:
                pass

            with ui.card().classes('w-full mb-2'):
                with ui.row().classes('items-center gap-4'):
                    # 소스별 아이콘
                    icon = {'YouTube': '🎬', 'Naver': '📗', 'Reddit': '💬'}.get(source, '📌')
                    ui.label(f'{icon} {source}').classes('font-bold text-base')
                    ui.label(f'점수: {score}').classes('text-sm')
                    ui.label(f'수집: {collected}').classes('text-sm text-gray-500')

                # 소스별 링크
                if source == 'YouTube' and meta.get('video_id'):
                    vid = meta['video_id']
                    channel = meta.get('channel', '')
                    ui.link(
                        f'▶ YouTube 영상 보기 (채널: {channel})',
                        f'https://www.youtube.com/watch?v={vid}',
                        new_tab=True,
                    ).classes('text-blue-400 text-sm')

                elif source == 'Naver' and meta.get('webtoon_id'):
                    wid = meta['webtoon_id']
                    star = meta.get('star_score', '')
                    ui.link(
                        f'📗 네이버 웹툰 보기 (별점: {star})',
                        f'https://comic.naver.com/webtoon/list?titleId={wid}',
                        new_tab=True,
                    ).classes('text-green-400 text-sm')

                elif source == 'Reddit' and meta.get('url'):
                    sub = meta.get('subreddit', '')
                    ups = meta.get('ups', 0)
                    ui.link(
                        f'💬 Reddit 글 보기 (r/{sub}, ↑{ups})',
                        meta['url'],
                        new_tab=True,
                    ).classes('text-orange-400 text-sm')
    else:
        ui.label('수집된 소스 데이터가 없습니다.').classes('text-gray-500')

    # ─── 기존 스크립트 ───
    ui.label('📝 생성된 스크립트').classes('text-lg font-bold mt-6 mb-2')
    if script_rows:
        for s in script_rows:
            with ui.card().classes('w-full mb-2'):
                with ui.row().classes('items-center gap-4'):
                    ui.label(f'ID: {s["id"]}').classes('font-bold')
                    ui.label(f'언어: {s["language"]}').classes('text-sm')
                    ui.label(f'상태: {s["status"]}').classes('text-sm')
                    ui.label(f'비용: ${s["cost_usd"]:.4f}').classes('text-sm')
                    ui.label(f'{s["created_at"][:19]}').classes('text-sm text-gray-500')
                ui.label(s.get('preview', '')).classes('text-sm text-gray-400 mt-1')
    else:
        ui.label('아직 스크립트가 없습니다.').classes('text-gray-500')

    # ─── 바로 스크립트 생성 버튼 ───
    ui.label('🚀 빠른 작업').classes('text-lg font-bold mt-6 mb-2')
    with ui.row().classes('gap-2'):
        async def quick_generate():
            ui.notify(f'"{title}" 스크립트 생성 시작...', color='blue')
            from app.services.script_factory import ScriptFactory
            factory = ScriptFactory()
            result = await factory.generate_script(
                title=title,
                episodes=ai.get('episode_range', '') if ai_row else '',
                duration_min=10,
                style='긴장감+감동',
                language='ko',
            )
            if result.get('status') == 'generated':
                ui.notify(f'스크립트 생성 완료! (비용: ${result.get("cost_usd", 0):.4f})', color='green')
                ui.navigate.to(f'/trend/{title}')  # 새로고침
            else:
                ui.notify('스크립트 생성 실패', color='red')

        ui.button('✍️ 한국어 스크립트 생성', on_click=quick_generate).props('color=primary')
        ui.button('← 트렌드 목록으로', on_click=lambda: ui.navigate.to('/')).props('color=grey')

    # ─── 연관 작품 ───
    if related_rows:
        ui.label('🔗 연관 작품').classes('text-lg font-bold mt-6 mb-2')
        for r in related_rows:
            with ui.row().classes('items-center gap-2'):
                from urllib.parse import quote
                ui.link(
                    f'{r["title"]} ({r["source"]}, {r["trend_score"]}점)',
                    f'/trend/{quote(r["title"])}',
                ).classes('text-blue-400')
