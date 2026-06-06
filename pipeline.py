#!/usr/bin/env python3
"""
Lazada Singapore Competitor Social Media Report Pipeline
Scrapes Instagram & TikTok for Lazada_SG and Shopee_SG, builds report, uploads to Google Drive.
"""

import os, sys, time, json, math, datetime, statistics, textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request, urllib.parse, urllib.error

APIFY_API_KEY = os.environ.get("APIFY_API_KEY", "")
BASE_URL = "https://api.apify.com/v2"

# ---------------------------------------------------------------------------
# Apify helpers
# ---------------------------------------------------------------------------

def apify_post(path: str, payload: dict) -> dict:
    url = f"{BASE_URL}/{path}?token={APIFY_API_KEY}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def apify_get(path: str) -> dict:
    url = f"{BASE_URL}/{path}?token={APIFY_API_KEY}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def start_instagram_scraper(username: str) -> str:
    """Start apify/instagram-scraper for a username, return run ID."""
    resp = apify_post(
        "acts/apify~instagram-scraper/runs",
        {
            "usernames": [username],
            "resultsType": "posts",
            "resultsLimit": 30,
            "addParentData": False,
        },
    )
    run_id = resp["data"]["id"]
    print(f"  [IG] Started run for @{username}: {run_id}")
    return run_id


def start_tiktok_scraper(username: str) -> str:
    """Start clockworks/tiktok-scraper for a username, return run ID."""
    resp = apify_post(
        "acts/clockworks~tiktok-scraper/runs",
        {
            "profiles": [username],
            "resultsPerPage": 30,
            "shouldDownloadVideos": False,
            "shouldDownloadCovers": False,
        },
    )
    run_id = resp["data"]["id"]
    print(f"  [TT] Started run for @{username}: {run_id}")
    return run_id


def poll_until_done(run_id: str, label: str, timeout_s: int = 600) -> str:
    """Poll run status until SUCCEEDED; return default dataset ID."""
    deadline = time.time() + timeout_s
    delay = 10
    while time.time() < deadline:
        info = apify_get(f"actor-runs/{run_id}")
        status = info["data"]["status"]
        print(f"    [{label}] run {run_id[:8]}… status={status}")
        if status == "SUCCEEDED":
            return info["data"]["defaultDatasetId"]
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Run {run_id} ended with status={status}")
        time.sleep(delay)
        delay = min(delay * 1.5, 60)
    raise TimeoutError(f"Run {run_id} did not finish within {timeout_s}s")


def fetch_dataset(dataset_id: str) -> list:
    url = f"{BASE_URL}/datasets/{dataset_id}/items?token={APIFY_API_KEY}&clean=true&format=json"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def ig_stats(posts: list, brand: str) -> dict:
    likes = [p.get("likesCount", 0) or 0 for p in posts]
    comments = [p.get("commentsCount", 0) or 0 for 0 in posts]
    comments = [p.get("commentsCount", 0) or 0 for p in posts]
    followers = posts[0].get("ownerFollowersCount", 0) if posts else 1
    followers = max(followers or 1, 1)
    er_list = [((l + c) / followers) * 100 for l, c in zip(likes, comments)]
    top5 = sorted(
        posts, key=lambda p: (p.get("likesCount", 0) or 0) + (p.get("commentsCount", 0) or 0), reverse=True
    )[:5]
    return {
        "brand": brand,
        "platform": "Instagram",
        "video_count": len(posts),
        "total_likes": sum(likes),
        "total_comments": sum(comments),
        "total_plays": 0,
        "total_shares": 0,
        "avg_er_pct": round(statistics.mean(er_list), 3) if er_list else 0,
        "followers": followers,
        "top5": top5,
    }


def tt_stats(posts: list, brand: str) -> dict:
    likes = [p.get("diggCount", 0) or 0 for p in posts]
    comments = [p.get("commentCount", 0) or 0 for p in posts]
    plays = [p.get("playCount", 0) or 0 for p in posts]
    shares = [p.get("shareCount", 0) or 0 for p in posts]
    followers = posts[0].get("authorMeta", {}).get("fans", 0) if posts else 1
    followers = max(followers or 1, 1)
    er_list = [((l + c + s) / followers) * 100 for l, c, s in zip(likes, comments, shares)]
    top5 = sorted(posts, key=lambda p: p.get("playCount", 0) or 0, reverse=True)[:5]
    return {
        "brand": brand,
        "platform": "TikTok",
        "video_count": len(posts),
        "total_likes": sum(likes),
        "total_comments": sum(comments),
        "total_plays": sum(plays),
        "total_shares": sum(shares),
        "avg_er_pct": round(statistics.mean(er_list), 3) if er_list else 0,
        "followers": followers,
        "top5": top5,
    }


# ---------------------------------------------------------------------------
# Chart helpers (text-only)
# ---------------------------------------------------------------------------

BAR_FULL = "█"
BAR_EMPTY = "░"


def bar_chart(val_a: float, val_b: float, width: int = 40) -> tuple[str, str]:
    """Return two filled-bar strings for a head-to-head comparison."""
    total = val_a + val_b
    if total == 0:
        return BAR_EMPTY * width, BAR_EMPTY * width
    fill_a = round((val_a / total) * width)
    fill_b = round((val_b / total) * width)
    return BAR_FULL * fill_a + BAR_EMPTY * (width - fill_a), BAR_FULL * fill_b + BAR_EMPTY * (width - fill_b)


def content_mix_bar(video_count: int, total_count: int, width: int = 14) -> str:
    if total_count == 0:
        return BAR_EMPTY * width
    fill = round((video_count / total_count) * width)
    return BAR_FULL * fill + BAR_EMPTY * (width - fill)


def fmt_num(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(stats: dict) -> str:
    today = datetime.date.today().strftime("%d %b %Y")
    lines = [
        f"Competitor Social Media Report — {today}",
        "=" * 60,
        "",
    ]

    platforms = ["Instagram", "TikTok"]
    brands = ["Lazada_SG", "Shopee_SG"]

    # ── Head-to-head bar charts ──────────────────────────────────────────
    lines += ["HEAD-TO-HEAD COMPARISON", "-" * 60]
    for plat in platforms:
        lines.append(f"\n{plat}")
        laz = stats.get(("Lazada_SG", plat), {})
        sho = stats.get(("Shopee_SG", plat), {})

        metrics = [
            ("Likes", "total_likes"),
            ("Comments", "total_comments"),
        ]
        if plat == "TikTok":
            metrics += [("Plays", "total_plays"), ("Shares", "total_shares")]

        for label, key in metrics:
            va = laz.get(key, 0)
            vb = sho.get(key, 0)
            ba, bb = bar_chart(va, vb, 40)
            lines.append(f"  {label:<10} Lazada  {ba}  {fmt_num(va)}")
            lines.append(f"  {' ':<10} Shopee  {bb}  {fmt_num(vb)}")

        lines.append(f"  {'Avg ER%':<10} Lazada  {laz.get('avg_er_pct',0):.3f}%   Shopee  {sho.get('avg_er_pct',0):.3f}%")

    # ── Content mix ─────────────────────────────────────────────────────
    lines += ["", "CONTENT MIX (video posts out of 30 scraped)", "-" * 60]
    for plat in platforms:
        lines.append(f"\n{plat}")
        for brand in brands:
            s = stats.get((brand, plat), {})
            vc = s.get("video_count", 0)
            bar = content_mix_bar(vc, 30, 14)
            lines.append(f"  {brand:<12}  {bar}  {vc}/30 posts")

    # ── Top 5 posts ──────────────────────────────────────────────────────
    lines += ["", "TOP 5 POSTS PER BRAND PER PLATFORM", "-" * 60]
    for plat in platforms:
        for brand in brands:
            lines.append(f"\n{brand} — {plat} (ranked by {'plays' if plat=='TikTok' else 'likes+comments'})")
            s = stats.get((brand, plat), {})
            for i, p in enumerate(s.get("top5", []), 1):
                if plat == "Instagram":
                    url = p.get("url", p.get("shortCode", "n/a"))
                    lk = fmt_num(p.get("likesCount", 0) or 0)
                    cm = fmt_num(p.get("commentsCount", 0) or 0)
                    caption = (p.get("caption", "") or "")[:80].replace("\n", " ")
                    lines.append(f"  {i}. Likes {lk}  Comments {cm}")
                    lines.append(f"     {url}")
                    lines.append(f"     {caption}")
                else:
                    url = f"https://tiktok.com/@{p.get('authorMeta',{}).get('name','?')}/video/{p.get('id','?')}"
                    pl = fmt_num(p.get("playCount", 0) or 0)
                    lk = fmt_num(p.get("diggCount", 0) or 0)
                    sh = fmt_num(p.get("shareCount", 0) or 0)
                    desc = (p.get("text", "") or "")[:80].replace("\n", " ")
                    lines.append(f"  {i}. Plays {pl}  Likes {lk}  Shares {sh}")
                    lines.append(f"     {url}")
                    lines.append(f"     {desc}")

    # ── Stats summary table ──────────────────────────────────────────────
    lines += ["", "STATS SUMMARY", "-" * 60]
    lines.append(f"{'Brand':<14} {'Platform':<12} {'Posts':<7} {'Likes':<10} {'Comments':<10} {'Plays':<10} {'Shares':<10} {'Avg ER%'}")
    for plat in platforms:
        for brand in brands:
            s = stats.get((brand, plat), {})
            lines.append(
                f"{brand:<14} {plat:<12} {s.get('video_count',0):<7} "
                f"{fmt_num(s.get('total_likes',0)):<10} {fmt_num(s.get('total_comments',0)):<10} "
                f"{fmt_num(s.get('total_plays',0)):<10} {fmt_num(s.get('total_shares',0)):<10} "
                f"{s.get('avg_er_pct',0):.3f}%"
            )

    # ── Executive summary ────────────────────────────────────────────────
    laz_tt = stats.get(("Lazada_SG", "TikTok"), {})
    sho_tt = stats.get(("Shopee_SG", "TikTok"), {})
    laz_ig = stats.get(("Lazada_SG", "Instagram"), {})
    sho_ig = stats.get(("Shopee_SG", "Instagram"), {})

    tt_reach_winner = "Lazada_SG" if laz_tt.get("total_plays", 0) >= sho_tt.get("total_plays", 0) else "Shopee_SG"
    tt_reach_delta = abs(laz_tt.get("total_plays", 0) - sho_tt.get("total_plays", 0))

    ig_er_winner = "Lazada_SG" if laz_ig.get("avg_er_pct", 0) >= sho_ig.get("avg_er_pct", 0) else "Shopee_SG"
    ig_er_loser  = "Shopee_SG" if ig_er_winner == "Lazada_SG" else "Lazada_SG"

    ig_likes_gap = sho_ig.get("total_likes", 0) - laz_ig.get("total_likes", 0)
    ig_likes_direction = "behind" if ig_likes_gap > 0 else "ahead of"
    ig_likes_gap_abs = abs(ig_likes_gap)

    exec_summary = (
        f"On TikTok, {tt_reach_winner} leads on total video reach with {fmt_num(tt_reach_delta)} more plays across the 30 most-recent posts. "
        f"On Instagram, {ig_er_winner} wins engagement rate, outperforming {ig_er_loser} by "
        f"{abs(laz_ig.get('avg_er_pct',0) - sho_ig.get('avg_er_pct',0)):.3f} percentage points. "
        f"Lazada_SG is {fmt_num(ig_likes_gap_abs)} likes {ig_likes_direction} Shopee_SG on Instagram — "
        f"closing this gap should be a near-term priority, with a recommended focus on reels and carousel posts to boost organic reach."
    )

    lines += [
        "",
        "EXECUTIVE SUMMARY",
        "-" * 60,
        "",
        textwrap.fill(exec_summary, width=78),
        "",
        "=" * 60,
        f"Report generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    if not APIFY_API_KEY:
        print("ERROR: APIFY_API_KEY environment variable is not set.")
        sys.exit(1)

    print("\n=== WAVE 1: Instagram scrapers ===")
    with ThreadPoolExecutor(max_workers=2) as ex:
        ig_futures = {
            ex.submit(start_instagram_scraper, "lazada_sg"): "Lazada_SG",
            ex.submit(start_instagram_scraper, "shopee_sg"): "Shopee_SG",
        }
        ig_run_ids = {}
        for fut in as_completed(ig_futures):
            brand = ig_futures[fut]
            ig_run_ids[brand] = fut.result()

    print("\n  Polling Instagram runs…")
    ig_dataset_ids = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        poll_futures = {
            ex.submit(poll_until_done, ig_run_ids[b], f"IG/{b}"): b
            for b in ig_run_ids
        }
        for fut in as_completed(poll_futures):
            brand = poll_futures[fut]
            ig_dataset_ids[brand] = fut.result()
            print(f"  [IG] {brand} dataset: {ig_dataset_ids[brand]}")

    print("\n=== WAVE 2: TikTok scrapers ===")
    tt_usernames = {"Lazada_SG": "lazadasg", "Shopee_SG": "shopeesg"}
    with ThreadPoolExecutor(max_workers=2) as ex:
        tt_futures = {
            ex.submit(start_tiktok_scraper, tt_usernames[b]): b
            for b in ["Lazada_SG", "Shopee_SG"]
        }
        tt_run_ids = {}
        for fut in as_completed(tt_futures):
            brand = tt_futures[fut]
            tt_run_ids[brand] = fut.result()

    print("\n  Polling TikTok runs…")
    tt_dataset_ids = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        poll_futures = {
            ex.submit(poll_until_done, tt_run_ids[b], f"TT/{b}"): b
            for b in tt_run_ids
        }
        for fut in as_completed(poll_futures):
            brand = poll_futures[fut]
            tt_dataset_ids[brand] = fut.result()
            print(f"  [TT] {brand} dataset: {tt_dataset_ids[brand]}")

    print("\n=== Fetching datasets ===")
    ig_data, tt_data = {}, {}
    for brand in ["Lazada_SG", "Shopee_SG"]:
        print(f"  Fetching IG {brand}…")
        ig_data[brand] = fetch_dataset(ig_dataset_ids[brand])
        print(f"  Fetching TT {brand}…")
        tt_data[brand] = fetch_dataset(tt_dataset_ids[brand])

    print("\n=== Computing stats ===")
    stats = {}
    for brand in ["Lazada_SG", "Shopee_SG"]:
        stats[(brand, "Instagram")] = ig_stats(ig_data[brand], brand)
        stats[(brand, "TikTok")] = tt_stats(tt_data[brand], brand)

    for key, s in stats.items():
        print(f"  {key[0]} {key[1]}: {s['video_count']} posts, {fmt_num(s['total_likes'])} likes, ER {s['avg_er_pct']:.3f}%")

    print("\n=== Building report ===")
    report_text = build_report(stats)
    print(report_text)

    # Save locally
    report_path = f"/home/user/lazada-dashboard/report_{datetime.date.today().strftime('%Y%m%d')}.txt"
    with open(report_path, "w") as f:
        f.write(report_text)
    print(f"\nReport saved to {report_path}")

    return report_text, stats


if __name__ == "__main__":
    main()
