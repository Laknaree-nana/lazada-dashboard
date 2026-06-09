#!/usr/bin/env python3
"""
Full pipeline: scrape → stats → charts → Google-Doc-ready report text.
Output: JSON with keys 'report_text' and 'stats'.
"""

import os, sys, json, time, threading, urllib.request
from datetime import datetime

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr)
    sys.exit(1)

TODAY_STR  = datetime.now().strftime('%d %b %Y')   # "09 Jun 2026"
TODAY_FILE = datetime.now().strftime('%Y-%m-%d')    # for log filenames


# ── Apify helpers ────────────────────────────────────────────────────────────

def apify_get(path):
    sep = '&' if '?' in path else '?'
    url = f'https://api.apify.com/v2/{path}{sep}token={API_KEY}'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def apify_post(path, body):
    url = f'https://api.apify.com/v2/{path}?token={API_KEY}'
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def start_run(actor, body, label):
    r = apify_post(f'acts/{actor}/runs', body)
    rid = r['data']['id']
    print(f'  [START] {label} → run {rid}', flush=True)
    return rid


def poll_until_done(rid, label, timeout_s=300, interval=15):
    deadline = time.time() + timeout_s
    i = 0
    while time.time() < deadline:
        d = apify_get(f'actor-runs/{rid}')['data']
        s = d['status']
        i += 1
        print(f'  [POLL]  {label} #{i}: {s}', flush=True)
        if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
            return d
        time.sleep(interval)
    return apify_get(f'actor-runs/{rid}')['data']


def fetch_items(dataset_id, limit=50):
    if not dataset_id:
        return []
    try:
        raw = apify_get(f'datasets/{dataset_id}/items?limit={limit}')
        # Apify returns a bare list for /items endpoint
        if isinstance(raw, list):
            return raw
        # Some wrappers return {"data": {"items": [...]}}
        if isinstance(raw, dict):
            return raw.get('data', {}).get('items', raw.get('items', []))
        return []
    except Exception as e:
        print(f'  [WARN]  fetch_items {dataset_id}: {e}', file=sys.stderr)
        return []


# ── Worker used by both waves ────────────────────────────────────────────────

def run_and_collect(actor, body, label, results_dict):
    """Start a run, poll, fetch items. Stores list into results_dict[label]."""
    try:
        rid   = start_run(actor, body, label)
        final = poll_until_done(rid, label)
        items = fetch_items(final.get('defaultDatasetId', ''))
        results_dict[label] = items
        print(f'  [DONE]  {label}: {len(items)} items', flush=True)
    except Exception as e:
        print(f'  [ERROR] {label}: {e}', file=sys.stderr)
        results_dict[label] = []


# ── Wave definitions ─────────────────────────────────────────────────────────

WAVE1 = [
    ('lazada_ig', 'apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/Lazada_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
    ('shopee_ig', 'apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/shopee_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
]

WAVE2 = [
    ('lazada_tt', 'clockworks~free-tiktok-scraper', {
        'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
    ('shopee_tt', 'clockworks~free-tiktok-scraper', {
        'profiles': ['shopeesg'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
]


def run_wave(wave, label):
    results = {}
    threads = []
    for name, actor, body in wave:
        t = threading.Thread(target=run_and_collect, args=(actor, body, name, results))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    print(f'  [{label} complete]', flush=True)
    return results


# ── Stats computation ────────────────────────────────────────────────────────

def ig_stats(items):
    if not items:
        return _empty_stats()
    likes    = [i.get('likesCount')    or i.get('likes',    0) for i in items]
    comments = [i.get('commentsCount') or i.get('comments', 0) for i in items]
    plays    = [i.get('videoPlayCount') or i.get('videoViewCount') or 0 for i in items]
    videos   = sum(1 for i in items if i.get('type', '') in ('Video', 'video', 'Reel'))
    n = len(items)
    total_eng = sum(likes) + sum(comments)
    avg_eng   = total_eng / n if n else 0
    # ER% approximation: avg (likes+comments) / avg_likes scaled to pct
    # True ER needs followers; we report avg-engagements-per-post
    return {
        'posts':        n,
        'total_likes':  sum(likes),
        'total_comments': sum(comments),
        'total_plays':  sum(plays),
        'total_shares': 0,
        'avg_likes':    round(sum(likes)    / n, 1) if n else 0,
        'avg_comments': round(sum(comments) / n, 1) if n else 0,
        'avg_plays':    round(sum(plays)    / n, 1) if n else 0,
        'avg_er_pct':   None,   # requires follower count
        'video_count':  videos,
        'items':        items,
    }


def tt_stats(items):
    if not items:
        return _empty_stats()
    likes    = [i.get('diggCount')    or i.get('likes',    0) for i in items]
    comments = [i.get('commentCount') or i.get('comments', 0) for i in items]
    plays    = [i.get('playCount')    or i.get('plays',    0) for i in items]
    shares   = [i.get('shareCount')   or i.get('shares',   0) for i in items]
    n = len(items)
    total_plays = sum(plays)
    total_eng   = sum(likes) + sum(comments) + sum(shares)
    avg_er = round(total_eng / total_plays * 100, 2) if total_plays else None
    return {
        'posts':          n,
        'total_likes':    sum(likes),
        'total_comments': sum(comments),
        'total_plays':    sum(plays),
        'total_shares':   sum(shares),
        'avg_likes':      round(sum(likes)    / n, 1) if n else 0,
        'avg_comments':   round(sum(comments) / n, 1) if n else 0,
        'avg_plays':      round(sum(plays)    / n, 1) if n else 0,
        'avg_shares':     round(sum(shares)   / n, 1) if n else 0,
        'avg_er_pct':     avg_er,
        'video_count':    n,   # all TikTok posts are videos
        'items':          items,
    }


def _empty_stats():
    return {
        'posts': 0, 'total_likes': 0, 'total_comments': 0,
        'total_plays': 0, 'total_shares': 0,
        'avg_likes': 0, 'avg_comments': 0, 'avg_plays': 0, 'avg_shares': 0,
        'avg_er_pct': None, 'video_count': 0, 'items': [],
    }


# ── Chart helpers ─────────────────────────────────────────────────────────────

def bar40(val_a, val_b, label_a='Lazada', label_b='Shopee', width=40):
    """Head-to-head horizontal bar (40 chars) using █/░."""
    total = val_a + val_b
    if total == 0:
        fa = fb = width // 2
    else:
        fa = round(val_a / total * width)
        fb = width - fa
    la = f'{val_a:,}'
    lb = f'{val_b:,}'
    line_a = f'{label_a:<8} {la:>8}  {"█" * fa}{"░" * (width - fa)}'
    line_b = f'{label_b:<8} {lb:>8}  {"░" * (width - fb)}{"█" * fb}'
    return line_a + '\n' + line_b


def mix_bar(video_count, total_count, width=14):
    """Content mix bar: video vs image/static (14 chars)."""
    if total_count == 0:
        return '░' * width
    vf = round(video_count / total_count * width)
    return '█' * vf + '░' * (width - vf)


def top5(items, platform):
    """Return top-5 posts sorted by engagement."""
    def eng(i):
        if platform == 'ig':
            return (i.get('likesCount') or 0) + (i.get('commentsCount') or 0)
        return (i.get('diggCount') or 0) + (i.get('commentCount') or 0) + (i.get('shareCount') or 0)

    ranked = sorted(items, key=eng, reverse=True)[:5]
    lines  = []
    for rank, i in enumerate(ranked, 1):
        if platform == 'ig':
            url     = i.get('url', i.get('shortCode', 'n/a'))
            caption = (i.get('caption') or '')[:60].replace('\n', ' ')
            e       = eng(i)
            lines.append(f'  #{rank}  ❤ {i.get("likesCount",0):,}  💬 {i.get("commentsCount",0):,}  (eng {e:,})')
            lines.append(f'       {caption[:55]}')
            lines.append(f'       {url}')
        else:
            url     = i.get('webVideoUrl', i.get('id', 'n/a'))
            caption = (i.get('text') or '')[:60].replace('\n', ' ')
            e       = eng(i)
            lines.append(f'  #{rank}  ❤ {i.get("diggCount",0):,}  💬 {i.get("commentCount",0):,}  '
                         f'▶ {i.get("playCount",0):,}  🔁 {i.get("shareCount",0):,}  (eng {e:,})')
            lines.append(f'       {caption[:55]}')
            lines.append(f'       {url}')
    return '\n'.join(lines)


def fmt_er(val):
    return f'{val:.2f}%' if val is not None else 'N/A*'


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(st):
    lz_ig = st['lazada_ig']
    sh_ig = st['shopee_ig']
    lz_tt = st['lazada_tt']
    sh_tt = st['shopee_tt']

    lines = []
    A = lines.append

    A(f'COMPETITOR SOCIAL MEDIA REPORT — {TODAY_STR}')
    A('=' * 64)
    A('')

    # ── 1. TikTok Overview ───────────────────────────────────────────
    A('▌ TIKTOK OVERVIEW')
    A('-' * 64)
    A(f'{"Metric":<22}  {"Lazada SG":>12}  {"Shopee SG":>12}')
    A(f'{"Posts sampled":<22}  {lz_tt["posts"]:>12}  {sh_tt["posts"]:>12}')
    A(f'{"Total Likes":<22}  {lz_tt["total_likes"]:>12,}  {sh_tt["total_likes"]:>12,}')
    A(f'{"Total Comments":<22}  {lz_tt["total_comments"]:>12,}  {sh_tt["total_comments"]:>12,}')
    A(f'{"Total Plays":<22}  {lz_tt["total_plays"]:>12,}  {sh_tt["total_plays"]:>12,}')
    A(f'{"Total Shares":<22}  {lz_tt["total_shares"]:>12,}  {sh_tt["total_shares"]:>12,}')
    A(f'{"Avg Plays / post":<22}  {lz_tt["avg_plays"]:>12,.0f}  {sh_tt["avg_plays"]:>12,.0f}')
    A(f'{"Avg ER%":<22}  {fmt_er(lz_tt["avg_er_pct"]):>12}  {fmt_er(sh_tt["avg_er_pct"]):>12}')
    A('')

    A('  Head-to-head — Avg Plays per post')
    A('  ' + bar40(lz_tt['avg_plays'], sh_tt['avg_plays'], 'Lazada', 'Shopee'))
    A('')
    A('  Head-to-head — Total Likes')
    A('  ' + bar40(lz_tt['total_likes'], sh_tt['total_likes'], 'Lazada', 'Shopee'))
    A('')
    A('  Content mix (all TikTok = video)  █=video ░=static')
    A(f'  Lazada  [{mix_bar(lz_tt["video_count"], lz_tt["posts"])}]  {lz_tt["video_count"]}/{lz_tt["posts"]}')
    A(f'  Shopee  [{mix_bar(sh_tt["video_count"], sh_tt["posts"])}]  {sh_tt["video_count"]}/{sh_tt["posts"]}')
    A('')

    A('  Top 5 TikTok posts — Lazada SG')
    A(top5(lz_tt['items'], 'tt') or '  (no data)')
    A('')
    A('  Top 5 TikTok posts — Shopee SG')
    A(top5(sh_tt['items'], 'tt') or '  (no data)')
    A('')

    # ── 2. Instagram Overview ────────────────────────────────────────
    A('▌ INSTAGRAM OVERVIEW')
    A('-' * 64)
    A(f'{"Metric":<22}  {"Lazada SG":>12}  {"Shopee SG":>12}')
    A(f'{"Posts sampled":<22}  {lz_ig["posts"]:>12}  {sh_ig["posts"]:>12}')
    A(f'{"Total Likes":<22}  {lz_ig["total_likes"]:>12,}  {sh_ig["total_likes"]:>12,}')
    A(f'{"Total Comments":<22}  {lz_ig["total_comments"]:>12,}  {sh_ig["total_comments"]:>12,}')
    A(f'{"Avg Likes / post":<22}  {lz_ig["avg_likes"]:>12,.1f}  {sh_ig["avg_likes"]:>12,.1f}')
    A(f'{"Avg Comments / post":<22}  {lz_ig["avg_comments"]:>12,.1f}  {sh_ig["avg_comments"]:>12,.1f}')
    A(f'{"Avg ER%":<22}  {"N/A*":>12}  {"N/A*":>12}')
    A(f'{"Video posts":<22}  {lz_ig["video_count"]:>12}  {sh_ig["video_count"]:>12}')
    A('')

    A('  Head-to-head — Total Likes')
    A('  ' + bar40(lz_ig['total_likes'], sh_ig['total_likes'], 'Lazada', 'Shopee'))
    A('')
    A('  Head-to-head — Total Comments')
    A('  ' + bar40(lz_ig['total_comments'], sh_ig['total_comments'], 'Lazada', 'Shopee'))
    A('')
    A('  Content mix  █=video ░=static/carousel')
    A(f'  Lazada  [{mix_bar(lz_ig["video_count"], lz_ig["posts"])}]  {lz_ig["video_count"]}/{lz_ig["posts"]} video')
    A(f'  Shopee  [{mix_bar(sh_ig["video_count"], sh_ig["posts"])}]  {sh_ig["video_count"]}/{sh_ig["posts"]} video')
    A('')

    A('  Top 5 Instagram posts — Lazada SG')
    A(top5(lz_ig['items'], 'ig') or '  (no data)')
    A('')
    A('  Top 5 Instagram posts — Shopee SG')
    A(top5(sh_ig['items'], 'ig') or '  (no data)')
    A('')

    # ── 3. Executive Summary ─────────────────────────────────────────
    A('▌ EXECUTIVE SUMMARY')
    A('-' * 64)

    # Determine TikTok reach winner
    lz_plays = lz_tt['total_plays']
    sh_plays  = sh_tt['total_plays']
    tt_winner = 'Shopee SG' if sh_plays > lz_plays else 'Lazada SG'
    tt_pct = abs(sh_plays - lz_plays) / max(sh_plays, lz_plays) * 100 if max(sh_plays, lz_plays) else 0

    # IG ER winner (avg comments+likes per post as proxy)
    lz_eng = lz_ig['avg_likes'] + lz_ig['avg_comments']
    sh_eng = sh_ig['avg_likes'] + sh_ig['avg_comments']
    ig_er_winner = 'Shopee SG' if sh_eng > lz_eng else 'Lazada SG'
    ig_er_loser  = 'Lazada SG' if ig_er_winner == 'Shopee SG' else 'Shopee SG'

    # IG likes gap
    lz_likes = lz_ig['total_likes']
    sh_likes  = sh_ig['total_likes']
    likes_leader = 'Shopee SG' if sh_likes > lz_likes else 'Lazada SG'
    likes_lagger = 'Lazada SG' if likes_leader == 'Shopee SG' else 'Shopee SG'
    likes_gap    = abs(sh_likes - lz_likes)

    s1 = (f'On TikTok, {tt_winner} leads in total video reach with {max(lz_plays, sh_plays):,} plays '
          f'({tt_pct:.0f}% ahead), indicating stronger short-video distribution or posting cadence.')

    s2 = (f'On Instagram, {ig_er_winner} wins on average post engagement '
          f'({max(lz_eng, sh_eng):,.0f} avg likes+comments vs {min(lz_eng, sh_eng):,.0f} for {ig_er_loser}), '
          f'suggesting more resonant content or a more active follower base.')

    s3 = (f'{likes_lagger} trails by {likes_gap:,} total Instagram likes in this sample; '
          f'increasing Reel output and carousel storytelling could close the gap against {likes_leader}\'s content playbook.')

    A(s1)
    A('')
    A(s2)
    A('')
    A(s3)
    A('')

    A('─' * 64)
    A('* ER% on Instagram requires follower counts not returned by post scraper.')
    A(f'  TikTok ER% = (likes + comments + shares) / plays × 100.')
    A(f'  Data sampled: up to 15 most-recent posts per account, {TODAY_STR}.')

    return '\n'.join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f'\n=== WAVE 1: Instagram scrapers ===', flush=True)
    w1 = run_wave(WAVE1, 'WAVE 1')

    print(f'\n=== WAVE 2: TikTok scrapers ===', flush=True)
    w2 = run_wave(WAVE2, 'WAVE 2')

    all_items = {**w1, **w2}

    print('\n=== Computing stats ===', flush=True)
    stats = {
        'lazada_ig': ig_stats(all_items.get('lazada_ig', [])),
        'shopee_ig': ig_stats(all_items.get('shopee_ig', [])),
        'lazada_tt': tt_stats(all_items.get('lazada_tt', [])),
        'shopee_tt': tt_stats(all_items.get('shopee_tt', [])),
    }

    report_text = build_report(stats)

    # Strip raw items from stats output to keep JSON lean
    stats_clean = {k: {m: v for m, v in s.items() if m != 'items'} for k, s in stats.items()}

    output = {'report_text': report_text, 'stats': stats_clean}
    print(json.dumps(output))


if __name__ == '__main__':
    main()
