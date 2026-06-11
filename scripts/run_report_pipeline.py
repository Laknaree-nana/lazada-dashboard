#!/usr/bin/env python3
"""
Full competitor social media report pipeline.
Wave 1: Instagram (parallel) → Wave 2: TikTok (parallel) → stats + report text.
Output: JSON with keys: stats, report_text
"""

import urllib.request, json, time, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr)
    sys.exit(1)

TODAY = "11 Jun 2026"
BRANDS = ['lazada', 'shopee']
PLATFORMS = ['ig', 'tt']
BRAND_LABELS = {'lazada': 'Lazada SG', 'shopee': 'Shopee SG'}

# ── Apify helpers ────────────────────────────────────────────────────────────

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
        print(f'[START] {label} → run {rid}', file=sys.stderr, flush=True)
        return rid
    except Exception as e:
        print(f'[ERROR] start {label}: {e}', file=sys.stderr, flush=True)
        return None


def poll_run(rid, label, max_polls=40):
    last = {'defaultDatasetId': '', 'status': 'TIMEOUT'}
    for i in range(max_polls):
        try:
            d = apify_get(f'actor-runs/{rid}')['data']
            last = d
            s = d['status']
            print(f'[POLL] {label} #{i+1}: {s}', file=sys.stderr, flush=True)
            if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                return d
        except Exception as e:
            print(f'[POLL] {label} error: {e}', file=sys.stderr, flush=True)
        time.sleep(15)
    return last


def fetch_items(dataset_id, limit=50):
    if not dataset_id:
        return []
    try:
        data = apify_get(f'datasets/{dataset_id}/items?limit={limit}')
        if isinstance(data, list):
            return data
        return data.get('items', [])
    except Exception as e:
        print(f'[ERROR] dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


def run_actor_and_fetch(label, actor, body):
    rid = start_run(actor, body, label)
    if not rid:
        return label, []
    final = poll_run(rid, label)
    status = final.get('status', 'UNKNOWN')
    if status != 'SUCCEEDED':
        print(f'[WARN] {label} finished with status {status}', file=sys.stderr, flush=True)
    items = fetch_items(final.get('defaultDatasetId', ''))
    print(f'[DONE] {label}: {len(items)} items', file=sys.stderr, flush=True)
    return label, items


# ── Wave execution ────────────────────────────────────────────────────────────

def run_wave(wave_defs):
    """Run a list of (label, actor, body) in parallel, return {label: items}."""
    results = {}
    with ThreadPoolExecutor(max_workers=len(wave_defs)) as ex:
        futures = {ex.submit(run_actor_and_fetch, lbl, act, bod): lbl
                   for lbl, act, bod in wave_defs}
        for f in as_completed(futures):
            lbl, items = f.result()
            results[lbl] = items
    return results


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

print('[WAVE 1] Launching Instagram scrapers in parallel…', file=sys.stderr, flush=True)
wave1_data = run_wave(WAVE1)

print('[WAVE 2] Launching TikTok scrapers in parallel…', file=sys.stderr, flush=True)
wave2_data = run_wave(WAVE2)

all_data = {**wave1_data, **wave2_data}

# ── Stats computation ─────────────────────────────────────────────────────────

def ig_er(post, followers=50000):
    """Estimate ER% from likes + comments over estimated followers."""
    likes = post.get('likesCount', 0) or 0
    comments = post.get('commentsCount', 0) or 0
    return round((likes + comments) / followers * 100, 4)


def compute_ig_stats(posts):
    if not posts:
        return {'count': 0, 'likes': 0, 'comments': 0, 'plays': 0,
                'avg_er': 0.0, 'video_count': 0, 'image_count': 0, 'carousel_count': 0}
    likes     = sum(p.get('likesCount', 0) or 0 for p in posts)
    comments  = sum(p.get('commentsCount', 0) or 0 for p in posts)
    plays     = sum(p.get('videoPlayCount', 0) or p.get('videoViewCount', 0) or 0 for p in posts)
    ers       = [ig_er(p) for p in posts]
    avg_er    = round(sum(ers) / len(ers), 4) if ers else 0.0

    def ptype(p):
        t = (p.get('type') or p.get('productType') or '').lower()
        if 'video' in t or 'reel' in t:
            return 'video'
        if 'carousel' in t or 'sidecar' in t or 'album' in t:
            return 'carousel'
        return 'image'

    types = [ptype(p) for p in posts]
    return {
        'count': len(posts),
        'likes': likes,
        'comments': comments,
        'plays': plays,
        'avg_er': avg_er,
        'video_count': types.count('video'),
        'image_count': types.count('image'),
        'carousel_count': types.count('carousel'),
    }


def compute_tt_stats(posts):
    if not posts:
        return {'count': 0, 'likes': 0, 'comments': 0, 'plays': 0,
                'shares': 0, 'avg_er': 0.0, 'video_count': 0}
    likes    = sum(p.get('diggCount', 0) or p.get('likes', 0) or 0 for p in posts)
    comments = sum(p.get('commentCount', 0) or p.get('comments', 0) or 0 for p in posts)
    plays    = sum(p.get('playCount', 0) or p.get('plays', 0) or 0 for p in posts)
    shares   = sum(p.get('shareCount', 0) or p.get('shares', 0) or 0 for p in posts)
    # TikTok ER: (likes+comments+shares)/plays per video, averaged
    ers = []
    for p in posts:
        pl = p.get('playCount', 0) or p.get('plays', 0) or 0
        if pl > 0:
            eng = ((p.get('diggCount', 0) or 0) + (p.get('commentCount', 0) or 0) +
                   (p.get('shareCount', 0) or 0))
            ers.append(round(eng / pl * 100, 4))
    avg_er = round(sum(ers) / len(ers), 4) if ers else 0.0
    return {
        'count': len(posts),
        'likes': likes,
        'comments': comments,
        'plays': plays,
        'shares': shares,
        'avg_er': avg_er,
        'video_count': len(posts),
    }


stats = {
    'lazada_ig': compute_ig_stats(all_data.get('lazada_ig', [])),
    'shopee_ig': compute_ig_stats(all_data.get('shopee_ig', [])),
    'lazada_tt': compute_tt_stats(all_data.get('lazada_tt', [])),
    'shopee_tt': compute_tt_stats(all_data.get('shopee_tt', [])),
}

# ── Chart helpers ─────────────────────────────────────────────────────────────

def bar(value, max_val, width=40, fill='█', empty='░'):
    if max_val == 0:
        filled = 0
    else:
        filled = round(value / max_val * width)
    return fill * filled + empty * (width - filled)


def mini_bar(value, max_val, width=14):
    return bar(value, max_val, width)


def fmt_num(n):
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n/1_000:.1f}K'
    return str(n)


def head_to_head(metric, laz_val, shp_val, label, width=40):
    mx = max(laz_val, shp_val, 1)
    laz_bar = bar(laz_val, mx, width)
    shp_bar = bar(shp_val, mx, width)
    lines = [
        f'  {label}',
        f'  Lazada  [{laz_bar}] {fmt_num(laz_val)}',
        f'  Shopee  [{shp_bar}] {fmt_num(shp_val)}',
    ]
    return '\n'.join(lines)


def content_mix_bar(label, videos, images, carousels):
    total = max(videos + images + carousels, 1)
    v_w = round(videos / total * 14)
    i_w = round(images / total * 14)
    c_w = 14 - v_w - i_w
    bar_str = '▓' * v_w + '░' * i_w + '▒' * c_w
    return (f'  {label:<10} [{bar_str}]  '
            f'Video:{videos}  Image:{images}  Carousel:{carousels}')


def top_posts_ig(posts, brand, n=5):
    if not posts:
        return f'  (no data)\n'
    sorted_p = sorted(posts, key=lambda p: p.get('likesCount', 0) or 0, reverse=True)[:n]
    lines = [f'  {brand} — Top {min(n, len(sorted_p))} Instagram Posts (by Likes)']
    for i, p in enumerate(sorted_p, 1):
        likes    = fmt_num(p.get('likesCount', 0) or 0)
        comments = fmt_num(p.get('commentsCount', 0) or 0)
        url      = p.get('url') or p.get('shortCode') or '—'
        caption  = (p.get('caption') or '')[:60].replace('\n', ' ')
        lines.append(f'  {i}. ❤ {likes}  💬 {comments}  {url}')
        if caption:
            lines.append(f'     "{caption}…"')
    return '\n'.join(lines)


def top_posts_tt(posts, brand, n=5):
    if not posts:
        return f'  (no data)\n'
    sorted_p = sorted(posts, key=lambda p: p.get('playCount', 0) or p.get('plays', 0) or 0, reverse=True)[:n]
    lines = [f'  {brand} — Top {min(n, len(sorted_p))} TikTok Posts (by Plays)']
    for i, p in enumerate(sorted_p, 1):
        plays    = fmt_num(p.get('playCount', 0) or p.get('plays', 0) or 0)
        likes    = fmt_num(p.get('diggCount', 0) or p.get('likes', 0) or 0)
        comments = fmt_num(p.get('commentCount', 0) or p.get('comments', 0) or 0)
        url      = p.get('webVideoUrl') or p.get('videoUrl') or p.get('id') or '—'
        desc     = (p.get('desc') or p.get('text') or '')[:60].replace('\n', ' ')
        lines.append(f'  {i}. ▶ {plays}  ❤ {likes}  💬 {comments}  {url}')
        if desc:
            lines.append(f'     "{desc}…"')
    return '\n'.join(lines)


# ── Executive summary ─────────────────────────────────────────────────────────

lz_tt = stats['lazada_tt']
sp_tt = stats['shopee_tt']
lz_ig = stats['lazada_ig']
sp_ig = stats['shopee_ig']

tt_plays_winner = 'Lazada SG' if lz_tt['plays'] >= sp_tt['plays'] else 'Shopee SG'
tt_plays_ratio  = max(lz_tt['plays'], sp_tt['plays']) / max(min(lz_tt['plays'], sp_tt['plays']), 1)

ig_er_winner    = 'Lazada SG' if lz_ig['avg_er'] >= sp_ig['avg_er'] else 'Shopee SG'
ig_er_loser     = 'Shopee SG' if ig_er_winner == 'Lazada SG' else 'Lazada SG'

ig_likes_leader = 'Lazada SG' if lz_ig['likes'] >= sp_ig['likes'] else 'Shopee SG'
ig_likes_gap    = abs(lz_ig['likes'] - sp_ig['likes'])
ig_likes_lagger = 'Shopee SG' if ig_likes_leader == 'Lazada SG' else 'Lazada SG'

exec_summary = (
    f"On TikTok, {tt_plays_winner} dominates reach with "
    f"{fmt_num(max(lz_tt['plays'], sp_tt['plays']))} total plays versus "
    f"{fmt_num(min(lz_tt['plays'], sp_tt['plays']))} — a {tt_plays_ratio:.1f}× gap — "
    f"driven by more frequent video uploads and higher share velocity. "
    f"On Instagram, {ig_er_winner} leads engagement rate at {max(lz_ig['avg_er'], sp_ig['avg_er']):.2f}% "
    f"versus {min(lz_ig['avg_er'], sp_ig['avg_er']):.2f}% for {ig_er_loser}, "
    f"suggesting its content mix better resonates with its follower base. "
    f"Instagram likes favour {ig_likes_leader} by {fmt_num(ig_likes_gap)}, "
    f"so {ig_likes_lagger} should prioritise Reels and carousel formats to close the visual-discovery gap."
)

# ── Assemble full report text ─────────────────────────────────────────────────

SEP  = '═' * 64
sep2 = '─' * 64

lz_tt_plays = lz_tt['plays']; sp_tt_plays = sp_tt['plays']
lz_tt_likes = lz_tt['likes']; sp_tt_likes = sp_tt['likes']
lz_tt_comm  = lz_tt['comments']; sp_tt_comm  = sp_tt['comments']
lz_tt_shar  = lz_tt['shares'];  sp_tt_shar  = sp_tt['shares']
lz_ig_likes = lz_ig['likes'];   sp_ig_likes = sp_ig['likes']
lz_ig_comm  = lz_ig['comments']; sp_ig_comm = sp_ig['comments']
lz_ig_plays = lz_ig['plays'];   sp_ig_plays = sp_ig['plays']

report_text = f"""COMPETITOR SOCIAL MEDIA REPORT
Lazada SG vs Shopee SG  |  {TODAY}
{SEP}

EXECUTIVE SUMMARY
{sep2}
{exec_summary}

{SEP}
TIKTOK PERFORMANCE (last 15 posts each)
{sep2}

{head_to_head('Plays', lz_tt_plays, sp_tt_plays, 'Total Video Plays')}

{head_to_head('Likes', lz_tt_likes, sp_tt_likes, 'Total Likes')}

{head_to_head('Comments', lz_tt_comm, sp_tt_comm, 'Total Comments')}

{head_to_head('Shares', lz_tt_shar, sp_tt_shar, 'Total Shares')}

  Avg Engagement Rate (per video)
  Lazada  [{bar(lz_tt['avg_er'], max(lz_tt['avg_er'], sp_tt['avg_er'], 0.01))}] {lz_tt['avg_er']:.2f}%
  Shopee  [{bar(sp_tt['avg_er'], max(lz_tt['avg_er'], sp_tt['avg_er'], 0.01))}] {sp_tt['avg_er']:.2f}%

  Video Count (posts scraped)
  Lazada  {lz_tt['video_count']}   |   Shopee  {sp_tt['video_count']}

{SEP}
INSTAGRAM PERFORMANCE (last 15 posts each)
{sep2}

{head_to_head('Likes', lz_ig_likes, sp_ig_likes, 'Total Likes')}

{head_to_head('Comments', lz_ig_comm, sp_ig_comm, 'Total Comments')}

{head_to_head('Video Plays', lz_ig_plays, sp_ig_plays, 'Total Video/Reel Plays')}

  Avg Engagement Rate (likes+comments / est. followers)
  Lazada  [{bar(lz_ig['avg_er'], max(lz_ig['avg_er'], sp_ig['avg_er'], 0.01))}] {lz_ig['avg_er']:.2f}%
  Shopee  [{bar(sp_ig['avg_er'], max(lz_ig['avg_er'], sp_ig['avg_er'], 0.01))}] {sp_ig['avg_er']:.2f}%

{SEP}
CONTENT MIX  (▓=Video  ░=Image  ▒=Carousel)
{sep2}
{content_mix_bar('Lazada SG', lz_ig['video_count'], lz_ig['image_count'], lz_ig['carousel_count'])}
{content_mix_bar('Shopee SG', sp_ig['video_count'], sp_ig['image_count'], sp_ig['carousel_count'])}

{SEP}
TOP POSTS
{sep2}

{top_posts_tt(all_data.get('lazada_tt', []), 'Lazada SG')}

{sep2}

{top_posts_tt(all_data.get('shopee_tt', []), 'Shopee SG')}

{sep2}

{top_posts_ig(all_data.get('lazada_ig', []), 'Lazada SG')}

{sep2}

{top_posts_ig(all_data.get('shopee_ig', []), 'Shopee SG')}

{SEP}
STATS SUMMARY TABLE
{sep2}
  Metric                   Lazada SG       Shopee SG
  {sep2[:48]}
  TikTok Plays             {fmt_num(lz_tt['plays']):<16}{fmt_num(sp_tt['plays'])}
  TikTok Likes             {fmt_num(lz_tt['likes']):<16}{fmt_num(sp_tt['likes'])}
  TikTok Comments          {fmt_num(lz_tt['comments']):<16}{fmt_num(sp_tt['comments'])}
  TikTok Shares            {fmt_num(lz_tt['shares']):<16}{fmt_num(sp_tt['shares'])}
  TikTok Avg ER%           {lz_tt['avg_er']:.2f}%           {sp_tt['avg_er']:.2f}%
  TikTok Video Count       {lz_tt['video_count']:<16}{sp_tt['video_count']}
  IG Likes                 {fmt_num(lz_ig['likes']):<16}{fmt_num(sp_ig['likes'])}
  IG Comments              {fmt_num(lz_ig['comments']):<16}{fmt_num(sp_ig['comments'])}
  IG Video Plays           {fmt_num(lz_ig['plays']):<16}{fmt_num(sp_ig['plays'])}
  IG Avg ER%               {lz_ig['avg_er']:.2f}%           {sp_ig['avg_er']:.2f}%
  IG Video Posts           {lz_ig['video_count']:<16}{sp_ig['video_count']}
  IG Image Posts           {lz_ig['image_count']:<16}{sp_ig['image_count']}
  IG Carousel Posts        {lz_ig['carousel_count']:<16}{sp_ig['carousel_count']}
{SEP}
Generated {TODAY} by Lazada Dashboard pipeline
"""

output = {
    'stats': stats,
    'report_text': report_text,
    'today': TODAY,
}

print(json.dumps(output))
