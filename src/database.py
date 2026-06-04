import sqlite3
import hashlib
import json
import os
from datetime import datetime
from typing import Optional
import pandas as pd
from config import DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash              TEXT UNIQUE NOT NULL,
                url                   TEXT,
                headline              TEXT,
                source_name           TEXT,
                published_date        TEXT,
                collected_date        TEXT,
                reference_month       TEXT,
                description           TEXT,
                language              TEXT DEFAULT 'en',

                summary               TEXT,
                naics_code            TEXT,
                naics_sector          TEXT,
                province              TEXT,
                event_type            TEXT,
                employer              TEXT,
                impact_direction      TEXT,
                workers_affected      INTEGER,
                relevance_score       INTEGER,
                relevance_justification TEXT,

                included_in_newsletter INTEGER DEFAULT 0,
                exclusion_reason      TEXT,
                analyst_notes         TEXT,
                classified_by         TEXT DEFAULT 'automated',
                review_date           TEXT,
                newsletter_run_id     INTEGER,

                FOREIGN KEY (newsletter_run_id) REFERENCES newsletter_runs(id)
            );

            CREATE TABLE IF NOT EXISTS newsletter_runs (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_month      TEXT NOT NULL,
                run_date             TEXT,
                articles_collected   INTEGER DEFAULT 0,
                articles_included    INTEGER DEFAULT 0,
                status               TEXT DEFAULT 'draft',
                sent_date            TEXT,
                recipients           TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_articles_reference_month
                ON articles(reference_month);
            CREATE INDEX IF NOT EXISTS idx_articles_naics
                ON articles(naics_code);
            CREATE INDEX IF NOT EXISTS idx_articles_relevance
                ON articles(relevance_score);
        """)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def insert_article(article: dict) -> Optional[int]:
    """Insert article; return row id or None if duplicate."""
    h = url_hash(article.get("url", article.get("headline", "")))
    try:
        with _connect() as conn:
            cur = conn.execute(
                """INSERT INTO articles
                   (url_hash, url, headline, source_name, published_date,
                    collected_date, reference_month, description, language)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    h,
                    article.get("url", ""),
                    article.get("headline", ""),
                    article.get("source_name", ""),
                    article.get("published_date", ""),
                    datetime.utcnow().isoformat(),
                    article.get("reference_month", ""),
                    article.get("description", ""),
                    article.get("language", "en"),
                ),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None  # duplicate


def update_processed_fields(article_id: int, fields: dict):
    allowed = {
        "summary", "naics_code", "naics_sector", "province", "event_type",
        "employer", "impact_direction", "workers_affected", "relevance_score",
        "relevance_justification", "included_in_newsletter", "exclusion_reason",
        "analyst_notes", "classified_by", "review_date", "newsletter_run_id",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        conn.execute(
            f"UPDATE articles SET {cols} WHERE id = ?",
            list(updates.values()) + [article_id],
        )


def get_unprocessed_articles(reference_month: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE reference_month = ?
                 AND (naics_code IS NULL OR naics_code = '')
               ORDER BY id""",
            (reference_month,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_articles_for_month(reference_month: str, min_score: int = 1) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE reference_month = ?
                 AND relevance_score >= ?
                 AND included_in_newsletter = 1
               ORDER BY naics_code, relevance_score DESC""",
            (reference_month, min_score),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_articles_for_month(reference_month: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE reference_month = ? ORDER BY relevance_score DESC",
            (reference_month,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_newsletter_run(reference_month: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO newsletter_runs (reference_month, run_date, status) VALUES (?, ?, 'draft')",
            (reference_month, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def update_newsletter_run(run_id: int, fields: dict):
    allowed = {"articles_collected", "articles_included", "status", "sent_date", "recipients"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    cols = ", ".join(f"{k} = ?" for k in updates)
    with _connect() as conn:
        conn.execute(
            f"UPDATE newsletter_runs SET {cols} WHERE id = ?",
            list(updates.values()) + [run_id],
        )


def export_to_excel(reference_month: str, output_path: str):
    articles = get_all_articles_for_month(reference_month)
    if not articles:
        print(f"No articles found for {reference_month}.")
        return

    columns_ordered = [
        "reference_month", "naics_code", "naics_sector", "province",
        "event_type", "employer", "headline", "summary",
        "impact_direction", "workers_affected", "source_name", "url",
        "published_date", "relevance_score", "relevance_justification",
        "included_in_newsletter", "exclusion_reason", "analyst_notes",
        "classified_by", "review_date",
    ]
    df = pd.DataFrame(articles)
    for col in columns_ordered:
        if col not in df.columns:
            df[col] = ""
    df = df[columns_ordered]

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Source Tracking", index=False)
        worksheet = writer.sheets["Source Tracking"]
        for col in worksheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            worksheet.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    print(f"Exported {len(articles)} articles to {output_path}")


def list_runs() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM newsletter_runs ORDER BY run_date DESC"
        ).fetchall()
    return [dict(r) for r in rows]
