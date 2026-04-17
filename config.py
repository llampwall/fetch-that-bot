import os
import re
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("FETCH_BOT_TOKEN", "")
WEBHOOK_URL = os.environ.get("FETCH_WEBHOOK_URL", "")  # e.g. https://yourtunnel.com/webhook/fetch
WEBHOOK_PATH = "/webhook/fetch"
WEBHOOK_PORT = int(os.environ.get("FETCH_WEBHOOK_PORT", "8443"))
API_PORT = int(os.environ.get("FETCH_API_PORT", "8444"))
TEMP_DIR = os.environ.get("FETCH_TEMP_DIR", os.path.join(os.path.dirname(__file__), "tmp"))
COOKIES_FILE = os.environ.get("FETCH_COOKIES_FILE", os.path.join(os.path.dirname(__file__), "cookies.txt"))

# Max file size Telegram bots can upload (50MB)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# URL patterns for supported platforms
URL_PATTERNS = re.compile(
    r"https?://(?:www\.)?"
    r"(?:"
    r"instagram\.com/(?:p|reel|reels|stories)/[\w\-]+"
    r"|(?:x\.com|twitter\.com)/\w+/status/\d+"
    r"|tiktok\.com/@[\w.]+/video/\d+"
    r"|(?:vm\.)?tiktok\.com/[\w]+"
    r"|(?:m\.)?youtube\.com/(?:watch\?[\w=&]+|shorts/[\w\-]+)"
    r"|youtu\.be/[\w\-]+"
    r"|(?:old\.)?reddit\.com/r/\w+/(?:comments|s)/[\w]+"
    r"|v\.redd\.it/[\w]+"
    r"|i\.redd\.it/[\w.]+"
    r"|threads\.(?:net|com)/(?:@[\w.]+/post|t)/[\w]+"
    r")"
    r"[/\w\-\?=&%.]*",
    re.IGNORECASE,
)

PLATFORM_MAP = {
    "instagram.com": "Instagram",
    "x.com": "X",
    "twitter.com": "X",
    "tiktok.com": "TikTok",
    "vm.tiktok.com": "TikTok",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "m.youtube.com": "YouTube",
    "reddit.com": "Reddit",
    "old.reddit.com": "Reddit",
    "v.redd.it": "Reddit",
    "i.redd.it": "Reddit",
    "threads.net": "Threads",
    "threads.com": "Threads",
}


def detect_platform(url: str) -> str:
    """Extract platform name from a URL."""
    for domain, name in PLATFORM_MAP.items():
        if domain in url.lower():
            return name
    return "Unknown"
