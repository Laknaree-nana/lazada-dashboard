#!/usr/bin/env python3
"""
Lazada SG Competitor Social Media Report Pipeline
Supports: Instagram (Wave 1) → TikTok (Wave 2) → stats → charts → summary
"""

import os, sys, time, json, math, textwrap
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    sys.exit("Missing: pip install requests")

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
API_KEY = os.environ.get("APIFY_API_KEY", "")
BASE    = "https://api.apify.com/v2"

# Apify actor IDs (standard public actors)
IG_ACTOR  = "shu8hvrXbJbY3Eb9W"   # apify/instagram-scraper
TT_ACTOR  = "clockworks~tiktok-scraper"

BRANDS = {
    "Lazada": {
        "instagram": "Lazada_SG",
        "tiktok":    "lazadasg",
    },
    "Shopee": {
        "instagram": "shopee_SG",
        "tiktok":    "shopeesg",
    },
}

RESULTS_LIMIT = 50   # posts per scrape

# ──────────────────────────────────────────────
# Apify helpers
# ──────────────────────────────────────────────

def _headers():
    return {"Authorization": f"Bearer {API_KEY}"}

def start_run(actor_id: str, input_payload: dict) -> str:
    """Start an actor run and return runId."""
    url = f"{BASE}/acts/{actor_id}/runs"
    r = requests.post(url, json=input_payload, headers=_headers(), timeout=30)
    r.raise_for_status()
    run_id = r.json()["data"]["id"]
    print(f"  ▶ Started {actor_id}  run={run_id}")
    return run_id

def poll_run(actor_id: str, run_id: str, label: str = "", timeout: int = 600) -> dict:
    """Block until run status is SUCCEEDED (or raises on failure/timeout)."""
    deadline = time.time() + timeout
    interval  = 10
    url = f"{BASE}/acts/{actor_id}/runs/{run_id}"
    while True:
        r = requests.get(url, headers=_headers(), timeout=20)
        r.raise_for_status()
        data   = r.json()["data"]
        status = data["status"]
        print(f"  ⏳ {label or run_id}  status={status}")
        if status == "SUCCEEDED":
            return data
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            raise RuntimeError(f"Run {run_id} ended with {status}")
        if time.time() > deadline:
            raise TimeoutError(f"Run {run_id} timed out after {timeout}s")
        time.sleep(interval)
        interval = min(interval * 1.5, 60)

def fetch_dataset(dataset_id: str) -> list[dict]:
    """Download all items from a dataset."""
    url  = f"{BASE}/datasets/{dataset_id}/items"
    params = {"clean": "true", "limit": 1000}
    r = requests.get(url, params=params, headers=_headers(), timeout=60)
    r.raise_for_status()
    items = r.json()
    print(f"  📥 Dataset {dataset_id}: {len(items)} items")
    return items

# ──────────────────────────────────────────────
# Wave launchers
# ──────────────────────────────────────────────

def launch_instagram_scrapers() -> dict[str, str]:
    """Start IG scrapers for both brands in parallel; return {brand: run_id}."""
    print("\n═══ Wave 1 — Instagram ═══")
    jobs: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {}
        for brand, cfg in BRANDS.items():
            handle = cfg["instagram"]
            payload = {
                "usernames":    [handle],
                "resultsType":  "posts",
                "resultsLimit": RESULTS_LIMIT,
            }
            futures[ex.submit(start_run, IG_ACTOR, payload)] = brand
        for f in as_completed(futures):
            brand = futures[f]
            jobs[brand] = f.result()
    return jobs

def poll_instagram_scrapers(jobs: dict[str, str]) -> dict[str, dict]:
    """Poll both IG runs in parallel; return {brand: run_data}."""
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(poll_run, IG_ACTOR, run_id, f"IG-{brand}"): brand
            for brand, run_id in jobs.items()
        }
        for f in as_completed(futures):
            brand = futures[f]
            results[brand] = f.result()
    return results

def launch_tiktok_scrapers() -> dict[str, str]:
    """Start TikTok scrapers for both brands in parallel; return {brand: run_id}."""
    print("\n═══ Wave 2 — TikTok ═══")
    jobs: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {}
        for brand, cfg in BRANDS.items():
            handle = cfg["tiktok"]
            payload = {
                "profiles":        [f"https://www.tiktok.com/@{handle}"],
                "resultsPerPage":  RESULTS_LIMIT,
                "shouldDownloadVideos": False,
                "shouldDownloadCovers": False,
            }
            futures[ex.submit(start_run, TT_ACTOR, payload)] = brand
        for f in as_completed(futures):
            brand = futures[f]
            jobs[brand] = f.result()
    return jobs

def poll_tiktok_scrapers(jobs: dict[str, str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(poll_run, TT_ACTOR, run_id, f"TT-{brand}"): brand
            for brand, run_id in jobs.items()
        }
        for f in as_completed(futures):
            brand = futures[f]
            results[brand] = f.result()
    return results

# ──────────────────────────────────────────────
# Stats computation
# ──────────────────────────────────────────────

def _safe_int(v) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0

def compute_ig_stats(items: list[dict]) -> dict:
    posts  = [i for i in items if i.get("type") not in ("Story",)]
    likes  = [_safe_int(p.get("likesCount")) for p in posts]
    comms  = [_safe_int(p.get("commentsCount")) for p in posts]
    total_l = sum(likes)
    total_c = sum(comms)
    n       = len(posts)

    follower = _safe_int(posts[0].get("ownerFollowersCount") if posts else 0)
    er_list  = []
    if follower:
        for p in posts:
            eng = _safe_int(p.get("likesCount")) + _safe_int(p.get("commentsCount"))
            er_list.append(eng / follower * 100)

    content_types = {}
    for p in posts:
        t = p.get("type", "Unknown")
        content_types[t] = content_types.get(t, 0) + 1

    top5 = sorted(
        posts,
        key=lambda p: _safe_int(p.get("likesCount")) + _safe_int(p.get("commentsCount")),
        reverse=True
    )[:5]

    return {
        "platform":       "Instagram",
        "video_count":    n,
        "total_likes":    total_l,
        "total_comments": total_c,
        "avg_likes":      round(total_l / n, 1) if n else 0,
        "avg_comments":   round(total_c / n, 1) if n else 0,
        "avg_er_pct":     round(sum(er_list) / len(er_list), 2) if er_list else 0,
        "content_types":  content_types,
        "top5":           top5,
        "follower_count": follower,
    }

def compute_tt_stats(items: list[dict]) -> dict:
    plays   = [_safe_int(i.get("playCount") or i.get("stats",{}).get("playCount")) for i in items]
    likes   = [_safe_int(i.get("diggCount") or i.get("stats",{}).get("diggCount")) for i in items]
    comms   = [_safe_int(i.get("commentCount") or i.get("stats",{}).get("commentCount")) for i in items]
    shares  = [_safe_int(i.get("shareCount") or i.get("stats",{}).get("shareCount")) for i in items]
    n       = len(items)

    follower = _safe_int(
        (items[0].get("authorMeta", {}) or {}).get("fans") if items else 0
    )
    er_list = []
    if follower:
        for l, c, s in zip(likes, comms, shares):
            er_list.append((l + c + s) / follower * 100)

    top5 = sorted(
        items,
        key=lambda i: _safe_int(i.get("playCount") or (i.get("stats",{}) or {}).get("playCount")),
        reverse=True
    )[:5]

    return {
        "platform":       "TikTok",
        "video_count":    n,
        "total_plays":    sum(plays),
        "total_likes":    sum(likes),
        "total_comments": sum(comms),
        "total_shares":   sum(shares),
        "avg_plays":      round(sum(plays) / n, 1) if n else 0,
        "avg_likes":      round(sum(likes) / n, 1) if n else 0,
        "avg_comments":   round(sum(comms) / n, 1) if n else 0,
        "avg_shares":     round(sum(shares) / n, 1) if n else 0,
        "avg_er_pct":     round(sum(er_list) / len(er_list), 2) if er_list else 0,
        "top5":           top5,
        "follower_count": follower,
    }

# ──────────────────────────────────────────────
# Chart helpers
# ──────────────────────────────────────────────
BAR_W   = 40
MIX_W   = 14

def _bar(value: float, max_val: float, width: int = BAR_W) -> str:
    if max_val == 0:
        return "░" * width
    filled = round(value / max_val * width)
    return "█" * filled + "░" * (width - filled)

def _fmt_num(n: float) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n))

def head_to_head(metric_label: str, laz_val: float, shp_val: float) -> str:
    mx = max(laz_val, shp_val, 1)
    l1 = f"  Lazada  {_bar(laz_val, mx):40s} {_fmt_num(laz_val)}"
    l2 = f"  Shopee  {_bar(shp_val, mx):40s} {_fmt_num(shp_val)}"
    return f"  {metric_label}\n{l1}\n{l2}"

def content_mix_bar(types: dict[str, int]) -> str:
    total = sum(types.values()) or 1
    lines = []
    for t, cnt in sorted(types.items(), key=lambda x: -x[1]):
        pct = cnt / total * 100
        bar = _bar(pct, 100, MIX_W)
        lines.append(f"    {t:<12s} {bar} {pct:.0f}%")
    return "\n".join(lines)

def top5_posts_ig(posts: list[dict], brand: str) -> str:
    lines = [f"  ── Top 5 Instagram posts ({brand}) ──"]
    for i, p in enumerate(posts, 1):
        url   = p.get("url") or p.get("shortCode") or "(no url)"
        likes = _fmt_num(_safe_int(p.get("likesCount")))
        comms = _fmt_num(_safe_int(p.get("commentsCount")))
        ts    = str(p.get("timestamp",""))[:10]
        lines.append(f"  {i}. ❤ {likes}  💬 {comms}  📅 {ts}  {url}")
    return "\n".join(lines)

def top5_posts_tt(posts: list[dict], brand: str) -> str:
    lines = [f"  ── Top 5 TikTok posts ({brand}) ──"]
    for i, p in enumerate(posts, 1):
        url    = p.get("webVideoUrl") or p.get("id") or "(no url)"
        plays  = _fmt_num(_safe_int(p.get("playCount") or (p.get("stats",{}) or {}).get("playCount")))
        likes  = _fmt_num(_safe_int(p.get("diggCount") or (p.get("stats",{}) or {}).get("diggCount")))
        ts     = str(p.get("createTimeISO","") or p.get("createTime",""))[:10]
        lines.append(f"  {i}. ▶ {plays}  ❤ {likes}  📅 {ts}  {url}")
    return "\n".join(lines)

# ──────────────────────────────────────────────
# Report builder
# ──────────────────────────────────────────────

def build_report(stats: dict) -> str:
    today = datetime.utcnow()
    title = f"Competitor Social Report — {today.strftime('%d %b %Y')}"

    ig_l = stats["Lazada"]["instagram"]
    ig_s = stats["Shopee"]["instagram"]
    tt_l = stats["Lazada"]["tiktok"]
    tt_s = stats["Shopee"]["tiktok"]

    # ─── Executive summary ───
    tt_reach_l = tt_l["total_plays"]
    tt_reach_s = tt_s["total_plays"]
    tt_winner  = "Lazada" if tt_reach_l > tt_reach_s else "Shopee"
    tt_loser   = "Shopee" if tt_winner == "Lazada" else "Lazada"
    tt_lead_pct = abs(tt_reach_l - tt_reach_s) / max(tt_reach_s, tt_reach_l, 1) * 100

    ig_er_l = ig_l["avg_er_pct"]
    ig_er_s = ig_s["avg_er_pct"]
    ig_er_winner = "Lazada" if ig_er_l > ig_er_s else "Shopee"

    ig_likes_l = ig_l["total_likes"]
    ig_likes_s = ig_s["total_likes"]
    ig_likes_gap = abs(ig_likes_l - ig_likes_s)
    ig_likes_lagger = "Lazada" if ig_likes_l < ig_likes_s else "Shopee"

    exec_summary = (
        f"On TikTok, {tt_winner} commands a {tt_lead_pct:.0f}% larger total reach "
        f"({_fmt_num(max(tt_reach_l, tt_reach_s))} plays) versus "
        f"{tt_loser} ({_fmt_num(min(tt_reach_l, tt_reach_s))} plays), "
        f"driven primarily by higher average play counts per video. "
        f"On Instagram, {ig_er_winner} wins the engagement-rate battle "
        f"({max(ig_er_l, ig_er_s):.2f}% avg ER vs {min(ig_er_l, ig_er_s):.2f}%), "
        f"signalling stronger audience interaction despite follower base differences. "
        f"The Instagram likes gap of {_fmt_num(ig_likes_gap)} is a key opportunity: "
        f"{ig_likes_lagger} should increase Reels frequency and interactive story content "
        f"to close the deficit and recapture feed-algorithm priority."
    )

    # ─── Assemble sections ───
    sep  = "─" * 68
    sep2 = "═" * 68

    lines = [
        sep2, f"  {title}", sep2, "",
        "  EXECUTIVE SUMMARY", sep,
        textwrap.fill(exec_summary, width=68, initial_indent="  ", subsequent_indent="  "),
        "",
        sep2, "  INSTAGRAM — HEAD-TO-HEAD", sep2, "",
        head_to_head("Total Likes",    ig_l["total_likes"],    ig_s["total_likes"]),    "",
        head_to_head("Total Comments", ig_l["total_comments"], ig_s["total_comments"]), "",
        head_to_head("Avg ER %",       ig_l["avg_er_pct"],     ig_s["avg_er_pct"]),     "",
        head_to_head("Post Count",     ig_l["video_count"],    ig_s["video_count"]),     "",
        sep2, "  TIKTOK — HEAD-TO-HEAD", sep2, "",
        head_to_head("Total Plays",    tt_l["total_plays"],    tt_s["total_plays"]),    "",
        head_to_head("Total Likes",    tt_l["total_likes"],    tt_s["total_likes"]),    "",
        head_to_head("Total Shares",   tt_l["total_shares"],   tt_s["total_shares"]),   "",
        head_to_head("Avg ER %",       tt_l["avg_er_pct"],     tt_s["avg_er_pct"]),     "",
        head_to_head("Video Count",    tt_l["video_count"],    tt_s["video_count"]),    "",
        sep2, "  CONTENT MIX — INSTAGRAM", sep2, "",
        "  Lazada",
        content_mix_bar(ig_l["content_types"]), "",
        "  Shopee",
        content_mix_bar(ig_s["content_types"]), "",
        sep2, "  TOP 5 POSTS", sep2, "",
        top5_posts_ig(ig_l["top5"], "Lazada"), "",
        top5_posts_ig(ig_s["top5"], "Shopee"), "",
        top5_posts_tt(tt_l["top5"], "Lazada"), "",
        top5_posts_tt(tt_s["top5"], "Shopee"), "",
        sep2,
        f"  Report generated: {today.strftime('%Y-%m-%d %H:%M UTC')}",
        sep2,
    ]

    return "\n".join(lines)

# ──────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────

def run_pipeline() -> tuple[str, str]:
    """Returns (title, report_text)."""

    if not API_KEY:
        sys.exit("ERROR: APIFY_API_KEY environment variable is not set.")

    # Wave 1 — Instagram
    ig_jobs  = launch_instagram_scrapers()
    ig_runs  = poll_instagram_scrapers(ig_jobs)

    # Wave 2 — TikTok
    tt_jobs  = launch_tiktok_scrapers()
    tt_runs  = poll_tiktok_scrapers(tt_jobs)

    # Fetch datasets
    print("\n═══ Fetching datasets ═══")
    raw: dict[str, dict[str, list]] = {"Lazada": {}, "Shopee": {}}
    for brand, run_data in ig_runs.items():
        ds_id = run_data["defaultDatasetId"]
        raw[brand]["instagram"] = fetch_dataset(ds_id)
    for brand, run_data in tt_runs.items():
        ds_id = run_data["defaultDatasetId"]
        raw[brand]["tiktok"] = fetch_dataset(ds_id)

    # Compute stats
    print("\n═══ Computing stats ═══")
    stats = {
        brand: {
            "instagram": compute_ig_stats(raw[brand]["instagram"]),
            "tiktok":    compute_tt_stats(raw[brand]["tiktok"]),
        }
        for brand in BRANDS
    }

    today = datetime.utcnow()
    title  = f"Competitor Social Report — {today.strftime('%d %b %Y')}"
    report = build_report(stats)
    return title, report


if __name__ == "__main__":
    title, report = run_pipeline()
    print("\n" + report)

    # Persist locally
    out_path = f"/home/user/lazada-dashboard/report_{datetime.utcnow().strftime('%Y%m%d')}.txt"
    with open(out_path, "w") as fh:
        fh.write(report)
    print(f"\n✅ Report saved to {out_path}")
