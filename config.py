# ==================== 配置模块 ====================
import json
import random
import re
import string
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

# ==================== 路径 ====================
BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.toml"
TEAM_JSON_FILE = BASE_DIR / "team.json"


def _load_toml() -> dict:
    if not CONFIG_FILE.exists() or tomllib is None:
        return {}
    try:
        with open(CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _load_teams() -> list:
    if not TEAM_JSON_FILE.exists():
        return []
    try:
        with open(TEAM_JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else [data]
    except Exception:
        return []


# ==================== 加载配置 ====================
_cfg = _load_toml()
_raw_teams = _load_teams()

# 转换 team.json 格式为 team_service.py 期望的格式
TEAMS = []
for i, t in enumerate(_raw_teams):
    TEAMS.append({
        "name": t.get("user", {}).get("email", f"Team{i+1}").split("@")[0],
        "account_id": t.get("account", {}).get("id", ""),
        "org_id": t.get("account", {}).get("organizationId", ""),
        "auth_token": t.get("accessToken", ""),
        "raw": t  # 保留原始数据
    })

# 邮箱
_email = _cfg.get("email", {})
EMAIL_API_BASE = _email.get("api_base", "")
EMAIL_API_AUTH = _email.get("api_auth", "")
EMAIL_DOMAINS = _email.get("domains", []) or ([_email["domain"]] if _email.get("domain") else [])
EMAIL_DOMAIN = EMAIL_DOMAINS[0] if EMAIL_DOMAINS else ""
EMAIL_ROLE = _email.get("role", "gpt-team")
EMAIL_WEB_URL = _email.get("web_url", "")

# CRS
_crs = _cfg.get("crs", {})
CRS_API_BASE = _crs.get("api_base", "")
CRS_ADMIN_TOKEN = _crs.get("admin_token", "")

# 账号
_account = _cfg.get("account", {})
DEFAULT_PASSWORD = _account.get("default_password", "kfcvivo50")
ACCOUNTS_PER_TEAM = _account.get("accounts_per_team", 4)

# 注册
_reg = _cfg.get("register", {})
REGISTER_NAME = _reg.get("name", "test")
REGISTER_BIRTHDAY = _reg.get("birthday", {"year": "2000", "month": "01", "day": "01"})


def get_random_birthday() -> dict:
    """生成随机生日 (2000-2005年)"""
    year = str(random.randint(2000, 2005))
    month = str(random.randint(1, 12)).zfill(2)
    day = str(random.randint(1, 28)).zfill(2)  # 用28避免月份天数问题
    return {"year": year, "month": month, "day": day}

# 请求
_req = _cfg.get("request", {})
REQUEST_TIMEOUT = _req.get("timeout", 30)
USER_AGENT = _req.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/135.0.0.0")

# 验证码
_ver = _cfg.get("verification", {})
VERIFICATION_CODE_TIMEOUT = _ver.get("timeout", 60)
VERIFICATION_CODE_INTERVAL = _ver.get("interval", 3)
VERIFICATION_CODE_MAX_RETRIES = _ver.get("max_retries", 20)

# 浏览器
_browser = _cfg.get("browser", {})
BROWSER_WAIT_TIMEOUT = _browser.get("wait_timeout", 60)
BROWSER_SHORT_WAIT = _browser.get("short_wait", 10)

# 文件
_files = _cfg.get("files", {})
CSV_FILE = _files.get("csv_file", str(BASE_DIR / "accounts.csv"))
TEAM_TRACKER_FILE = _files.get("tracker_file", str(BASE_DIR / "team_tracker.json"))

# 代理
PROXIES = _cfg.get("proxies", [])
_proxy_index = 0


# ==================== 代理辅助函数 ====================
def get_next_proxy() -> dict:
    """轮换获取下一个代理"""
    global _proxy_index
    if not PROXIES:
        return None
    proxy = PROXIES[_proxy_index % len(PROXIES)]
    _proxy_index += 1
    return proxy


def get_random_proxy() -> dict:
    """随机获取一个代理"""
    if not PROXIES:
        return None
    return random.choice(PROXIES)


def format_proxy_url(proxy: dict) -> str:
    """格式化代理URL: socks5://user:pass@host:port"""
    if not proxy:
        return None
    p_type = proxy.get("type", "socks5")
    host = proxy.get("host", "")
    port = proxy.get("port", "")
    user = proxy.get("username", "")
    pwd = proxy.get("password", "")
    if user and pwd:
        return f"{p_type}://{user}:{pwd}@{host}:{port}"
    return f"{p_type}://{host}:{port}"


# ==================== 随机姓名列表 ====================
FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph",
    "Thomas", "Christopher", "Charles", "Daniel", "Matthew", "Anthony", "Mark",
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan",
    "Jessica", "Sarah", "Karen", "Emma", "Olivia", "Sophia", "Isabella", "Mia"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Thompson", "White",
    "Harris", "Clark", "Lewis", "Robinson", "Walker", "Young", "Allen"
]


def get_random_name() -> str:
    """获取随机外国名字"""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    return f"{first} {last}"


# ==================== 浏览器指纹 ====================
FINGERPRINTS = [
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "platform": "Win32",
        "webgl_vendor": "Google Inc. (NVIDIA)",
        "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
        "language": "en-US",
        "timezone": "America/New_York",
        "screen": {"width": 1920, "height": 1080}
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "platform": "Win32",
        "webgl_vendor": "Google Inc. (AMD)",
        "webgl_renderer": "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0)",
        "language": "en-US",
        "timezone": "America/Los_Angeles",
        "screen": {"width": 2560, "height": 1440}
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "platform": "MacIntel",
        "webgl_vendor": "Google Inc. (Apple)",
        "webgl_renderer": "ANGLE (Apple, Apple M1 Pro, OpenGL 4.1)",
        "language": "en-US",
        "timezone": "America/Chicago",
        "screen": {"width": 1728, "height": 1117}
    },
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "platform": "Win32",
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)",
        "language": "en-GB",
        "timezone": "Europe/London",
        "screen": {"width": 1920, "height": 1200}
    }
]


def get_random_fingerprint() -> dict:
    """随机获取一个浏览器指纹"""
    return random.choice(FINGERPRINTS)


# ==================== 邮箱辅助函数 ====================
def get_random_domain() -> str:
    return random.choice(EMAIL_DOMAINS) if EMAIL_DOMAINS else EMAIL_DOMAIN


def generate_random_email(prefix_len: int = 8) -> str:
    prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=prefix_len))
    return f"{prefix}oaiteam@{get_random_domain()}"


def generate_email_for_user(username: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9]', '', username.lower())[:20]
    return f"{safe}oaiteam@{get_random_domain()}"


def get_team(index: int = 0) -> dict:
    return TEAMS[index] if 0 <= index < len(TEAMS) else {}


def get_team_by_email(email: str) -> dict:
    return next((t for t in TEAMS if t.get("user", {}).get("email") == email), {})


def get_team_by_org(org_id: str) -> dict:
    return next((t for t in TEAMS if t.get("account", {}).get("organizationId") == org_id), {})
