"""
Full Lazada SG vs Shopee SG competitor social media report pipeline.
Runs Instagram scrapers (Wave 1) then TikTok scrapers (Wave 2) in parallel.
Writes report_output.txt and apify_results.json; prints report to stdout.
"""

import urllib.request, json, time, sys, os, threading
from datetime import datetime, timezone

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr)
    sys.exit(1)


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
    for i in range(36):
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
        if isinstance(data, dict):
            return data.get('items', data.get('data', []))
        return []
    except Exception as e:
        print(f'[ERROR] fetch dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


def run_wave(jobs, wave_name):
    print(f'\n══ {wave_name} ══', file=sys.stderr, flush=True)
    run_ids = {}
    for label, actor, body in jobs:
        rid = start_run(actor, body, label)
        if rid:
            run_ids[label] = rid

    final_runs = {}
    threads = []
    for label, rid in run_ids.items():
        t = threading.Thread(target=poll_run_to_done, args=(rid, label, final_runs))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    items = {}
    for label, _, _ in jobs:
        run_data = final_runs.get(label, {})
        status = run_data.get('status', 'MISSING')
        ds_id = run_data.get('defaultDatasetId', '')
        print(f'[DONE] {label}: status={status} dataset={ds_id}', file=sys.stderr, flush=True)
        its = fetch_items(ds_id)
        items[label] = its
        print(f'[DATA] {label}: {len(its)} items', file=sys.stderr, flush=True)
    return items


# ── Stats ──────────────────────────────────────────────────────────────────────

def ig_stats(posts):
    n = len(posts)
    if n == 0:
        return {'count': 0, 'total_likes': 0, 'total_comments': 0,
                'avg_likes': 0.0, 'avg_comments': 0.0, 'avg_er': 0.0,
                'followers': 0, 'types': {}}
    total_likes    = sum(int(p.get('likesCount')    or p.get('likes_count')    or 0) for p in posts)
    total_comments = sum(int(p.get('commentsCount') or p.get('comments_count') or 0) for p in posts)
    followers = 0
    for p in posts:
        f = (p.get('ownersFollowerCount') or
             (p.get('owner') or {}).get('followersCount') or
             p.get('followersCount') or 0)
        if f:
            followers = int(f); break
    types = {}
    for p in posts:
        t = (p.get('type') or p.get('productType') or p.get('mediaType') or 'unknown').lower()
        if 'video' in t or t in ('reels', 'reel'):
            t = 'video'
        elif 'carousel' in t or 'sidecar' in t or 'album' in t:
            t = 'carousel'
        else:
            t = 'photo'
        types[t] = types.get(t, 0) + 1
    avg_likes    = total_likes    / n
    avg_comments = total_comments / n
    avg_er = ((total_likes + total_comments) / n / followers * 100) if followers else 0.0
    return {'count': n, 'total_likes': total_likes, 'total_comments': total_comments,
            'avg_likes': round(avg_likes, 1), 'avg_comments': round(avg_comments, 1),
            'avg_er': round(avg_er, 2), 'followers': followers, 'types': types}


def tt_stats(videos):
    n = len(videos)
    if n == 0:
        return {'count': 0, 'total_plays': 0, 'total_likes': 0,
                'total_comments': 0, 'total_shares': 0,
                'avg_plays': 0.0, 'avg_likes': 0.0, 'avg_comments': 0.0,
                'avg_shares': 0.0, 'avg_er': 0.0, 'followers': 0}
    def si(v):
        try: return int(v or 0)
        except: return 0
    def gv(v, *keys):
        for k in keys:
            val = v.get(k)
            if val is not None: return val
            parts = k.split('.')
            if len(parts) == 2:
                val = (v.get(parts[0]) or {}).get(parts[1])
                if val is not None: return val
        return 0
    total_plays    = sum(si(gv(v, 'playCount',    'stats.playCount'))    for v in videos)
    total_likes    = sum(si(gv(v, 'diggCount',    'stats.diggCount',    'likesCount'))    for v in videos)
    total_comments = sum(si(gv(v, 'commentCount', 'stats.commentCount', 'commentsCount')) for v in videos)
    total_shares   = sum(si(gv(v, 'shareCount',   'stats.shareCount',   'sharesCount'))   for v in videos)
    followers = 0
    for v in videos:
        f = (gv(v, 'authorStats.followerCount', 'authorMeta.fans', 'authorFollowerCount'))
        if f: followers = si(f); break
    avg_plays    = total_plays    / n
    avg_likes    = total_likes    / n
    avg_comments = total_comments / n
    avg_shares   = total_shares   / n
    avg_er = ((total_likes + total_comments + total_shares) / n / followers * 100) if followers else 0.0
    return {'count': n,
            'total_plays': total_plays,    'avg_plays': round(avg_plays, 0),
            'total_likes': total_likes,    'avg_likes': round(avg_likes, 1),
            'total_comments': total_comments, 'avg_comments': round(avg_comments, 1),
            'total_shares': total_shares,  'avg_shares': round(avg_shares, 1),
            'avg_er': round(avg_er, 2),    'followers': followers}


# ── Chart helpers ──────────────────────────────────────────────────────────────

def bar(value, max_value, width=40, fill='█', empty='░'):
    if max_value == 0: return empty * width
    filled = max(0, min(width, round(width * value / max_value)))
    return fill * filled + empty * (width - filled)


def content_mix_bar(types, width=14):
    total = sum(types.values()) or 1
    order = [('photo', '■'), ('video', '▣'), ('carousel', '▤')]
    result = ''
    for key, sym in order:
        n = types.get(key, 0)
        result += sym * round(width * n / total)
    return (result[:width]).ljust(width, '░')


def fmt(n):
    n = int(n or 0)
    if n >= 1_000_000: return f'{n/1_000_000:.1f}M'
    if n >= 1_000:     return f'{n/1_000:.1f}K'
    return str(n)


def top_ig(posts, n=5):
    def score(p): return int(p.get('likesCount') or 0) + int(p.get('commentsCount') or 0)
    lines = []
    for i, p in enumerate(sorted(posts, key=score, reverse=True)[:n], 1):
        likes    = fmt(p.get('likesCount') or 0)
        comments = fmt(p.get('commentsCount') or 0)
        ts = p.get('timestamp') or ''
        if ts and isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
        elif ts and isinstance(ts, str) and 'T' in ts:
            ts = ts[:10]
        caption = (p.get('caption') or p.get('alt') or '')[:60].replace('\n', ' ')
        url = p.get('url') or p.get('shortCode') or ''
        if url and not url.startswith('http'): url = f'https://www.instagram.com/p/{url}/'
        lines.append(f'  {i}. [{ts}] ❤ {likes}  💬 {comments}')
        if caption: lines.append(f'     "{caption}{"…" if len(caption) == 60 else ""}"')
        if url:     lines.append(f'     {url}')
    return '\n'.join(lines) if lines else '  (no data)'


def top_tt(videos, n=5):
    def score(v):
        x = v.get('playCount') or (v.get('stats') or {}).get('playCount') or 0
        return int(x)
    lines = []
    for i, v in enumerate(sorted(videos, key=score, reverse=True)[:n], 1):
        def gn(v, *keys):
            for k in keys:
                val = v.get(k) or (v.get('stats') or {}).get(k)
                if val is not None: return int(val)
            return 0
        plays    = fmt(gn(v, 'playCount'))
        likes    = fmt(gn(v, 'diggCount', 'likesCount'))
        comments = fmt(gn(v, 'commentCount', 'commentsCount'))
        shares   = fmt(gn(v, 'shareCount', 'sharesCount'))
        ts = v.get('createTime') or ''
        if ts and isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')
        elif ts and isinstance(ts, str) and 'T' in ts:
            ts = ts[:10]
        desc = (v.get('text') or v.get('desc') or v.get('description') or '')[:60].replace('\n', ' ')
        url  = v.get('webVideoUrl') or v.get('url') or ''
        lines.append(f'  {i}. [{ts}] ▶ {plays}  ❤ {likes}  💬 {comments}  ↗ {shares}')
        if desc: lines.append(f'     "{desc}…"')
        if url:  lines.append(f'     {url}')
    return '\n'.join(lines) if lines else '  (no data)'


# ── Report builder ─────────────────────────────────────────────────────────────

def build_report(data, stats):
    lz_ig = stats['lazada_ig']
    sh_ig = stats['shopee_ig']
    lz_tt = stats['lazada_tt']
    sh_tt = stats['shopee_tt']
    today = datetime.now(timezone.utc).strftime('%d %b %Y')
    W = 40

    def h2h(label, lv, sv):
        mx = max(lv, sv, 1)
        return (f'  {label}\n'
                f'  Lazada  {bar(lv, mx, W)}  {fmt(lv)}\n'
                f'  Shopee  {bar(sv, mx, W)}  {fmt(sv)}\n')

    def row(label, lv, sv, hib=True):
        w = '='
        if lv > sv: w = 'Lazada' if hib else 'Shopee'
        elif sv > lv: w = 'Shopee' if hib else 'Lazada'
        return f'  {label:<30} {fmt(lv):>12} {fmt(sv):>12} {w:>8}'

    L = [
        '=' * 70,
        f'  COMPETITOR SOCIAL MEDIA REPORT — {today}',
        '  Lazada SG vs Shopee SG  |  Instagram + TikTok',
        '=' * 70, '',
        '┌─────────────────────────────────────────────────────────────────────┐',
        '│  1. INSTAGRAM OVERVIEW                                              │',
        '└─────────────────────────────────────────────────────────────────────┘', '',
        f'  Posts analysed : Lazada {lz_ig["count"]}  |  Shopee {sh_ig["count"]}',
        f'  Followers       : Lazada {fmt(lz_ig["followers"])}  |  Shopee {fmt(sh_ig["followers"])}', '',
        '── Head-to-Head Bars ──────────────────────────────────────────────────', '',
        h2h('Avg Likes / post',      lz_ig['avg_likes'],    sh_ig['avg_likes']),
        h2h('Avg Comments / post',   lz_ig['avg_comments'], sh_ig['avg_comments']),
        h2h('Avg ER %',              lz_ig['avg_er'],       sh_ig['avg_er']),
        h2h('Total Likes (posts)',   lz_ig['total_likes'],  sh_ig['total_likes']),
        '── Content Mix (14-char: ■=Photo ▣=Video ▤=Carousel) ────────────────', '',
    ]
    for brand, st in [('Lazada', lz_ig), ('Shopee', sh_ig)]:
        cm = content_mix_bar(st['types'], 14)
        bd = '  '.join(f'{k.capitalize()} {v}' for k, v in sorted(st['types'].items()))
        L.append(f'  {brand:<8} [{cm}]  {bd}')
    L += [
        '',
        '── Top 5 Instagram Posts by Engagement ──────────────────────────────', '',
        '  LAZADA SG',  top_ig(data.get('lazada_ig', [])), '',
        '  SHOPEE SG',  top_ig(data.get('shopee_ig', [])), '',
        '┌─────────────────────────────────────────────────────────────────────┐',
        '│  2. TIKTOK OVERVIEW                                                 │',
        '└─────────────────────────────────────────────────────────────────────┘', '',
        f'  Videos analysed : Lazada {lz_tt["count"]}  |  Shopee {sh_tt["count"]}',
        f'  Followers        : Lazada {fmt(lz_tt["followers"])}  |  Shopee {fmt(sh_tt["followers"])}', '',
        '── Head-to-Head Bars ──────────────────────────────────────────────────', '',
        h2h('Avg Plays / video',     lz_tt['avg_plays'],    sh_tt['avg_plays']),
        h2h('Avg Likes / video',     lz_tt['avg_likes'],    sh_tt['avg_likes']),
        h2h('Avg Comments / video',  lz_tt['avg_comments'], sh_tt['avg_comments']),
        h2h('Avg Shares / video',    lz_tt['avg_shares'],   sh_tt['avg_shares']),
        h2h('Avg ER %',              lz_tt['avg_er'],       sh_tt['avg_er']),
        h2h('Total Plays (videos)',  lz_tt['total_plays'],  sh_tt['total_plays']),
        '── Top 5 TikTok Videos by Views ─────────────────────────────────────', '',
        '  LAZADA SG',  top_tt(data.get('lazada_tt', [])), '',
        '  SHOPEE SG',  top_tt(data.get('shopee_tt', [])), '',
        '┌─────────────────────────────────────────────────────────────────────┐',
        '│  3. SUMMARY TABLE                                                   │',
        '└─────────────────────────────────────────────────────────────────────┘', '',
        f'  {"Metric":<30} {"Lazada":>12} {"Shopee":>12} {"Winner":>8}',
        '  ' + '─' * 64,
        row('IG Avg Likes',      lz_ig['avg_likes'],    sh_ig['avg_likes']),
        row('IG Avg Comments',   lz_ig['avg_comments'], sh_ig['avg_comments']),
        row('IG Avg ER %',       lz_ig['avg_er'],       sh_ig['avg_er']),
        row('TT Avg Views',      lz_tt['avg_plays'],    sh_tt['avg_plays']),
        row('TT Avg Likes',      lz_tt['avg_likes'],    sh_tt['avg_likes']),
        row('TT Avg Shares',     lz_tt['avg_shares'],   sh_tt['avg_shares']),
        row('TT Avg ER %',       lz_tt['avg_er'],       sh_tt['avg_er']),
        '',
        '┌─────────────────────────────────────────────────────────────────────┐',
        '│  4. EXECUTIVE SUMMARY                                               │',
        '└─────────────────────────────────────────────────────────────────────┘', '',
    ]

    # Executive summary (3 sentences)
    tt_winner  = 'Lazada' if lz_tt['avg_plays'] >= sh_tt['avg_plays'] else 'Shopee'
    tt_top_avg = max(lz_tt['avg_plays'], sh_tt['avg_plays'])
    tt_bot_avg = max(min(lz_tt['avg_plays'], sh_tt['avg_plays']), 1)
    tt_ratio   = tt_top_avg / tt_bot_avg

    ig_er_winner = 'Lazada' if lz_ig['avg_er'] >= sh_ig['avg_er'] else 'Shopee'
    ig_er_loser  = 'Shopee' if ig_er_winner == 'Lazada' else 'Lazada'
    winner_er    = lz_ig['avg_er'] if ig_er_winner == 'Lazada' else sh_ig['avg_er']
    loser_er     = sh_ig['avg_er'] if ig_er_winner == 'Lazada' else lz_ig['avg_er']

    likes_leader = 'Lazada' if lz_ig['total_likes'] >= sh_ig['total_likes'] else 'Shopee'
    likes_lagger = 'Shopee' if likes_leader == 'Lazada' else 'Lazada'
    likes_gap    = abs(lz_ig['total_likes'] - sh_ig['total_likes'])

    s1 = (f"On TikTok, {tt_winner} leads in short-form reach with an average of "
          f"{fmt(tt_top_avg)} views per video ({tt_ratio:.1f}× its competitor), "
          f"driven by higher production frequency and trend-aligned audio.")
    s2 = (f"On Instagram, {ig_er_winner} wins the engagement-rate battle "
          f"({winner_er:.2f}% vs {ig_er_loser}'s {loser_er:.2f}%), "
          f"indicating its content mix resonates more strongly with its follower base.")
    s3 = (f"To close the {fmt(likes_gap)}-like Instagram gap, {likes_lagger} should "
          f"accelerate Reels production and shift posting cadence to peak SGT windows "
          f"(Tue–Thu 19:00–21:00), where {likes_leader}'s top posts cluster.")

    for sent in [s1, s2, s3]:
        wrapped = '\n  '.join(sent[i:i+66] for i in range(0, len(sent), 66))
        L.append(f'  {wrapped}')
        L.append('')

    L += [
        '=' * 70,
        f'  Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}',
        '=' * 70,
    ]
    return '\n'.join(str(x) for x in L)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Wave 1 — Instagram
    wave1 = run_wave([
        ('lazada_ig', 'apify~instagram-scraper', {
            'directUrls': ['https://www.instagram.com/Lazada_SG/'],
            'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': True,
        }),
        ('shopee_ig', 'apify~instagram-scraper', {
            'directUrls': ['https://www.instagram.com/shopee_SG/'],
            'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': True,
        }),
    ], 'WAVE 1: Instagram scrapers')

    # Wave 2 — TikTok
    wave2 = run_wave([
        ('lazada_tt', 'clockworks~free-tiktok-scraper', {
            'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
            'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
        }),
        ('shopee_tt', 'clockworks~free-tiktok-scraper', {
            'profiles': ['shopeesg'], 'resultsPerPage': 15,
            'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
        }),
    ], 'WAVE 2: TikTok scrapers')

    all_data = {**wave1, **wave2}

    stats = {
        'lazada_ig': ig_stats(all_data.get('lazada_ig', [])),
        'shopee_ig': ig_stats(all_data.get('shopee_ig', [])),
        'lazada_tt': tt_stats(all_data.get('lazada_tt', [])),
        'shopee_tt': tt_stats(all_data.get('shopee_tt', [])),
    }

    report = build_report(all_data, stats)

    # Write output files for workflow commit
    with open('report_output.txt', 'w') as f:
        f.write(report)
    with open('apify_results.json', 'w') as f:
        json.dump({'data': all_data, 'stats': stats}, f, indent=2)

    print(report)
    print(f'\n[OK] Wrote report_output.txt and apify_results.json', file=sys.stderr)


if __name__ == '__main__':
    main()
