# Daily Competitor Social Media Report

## Pipeline Instructions

When this session starts as part of the "Daily Competitor Social Report" routine, run the full pipeline automatically:

### Step 1 — Scrape TikTok (run sequentially due to Apify memory limits)
```bash
# TikTok Lazada SG
curl -s -X POST "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/runs?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profiles":["lazada_sg"],"resultsPerPage":30}'

# TikTok Shopee SG
curl -s -X POST "https://api.apify.com/v2/acts/clockworks~free-tiktok-scraper/runs?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"profiles":["shopeesg"],"resultsPerPage":30}'
```
Wait for both TikTok runs to reach SUCCEEDED status before proceeding.

### Step 2 — Scrape Instagram (after TikTok completes to avoid memory limit)
```bash
# Instagram Lazada SG
curl -s -X POST "https://api.apify.com/v2/acts/apify~instagram-scraper/runs?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"directUrls":["https://www.instagram.com/lazada_sg/"],"resultsLimit":30}'

# Instagram Shopee SG
curl -s -X POST "https://api.apify.com/v2/acts/apify~instagram-scraper/runs?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"directUrls":["https://www.instagram.com/shopee_sg/"],"resultsLimit":30}'
```
Wait for both Instagram runs to reach SUCCEEDED status.

### Step 3 — Fetch dataset items
Download results from each run's defaultDatasetId using:
```
GET https://api.apify.com/v2/datasets/{datasetId}/items?token=$APIFY_TOKEN&limit=30
```

### Step 4 — Compute metrics
- TikTok: total plays, likes, comments, shares per brand
- Instagram: total likes, comments, video views per brand
- TikTok ER = (likes + comments + shares) / plays × 100
- Instagram ER = (likes + comments) / videoViews × 100
- Top 3 posts per platform per brand (TikTok by plays, Instagram by likes)
- Instagram content mix: count Video/Reel vs Image vs Sidecar/Carousel posts

### Step 5 — Update index.html
Update all KPI values, chart data, top posts tables, and content mix in `index.html`.
Update the date to today's date in format "DD Mon YYYY" (e.g. "05 Jun 2026").
Commit and push to branch `claude/amazing-euler-8tdsG`.

### Step 6 — Save report to Google Drive
Save a text report to Google Drive folder ID: `1M7snHgI-MNTa9Y5PiyM0FPc3bKktNlqT`
Title format: `Competitor Social Report — DD Mon YYYY`

## Key Details
- Apify token: read from `$APIFY_TOKEN` environment variable
- TikTok actor: `clockworks~free-tiktok-scraper`
- Instagram actor: `apify~instagram-scraper`
- Profiles: TikTok `lazada_sg` / `shopeesg`, Instagram `lazada_sg` / `shopee_sg`
- Run TikTok first, wait for completion, then run Instagram (Apify free tier memory limit)
- Google Drive folder: `1M7snHgI-MNTa9Y5PiyM0FPc3bKktNlqT`
