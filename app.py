import streamlit as st
import subprocess
import sys
import os
import re
import time as _t
from datetime import date
from dateutil.relativedelta import relativedelta
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

def _subprocess_env() -> dict:
    """Build env dict for subprocesses, merging OS env with Streamlit secrets."""
    env = os.environ.copy()
    try:
        for key in ["GROQ_API_KEY", "NEWS_API_KEY"]:
            if key in st.secrets:
                env[key] = str(st.secrets[key])
    except Exception:
        pass
    return env


# On Streamlit Cloud there is no .env file — write one from st.secrets so
# config.py's load_dotenv() picks it up in subprocesses.
_env_path = os.path.join(BASE_DIR, ".env")
if not os.path.exists(_env_path):
    try:
        lines = []
        for _key in ["GROQ_API_KEY", "NEWS_API_KEY"]:
            if _key in st.secrets:
                lines.append(f'{_key}={st.secrets[_key]}')
        if lines:
            with open(_env_path, "w") as _f:
                _f.write("\n".join(lines) + "\n")
    except Exception:
        pass

st.set_page_config(
    page_title="CLMI Newsletter Generator",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root {
    --navy:       #1B2A4A;
    --navy-mid:   #243556;
    --navy-dark:  #111E35;
    --teal:       #0EA5C9;
    --teal-light: #38BDF8;
    --slate:      #475569;
    --slate-light:#94A3B8;
    --bg:         #EFF3F8;
    --surface:    #FFFFFF;
    --border:     #E2E8F0;
    --text:       #0F172A;
    --muted:      #64748B;
    --radius:     12px;
    --shadow-sm:  0 1px 3px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.04);
    --shadow:     0 4px 12px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.05);
    --shadow-lg:  0 10px 30px rgba(0,0,0,0.12), 0 4px 8px rgba(0,0,0,0.06);
}

/* ── Global font (avoid * !important — it breaks Material Icons) ── */
body, .stApp, .stMarkdown, p, span, div, label, h1, h2, h3, h4, h5, h6, button, input, select, td, th {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* ── App background ── */
[data-testid="stAppViewContainer"] { background: var(--bg); }
.main .block-container {
    padding-top: 0 !important;
    padding-bottom: 3rem;
    max-width: 1200px;
}

/* ── Hero header ── */
.page-hero {
    background: linear-gradient(135deg, #111E35 0%, #1B2A4A 45%, #1a3f6e 100%);
    margin: -1rem -4rem 2.5rem -4rem;
    padding: 2.5rem 4rem 2.5rem;
    position: relative; overflow: hidden;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
.page-hero::before {
    content: '';
    position: absolute; top: -80px; right: -80px;
    width: 380px; height: 380px;
    background: radial-gradient(circle, rgba(14,165,201,0.18) 0%, transparent 65%);
    pointer-events: none;
}
.page-hero::after {
    content: '';
    position: absolute; bottom: -60px; left: 30%;
    width: 300px; height: 300px;
    background: radial-gradient(circle, rgba(56,189,248,0.08) 0%, transparent 65%);
    pointer-events: none;
}
.hero-badge {
    display: inline-flex; align-items: center; gap: 7px;
    background: rgba(14,165,201,0.15);
    border: 1px solid rgba(14,165,201,0.35);
    color: #7DD3FC;
    font-size: 10.5px; font-weight: 700;
    letter-spacing: 0.09em; text-transform: uppercase;
    padding: 5px 14px; border-radius: 100px;
    margin-bottom: 14px;
}
.hero-title {
    color: #FFFFFF !important;
    font-size: 2.1rem !important; font-weight: 800 !important;
    letter-spacing: -0.03em; line-height: 1.1;
    margin: 0 0 10px 0 !important;
}
.hero-subtitle {
    color: #94A3B8; font-size: 14px; margin: 0;
    font-weight: 400;
}
.hero-subtitle strong { color: #CBD5E1; font-weight: 600; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    min-width: 280px; max-width: 280px;
    background: var(--navy-dark) !important;
    border-right: 1px solid rgba(255,255,255,0.05);
}
[data-testid="stSidebar"] > div { background: transparent !important; }
[data-testid="stSidebar"] section { background: transparent !important; }
[data-testid="stSidebar"] label { color: #FFFFFF !important; font-size: 12px !important; font-weight: 500 !important; }
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] .stMarkdown strong { color: #CBD5E1 !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.07) !important; margin: 6px 0 !important; }
[data-testid="stSidebar"] [data-baseweb="select"] {
    background: #FFFFFF !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] * { color: #0F172A !important; }
[data-testid="stSidebar"] [data-testid="stCheckbox"] *,
[data-testid="stSidebar"] .stCheckbox * { color: #FFFFFF !important; }
[data-testid="stSidebar"] [data-baseweb="popover"] { background: #1E3158 !important; }

/* Sidebar brand */
.sidebar-brand {
    display: flex; flex-direction: column; gap: 12px;
    padding: 6px 0 22px;
}
.sidebar-logo {
    width: 100%; height: auto;
    border-radius: 10px; object-fit: contain;
    background: #FFFFFF; padding: 8px;
    display: block;
}
.sidebar-brand-title {
    color: #F1F5F9; font-size: 18px; font-weight: 800;
    letter-spacing: -0.02em; line-height: 1.1;
}
.sidebar-brand-sub {
    color: #7B96B2; font-size: 10.5px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.08em; margin-top: 2px;
}
.sidebar-section {
    color: #6B8CAE; font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.1em;
    padding: 18px 0 8px;
}
.sidebar-footer {
    border-top: 1px solid rgba(255,255,255,0.06);
    padding-top: 14px; margin-top: 4px;
}
.sidebar-footer-row {
    display: flex; align-items: center; gap: 8px;
    padding: 4px 0; color: #7B96B2; font-size: 11.5px; font-weight: 500;
}
.sidebar-footer-row span { color: #94A3B8; }

/* ── Metric cards ── */
div[data-testid="metric-container"] {
    background: var(--surface);
    padding: 20px 22px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    border-top: 3px solid var(--navy);
    box-shadow: var(--shadow-sm);
    transition: transform 0.18s ease, box-shadow 0.18s ease;
}
div[data-testid="metric-container"]:hover {
    transform: translateY(-3px);
    box-shadow: var(--shadow);
}
div[data-testid="metric-container"] [data-testid="stMetricLabel"] {
    font-size: 11px !important; font-weight: 700 !important;
    text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted) !important;
}
div[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: var(--navy) !important; font-weight: 800 !important; font-size: 2rem !important;
    letter-spacing: -0.02em;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: var(--surface); border-radius: var(--radius);
    padding: 5px; gap: 3px;
    border: 1px solid var(--border); box-shadow: var(--shadow-sm);
}
.stTabs [data-baseweb="tab"] {
    font-size: 13px; font-weight: 600; padding: 9px 24px;
    border-radius: 9px; color: var(--slate);
    background: transparent; border: none;
    transition: all 0.15s ease;
}
.stTabs [data-baseweb="tab"]:hover:not([aria-selected="true"]) {
    background: #F1F5F9; color: var(--navy);
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, var(--navy) 0%, #243E6E 100%) !important;
    color: #FFFFFF !important;
    box-shadow: 0 2px 10px rgba(27,42,74,0.35);
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none; }

/* ── Buttons ── */
.stButton > button, .stDownloadButton > button {
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important; border-radius: 9px !important;
    transition: all 0.18s ease !important; letter-spacing: -0.01em !important;
}
.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1B2A4A 0%, #243E6E 100%) !important;
    border: none !important;
    box-shadow: 0 2px 10px rgba(27,42,74,0.3) !important;
}
.stButton > button[kind="primary"]:hover { transform: translateY(-2px) !important; box-shadow: 0 6px 18px rgba(27,42,74,0.4) !important; }
.stButton > button:not([kind="primary"]) {
    background: var(--surface) !important; border: 1.5px solid var(--border) !important; color: var(--slate) !important;
}
.stButton > button:not([kind="primary"]):hover { border-color: var(--navy) !important; color: var(--navy) !important; transform: translateY(-1px) !important; }

/* ── Progress bar ── */
.stProgress > div > div { background: #E2E8F0 !important; border-radius: 100px; height: 8px !important; }
.stProgress > div > div > div { background: linear-gradient(90deg, #1B2A4A, #0EA5C9) !important; border-radius: 100px; transition: width 0.4s ease; }

/* ── Expanders ── */
[data-testid="stExpander"] {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow-sm);
}
[data-testid="stExpander"] summary { font-weight: 600 !important; font-size: 13px !important; }

/* ── Alerts ── */
[data-testid="stAlert"] { border-radius: var(--radius) !important; border: none !important; box-shadow: var(--shadow-sm) !important; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
    border-radius: var(--radius) !important; overflow: hidden;
    box-shadow: var(--shadow-sm); border: 1px solid var(--border) !important;
}

/* ── Typography ── */
h1 { color: var(--navy) !important; font-weight: 800 !important; letter-spacing: -0.03em; }
h2 { color: var(--navy) !important; font-weight: 700 !important; }
h3 { color: #1E3358 !important; font-weight: 600 !important; }
hr { border-color: var(--border) !important; }
[data-testid="stCaption"] { color: var(--muted) !important; font-size: 12px !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_month_options(n: int = 36) -> list[tuple[str, str]]:
    options = []
    d = date.today().replace(day=1)
    for _ in range(n):
        options.append((d.strftime("%B %Y"), d.strftime("%Y-%m")))
        d -= relativedelta(months=1)
    return options


def is_past_month(month: str) -> bool:
    return month < date.today().strftime("%Y-%m")


def has_committed_newsletter(month: str) -> bool:
    """True if a newsletter HTML was committed to newsletters/ by GitHub Actions."""
    slug = month.replace("-", "_")
    return os.path.exists(os.path.join(BASE_DIR, "newsletters", f"newsletter_{slug}.html"))


def has_newsletter_data(month: str) -> bool:
    """True if the local DB has processed articles for this month."""
    try:
        from src.database import init_db, _connect
        init_db()
        with _connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE reference_month = ? AND included_in_newsletter = 1",
                (month,),
            ).fetchone()[0]
        return count > 0
    except Exception:
        return False


def load_articles(month: str) -> pd.DataFrame:
    from src.database import init_db, _connect
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM articles WHERE reference_month = ? ORDER BY relevance_score DESC, naics_code",
            (month,),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def load_newsletter_html(month: str) -> str:
    slug = month.replace("-", "_")
    # Check committed newsletters/ folder first (auto-generated by GitHub Actions)
    for path in [
        os.path.join(BASE_DIR, "newsletters", f"newsletter_{slug}.html"),
        os.path.join(BASE_DIR, f"newsletter_{slug}.html"),
    ]:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return ""


def run_subprocess(cmd: list[str]) -> tuple[int, str]:
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=BASE_DIR,
        env=_subprocess_env(),
    )
    return result.returncode, result.stdout + result.stderr


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <img src="https://tse1.mm.bing.net/th/id/OIP.zlgVzPGAKRwJC7QbfljDKgHaA0?r=0&rs=1&pid=ImgDetMain&o=7&rm=3"
             class="sidebar-logo" alt="Logo">
        <div>
            <div class="sidebar-brand-title">CLMI</div>
            <div class="sidebar-brand-sub">Newsletter Generator</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    st.markdown('<div class="sidebar-section">Reference Month</div>', unsafe_allow_html=True)
    month_options = get_month_options(36)
    month_labels = [o[0] for o in month_options]
    month_values = [o[1] for o in month_options]
    idx = st.selectbox(
        "Month", range(len(month_labels)),
        format_func=lambda i: month_labels[i],
        label_visibility="collapsed",
    )
    selected_month = month_values[idx]
    selected_label = month_labels[idx]

    st.markdown('<div class="sidebar-section">Languages</div>', unsafe_allow_html=True)
    col_en, col_fr = st.columns(2)
    with col_en:
        inc_en = st.checkbox("🇨🇦 English", value=True)
    with col_fr:
        inc_fr = st.checkbox("🇫🇷 French", value=True)

    st.divider()
    st.markdown("""
    <div class="sidebar-footer">
        <div class="sidebar-footer-row">⚡ <span>GPT OSS 20B · Groq</span></div>
        <div class="sidebar-footer-row">📡 <span>Google News RSS · NewsAPI</span></div>
    </div>
    """, unsafe_allow_html=True)


# ── Page header ───────────────────────────────────────────────────────────────

st.markdown(f"""
<div class="page-hero">
    <div class="hero-badge">🇨🇦 Statistics Canada · Labour Market Program</div>
    <div class="hero-title">CLMI Labour Market Intelligence</div>
    <p class="hero-subtitle">Reference period: <strong>{selected_label}</strong></p>
</div>
""", unsafe_allow_html=True)

tab_run, tab_articles, tab_preview = st.tabs([
    "▶  Run Pipeline", "📊  Articles", "📄  Preview & Download",
])


# ── Tab 1: Run Pipeline ───────────────────────────────────────────────────────

with tab_run:
    st.markdown("### Generate Newsletter")

    _committed = has_committed_newsletter(selected_month)
    _past_with_data = not _committed and is_past_month(selected_month) and has_newsletter_data(selected_month)

    if _committed:
        st.info(
            f"**{selected_label}** was generated automatically. "
            "Open the **Preview & Download** tab to view and download it."
        )
        html = load_newsletter_html(selected_month)
        if html:
            st.session_state["newsletter_html"] = html
            st.session_state["newsletter_month"] = selected_month
        col_dl, col_rerun = st.columns([1, 1])
        with col_dl:
            if html:
                st.download_button(
                    label="⬇  Download newsletter HTML",
                    data=html,
                    file_name=f"seph_newsletter_{selected_month}.html",
                    mime="text/html",
                    type="primary",
                    use_container_width=True,
                    key="download_load_tab",
                )
        with col_rerun:
            run_btn = st.button("↺  Re-run full pipeline", use_container_width=True,
                                help="Collects fresh articles and overwrites the existing newsletter.")
        load_btn = False
    elif _past_with_data:
        st.info(
            f"**{selected_label}** is a past month with existing data in the database. "
            "Loading from the database is instant — no need to re-run the pipeline."
        )
        col_load, col_rerun = st.columns([1, 1])
        with col_load:
            load_btn = st.button("⚡  Load from database", type="primary", use_container_width=True)
        with col_rerun:
            run_btn = st.button("↺  Re-run full pipeline", use_container_width=True,
                                help="Overwrites existing data by collecting fresh articles.")
    else:
        load_btn = False
        col_btn, col_skip = st.columns([1, 2])
        with col_btn:
            run_btn = st.button("▶  Run Full Pipeline", type="primary", use_container_width=True)
        with col_skip:
            no_collect = st.checkbox("Skip collection — reprocess articles already in the database")

    if not _committed and not _past_with_data and not inc_en and not inc_fr:
        st.warning("Select at least one language in the sidebar before running.")

    # ── Fast path: load from DB ───────────────────────────────────────────────
    if load_btn:
        with st.spinner(f"Rendering {selected_label} from database…"):
            rc, out = run_subprocess([sys.executable, "main.py", "draft", "--month", selected_month])
        if rc == 0:
            html = load_newsletter_html(selected_month)
            if html:
                st.session_state["newsletter_html"] = html
                st.session_state["newsletter_month"] = selected_month
                st.success(f"Newsletter for **{selected_label}** loaded from database.")
                st.download_button(
                    label="⬇  Download newsletter HTML",
                    data=html,
                    file_name=f"seph_newsletter_{selected_month}.html",
                    mime="text/html",
                    type="primary",
                    use_container_width=True,
                    key="download_load_tab",
                )
                st.caption("You can also preview it in the **Preview & Download** tab.")
        else:
            st.error(out)

    # ── Full pipeline ─────────────────────────────────────────────────────────
    if run_btn and (_past_with_data or inc_en or inc_fr):
        langs = (["en"] if inc_en else []) + (["fr"] if inc_fr else []) if not _past_with_data else ["en", "fr"]
        no_collect_flag = (not _past_with_data) and no_collect
        cmd = [sys.executable, "main.py", "run", "--month", selected_month,
               "--languages", ",".join(langs)]
        if no_collect_flag:
            cmd.append("--no-collect")

        stage_label = st.empty()
        progress_bar = st.progress(0)
        elapsed_label = st.empty()
        log_box = st.expander("Pipeline log", expanded=True)

        stage_label.markdown("**Stage 1 / 3** — Collecting news articles…")

        total_articles = 0
        current_article = 0
        processing_start = None
        pipeline_start = _t.monotonic()
        success = False

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            cwd=BASE_DIR, env=_subprocess_env(),
        )

        for raw_line in proc.stdout:
            line = raw_line.rstrip()
            if not line:
                continue

            elapsed_total = _t.monotonic() - pipeline_start
            elapsed_label.caption(f"Elapsed: {int(elapsed_total // 60)}m {int(elapsed_total % 60)}s")

            with log_box:
                st.text(line)

            if "Collecting news for" in line:
                stage_label.markdown("**Stage 1 / 3** — Collecting news articles…")
                progress_bar.progress(0.05)

            elif "Total after deduplication" in line:
                m = re.search(r"(\d+) articles", line)
                n = m.group(1) if m else "?"
                stage_label.markdown(f"**Stage 1 / 3 complete** — {n} articles collected")
                progress_bar.progress(0.18)

            elif "Processing" in line and "articles with Groq" in line:
                m = re.search(r"Processing (\d+) articles", line)
                if m:
                    total_articles = int(m.group(1))
                processing_start = _t.monotonic()
                stage_label.markdown(
                    f"**Stage 2 / 3** — Classifying {total_articles} articles with AI…"
                )
                progress_bar.progress(0.20)

            elif total_articles > 0 and re.match(r"\s+\[\d+/\d+\]", line):
                m = re.search(r"\[(\d+)/(\d+)\]", line)
                if m:
                    current_article = int(m.group(1))
                    pct = 0.20 + (current_article / total_articles) * 0.65
                    progress_bar.progress(min(pct, 0.85))

                    eta_str = ""
                    if processing_start and current_article > 1:
                        elapsed = _t.monotonic() - processing_start
                        if elapsed > 0:
                            rate = current_article / elapsed
                            remaining = (total_articles - current_article) / rate
                            eta_str = f" — ~{int(remaining // 60)}m {int(remaining % 60)}s left"

                    stage_label.markdown(
                        f"**Stage 2 / 3** — Classifying articles with AI "
                        f"({current_article} / {total_articles}){eta_str}"
                    )

            elif "processor] Done" in line:
                m = re.search(r"(\d+)/(\d+) articles marked", line)
                if m:
                    inc, tot = m.group(1), m.group(2)
                    stage_label.markdown(
                        f"**Stage 2 / 3 complete** — {inc} of {tot} articles selected for newsletter"
                    )
                progress_bar.progress(0.88)

            elif "Building newsletter" in line:
                stage_label.markdown("**Stage 3 / 3** — Building newsletter…")
                progress_bar.progress(0.93)

            elif "Pipeline complete" in line:
                progress_bar.progress(1.0)
                elapsed_label.caption(f"Completed in {int(elapsed_total // 60)}m {int(elapsed_total % 60)}s")
                stage_label.markdown(f"**Done** — newsletter ready for {selected_label}")
                success = True

        proc.wait()

        if proc.returncode == 0 and success:
            html = load_newsletter_html(selected_month)
            if html:
                st.session_state["newsletter_html"] = html
                st.session_state["newsletter_month"] = selected_month
                st.success(f"Newsletter for **{selected_label}** is ready.")
                st.download_button(
                    label="⬇  Download newsletter HTML",
                    data=html,
                    file_name=f"seph_newsletter_{selected_month}.html",
                    mime="text/html",
                    type="primary",
                    use_container_width=True,
                    key="download_run_tab",
                )
                st.caption("You can also preview it in the **Preview & Download** tab.")
        else:
            progress_bar.progress(1.0)
            stage_label.markdown("**Pipeline encountered an error** — see the log above.")
            st.error("Something went wrong. Check the pipeline log.")


# ── Tab 2: Articles ───────────────────────────────────────────────────────────

with tab_articles:
    df = load_articles(selected_month)

    if df.empty:
        st.info(f"No articles for {selected_label} yet. Run the pipeline first.")
    else:
        total = len(df)
        included = int(df.get("included_in_newsletter", pd.Series([0])).sum())
        active_sectors = (
            df[df["included_in_newsletter"] == 1]["naics_code"].nunique()
            if included else 0
        )
        scores = df["relevance_score"].dropna()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Collected", total)
        c2.metric("In newsletter", included)
        c3.metric("Active sectors", active_sectors)
        c4.metric("Avg score", f"{scores.mean():.1f}" if not scores.empty else "—")

        st.divider()

        with st.expander("Filters", expanded=True):
            fc1, fc2, fc3, fc4, fc5 = st.columns(5)
            with fc1:
                show_excluded = st.checkbox("Show excluded articles", value=False)
            with fc2:
                min_score = st.slider("Min score", 1, 5, 2)
            with fc3:
                naics_opts = ["All"] + sorted(df["naics_code"].dropna().unique().tolist())
                sel_naics = st.selectbox("NAICS", naics_opts)
            with fc4:
                impact_opts = ["All"] + sorted(df["impact_direction"].dropna().unique().tolist())
                sel_impact = st.selectbox("Impact", impact_opts)
            with fc5:
                if "language" in df.columns:
                    lang_opts = ["All"] + sorted(df["language"].dropna().unique().tolist())
                    sel_lang = st.selectbox("Language", lang_opts)
                else:
                    sel_lang = "All"

        view = df.copy()
        if not show_excluded:
            view = view[view["included_in_newsletter"] == 1]
        view = view[view["relevance_score"] >= min_score]
        if sel_naics != "All":
            view = view[view["naics_code"] == sel_naics]
        if sel_impact != "All":
            view = view[view["impact_direction"] == sel_impact]
        if sel_lang != "All" and "language" in view.columns:
            view = view[view["language"] == sel_lang]

        wanted = [
            "relevance_score", "naics_code", "naics_sector", "province",
            "event_type", "employer", "headline", "impact_direction",
            "workers_affected", "source_name", "published_date",
        ]
        if "language" in view.columns:
            wanted.insert(1, "language")

        display = view[[c for c in wanted if c in view.columns]].rename(columns={
            "relevance_score": "Score", "naics_code": "NAICS",
            "naics_sector": "Sector", "province": "Province",
            "event_type": "Event", "impact_direction": "Impact",
            "workers_affected": "Workers", "source_name": "Source",
            "published_date": "Date", "language": "Lang",
        })

        st.dataframe(display, use_container_width=True, hide_index=True, height=520)
        st.caption(f"Showing {len(view)} of {total} articles")


# ── Tab 3: Preview & Download ─────────────────────────────────────────────────

with tab_preview:
    # Use session state if available (freshly generated), otherwise read from disk
    if st.session_state.get("newsletter_month") == selected_month:
        html = st.session_state.get("newsletter_html") or load_newsletter_html(selected_month)
    else:
        html = load_newsletter_html(selected_month)

    if not html:
        st.info(f"No newsletter rendered yet for {selected_label}. Run the pipeline first.")
    else:
        col_a, col_b, col_c = st.columns([2, 2, 2])

        with col_a:
            st.download_button(
                label="⬇  Download newsletter HTML",
                data=html,
                file_name=f"seph_newsletter_{selected_month}.html",
                mime="text/html",
                type="primary",
                use_container_width=True,
                key="download_preview_tab",
            )

        with col_b:
            if st.button("Re-render from database", use_container_width=True):
                rc, out = run_subprocess([sys.executable, "main.py", "draft", "--month", selected_month])
                if rc == 0:
                    st.success("Re-rendered — refresh the page to see updates.")
                else:
                    st.error(out)

        with col_c:
            if st.button("Export to Excel", use_container_width=True):
                rc, out = run_subprocess([sys.executable, "main.py", "export", "--month", selected_month])
                if rc == 0:
                    xlsx = os.path.join(BASE_DIR, f"seph_source_tracking_{selected_month.replace('-','_')}.xlsx")
                    st.success(f"Saved: {os.path.basename(xlsx)}")
                else:
                    st.error(out)

        st.divider()
        st.markdown(f"**{selected_label}** — rendered newsletter")
        st.components.v1.html(html, height=950, scrolling=True)
