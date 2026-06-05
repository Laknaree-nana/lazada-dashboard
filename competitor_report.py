#!/usr/bin/env python3
"""
Lazada Singapore — Daily Competitor Social Media Report
Runs Apify scrapers for Lazada SG & Shopee SG (Instagram + TikTok),
computes engagement metrics, builds ASCII bar charts, and uploads
the finished report to Google Drive as a Google Doc.

Requirements:
    pip install requests google-auth google-auth-oauthlib google-api-python-client

Usage:
    export APIFY_API_KEY="apify_api_..."
    export GOOGLE_SERVICE_ACCOUNT_JSON="/path/to/sa.json"   # OR use OAuth (see below)
    python3 competitor_report.py
"""

import os
import sys
import json
import time
import math
import statistics
import datetime
import requests

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────
APIFY_KEY = os.environ.get("APIFY_API_KEY")
if not APIFY_KEY:
    sys.exit("ERROR: Set the APIFY_API_KEY environment variable before running this script.")
APIFY_BASE = "https://api.apify.com/v2"
HEADERS = {"Authorization": f"Bearer {APIFY_KEY}", "Content-Type": "application/json"}

ACTORS = {
    "lazada_ig":  ("apify~instagram-scraper",
                   {"directUrls": ["https://www.instagram.com/Lazada_SG/"],
                    "resultsType": "posts", "resultsLimit": 15, "addParentData": False}),
    "shopee_ig":  ("apify~instagram-scraper",
                   {"directUrls": ["https://www.instagram.com/shopee_SG/"],
                    "resultsType": "posts", "resultsLimit": 15, "addParentData": False}),
    "lazada_tt":  ("clockworks~free-tiktok-scraper",
                   {"profiles": ["Lazada_SG"], "resultsPerPage": 15,
                    "shouldDownloadVideos": False, "shouldDownloadCovers": False}),
    "shopee_tt":  ("clockworks~free-tiktok-scraper",
                   {"profiles": ["shopeesg"], "resultsPerPage": 15,
                    "shouldDownloadVideos": False, "shouldDownloadCovers": False}),
}

POLL_INTERVAL = 10          # seconds between status polls
MAX_WAIT      = 4 * 60      # 4 minutes max per run
BAR_WIDE      = 40          # character width for main bar charts
BAR_MIX       = 14          # character width for content-mix bar


# ──────────────────────────────────────────────────────────────
# APIFY HELPERS
# ──────────────────────────────────────────────────────────────

def start_run(actor_id: str, body: dict) -> dict:
    url = f"{APIFY_BASE}/acts/{actor_id}/runs"
    r = requests.post(url, headers=HEADERS, json=body, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def poll_run(run_id: str) -> dict:
    """Block until run finishes (SUCCEEDED/FAILED/ABORTED/TIMED-OUT). Returns final run data."""
    deadline = time.time() + MAX_WAIT
    terminal = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
    while True:
        r = requests.get(f"{APIFY_BASE}/actor-runs/{run_id}", headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()["data"]
        status = data["status"]
        print(f"  [{run_id[:8]}] status={status}", flush=True)
        if status in terminal:
            return data
        if time.time() > deadline:
            raise TimeoutError(f"Run {run_id} did not finish in {MAX_WAIT}s")
        time.sleep(POLL_INTERVAL)


def fetch_dataset(dataset_id: str) -> list:
    url = f"{APIFY_BASE}/datasets/{dataset_id}/items?limit=50"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


# ──────────────────────────────────────────────────────────────
# DATA COLLECTION
# ──────────────────────────────────────────────────────────────

def collect_all() -> dict:
    """Start all 4 runs in parallel, then poll and fetch each."""
    print("Starting Apify runs …")
    runs = {}
    for key, (actor_id, body) in ACTORS.items():
        print(f"  Launching {key} …")
        run = start_run(actor_id, body)
        runs[key] = {"run_id": run["id"], "dataset_id": run["defaultDatasetId"]}
        print(f"    run_id={run['id']}")

    print("\nPolling runs …")
    results = {}
    for key, meta in runs.items():
        print(f"  Polling {key} …")
        final = poll_run(meta["run_id"])
        if final["status"] != "SUCCEEDED":
            print(f"  WARNING: {key} ended with status {final['status']}")
            results[key] = []
        else:
            ds_id = final["defaultDatasetId"]
            items = fetch_dataset(ds_id)
            print(f"    fetched {len(items)} items")
            results[key] = items

    return results


# ──────────────────────────────────────────────────────────────
# METRICS
# ──────────────────────────────────────────────────────────────

def fmt(n: float) -> str:
    """Format number: >1M → 2.1M, >1K → 2.1K, else integer."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n))


def parse_ig_posts(items: list) -> list:
    posts = []
    for p in items:
        if "error" in p:
            continue
        media_type = (p.get("type") or "").lower()
        likes    = int(p.get("likesCount")     or 0)
        comments = int(p.get("commentsCount")  or 0)
        plays    = int(p.get("videoViewCount") or 0)
        shares   = 0
        er = (likes + comments + shares) / plays if plays > 0 else 0
        is_video = any(v in media_type for v in ("video", "reel"))
        posts.append({
            "url":        p.get("url") or p.get("shortCode") or "",
            "caption":    (p.get("caption") or "")[:120],
            "likes":      likes,
            "comments":   comments,
            "plays":      plays,
            "shares":     shares,
            "er":         er,
            "is_video":   is_video,
            "media_type": media_type,
        })
    return posts


def parse_tt_posts(items: list) -> list:
    posts = []
    for p in items:
        if "error" in p:
            continue
        likes    = int(p.get("diggCount")    or 0)
        comments = int(p.get("commentCount") or 0)
        shares   = int(p.get("shareCount")   or 0)
        plays    = int(p.get("playCount")    or 0)
        er = (likes + comments + shares) / plays if plays > 0 else 0
        posts.append({
            "url":      p.get("webVideoUrl") or p.get("id") or "",
            "caption":  (p.get("desc") or "")[:120],
            "likes":    likes,
            "comments": comments,
            "plays":    plays,
            "shares":   shares,
            "er":       er,
            "is_video": True,
        })
    return posts


def compute_stats(posts: list, platform: str) -> dict:
    if not posts:
        return {"post_count": 0, "total_likes": 0, "total_comments": 0,
                "total_shares": 0, "total_plays": 0, "avg_er_pct": 0.0,
                "video_count": 0, "top5": []}
    total_likes    = sum(p["likes"]    for p in posts)
    total_comments = sum(p["comments"] for p in posts)
    total_shares   = sum(p["shares"]   for p in posts)
    total_plays    = sum(p["plays"]    for p in posts)
    avg_er_pct     = statistics.mean(p["er"] for p in posts) * 100
    video_count    = sum(1 for p in posts if p["is_video"])

    sort_key = "likes" if platform == "ig" else "plays"
    top5 = sorted(posts, key=lambda p: p[sort_key], reverse=True)[:5]

    return {
        "post_count":    len(posts),
        "total_likes":   total_likes,
        "total_comments":total_comments,
        "total_shares":  total_shares,
        "total_plays":   total_plays,
        "avg_er_pct":    round(avg_er_pct, 4),
        "video_count":   video_count,
        "top5":          top5,
    }


# ──────────────────────────────────────────────────────────────
# BAR CHARTS
# ──────────────────────────────────────────────────────────────

def bar(value: float, max_val: float, width: int) -> str:
    if max_val == 0:
        filled = 0
    else:
        filled = round((value / max_val) * width)
    filled = max(0, min(filled, width))
    return "█" * filled + "░" * (width - filled)


def head_to_head(label: str, laz_val: float, shp_val: float, width: int = BAR_WIDE) -> str:
    max_v = max(laz_val, shp_val, 1)
    lines = [
        f"  {label}",
        f"  Lazada  [{bar(laz_val, max_v, width)}] {fmt(laz_val)}",
        f"  Shopee  [{bar(shp_val, max_v, width)}] {fmt(shp_val)}",
    ]
    return "\n".join(lines)


def content_mix_bar(video_count: int, total: int, width: int = BAR_MIX) -> str:
    if total == 0:
        return "[" + "░" * width + "] 0 posts"
    filled = round((video_count / total) * width)
    filled = max(0, min(filled, width))
    non_video = total - video_count
    return f"[{'█' * filled}{'░' * (width - filled)}] {video_count}v/{non_video}s"


# ──────────────────────────────────────────────────────────────
# EXECUTIVE SUMMARY
# ──────────────────────────────────────────────────────────────

def executive_summary(laz_ig, shp_ig, laz_tt, shp_tt) -> str:
    # Sentence 1 — TikTok reach
    laz_tt_plays = laz_tt["total_plays"]
    shp_tt_plays = shp_tt["total_plays"]
    laz_tt_likes = laz_tt["total_likes"]
    shp_tt_likes = shp_tt["total_likes"]

    if shp_tt_plays > 0 and laz_tt_plays > 0:
        ratio = max(shp_tt_plays, laz_tt_plays) / max(min(shp_tt_plays, laz_tt_plays), 1)
        leader_tt = "Shopee" if shp_tt_plays > laz_tt_plays else "Lazada"
        trailer_tt = "Lazada" if leader_tt == "Shopee" else "Shopee"
        s1 = (f"On TikTok, {leader_tt} dominates reach with {fmt(max(laz_tt_plays, shp_tt_plays))} total plays "
              f"vs {fmt(min(laz_tt_plays, shp_tt_plays))} for {trailer_tt} ({ratio:.1f}× advantage), "
              f"with {leader_tt} also leading on likes ({fmt(max(laz_tt_likes, shp_tt_likes))}).")
    else:
        s1 = "TikTok reach data was unavailable for one or both brands this period."

    # Sentence 2 — Instagram ER
    laz_er = laz_ig["avg_er_pct"]
    shp_er = shp_ig["avg_er_pct"]
    er_winner = "Lazada" if laz_er >= shp_er else "Shopee"
    er_loser  = "Shopee" if er_winner == "Lazada" else "Lazada"
    laz_vc = laz_ig["video_count"]
    shp_vc = shp_ig["video_count"]
    higher_vc_brand = "Lazada" if laz_vc >= shp_vc else "Shopee"
    s2 = (f"On Instagram, {er_winner} wins average engagement rate "
          f"({laz_er:.2f}% vs {shp_er:.2f}%), "
          f"which may partly reflect {higher_vc_brand}'s higher Reels/video count "
          f"({laz_vc} vs {shp_vc} video posts).")

    # Sentence 3 — Instagram likes gap & recommendation
    laz_ig_likes = laz_ig["total_likes"]
    shp_ig_likes = shp_ig["total_likes"]
    max_ig = max(laz_ig_likes, shp_ig_likes, 1)
    gap_pct = abs(laz_ig_likes - shp_ig_likes) / max_ig * 100

    if laz_ig_likes >= shp_ig_likes:
        if gap_pct < 15:
            s3 = (f"The Instagram likes gap is tight ({gap_pct:.1f}%), "
                  "suggesting Lazada should shift more content budget to Reels to widen the lead before Shopee catches up.")
        else:
            s3 = (f"Lazada leads Instagram likes by {gap_pct:.1f}% — "
                  "sustaining this advantage calls for widening the Reels pipeline to consolidate reach leadership.")
    else:
        s3 = (f"Shopee leads Lazada on Instagram likes by {gap_pct:.1f}% — "
              "Lazada should urgently accelerate Reels production and posting frequency to close the gap.")

    return f"{s1}\n\n{s2}\n\n{s3}"


# ──────────────────────────────────────────────────────────────
# REPORT BUILDER
# ──────────────────────────────────────────────────────────────

def top_posts_block(posts: list, platform: str, brand: str) -> str:
    sort_key = "likes" if platform == "ig" else "plays"
    metric_label = "Likes" if platform == "ig" else "Plays"
    lines = [f"  Top 5 {brand} {platform.upper()} posts by {metric_label}:"]
    for i, p in enumerate(posts, 1):
        cap = p["caption"][:80].replace("\n", " ")
        lines.append(f"  {i}. {metric_label}: {fmt(p[sort_key])} | "
                     f"Comments: {fmt(p['comments'])} | "
                     f"{'Plays: ' + fmt(p['plays']) + ' | ' if platform == 'ig' and p['plays'] else ''}"
                     f"URL: {p['url']}")
        lines.append(f"     Caption: {cap}…" if len(p["caption"]) > 80 else f"     Caption: {cap}")
    return "\n".join(lines)


def build_report(raw: dict, today: str) -> str:
    laz_ig_posts = parse_ig_posts(raw.get("lazada_ig", []))
    shp_ig_posts = parse_ig_posts(raw.get("shopee_ig", []))
    laz_tt_posts = parse_tt_posts(raw.get("lazada_tt", []))
    shp_tt_posts = parse_tt_posts(raw.get("shopee_tt", []))

    laz_ig = compute_stats(laz_ig_posts, "ig")
    shp_ig = compute_stats(shp_ig_posts, "ig")
    laz_tt = compute_stats(laz_tt_posts, "tt")
    shp_tt = compute_stats(shp_tt_posts, "tt")

    sep = "=" * 60
    thin = "-" * 60

    lines = []

    # ── HEADER ──
    lines += [
        sep,
        f"  COMPETITOR SOCIAL MEDIA REPORT — {today}",
        f"  Lazada Singapore vs Shopee Singapore",
        sep,
        "",
    ]

    # ── EXECUTIVE SUMMARY ──
    lines += [
        "EXECUTIVE SUMMARY",
        thin,
        executive_summary(laz_ig, shp_ig, laz_tt, shp_tt),
        "",
    ]

    # ── HEAD-TO-HEAD CHARTS ──
    lines += [
        "HEAD-TO-HEAD PERFORMANCE CHARTS",
        thin,
        "",
        head_to_head("TikTok Total Plays", laz_tt["total_plays"], shp_tt["total_plays"]),
        "",
        head_to_head("TikTok Total Likes", laz_tt["total_likes"], shp_tt["total_likes"]),
        "",
        head_to_head("Instagram Total Likes", laz_ig["total_likes"], shp_ig["total_likes"]),
        "",
        head_to_head("Instagram Total Plays (Video Views)", laz_ig["total_plays"], shp_ig["total_plays"]),
        "",
        head_to_head("Instagram Avg ER %  (×100 for scale)",
                     laz_ig["avg_er_pct"] * 100, shp_ig["avg_er_pct"] * 100),
        "",
    ]

    # ── CONTENT MIX ──
    lines += [
        "INSTAGRAM CONTENT MIX  (Video/Reel vs Static)",
        thin,
        f"  Lazada  {content_mix_bar(laz_ig['video_count'], laz_ig['post_count'])}  "
        f"({laz_ig['video_count']}/{laz_ig['post_count']} posts are video)",
        f"  Shopee  {content_mix_bar(shp_ig['video_count'], shp_ig['post_count'])}  "
        f"({shp_ig['video_count']}/{shp_ig['post_count']} posts are video)",
        "",
    ]

    # ── TIKTOK DEEP DIVE ──
    lines += [
        "TIKTOK DEEP DIVE",
        thin,
        "",
        "  LAZADA SG (@Lazada_SG)",
        f"    Posts scraped : {laz_tt['post_count']}",
        f"    Total Plays   : {fmt(laz_tt['total_plays'])}",
        f"    Total Likes   : {fmt(laz_tt['total_likes'])}",
        f"    Total Comments: {fmt(laz_tt['total_comments'])}",
        f"    Total Shares  : {fmt(laz_tt['total_shares'])}",
        f"    Avg ER        : {laz_tt['avg_er_pct']:.2f}%",
        "",
        top_posts_block(laz_tt["top5"], "tt", "Lazada"),
        "",
        "  SHOPEE SG (@shopeesg)",
        f"    Posts scraped : {shp_tt['post_count']}",
        f"    Total Plays   : {fmt(shp_tt['total_plays'])}",
        f"    Total Likes   : {fmt(shp_tt['total_likes'])}",
        f"    Total Comments: {fmt(shp_tt['total_comments'])}",
        f"    Total Shares  : {fmt(shp_tt['total_shares'])}",
        f"    Avg ER        : {shp_tt['avg_er_pct']:.2f}%",
        "",
        top_posts_block(shp_tt["top5"], "tt", "Shopee"),
        "",
    ]

    # ── INSTAGRAM DEEP DIVE ──
    lines += [
        "INSTAGRAM DEEP DIVE",
        thin,
        "",
        "  LAZADA SG (@Lazada_SG)",
        f"    Posts scraped : {laz_ig['post_count']}",
        f"    Total Likes   : {fmt(laz_ig['total_likes'])}",
        f"    Total Comments: {fmt(laz_ig['total_comments'])}",
        f"    Total Plays   : {fmt(laz_ig['total_plays'])}",
        f"    Video Posts   : {laz_ig['video_count']} / {laz_ig['post_count']}",
        f"    Avg ER        : {laz_ig['avg_er_pct']:.2f}%",
        "",
        top_posts_block(laz_ig["top5"], "ig", "Lazada"),
        "",
        "  SHOPEE SG (@shopee_SG)",
        f"    Posts scraped : {shp_ig['post_count']}",
        f"    Total Likes   : {fmt(shp_ig['total_likes'])}",
        f"    Total Comments: {fmt(shp_ig['total_comments'])}",
        f"    Total Plays   : {fmt(shp_ig['total_plays'])}",
        f"    Video Posts   : {shp_ig['video_count']} / {shp_ig['post_count']}",
        f"    Avg ER        : {shp_ig['avg_er_pct']:.2f}%",
        "",
        top_posts_block(shp_ig["top5"], "ig", "Shopee"),
        "",
    ]

    # ── KEY ACTIONS ──
    laz_tt_plays = laz_tt["total_plays"]
    shp_tt_plays = shp_tt["total_plays"]
    tt_leader    = "Shopee" if shp_tt_plays > laz_tt_plays else "Lazada"
    ig_er_leader = "Shopee" if shp_ig["avg_er_pct"] > laz_ig["avg_er_pct"] else "Lazada"

    action_tt = (
        f"  1. TikTok Volume — {'Shopee outpaces Lazada on TikTok plays. Increase posting cadence to 5-7/week and experiment with trending audio hooks.' if tt_leader == 'Shopee' else 'Lazada leads on TikTok plays. Maintain cadence and A/B test longer-form product storytelling (60-90 s) to deepen engagement.'}"
    )
    action_reels = (
        "  2. Instagram Reels — Shift ≥60% of Instagram content budget to Reels; "
        "short-form video (15-30 s) consistently drives higher reach and ER on the platform."
    )
    action_er = (
        f"  3. Engagement Rate — {'Shopee leads IG ER; audit their comment-reply pattern and CTA placement, then replicate tactics on Lazada content.' if ig_er_leader == 'Shopee' else 'Lazada leads IG ER; replicate winning content formats across all upcoming campaign tentpoles.'}"
    )
    action_cadence = (
        "  4. Posting Cadence & Timing — Benchmark top-performing post timestamps from this dataset "
        "and schedule future posts within ±1 h of proven peak windows to maximise organic reach."
    )

    lines += [
        "KEY ACTIONS FOR LAZADA SG",
        thin,
        "",
        action_tt,
        action_reels,
        action_er,
        action_cadence,
        "",
        sep,
        f"  Report generated: {today}  |  Data source: Apify (Instagram Scraper + TikTok Scraper)",
        sep,
    ]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# GOOGLE DRIVE UPLOAD
# ──────────────────────────────────────────────────────────────

def upload_to_drive(title: str, content: str) -> str:
    """
    Upload report as a Google Doc via the Drive API (service-account auth).
    Returns the shareable web link.

    Set GOOGLE_SERVICE_ACCOUNT_JSON env var to the path of your service-account key file.
    Alternatively, run `gcloud auth application-default login` before executing this script.
    """
    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account
        from google.auth import default as google_auth_default
        from googleapiclient.http import MediaInMemoryUpload

        sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if sa_path:
            creds = service_account.Credentials.from_service_account_file(
                sa_path, scopes=["https://www.googleapis.com/auth/drive.file"])
        else:
            creds, _ = google_auth_default(scopes=["https://www.googleapis.com/auth/drive.file"])

        service = build("drive", "v3", credentials=creds)

        file_metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document",
        }
        media = MediaInMemoryUpload(
            content.encode("utf-8"),
            mimetype="text/plain",
            resumable=False,
        )
        f = service.files().create(
            body=file_metadata, media_body=media, fields="id,webViewLink"
        ).execute()

        file_id   = f.get("id")
        view_link = f.get("webViewLink")

        # Make it readable by anyone with the link
        service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"},
        ).execute()

        return view_link

    except Exception as e:
        print(f"  WARNING: Google Drive upload failed — {e}")
        print("  Report saved locally as report_output.txt instead.")
        with open("report_output.txt", "w") as fh:
            fh.write(content)
        return "(saved locally: report_output.txt)"


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

def main():
    today = datetime.date.today().strftime("%d %b %Y")
    print(f"\n{'='*60}")
    print(f"  Lazada Competitor Social Report — {today}")
    print(f"{'='*60}\n")

    raw = collect_all()

    print("\nBuilding report …")
    report = build_report(raw, today)

    print("\nUploading to Google Drive …")
    title = f"Competitor Social Report — {today}"
    link = upload_to_drive(title, report)

    print("\n" + "="*60)
    print(f"  DONE — Google Drive link:")
    print(f"  {link}")
    print("="*60 + "\n")

    # Also print the full report to stdout
    print(report)


if __name__ == "__main__":
    main()
