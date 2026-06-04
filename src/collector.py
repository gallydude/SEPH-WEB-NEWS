import time
import json
import os
import urllib.parse
import requests
import feedparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from dateutil import parser as dateparser
from config import NEWS_API_KEY, DATA_DIR, MAX_ARTICLES_PER_QUERY, REQUEST_DELAY_SECONDS

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Google News RSS — one query per sector, free, no API key
_GNEWS_BASE = "https://news.google.com/rss/search"

# Core queries: one representative query per NAICS sector, scoped to Canada
_SECTOR_GNEWS_QUERIES = {
    "11":    "farm workers OR agricultural workers Canada layoffs OR strike OR hiring",
    "21":    "oil sands OR mining OR oilfield Canada layoffs OR strike OR closure",
    "22":    "hydro OR utility workers Canada strike OR layoffs",
    "23":    "construction workers Canada layoffs OR strike OR jobs",
    "31-33": "plant closure OR factory shutdown OR manufacturing layoffs Canada",
    "41":    "wholesale distribution layoffs Canada",
    "44-45": "retail store closure OR retail layoffs Canada",
    "48-49": "rail workers OR truckers OR airline workers Canada strike OR layoffs",
    "51":    "tech layoffs OR media layoffs Canada",
    "52":    "bank layoffs OR insurance Canada job cuts",
    "53":    "real estate company Canada layoffs",
    "54":    "consulting firm OR professional services Canada layoffs OR contract",
    "56":    "staffing agency OR call centre OR security company Canada layoffs",
    "61":    "teachers OR university workers OR school board Canada strike OR layoffs",
    "62":    "hospital OR nurses OR long-term care Canada strike OR layoffs OR hiring",
    "71":    "casino workers OR entertainment workers Canada strike OR layoffs",
    "72":    "restaurant OR hotel workers Canada layoffs OR closure",
    "81":    "non-profit workers Canada layoffs",
    "91":    "federal government OR public service Canada layoffs OR hiring OR cuts",
}

# Broad catch-all queries (English)
_BROAD_QUERIES = [
    "Canada layoffs jobs 2026",
    "Canada strike workers 2026",
    "Canada plant closure jobs 2026",
    "Canada hiring jobs announcement 2026",
    "Canada bankruptcy workers 2026",
    "PSAC OR Unifor OR CUPE Canada 2026",
]

# French sector queries — Google News fr-CA
_FR_SECTOR_GNEWS_QUERIES = {
    "11":    "travailleurs agricoles Canada mises à pied OR grève OR embauche",
    "21":    "mines OR pétrole OR sables bitumineux Canada mises à pied OR grève OR fermeture",
    "22":    "Hydro-Québec OR travailleurs services publics Canada grève OR mises à pied",
    "23":    "travailleurs construction Canada mises à pied OR grève emplois",
    "31-33": "fermeture usine OR mises à pied Canada fabrication OR manufacture",
    "41":    "grossistes OR distribution Canada mises à pied emplois",
    "44-45": "fermeture magasin OR mises à pied Canada commerce détail",
    "48-49": "cheminots OR camionneurs OR travailleurs transport Canada grève OR mises à pied",
    "51":    "mises à pied médias OR technologie Canada compressions",
    "52":    "banque OR assurance Canada mises à pied OR compressions emplois",
    "53":    "immobilier Canada mises à pied emplois",
    "54":    "services professionnels OR consultation Canada mises à pied contrat",
    "56":    "agence placement OR centre appels Canada mises à pied fermeture",
    "61":    "enseignants OR travailleurs scolaires OR université Canada grève OR mises à pied",
    "62":    "travailleurs santé OR infirmières OR soins longue durée Canada grève OR mises à pied OR embauche",
    "71":    "travailleurs casino OR divertissement Canada grève OR mises à pied",
    "72":    "travailleurs hôtellerie OR restauration Canada mises à pied OR fermeture",
    "81":    "organismes sans but lucratif Canada mises à pied emplois",
    "91":    "gouvernement fédéral OR fonction publique Canada mises à pied OR compressions OR grève",
}

# Broad catch-all queries (French)
_FR_BROAD_QUERIES = [
    "mises à pied Canada emplois 2026",
    "grève Canada travailleurs 2026",
    "fermeture emplois Canada 2026",
    "embauche recrutement Canada 2026",
    "faillite Canada travailleurs 2026",
    "SCFP OR Unifor OR AFPC Canada 2026",
]


def _month_date_range(reference_month: str, lookback_days: int = 14) -> tuple[str, str]:
    year, month = map(int, reference_month.split("-"))
    start = datetime(year, month, 1) - timedelta(days=lookback_days)
    end = datetime(year, month, 1) + relativedelta(months=1) - timedelta(days=1)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _normalize_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        return dateparser.parse(raw).strftime("%Y-%m-%d")
    except Exception:
        return raw[:10] if len(raw) >= 10 else raw


def _in_date_range(pub_date_str: str, from_dt: datetime, to_dt: datetime) -> bool:
    if not pub_date_str:
        return True  # Keep if date unknown
    try:
        pub_dt = datetime.strptime(pub_date_str[:10], "%Y-%m-%d")
        return from_dt <= pub_dt <= to_dt
    except ValueError:
        return True


def _gnews_url(query: str, lang: str = "en") -> str:
    if lang == "fr":
        params = urllib.parse.urlencode({"q": query, "hl": "fr-CA", "gl": "CA", "ceid": "CA:fr"})
    else:
        params = urllib.parse.urlencode({"q": query, "hl": "en-CA", "gl": "CA", "ceid": "CA:en"})
    return f"{_GNEWS_BASE}?{params}"


def _fetch_feed(args: tuple) -> tuple:
    """Fetch a single RSS feed. Safe to call from worker threads."""
    lang, naics_hint, query = args
    url = _gnews_url(query, lang)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        return lang, naics_hint, query, resp.content
    except Exception as e:
        print(f"  [collector] Google News error for '{query[:45]}': {e}")
        return lang, naics_hint, query, None


def _parse_gnews_feed(feed, seen_urls: set, reference_month: str,
                      naics_hint: str, lang: str) -> list[dict]:
    articles = []
    for entry in feed.entries:
        article_url = entry.get("link", "")
        if not article_url or article_url in seen_urls:
            continue
        pub_date = _normalize_date(entry.get("published", entry.get("updated", "")))
        seen_urls.add(article_url)
        description = entry.get("summary", "") or entry.get("description", "")
        headline = entry.get("title", "")
        source_name = ""
        if " - " in headline:
            parts = headline.rsplit(" - ", 1)
            headline = parts[0].strip()
            source_name = parts[1].strip()
        articles.append({
            "url": article_url,
            "headline": headline,
            "source_name": source_name or "Google News",
            "published_date": pub_date,
            "description": description,
            "reference_month": reference_month,
            "collection_source": "google_news",
            "query_naics_hint": naics_hint,
            "language": lang,
        })
    return articles


def collect_from_google_news(reference_month: str, lookback_days: int = 14,
                              languages: list[str] = None) -> list[dict]:
    """Query Google News RSS in English and/or French."""
    if languages is None:
        languages = ["en", "fr"]

    from_date_str, to_date_str = _month_date_range(reference_month, lookback_days)
    from_dt = datetime.strptime(from_date_str, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date_str, "%Y-%m-%d").replace(hour=23, minute=59)

    articles = []
    seen_urls: set = set()

    query_sets = []
    if "en" in languages:
        query_sets += [("en", naics, q) for naics, q in _SECTOR_GNEWS_QUERIES.items()]
        query_sets += [("en", "", q) for q in _BROAD_QUERIES]
    if "fr" in languages:
        query_sets += [("fr", naics, q) for naics, q in _FR_SECTOR_GNEWS_QUERIES.items()]
        query_sets += [("fr", "", q) for q in _FR_BROAD_QUERIES]

    print(f"  [collector] Fetching {len(query_sets)} feeds in parallel (8 workers)...")
    with ThreadPoolExecutor(max_workers=8) as executor:
        fetch_results = list(executor.map(_fetch_feed, query_sets))

    for lang, naics_hint, query, content in fetch_results:
        if content is None:
            continue
        feed = feedparser.parse(content)
        before = len(articles)
        new = _parse_gnews_feed(feed, seen_urls, reference_month, naics_hint, lang)
        new = [a for a in new if _in_date_range(a["published_date"], from_dt, to_dt)]
        articles.extend(new)
        label = f"[{lang.upper()}] NAICS {naics_hint}" if naics_hint else f"[{lang.upper()}] broad"
        print(f"  [collector] {label}: '{query[:50]}' -> {len(articles) - before} articles")

    print(f"  [collector] Google News total: {len(articles)} articles.")
    return articles


def collect_from_newsapi(reference_month: str, lookback_days: int = 14) -> list[dict]:
    """Fetch articles from NewsAPI (requires API key)."""
    if not NEWS_API_KEY:
        return []

    query_path = os.path.join(DATA_DIR, "search_queries.json")
    with open(query_path, encoding="utf-8") as f:
        queries = json.load(f)

    from_date, to_date = _month_date_range(reference_month, lookback_days)
    articles = []
    seen_urls = set()

    base_url = "https://newsapi.org/v2/everything"
    headers = {"X-Api-Key": NEWS_API_KEY}

    for naics_code, query_list in queries["sector_queries"].items():
        for query_str in query_list:
            params = {
                "q": query_str,
                "from": from_date,
                "to": to_date,
                "language": "en",
                "sortBy": "relevancy",
                "pageSize": MAX_ARTICLES_PER_QUERY,
            }
            try:
                resp = requests.get(base_url, params=params, headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  [collector] NewsAPI error for '{query_str}': {e}")
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            for item in data.get("articles", []):
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                articles.append({
                    "url": url,
                    "headline": item.get("title", ""),
                    "source_name": item.get("source", {}).get("name", ""),
                    "published_date": _normalize_date(item.get("publishedAt", "")),
                    "description": (item.get("description") or "") + " " + (item.get("content") or ""),
                    "reference_month": reference_month,
                    "collection_source": "newsapi",
                    "query_naics_hint": naics_code,
                })

            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"  [collector] NewsAPI: {len(articles)} articles.")
    return articles


def deduplicate(articles: list[dict]) -> list[dict]:
    seen_urls = set()
    seen_headlines = []
    result = []

    for a in articles:
        url = a.get("url", "")
        headline = (a.get("headline") or "").lower().strip()

        if url in seen_urls:
            continue

        is_duplicate = False
        for existing in seen_headlines:
            if _headline_similarity(headline, existing) > 0.85:
                is_duplicate = True
                break

        if is_duplicate:
            continue

        seen_urls.add(url)
        seen_headlines.append(headline)
        result.append(a)

    removed = len(articles) - len(result)
    if removed:
        print(f"  [collector] Deduplication removed {removed} articles.")
    return result


def _headline_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def collect_all(reference_month: str, lookback_days: int = 14,
                languages: list[str] = None) -> list[dict]:
    if languages is None:
        languages = ["en", "fr"]
    lang_label = " + ".join(l.upper() for l in languages)
    print(f"\n[collector] Collecting news for {reference_month} [{lang_label}]")
    gnews_articles = collect_from_google_news(reference_month, lookback_days, languages)
    newsapi_articles = collect_from_newsapi(reference_month, lookback_days)
    combined = gnews_articles + newsapi_articles
    deduped = deduplicate(combined)
    print(f"[collector] Total after deduplication: {len(deduped)} articles.")
    return deduped
