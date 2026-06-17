"""
Full Lazada SG competitor social media report pipeline.
Wave 1: Instagram (parallel) -> Wave 2: TikTok (parallel) -> stats + report text
"""

import urllib.request, json, time, sys, os, threading
from datetime import datetime

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr)
    sys.exit(1)

TODAY = datetime.utcnow()
DATE_LABEL = TODAY.strftime('%-d %b %Y')   # e.g. "17 Jun 2026"

# ── Apify helpers ─────────────────────────────────────────────────────────────

def apify_get(path):
    sep = '&' if '?' in path else '?'
    url = f'https://api.apify.com/v2/{path}{sep}token={API_KEY}'
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
        return json.loads(r.read())


def apify_post(path, body):
    url = f'https://api.apify.com/v2/{path}?token={API_KEY}'
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def start_run(actor, body, label):
    try:
        r = apify_post(f'acts/{actor}/runs', body)
        rid = r['data']['id']
        print(f'[START] {label} -> {rid}', file=sys.stderr, flush=True)
        return rid
    except Exception as e:
        print(f'[ERROR] start {label}: {e}', file=sys.stderr, flush=True)
        return None


def poll_run(rid, label, result_box, key, max_polls=36):
    """Poll until terminal status; store final run data in result_box[key]."""
    last = {'defaultDatasetId': '', 'status': 'TIMEOUT'}
    for i in range(max_polls):
        try:
            d = apify_get(f'actor-runs/{rid}')['data']
            last = d
            s = d['status']
            print(f'[POLL] {label} #{i+1}: {s}', file=sys.stderr, flush=True)
            if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                break
        except Exception as e:
            print(f'[POLL] {label} error: {e}', file=sys.stderr, flush=True)
        time.sleep(10)
    result_box[key] = last


def fetch_items(dataset_id, limit=50):
    if not dataset_id:
        return []
    try:
        data = apify_get(f'datasets/{dataset_id}/items?limit={limit}')
        if isinstance(data, list):
            return data
        return data.get('data', {}).get('items', []) if isinstance(data, dict) else []
    except Exception as e:
        print(f'[ERROR] dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


# ── Wave runner ───────────────────────────────────────────────────────────────

def run_wave(wave_defs):
    """
    wave_defs: list of (key, actor, body)
    Returns dict key -> list[item]
    """
    run_ids = {}
    for key, actor, body in wave_defs:
        rid = start_run(actor, body, key)
        run_ids[key] = rid

    run_data = {}
    threads = []
    for key, actor, body in wave_defs:
        rid = run_ids.get(key)
        if not rid:
            run_data[key] = {'defaultDatasetId': '', 'status': 'FAILED'}
            continue
        t = threading.Thread(target=poll_run, args=(rid, key, run_data, key), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    items = {}
    for key, actor, body in wave_defs:
        d = run_data.get(key, {})
        status = d.get('status', 'UNKNOWN')
        dataset_id = d.get('defaultDatasetId', '')
        print(f'[WAVE] {key} finished status={status} dataset={dataset_id}', file=sys.stderr, flush=True)
        posts = fetch_items(dataset_id)
        items[key] = posts
        print(f'[DONE] {key}: {len(posts)} items', file=sys.stderr, flush=True)
    return items


# ── Stats ─────────────────────────────────────────────────────────────────────

FOLLOWERS = {
    'lazada_ig': 214_000,
    'shopee_ig': 482_000,
    'lazada_tt': 95_000,
    'shopee_tt': 850_000,
}


def ig_stats(posts):
    n = len(posts)
    likes = sum(p.get('likesCount', 0) or 0 for p in posts)
    comments = sum(p.get('commentsCount', 0) or 0 for p in posts)
    plays = sum((p.get('videoPlayCount', 0) or p.get('videoViewCount', 0) or 0) for p in posts)
    shares = 0  # IG API does not surface shares
    videos = sum(1 for p in posts if p.get('type', '') in ('Video', 'Reel', 'video', 'reel') or p.get('isVideo', False))
    return dict(n=n, likes=likes, comments=comments, plays=plays, shares=shares, videos=videos)


def tt_stats(posts):
    n = len(posts)
    likes = sum(p.get('diggCount', 0) or 0 for p in posts)
    comments = sum(p.get('commentCount', 0) or 0 for p in posts)
    plays = sum(p.get('playCount', 0) or 0 for p in posts)
    shares = sum(p.get('shareCount', 0) or 0 for p in posts)
    videos = n  # TikTok is all video
    return dict(n=n, likes=likes, comments=comments, plays=plays, shares=shares, videos=videos)


def avg_er(stats, key):
    n = stats['n']
    if n == 0:
        return 0.0
    followers = FOLLOWERS.get(key, 1)
    eng = (stats['likes'] + stats['comments'] + stats.get('shares', 0))
    return round(eng / n / followers * 100, 2)


# ── Chart builders ────────────────────────────────────────────────────────────

def bar40(val_a, val_b, label_a='Lazada', label_b='Shopee', width=40):
    """Head-to-head horizontal bar (40 chars)."""
    total = val_a + val_b
    if total == 0:
        fa = fb = width // 2
    else:
        fa = round(val_a / total * width)
        fb = width - fa
    bar_a = '█' * fa + '░' * (width - fa)
    bar_b = '░' * (width - fb) + '█' * fb
    pct_a = round(val_a / total * 100) if total else 0
    pct_b = 100 - pct_a
    lines = [
        f'{label_a:<8} {bar_a} {_fmt(val_a)} ({pct_a}%)',
        f'{label_b:<8} {bar_b} {_fmt(val_b)} ({pct_b}%)',
    ]
    return '\n'.join(lines)


def content_bar(videos, total, width=14):
    """14-char content-mix bar: V=video, P=photo."""
    if total == 0:
        return '░' * width
    vf = round(videos / total * width)
    pf = width - vf
    return '▶' * vf + '◼' * pf


def _fmt(n):
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n/1_000:.1f}K'
    return str(n)


def top5_posts_ig(posts, brand):
    scored = []
    for p in posts:
        eng = (p.get('likesCount', 0) or 0) + (p.get('commentsCount', 0) or 0)
        url = p.get('url', p.get('shortCode', ''))
        caption = (p.get('caption') or '')[:80].replace('\n', ' ')
        ts = p.get('timestamp', '')[:10] if p.get('timestamp') else ''
        ptype = p.get('type', 'Post')
        scored.append((eng, url, caption, ts, ptype))
    scored.sort(key=lambda x: x[0], reverse=True)
    lines = [f'  Top 5 Instagram posts — {brand}']
    for rank, (eng, url, caption, ts, ptype) in enumerate(scored[:5], 1):
        lines.append(f'  {rank}. [{ptype}] {ts} | +{_fmt(eng)} eng | {caption[:60]}')
        if url:
            lines.append(f'     {url}')
    return '\n'.join(lines)


def top5_posts_tt(posts, brand):
    scored = []
    for p in posts:
        plays = p.get('playCount', 0) or 0
        likes = p.get('diggCount', 0) or 0
        comments = p.get('commentCount', 0) or 0
        shares = p.get('shareCount', 0) or 0
        eng = likes + comments + shares
        url = p.get('webVideoUrl', p.get('authorMeta', {}).get('profileUrl', ''))
        desc = (p.get('text', p.get('desc', '')) or '')[:80].replace('\n', ' ')
        ts = ''
        ct = p.get('createTime', p.get('createTimeISO', ''))
        if ct:
            try:
                if isinstance(ct, int):
                    ts = datetime.utcfromtimestamp(ct).strftime('%Y-%m-%d')
                else:
                    ts = str(ct)[:10]
            except Exception:
                ts = str(ct)[:10]
        scored.append((plays, eng, url, desc, ts))
    scored.sort(key=lambda x: x[0], reverse=True)
    lines = [f'  Top 5 TikTok posts — {brand}']
    for rank, (plays, eng, url, desc, ts) in enumerate(scored[:5], 1):
        lines.append(f'  {rank}. {ts} | {_fmt(plays)} plays | +{_fmt(eng)} eng | {desc[:60]}')
        if url:
            lines.append(f'     {url}')
    return '\n'.join(lines)


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(all_items):
    lz_ig = ig_stats(all_items.get('lazada_ig', []))
    sh_ig = ig_stats(all_items.get('shopee_ig', []))
    lz_tt = tt_stats(all_items.get('lazada_tt', []))
    sh_tt = tt_stats(all_items.get('shopee_tt', []))

    lz_ig_er = avg_er(lz_ig, 'lazada_ig')
    sh_ig_er = avg_er(sh_ig, 'shopee_ig')
    lz_tt_er = avg_er(lz_tt, 'lazada_tt')
    sh_tt_er = avg_er(sh_tt, 'shopee_tt')

    ig_er_winner = 'Lazada' if lz_ig_er >= sh_ig_er else 'Shopee'
    ig_er_loser  = 'Shopee' if ig_er_winner == 'Lazada' else 'Lazada'

    tt_total_plays = lz_tt['plays'] + sh_tt['plays']
    lz_tt_share_pct = round(lz_tt['plays'] / tt_total_plays * 100) if tt_total_plays else 0
    sh_tt_share_pct = 100 - lz_tt_share_pct

    likes_gap = abs(lz_ig['likes'] - sh_ig['likes'])
    likes_leader = 'Shopee' if sh_ig['likes'] > lz_ig['likes'] else 'Lazada'
    likes_trailer = 'Lazada' if likes_leader == 'Shopee' else 'Shopee'

    sep  = '═' * 60
    sep2 = '─' * 60

    lines = []
    lines.append(sep)
    lines.append(f'  COMPETITOR SOCIAL REPORT — {DATE_LABEL.upper()}')
    lines.append(f'  Lazada SG vs Shopee SG | Instagram + TikTok')
    lines.append(sep)

    # ── Executive Summary ────────────────────────────────────────
    lines.append('')
    lines.append('EXECUTIVE SUMMARY')
    lines.append(sep2)

    # 3-sentence summary
    s1 = (f'On TikTok, combined reach totalled {_fmt(tt_total_plays)} video plays, '
          f'with Lazada capturing {lz_tt_share_pct}% ({_fmt(lz_tt["plays"])}) '
          f'versus Shopee\'s {sh_tt_share_pct}% ({_fmt(sh_tt["plays"])}).')
    s2 = (f'On Instagram, {ig_er_winner} leads engagement rate at {max(lz_ig_er, sh_ig_er):.2f}% avg ER '
          f'compared to {ig_er_loser}\'s {min(lz_ig_er, sh_ig_er):.2f}%, '
          f'suggesting {ig_er_winner}\'s content mix resonates more strongly with its audience.')
    s3 = (f'{likes_leader} outpaces {likes_trailer} by {_fmt(likes_gap)} Instagram likes '
          f'({_fmt(max(lz_ig["likes"], sh_ig["likes"]))} vs {_fmt(min(lz_ig["likes"], sh_ig["likes"]))}); '
          f'{likes_trailer} should increase video/Reel frequency and test promotional hooks '
          f'to close this visibility gap.')

    lines.append(s1)
    lines.append(s2)
    lines.append(s3)

    # ── Instagram Section ────────────────────────────────────────
    lines.append('')
    lines.append('━' * 60)
    lines.append('  INSTAGRAM')
    lines.append('━' * 60)

    def ig_table(st, key, name):
        er = avg_er(st, key)
        return [
            f'  {name}',
            f'    Posts analysed : {st["n"]}',
            f'    Total likes     : {_fmt(st["likes"])}',
            f'    Total comments  : {_fmt(st["comments"])}',
            f'    Video/Reel count: {st["videos"]} / {st["n"]}',
            f'    Avg ER%         : {er:.2f}%',
        ]

    lines += ig_table(lz_ig, 'lazada_ig', 'Lazada SG (@Lazada_SG)')
    lines.append('')
    lines += ig_table(sh_ig, 'shopee_ig', 'Shopee SG (@shopee_SG)')

    lines.append('')
    lines.append('  HEAD-TO-HEAD — Instagram Likes (last 15 posts)')
    lines.append('  ' + bar40(lz_ig['likes'], sh_ig['likes'], 'Lazada', 'Shopee'))
    lines.append('')
    lines.append('  HEAD-TO-HEAD — Instagram Comments')
    lines.append('  ' + bar40(lz_ig['comments'], sh_ig['comments'], 'Lazada', 'Shopee'))
    lines.append('')
    lines.append('  HEAD-TO-HEAD — Instagram Avg ER%')
    lines.append('  ' + bar40(int(lz_ig_er * 100), int(sh_ig_er * 100), 'Lazada', 'Shopee'))

    lines.append('')
    lines.append('  CONTENT MIX (▶=Video/Reel  ◼=Photo)')
    lz_cm = content_bar(lz_ig['videos'], lz_ig['n'])
    sh_cm = content_bar(sh_ig['videos'], sh_ig['n'])
    lines.append(f'  Lazada  [{lz_cm}]  {lz_ig["videos"]}V / {lz_ig["n"] - lz_ig["videos"]}P')
    lines.append(f'  Shopee  [{sh_cm}]  {sh_ig["videos"]}V / {sh_ig["n"] - sh_ig["videos"]}P')

    lines.append('')
    lines.append(sep2)
    lines.append(top5_posts_ig(all_items.get('lazada_ig', []), 'Lazada SG'))
    lines.append('')
    lines.append(top5_posts_ig(all_items.get('shopee_ig', []), 'Shopee SG'))

    # ── TikTok Section ───────────────────────────────────────────
    lines.append('')
    lines.append('━' * 60)
    lines.append('  TIKTOK')
    lines.append('━' * 60)

    def tt_table(st, key, name):
        er = avg_er(st, key)
        return [
            f'  {name}',
            f'    Videos analysed : {st["n"]}',
            f'    Total plays     : {_fmt(st["plays"])}',
            f'    Total likes     : {_fmt(st["likes"])}',
            f'    Total comments  : {_fmt(st["comments"])}',
            f'    Total shares    : {_fmt(st["shares"])}',
            f'    Avg ER%         : {er:.2f}%',
        ]

    lines += tt_table(lz_tt, 'lazada_tt', 'Lazada SG (@Lazada_SG)')
    lines.append('')
    lines += tt_table(sh_tt, 'shopee_tt', 'Shopee SG (@shopeesg)')

    lines.append('')
    lines.append('  HEAD-TO-HEAD — TikTok Plays')
    lines.append('  ' + bar40(lz_tt['plays'], sh_tt['plays'], 'Lazada', 'Shopee'))
    lines.append('')
    lines.append('  HEAD-TO-HEAD — TikTok Likes')
    lines.append('  ' + bar40(lz_tt['likes'], sh_tt['likes'], 'Lazada', 'Shopee'))
    lines.append('')
    lines.append('  HEAD-TO-HEAD — TikTok Shares')
    lines.append('  ' + bar40(lz_tt['shares'], sh_tt['shares'], 'Lazada', 'Shopee'))
    lines.append('')
    lines.append('  HEAD-TO-HEAD — TikTok Avg ER%')
    lines.append('  ' + bar40(int(lz_tt_er * 100), int(sh_tt_er * 100), 'Lazada', 'Shopee'))

    lines.append('')
    lines.append(sep2)
    lines.append(top5_posts_tt(all_items.get('lazada_tt', []), 'Lazada SG'))
    lines.append('')
    lines.append(top5_posts_tt(all_items.get('shopee_tt', []), 'Shopee SG'))

    lines.append('')
    lines.append(sep)
    lines.append(f'  Generated {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}')
    lines.append(f'  Data: Apify (apify~instagram-scraper, clockworks~free-tiktok-scraper)')
    lines.append(f'  Sample size: 15 posts/videos per brand per platform')
    lines.append(sep)

    report = '\n'.join(lines)
    # Also expose summary sentences for external use
    summary = f'{s1}\n{s2}\n{s3}'
    return report, summary


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print(f'[PIPELINE] Starting — {DATE_LABEL}', file=sys.stderr, flush=True)

    # Wave 1: Instagram
    print('[WAVE 1] Launching Instagram scrapers...', file=sys.stderr, flush=True)
    wave1 = [
        ('lazada_ig', 'apify~instagram-scraper', {
            'directUrls': ['https://www.instagram.com/Lazada_SG/'],
            'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
        }),
        ('shopee_ig', 'apify~instagram-scraper', {
            'directUrls': ['https://www.instagram.com/shopee_SG/'],
            'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
        }),
    ]
    w1_items = run_wave(wave1)

    # Wave 2: TikTok
    print('[WAVE 2] Launching TikTok scrapers...', file=sys.stderr, flush=True)
    wave2 = [
        ('lazada_tt', 'clockworks~free-tiktok-scraper', {
            'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
            'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
        }),
        ('shopee_tt', 'clockworks~free-tiktok-scraper', {
            'profiles': ['shopeesg'], 'resultsPerPage': 15,
            'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
        }),
    ]
    w2_items = run_wave(wave2)

    all_items = {**w1_items, **w2_items}

    # Save raw JSON
    out_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(out_dir, 'apify_results.json')
    with open(json_path, 'w') as f:
        json.dump(all_items, f, indent=2)
    print(f'[SAVED] Raw data -> {json_path}', file=sys.stderr, flush=True)

    report, summary = build_report(all_items)

    # Save report text
    txt_path = os.path.join(out_dir, 'report_output.txt')
    with open(txt_path, 'w') as f:
        f.write(report)
    print(f'[SAVED] Report -> {txt_path}', file=sys.stderr, flush=True)

    # Print report to stdout (captured by workflow)
    print(report)
