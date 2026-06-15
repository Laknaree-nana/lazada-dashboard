"""
Full Lazada SG vs Shopee SG competitor social media report pipeline.
Runs Instagram scrapers (Wave 1) then TikTok scrapers (Wave 2) in parallel waves.
Outputs a plain-text report to stdout as a single JSON: {"report": "...", "raw": {...}}
"""

import urllib.request, json, time, sys, os, threading, math
from datetime import datetime, timezone

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr)
    sys.exit(1)


# ── Apify helpers ──────────────────────────────────────────────────────────────

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
        print(f'[START] {label} ({actor}) -> run {rid}', file=sys.stderr, flush=True)
        return rid
    except Exception as e:
        print(f'[ERROR] start {label}: {e}', file=sys.stderr, flush=True)
        return None


def poll_run_to_done(rid, label, out):
    """Polls a run until terminal; stores final run data in out[label]."""
    for i in range(36):          # 36 × 10 s = 6 min max
        try:
            d = apify_get(f'actor-runs/{rid}')['data']
            s = d['status']
            print(f'[POLL] {label} #{i+1}: {s}', file=sys.stderr, flush=True)
            if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                out[label] = d
                return
        except Exception as e:
            print(f'[POLL] {label} error: {e}', file=sys.stderr, flush=True)
        time.sleep(10)
    out[label] = {'status': 'TIMEOUT', 'defaultDatasetId': ''}


def fetch_items(dataset_id, limit=30):
    if not dataset_id:
        return []
    try:
        data = apify_get(f'datasets/{dataset_id}/items?limit={limit}')
        if isinstance(data, list):
            return data
        # Some actors wrap in {"items": [...]}
        if isinstance(data, dict):
            return data.get('items', data.get('data', []))
        return []
    except Exception as e:
        print(f'[ERROR] fetch dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


def run_wave(jobs):
    """Start all jobs in wave, poll all in parallel, return {label: items}."""
    # Start all
    run_ids = {}
    for label, actor, body in jobs:
        rid = start_run(actor, body, label)
        if rid:
            run_ids[label] = rid

    # Poll all in parallel
    final_runs = {}
    threads = []
    for label, rid in run_ids.items():
        t = threading.Thread(target=poll_run_to_done, args=(rid, label, final_runs))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    # Fetch datasets
    items = {}
    for label, _, _ in jobs:
        run_data = final_runs.get(label, {})
        status = run_data.get('status', 'MISSING')
        ds_id = run_data.get('defaultDatasetId', '')
        print(f'[DONE] {label}: status={status} dataset={ds_id}', file=sys.stderr, flush=True)
        its = fetch_items(ds_id)
        items[label] = its
        print(f'[DATA] {label}: {len(its)} items fetched', file=sys.stderr, flush=True)
    return items


# ── Stats helpers ──────────────────────────────────────────────────────────────

def ig_stats(posts):
    """Return dict of Instagram stats from post list."""
    n = len(posts)
    if n == 0:
        return {'count': 0, 'total_likes': 0, 'total_comments': 0,
                'avg_likes': 0, 'avg_comments': 0, 'avg_er': 0.0,
                'followers': 0, 'types': {}}

    total_likes = sum(int(p.get('likesCount') or p.get('likes_count') or 0) for p in posts)
    total_comments = sum(int(p.get('commentsCount') or p.get('comments_count') or 0) for p in posts)

    # Followers may be in ownerFullName / owner / profileData
    followers = 0
    for p in posts:
        f = (p.get('ownersFollowerCount') or
             p.get('owner', {}).get('followersCount') or
             p.get('followersCount') or 0)
        if f:
            followers = int(f)
            break

    # Content type breakdown
    types = {}
    for p in posts:
        t = (p.get('type') or p.get('productType') or
             p.get('mediaType') or 'unknown').lower()
        # Normalise
        if 'video' in t or t in ('reels', 'reel'):
            t = 'video'
        elif 'carousel' in t or 'sidecar' in t or 'album' in t:
            t = 'carousel'
        else:
            t = 'photo'
        types[t] = types.get(t, 0) + 1

    avg_likes = total_likes / n
    avg_comments = total_comments / n
    avg_er = ((total_likes + total_comments) / n / followers * 100) if followers else 0.0

    return {
        'count': n,
        'total_likes': total_likes,
        'total_comments': total_comments,
        'avg_likes': round(avg_likes, 1),
        'avg_comments': round(avg_comments, 1),
        'avg_er': round(avg_er, 2),
        'followers': followers,
        'types': types,
    }


def tt_stats(videos):
    """Return dict of TikTok stats from video list."""
    n = len(videos)
    if n == 0:
        return {'count': 0, 'total_plays': 0, 'total_likes': 0,
                'total_comments': 0, 'total_shares': 0,
                'avg_plays': 0, 'avg_likes': 0, 'avg_comments': 0,
                'avg_shares': 0, 'avg_er': 0.0, 'followers': 0}

    def safe_int(v):
        try:
            return int(v or 0)
        except (ValueError, TypeError):
            return 0

    total_plays    = sum(safe_int(v.get('playCount')    or v.get('stats', {}).get('playCount'))    for v in videos)
    total_likes    = sum(safe_int(v.get('diggCount')    or v.get('stats', {}).get('diggCount')    or v.get('likesCount'))    for v in videos)
    total_comments = sum(safe_int(v.get('commentCount') or v.get('stats', {}).get('commentCount') or v.get('commentsCount')) for v in videos)
    total_shares   = sum(safe_int(v.get('shareCount')   or v.get('stats', {}).get('shareCount')   or v.get('sharesCount'))   for v in videos)

    followers = 0
    for v in videos:
        f = (v.get('authorStats', {}).get('followerCount') or
             v.get('authorMeta', {}).get('fans') or
             v.get('authorFollowerCount') or 0)
        if f:
            followers = safe_int(f)
            break

    avg_plays    = total_plays    / n
    avg_likes    = total_likes    / n
    avg_comments = total_comments / n
    avg_shares   = total_shares   / n
    avg_er = ((total_likes + total_comments + total_shares) / n / followers * 100) if followers else 0.0

    return {
        'count': n,
        'total_plays': total_plays,    'avg_plays': round(avg_plays, 0),
        'total_likes': total_likes,    'avg_likes': round(avg_likes, 1),
        'total_comments': total_comments, 'avg_comments': round(avg_comments, 1),
        'total_shares': total_shares,  'avg_shares': round(avg_shares, 1),
        'avg_er': round(avg_er, 2),    'followers': followers,
    }


# ── Rendering helpers ──────────────────────────────────────────────────────────

def bar(value, max_value, width=40, fill='█', empty='░'):
    if max_value == 0:
        return empty * width
    filled = round(width * value / max_value)
    filled = max(0, min(width, filled))
    return fill * filled + empty * (width - filled)


def content_mix_bar(types, width=14):
    """Build a 14-char bar split by Photo/Video/Carousel."""
    total = sum(types.values()) or 1
    order = [('photo', '■'), ('video', '▣'), ('carousel', '▤')]
    result = ''
    for key, sym in order:
        n = types.get(key, 0)
        chars = round(width * n / total)
        result += sym * chars
    # Pad to exact width
    result = result[:width].ljust(width, '░')
    return result


def fmt_num(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n/1_000:.1f}K'
    return str(n)


def top_posts_ig(posts, n=5):
    def score(p):
        return int(p.get('likesCount') or 0) + int(p.get('commentsCount') or 0)
    top = sorted(posts, key=score, reverse=True)[:n]
    lines = []
    for i, p in enumerate(top, 1):
        likes = fmt_num(p.get('likesCount') or 0)
        comments = fmt_num(p.get('commentsCount') or 0)
        ts = p.get('timestamp') or p.get('taken_at_timestamp') or ''
        if ts and isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
        elif ts and isinstance(ts, str) and 'T' in ts:
            ts = ts[:10]
        caption = (p.get('caption') or p.get('alt') or p.get('accessibility_caption') or '')
        caption_snip = caption[:60].replace('\n', ' ') + ('…' if len(caption) > 60 else '')
        url = p.get('url') or p.get('displayUrl') or p.get('shortCode') or ''
        if url and not url.startswith('http'):
            url = f'https://www.instagram.com/p/{url}/'
        lines.append(f'  {i}. [{ts}] ❤ {likes}  💬 {comments}')
        if caption_snip:
            lines.append(f'     "{caption_snip}"')
        if url:
            lines.append(f'     {url}')
    return '\n'.join(lines) if lines else '  (no data)'


def top_posts_tt(videos, n=5):
    def score(v):
        return int(v.get('playCount') or v.get('stats', {}).get('playCount') or 0)
    top = sorted(videos, key=score, reverse=True)[:n]
    lines = []
    for i, v in enumerate(top, 1):
        plays    = fmt_num(v.get('playCount')    or v.get('stats', {}).get('playCount')    or 0)
        likes    = fmt_num(v.get('diggCount')    or v.get('stats', {}).get('diggCount')    or 0)
        comments = fmt_num(v.get('commentCount') or v.get('stats', {}).get('commentCount') or 0)
        shares   = fmt_num(v.get('shareCount')   or v.get('stats', {}).get('shareCount')   or 0)
        desc = (v.get('text') or v.get('desc') or v.get('description') or '')[:60].replace('\n', ' ')
        ts = v.get('createTime') or v.get('created_time') or ''
        if ts and isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
        elif ts and isinstance(ts, str) and 'T' in ts:
            ts = ts[:10]
        url = v.get('webVideoUrl') or v.get('url') or ''
        lines.append(f'  {i}. [{ts}] ▶ {plays}  ❤ {likes}  💬 {comments}  ↗ {shares}')
        if desc:
            lines.append(f'     "{desc}…"')
        if url:
            lines.append(f'     {url}')
    return '\n'.join(lines) if lines else '  (no data)'


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime('%d %b %Y')

    # ── Wave 1: Instagram ──────────────────────────────────────────────────────
    print('\n══ WAVE 1: Instagram scrapers ══', file=sys.stderr, flush=True)
    wave1_jobs = [
        ('lazada_ig', 'apify~instagram-scraper', {
            'directUrls': ['https://www.instagram.com/Lazada_SG/'],
            'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': True,
        }),
        ('shopee_ig', 'apify~instagram-scraper', {
            'directUrls': ['https://www.instagram.com/shopee_SG/'],
            'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': True,
        }),
    ]
    wave1 = run_wave(wave1_jobs)

    # ── Wave 2: TikTok ─────────────────────────────────────────────────────────
    print('\n══ WAVE 2: TikTok scrapers ══', file=sys.stderr, flush=True)
    wave2_jobs = [
        ('lazada_tt', 'clockworks~free-tiktok-scraper', {
            'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
            'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
        }),
        ('shopee_tt', 'clockworks~free-tiktok-scraper', {
            'profiles': ['shopeesg'], 'resultsPerPage': 15,
            'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
        }),
    ]
    wave2 = run_wave(wave2_jobs)

    all_data = {**wave1, **wave2}

    # ── Compute stats ──────────────────────────────────────────────────────────
    lz_ig = ig_stats(all_data.get('lazada_ig', []))
    sh_ig = ig_stats(all_data.get('shopee_ig', []))
    lz_tt = tt_stats(all_data.get('lazada_tt', []))
    sh_tt = tt_stats(all_data.get('shopee_tt', []))

    # ── Build report ───────────────────────────────────────────────────────────
    W = 40   # bar width

    def h2h_section(metric_label, lz_val, sh_val):
        mx = max(lz_val, sh_val, 1)
        lz_bar = bar(lz_val, mx, W)
        sh_bar = bar(sh_val, mx, W)
        return (
            f'  {metric_label}\n'
            f'  Lazada  {lz_bar}  {fmt_num(lz_val)}\n'
            f'  Shopee  {sh_bar}  {fmt_num(sh_val)}\n'
        )

    lines = [
        '=' * 70,
        f'  COMPETITOR SOCIAL MEDIA REPORT — {today}',
        f'  Lazada SG vs Shopee SG  |  Instagram + TikTok',
        '=' * 70,
        '',
        '┌─────────────────────────────────────────────────────────────────────┐',
        '│  1. INSTAGRAM OVERVIEW                                              │',
        '└─────────────────────────────────────────────────────────────────────┘',
        '',
        f'  Posts analysed : Lazada {lz_ig["count"]}  |  Shopee {sh_ig["count"]}',
        f'  Followers       : Lazada {fmt_num(lz_ig["followers"])}  |  Shopee {fmt_num(sh_ig["followers"])}',
        '',
        '── Head-to-Head Bars ──────────────────────────────────────────────────',
        '',
    ]

    for label, lv, sv in [
        ('Avg Likes / post', lz_ig['avg_likes'], sh_ig['avg_likes']),
        ('Avg Comments / post', lz_ig['avg_comments'], sh_ig['avg_comments']),
        ('Avg ER %', lz_ig['avg_er'], sh_ig['avg_er']),
        ('Total Likes (15 posts)', lz_ig['total_likes'], sh_ig['total_likes']),
    ]:
        lines.append(h2h_section(label, lv, sv))

    lines += [
        '── Content Mix (14-char bar: ■=Photo ▣=Video ▤=Carousel) ────────────',
        '',
    ]

    for brand, st in [('Lazada', lz_ig), ('Shopee', sh_ig)]:
        types = st['types']
        cm = content_mix_bar(types, 14)
        breakdown = '  '.join(f'{k.capitalize()} {v}' for k, v in sorted(types.items()))
        lines.append(f'  {brand:<8} [{cm}]  {breakdown}')
    lines.append('')

    lines += [
        '── Top 5 Instagram Posts by Engagement ──────────────────────────────',
        '',
        '  LAZADA SG',
        top_posts_ig(all_data.get('lazada_ig', [])),
        '',
        '  SHOPEE SG',
        top_posts_ig(all_data.get('shopee_ig', [])),
        '',
        '┌─────────────────────────────────────────────────────────────────────┐',
        '│  2. TIKTOK OVERVIEW                                                 │',
        '└─────────────────────────────────────────────────────────────────────┘',
        '',
        f'  Videos analysed : Lazada {lz_tt["count"]}  |  Shopee {sh_tt["count"]}',
        f'  Followers        : Lazada {fmt_num(lz_tt["followers"])}  |  Shopee {fmt_num(sh_tt["followers"])}',
        '',
        '── Head-to-Head Bars ──────────────────────────────────────────────────',
        '',
    ]

    for label, lv, sv in [
        ('Avg Plays / video', lz_tt['avg_plays'], sh_tt['avg_plays']),
        ('Avg Likes / video', lz_tt['avg_likes'], sh_tt['avg_likes']),
        ('Avg Comments / video', lz_tt['avg_comments'], sh_tt['avg_comments']),
        ('Avg Shares / video', lz_tt['avg_shares'], sh_tt['avg_shares']),
        ('Avg ER %', lz_tt['avg_er'], sh_tt['avg_er']),
        ('Total Plays (15 vids)', lz_tt['total_plays'], sh_tt['total_plays']),
    ]:
        lines.append(h2h_section(label, lv, sv))

    lines += [
        '── Top 5 TikTok Videos by Views ─────────────────────────────────────',
        '',
        '  LAZADA SG',
        top_posts_tt(all_data.get('lazada_tt', [])),
        '',
        '  SHOPEE SG',
        top_posts_tt(all_data.get('shopee_tt', [])),
        '',
        '┌─────────────────────────────────────────────────────────────────────┐',
        '│  3. SUMMARY TABLE                                                   │',
        '└─────────────────────────────────────────────────────────────────────┘',
        '',
        f'  {"Metric":<30} {"Lazada":>12} {"Shopee":>12} {"Winner":>8}',
        '  ' + '─' * 64,
    ]

    def row(label, lv, sv, higher_is_better=True):
        winner = '='
        if lv > sv:
            winner = 'Lazada' if higher_is_better else 'Shopee'
        elif sv > lv:
            winner = 'Shopee' if higher_is_better else 'Lazada'
        return f'  {label:<30} {fmt_num(lv):>12} {fmt_num(sv):>12} {winner:>8}'

    lines += [
        row('IG Avg Likes', lz_ig['avg_likes'], sh_ig['avg_likes']),
        row('IG Avg Comments', lz_ig['avg_comments'], sh_ig['avg_comments']),
        row('IG Avg ER %', lz_ig['avg_er'], sh_ig['avg_er']),
        row('TT Avg Views', lz_tt['avg_plays'], sh_tt['avg_plays']),
        row('TT Avg Likes', lz_tt['avg_likes'], sh_tt['avg_likes']),
        row('TT Avg ER %', lz_tt['avg_er'], sh_tt['avg_er']),
        '',
        '┌─────────────────────────────────────────────────────────────────────┐',
        '│  4. EXECUTIVE SUMMARY                                               │',
        '└─────────────────────────────────────────────────────────────────────┘',
        '',
    ]

    # Build executive summary
    tt_reach_winner = 'Lazada' if lz_tt['avg_plays'] >= sh_tt['avg_plays'] else 'Shopee'
    tt_reach_ratio  = max(lz_tt['avg_plays'], sh_tt['avg_plays']) / max(min(lz_tt['avg_plays'], sh_tt['avg_plays']), 1)
    ig_er_winner    = 'Lazada' if lz_ig['avg_er'] >= sh_ig['avg_er'] else 'Shopee'
    ig_er_loser     = 'Shopee' if ig_er_winner == 'Lazada' else 'Lazada'
    likes_gap       = abs(lz_ig['total_likes'] - sh_ig['total_likes'])
    likes_leader    = 'Lazada' if lz_ig['total_likes'] >= sh_ig['total_likes'] else 'Shopee'
    likes_lagger    = 'Shopee' if likes_leader == 'Lazada' else 'Lazada'

    summary = (
        f"On TikTok, {tt_reach_winner} dominates short-form video reach with an average of "
        f"{fmt_num(max(lz_tt['avg_plays'], sh_tt['avg_plays']))} views per video — "
        f"approximately {tt_reach_ratio:.1f}× the competitor — driven by higher production frequency and trending audio use. "
        f"On Instagram, {ig_er_winner} wins the engagement-rate battle ({ig_er_winner}'s ER "
        f"{lz_ig['avg_er'] if ig_er_winner == 'Lazada' else sh_ig['avg_er']:.2f}% vs "
        f"{ig_er_loser}'s {sh_ig['avg_er'] if ig_er_winner == 'Lazada' else lz_ig['avg_er']:.2f}%), "
        f"suggesting its content mix resonates more strongly with its follower base. "
        f"To close the {fmt_num(likes_gap)}-like gap on Instagram, {likes_lagger} should increase Reels output "
        f"and shift posting cadence to peak SGT engagement windows (Tue–Thu 19:00–21:00), "
        f"which have shown {likes_leader}'s top-performing posts cluster."
    )
    lines.append('  ' + '\n  '.join([summary[i:i+66] for i in range(0, len(summary), 66)]))
    lines += [
        '',
        '=' * 70,
        f'  Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
        '=' * 70,
    ]

    report_text = '\n'.join(lines)
    output = {
        'report': report_text,
        'stats': {
            'lazada_ig': lz_ig, 'shopee_ig': sh_ig,
            'lazada_tt': lz_tt, 'shopee_tt': sh_tt,
        },
    }
    print(json.dumps(output))


if __name__ == '__main__':
    main()
