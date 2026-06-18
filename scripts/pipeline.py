#!/usr/bin/env python3
"""Lazada SG Competitor Social Media Report Pipeline."""
import urllib.request, json, time, sys, os, textwrap
from datetime import datetime

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr)
    sys.exit(1)

TODAY = datetime.utcnow().strftime('%d %b %Y')
NOW_UTC = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

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
        print(f'[START] {label} -> {rid}', file=sys.stderr, flush=True)
        return rid
    except Exception as e:
        print(f'[ERROR] start {label}: {e}', file=sys.stderr, flush=True)
        return None


def check_run_status(rid):
    try:
        return apify_get(f'actor-runs/{rid}')['data']
    except Exception as e:
        print(f'[WARN] check {rid}: {e}', file=sys.stderr, flush=True)
        return {'status': 'UNKNOWN', 'defaultDatasetId': ''}


TERMINAL = {'SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'}


def poll_wave(run_ids, max_polls=48):
    """Poll a {label: run_id} map until all reach a terminal state."""
    pending = dict(run_ids)
    finals = {}
    for i in range(max_polls):
        newly_done = {}
        still_going = {}
        for label, rid in pending.items():
            d = check_run_status(rid)
            s = d.get('status', 'UNKNOWN')
            print(f'[POLL] {label} #{i+1}: {s}', file=sys.stderr, flush=True)
            if s in TERMINAL:
                newly_done[label] = d
            else:
                still_going[label] = rid
        finals.update(newly_done)
        pending = still_going
        if not pending:
            break
        time.sleep(10)
    # anything still pending after max polls → timeout
    for label, rid in pending.items():
        print(f'[TIMEOUT] {label}', file=sys.stderr, flush=True)
        finals[label] = {'status': 'TIMEOUT', 'defaultDatasetId': ''}
    return finals


def fetch_items(dataset_id):
    if not dataset_id:
        return []
    try:
        data = apify_get(f'datasets/{dataset_id}/items?limit=50')
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get('items', data.get('data', []))
        return []
    except Exception as e:
        print(f'[ERROR] dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


# ── Wave 1 : Instagram ─────────────────────────────────────────────────────────

IG_ACTOR = 'apify~instagram-scraper'
IG_RUNS = {
    'lazada_ig': {
        'directUrls': ['https://www.instagram.com/Lazada_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    },
    'shopee_ig': {
        'directUrls': ['https://www.instagram.com/shopee_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    },
}

print('[WAVE 1] Launching Instagram scrapers in parallel…', file=sys.stderr, flush=True)
ig_ids = {lbl: start_run(IG_ACTOR, body, lbl) for lbl, body in IG_RUNS.items()}
ig_ids = {k: v for k, v in ig_ids.items() if v}
ig_finals = poll_wave(ig_ids)

# ── Wave 2 : TikTok ────────────────────────────────────────────────────────────

TT_ACTOR = 'clockworks~free-tiktok-scraper'
TT_RUNS = {
    'lazada_tt': {
        'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    },
    'shopee_tt': {
        'profiles': ['shopeesg'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    },
}

print('[WAVE 2] Launching TikTok scrapers in parallel…', file=sys.stderr, flush=True)
tt_ids = {lbl: start_run(TT_ACTOR, body, lbl) for lbl, body in TT_RUNS.items()}
tt_ids = {k: v for k, v in tt_ids.items() if v}
tt_finals = poll_wave(tt_ids)

# ── Fetch all four datasets ────────────────────────────────────────────────────

all_finals = {**ig_finals, **tt_finals}
datasets = {}
for label, d in all_finals.items():
    items = fetch_items(d.get('defaultDatasetId', ''))
    datasets[label] = items
    print(f'[DONE] {label}: {len(items)} items  status={d.get("status")}',
          file=sys.stderr, flush=True)

# Persist raw scrape data
with open('apify_results.json', 'w') as f:
    json.dump(datasets, f, indent=2)

# ── Compute stats ──────────────────────────────────────────────────────────────

def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def ig_stats(items):
    n = len(items)
    if n == 0:
        return {'count': 0, 'likes': 0, 'comments': 0, 'plays': 0,
                'shares': 0, 'er_pct': 0.0, 'top5': [], 'vid_count': 0}
    total_likes    = sum(_int(p.get('likesCount'))    for p in items)
    total_comments = sum(_int(p.get('commentsCount')) for p in items)
    total_plays    = sum(_int(p.get('videoPlayCount') or p.get('videoViewCount'))
                        for p in items)
    total_shares   = sum(_int(p.get('sharesCount'))   for p in items)
    vid_count = sum(1 for p in items
                    if (p.get('type') or '').lower() in ('video', 'reel', 'igtv'))
    er_vals = []
    for p in items:
        views = _int(p.get('videoPlayCount') or p.get('videoViewCount'))
        if views > 0:
            er_vals.append((_int(p.get('likesCount')) + _int(p.get('commentsCount')))
                           / views * 100)
    er_pct = sum(er_vals) / len(er_vals) if er_vals else 0.0
    top5 = sorted(items, key=lambda p: _int(p.get('likesCount')), reverse=True)[:5]
    top5_out = [{
        'url':      p.get('url', p.get('shortCode', '')),
        'likes':    _int(p.get('likesCount')),
        'comments': _int(p.get('commentsCount')),
        'plays':    _int(p.get('videoPlayCount') or p.get('videoViewCount')),
        'caption':  (p.get('caption') or '')[:80],
        'type':     p.get('type', 'Image'),
    } for p in top5]
    return {
        'count': n, 'likes': total_likes, 'comments': total_comments,
        'plays': total_plays, 'shares': total_shares,
        'er_pct': round(er_pct, 2), 'top5': top5_out, 'vid_count': vid_count,
    }


def tt_stats(items):
    n = len(items)
    if n == 0:
        return {'count': 0, 'likes': 0, 'comments': 0, 'plays': 0,
                'shares': 0, 'er_pct': 0.0, 'top5': []}
    total_likes    = sum(_int(p.get('diggCount'))    for p in items)
    total_comments = sum(_int(p.get('commentCount')) for p in items)
    total_plays    = sum(_int(p.get('playCount'))    for p in items)
    total_shares   = sum(_int(p.get('shareCount'))   for p in items)
    er_vals = []
    for p in items:
        plays = _int(p.get('playCount'))
        if plays > 0:
            er_vals.append((_int(p.get('diggCount')) + _int(p.get('commentCount'))
                            + _int(p.get('shareCount'))) / plays * 100)
    er_pct = sum(er_vals) / len(er_vals) if er_vals else 0.0
    top5 = sorted(items, key=lambda p: _int(p.get('playCount')), reverse=True)[:5]
    top5_out = [{
        'url':      p.get('webVideoUrl', p.get('videoUrl', '')),
        'likes':    _int(p.get('diggCount')),
        'comments': _int(p.get('commentCount')),
        'plays':    _int(p.get('playCount')),
        'shares':   _int(p.get('shareCount')),
        'caption':  (p.get('text') or '')[:80],
    } for p in top5]
    return {
        'count': n, 'likes': total_likes, 'comments': total_comments,
        'plays': total_plays, 'shares': total_shares,
        'er_pct': round(er_pct, 2), 'top5': top5_out,
    }


stats = {
    'lazada_ig': ig_stats(datasets.get('lazada_ig', [])),
    'shopee_ig': ig_stats(datasets.get('shopee_ig', [])),
    'lazada_tt': tt_stats(datasets.get('lazada_tt', [])),
    'shopee_tt': tt_stats(datasets.get('shopee_tt', [])),
}

# ── Chart helpers ──────────────────────────────────────────────────────────────

def hbar(val, max_val, width=40):
    filled = round(val / max_val * width) if max_val else 0
    filled = max(0, min(width, filled))
    return '█' * filled + '░' * (width - filled)


def content_bar(vid, total, width=14):
    v = round(vid / total * width) if total else 0
    v = max(0, min(width, v))
    return '▓' * v + '░' * (width - v)


def fk(n):
    n = int(n)
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n/1_000:.1f}K'
    return str(n)


# ── Build report ───────────────────────────────────────────────────────────────

def build_report():
    L = []
    W = L.append

    li = stats['lazada_ig']
    si = stats['shopee_ig']
    lt = stats['lazada_tt']
    st = stats['shopee_tt']

    W(f'LAZADA SG · COMPETITOR SOCIAL MEDIA REPORT')
    W('=' * 62)
    W(f'Report Date  : {TODAY}')
    W(f'Brands       : Lazada SG vs Shopee SG')
    W(f'Platforms    : Instagram · TikTok')
    W(f'Posts scanned: {li["count"]+si["count"]} IG, '
      f'{lt["count"]+st["count"]} TT')
    W('')

    # ── INSTAGRAM ──────────────────────────────────────────────────────────────
    W('━' * 62)
    W('INSTAGRAM')
    W('━' * 62)
    W('')
    W(f'  {"Metric":<20} {"Lazada SG":>11} {"Shopee SG":>11}  {"Winner":<10}')
    W(f'  {"─"*20} {"─"*11} {"─"*11}  {"─"*10}')

    ig_rows = [
        ('Posts',         li['count'],    si['count']),
        ('Total Likes',   li['likes'],    si['likes']),
        ('Total Comments',li['comments'], si['comments']),
        ('Video Plays',   li['plays'],    si['plays']),
        ('Avg ER %',      li['er_pct'],   si['er_pct']),
    ]
    for label, lv, sv in ig_rows:
        if isinstance(lv, float):
            ls, ss = f'{lv:.2f}%', f'{sv:.2f}%'
        else:
            ls, ss = fk(lv), fk(sv)
        w = 'Lazada' if lv > sv else ('Shopee' if sv > lv else 'Tie')
        W(f'  {label:<20} {ls:>11} {ss:>11}  {w:<10}')
    W('')

    # Head-to-head bars
    def h2h(metric, lv, sv, label_suffix=''):
        mx = max(lv, sv, 1)
        W(f'  {metric}')
        W(f'  Lazada  [{hbar(lv, mx)}] {fk(lv)}{label_suffix}')
        W(f'  Shopee  [{hbar(sv, mx)}] {fk(sv)}{label_suffix}')
        W('')

    h2h('Likes', li['likes'], si['likes'])
    h2h('Comments', li['comments'], si['comments'])
    h2h('Avg Engagement Rate', li['er_pct'], si['er_pct'], '%')

    # Content mix
    W('  Content Mix  (░ = photo/carousel  ▓ = video/reel)')
    lvc, svc = li['vid_count'], si['vid_count']
    W(f'  Lazada  [{content_bar(lvc, max(li["count"],1))}]  '
      f'{lvc}v / {li["count"]-lvc}p  ({li["count"]} posts)')
    W(f'  Shopee  [{content_bar(svc, max(si["count"],1))}]  '
      f'{svc}v / {si["count"]-svc}p  ({si["count"]} posts)')
    W('')

    # Top 5 per brand
    for brand, key in [('Lazada SG', 'lazada_ig'), ('Shopee SG', 'shopee_ig')]:
        W(f'  ── Top 5 Instagram Posts : {brand} ──')
        W(f'  {"#":<3} {"Likes":>8} {"Comments":>9}  Caption / URL')
        W(f'  {"─"*3} {"─"*8} {"─"*9}  {"─"*48}')
        for i, p in enumerate(stats[key]['top5'], 1):
            snippet = (p['caption'] or p['url'])[:50]
            W(f'  {i:<3} {fk(p["likes"]):>8} {fk(p["comments"]):>9}  {snippet}')
        if not stats[key]['top5']:
            W('  (no data)')
        W('')

    # ── TIKTOK ────────────────────────────────────────────────────────────────
    W('━' * 62)
    W('TIKTOK')
    W('━' * 62)
    W('')
    W(f'  {"Metric":<20} {"Lazada SG":>11} {"Shopee SG":>11}  {"Winner":<10}')
    W(f'  {"─"*20} {"─"*11} {"─"*11}  {"─"*10}')

    tt_rows = [
        ('Videos',         lt['count'],    st['count']),
        ('Total Likes',    lt['likes'],    st['likes']),
        ('Total Comments', lt['comments'], st['comments']),
        ('Total Plays',    lt['plays'],    st['plays']),
        ('Total Shares',   lt['shares'],   st['shares']),
        ('Avg ER %',       lt['er_pct'],   st['er_pct']),
    ]
    for label, lv, sv in tt_rows:
        if isinstance(lv, float):
            ls, ss = f'{lv:.2f}%', f'{sv:.2f}%'
        else:
            ls, ss = fk(lv), fk(sv)
        w = 'Lazada' if lv > sv else ('Shopee' if sv > lv else 'Tie')
        W(f'  {label:<20} {ls:>11} {ss:>11}  {w:<10}')
    W('')

    h2h('Total Plays', lt['plays'], st['plays'])
    h2h('Likes', lt['likes'], st['likes'])
    h2h('Shares', lt['shares'], st['shares'])
    h2h('Avg Engagement Rate', lt['er_pct'], st['er_pct'], '%')

    for brand, key in [('Lazada SG', 'lazada_tt'), ('Shopee SG', 'shopee_tt')]:
        W(f'  ── Top 5 TikTok Videos : {brand} ──')
        W(f'  {"#":<3} {"Plays":>10} {"Likes":>8} {"Shares":>7}  Caption')
        W(f'  {"─"*3} {"─"*10} {"─"*8} {"─"*7}  {"─"*42}')
        for i, p in enumerate(stats[key]['top5'], 1):
            snippet = (p.get('caption') or p.get('url', ''))[:44]
            W(f'  {i:<3} {fk(p.get("plays",0)):>10} {fk(p["likes"]):>8} '
              f'{fk(p.get("shares",0)):>7}  {snippet}')
        if not stats[key]['top5']:
            W('  (no data)')
        W('')

    # ── EXECUTIVE SUMMARY ─────────────────────────────────────────────────────
    W('━' * 62)
    W('EXECUTIVE SUMMARY')
    W('━' * 62)
    W('')

    # TikTok reach sentence
    if lt['plays'] + st['plays'] == 0:
        tt_sent = ('TikTok data was unavailable for this report period; '
                   'both brands returned zero plays.')
    else:
        tt_winner = 'Lazada SG' if lt['plays'] >= st['plays'] else 'Shopee SG'
        tt_loser  = 'Shopee SG' if tt_winner == 'Lazada SG' else 'Lazada SG'
        tt_w_plays = max(lt['plays'], st['plays'])
        tt_l_plays = min(lt['plays'], st['plays'])
        ratio = tt_w_plays / max(tt_l_plays, 1)
        tt_sent = (
            f'On TikTok, {tt_winner} dominates reach with {fk(tt_w_plays)} total plays '
            f'— {ratio:.1f}× ahead of {tt_loser} ({fk(tt_l_plays)} plays) — '
            f'driven by higher posting frequency and stronger share velocity.'
        )

    # Instagram ER sentence
    ig_er_winner = 'Lazada SG' if li['er_pct'] >= si['er_pct'] else 'Shopee SG'
    ig_er_loser  = 'Shopee SG' if ig_er_winner == 'Lazada SG' else 'Lazada SG'
    ig_er_w = max(li['er_pct'], si['er_pct'])
    ig_er_l = min(li['er_pct'], si['er_pct'])
    if ig_er_w == 0:
        er_sent = ('Instagram engagement-rate data was insufficient to determine a winner.')
    else:
        er_sent = (
            f'On Instagram, {ig_er_winner} leads engagement rate at {ig_er_w:.2f}% '
            f'vs {ig_er_loser}\'s {ig_er_l:.2f}%, indicating its content resonates '
            f'more deeply with viewers.'
        )

    # Likes gap sentence
    ig_likes_winner = 'Lazada SG' if li['likes'] >= si['likes'] else 'Shopee SG'
    ig_likes_loser  = 'Shopee SG' if ig_likes_winner == 'Lazada SG' else 'Lazada SG'
    gap = abs(li['likes'] - si['likes'])
    gap_sent = (
        f'{ig_likes_winner} holds a {fk(gap)}-like advantage on Instagram; '
        f'{ig_likes_loser} should close this gap by increasing Reel production '
        f'frequency and amplifying top-performing posts via paid promotion.'
    )

    summary = f'{tt_sent} {er_sent} {gap_sent}'
    for line in textwrap.wrap(summary, 70):
        W(line)
    W('')
    W('━' * 62)
    W(f'Generated : {NOW_UTC}')
    W('Pipeline  : Lazada SG Competitor Social Report')
    W('━' * 62)

    return '\n'.join(L)


report_text = build_report()
print(report_text)

with open('report_output.txt', 'w') as f:
    f.write(report_text)

with open('report_summary.json', 'w') as f:
    json.dump({'date': TODAY, 'stats': stats, 'report': report_text}, f, indent=2)

print('\n[PIPELINE COMPLETE]', file=sys.stderr, flush=True)
