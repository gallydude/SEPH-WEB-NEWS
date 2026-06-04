import os
from datetime import date
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

load_dotenv(override=True)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
GROQ_MODEL = "llama-3.1-8b-instant"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "seph_articles.db")
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

MIN_RELEVANCE_SCORE = 2
LOOKBACK_DAYS = 14
MAX_ARTICLES_PER_QUERY = 10
REQUEST_DELAY_SECONDS = 1.0


def get_default_reference_month() -> str:
    prior = date.today().replace(day=1) - relativedelta(months=1)
    return prior.strftime("%Y-%m")
