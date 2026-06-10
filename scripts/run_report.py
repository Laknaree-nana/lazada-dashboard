"""
Lazada SG vs Shopee SG — Competitor Social Media Report Pipeline
Wave 1: Instagram (parallel) → Wave 2: TikTok (parallel) → Report → stdout
"""

import json, os, sys, time
import urllib.request

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
    r = apify_post(f'acts/{actor}/runs', body)
    rid = r['data']['id']
    print(f'  [START] {label} → run {rid}', file=sys.stderr, flush=True)
    return rid


def poll_until_done(run_map, timeout_rounds=30):
    """run_map: {label: run_id}. Returns {label: run_data}."""
    remaining = dict(run_map)
    done = {}
    for i in range(timeout_rounds):
        if not remaining:
            break
        for label, rid in list(remaining.items()):
            try:
                d = apify_get(f'actor-runs/{rid}')['data']
                s = d['status']
                print(f'  [POLL {i+1}] {label}: {s}', file=sys.stderr, flush=True)
                if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                    done[label] = d
                    del remaining[label]
            except Exception as e:
                print(f'  [POLL {i+1}] {label} error: {e}', file=sys.stderr, flush=True)
        if remaining:
            time.sleep(15)
    for label in remaining:
        print(f'  [TIMEOUT] {label}', file=sys.stderr)
        done[label] = {'status': 'TIMEOUT', 'defaultDatasetId': ''}
    return done


def fetch_items(dataset_id, limit=50):
    if not dataset_id:
        return []
    try:
        data = apify_get(f'datasets/{dataset_id}/items?limit={limit}')
        # Apify may return list directly or {"data": {"items": [...]}}
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get('data', {}).get('items', data.get('items', []))
        return []
    except Exception as e:
        print(f'  [ERROR] fetch dataset {dataset_id}: {e}', file=sys.stderr)
        return []


# ── Wave execution ─────────────────────────────────────────────────────────────

print('\n══ WAVE 1: Instagram scrapers ══', file=sys.stderr)
ig_configs = {
    'lazada_ig': ('apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/Lazada_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
    'shopee_ig': ('apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/shopee_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
}

ig_run_ids = {}
for label, (actor, body) in ig_configs.items():
    ig_run_ids[label] = start_run(actor, body, label)

ig_done = poll_until_done(ig_run_ids)

print('\n══ WAVE 2: TikTok scrapers ══', file=sys.stderr)
tt_configs = {
    'lazada_tt': ('clockworks~free-tiktok-scraper', {
        'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
    'shopee_tt': ('clockworks~free-tiktok-scraper', {
        'profiles': ['shopeesg'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
}

tt_run_ids = {}
for label, (actor, body) in tt_configs.items():
    tt_run_ids[label] = start_run(actor, body, label)

tt_done = poll_until_done(tt_run_ids)

# ── Fetch datasets ─────────────────────────────────────────────────────────────

print('\n══ Fetching datasets ══', file=sys.stderr)
all_done = {**ig_done, **tt_done}
datasets = {}
for label, run_data in all_done.items():
    did = run_data.get('defaultDatasetId', '')
    items = fetch_items(did)
    datasets[label] = items
    print(f'  {label}: {len(items)} items (status={run_data["status"]})', file=sys.stderr)

# ── Stats computation ──────────────────────────────────────────────────────────

def ig_stats(posts):
    if not posts:
        return {}
    likes   = [p.get('likesCount', 0) or 0 for p in posts]
    comments= [p.get('commentsCount', 0) or 0 for p in posts]
    followers = posts[0].get('followersCount', 0) or 1
    er_list = [(l + c) / followers * 100 for l, c in zip(likes, comments)]
    video_types = {'Video', 'Reel', 'REEL', 'VIDEO'}
    videos = sum(1 for p in posts if p.get('type', p.get('productType', '')) in video_types)
    return {
        'post_count':   len(posts),
        'total_likes':  sum(likes),
        'total_comments': sum(comments),
        'avg_likes':    sum(likes) / len(likes),
        'avg_comments': sum(comments) / len(comments),
        'avg_er_pct':   sum(er_list) / len(er_list),
        'video_count':  videos,
        'followers':    followers,
    }


def tt_stats(videos):
    if not videos:
        return {}
    likes   = [v.get('diggCount', 0) or 0 for v in videos]
    comments= [v.get('commentCount', 0) or 0 for v in videos]
    plays   = [v.get('playCount', 0) or 0 for v in videos]
    shares  = [v.get('shareCount', 0) or 0 for v in videos]
    followers = videos[0].get('authorMeta', {}).get('fans', 0) or 1
    er_list = [(l + c + s) / followers * 100 for l, c, s in zip(likes, comments, shares)]
    return {
        'post_count':   len(videos),
        'total_likes':  sum(likes),
        'total_comments': sum(comments),
        'total_plays':  sum(plays),
        'total_shares': sum(shares),
        'avg_likes':    sum(likes) / len(likes),
        'avg_comments': sum(comments) / len(comments),
        'avg_plays':    sum(plays) / len(plays),
        'avg_shares':   sum(shares) / len(shares),
        'avg_er_pct':   sum(er_list) / len(er_list),
        'video_count':  len(videos),
        'followers':    followers,
    }

stats = {
    'lazada_ig': ig_stats(datasets['lazada_ig']),
    'shopee_ig': ig_stats(datasets['shopee_ig']),
    'lazada_tt': tt_stats(datasets['lazada_tt']),
    'shopee_tt': tt_stats(datasets['shopee_tt']),
}

# ── Chart helpers ──────────────────────────────────────────────────────────────

def bar(value, max_value, width=40):
    if max_value == 0:
        filled = 0
    else:
        filled = round(value / max_value * width)
    filled = max(0, min(width, filled))
    return '█' * filled + '░' * (width - filled)


def content_bar(video_count, total, width=14):
    if total == 0:
        v_filled = 0
    else:
        v_filled = round(video_count / total * width)
    v_filled = max(0, min(width, v_filled))
    p_filled = width - v_filled
    return '▓' * v_filled + '░' * p_filled


def fmt_num(n):
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1_000:
        return f'{n/1_000:.1f}K'
    return str(int(n))


def top5_posts_ig(posts, label):
    if not posts:
        return f'  (no data)\n'
    ranked = sorted(posts, key=lambda p: (p.get('likesCount', 0) or 0) + (p.get('commentsCount', 0) or 0), reverse=True)[:5]
    lines = []
    for i, p in enumerate(ranked, 1):
        l = p.get('likesCount', 0) or 0
        c = p.get('commentsCount', 0) or 0
        url = p.get('url', p.get('shortCode', ''))
        caption = (p.get('caption') or '')[:60].replace('\n', ' ')
        lines.append(f'  {i}. ❤ {fmt_num(l):>6}  💬 {fmt_num(c):>5}  {caption[:50]!r}')
    return '\n'.join(lines)


def top5_posts_tt(videos, label):
    if not videos:
        return '  (no data)'
    ranked = sorted(videos, key=lambda v: v.get('playCount', 0) or 0, reverse=True)[:5]
    lines = []
    for i, v in enumerate(ranked, 1):
        plays  = v.get('playCount', 0) or 0
        likes  = v.get('diggCount', 0) or 0
        shares = v.get('shareCount', 0) or 0
        desc   = (v.get('text', '') or '')[:50].replace('\n', ' ')
        lines.append(f'  {i}. ▶ {fmt_num(plays):>7}  ❤ {fmt_num(likes):>6}  ↗ {fmt_num(shares):>5}  {desc!r}')
    return '\n'.join(lines)


# ── Build report ───────────────────────────────────────────────────────────────

li = stats['lazada_ig']
si = stats['shopee_ig']
lt = stats['lazada_tt']
st = stats['shopee_tt']

# Determine maxes for bar scaling
max_ig_likes   = max(li.get('avg_likes', 0),   si.get('avg_likes', 0),   1)
max_ig_er      = max(li.get('avg_er_pct', 0),  si.get('avg_er_pct', 0),  0.01)
max_tt_plays   = max(lt.get('avg_plays', 0),   st.get('avg_plays', 0),   1)
max_tt_likes   = max(lt.get('avg_likes', 0),   st.get('avg_likes', 0),   1)
max_tt_shares  = max(lt.get('avg_shares', 0),  st.get('avg_shares', 0),  1)
max_tt_er      = max(lt.get('avg_er_pct', 0),  st.get('avg_er_pct', 0),  0.01)

ig_er_winner = 'Lazada SG' if li.get('avg_er_pct', 0) >= si.get('avg_er_pct', 0) else 'Shopee SG'
likes_gap_abs = abs(li.get('avg_likes', 0) - si.get('avg_likes', 0))
likes_leader  = 'Lazada SG' if li.get('avg_likes', 0) >= si.get('avg_likes', 0) else 'Shopee SG'
tt_reach_leader = 'Lazada SG' if lt.get('avg_plays', 0) >= st.get('avg_plays', 0) else 'Shopee SG'
tt_reach_ratio  = max(lt.get('avg_plays',0), st.get('avg_plays',0)) / max(min(lt.get('avg_plays',0), st.get('avg_plays',0)), 1)

report = f"""
╔══════════════════════════════════════════════════════════════════╗
║        COMPETITOR SOCIAL MEDIA REPORT — {time.strftime('%d %b %Y').upper()}         ║
║               Lazada SG  vs  Shopee SG                          ║
╚══════════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 EXECUTIVE SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{tt_reach_leader} dominates TikTok reach with avg {fmt_num(max(lt.get('avg_plays',0), st.get('avg_plays',0)))} plays per video,
approximately {tt_reach_ratio:.1f}× ahead of the competitor on raw video views.
On Instagram, {ig_er_winner} leads engagement rate at {max(li.get('avg_er_pct',0), si.get('avg_er_pct',0)):.2f}% avg ER,
signalling stronger audience interaction per post.
{likes_leader} holds the Instagram likes lead by ~{fmt_num(likes_gap_abs)} avg likes per post,
and the lagging brand should prioritise Reel output and hashtag diversification
to close the visibility gap.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 INSTAGRAM — HEAD-TO-HEAD (40-char bars, avg per post)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 Metric          Lazada SG                                Shopee SG
 ────────────────────────────────────────────────────────────────────
 Avg Likes
   Lazada  [{bar(li.get('avg_likes',0), max_ig_likes)}] {fmt_num(li.get('avg_likes',0)):>8}
   Shopee  [{bar(si.get('avg_likes',0), max_ig_likes)}] {fmt_num(si.get('avg_likes',0)):>8}

 Avg Comments
   Lazada  [{bar(li.get('avg_comments',0), max(li.get('avg_comments',0), si.get('avg_comments',0), 1))}] {fmt_num(li.get('avg_comments',0)):>8}
   Shopee  [{bar(si.get('avg_comments',0), max(li.get('avg_comments',0), si.get('avg_comments',0), 1))}] {fmt_num(si.get('avg_comments',0)):>8}

 Avg ER %
   Lazada  [{bar(li.get('avg_er_pct',0), max_ig_er)}] {li.get('avg_er_pct',0):.2f}%
   Shopee  [{bar(si.get('avg_er_pct',0), max_ig_er)}] {si.get('avg_er_pct',0):.2f}%

 IG SUMMARY TABLE
 ┌─────────────────┬────────────┬────────────┐
 │ Metric          │  Lazada SG │  Shopee SG │
 ├─────────────────┼────────────┼────────────┤
 │ Posts scraped   │ {li.get('post_count',0):>10} │ {si.get('post_count',0):>10} │
 │ Total likes     │ {fmt_num(li.get('total_likes',0)):>10} │ {fmt_num(si.get('total_likes',0)):>10} │
 │ Total comments  │ {fmt_num(li.get('total_comments',0)):>10} │ {fmt_num(si.get('total_comments',0)):>10} │
 │ Avg likes/post  │ {fmt_num(li.get('avg_likes',0)):>10} │ {fmt_num(si.get('avg_likes',0)):>10} │
 │ Avg comments    │ {fmt_num(li.get('avg_comments',0)):>10} │ {fmt_num(si.get('avg_comments',0)):>10} │
 │ Avg ER %        │ {li.get('avg_er_pct',0):>9.2f}% │ {si.get('avg_er_pct',0):>9.2f}% │
 │ Video count     │ {li.get('video_count',0):>10} │ {si.get('video_count',0):>10} │
 │ Followers (est) │ {fmt_num(li.get('followers',0)):>10} │ {fmt_num(si.get('followers',0)):>10} │
 └─────────────────┴────────────┴────────────┘

 CONTENT MIX (14-char bar: ▓=Video/Reel  ░=Photo/Carousel)
   Lazada  [{content_bar(li.get('video_count',0), li.get('post_count',1))}]  {li.get('video_count',0)}/{li.get('post_count',0)} videos
   Shopee  [{content_bar(si.get('video_count',0), si.get('post_count',1))}]  {si.get('video_count',0)}/{si.get('post_count',0)} videos

 TOP 5 POSTS — Lazada SG Instagram (ranked by likes+comments)
{top5_posts_ig(datasets['lazada_ig'], 'lazada_ig')}

 TOP 5 POSTS — Shopee SG Instagram (ranked by likes+comments)
{top5_posts_ig(datasets['shopee_ig'], 'shopee_ig')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 TIKTOK — HEAD-TO-HEAD (40-char bars, avg per video)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

 Avg Plays (Reach)
   Lazada  [{bar(lt.get('avg_plays',0), max_tt_plays)}] {fmt_num(lt.get('avg_plays',0)):>8}
   Shopee  [{bar(st.get('avg_plays',0), max_tt_plays)}] {fmt_num(st.get('avg_plays',0)):>8}

 Avg Likes
   Lazada  [{bar(lt.get('avg_likes',0), max_tt_likes)}] {fmt_num(lt.get('avg_likes',0)):>8}
   Shopee  [{bar(st.get('avg_likes',0), max_tt_likes)}] {fmt_num(st.get('avg_likes',0)):>8}

 Avg Shares
   Lazada  [{bar(lt.get('avg_shares',0), max_tt_shares)}] {fmt_num(lt.get('avg_shares',0)):>8}
   Shopee  [{bar(st.get('avg_shares',0), max_tt_shares)}] {fmt_num(st.get('avg_shares',0)):>8}

 Avg ER %
   Lazada  [{bar(lt.get('avg_er_pct',0), max_tt_er)}] {lt.get('avg_er_pct',0):.2f}%
   Shopee  [{bar(st.get('avg_er_pct',0), max_tt_er)}] {st.get('avg_er_pct',0):.2f}%

 TIKTOK SUMMARY TABLE
 ┌─────────────────┬────────────┬────────────┐
 │ Metric          │  Lazada SG │  Shopee SG │
 ├─────────────────┼────────────┼────────────┤
 │ Videos scraped  │ {lt.get('video_count',0):>10} │ {st.get('video_count',0):>10} │
 │ Total plays     │ {fmt_num(lt.get('total_plays',0)):>10} │ {fmt_num(st.get('total_plays',0)):>10} │
 │ Total likes     │ {fmt_num(lt.get('total_likes',0)):>10} │ {fmt_num(st.get('total_likes',0)):>10} │
 │ Total comments  │ {fmt_num(lt.get('total_comments',0)):>10} │ {fmt_num(st.get('total_comments',0)):>10} │
 │ Total shares    │ {fmt_num(lt.get('total_shares',0)):>10} │ {fmt_num(st.get('total_shares',0)):>10} │
 │ Avg plays/video │ {fmt_num(lt.get('avg_plays',0)):>10} │ {fmt_num(st.get('avg_plays',0)):>10} │
 │ Avg likes/video │ {fmt_num(lt.get('avg_likes',0)):>10} │ {fmt_num(st.get('avg_likes',0)):>10} │
 │ Avg shares      │ {fmt_num(lt.get('avg_shares',0)):>10} │ {fmt_num(st.get('avg_shares',0)):>10} │
 │ Avg ER %        │ {lt.get('avg_er_pct',0):>9.2f}% │ {st.get('avg_er_pct',0):>9.2f}% │
 │ Followers (est) │ {fmt_num(lt.get('followers',0)):>10} │ {fmt_num(st.get('followers',0)):>10} │
 └─────────────────┴────────────┴────────────┘

 TOP 5 VIDEOS — Lazada SG TikTok (ranked by plays)
{top5_posts_tt(datasets['lazada_tt'], 'lazada_tt')}

 TOP 5 VIDEOS — Shopee SG TikTok (ranked by plays)
{top5_posts_tt(datasets['shopee_tt'], 'shopee_tt')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Raw data: {sum(len(v) for v in datasets.values())} total posts scraped
 Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

print(report)

# Write JSON for downstream use (committed by CI)
out_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
json_path = os.path.join(out_dir, 'social_report_data.json')
with open(json_path, 'w') as f:
    json.dump({'stats': stats, 'datasets': datasets, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, f, indent=2, default=str)
print(f'[DONE] Raw data written to {json_path}', file=sys.stderr)
