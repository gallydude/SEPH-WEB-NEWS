import json
import time
import os
import csv
from typing import Optional
from groq import Groq, RateLimitError
from config import GROQ_API_KEY, GROQ_MODEL, DATA_DIR, MIN_RELEVANCE_SCORE

_SYSTEM_PROMPT = """You analyze Canadian news for SEPH (Survey of Employment, Payrolls and Hours) — a Statistics Canada survey measuring payroll employment by industry.

Articles may be in English or French. Always respond in English JSON regardless of the article language.

NAICS CLASSIFICATION RULES:
- Classify by employer's PRIMARY activity, not client or parent company
- Staffing/temp agency workers -> NAICS 56 (unless placement sector named)
- Contractors on client site -> contractor's sector (e.g. construction contractors -> 23)
- Gov-funded nonprofits -> functional sector (61=education, 62=health), not 91
- Crown corps -> by activity: Canada Post->48-49, CBC->51, BC Hydro->22
- Gov departments -> NAICS 91
- NAICS 55 is almost never correct -> use UNCLEAR instead
- Ambiguous -> UNCLEAR

NAICS SECTORS: 11=Agriculture 21=Mining/oil&gas 22=Utilities 23=Construction 31-33=Manufacturing 41=Wholesale 44-45=Retail 48-49=Transportation 51=Information/media 52=Finance/insurance 53=Real estate 54=Professional services 55=Management of companies 56=Admin/support 61=Education 62=Health care 71=Arts/entertainment 72=Accommodation/food 81=Other services 91=Public administration

RELEVANCE (1-5 for SEPH payroll impact):
5=specific worker count + confirmed timing; 4=significant but count missing; 3=possible impact, uncertain scale; 2=indirect/policy/speculative; 1=no employment event

IMPACT: Positive|Negative|Mixed|Uncertain|No clear impact
PROVINCE: where workers are employed (not HQ); use abbreviations; "National" for federal; "Not specified" if unknown
EVENT TYPE: Strike|Layoff|Closure|Hiring|Expansion|Bankruptcy|Restructuring|Policy|Contract|Seasonal|Shutdown|Other"""


def _load_known_employers() -> dict[str, str]:
    path = os.path.join(DATA_DIR, "known_employers.csv")
    registry = {}
    try:
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("employer_name", "").lower().strip()
                code = row.get("naics_code", "").strip()
                if name and code and code != "UNION":
                    registry[name] = code
    except FileNotFoundError:
        pass
    return registry


_KNOWN_EMPLOYERS = _load_known_employers()


def _employer_naics_override(headline: str, description: str) -> Optional[str]:
    text = (headline + " " + description).lower()
    for employer, code in _KNOWN_EMPLOYERS.items():
        if employer in text:
            return code
    return None


def _build_user_message(article: dict) -> str:
    headline = article.get("headline", "").strip()
    source = article.get("source_name", "").strip()
    pub_date = article.get("published_date", "").strip()
    description = (article.get("description") or "").strip()[:2000]
    naics_hint = article.get("query_naics_hint", "")
    hint_line = f"\nSearch hint (possible NAICS): {naics_hint}" if naics_hint else ""

    return f"""Analyze this Canadian news article for SEPH employment relevance.{hint_line}

Headline: {headline}
Source: {source}
Published: {pub_date}
Content: {description}

Return a JSON object with EXACTLY these fields:
{{
  "summary": "2-3 factual sentences focused on employment impact",
  "naics_code": "two-digit code or range e.g. 31-33, or UNCLEAR",
  "naics_sector": "full sector name",
  "event_type": "Strike|Layoff|Closure|Hiring|Expansion|Bankruptcy|Restructuring|Policy|Contract|Seasonal|Shutdown|Other",
  "employer": "company or organization name, or Not specified",
  "province": "province abbreviation(s) or National or Not specified",
  "impact_direction": "Positive|Negative|Mixed|Uncertain|No clear impact",
  "workers_affected": null or integer,
  "relevance_score": 1 to 5 integer,
  "relevance_justification": "one sentence explaining the score",
  "include_in_newsletter": true or false
}}"""


def process_article(article: dict, client: Groq, _retry: int = 0) -> dict:
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(article)},
            ],
            max_tokens=600,
            temperature=0.1,
            response_format={"type": "json_object"},  # Forces valid JSON output
        )

        parsed = json.loads(response.choices[0].message.content)

        # Known employer override
        override = _employer_naics_override(
            article.get("headline", ""), article.get("description", "")
        )
        if override and parsed.get("naics_code") in ("UNCLEAR", "55", ""):
            parsed["naics_code"] = override

        # Minimum relevance score filter
        if parsed.get("relevance_score", 0) < MIN_RELEVANCE_SCORE:
            parsed["include_in_newsletter"] = False

        # Significance filter: require 100+ workers affected, unless it's a strike/lockout
        # (worker count unknown = keep; strikes always kept regardless of size)
        workers = parsed.get("workers_affected")
        event = parsed.get("event_type", "")
        is_strike = event in ("Strike", "Lockout")
        exclusion_reason = ""

        if parsed.get("include_in_newsletter", True) and not is_strike:
            if workers is not None and workers < 100:
                parsed["include_in_newsletter"] = False
                exclusion_reason = f"Below 100-worker threshold ({workers} reported)"

        article.update({
            "summary": parsed.get("summary", ""),
            "naics_code": parsed.get("naics_code", "UNCLEAR"),
            "naics_sector": parsed.get("naics_sector", ""),
            "event_type": event,
            "employer": parsed.get("employer", "Not specified"),
            "province": parsed.get("province", "Not specified"),
            "impact_direction": parsed.get("impact_direction", "Uncertain"),
            "workers_affected": workers,
            "relevance_score": parsed.get("relevance_score", 1),
            "relevance_justification": parsed.get("relevance_justification", ""),
            "included_in_newsletter": 1 if parsed.get("include_in_newsletter", False) else 0,
            "exclusion_reason": exclusion_reason,
            "classified_by": f"groq/{GROQ_MODEL}",
        })

    except RateLimitError:
        if _retry >= 4:
            print("  [processor] Rate limit: max retries exceeded, skipping article.")
            article.update({"naics_code": "UNCLEAR", "relevance_score": 1,
                            "included_in_newsletter": 0, "exclusion_reason": "Rate limit"})
            return article
        wait = 30 * (2 ** _retry)  # 30s, 60s, 120s, 240s
        print(f"  [processor] Rate limit hit — waiting {wait}s (retry {_retry + 1}/4)...")
        time.sleep(wait)
        return process_article(article, client, _retry + 1)
    except json.JSONDecodeError as e:
        print(f"  [processor] JSON parse error for '{article.get('headline', '')[:60]}': {e}")
        article.update({
            "naics_code": "UNCLEAR", "relevance_score": 1,
            "included_in_newsletter": 0, "exclusion_reason": "JSON parse error",
            "classified_by": "error",
        })
    except Exception as e:
        print(f"  [processor] Error for '{article.get('headline', '')[:60]}': {e}")
        article.update({
            "naics_code": "UNCLEAR", "relevance_score": 1,
            "included_in_newsletter": 0,
            "exclusion_reason": f"Processing error: {type(e).__name__}",
            "classified_by": "error",
        })

    return article


def process_articles(articles: list[dict], delay: float = 2.5) -> list[dict]:
    # 2.5s delay = ~24 req/min, safely under Groq free tier limit of 30 req/min
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set. Add it to your .env file.")

    client = Groq(api_key=GROQ_API_KEY)
    total = len(articles)
    print(f"\n[processor] Processing {total} articles with Groq ({GROQ_MODEL})...")

    enriched = []
    for i, article in enumerate(articles, 1):
        print(f"  [{i}/{total}] {article.get('headline', '')[:70]}")
        result = process_article(article, client)
        enriched.append(result)
        if i < total:
            time.sleep(delay)

    included = sum(1 for a in enriched if a.get("included_in_newsletter"))
    print(f"[processor] Done. {included}/{total} articles marked for newsletter.")
    return enriched
