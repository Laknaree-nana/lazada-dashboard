# Lazada Dashboard — Standing Instructions

## Daily Competitor Social Report

After generating each report, always save the Google Doc to this Drive folder:
- Folder ID: `1M7snHgI-MNTa9Y5PiyM0FPc3bKktNlqT`
- Folder URL: https://drive.google.com/drive/folders/1M7snHgI-MNTa9Y5PiyM0FPc3bKktNlqT

Name each doc: `Competitor Social Report — DD Mon YYYY` (e.g. `Competitor Social Report — 03 Jun 2026`)

Always create the Google Doc directly inside this folder by passing the folder ID as `parentId` when creating the file.

## Apify Token
Stored in `.env` as `APIFY_API_TOKEN`.

## Accounts to scrape
- Instagram: Lazada_SG, shopee_sg
- TikTok: lazada_sg, shopeesg

## Apify Actors
- Instagram: `shu8hvrXbJbY3Eb9W` (apify/instagram-scraper)
- TikTok: `OtzYfK1ndEGdwWFKQ` (clockworks/free-tiktok-scraper)

## Report includes
- 30 most recent posts per platform per brand
- KPI cards: TikTok plays, likes, comments, shares; Instagram likes, comments
- Bar charts and content mix doughnut charts
- Top 3 posts per brand per platform
- Executive summary (3 sentences)
- Link to live interactive HTML report on GitHub
