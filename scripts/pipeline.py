#!/usr/bin/env python3
"""
Full pipeline: Instagram (Wave 1) → TikTok (Wave 2) → stats → report
Outputs: /home/user/lazada-dashboard/report_output.txt
         /home/user/lazada-dashboard/apify_results.json
"""
import urllib.request, json, time, sys, os, textwrap
from datetime import datetime

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr); sys.exit(1)

TODAY = datetime.now().strftime('%d %b %Y')
print(f'[PIPELINE] Starting — {TODAY}', flush=True)


# ─── Apify helpers ────────────────────────────────────────────────────────────

def apify_get(path):
    sep = '&' if '?' in path else '?'
    url = f'https://api.apify.com/v2/{path}{sep}token={API_KEY}'
    req = urllib.request.Request(url, headers={'User-Agent': 'lazada-pipeline/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def apify_post(path, body):
    url = f'https://api.apify.com/v2/{path}?token={API_KEY}'
    req = urllib.request.Request(
        url, json.dumps(body).encode(),
        {'Content-Type': 'application/json', 'User-Agent': 'lazada-pipeline/1.0'}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def start_run(label, actor, body):
    try:
        r = apify_post(f'acts/{actor}/runs', body)
        rid = r['data']['id']
        print(f'  [START] {label} → {rid}', flush=True)
        return rid
    except Exception as e:
        print(f'  [ERROR] start {label}: {e}', flush=True)
        return None


def poll_wave(wave_dict, max_cycles=25, interval=10):
    """
    Poll all runs in parallel until all complete or max_cycles exhausted.
    wave_dict = {label: run_id | None}
    Returns {label: final_data_dict}
    """
    pending = {k: v for k, v in wave_dict.items() if v}
    results = {k: {'status': 'NO_RUN', 'defaultDatasetId': ''}
               for k, v in wave_dict.items() if not v}
    for cycle in range(1, max_cycles + 1):
        if not pending:
            break
        completed = []
        for label, rid in pending.items():
            try:
                d = apify_get(f'actor-runs/{rid}')['data']
                s = d['status']
                print(f'  [POLL {cycle:02d}] {label}: {s}', flush=True)
                if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                    results[label] = d
                    completed.append(label)
            except Exception as e:
                print(f'  [POLL {cycle:02d}] {label} err: {e}', flush=True)
        for l in completed:
            del pending[l]
        if pending:
            time.sleep(interval)
    for label in pending:
        print(f'  [TIMEOUT] {label} did not finish within poll window', flush=True)
        results[label] = {'status': 'POLL_TIMEOUT', 'defaultDatasetId': ''}
    return results


def fetch_items(dataset_id, limit=50):
    if not dataset_id:
        return []
    try:
        d = apify_get(f'datasets/{dataset_id}/items?limit={limit}')
        return d if isinstance(d, list) else d.get('items', [])
    except Exception as e:
        print(f'  [ERROR] fetch dataset {dataset_id}: {e}', flush=True)
        return []


# ─── WAVE 1: Instagram ────────────────────────────────────────────────────────

print('\n══ WAVE 1 — Instagram scrapers ══════════════════════════════', flush=True)
w1 = {
    'lazada_ig': start_run('lazada_ig', 'apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/Lazada_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
    'shopee_ig': start_run('shopee_ig', 'apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/shopee_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
}
w1_done = poll_wave(w1)

# ─── WAVE 2: TikTok ───────────────────────────────────────────────────────────

print('\n══ WAVE 2 — TikTok scrapers ═════════════════════════════════', flush=True)
w2 = {
    'lazada_tt': start_run('lazada_tt', 'clockworks~free-tiktok-scraper', {
        'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
    'shopee_tt': start_run('shopee_tt', 'clockworks~free-tiktok-scraper', {
        'profiles': ['shopeesg'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
}
w2_done = poll_wave(w2)

# ─── Fetch all four datasets ──────────────────────────────────────────────────

print('\n══ Fetching datasets ════════════════════════════════════════', flush=True)
all_done = {**w1_done, **w2_done}
raw = {}
for key in ('lazada_ig', 'shopee_ig', 'lazada_tt', 'shopee_tt'):
    final = all_done.get(key, {})
    items = fetch_items(final.get('defaultDatasetId', ''))
    raw[key] = items
    print(f'  {key}: {len(items)} items  [status={final.get("status", "?")}]', flush=True)


# ─── Compute stats ────────────────────────────────────────────────────────────

def safe(x):
    return int(x) if x else 0


def ig_stats(posts):
    n = len(posts)
    empty = {'likes': 0, 'comments': 0, 'plays': 0, 'shares': 0,
             'er': 0.0, 'count': 0, 'types': {}}
    if n == 0:
        return empty
    likes    = sum(safe(p.get('likesCount'))     for p in posts)
    comments = sum(safe(p.get('commentsCount'))  for p in posts)
    plays    = sum(safe(p.get('videoViewCount')) for p in posts)
    er_vals  = []
    for p in posts:
        l = safe(p.get('likesCount')); c = safe(p.get('commentsCount'))
        v = safe(p.get('videoViewCount'))
        base = v if v > 0 else max(l + c, 1)
        er_vals.append((l + c) / base * 100)
    types = {}
    for p in posts:
        t = str(p.get('type') or p.get('productType') or 'Unknown')
        types[t] = types.get(t, 0) + 1
    return {'likes': likes, 'comments': comments, 'plays': plays, 'shares': 0,
            'er': round(sum(er_vals) / len(er_vals), 2), 'count': n, 'types': types}


def tt_stats(posts):
    n = len(posts)
    empty = {'likes': 0, 'comments': 0, 'plays': 0, 'shares': 0,
             'er': 0.0, 'count': 0, 'types': {}}
    if n == 0:
        return empty
    likes    = sum(safe(p.get('diggCount'))    for p in posts)
    comments = sum(safe(p.get('commentCount')) for p in posts)
    plays    = sum(safe(p.get('playCount'))    for p in posts)
    shares   = sum(safe(p.get('shareCount'))   for p in posts)
    er_vals  = []
    for p in posts:
        l = safe(p.get('diggCount')); c = safe(p.get('commentCount'))
        s = safe(p.get('shareCount')); v = max(safe(p.get('playCount')), 1)
        er_vals.append((l + c + s) / v * 100)
    return {'likes': likes, 'comments': comments, 'plays': plays, 'shares': shares,
            'er': round(sum(er_vals) / len(er_vals), 2), 'count': n, 'types': {'Video': n}}


S = {
    'lazada_ig': ig_stats(raw['lazada_ig']),
    'shopee_ig':  ig_stats(raw['shopee_ig']),
    'lazada_tt': tt_stats(raw['lazada_tt']),
    'shopee_tt':  tt_stats(raw['shopee_tt']),
}
LI = S['lazada_ig']; SI = S['shopee_ig']
LT = S['lazada_tt']; ST = S['shopee_tt']

print('\n══ Stats computed ═══════════════════════════════════════════', flush=True)
for k, v in S.items():
    print(f'  {k}: likes={v["likes"]} comments={v["comments"]} '
          f'plays={v["plays"]} er={v["er"]}%', flush=True)


# ─── Chart helpers ────────────────────────────────────────────────────────────

def bar40(a, b, width=40):
    mx = max(a, b, 1)
    fa = max(0, min(width, int(round(a / mx * width))))
    fb = max(0, min(width, int(round(b / mx * width))))
    return '█' * fa + '░' * (width - fa), '█' * fb + '░' * (width - fb)


def bar14(val, total, width=14):
    if total == 0:
        return '░' * width
    filled = max(0, min(width, int(round(val / total * width))))
    return '█' * filled + '░' * (width - filled)


def fmt(n):
    if n >= 1_000_000: return f'{n / 1_000_000:.1f}M'
    if n >= 1_000:     return f'{n / 1_000:.1f}K'
    return str(n)


def h2h(metric, lv, sv, unit=''):
    lb, sb = bar40(lv, sv)
    return (f'  {"Lazada SG":<12s}  {lb}  {fmt(lv)}{unit}\n'
            f'  {"Shopee SG":<12s}  {sb}  {fmt(sv)}{unit}')


def mix_block(types, total):
    if not types or total == 0:
        return '  (no data)'
    lines = []
    for t, cnt in sorted(types.items(), key=lambda x: -x[1]):
        pct = cnt / total * 100
        b = bar14(cnt, total)
        lines.append(f'  {t:<14s}  {b}  {cnt} posts ({pct:.0f}%)')
    return '\n'.join(lines)


# ─── Top 5 posts ──────────────────────────────────────────────────────────────

def top5_ig(posts):
    scored = sorted(posts,
                    key=lambda p: safe(p.get('likesCount')) + safe(p.get('commentsCount')),
                    reverse=True)[:5]
    out = []
    for p in scored:
        sc = p.get('shortCode', '')
        url = p.get('url') or (f'https://www.instagram.com/p/{sc}/' if sc else '')
        out.append({
            'url': url,
            'likes': safe(p.get('likesCount')),
            'comments': safe(p.get('commentsCount')),
            'caption': (p.get('caption') or '')[:70],
        })
    return out


def top5_tt(posts):
    scored = sorted(posts, key=lambda p: safe(p.get('playCount')), reverse=True)[:5]
    out = []
    for p in scored:
        out.append({
            'url': p.get('webVideoUrl') or p.get('url', ''),
            'plays': safe(p.get('playCount')),
            'likes': safe(p.get('diggCount')),
            'desc': (p.get('text') or p.get('desc') or '')[:70],
        })
    return out


top = {
    'lazada_ig': top5_ig(raw['lazada_ig']),
    'shopee_ig':  top5_ig(raw['shopee_ig']),
    'lazada_tt': top5_tt(raw['lazada_tt']),
    'shopee_tt':  top5_tt(raw['shopee_tt']),
}


# ─── Build report ─────────────────────────────────────────────────────────────

W = 62
SEP  = '═' * W
SEP2 = '─' * W

def section(t): return f'\n{SEP}\n  {t}\n{SEP}'
def sub(t):     return f'\n{SEP2}\n  {t}\n{SEP2}'


lines = [
    SEP,
    f'  COMPETITOR SOCIAL MEDIA REPORT — {TODAY}',
    f'  Lazada SG  vs  Shopee SG  |  Instagram & TikTok',
    SEP,
]

# ── Instagram ──────────────────────────────────────────────────────────────
lines += [section('INSTAGRAM')]
lines += [sub('Total Likes (last 15 posts)'), h2h('Likes', LI['likes'], SI['likes'])]
lines += [sub('Total Comments'), h2h('Comments', LI['comments'], SI['comments'])]
if LI['plays'] or SI['plays']:
    lines += [sub('Total Video Views'), h2h('Video Views', LI['plays'], SI['plays'])]
lines += [sub('Avg Engagement Rate %'), h2h('ER%', LI['er'], SI['er'], '%')]
lines += [sub('Content Mix — Lazada SG'), mix_block(LI['types'], LI['count'])]
lines += [sub('Content Mix — Shopee SG'), mix_block(SI['types'], SI['count'])]

for brand, key in [('Lazada SG', 'lazada_ig'), ('Shopee SG', 'shopee_ig')]:
    lines.append(sub(f'Top 5 Posts — {brand}  (sorted by likes+comments)'))
    posts = top[key]
    if not posts:
        lines.append('  (no data)')
    else:
        for i, p in enumerate(posts, 1):
            lines.append(f'  {i}. ❤ {fmt(p["likes"]):<8s} 💬 {p["comments"]}')
            cap = p['caption'] or '(no caption)'
            for chunk in textwrap.wrap(cap, 56):
                lines.append(f'     {chunk}')
            if p['url']:
                lines.append(f'     {p["url"]}')

# ── TikTok ─────────────────────────────────────────────────────────────────
lines += [section('TIKTOK')]
lines += [sub('Total Plays'),    h2h('Plays',    LT['plays'],    ST['plays'])]
lines += [sub('Total Likes'),    h2h('Likes',    LT['likes'],    ST['likes'])]
lines += [sub('Total Comments'), h2h('Comments', LT['comments'], ST['comments'])]
lines += [sub('Total Shares'),   h2h('Shares',   LT['shares'],   ST['shares'])]
lines += [sub('Avg ER % (likes+comments+shares / plays)'),
          h2h('ER%', LT['er'], ST['er'], '%')]
lines.append(sub('Video Count'))
lines.append(f'  Lazada SG:  {LT["count"]} videos')
lines.append(f'  Shopee SG:  {ST["count"]} videos')

for brand, key in [('Lazada SG', 'lazada_tt'), ('Shopee SG', 'shopee_tt')]:
    lines.append(sub(f'Top 5 Posts — {brand}  (sorted by plays)'))
    posts = top[key]
    if not posts:
        lines.append('  (no data)')
    else:
        for i, p in enumerate(posts, 1):
            lines.append(f'  {i}. ▶ {fmt(p["plays"]):<8s} ❤ {fmt(p["likes"])}')
            desc = p['desc'] or '(no description)'
            for chunk in textwrap.wrap(desc, 56):
                lines.append(f'     {chunk}')
            if p['url']:
                lines.append(f'     {p["url"]}')

# ── Summary table ──────────────────────────────────────────────────────────
lines.append(section('SUMMARY TABLE'))
lines.append(f'  {"Metric":<32s}  {"Lazada SG":>11s}  {"Shopee SG":>11s}')
lines.append('  ' + '─' * 58)
for label, lv, sv in [
    ('IG Likes (total)',         fmt(LI['likes']),         fmt(SI['likes'])),
    ('IG Comments (total)',      fmt(LI['comments']),      fmt(SI['comments'])),
    ('IG Video Views (total)',   fmt(LI['plays']),         fmt(SI['plays'])),
    ('IG Avg ER%',               f'{LI["er"]:.2f}%',      f'{SI["er"]:.2f}%'),
    ('TT Plays (total)',         fmt(LT['plays']),         fmt(ST['plays'])),
    ('TT Likes (total)',         fmt(LT['likes']),         fmt(ST['likes'])),
    ('TT Comments (total)',      fmt(LT['comments']),      fmt(ST['comments'])),
    ('TT Shares (total)',        fmt(LT['shares']),        fmt(ST['shares'])),
    ('TT Avg ER%',               f'{LT["er"]:.2f}%',      f'{ST["er"]:.2f}%'),
    ('TT Video Count',           str(LT['count']),         str(ST['count'])),
]:
    lines.append(f'  {label:<32s}  {lv:>11s}  {sv:>11s}')

# ── Executive Summary ─────────────────────────────────────────────────────
tt_leader  = 'Lazada SG' if LT['plays'] >= ST['plays'] else 'Shopee SG'
tt_trailer = 'Shopee SG' if tt_leader == 'Lazada SG' else 'Lazada SG'
tt_gap     = abs(LT['plays'] - ST['plays'])
ig_er_win  = 'Lazada SG' if LI['er'] >= SI['er'] else 'Shopee SG'
ig_er_los  = 'Shopee SG' if ig_er_win == 'Lazada SG' else 'Lazada SG'
ig_lk_lead = 'Lazada SG' if LI['likes'] >= SI['likes'] else 'Shopee SG'
ig_lk_trl  = 'Shopee SG' if ig_lk_lead == 'Lazada SG' else 'Lazada SG'
ig_lk_gap  = abs(LI['likes'] - SI['likes'])

exec_text = (
    f"{tt_leader} dominates TikTok reach with "
    f"{fmt(max(LT['plays'], ST['plays']))} total plays vs "
    f"{fmt(min(LT['plays'], ST['plays']))} for {tt_trailer} "
    f"(+{fmt(tt_gap)} gap), signalling stronger short-video distribution. "
    f"On Instagram, {ig_er_win} leads engagement rate at "
    f"{max(LI['er'], SI['er']):.2f}% vs {min(LI['er'], SI['er']):.2f}% "
    f"for {ig_er_los}, indicating higher content resonance per post. "
    f"{ig_lk_lead} holds a {fmt(ig_lk_gap)}-like advantage on Instagram — "
    f"{ig_lk_trl} should increase Reels/carousel output and boost posting "
    f"cadence to close this visibility gap."
)

lines.append(section('EXECUTIVE SUMMARY'))
for chunk in textwrap.wrap(exec_text, W - 4):
    lines.append('  ' + chunk)

lines += ['', SEP2,
          f'  Generated: {TODAY}  |  Apify Instagram + TikTok scrapers',
          SEP2, '']

report = '\n'.join(lines)

# ── Write outputs ─────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

report_path = os.path.join(BASE, 'report_output.txt')
with open(report_path, 'w', encoding='utf-8') as f:
    f.write(report)
print(f'\n[SAVED] {report_path}', flush=True)

results_path = os.path.join(BASE, 'apify_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump({'stats': S, 'raw': raw}, f, default=str, indent=2)
print(f'[SAVED] {results_path}', flush=True)

# Print report to stdout for capture
print('\n\n' + '=' * 62)
print('REPORT OUTPUT')
print('=' * 62)
print(report)
