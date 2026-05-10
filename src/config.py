import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "700"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
TOP_K = int(os.getenv("TOP_K", "5"))
MERGE_SIM_THRESHOLD = float(os.getenv("MERGE_SIM_THRESHOLD", "0.82"))
FAST_MODE_MAX_PAGES = int(os.getenv("FAST_MODE_MAX_PAGES_PER_BOOK", "60"))
FAST_MODE_MAX_CHAPTERS = int(os.getenv("FAST_MODE_MAX_CHAPTERS_PER_BOOK", "8"))
