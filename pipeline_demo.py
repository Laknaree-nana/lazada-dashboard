#!/usr/bin/env python3
"""
Demo run of the report pipeline using synthetic data.
Exercises steps 3-6 (stats, charts, top posts, Google Doc creation).
Replace with pipeline.py when APIFY_API_KEY is available.
"""

import datetime, statistics, textwrap, random

random.seed(42)

# ---------------------------------------------------------------------------
# Synthetic dataset generator
# ---------------------------------------------------------------------------

def make_ig_posts(seed_likes: int, seed_comments: int, followers: int, n: int = 28) -> list:
    rng = random.Random(seed_likes)
    posts = []
    for i in range(n):
        likes = max(0, int(rng.gauss(seed_likes, seed_likes * 0.3)))
        comments = max(0, int(rng.gauss(seed_comments, seed_comments * 0.4)))
        posts.append({
            "likesCount": likes,
            "commentsCount": comments,
            "ownerFollowersCount": followers,
            "url": f"https://www.instagram.com/p/demo{i:03d}/",
            "caption": f"Demo caption for post {i+1} — special offers and promotions inside!",
        })
    return posts


def make_tt_posts(seed_plays: int, seed_likes: int, seed_comments: int, seed_shares: int, fans: int, n: int = 28) -> list:
    rng = random.Random(seed_plays)
    posts = []
    for i in range(n):
        plays = max(0, int(rng.gauss(seed_plays, seed_plays * 0.4)))
        likes = max(0, int(rng.gauss(seed_likes, seed_likes * 0.3)))
        comments = max(0, int(rng.gauss(seed_comments, seed_comments * 0.4)))
        shares = max(0, int(rng.gauss(seed_shares, seed_shares * 0.5)))
        posts.append({
            "playCount": plays,
            "diggCount": likes,
            "commentCount": comments,
            "shareCount": shares,
            "authorMeta": {"fans": fans, "name": f"demouser{i%2}"},
            "id": f"demo{7000000+i}",
            "text": f"Demo TikTok caption {i+1} #lazada #shopee #sale #singapore",
        })
    return posts


DEMO_DATA = {
    ("Lazada_SG", "Instagram"): make_ig_posts(
        seed_likes=3200, seed_comments=85, followers=620_000),
    ("Shopee_SG", "Instagram"): make_ig_posts(
        seed_likes=8700, seed_comments=220, followers=1_450_000),
    ("Lazada_SG", "TikTok"): make_tt_posts(
        seed_plays=145_000, seed_likes=6200, seed_comments=310, seed_shares=820, fans=280_000),
    ("Shopee_SG", "TikTok"): make_tt_posts(
        seed_plays=390_000, seed_likes=15_000, seed_comments=780, seed_shares=2100, fans=890_000),
}

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def ig_stats(posts: list, brand: str) -> dict:
    likes = [p.get("likesCount", 0) or 0 for p in posts]
    comments = [p.get("commentsCount", 0) or 0 for p in posts]
    followers = posts[0].get("ownerFollowersCount", 1) if posts else 1
    followers = max(followers, 1)
    er_list = [((l + c) / followers) * 100 for l, c in zip(likes, comments)]
    top5 = sorted(posts, key=lambda p: (p.get("likesCount", 0) or 0) + (p.get("commentsCount", 0) or 0), reverse=True)[:5]
    return {
        "brand": brand, "platform": "Instagram",
        "video_count": len(posts),
        "total_likes": sum(likes), "total_comments": sum(comments),
        "total_plays": 0, "total_shares": 0,
        "avg_er_pct": round(statistics.mean(er_list), 3) if er_list else 0,
        "followers": followers, "top5": top5,
    }


def tt_stats(posts: list, brand: str) -> dict:
    likes = [p.get("diggCount", 0) or 0 for p in posts]
    comments = [p.get("commentCount", 0) or 0 for p in posts]
    plays = [p.get("playCount", 0) or 0 for p in posts]
    shares = [p.get("shareCount", 0) or 0 for p in posts]
    followers = posts[0].get("authorMeta", {}).get("fans", 1) if posts else 1
    followers = max(followers, 1)
    er_list = [((l + c + s) / followers) * 100 for l, c, s in zip(likes, comments, shares)]
    top5 = sorted(posts, key=lambda p: p.get("playCount", 0) or 0, reverse=True)[:5]
    return {
        "brand": brand, "platform": "TikTok",
        "video_count": len(posts),
        "total_likes": sum(likes), "total_comments": sum(comments),
        "total_plays": sum(plays), "total_shares": sum(shares),
        "avg_er_pct": round(statistics.mean(er_list), 3) if er_list else 0,
        "followers": followers, "top5": top5,
    }

# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

BAR_FULL, BAR_EMPTY = "█", "░"


def bar_chart(val_a: float, val_b: float, width: int = 40):
    total = val_a + val_b
    if total == 0:
        return BAR_EMPTY * width, BAR_EMPTY * width
    fill_a = round((val_a / total) * width)
    fill_b = round((val_b / total) * width)
    return BAR_FULL * fill_a + BAR_EMPTY * (width - fill_a), BAR_FULL * fill_b + BAR_EMPTY * (width - fill_b)


def content_mix_bar(count: int, total: int, width: int = 14) -> str:
    if total == 0:
        return BAR_EMPTY * width
    fill = round((count / total) * width)
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

def build_report(stats: dict, demo: bool = False) -> str:
    today = datetime.date.today().strftime("%d %b %Y")
    header_note = "  ⚠  DEMO DATA — re-run pipeline.py with APIFY_API_KEY for live figures\n" if demo else ""
    lines = [
        f"Competitor Social Report — {today}",
        "=" * 60,
        header_note,
    ]

    platforms = ["Instagram", "TikTok"]
    brands = ["Lazada_SG", "Shopee_SG"]

    # Head-to-head bar charts
    lines += ["HEAD-TO-HEAD COMPARISON", "-" * 60]
    for plat in platforms:
        lines.append(f"\n{plat}")
        laz = stats.get(("Lazada_SG", plat), {})
        sho = stats.get(("Shopee_SG", plat), {})
        metrics = [("Likes", "total_likes"), ("Comments", "total_comments")]
        if plat == "TikTok":
            metrics += [("Plays", "total_plays"), ("Shares", "total_shares")]
        for label, key in metrics:
            va, vb = laz.get(key, 0), sho.get(key, 0)
            ba, bb = bar_chart(va, vb, 40)
            lines.append(f"  {label:<10} Lazada   {ba}  {fmt_num(va)}")
            lines.append(f"  {' ':<10} Shopee   {bb}  {fmt_num(vb)}")
        lines.append(
            f"  {'Avg ER%':<10} Lazada  {laz.get('avg_er_pct',0):.3f}%   "
            f"Shopee  {sho.get('avg_er_pct',0):.3f}%"
        )

    # Content mix
    lines += ["", "CONTENT MIX  (posts scraped: 28)", "-" * 60]
    for plat in platforms:
        lines.append(f"\n{plat}  [14-char bar = proportion of 28 posts that are video/reels]")
        for brand in brands:
            s = stats.get((brand, plat), {})
            vc = s.get("video_count", 0)
            bar = content_mix_bar(vc, 28, 14)
            lines.append(f"  {brand:<14}  {bar}  {vc}/28")

    # Top 5 posts
    lines += ["", "TOP 5 POSTS PER BRAND PER PLATFORM", "-" * 60]
    for plat in platforms:
        for brand in brands:
            rank_by = "plays" if plat == "TikTok" else "likes + comments"
            lines.append(f"\n{brand} — {plat}  (ranked by {rank_by})")
            s = stats.get((brand, plat), {})
            for i, p in enumerate(s.get("top5", []), 1):
                if plat == "Instagram":
                    url  = p.get("url", "n/a")
                    lk   = fmt_num(p.get("likesCount", 0) or 0)
                    cm   = fmt_num(p.get("commentsCount", 0) or 0)
                    cap  = (p.get("caption", "") or "")[:80].replace("\n", " ")
                    lines += [f"  {i}. Likes {lk}  Comments {cm}", f"     {url}", f"     {cap}"]
                else:
                    uid  = p.get("authorMeta", {}).get("name", "?")
                    vid  = p.get("id", "?")
                    url  = f"https://tiktok.com/@{uid}/video/{vid}"
                    pl   = fmt_num(p.get("playCount", 0) or 0)
                    lk   = fmt_num(p.get("diggCount", 0) or 0)
                    sh   = fmt_num(p.get("shareCount", 0) or 0)
                    desc = (p.get("text", "") or "")[:80].replace("\n", " ")
                    lines += [f"  {i}. Plays {pl}  Likes {lk}  Shares {sh}", f"     {url}", f"     {desc}"]

    # Stats summary table
    lines += ["", "STATS SUMMARY", "-" * 60]
    lines.append(f"{'Brand':<14} {'Platform':<12} {'Posts':<7} {'Likes':<10} {'Comments':<10} {'Plays':<10} {'Shares':<10} {'Avg ER%'}")
    lines.append("-" * 80)
    for plat in platforms:
        for brand in brands:
            s = stats.get((brand, plat), {})
            lines.append(
                f"{brand:<14} {plat:<12} {s.get('video_count',0):<7} "
                f"{fmt_num(s.get('total_likes',0)):<10} {fmt_num(s.get('total_comments',0)):<10} "
                f"{fmt_num(s.get('total_plays',0)):<10} {fmt_num(s.get('total_shares',0)):<10} "
                f"{s.get('avg_er_pct',0):.3f}%"
            )

    # Executive summary
    laz_tt = stats.get(("Lazada_SG", "TikTok"), {})
    sho_tt = stats.get(("Shopee_SG", "TikTok"), {})
    laz_ig = stats.get(("Lazada_SG", "Instagram"), {})
    sho_ig = stats.get(("Shopee_SG", "Instagram"), {})

    laz_tt_plays = laz_tt.get("total_plays", 0)
    sho_tt_plays = sho_tt.get("total_plays", 0)
    tt_winner = "Lazada_SG" if laz_tt_plays >= sho_tt_plays else "Shopee_SG"
    tt_loser  = "Shopee_SG" if tt_winner == "Lazada_SG" else "Lazada_SG"
    tt_delta  = abs(laz_tt_plays - sho_tt_plays)

    laz_er = laz_ig.get("avg_er_pct", 0)
    sho_er = sho_ig.get("avg_er_pct", 0)
    ig_er_winner = "Lazada_SG" if laz_er >= sho_er else "Shopee_SG"
    ig_er_loser  = "Shopee_SG" if ig_er_winner == "Lazada_SG" else "Lazada_SG"
    ig_er_delta  = abs(laz_er - sho_er)

    laz_ig_likes = laz_ig.get("total_likes", 0)
    sho_ig_likes = sho_ig.get("total_likes", 0)
    ig_likes_gap = sho_ig_likes - laz_ig_likes
    ig_direction = "behind" if ig_likes_gap > 0 else "ahead of"

    exec_summary = (
        f"On TikTok, {tt_winner} dominates video reach with {fmt_num(tt_delta)} more plays than {tt_loser} "
        f"across the most-recent 28 posts, signalling a stronger short-video content cadence. "
        f"On Instagram, {ig_er_winner} leads engagement rate by {ig_er_delta:.3f} percentage points over "
        f"{ig_er_loser}, indicating a more interactive audience relationship. "
        f"Lazada_SG sits {fmt_num(abs(ig_likes_gap))} likes {ig_direction} Shopee_SG on Instagram — "
        f"bridging this gap via high-frequency reels and shoppable carousel posts is the single highest-ROI "
        f"Instagram action for the next quarter."
    )

    lines += [
        "", "EXECUTIVE SUMMARY", "-" * 60, "",
        textwrap.fill(exec_summary, width=78),
        "", "=" * 60,
        f"Report generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    if demo:
        lines.append("⚠  DEMO DATA — figures are synthetic. Re-run pipeline.py with APIFY_API_KEY.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n=== Computing stats from demo data ===")
    stats = {}
    for brand in ["Lazada_SG", "Shopee_SG"]:
        ig_posts = DEMO_DATA[(brand, "Instagram")]
        tt_posts = DEMO_DATA[(brand, "TikTok")]
        stats[(brand, "Instagram")] = ig_stats(ig_posts, brand)
        stats[(brand, "TikTok")]    = tt_stats(tt_posts, brand)

    for key, s in stats.items():
        print(f"  {key[0]:14} {key[1]:12} posts={s['video_count']:3}  likes={fmt_num(s['total_likes']):8}  "
              f"plays={fmt_num(s['total_plays']):8}  ER={s['avg_er_pct']:.3f}%")

    report = build_report(stats, demo=True)
    print("\n" + report)

    out = f"/home/user/lazada-dashboard/report_demo_{datetime.date.today().strftime('%Y%m%d')}.txt"
    with open(out, "w") as f:
        f.write(report)
    print(f"\nSaved to {out}")
