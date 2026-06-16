#!/usr/bin/env python3
"""Full Lazada SG competitor social media report pipeline.

Wave 1 → Instagram (Lazada_SG, shopee_SG) in parallel
Wave 2 → TikTok   (Lazada_SG, shopeesg)   in parallel
Then: fetch datasets → stats → ASCII charts → report_output.txt
"""

import urllib.request, json, time, sys, os
from datetime import datetime, timezone

TODAY = datetime.now(timezone.utc)
DATE_STR = TODAY.strftime('%d %b %Y')   # e.g. "16 Jun 2026"

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY not set', file=sys.stderr)
    sys.exit(1)


# ── Apify helpers ────────────────────────────────────────────────────

def apify_get(path):
    sep = '&' if '?' in path else '?'
    url = f'https://api.apify.com/v2/{path}{sep}token={API_KEY}'
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def apify_post(path, body):
    url = f'https://api.apify.com/v2/{path}?token={API_KEY}'
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def start_run(actor, body):
    try:
        r = apify_post(f'acts/{actor}/runs', body)
        rid = r['data']['id']
        print(f'[START] {actor} → {rid}', file=sys.stderr, flush=True)
        return rid
    except Exception as e:
        print(f'[ERROR] start {actor}: {e}', file=sys.stderr, flush=True)
        return None


def poll_runs(run_ids, max_iter=30, sleep_sec=10):
    """Poll {name: run_id} until all reach a terminal state.
    Returns {name: run_data_dict}."""
    pending = {k: v for k, v in run_ids.items() if v}
    done = {}
    for i in range(max_iter):
        if not pending:
            break
        still = {}
        for name, rid in pending.items():
            try:
                d = apify_get(f'actor-runs/{rid}')['data']
                s = d['status']
                print(f'[POLL] {name} iter={i+1}: {s}', file=sys.stderr, flush=True)
                if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                    done[name] = d
                else:
                    still[name] = rid
            except Exception as e:
                print(f'[POLL] {name} error: {e}', file=sys.stderr, flush=True)
                still[name] = rid
        pending = still
        if pending:
            time.sleep(sleep_sec)
    for name, rid in pending.items():
        done[name] = {'status': 'TIMEOUT', 'defaultDatasetId': ''}
    return done


def fetch_items(dataset_id, limit=50):
    if not dataset_id:
        return []
    try:
        d = apify_get(f'datasets/{dataset_id}/items?limit={limit}')
        return d if isinstance(d, list) else d.get('items', [])
    except Exception as e:
        print(f'[ERROR] fetch dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


# ── Wave 1: Instagram ────────────────────────────────────────────────

print('\n[WAVE 1] Launching Instagram scrapers (parallel)…', file=sys.stderr, flush=True)
ig_ids = {
    'lazada_ig': start_run('apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/Lazada_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
    'shopee_ig': start_run('apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/shopee_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
}
ig_done = poll_runs(ig_ids)
print('[WAVE 1] Instagram complete.\n', file=sys.stderr, flush=True)

# ── Wave 2: TikTok ───────────────────────────────────────────────────

print('[WAVE 2] Launching TikTok scrapers (parallel)…', file=sys.stderr, flush=True)
tt_ids = {
    'lazada_tt': start_run('clockworks~free-tiktok-scraper', {
        'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
    'shopee_tt': start_run('clockworks~free-tiktok-scraper', {
        'profiles': ['shopeesg'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
}
tt_done = poll_runs(tt_ids)
print('[WAVE 2] TikTok complete.\n', file=sys.stderr, flush=True)

# ── Fetch all datasets ────────────────────────────────────────────────

all_runs = {**ig_done, **tt_done}
raw = {}
for name, run_data in all_runs.items():
    did = run_data.get('defaultDatasetId', '')
    items = fetch_items(did)
    raw[name] = items
    print(f'[DATA] {name}: {len(items)} items  (status={run_data.get("status")})',
          file=sys.stderr, flush=True)

with open('apify_results.json', 'w') as f:
    json.dump(raw, f, indent=2)
print('[DATA] Saved → apify_results.json', file=sys.stderr, flush=True)


# ── Stats computation ─────────────────────────────────────────────────

def z(v):
    return v if isinstance(v, (int, float)) else 0


def _ig_followers(items):
    """Best-effort: look for follower count in any post field."""
    for p in items:
        for key in ('ownerFollowersCount', 'followersCount'):
            v = p.get(key)
            if isinstance(v, int) and v > 0:
                return v
        owner = p.get('owner') or p.get('ownerDetails') or {}
        if isinstance(owner, dict):
            for k in ('followersCount', 'edge_followed_by'):
                v = owner.get(k)
                if isinstance(v, int) and v > 0:
                    return v
                if isinstance(v, dict):
                    c = v.get('count')
                    if c and c > 0:
                        return c
    return None


def compute_ig(items):
    if not items:
        return {'count': 0, 'total_likes': 0, 'total_comments': 0,
                'total_plays': 0, 'total_shares': 0,
                'avg_likes': 0, 'avg_comments': 0, 'avg_er': None,
                'followers': None, 'video_count': 0, 'image_count': 0,
                'sidecar_count': 0}
    n = len(items)
    likes = sum(z(p.get('likesCount')) for p in items)
    comments = sum(z(p.get('commentsCount')) for p in items)
    plays = sum(z(p.get('videoPlayCount')) for p in items)
    videos = sum(1 for p in items
                 if (p.get('type') or '').lower() in ('video', 'reel'))
    sidecars = sum(1 for p in items
                   if (p.get('type') or '').lower() in ('sidecar', 'carousel'))
    images = n - videos - sidecars
    followers = _ig_followers(items)
    avg_er = ((likes + comments) / n / followers * 100
              if followers and followers > 0 else None)
    return {
        'count': n, 'total_likes': likes, 'total_comments': comments,
        'total_plays': plays, 'total_shares': 0,
        'avg_likes': likes / n, 'avg_comments': comments / n,
        'avg_er': avg_er, 'followers': followers,
        'video_count': videos, 'image_count': images, 'sidecar_count': sidecars,
    }


def compute_tt(items):
    if not items:
        return {'count': 0, 'total_likes': 0, 'total_comments': 0,
                'total_plays': 0, 'total_shares': 0,
                'avg_likes': 0, 'avg_comments': 0, 'avg_er': None,
                'followers': None, 'video_count': 0, 'image_count': 0}
    n = len(items)
    likes = sum(z(p.get('diggCount')) for p in items)
    comments = sum(z(p.get('commentCount')) for p in items)
    plays = sum(z(p.get('playCount')) for p in items)
    shares = sum(z(p.get('shareCount')) for p in items)
    followers = None
    for p in items:
        am = p.get('authorMeta') or {}
        f = am.get('fans') or am.get('followers')
        if isinstance(f, int) and f > 0:
            followers = f
            break
    avg_er = ((likes + comments + shares) / n / followers * 100
              if followers and followers > 0 else None)
    return {
        'count': n, 'total_likes': likes, 'total_comments': comments,
        'total_plays': plays, 'total_shares': shares,
        'avg_likes': likes / n, 'avg_comments': comments / n,
        'avg_er': avg_er, 'followers': followers,
        'video_count': n, 'image_count': 0,
    }


stats = {
    'lazada_ig': compute_ig(raw.get('lazada_ig', [])),
    'shopee_ig': compute_ig(raw.get('shopee_ig', [])),
    'lazada_tt': compute_tt(raw.get('lazada_tt', [])),
    'shopee_tt': compute_tt(raw.get('shopee_tt', [])),
}


# ── Charting helpers ──────────────────────────────────────────────────

def bar(value, max_val, width):
    if max_val <= 0:
        return '░' * width
    filled = min(round(value / max_val * width), width)
    return '█' * filled + '░' * (width - filled)


def fn(v):
    """Format a number compactly."""
    v = int(v)
    if v >= 1_000_000:
        return f'{v/1_000_000:.1f}M'
    if v >= 1_000:
        return f'{v/1_000:.1f}K'
    return str(v)


# ── Top-5 posts ───────────────────────────────────────────────────────

def top5_ig(items):
    if not items:
        return []
    scored = sorted(items,
                    key=lambda p: z(p.get('likesCount')) + z(p.get('commentsCount')),
                    reverse=True)
    out = []
    for p in scored[:5]:
        out.append({
            'type': (p.get('type') or 'Post').capitalize(),
            'likes': z(p.get('likesCount')),
            'comments': z(p.get('commentsCount')),
            'plays': z(p.get('videoPlayCount')),
            'url': p.get('url') or (
                f"https://www.instagram.com/p/{p['shortCode']}/"
                if p.get('shortCode') else ''),
            'caption': (p.get('caption') or '')[:80],
            'date': (p.get('timestamp') or '')[:10],
        })
    return out


def top5_tt(items):
    if not items:
        return []
    scored = sorted(items,
                    key=lambda p: z(p.get('diggCount')) + z(p.get('commentCount'))
                                  + z(p.get('shareCount')),
                    reverse=True)
    out = []
    for p in scored[:5]:
        ct = p.get('createTime')
        date_s = (datetime.utcfromtimestamp(ct).strftime('%Y-%m-%d')
                  if ct else '')
        am = p.get('authorMeta') or {}
        out.append({
            'likes': z(p.get('diggCount')),
            'comments': z(p.get('commentCount')),
            'plays': z(p.get('playCount')),
            'shares': z(p.get('shareCount')),
            'url': f"https://www.tiktok.com/@{am.get('name', '')}/video/{p.get('id', '')}",
            'caption': (p.get('desc') or '')[:80],
            'date': date_s,
        })
    return out


tops = {
    'lazada_ig': top5_ig(raw.get('lazada_ig', [])),
    'shopee_ig': top5_ig(raw.get('shopee_ig', [])),
    'lazada_tt': top5_tt(raw.get('lazada_tt', [])),
    'shopee_tt': top5_tt(raw.get('shopee_tt', [])),
}


# ── Build report ──────────────────────────────────────────────────────

lig = stats['lazada_ig']
sig = stats['shopee_ig']
ltt = stats['lazada_tt']
stt = stats['shopee_tt']

L = []   # report lines


def h(t=''):
    L.append(t)


h('╔══════════════════════════════════════════════════════════════════╗')
h(f'║   COMPETITOR SOCIAL REPORT — {DATE_STR:<35}║')
h('╚══════════════════════════════════════════════════════════════════╝')
h()


# ─ Instagram head-to-head ─────────────────────────────────────────────
h('━━━ INSTAGRAM HEAD-TO-HEAD ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
h()

def ig_row(label, lv, sv):
    mx = max(lv, sv, 1)
    h(f'  {label}')
    h(f'    Lazada  {fn(lv):>8}  [{bar(lv, mx, 40)}]')
    h(f'    Shopee  {fn(sv):>8}  [{bar(sv, mx, 40)}]')
    h()

ig_row('Posts analysed',    lig['count'],          sig['count'])
ig_row('Total likes',       lig['total_likes'],     sig['total_likes'])
ig_row('Total comments',    lig['total_comments'],  sig['total_comments'])
ig_row('Avg likes / post',  lig['avg_likes'],       sig['avg_likes'])
ig_row('Avg comments/post', lig['avg_comments'],    sig['avg_comments'])

# ER%
lig_er = lig.get('avg_er')
sig_er = sig.get('avg_er')
if lig_er is not None or sig_er is not None:
    lv = lig_er or 0
    sv = sig_er or 0
    mx = max(lv, sv, 0.001)
    h('  Avg ER %')
    h(f'    Lazada  {lv:>7.2f}%  [{bar(lv, mx, 40)}]')
    h(f'    Shopee  {sv:>7.2f}%  [{bar(sv, mx, 40)}]')
    h()
else:
    h('  Avg ER %: N/A — follower count not returned (addParentData=False).')
    h()


# Instagram content mix (14-char bars)
h('  Content mix (14-char bar):')
for brand, s in [('Lazada', lig), ('Shopee', sig)]:
    total = max(s['count'], 1)
    vc = s.get('video_count', 0)
    ic = s.get('image_count', 0)
    sc = s.get('sidecar_count', 0)
    h(f'    {brand}  Video    {vc:>2}  [{bar(vc, total, 14)}]  {vc/total*100:.0f}%')
    h(f'    {" "*6}  Image    {ic:>2}  [{bar(ic, total, 14)}]  {ic/total*100:.0f}%')
    if sc:
        h(f'    {" "*6}  Carousel {sc:>2}  [{bar(sc, total, 14)}]  {sc/total*100:.0f}%')
h()


# ─ TikTok head-to-head ───────────────────────────────────────────────
h('━━━ TIKTOK HEAD-TO-HEAD ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
h()

def tt_row(label, lv, sv):
    mx = max(lv, sv, 1)
    h(f'  {label}')
    h(f'    Lazada  {fn(lv):>8}  [{bar(lv, mx, 40)}]')
    h(f'    Shopee  {fn(sv):>8}  [{bar(sv, mx, 40)}]')
    h()

tt_row('Videos analysed',  ltt['count'],          stt['count'])
tt_row('Total views',       ltt['total_plays'],    stt['total_plays'])
tt_row('Total likes',       ltt['total_likes'],    stt['total_likes'])
tt_row('Total comments',    ltt['total_comments'], stt['total_comments'])
tt_row('Total shares',      ltt['total_shares'],   stt['total_shares'])
tt_row('Avg likes / video', ltt['avg_likes'],      stt['avg_likes'])

ltt_er = ltt.get('avg_er')
stt_er = stt.get('avg_er')
if ltt_er is not None or stt_er is not None:
    lv = ltt_er or 0
    sv = stt_er or 0
    mx = max(lv, sv, 0.001)
    h('  Avg ER %')
    h(f'    Lazada  {lv:>7.2f}%  [{bar(lv, mx, 40)}]')
    h(f'    Shopee  {sv:>7.2f}%  [{bar(sv, mx, 40)}]')
    h()
else:
    h('  Avg ER %: N/A — follower count not returned by TikTok scraper.')
    h()


# ─ Top-5 posts ───────────────────────────────────────────────────────
SECTIONS = [
    ('lazada_ig', 'Lazada SG', 'Instagram'),
    ('shopee_ig', 'Shopee SG', 'Instagram'),
    ('lazada_tt', 'Lazada SG', 'TikTok'),
    ('shopee_tt', 'Shopee SG', 'TikTok'),
]

for key, brand, platform in SECTIONS:
    h(f'━━━ TOP 5 POSTS — {brand} / {platform} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    posts = tops[key]
    if not posts:
        h('  (no data)')
        h()
        continue
    for i, p in enumerate(posts, 1):
        if platform == 'Instagram':
            h(f'  #{i}  {p["type"]:<9}  ♥ {fn(p["likes"]):<8}  '
              f'💬 {fn(p["comments"]):<7}  📅 {p["date"]}')
        else:
            h(f'  #{i}  ▶ {fn(p["plays"]):<9}  ♥ {fn(p["likes"]):<8}  '
              f'💬 {fn(p["comments"]):<6}  🔁 {fn(p["shares"]):<6}  📅 {p["date"]}')
        if p.get('caption'):
            cap = p['caption']
            h(f'       "{cap[:75]}{"…" if len(cap) > 75 else ""}"')
        if p.get('url'):
            h(f'       {p["url"]}')
        h()
    h()


# ─ Executive summary ─────────────────────────────────────────────────
h('━━━ EXECUTIVE SUMMARY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
h()

# 1. TikTok reach
ltt_v = ltt['total_plays']
stt_v = stt['total_plays']
if ltt_v + stt_v == 0:
    tt_sent = ('TikTok data was unavailable for both brands in this run; '
               'rerun the pipeline when Apify TikTok actor returns results.')
else:
    tt_leader = 'Lazada SG' if ltt_v >= stt_v else 'Shopee SG'
    tt_trailer = 'Shopee SG' if tt_leader == 'Lazada SG' else 'Lazada SG'
    tt_lead_v = max(ltt_v, stt_v)
    tt_lag_v = min(ltt_v, stt_v)
    ratio = tt_lead_v / max(tt_lag_v, 1)
    tt_sent = (f'{tt_leader} leads TikTok reach with {fn(tt_lead_v)} total views '
               f'across {ltt["count"] if tt_leader=="Lazada SG" else stt["count"]} videos, '
               f'outpacing {tt_trailer} by {fn(tt_lead_v - tt_lag_v)} views '
               f'({ratio:.1f}×) — indicating a significantly stronger video content strategy.')

# 2. Instagram ER winner
if lig_er is not None and sig_er is not None:
    er_winner = 'Lazada SG' if lig_er >= sig_er else 'Shopee SG'
    er_high = max(lig_er, sig_er)
    er_low = min(lig_er, sig_er)
    er_sent = (f'{er_winner} wins Instagram engagement rate at {er_high:.2f}% '
               f'vs {er_low:.2f}%, suggesting its content resonates more deeply '
               f'with followers relative to audience size.')
else:
    # Fall back to avg likes as ER proxy
    if lig['avg_likes'] + sig['avg_likes'] > 0:
        er_winner = 'Lazada SG' if lig['avg_likes'] >= sig['avg_likes'] else 'Shopee SG'
        er_high = max(lig['avg_likes'], sig['avg_likes'])
        er_low = min(lig['avg_likes'], sig['avg_likes'])
        er_sent = (f'{er_winner} leads Instagram on average likes per post '
                   f'({fn(er_high)} vs {fn(er_low)}), suggesting stronger audience '
                   f'resonance (ER% unavailable without follower data).')
    else:
        er_sent = 'Instagram ER data was unavailable for both brands in this run.'

# 3. Likes gap recommendation
l_likes = lig['total_likes']
s_likes = sig['total_likes']
gap = abs(l_likes - s_likes)
if gap == 0:
    rec_sent = ('Both brands are evenly matched on Instagram likes; '
                'focus A/B testing on Reel formats and caption hooks '
                'to find the next engagement growth lever.')
else:
    ig_leader = 'Lazada SG' if l_likes >= s_likes else 'Shopee SG'
    ig_trailer = 'Shopee SG' if ig_leader == 'Lazada SG' else 'Lazada SG'
    rec_sent = (f'To close the {fn(gap)}-like Instagram gap, {ig_trailer} should '
                f'increase Reel/video output (higher play → like conversion), '
                f'test campaign-led captions with CTAs, and aim for '
                f'≥1 Reel per day to compress the gap within 30 days.')

h(f'1. TikTok Reach: {tt_sent}')
h()
h(f'2. Instagram ER Winner: {er_sent}')
h()
h(f'3. Instagram Likes Gap Recommendation: {rec_sent}')
h()
h('─' * 68)
h(f'Generated: {TODAY.strftime("%Y-%m-%d %H:%M")} UTC  |  '
  f'Source: Apify (last 15 posts/videos per brand)')
h('Brands: Lazada_SG · shopee_SG (Instagram)   '
  'Lazada_SG · shopeesg (TikTok)')

report_text = '\n'.join(L)

with open('report_output.txt', 'w') as f:
    f.write(report_text)
print('\n[DONE] Report saved → report_output.txt', file=sys.stderr, flush=True)

# JSON summary to stdout for downstream consumption
print(json.dumps({
    'date': DATE_STR,
    'stats': stats,
    'tops': tops,
    'report_text': report_text,
}))
