"""
Lazada SG Competitor Social Media Report Pipeline
Waves: IG (Wave 1) -> TikTok (Wave 2) -> Stats -> Report text
"""

import urllib.request, json, time, sys, os, datetime

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY environment variable not set', file=sys.stderr)
    sys.exit(1)

TODAY = datetime.date.today()
DATE_STR = TODAY.strftime('%d %b %Y')          # "19 Jun 2026"
DATE_SLUG = TODAY.strftime('%Y-%m-%d')          # "2026-06-19"

# ---------------------------------------------------------------------------
# Apify helpers
# ---------------------------------------------------------------------------

def apify_get(path):
    sep = '&' if '?' in path else '?'
    url = f'https://api.apify.com/v2/{path}{sep}token={API_KEY}'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as r:
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
        print(f'[START] {label} -> run {rid}', file=sys.stderr, flush=True)
        return rid
    except Exception as e:
        print(f'[ERROR] start {label}: {e}', file=sys.stderr, flush=True)
        return None


def poll_until_done(runs_dict, max_polls=60, interval=10):
    """Poll a dict {label: run_id} until all terminal. Returns {label: run_data}."""
    pending = {k: v for k, v in runs_dict.items() if v}
    results = {}
    for i in range(max_polls):
        still_running = {}
        for label, rid in pending.items():
            try:
                d = apify_get(f'actor-runs/{rid}')['data']
                s = d['status']
                print(f'[POLL] {label} #{i+1}: {s}', file=sys.stderr, flush=True)
                if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                    results[label] = d
                else:
                    still_running[label] = rid
            except Exception as e:
                print(f'[POLL] {label} error: {e}', file=sys.stderr, flush=True)
                still_running[label] = rid
        pending = still_running
        if not pending:
            break
        time.sleep(interval)
    # anything still pending -> timeout placeholder
    for label, rid in pending.items():
        results[label] = {'status': 'TIMEOUT', 'defaultDatasetId': ''}
    return results


def fetch_items(dataset_id, limit=50):
    if not dataset_id:
        return []
    try:
        return apify_get(f'datasets/{dataset_id}/items?limit={limit}')
    except Exception as e:
        print(f'[ERROR] dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


# ---------------------------------------------------------------------------
# Wave 1 – Instagram
# ---------------------------------------------------------------------------

print('\n=== WAVE 1: Instagram ===', file=sys.stderr, flush=True)

IG_ACTOR = 'apify~instagram-scraper'
ig_runs = {
    'lazada_ig': start_run(IG_ACTOR, {
        'directUrls': ['https://www.instagram.com/Lazada_SG/'],
        'resultsType': 'posts', 'resultsLimit': 20, 'addParentData': False,
    }, 'lazada_ig'),
    'shopee_ig': start_run(IG_ACTOR, {
        'directUrls': ['https://www.instagram.com/shopee_SG/'],
        'resultsType': 'posts', 'resultsLimit': 20, 'addParentData': False,
    }, 'shopee_ig'),
}

ig_final = poll_until_done(ig_runs)
for lbl, d in ig_final.items():
    print(f'[WAVE1] {lbl} finished: {d["status"]}', file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# Wave 2 – TikTok (starts after Wave 1)
# ---------------------------------------------------------------------------

print('\n=== WAVE 2: TikTok ===', file=sys.stderr, flush=True)

TT_ACTOR = 'clockworks~free-tiktok-scraper'
tt_runs = {
    'lazada_tt': start_run(TT_ACTOR, {
        'profiles': ['Lazada_SG'], 'resultsPerPage': 20,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }, 'lazada_tt'),
    'shopee_tt': start_run(TT_ACTOR, {
        'profiles': ['shopeesg'], 'resultsPerPage': 20,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }, 'shopee_tt'),
}

tt_final = poll_until_done(tt_runs)
for lbl, d in tt_final.items():
    print(f'[WAVE2] {lbl} finished: {d["status"]}', file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# Fetch all datasets
# ---------------------------------------------------------------------------

print('\n=== FETCHING DATASETS ===', file=sys.stderr, flush=True)

all_final = {**ig_final, **tt_final}
raw = {}
for label, d in all_final.items():
    dsid = d.get('defaultDatasetId', '')
    items = fetch_items(dsid, limit=50)
    raw[label] = items
    print(f'[DATA] {label}: {len(items)} items', file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def ig_stats(posts):
    if not posts:
        return {}
    likes = [p.get('likesCount', 0) or 0 for p in posts]
    comments = [p.get('commentsCount', 0) or 0 for p in posts]
    plays = [p.get('videoPlayCount', 0) or 0 for p in posts]
    follower = posts[0].get('ownerFollowersCount', 1) or 1
    er_list = [
        round(100 * (lk + cm) / follower, 2)
        for lk, cm in zip(likes, comments)
    ]
    video_posts = [p for p in posts if p.get('type') == 'Video' or p.get('videoPlayCount')]
    carousel = [p for p in posts if p.get('type') in ('Sidecar', 'carousel')]
    image_only = [p for p in posts if p not in video_posts and p not in carousel]
    return {
        'count': len(posts),
        'total_likes': sum(likes),
        'total_comments': sum(comments),
        'total_plays': sum(plays),
        'avg_likes': round(sum(likes) / len(posts)),
        'avg_comments': round(sum(comments) / len(posts)),
        'avg_er': round(sum(er_list) / len(er_list), 2),
        'followers': follower,
        'video_count': len(video_posts),
        'carousel_count': len(carousel),
        'image_count': len(image_only),
    }


def tt_stats(videos):
    if not videos:
        return {}
    plays   = [v.get('playCount', 0) or 0 for v in videos]
    likes   = [v.get('diggCount', 0) or 0 for v in videos]
    comments= [v.get('commentCount', 0) or 0 for v in videos]
    shares  = [v.get('shareCount', 0) or 0 for v in videos]
    followers = videos[0].get('authorMeta', {}).get('fans', 1) or 1
    er_list = [
        round(100 * (lk + cm + sh) / max(pl, 1), 2)
        for pl, lk, cm, sh in zip(plays, likes, comments, shares)
    ]
    return {
        'count': len(videos),
        'total_plays': sum(plays),
        'total_likes': sum(likes),
        'total_comments': sum(comments),
        'total_shares': sum(shares),
        'avg_plays': round(sum(plays) / len(videos)),
        'avg_likes': round(sum(likes) / len(videos)),
        'avg_comments': round(sum(comments) / len(videos)),
        'avg_shares': round(sum(shares) / len(videos)),
        'avg_er': round(sum(er_list) / len(er_list), 2),
        'followers': followers,
    }


stats = {
    'lazada_ig': ig_stats(raw.get('lazada_ig', [])),
    'shopee_ig': ig_stats(raw.get('shopee_ig', [])),
    'lazada_tt': tt_stats(raw.get('lazada_tt', [])),
    'shopee_tt': tt_stats(raw.get('shopee_tt', [])),
}

# ---------------------------------------------------------------------------
# Bar chart helpers
# ---------------------------------------------------------------------------

def hbar(val_a, val_b, width=40, fill='█', empty='░'):
    """Return two strings: bar for A and bar for B, proportional to values."""
    total = max(val_a + val_b, 1)
    a_width = round(width * val_a / total)
    b_width = round(width * val_b / total)
    return fill * a_width + empty * (width - a_width), fill * b_width + empty * (width - b_width)


def content_bar(v, c, i, width=14):
    """Stacked content-mix bar."""
    total = max(v + c + i, 1)
    vw = round(width * v / total)
    cw = round(width * c / total)
    iw = width - vw - cw
    return 'V' * vw + 'C' * cw + 'I' * iw


# ---------------------------------------------------------------------------
# Top 5 posts helper
# ---------------------------------------------------------------------------

def top5_ig(posts, sort_key='likesCount'):
    sorted_p = sorted(posts, key=lambda p: p.get(sort_key, 0) or 0, reverse=True)[:5]
    lines = []
    for i, p in enumerate(sorted_p, 1):
        url = p.get('url', p.get('shortCode', '?'))
        lk  = p.get('likesCount', 0) or 0
        cm  = p.get('commentsCount', 0) or 0
        cap = (p.get('caption') or '')[:60].replace('\n', ' ')
        lines.append(f'  {i}. {lk:,} likes | {cm:,} cmt | {url}')
        if cap:
            lines.append(f'     "{cap}…"')
    return '\n'.join(lines) if lines else '  (no data)'


def top5_tt(videos, sort_key='playCount'):
    sorted_v = sorted(videos, key=lambda v: v.get(sort_key, 0) or 0, reverse=True)[:5]
    lines = []
    for i, v in enumerate(sorted_v, 1):
        url  = f"https://www.tiktok.com/@{v.get('authorMeta',{}).get('name','?')}/video/{v.get('id','?')}"
        pl   = v.get('playCount', 0) or 0
        lk   = v.get('diggCount', 0) or 0
        cm   = v.get('commentCount', 0) or 0
        sh   = v.get('shareCount', 0) or 0
        desc = (v.get('text') or '')[:60].replace('\n', ' ')
        lines.append(f'  {i}. {pl:,} plays | {lk:,} likes | {cm:,} cmt | {sh:,} shares')
        lines.append(f'     {url}')
        if desc:
            lines.append(f'     "{desc}…"')
    return '\n'.join(lines) if lines else '  (no data)'


# ---------------------------------------------------------------------------
# Assemble report text
# ---------------------------------------------------------------------------

li = stats['lazada_ig']
si = stats['shopee_ig']
lt = stats['lazada_tt']
st = stats['shopee_tt']


def safe(d, k, default=0):
    return d.get(k, default) if d else default


# head-to-head bars – TikTok
tt_play_bars  = hbar(safe(lt,'total_plays'), safe(st,'total_plays'))
tt_like_bars  = hbar(safe(lt,'total_likes'), safe(st,'total_likes'))
tt_cm_bars    = hbar(safe(lt,'total_comments'), safe(st,'total_comments'))
tt_sh_bars    = hbar(safe(lt,'total_shares'), safe(st,'total_shares'))
tt_er_bars    = hbar(int(safe(lt,'avg_er',0)*100), int(safe(st,'avg_er',0)*100))

# head-to-head bars – Instagram
ig_like_bars  = hbar(safe(li,'total_likes'), safe(si,'total_likes'))
ig_cm_bars    = hbar(safe(li,'total_comments'), safe(si,'total_comments'))
ig_er_bars    = hbar(int(safe(li,'avg_er',0)*100), int(safe(si,'avg_er',0)*100))

# content mix bars
lz_ig_mix = content_bar(safe(li,'video_count'), safe(li,'carousel_count'), safe(li,'image_count'))
sh_ig_mix = content_bar(safe(si,'video_count'), safe(si,'carousel_count'), safe(si,'image_count'))

# executive summary
tt_winner  = 'Lazada SG' if safe(lt,'total_plays') >= safe(st,'total_plays') else 'Shopee SG'
ig_er_win  = 'Lazada SG' if safe(li,'avg_er',0) >= safe(si,'avg_er',0) else 'Shopee SG'
lz_ig_lk   = safe(li,'avg_likes')
sh_ig_lk   = safe(si,'avg_likes')
lk_gap     = abs(lz_ig_lk - sh_ig_lk)
lk_leader  = 'Lazada SG' if lz_ig_lk >= sh_ig_lk else 'Shopee SG'
lk_trailer = 'Shopee SG' if lz_ig_lk >= sh_ig_lk else 'Lazada SG'

exec_summary = (
    f"TikTok reach is dominated by {tt_winner}, recording "
    f"{safe(lt,'total_plays'):,} total plays vs "
    f"{safe(st,'total_plays'):,} for the competitor "
    f"(avg ER {safe(lt,'avg_er')}% vs {safe(st,'avg_er')}%). "
    f"On Instagram, {ig_er_win} leads engagement rate at "
    f"{max(safe(li,'avg_er',0), safe(si,'avg_er',0))}% avg ER. "
    f"{lk_leader} outpaces {lk_trailer} on Instagram likes by "
    f"{lk_gap:,} avg likes per post — closing this gap should be "
    f"a priority through more Reel content and community activations."
)

report = f"""╔══════════════════════════════════════════════════════════════╗
║   COMPETITOR SOCIAL MEDIA REPORT — {DATE_STR:>14}        ║
║   Lazada SG  vs  Shopee SG                                  ║
╚══════════════════════════════════════════════════════════════╝

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EXECUTIVE SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{exec_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TIKTOK HEAD-TO-HEAD  (n={safe(lt,'count')} Lazada / {safe(st,'count')} Shopee videos)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Metric            Lazada SG              Shopee SG
─────────────────────────────────────────────────────────────
Total Plays       {tt_play_bars[0]}  {tt_play_bars[1]}
                  {safe(lt,'total_plays'):>20,}   {safe(st,'total_plays'):>20,}

Total Likes       {tt_like_bars[0]}  {tt_like_bars[1]}
                  {safe(lt,'total_likes'):>20,}   {safe(st,'total_likes'):>20,}

Total Comments    {tt_cm_bars[0]}  {tt_cm_bars[1]}
                  {safe(lt,'total_comments'):>20,}   {safe(st,'total_comments'):>20,}

Total Shares      {tt_sh_bars[0]}  {tt_sh_bars[1]}
                  {safe(lt,'total_shares'):>20,}   {safe(st,'total_shares'):>20,}

Avg ER %          {tt_er_bars[0]}  {tt_er_bars[1]}
                  {safe(lt,'avg_er'):>19.2f}%   {safe(st,'avg_er'):>19.2f}%

Avg Plays/video   {safe(lt,'avg_plays'):>20,}   {safe(st,'avg_plays'):>20,}
Avg Likes/video   {safe(lt,'avg_likes'):>20,}   {safe(st,'avg_likes'):>20,}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INSTAGRAM HEAD-TO-HEAD  (n={safe(li,'count')} Lazada / {safe(si,'count')} Shopee posts)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Metric            Lazada SG              Shopee SG
─────────────────────────────────────────────────────────────
Total Likes       {ig_like_bars[0]}  {ig_like_bars[1]}
                  {safe(li,'total_likes'):>20,}   {safe(si,'total_likes'):>20,}

Total Comments    {ig_cm_bars[0]}  {ig_cm_bars[1]}
                  {safe(li,'total_comments'):>20,}   {safe(si,'total_comments'):>20,}

Avg ER %          {ig_er_bars[0]}  {ig_er_bars[1]}
                  {safe(li,'avg_er'):>19.2f}%   {safe(si,'avg_er'):>19.2f}%

Avg Likes/post    {safe(li,'avg_likes'):>20,}   {safe(si,'avg_likes'):>20,}
Avg Comments/post {safe(li,'avg_comments'):>20,}   {safe(si,'avg_comments'):>20,}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INSTAGRAM CONTENT MIX  (V=Video  C=Carousel  I=Image)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Lazada SG [{lz_ig_mix}]  V:{safe(li,'video_count')}  C:{safe(li,'carousel_count')}  I:{safe(li,'image_count')}
Shopee SG [{sh_ig_mix}]  V:{safe(si,'video_count')}  C:{safe(si,'carousel_count')}  I:{safe(si,'image_count')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TOP 5 TIKTOK VIDEOS — LAZADA SG  (by plays)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{top5_tt(raw.get('lazada_tt', []))}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TOP 5 TIKTOK VIDEOS — SHOPEE SG  (by plays)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{top5_tt(raw.get('shopee_tt', []))}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TOP 5 INSTAGRAM POSTS — LAZADA SG  (by likes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{top5_ig(raw.get('lazada_ig', []))}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  TOP 5 INSTAGRAM POSTS — SHOPEE SG  (by likes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{top5_ig(raw.get('shopee_ig', []))}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  RAW STATS DUMP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{json.dumps(stats, indent=2)}

Generated {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
"""

# ---------------------------------------------------------------------------
# Write outputs
# ---------------------------------------------------------------------------

with open('report_output.txt', 'w') as f:
    f.write(report)

with open('apify_results.json', 'w') as f:
    json.dump({'stats': stats, 'raw_item_counts': {k: len(v) for k, v in raw.items()}}, f, indent=2)

print(report)
print('\n[DONE] report_output.txt and apify_results.json written.', file=sys.stderr)
