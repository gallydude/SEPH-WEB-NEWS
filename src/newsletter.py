import os
import json
from datetime import datetime
from collections import defaultdict
from jinja2 import Environment, FileSystemLoader
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL, DATA_DIR, TEMPLATES_DIR
from src.database import get_articles_for_month


_NAICS_ORDER = [
    "11", "21", "22", "23", "31-33", "41", "44-45", "48-49",
    "51", "52", "53", "54", "55", "56", "61", "62", "71", "72", "81", "91",
]


def _load_naics_map() -> dict[str, str]:
    path = os.path.join(DATA_DIR, "naics_sectors.json")
    with open(path, encoding="utf-8") as f:
        sectors = json.load(f)
    return {s["code"]: s["name"] for s in sectors}


def _group_by_sector(articles: list[dict]) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for a in articles:
        code = a.get("naics_code", "UNCLEAR")
        grouped[code].append(a)
    return dict(grouped)


def _generate_executive_summary(articles: list[dict]) -> str:
    """Call Groq to generate the executive summary paragraph."""
    if not articles:
        return "No significant employment events were identified for this reference month."

    if not GROQ_API_KEY:
        return _fallback_executive_summary(articles)

    bullet_lines = []
    for a in articles[:20]:
        workers = f" (~{a['workers_affected']:,} workers)" if a.get("workers_affected") else ""
        bullet_lines.append(
            f"- NAICS {a.get('naics_code')}: {a.get('event_type')} — "
            f"{a.get('headline', '')[:100]}{workers} [{a.get('impact_direction')}]"
        )

    prompt = f"""You are writing the executive summary for a monthly SEPH Labour Market Intelligence Newsletter.
SEPH (Survey of Employment, Payrolls and Hours) measures payroll employment by industry in Canada.

Below are the key employment events found for this reference month. Write a professional executive summary
of 3-5 sentences for analysts reviewing SEPH estimates. Highlight the sectors most likely to show unusual
movement, the dominant direction of impact, and any standout events. Be specific, factual, and concise.

Events:
{chr(10).join(bullet_lines)}

Write only the summary paragraph. No headers, no bullet points."""

    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=300,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  [newsletter] Executive summary generation error: {e}")
        return _fallback_executive_summary(articles)


def _fallback_executive_summary(articles: list[dict]) -> str:
    negative = [a for a in articles if a.get("impact_direction") == "Negative"]
    positive = [a for a in articles if a.get("impact_direction") == "Positive"]
    sectors = sorted(set(a.get("naics_sector", "") for a in articles if a.get("naics_sector")))
    return (
        f"This newsletter covers {len(articles)} employment-relevant events for the reference month. "
        f"{len(negative)} events indicate negative employment impact and {len(positive)} indicate positive impact. "
        f"Sectors with notable activity include: {', '.join(sectors[:5]) if sectors else 'see details below'}. "
        f"Analysts should cross-reference high-relevance items (score 4-5) against SEPH preliminary estimates."
    )


def _key_events_bullets(articles: list[dict], max_items: int = 10) -> list[dict]:
    """Return up to max_items highest-scoring articles for the key events section."""
    sorted_articles = sorted(articles, key=lambda a: a.get("relevance_score", 0), reverse=True)
    bullets = []
    for a in sorted_articles[:max_items]:
        workers = f" — {a['workers_affected']:,} workers" if a.get("workers_affected") else ""
        bullets.append({
            "naics_code": a.get("naics_code", ""),
            "event_type": a.get("event_type", ""),
            "headline": a.get("headline", ""),
            "workers_str": workers,
            "impact_direction": a.get("impact_direction", ""),
            "relevance_score": a.get("relevance_score", 0),
        })
    return bullets


def _sectors_with_no_events(articles: list[dict], naics_map: dict[str, str]) -> list[dict]:
    active_codes = set(a.get("naics_code", "") for a in articles)
    empty = []
    for code in _NAICS_ORDER:
        if code not in active_codes:
            empty.append({"code": code, "name": naics_map.get(code, code)})
    return empty


def _ordered_sectors(grouped: dict, naics_map: dict) -> list[dict]:
    """Return sectors in NAICS order with their articles, plus any unrecognized codes."""
    result = []
    seen = set()
    for code in _NAICS_ORDER:
        if code in grouped:
            result.append({
                "code": code,
                "name": naics_map.get(code, code),
                "articles": sorted(grouped[code], key=lambda a: a.get("relevance_score", 0), reverse=True),
            })
            seen.add(code)

    for code, arts in grouped.items():
        if code not in seen:
            result.append({
                "code": code,
                "name": naics_map.get(code, code),
                "articles": sorted(arts, key=lambda a: a.get("relevance_score", 0), reverse=True),
            })
    return result


def build_newsletter_context(reference_month: str) -> dict:
    """Assemble all template context for a given reference month."""
    articles = get_articles_for_month(reference_month)
    naics_map = _load_naics_map()
    grouped = _group_by_sector(articles)

    executive_summary = _generate_executive_summary(articles)
    key_events = _key_events_bullets(articles)
    ordered_sectors = _ordered_sectors(grouped, naics_map)
    empty_sectors = _sectors_with_no_events(articles, naics_map)

    return {
        "reference_month": reference_month,
        "issued_date": datetime.now().strftime("%B %d, %Y"),
        "total_articles": len(articles),
        "executive_summary": executive_summary,
        "key_events": key_events,
        "sectors": ordered_sectors,
        "empty_sectors": empty_sectors,
        "naics_map": naics_map,
    }


def render_html(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("newsletter.html")
    return template.render(**context)


def render_text(context: dict) -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
    template = env.get_template("newsletter.txt")
    return template.render(**context)


def generate(reference_month: str) -> tuple[str, str]:
    """Return (html_content, text_content) for the newsletter."""
    print(f"\n[newsletter] Building newsletter for {reference_month}...")
    context = build_newsletter_context(reference_month)
    html = render_html(context)
    text = render_text(context)
    print(f"[newsletter] Rendered. {context['total_articles']} articles, "
          f"{len(context['sectors'])} active sectors.")
    return html, text
