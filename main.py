#!/usr/bin/env python3
"""
SEPH Newsletter Generator — CLI entry point

Usage:
  python main.py run    --month 2026-04   # Full pipeline (collect, process, save draft)
  python main.py draft  --month 2026-04   # Re-render draft from DB
  python main.py export --month 2026-04   # Export source tracking to Excel
  python main.py list                     # List all runs
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import os
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))

from config import get_default_reference_month, MIN_RELEVANCE_SCORE, LOOKBACK_DAYS


class _RateLimiter:
    def __init__(self, calls_per_minute: float = 25):
        self._interval = 60.0 / calls_per_minute
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self):
        with self._lock:
            now = _time.monotonic()
            if now < self._next_allowed:
                _time.sleep(self._next_allowed - now)
            self._next_allowed = _time.monotonic() + self._interval


from src.database import (
    init_db, insert_article, update_processed_fields,
    create_newsletter_run, update_newsletter_run,
    export_to_excel, list_runs, get_unprocessed_articles,
)
from src.collector import collect_all
from src.newsletter import generate


def _save_draft(html: str, text: str, month: str) -> tuple[str, str]:
    output_dir = os.path.dirname(os.path.abspath(__file__))
    slug = month.replace("-", "_")
    html_path = os.path.join(output_dir, f"newsletter_{slug}.html")
    txt_path = os.path.join(output_dir, f"newsletter_{slug}.txt")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    return html_path, txt_path


def cmd_run(month: str, skip_collection: bool = False, languages: list = None):
    print(f"\n{'='*60}")
    print(f"  SEPH Newsletter Pipeline — Reference Month: {month}")
    print(f"{'='*60}")

    init_db()
    run_id = create_newsletter_run(month)
    print(f"[main] Newsletter run created (id={run_id})")

    if skip_collection:
        print("[main] Skipping collection — loading unprocessed articles from DB.")
        pending = get_unprocessed_articles(month)
        inserted_ids = [(row["id"], row) for row in pending]
        print(f"[main] Found {len(inserted_ids)} unprocessed articles in DB.")
    else:
        articles = collect_all(month, lookback_days=LOOKBACK_DAYS,
                               languages=languages or ["en", "fr"])
        inserted_ids = []
        duplicates = 0
        for article in articles:
            article_id = insert_article(article)
            if article_id is not None:
                inserted_ids.append((article_id, article))
            else:
                duplicates += 1
        print(f"[main] Inserted {len(inserted_ids)} new articles ({duplicates} duplicates skipped).")
        update_newsletter_run(run_id, {"articles_collected": len(inserted_ids)})

    if inserted_ids:
        from src.processor import process_article
        from groq import Groq
        from config import GROQ_API_KEY, GROQ_MODEL

        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set.")

        client = Groq(api_key=GROQ_API_KEY)
        total = len(inserted_ids)
        print(f"\n[processor] Processing {total} articles with Groq ({GROQ_MODEL})...")

        limiter = _RateLimiter(calls_per_minute=25)
        _proc_start = _time.monotonic()

        def _process_one(args):
            idx, article_id, article = args
            limiter.wait()
            elapsed = _time.monotonic() - _proc_start
            print(f"  [{idx}/{total}] (+{elapsed:.0f}s) {article.get('headline', '')[:65]}")
            enriched = process_article(article, client)
            fields = {
                "summary": enriched.get("summary", ""),
                "naics_code": enriched.get("naics_code", "UNCLEAR"),
                "naics_sector": enriched.get("naics_sector", ""),
                "event_type": enriched.get("event_type", "Other"),
                "employer": enriched.get("employer", "Not specified"),
                "province": enriched.get("province", "Not specified"),
                "impact_direction": enriched.get("impact_direction", "Uncertain"),
                "workers_affected": enriched.get("workers_affected"),
                "relevance_score": enriched.get("relevance_score", 1),
                "relevance_justification": enriched.get("relevance_justification", ""),
                "included_in_newsletter": enriched.get("included_in_newsletter", 0),
                "exclusion_reason": enriched.get("exclusion_reason", ""),
                "classified_by": enriched.get("classified_by", "automated"),
                "newsletter_run_id": run_id,
            }
            update_processed_fields(article_id, fields)
            return fields["included_in_newsletter"]

        tasks = [(i, article_id, article) for i, (article_id, article) in enumerate(inserted_ids, 1)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(_process_one, tasks))

        included_count = sum(results)
        print(f"[processor] Done. {included_count}/{total} articles marked for newsletter.")
    else:
        print("[main] No articles to process.")
        included_count = 0

    html, text = generate(month)
    html_path, _ = _save_draft(html, text, month)
    print(f"[main] Draft saved: {html_path}")

    update_newsletter_run(run_id, {"articles_included": included_count, "status": "draft"})
    print(f"\n[main] Pipeline complete for {month}.")


def cmd_draft(month: str):
    init_db()
    html, text = generate(month)
    html_path, _ = _save_draft(html, text, month)
    print(f"[main] Draft saved: {html_path}")


def cmd_export(month: str):
    init_db()
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"seph_source_tracking_{month.replace('-', '_')}.xlsx",
    )
    export_to_excel(month, output_path)


def cmd_list():
    init_db()
    runs = list_runs()
    if not runs:
        print("No newsletter runs found.")
        return
    print(f"\n{'ID':<5} {'Reference Month':<18} {'Status':<12} {'Collected':<12} {'Included':<10} {'Run Date'}")
    print("-" * 75)
    for r in runs:
        print(
            f"{r['id']:<5} {r['reference_month']:<18} {r['status']:<12} "
            f"{r['articles_collected'] or 0:<12} {r['articles_included'] or 0:<10} "
            f"{(r['run_date'] or '')[:19]}"
        )


def main():
    parser = argparse.ArgumentParser(description="SEPH Newsletter Generator")
    subparsers = parser.add_subparsers(dest="command")

    p_run = subparsers.add_parser("run", help="Full pipeline: collect, process, save draft")
    p_run.add_argument("--month", default=None)
    p_run.add_argument("--no-collect", action="store_true")
    p_run.add_argument("--languages", default="en,fr")

    p_draft = subparsers.add_parser("draft", help="Re-render draft from DB")
    p_draft.add_argument("--month", default=None)

    p_export = subparsers.add_parser("export", help="Export source tracking to Excel")
    p_export.add_argument("--month", default=None)

    subparsers.add_parser("list", help="List all newsletter runs")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return

    month = getattr(args, "month", None) or get_default_reference_month()

    if args.command == "run":
        langs = [l.strip() for l in args.languages.split(",") if l.strip()]
        cmd_run(month, skip_collection=args.no_collect, languages=langs)
    elif args.command == "draft":
        cmd_draft(month)
    elif args.command == "export":
        cmd_export(month)
    elif args.command == "list":
        cmd_list()


if __name__ == "__main__":
    main()
