"""
Full competitor social media pipeline.
Wave 1: Instagram scrapers (parallel)
Wave 2: TikTok scrapers (parallel, after Wave 1 done)
Then: fetch datasets, compute stats, print JSON
"""
import urllib.request, json, time, sys, os, threading

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
    r = apify_post(f'acts/{actor}/runs', body)
    rid = r['data']['id']
    print(f'[START] {label} -> run={rid}', file=sys.stderr, flush=True)
    return rid


def poll_until_done(rid, label, out, key, max_tries=48, interval=15):
    """Poll actor run until terminal status. Writes final run data to out[key]."""
    for i in range(max_tries):
        try:
            d = apify_get(f'actor-runs/{rid}')['data']
            s = d['status']
            print(f'[POLL] {label} #{i+1}: {s}', file=sys.stderr, flush=True)
            if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                out[key] = d
                return
        except Exception as e:
            print(f'[POLL] {label} err: {e}', file=sys.stderr, flush=True)
        time.sleep(interval)
    out[key] = {'status': 'TIMEOUT', 'defaultDatasetId': ''}


def fetch_items(dataset_id):
    if not dataset_id:
        return []
    try:
        data = apify_get(f'datasets/{dataset_id}/items?limit=50')
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and 'data' in data:
            items = data['data']
            if isinstance(items, dict) and 'items' in items:
                return items['items']
            return items
        return []
    except Exception as e:
        print(f'[ERROR] fetch dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


# ── Wave 1: Instagram ──────────────────────────────────────────────────────────
print('\n=== WAVE 1: Instagram scrapers ===', file=sys.stderr, flush=True)

IG_CONFIGS = {
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
for key, (actor, body) in IG_CONFIGS.items():
    ig_run_ids[key] = start_run(actor, body, key)

ig_finals = {}
ig_threads = [
    threading.Thread(target=poll_until_done, args=(rid, key, ig_finals, key))
    for key, rid in ig_run_ids.items()
]
for t in ig_threads:
    t.start()
for t in ig_threads:
    t.join()

print(f'[WAVE1 DONE] lazada_ig={ig_finals["lazada_ig"]["status"]}  '
      f'shopee_ig={ig_finals["shopee_ig"]["status"]}', file=sys.stderr, flush=True)

# ── Wave 2: TikTok ─────────────────────────────────────────────────────────────
print('\n=== WAVE 2: TikTok scrapers ===', file=sys.stderr, flush=True)

TT_CONFIGS = {
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
for key, (actor, body) in TT_CONFIGS.items():
    tt_run_ids[key] = start_run(actor, body, key)

tt_finals = {}
tt_threads = [
    threading.Thread(target=poll_until_done, args=(rid, key, tt_finals, key))
    for key, rid in tt_run_ids.items()
]
for t in tt_threads:
    t.start()
for t in tt_threads:
    t.join()

print(f'[WAVE2 DONE] lazada_tt={tt_finals["lazada_tt"]["status"]}  '
      f'shopee_tt={tt_finals["shopee_tt"]["status"]}', file=sys.stderr, flush=True)

# ── Fetch all datasets ─────────────────────────────────────────────────────────
print('\n=== Fetching datasets ===', file=sys.stderr, flush=True)

all_finals = {**ig_finals, **tt_finals}
all_data = {}
for key, final in all_finals.items():
    items = fetch_items(final.get('defaultDatasetId', ''))
    all_data[key] = items
    print(f'[FETCH] {key}: {len(items)} items', file=sys.stderr, flush=True)

# Write raw data to file for inspection
with open('/home/user/lazada-dashboard/apify_results.json', 'w') as f:
    json.dump(all_data, f, indent=2)

print('\n[PIPELINE COMPLETE] Results saved to apify_results.json', file=sys.stderr, flush=True)
print(json.dumps({'status': 'ok', 'counts': {k: len(v) for k, v in all_data.items()}}))
