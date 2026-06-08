import urllib.request, json, time, sys, os

API_KEY = os.environ.get('APIFY_API_KEY', '')
if not API_KEY:
    print('[ERROR] APIFY_API_KEY environment variable not set', file=sys.stderr)
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


def start_run(actor, body):
    try:
        r = apify_post(f'acts/{actor}/runs', body)
        rid = r['data']['id']
        print(f'[START] {actor} -> {rid}', file=sys.stderr, flush=True)
        return rid
    except Exception as e:
        print(f'[ERROR] start {actor}: {e}', file=sys.stderr, flush=True)
        return None


def poll_run(rid, label):
    last = {'defaultDatasetId': '', 'status': 'TIMEOUT'}
    for i in range(24):
        try:
            d = apify_get(f'actor-runs/{rid}')['data']
            last = d
            s = d['status']
            print(f'[POLL] {label} #{i+1}: {s}', file=sys.stderr, flush=True)
            if s in ('SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'):
                return d
        except Exception as e:
            print(f'[POLL] {label} error: {e}', file=sys.stderr, flush=True)
        time.sleep(10)
    return last


def fetch_items(dataset_id):
    if not dataset_id:
        return []
    try:
        return apify_get(f'datasets/{dataset_id}/items?limit=50')
    except Exception as e:
        print(f'[ERROR] dataset {dataset_id}: {e}', file=sys.stderr, flush=True)
        return []


RUNS = [
    ('lazada_ig', 'apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/Lazada_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
    ('shopee_ig', 'apify~instagram-scraper', {
        'directUrls': ['https://www.instagram.com/shopee_SG/'],
        'resultsType': 'posts', 'resultsLimit': 15, 'addParentData': False,
    }),
    ('lazada_tt', 'clockworks~free-tiktok-scraper', {
        'profiles': ['Lazada_SG'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
    ('shopee_tt', 'clockworks~free-tiktok-scraper', {
        'profiles': ['shopeesg'], 'resultsPerPage': 15,
        'shouldDownloadVideos': False, 'shouldDownloadCovers': False,
    }),
]

ids = {n: start_run(a, b) for n, a, b in RUNS}

results = {}
for name, actor, body in RUNS:
    rid = ids.get(name)
    if not rid:
        results[name] = []
        continue
    final = poll_run(rid, name)
    items = fetch_items(final.get('defaultDatasetId', ''))
    results[name] = items
    print(f'[DONE] {name}: {len(items)} items', file=sys.stderr, flush=True)

print(json.dumps(results))
