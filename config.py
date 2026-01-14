# ==================== 配置模块 ====================
import json
import random
import re
import string
import sys
from datetime import datetime
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

# ==================== 配置加载日志 ====================
# 由于 config.py 在 logger.py 之前加载，使用简单的打印函数记录错误
# 这些错误会在程序启动时显示

_config_errors = []  # 存储配置加载错误，供后续日志记录


def _log_config(level: str, source: str, message: str, details: str = None):
    """记录配置加载日志 (启动时使用)

    Args:
        level: 日志级别 (INFO/WARNING/ERROR)
        source: 配置来源
        message: 消息
        details: 详细信息
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] [{level}] 配置 [{source}]: {message}"
    if details:
        full_msg += f" - {details}"

    # 打印到控制台
    if level == "ERROR":
        print(f"\033[91m{full_msg}\033[0m", file=sys.stderr)
    elif level == "WARNING":
        print(f"\033[93m{full_msg}\033[0m", file=sys.stderr)
    else:
        print(full_msg)

    # 存储错误信息供后续使用
    if level in ("ERROR", "WARNING"):
        _config_errors.append({"level": level, "source": source, "message": message, "details": details})


def get_config_errors() -> list:
    """获取配置加载时的错误列表"""
    return _config_errors.copy()


def _load_toml() -> dict:
    """加载 TOML 配置文件"""
    if tomllib is None:
        _log_config("WARNING", "config.toml", "tomllib 未安装", "请安装 tomli: pip install tomli")
        return {}

    if not CONFIG_FILE.exists():
        _log_config("WARNING", "config.toml", "配置文件不存在", str(CONFIG_FILE))
        return {}

    try:
        with open(CONFIG_FILE, "rb") as f:
            config = tomllib.load(f)
            _log_config("INFO", "config.toml", "配置文件加载成功")
            return config
    except tomllib.TOMLDecodeError as e:
        _log_config("ERROR", "config.toml", "TOML 解析错误", str(e))
        return {}
    except PermissionError:
        _log_config("ERROR", "config.toml", "权限不足，无法读取配置文件")
        return {}
    except Exception as e:
        _log_config("ERROR", "config.toml", "加载失败", f"{type(e).__name__}: {e}")
        return {}


def _load_teams() -> list:
    """加载 Team 配置文件"""
    if not TEAM_JSON_FILE.exists():
        _log_config("WARNING", "team.json", "Team 配置文件不存在", str(TEAM_JSON_FILE))
        return []

    try:
        with open(TEAM_JSON_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            teams = data if isinstance(data, list) else [data]
            _log_config("INFO", "team.json", f"加载了 {len(teams)} 个 Team 配置")
            return teams
    except json.JSONDecodeError as e:
        _log_config("ERROR", "team.json", "JSON 解析错误", str(e))
        return []
    except PermissionError:
        _log_config("ERROR", "team.json", "权限不足，无法读取配置文件")
        return []
    except Exception as e:
        _log_config("ERROR", "team.json", "加载失败", f"{type(e).__name__}: {e}")
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

# 邮箱系统选择
EMAIL_PROVIDER = _cfg.get("email_provider", "cloudmail")  # "cloudmail" 或 "gptmail"

# Cloud Mail 邮箱系统
_email = _cfg.get("email", {})
EMAIL_API_BASE = _email.get("api_base", "")
EMAIL_API_AUTH = _email.get("api_auth", "")
EMAIL_DOMAINS = _email.get("domains", []) or ([_email["domain"]] if _email.get("domain") else [])
EMAIL_DOMAIN = EMAIL_DOMAINS[0] if EMAIL_DOMAINS else ""
EMAIL_ROLE = _email.get("role", "gpt-team")
EMAIL_WEB_URL = _email.get("web_url", "")

# GPTMail 临时邮箱配置
_gptmail = _cfg.get("gptmail", {})
GPTMAIL_API_BASE = _gptmail.get("api_base", "https://mail.chatgpt.org.uk")
GPTMAIL_API_KEY = _gptmail.get("api_key", "gpt-test")
GPTMAIL_PREFIX = _gptmail.get("prefix", "")
GPTMAIL_DOMAINS = _gptmail.get("domains", [])


# ==================== 域名黑名单管理 ====================
BLACKLIST_FILE = BASE_DIR / "domain_blacklist.json"
_domain_blacklist = set()


def _load_blacklist() -> set:
    """加载域名黑名单"""
    if not BLACKLIST_FILE.exists():
        return set()
    try:
        with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("domains", []))
    except Exception:
        return set()


def _save_blacklist():
    """保存域名黑名单"""
    try:
        with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"domains": list(_domain_blacklist)}, f, indent=2)
    except Exception:
        pass


def add_domain_to_blacklist(domain: str):
    """将域名加入黑名单"""
    global _domain_blacklist
    if domain and domain not in _domain_blacklist:
        _domain_blacklist.add(domain)
        _save_blacklist()
        return True
    return False


def is_domain_blacklisted(domain: str) -> bool:
    """检查域名是否在黑名单中"""
    return domain in _domain_blacklist


def get_domain_from_email(email: str) -> str:
    """从邮箱地址提取域名"""
    if "@" in email:
        return email.split("@")[1]
    return ""


def is_email_blacklisted(email: str) -> bool:
    """检查邮箱域名是否在黑名单中"""
    domain = get_domain_from_email(email)
    return is_domain_blacklisted(domain)


# 启动时加载黑名单
_domain_blacklist = _load_blacklist()


def get_random_gptmail_domain() -> str:
    """随机获取一个 GPTMail 可用域名 (排除黑名单)"""
    available = [d for d in GPTMAIL_DOMAINS if d not in _domain_blacklist]
    if available:
        return random.choice(available)
    return ""


# CRS
_crs = _cfg.get("crs", {})
CRS_API_BASE = _crs.get("api_base", "")
CRS_ADMIN_TOKEN = _crs.get("admin_token", "")
CRS_INCLUDE_TEAM_OWNERS = _crs.get("include_team_owners", False)

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
