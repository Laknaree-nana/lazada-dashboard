"""
Report generator: reads apify_results.json and produces a full competitor
social media report as a text string ready for Google Docs.

Usage:
    python3 scripts/generate_report.py > report_output.txt
"""

import json, sys, os
from datetime import datetime

TODAY = datetime.utcnow()
DATE_STR = TODAY.strftime('%-d %b %Y')   # e.g. 14 Jun 2026


# ── Metric extractors ──────────────────────────────────────────────────────────

def ig_metrics(post):
    return {
        'likes':    post.get('likesCount') or post.get('likes') or 0,
        'comments': post.get('commentsCount') or post.get('comments') or 0,
        'plays':    0,
        'shares':   0,
        'url':      post.get('url') or post.get('shortCode') or '',
        'caption':  (post.get('caption') or '')[:80],
        'timestamp': post.get('timestamp') or post.get('taken_at_timestamp') or '',
        'type':     post.get('type') or post.get('productType') or 'image',
    }


def tt_metrics(post):
    stats = post.get('stats') or {}
    return {
        'likes':    stats.get('diggCount') or post.get('diggCount') or 0,
        'comments': stats.get('commentCount') or post.get('commentCount') or 0,
        'plays':    stats.get('playCount') or post.get('playCount') or 0,
        'shares':   stats.get('shareCount') or post.get('shareCount') or 0,
        'url':      post.get('webVideoUrl') or post.get('id') or '',
        'caption':  (post.get('desc') or '')[:80],
        'timestamp': post.get('createTime') or '',
        'type':     'video',
    }


def compute_stats(items, extractor):
    if not items:
        return {'count': 0, 'likes': 0, 'comments': 0, 'plays': 0, 'shares': 0,
                'avg_er': 0.0, 'posts': []}
    posts = [extractor(p) for p in items]
    count = len(posts)
    total_likes = sum(p['likes'] for p in posts)
    total_comments = sum(p['comments'] for p in posts)
    total_plays = sum(p['plays'] for p in posts)
    total_shares = sum(p['shares'] for p in posts)
    avg_er = (total_likes + total_comments) / count if count else 0
    return {
        'count': count,
        'likes': total_likes,
        'comments': total_comments,
        'plays': total_plays,
        'shares': total_shares,
        'avg_er': round(avg_er, 1),
        'posts': sorted(posts, key=lambda p: p['likes'] + p['comments'], reverse=True),
    }


# ── Chart builders ─────────────────────────────────────────────────────────────

def bar_chart(label_a, val_a, label_b, val_b, width=40):
    """Head-to-head horizontal bar chart using █/░."""
    total = (val_a + val_b) or 1
    filled_a = round(val_a / total * width)
    filled_b = round(val_b / total * width)
    pct_a = round(val_a / total * 100)
    pct_b = round(val_b / total * 100)
    bar_a = '█' * filled_a + '░' * (width - filled_a)
    bar_b = '█' * filled_b + '░' * (width - filled_b)
    return (
        f"  {label_a:<10} {bar_a} {val_a:,} ({pct_a}%)\n"
        f"  {label_b:<10} {bar_b} {val_b:,} ({pct_b}%)"
    )


def content_mix_bar(reel_count, image_count, total, width=14):
    """Single brand content type bar (reels vs images)."""
    if total == 0:
        return '░' * width + ' (no data)'
    reel_w = round(reel_count / total * width)
    img_w = width - reel_w
    bar = '▓' * reel_w + '░' * img_w
    return f"{bar}  reels={reel_count}  img/carousel={image_count}"


def top5_table(posts, platform):
    """Top 5 posts ranked by engagement."""
    lines = []
    for i, p in enumerate(posts[:5], 1):
        eng = p['likes'] + p['comments']
        if platform == 'tt':
            detail = f"plays={p['plays']:,}  likes={p['likes']:,}  shares={p['shares']:,}"
        else:
            detail = f"likes={p['likes']:,}  comments={p['comments']:,}"
        caption = p['caption'][:60] + ('…' if len(p['caption']) >= 60 else '')
        url = p['url']
        lines.append(f"  {i}. eng={eng:,}  {detail}\n     \"{caption}\"\n     {url}")
    return '\n'.join(lines) if lines else '  (no posts)'


# ── Main ───────────────────────────────────────────────────────────────────────

def build_report(data):
    lz_ig = compute_stats(data.get('lazada_ig', []), ig_metrics)
    sh_ig = compute_stats(data.get('shopee_ig', []), ig_metrics)
    lz_tt = compute_stats(data.get('lazada_tt', []), tt_metrics)
    sh_tt = compute_stats(data.get('shopee_tt', []), tt_metrics)

    # IG content mix (reels vs image/carousel)
    def ig_mix(items):
        reels = sum(1 for p in items if 'reel' in str(p.get('type', '')).lower() or
                    p.get('productType') == 'clips')
        total = len(items)
        images = total - reels
        return reels, images, total

    lz_ig_reels, lz_ig_imgs, lz_ig_total = ig_mix(data.get('lazada_ig', []))
    sh_ig_reels, sh_ig_imgs, sh_ig_total = ig_mix(data.get('shopee_ig', []))

    # Executive summary
    lz_tt_reach = lz_tt['plays']
    sh_tt_reach = sh_tt['plays']
    ig_er_winner = 'Lazada SG' if lz_ig['avg_er'] >= sh_ig['avg_er'] else 'Shopee SG'
    ig_er_loser = 'Shopee SG' if ig_er_winner == 'Lazada SG' else 'Lazada SG'
    ig_likes_gap = abs(lz_ig['likes'] - sh_ig['likes'])
    ig_likes_leader = 'Lazada SG' if lz_ig['likes'] >= sh_ig['likes'] else 'Shopee SG'

    summary = (
        f"On TikTok, Lazada SG accumulated {lz_tt_reach:,} total video plays across "
        f"{lz_tt['count']} posts versus Shopee SG's {sh_tt_reach:,} plays across "
        f"{sh_tt['count']} posts, giving {'Lazada SG' if lz_tt_reach >= sh_tt_reach else 'Shopee SG'} "
        f"a {abs(lz_tt_reach - sh_tt_reach):,}-play reach advantage. "
        f"On Instagram, {ig_er_winner} leads on average engagement per post "
        f"({(lz_ig['avg_er'] if ig_er_winner == 'Lazada SG' else sh_ig['avg_er']):,.0f} vs "
        f"{(sh_ig['avg_er'] if ig_er_winner == 'Lazada SG' else lz_ig['avg_er']):,.0f}) "
        f"driven by stronger comment volume. "
        f"{ig_likes_leader} holds a {ig_likes_gap:,}-like lead in total Instagram likes — "
        f"{'the trailing brand' if ig_likes_leader == 'Lazada SG' else 'Lazada'} should "
        f"increase posting cadence and incorporate trending audio in Reels to close the gap."
    )

    lines = [
        '=' * 60,
        f'COMPETITOR SOCIAL REPORT — {DATE_STR.upper()}',
        f'Lazada SG vs Shopee SG  |  Instagram & TikTok',
        '=' * 60,
        '',
        '──────────────────────────────────────────────────────────',
        'EXECUTIVE SUMMARY',
        '──────────────────────────────────────────────────────────',
        summary,
        '',
        '══════════════════════════════════════════════════════════',
        '  TIKTOK HEAD-TO-HEAD',
        '══════════════════════════════════════════════════════════',
        '',
        f'  Posts scraped:',
        f'    Lazada SG : {lz_tt["count"]}',
        f'    Shopee SG : {sh_tt["count"]}',
        '',
        'VIDEO PLAYS',
        bar_chart('Lazada SG', lz_tt['plays'], 'Shopee SG', sh_tt['plays']),
        '',
        'LIKES',
        bar_chart('Lazada SG', lz_tt['likes'], 'Shopee SG', sh_tt['likes']),
        '',
        'COMMENTS',
        bar_chart('Lazada SG', lz_tt['comments'], 'Shopee SG', sh_tt['comments']),
        '',
        'SHARES',
        bar_chart('Lazada SG', lz_tt['shares'], 'Shopee SG', sh_tt['shares']),
        '',
        f'  Avg engagement/post (likes+comments):',
        f'    Lazada SG : {lz_tt["avg_er"]:,.0f}',
        f'    Shopee SG : {sh_tt["avg_er"]:,.0f}',
        '',
        '──────────────────────────────────────────────────────────',
        '  TOP 5 TIKTOK POSTS — LAZADA SG',
        '──────────────────────────────────────────────────────────',
        top5_table(lz_tt['posts'], 'tt'),
        '',
        '──────────────────────────────────────────────────────────',
        '  TOP 5 TIKTOK POSTS — SHOPEE SG',
        '──────────────────────────────────────────────────────────',
        top5_table(sh_tt['posts'], 'tt'),
        '',
        '══════════════════════════════════════════════════════════',
        '  INSTAGRAM HEAD-TO-HEAD',
        '══════════════════════════════════════════════════════════',
        '',
        f'  Posts scraped:',
        f'    Lazada SG : {lz_ig["count"]}',
        f'    Shopee SG : {sh_ig["count"]}',
        '',
        'LIKES',
        bar_chart('Lazada SG', lz_ig['likes'], 'Shopee SG', sh_ig['likes']),
        '',
        'COMMENTS',
        bar_chart('Lazada SG', lz_ig['comments'], 'Shopee SG', sh_ig['comments']),
        '',
        f'  Avg engagement/post (likes+comments):',
        f'    Lazada SG : {lz_ig["avg_er"]:,.0f}',
        f'    Shopee SG : {sh_ig["avg_er"]:,.0f}',
        '',
        'CONTENT MIX  (▓=Reels  ░=Image/Carousel)',
        f'  Lazada SG  {content_mix_bar(lz_ig_reels, lz_ig_imgs, lz_ig_total)}',
        f'  Shopee SG  {content_mix_bar(sh_ig_reels, sh_ig_imgs, sh_ig_total)}',
        '',
        '──────────────────────────────────────────────────────────',
        '  TOP 5 INSTAGRAM POSTS — LAZADA SG',
        '──────────────────────────────────────────────────────────',
        top5_table(lz_ig['posts'], 'ig'),
        '',
        '──────────────────────────────────────────────────────────',
        '  TOP 5 INSTAGRAM POSTS — SHOPEE SG',
        '──────────────────────────────────────────────────────────',
        top5_table(sh_ig['posts'], 'ig'),
        '',
        '══════════════════════════════════════════════════════════',
        '  METRICS SUMMARY TABLE',
        '══════════════════════════════════════════════════════════',
        '',
        f'  {"Metric":<22} {"Lazada SG":>14} {"Shopee SG":>14}',
        f'  {"─"*22} {"─"*14} {"─"*14}',
        f'  {"[TT] Video Plays":<22} {lz_tt["plays"]:>14,} {sh_tt["plays"]:>14,}',
        f'  {"[TT] Likes":<22} {lz_tt["likes"]:>14,} {sh_tt["likes"]:>14,}',
        f'  {"[TT] Comments":<22} {lz_tt["comments"]:>14,} {sh_tt["comments"]:>14,}',
        f'  {"[TT] Shares":<22} {lz_tt["shares"]:>14,} {sh_tt["shares"]:>14,}',
        f'  {"[TT] Avg ER/post":<22} {lz_tt["avg_er"]:>14,.0f} {sh_tt["avg_er"]:>14,.0f}',
        f'  {"[TT] Video Count":<22} {lz_tt["count"]:>14} {sh_tt["count"]:>14}',
        f'  {"[IG] Likes":<22} {lz_ig["likes"]:>14,} {sh_ig["likes"]:>14,}',
        f'  {"[IG] Comments":<22} {lz_ig["comments"]:>14,} {sh_ig["comments"]:>14,}',
        f'  {"[IG] Avg ER/post":<22} {lz_ig["avg_er"]:>14,.0f} {sh_ig["avg_er"]:>14,.0f}',
        f'  {"[IG] Post Count":<22} {lz_ig["count"]:>14} {sh_ig["count"]:>14}',
        '',
        '=' * 60,
        f'Generated: {TODAY.strftime("%Y-%m-%d %H:%M UTC")}',
        '=' * 60,
    ]

    return '\n'.join(lines)


if __name__ == '__main__':
    data_path = '/home/user/lazada-dashboard/apify_results.json'
    if not os.path.exists(data_path):
        print('[ERROR] apify_results.json not found — run pipeline_run.py first', file=sys.stderr)
        sys.exit(1)

    with open(data_path) as f:
        data = json.load(f)

    report = build_report(data)
    print(report)

    # Also save to file
    out_path = '/home/user/lazada-dashboard/report_output.txt'
    with open(out_path, 'w') as f:
        f.write(report)
    print(f'\n[SAVED] {out_path}', file=sys.stderr)
