# Newsstand — final local build

A single-file Python backend + single HTML frontend for a personal news/e-paper dashboard.

## Files

```text
newsstand/
  app.py
  sources.json
  index.html
  requirements.txt
  README.md
```

`newsstand.db` is created automatically.

## Windows — quickest setup

Open Command Prompt:

```bat
cd /d D:\newsstand

py -3 -m venv .venv
.venv\Scripts\activate

python -m pip install --upgrade pip
pip install -r requirements.txt

python app.py
```

Open:

http://127.0.0.1:8000

Click **Refresh** once.

## What is implemented

### News
- World / India / Maharashtra hierarchy
- State coverage
- Maharashtra city feeds for Mumbai, Pune, Nashik and Nagpur
- RSS ingestion
- Google News RSS discovery feeds for additional Indian states
- Automatic categorization
- Importance scoring
- Story clustering / basic duplicate grouping
- Source count
- Search
- Date filter
- SQLite archive
- Background refresh every 30 minutes
- Manual refresh
- Daily briefing
- Responsive frontend

### E-paper
- Central e-paper directory
- Newspaper → region/state/edition metadata
- Official e-paper URL
- Official archive URL where supplied
- Selected date is passed through the UI
- The system never fabricates a historical edition URL
- No full newspaper PDFs are downloaded/re-hosted by default

This is deliberate: complete newspaper editions are generally copyrighted. The app is designed to send the user to the publisher's official reader/archive. A publisher-specific adapter can be added only where the publisher permits the required access/redistribution.

## Adding a newspaper

Edit `sources.json`.

RSS:

```json
{
  "name": "Example",
  "url": "https://example.com/rss.xml",
  "region": "India",
  "state": "Maharashtra",
  "city": "Pune",
  "language": "en",
  "priority": 8
}
```

E-paper:

```json
"epapers": [
  {
    "name": "Example",
    "region": "India",
    "state": "Maharashtra",
    "city": "Pune",
    "edition": "Pune",
    "language": "en",
    "official_url": "https://example.com/epaper",
    "archive_url": "https://example.com/epaper/archive"
  }
]
```

Restart the app after changing `sources.json`.

## Historical dates

News articles are stored locally when ingested, so the date selector can search your stored archive.

For e-papers, the date selector cannot magically create an edition-specific URL. The app opens the publisher's official e-paper/archive landing page. If a publisher provides a documented/licensed date+edition URL scheme, implement it as an adapter before adding it to the registry.

## Optional environment variables

```bat
set PORT=8000
set REFRESH_MINUTES=30
python app.py
```

## Troubleshooting

If you see a Python import error:

```bat
.venv\Scripts\activate
pip install -r requirements.txt
```

If an old process is running:

```text
CTRL+C
python app.py
```

If you want a clean local database, stop the server and delete:

```text
newsstand.db
```

It will be recreated automatically.

## Important practical limitation

Some publishers change or block RSS feeds. A feed returning zero articles does not necessarily mean the publisher has no news. Add a different official feed or a permitted API/source in `sources.json`.

The Google News RSS feeds are used as a discovery layer and the article cards link to the underlying/original news destination rather than copying the article.
