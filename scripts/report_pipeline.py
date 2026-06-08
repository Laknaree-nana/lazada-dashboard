#!/usr/bin/env python3
"""
Lazada SG Competitor Social Media Report Pipeline
Wave 1 → Instagram (parallel)
Wave 2 → TikTok   (parallel, after Wave 1)
"""
import urllib.request, json, time, sys, os, threading
from datetime import datetime, timezone

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr)
    sys.exit(1)

TODAY = datetime.now(timezone.utc).strftime('%d %b %Y')

# ─── Apify helpers ──────────────────────────────────────────

def apify_get(path):
    sep = '&' if '?' in path else '?'
    url = f'https://api.apify.com/v2/{path}{sep}token={API_KEY}'
    req = urllib.request.Request(url, headers={'User-Agent': 'report-pipeline/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def apify_post(path, body):
    url = f'https://api.apify.com/v2/{path}?token={API_KEY}'
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def start_run(actor, body):
    r = apify_post(f'acts/{actor}/runs', body)
    rid = r['data']['id']
    print(f'[START] {actor} → {rid}', file=sys.stderr, flush=True)
    return rid

def poll_run(rid, label, out, key):
    for i in range(60):  # up to 10 minutes
        try:
            d = apify_get(f'actor-runs/{rid}')['data']
            s = d['status']
            print(f'[POLL] {label} #{i+1}: {s}', file=sys.stderr, flush=True)
            if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                out[key] = d
                return
        except Exception as e:
            print(f'[POLL] {label} error: {e}', file=sys.stderr, flush=True)
        time.sleep(10)
    out[key] = {'status': 'TIMEOUT', 'defaultDatasetId': ''}

def fetch_items(dataset_id):
    if not dataset_id:
        return []
    try:
        raw = apify_get(f'datasets/{dataset_id}/items?limit=50')
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            data = raw.get('data', {})
            if isinstance(data, dict):
                return data.get('items', [])
            return raw.get('items', [])
        return []
    except Exception as e:
        print(f'[ERROR] fetch {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []

# ─── Stats helpers ──────────────────────────────────────────

def _n(v):
    return v if isinstance(v, (int, float)) and v == v else 0

def ig_stats(items):
    if not items:
        return dict(count=0, likes=0, comments=0, plays=0, er=None, mix={}, top5=[])
    n = len(items)
    likes    = [_n(i.get('likesCount', 0)) for i in items]
    comments = [_n(i.get('commentsCount', 0)) for i in items]
    plays    = [_n(i.get('videoViewCount', 0)) for i in items]
    followers = next((i.get('followersCount') for i in items if i.get('followersCount')), None)

    avg_likes    = sum(likes) / n
    avg_comments = sum(comments) / n
    avg_plays    = sum(plays) / n
    avg_er       = (avg_likes + avg_comments) / followers * 100 if followers else None

    mix = {}
    for i in items:
        t = i.get('type', 'unknown')
        mix[t] = mix.get(t, 0) + 1

    top5 = sorted(items, key=lambda i: _n(i.get('likesCount',0)) + _n(i.get('commentsCount',0)), reverse=True)[:5]
    top5 = [{
        'url': i.get('url', i.get('shortCode', '')),
        'type': i.get('type', '?'),
        'likes': _n(i.get('likesCount', 0)),
        'comments': _n(i.get('commentsCount', 0)),
        'timestamp': str(i.get('timestamp', ''))[:10],
    } for i in top5]

    return dict(count=n, likes=avg_likes, comments=avg_comments,
                plays=avg_plays, er=avg_er, mix=mix, top5=top5, followers=followers)

def tt_stats(items):
    if not items:
        return dict(count=0, likes=0, comments=0, plays=0, shares=0, er=0, top5=[])
    n = len(items)
    likes    = [_n(i.get('diggCount', 0)) for i in items]
    comments = [_n(i.get('commentCount', 0)) for i in items]
    plays    = [_n(i.get('playCount', 0)) for i in items]
    shares   = [_n(i.get('shareCount', 0)) for i in items]

    avg_likes    = sum(likes) / n
    avg_comments = sum(comments) / n
    avg_plays    = sum(plays) / n
    avg_shares   = sum(shares) / n

    ers = [(l + c + s) / p * 100 for p, l, c, s in zip(plays, likes, comments, shares) if p > 0]
    avg_er = sum(ers) / len(ers) if ers else 0

    top5 = sorted(items, key=lambda i: _n(i.get('playCount', 0)), reverse=True)[:5]
    top5 = [{
        'text': str(i.get('text', '') or '')[:80],
        'likes': _n(i.get('diggCount', 0)),
        'comments': _n(i.get('commentCount', 0)),
        'plays': _n(i.get('playCount', 0)),
        'shares': _n(i.get('shareCount', 0)),
    } for i in top5]

    return dict(count=n, likes=avg_likes, comments=avg_comments,
                plays=avg_plays, shares=avg_shares, er=avg_er, top5=top5)

# ─── Chart helpers ──────────────────────────────────────────

def bar_h2h(a_val, b_val, width=40):
    mx = max(a_val, b_val, 1)
    a_w = round(a_val / mx * width)
    b_w = round(b_val / mx * width)
    return (
        f"  Lazada  {'█'*a_w}{'░'*(width-a_w)}  {fmt_num(a_val)}\n"
        f"  Shopee  {'█'*b_w}{'░'*(width-b_w)}  {fmt_num(b_val)}"
    )

def bar_mix(mix_dict, total, width=14):
    out = []
    for k, v in sorted(mix_dict.items(), key=lambda x: -x[1]):
        w = round(v / max(total, 1) * width)
        pct = v / max(total, 1) * 100
        out.append(f"    {k:<22} {'█'*w}{'░'*(width-w)}  {pct:.0f}%")
    return '\n'.join(out)

def fmt_num(n):
    if n >= 1_000_000: return f'{n/1_000_000:.1f}M'
    if n >= 1_000:     return f'{n/1_000:.1f}K'
    return f'{n:.0f}'

def cell(v, w=12):
    return str(v)[:w].ljust(w)

# ─── Pipeline ─────────────────────────────────────────────────

print('═'*60, file=sys.stderr)
print(f'REPORT PIPELINE  {TODAY}', file=sys.stderr)
print('═'*60, file=sys.stderr, flush=True)

# WAVE 1 — Instagram
print('\n[WAVE 1] Starting Instagram scrapers in parallel...', file=sys.stderr, flush=True)

lazada_ig_id = start_run('apify~instagram-scraper', {
    'directUrls': ['https://www.instagram.com/Lazada_SG/'],
    'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
})
shopee_ig_id = start_run('apify~instagram-scraper', {
    'directUrls': ['https://www.instagram.com/shopee_SG/'],
    'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
})

w1 = {}
threads = [
    threading.Thread(target=poll_run, args=(lazada_ig_id, 'lazada_ig', w1, 'lazada_ig')),
    threading.Thread(target=poll_run, args=(shopee_ig_id, 'shopee_ig', w1, 'shopee_ig')),
]
for t in threads: t.start()
for t in threads: t.join()

print(f'\n[WAVE 1] DONE — lazada_ig={w1["lazada_ig"]["status"]}  shopee_ig={w1["shopee_ig"]["status"]}', file=sys.stderr, flush=True)

# WAVE 2 — TikTok
print('\n[WAVE 2] Starting TikTok scrapers in parallel...', file=sys.stderr, flush=True)

lazada_tt_id = start_run('clockworks~free-tiktok-scraper', {
    'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
    'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
})
shopee_tt_id = start_run('clockworks~free-tiktok-scraper', {
    'profiles': ['shopeesg'], 'resultsPerPage': 15,
    'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
})

w2 = {}
threads = [
    threading.Thread(target=poll_run, args=(lazada_tt_id, 'lazada_tt', w2, 'lazada_tt')),
    threading.Thread(target=poll_run, args=(shopee_tt_id, 'shopee_tt', w2, 'shopee_tt')),
]
for t in threads: t.start()
for t in threads: t.join()

print(f'\n[WAVE 2] DONE — lazada_tt={w2["lazada_tt"]["status"]}  shopee_tt={w2["shopee_tt"]["status"]}', file=sys.stderr, flush=True)

# FETCH DATASETS
print('\n[FETCH] Pulling datasets...', file=sys.stderr, flush=True)
lazada_ig_items = fetch_items(w1['lazada_ig'].get('defaultDatasetId'))
shopee_ig_items = fetch_items(w1['shopee_ig'].get('defaultDatasetId'))
lazada_tt_items = fetch_items(w2['lazada_tt'].get('defaultDatasetId'))
shopee_tt_items = fetch_items(w2['shopee_tt'].get('defaultDatasetId'))
print(f'[FETCH] ig_lazada={len(lazada_ig_items)}  ig_shopee={len(shopee_ig_items)}  tt_lazada={len(lazada_tt_items)}  tt_shopee={len(shopee_tt_items)}', file=sys.stderr, flush=True)

# COMPUTE STATS
lz_ig = ig_stats(lazada_ig_items)
sh_ig = ig_stats(shopee_ig_items)
lz_tt = tt_stats(lazada_tt_items)
sh_tt = tt_stats(shopee_tt_items)

# ─── BUILD REPORT ───────────────────────────────────────────

def section(title):
    return [f'\n{"━"*60}', f'  {title}', '━'*60, '']

L = []  # report lines

L += [f'COMPETITOR SOCIAL MEDIA REPORT — {TODAY}', '='*60, '']

# ── TikTok ──────────────────────────────────────────────────────────
L += section('TIKTOK  —  Head-to-Head')

L += ['▸ Avg Plays per Video', bar_h2h(lz_tt['plays'], sh_tt['plays']), '']
L += ['▸ Avg Likes per Video', bar_h2h(lz_tt['likes'], sh_tt['likes']), '']
L += ['▸ Avg Comments',        bar_h2h(lz_tt['comments'], sh_tt['comments']), '']
L += ['▸ Avg Shares',          bar_h2h(lz_tt['shares'], sh_tt['shares']), '']

L.append('┌───────────────┬──────────────┬──────────────┐')
L.append('│ TikTok Metric │ Lazada SG    │ Shopee SG    │')
L.append('├───────────────┼──────────────┼──────────────┤')
L.append(f'│ Video Count   │ {cell(lz_tt["count"])} │ {cell(sh_tt["count"])} │')
L.append(f'│ Avg Plays     │ {cell(fmt_num(lz_tt["plays"]))} │ {cell(fmt_num(sh_tt["plays"]))} │')
L.append(f'│ Avg Likes     │ {cell(fmt_num(lz_tt["likes"]))} │ {cell(fmt_num(sh_tt["likes"]))} │')
L.append(f'│ Avg Comments  │ {cell(fmt_num(lz_tt["comments"]))} │ {cell(fmt_num(sh_tt["comments"]))} │')
L.append(f'│ Avg Shares    │ {cell(fmt_num(lz_tt["shares"]))} │ {cell(fmt_num(sh_tt["shares"]))} │')
_tt_er_lz = f'{lz_tt["er"]:.2f}%'; _tt_er_sh = f'{sh_tt["er"]:.2f}%'
L.append(f'│ Avg ER%       │ {cell(_tt_er_lz)} │ {cell(_tt_er_sh)} │')
L.append('└───────────────┴──────────────┴──────────────┘')
L.append('')

for brand_label, data in [('LAZADA SG', lz_tt), ('SHOPEE SG', sh_tt)]:
    L.append(f'▸ TikTok Top 5 — {brand_label}')
    if not data['top5']:
        L.append('  (no data)')
    for i, p in enumerate(data['top5'], 1):
        txt = p['text'][:72] + ('…' if len(p['text']) > 72 else '')
        L.append(f'  #{i}  {fmt_num(p["plays"])} plays  {fmt_num(p["likes"])} ♥  {fmt_num(p["comments"])} \U0001f4ac  {fmt_num(p["shares"])} ↗')
        L.append(f'      "{txt}"')
    L.append('')

# ── Instagram ───────────────────────────────────────────────────
L += section('INSTAGRAM  —  Head-to-Head')

L += ['▸ Avg Likes per Post', bar_h2h(lz_ig['likes'], sh_ig['likes']), '']
L += ['▸ Avg Comments',       bar_h2h(lz_ig['comments'], sh_ig['comments']), '']
if lz_ig['er'] is not None and sh_ig['er'] is not None:
    L += ['▸ Avg ER% (vs followers)', bar_h2h(lz_ig['er'], sh_ig['er']), '']

er_lz = f'{lz_ig["er"]:.2f}%' if lz_ig['er'] is not None else 'N/A'
er_sh = f'{sh_ig["er"]:.2f}%' if sh_ig['er'] is not None else 'N/A'

L.append('┌────────────────┬──────────────┬──────────────┐')
L.append('│ IG Metric      │ Lazada SG    │ Shopee SG    │')
L.append('├────────────────┼──────────────┼──────────────┤')
L.append(f'│ Post Count     │ {cell(lz_ig["count"])} │ {cell(sh_ig["count"])} │')
L.append(f'│ Avg Likes      │ {cell(fmt_num(lz_ig["likes"]))} │ {cell(fmt_num(sh_ig["likes"]))} │')
L.append(f'│ Avg Comments   │ {cell(fmt_num(lz_ig["comments"]))} │ {cell(fmt_num(sh_ig["comments"]))} │')
L.append(f'│ Avg ER%        │ {cell(er_lz)} │ {cell(er_sh)} │')
L.append('└────────────────┴──────────────┴──────────────┘')
L.append('')

L.append('▸ Instagram Content Mix — Lazada SG')
L.append(bar_mix(lz_ig['mix'], lz_ig['count']) if lz_ig['mix'] else '  (no data)')
L.append('')
L.append('▸ Instagram Content Mix — Shopee SG')
L.append(bar_mix(sh_ig['mix'], sh_ig['count']) if sh_ig['mix'] else '  (no data)')
L.append('')

for brand_label, data in [('LAZADA SG', lz_ig), ('SHOPEE SG', sh_ig)]:
    L.append(f'▸ Instagram Top 5 — {brand_label}')
    if not data['top5']:
        L.append('  (no data)')
    for i, p in enumerate(data['top5'], 1):
        L.append(f'  #{i}  [{p["type"]}]  {fmt_num(p["likes"])} ♥  {fmt_num(p["comments"])} \U0001f4ac  {p["timestamp"]}')
        L.append(f'      {p["url"]}')
    L.append('')

# ── Executive Summary ────────────────────────────────────────────
L += section('EXECUTIVE SUMMARY')

tt_leader     = 'Lazada' if lz_tt['plays'] >= sh_tt['plays'] else 'Shopee'
tt_leader_val = max(lz_tt['plays'], sh_tt['plays'])
tt_lagger_val = min(lz_tt['plays'], sh_tt['plays'])
tt_gap_pct    = (tt_leader_val - tt_lagger_val) / max(tt_lagger_val, 1) * 100

ig_er_lz = lz_ig['er'] if lz_ig['er'] is not None else (lz_ig['likes'] + lz_ig['comments'])
ig_er_sh = sh_ig['er'] if sh_ig['er'] is not None else (sh_ig['likes'] + sh_ig['comments'])
ig_er_winner  = 'Lazada' if ig_er_lz >= ig_er_sh else 'Shopee'
ig_er_loser   = 'Shopee' if ig_er_winner == 'Lazada' else 'Lazada'

ig_likes_leader = 'Lazada' if lz_ig['likes'] >= sh_ig['likes'] else 'Shopee'
ig_likes_lagger = 'Shopee' if ig_likes_leader == 'Lazada' else 'Lazada'
ig_likes_gap    = abs(lz_ig['likes'] - sh_ig['likes'])

er_note = ''
if lz_ig['er'] is not None and sh_ig['er'] is not None:
    er_note = f' ({er_lz} vs {er_sh})'

summaries = [
    f'1. TikTok Reach: {tt_leader} dominates TikTok video reach with {fmt_num(tt_leader_val)} average plays per post, outpacing its rival by {tt_gap_pct:.0f}%, signalling a stronger short-form content engine and broader algorithmic distribution in the Singapore market.',
    f'2. Instagram ER: {ig_er_winner} wins the Instagram engagement-rate battle{er_note}, reflecting higher audience affinity and more resonant creative — {ig_er_loser} should audit its content pillars and posting cadence to close the relevance gap.',
    f'3. Instagram Likes Gap: {ig_likes_lagger} trails on average Instagram likes by {fmt_num(ig_likes_gap)} per post; the fastest lever to close this gap is investing in short Reels and time-limited promotional carousels optimised for the Singapore deal-seeker audience.',
]

for s in summaries:
    words = s.split()
    line = ''
    for w in words:
        if len(line) + 1 + len(w) > 76:
            L.append(line)
            line = w
        else:
            line = (line + ' ' + w).strip()
    if line:
        L.append(line)
    L.append('')

L.append('─'*60)
L.append(f'Generated {TODAY}  |  Source: Apify Instagram & TikTok Scrapers')
L.append('─'*60)

report_text = '\n'.join(L)

out = {
    'report': report_text,
    'date': TODAY,
    'stats': {
        'lazada_ig': {k: v for k, v in lz_ig.items() if k != 'top5'},
        'shopee_ig': {k: v for k, v in sh_ig.items() if k != 'top5'},
        'lazada_tt': {k: v for k, v in lz_tt.items() if k != 'top5'},
        'shopee_tt': {k: v for k, v in sh_tt.items() if k != 'top5'},
    },
}
print(json.dumps(out, default=str))
