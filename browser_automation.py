# ==================== 浏览器自动化模块 ====================
# 处理 OpenAI 注册、Codex 授权等浏览器自动化操作
# 使用 DrissionPage 替代 Selenium

import time
import random
import subprocess
import os
from contextlib import contextmanager
from DrissionPage import ChromiumPage, ChromiumOptions

from config import (
    BROWSER_WAIT_TIMEOUT,
    BROWSER_SHORT_WAIT,
    get_random_name,
    get_random_birthday
)
from email_service import unified_get_verification_code
from crs_service import crs_generate_auth_url, crs_exchange_code, crs_add_account, extract_code_from_url
from logger import log


# ==================== 浏览器配置常量 ====================
BROWSER_MAX_RETRIES = 3  # 浏览器启动最大重试次数
BROWSER_RETRY_DELAY = 2  # 重试间隔 (秒)
PAGE_LOAD_TIMEOUT = 15   # 页面加载超时 (秒)

# ==================== 输入速度配置 (模拟真人) ====================
SAFE_MODE = True
TYPING_DELAY = 0.12 if SAFE_MODE else 0.06
ACTION_DELAY = (1.0, 2.0) if SAFE_MODE else (0.3, 0.8)


# ==================== URL 监听与日志 ====================
_last_logged_url = None


def log_current_url(page, context: str = None, force: bool = False):
    """记录当前页面URL"""
    global _last_logged_url
    try:
        current_url = page.url
        if force or current_url != _last_logged_url:
            _last_logged_url = current_url
            url_info = _parse_url_info(current_url)

            if context:
                if url_info:
                    log.info(f"[URL] {context} | {current_url} | {url_info}")
                else:
                    log.info(f"[URL] {context} | {current_url}")
            else:
                if url_info:
                    log.info(f"[URL] {current_url} | {url_info}")
                else:
                    log.info(f"[URL] {current_url}")
    except Exception as e:
        log.warning(f"获取URL失败: {e}")


def _parse_url_info(url: str) -> str:
    """解析URL，返回页面类型描述"""
    if not url:
        return ""

    if "auth.openai.com" in url:
        if "/log-in-or-create-account" in url:
            return "登录/注册选择页"
        elif "/log-in/password" in url:
            return "密码登录页"
        elif "/create-account/password" in url:
            return "创建账号密码页"
        elif "/email-verification" in url:
            return "邮箱验证码页"
        elif "/about-you" in url:
            return "个人信息填写页"
        elif "/authorize" in url:
            return "授权确认页"
        elif "/callback" in url:
            return "回调处理页"
        else:
            return "OpenAI 认证页"
    elif "chatgpt.com" in url:
        if "/auth" in url:
            return "ChatGPT 认证页"
        else:
            return "ChatGPT 主页"
    elif "localhost:1455" in url:
        if "/auth/callback" in url:
            return "本地授权回调页"
        else:
            return "本地服务页"

    return ""


def log_url_change(page, old_url: str, action: str = None):
    """记录URL变化"""
    global _last_logged_url
    try:
        new_url = page.url
        if new_url != old_url:
            _last_logged_url = new_url
            new_info = _parse_url_info(new_url)

            if action:
                if new_info:
                    log.info(f"[URL] {action} | {new_url} | {new_info}")
                else:
                    log.info(f"[URL] {action} | {new_url}")
            else:
                if new_info:
                    log.info(f"[URL] 跳转 | {new_url} | {new_info}")
                else:
                    log.info(f"[URL] 跳转 | {new_url}")
    except Exception as e:
        log.warning(f"记录URL变化失败: {e}")


def cleanup_chrome_processes():
    """清理残留的 Chrome 进程 (Windows)"""
    try:
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq chrome.exe', '/FO', 'CSV'],
            capture_output=True, text=True, timeout=5
        )
        
        if 'chrome.exe' in result.stdout:
            subprocess.run(
                ['taskkill', '/F', '/IM', 'chromedriver.exe'],
                capture_output=True, timeout=5
            )
            log.step("已清理 chromedriver 残留进程")
    except Exception:
        pass


def init_browser(max_retries: int = BROWSER_MAX_RETRIES) -> ChromiumPage:
    """初始化 DrissionPage 浏览器 (带重试机制)"""
    log.info("初始化浏览器...", icon="browser")
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                log.warning(f"浏览器启动重试 ({attempt + 1}/{max_retries})...")
                cleanup_chrome_processes()
                time.sleep(BROWSER_RETRY_DELAY)
            
            co = ChromiumOptions()
            co.set_argument('--no-first-run')
            co.set_argument('--disable-infobars')
            co.set_argument('--incognito')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-dev-shm-usage')
            co.auto_port()
            co.set_timeouts(base=PAGE_LOAD_TIMEOUT, page_load=PAGE_LOAD_TIMEOUT * 2)

            log.step("启动 Chrome (无痕模式)...")
            page = ChromiumPage(co)
            log.success("浏览器启动成功")
            return page

        except Exception as e:
            last_error = e
            log.warning(f"浏览器启动失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            cleanup_chrome_processes()
    
    log.error(f"浏览器启动失败，已重试 {max_retries} 次: {last_error}")
    raise last_error


@contextmanager
def browser_context(max_retries: int = BROWSER_MAX_RETRIES):
    """浏览器上下文管理器"""
    page = None
    try:
        page = init_browser(max_retries)
        yield page
    finally:
        if page:
            log.step("关闭浏览器...")
            try:
                page.quit()
            except Exception as e:
                log.warning(f"浏览器关闭异常: {e}")
            finally:
                cleanup_chrome_processes()


@contextmanager
def browser_context_with_retry(max_browser_retries: int = 2):
    """带重试机制的浏览器上下文管理器"""
    ctx = BrowserRetryContext(max_browser_retries)
    try:
        yield ctx
    finally:
        ctx.cleanup()


class BrowserRetryContext:
    """浏览器重试上下文"""

    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries
        self.current_attempt = 0
        self.page = None
        self._should_continue = True

    def attempts(self):
        """生成重试迭代器"""
        for attempt in range(self.max_retries):
            if not self._should_continue:
                break

            self.current_attempt = attempt

            if attempt > 0:
                log.warning(f"重试整体流程 ({attempt + 1}/{self.max_retries})...")
                self._cleanup_page()
                cleanup_chrome_processes()
                time.sleep(2)

            try:
                self.page = init_browser()
                yield attempt
            except Exception as e:
                log.error(f"浏览器初始化失败: {e}")
                if attempt >= self.max_retries - 1:
                    raise

    def handle_error(self, error: Exception):
        """处理错误"""
        log.error(f"流程异常: {error}")
        if self.current_attempt >= self.max_retries - 1:
            self._should_continue = False
        else:
            log.warning("准备重试...")

    def stop(self):
        """停止重试"""
        self._should_continue = False

    def _cleanup_page(self):
        """清理当前页面"""
        if self.page:
            try:
                self.page.quit()
            except Exception:
                pass
            self.page = None

    def cleanup(self):
        """最终清理"""
        if self.page:
            log.step("关闭浏览器...")
            try:
                self.page.quit()
            except Exception:
                pass
            self.page = None


def wait_for_page_stable(page, timeout: int = 10, check_interval: float = 0.5) -> bool:
    """等待页面稳定"""
    start_time = time.time()
    last_html_len = 0
    stable_count = 0
    
    while time.time() - start_time < timeout:
        try:
            current_len = len(page.html)
            if current_len == last_html_len:
                stable_count += 1
                if stable_count >= 3:
                    return True
            else:
                stable_count = 0
                last_html_len = current_len
            time.sleep(check_interval)
        except Exception:
            time.sleep(check_interval)
    
    return False


def wait_for_element(page, selector: str, timeout: int = 10, visible: bool = True):
    """智能等待元素出现"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            element = page.ele(selector, timeout=1)
            if element:
                if not visible or (element.states.is_displayed if hasattr(element, 'states') else True):
                    return element
        except Exception:
            pass
        time.sleep(0.3)
    
    return None


def wait_for_url_change(page, old_url: str, timeout: int = 15, contains: str = None) -> bool:
    """等待 URL 变化"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            current_url = page.url
            if current_url != old_url:
                if contains is None or contains in current_url:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    
    return False


def type_slowly(page, selector_or_element, text, base_delay=None):
    """缓慢输入文本 (模拟真人输入)"""
    if base_delay is None:
        base_delay = TYPING_DELAY
    
    if isinstance(selector_or_element, str):
        element = page.ele(selector_or_element, timeout=10)
    else:
        element = selector_or_element

    if not text:
        return

    if len(text) <= 8:
        element.input(text, clear=True)
        return

    element.input(text[0], clear=True)
    time.sleep(random.uniform(0.1, 0.2))

    for char in text[1:]:
        element.input(char, clear=False)
        actual_delay = base_delay * random.uniform(0.5, 1.2)
        if char in ' @._-':
            actual_delay *= 1.3
        time.sleep(actual_delay)


def human_delay(min_sec: float = None, max_sec: float = None):
    """模拟人类操作间隔"""
    if min_sec is None:
        min_sec = ACTION_DELAY[0]
    if max_sec is None:
        max_sec = ACTION_DELAY[1]
    time.sleep(random.uniform(min_sec, max_sec))


def check_and_handle_error(page, max_retries=5) -> bool:
    """检查并处理页面错误"""
    for attempt in range(max_retries):
        try:
            page_source = page.html.lower()
            error_keywords = ['出错', 'error', 'timed out', 'operation timeout', 'route error', 'invalid content']
            has_error = any(keyword in page_source for keyword in error_keywords)

            if has_error:
                try:
                    retry_btn = page.ele('css:button[data-dd-action-name="Try again"]', timeout=2)
                    if retry_btn:
                        log.warning(f"检测到错误页面，点击重试 ({attempt + 1}/{max_retries})...")
                        retry_btn.click()
                        wait_time = 3 + attempt
                        time.sleep(wait_time)
                        return True
                except Exception:
                    time.sleep(1)
                    continue
            return False
        except Exception:
            return False
    return False


def is_logged_in(page) -> bool:
    """检测是否已登录 ChatGPT"""
    try:
        result = page.run_js('''
            return fetch('/api/auth/session', {
                method: 'GET',
                credentials: 'include'
            })
            .then(r => r.json())
            .then(data => JSON.stringify(data))
            .catch(e => '{}');
        ''')

        if result and result != '{}':
            import json
            data = json.loads(result)
            if data.get('user') and data.get('accessToken'):
                log.success(f"已登录: {data['user'].get('email', 'unknown')}")
                return True
        return False
    except Exception as e:
        log.warning(f"登录检测异常: {e}")
        return False


def retry_on_page_refresh(func):
    """装饰器: 页面刷新时自动重试"""
    def wrapper(*args, **kwargs):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                if '页面被刷新' in error_msg or 'page refresh' in error_msg or 'stale' in error_msg:
                    if attempt < max_retries - 1:
                        log.warning(f"页面刷新，重试操作 ({attempt + 1}/{max_retries})...")
                        time.sleep(1)
                        continue
                raise
        return None
    return wrapper


def register_openai_account(page, email: str, password: str) -> bool:
    """使用浏览器注册 OpenAI 账号

    Args:
        page: 浏览器实例
        email: 邮箱地址
        password: 密码

    Returns:
        bool: 是否成功
    """
    log.info(f"开始注册 OpenAI 账号: {email}", icon="account")

    try:
        # 打开注册页面
        url = "https://chatgpt.com"
        log.step(f"打开 {url}")
        page.get(url)

        # 智能等待页面加载完成
        wait_for_page_stable(page, timeout=8)
        log_current_url(page, "页面加载完成", force=True)

        # 检测是否已登录 (通过 API 判断)
        try:
            if is_logged_in(page):
                log.success("检测到已登录，跳过注册步骤")
                return True
        except Exception:
            pass  # 忽略登录检测异常，继续注册流程

        # 点击"免费注册"按钮
        log.step("点击免费注册...")
        signup_btn = wait_for_element(page, 'css:[data-testid="signup-button"]', timeout=5)
        if not signup_btn:
            signup_btn = wait_for_element(page, 'text:免费注册', timeout=3)
        if not signup_btn:
            signup_btn = wait_for_element(page, 'text:Sign up', timeout=3)
        if signup_btn:
            old_url = page.url
            signup_btn.click()
            # 等待 URL 变化或弹窗/输入框出现 (最多3秒快速检测)
            for _ in range(6):
                time.sleep(0.5)
                if page.url != old_url:
                    log_url_change(page, old_url, "点击注册按钮")
                    break
                # 检测弹窗中的邮箱输入框
                try:
                    email_input = page.ele('css:input[type="email"], input[name="email"]', timeout=1)
                    if email_input and email_input.states.is_displayed:
                        break
                except Exception:
                    pass

        current_url = page.url
        log_current_url(page, "注册按钮点击后")

        # 如果没有跳转到 auth.openai.com，检查是否在 chatgpt.com 弹窗中
        if "auth.openai.com" not in current_url and "chatgpt.com" in current_url:
            log.step("尝试在当前弹窗中输入邮箱...")
            email_input = wait_for_element(page, 'css:input[type="email"], input[name="email"], input[id="email"]', timeout=5)
            if email_input:
                human_delay()  # 模拟人类思考时间
                type_slowly(page, 'css:input[type="email"], input[name="email"], input[id="email"]', email)
                log.success("邮箱已输入")

                # 点击继续
                human_delay(0.5, 1.0)
                log.step("点击继续...")
                continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=5)
                if continue_btn:
                    old_url = page.url
                    continue_btn.click()
                    wait_for_url_change(page, old_url, timeout=10, contains="/password")

        # === 使用循环处理整个注册流程 ===
        max_steps = 10  # 防止无限循环
        for step in range(max_steps):
            current_url = page.url
            log_current_url(page, f"注册流程步骤 {step + 1}")

            # 如果在 chatgpt.com 且已登录，注册成功
            if "chatgpt.com" in current_url and "auth.openai.com" not in current_url:
                try:
                    if is_logged_in(page):
                        log.success("检测到已登录，账号已注册成功")
                        return True
                except Exception:
                    pass

            # 步骤1: 输入邮箱 (在 log-in-or-create-account 页面)
            if "auth.openai.com/log-in-or-create-account" in current_url:
                log.step("等待邮箱输入框...")
                email_input = wait_for_element(page, 'css:input[type="email"]', timeout=15)
                if not email_input:
                    log.error("无法找到邮箱输入框")
                    return False

                human_delay()  # 模拟人类思考时间
                log.step("输入邮箱...")
                type_slowly(page, 'css:input[type="email"]', email)
                log.success("邮箱已输入")

                # 点击继续
                human_delay(0.5, 1.2)
                log.step("点击继续...")
                continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=5)
                if continue_btn:
                    old_url = page.url
                    continue_btn.click()
                    wait_for_url_change(page, old_url, timeout=10)
                continue

            # 步骤2: 输入密码 (在密码页面: log-in/password 或 create-account/password)
            if "auth.openai.com/log-in/password" in current_url or "auth.openai.com/create-account/password" in current_url:
                # 先检查是否有密码错误提示，如果有则使用一次性验证码登录
                try:
                    error_text = page.ele('text:Incorrect email address or password', timeout=1)
                    if error_text and error_text.states.is_displayed:
                        log.warning("密码错误，尝试使用一次性验证码登录...")
                        otp_btn = wait_for_element(page, 'text=使用一次性验证码登录', timeout=3)
                        if not otp_btn:
                            otp_btn = wait_for_element(page, 'text=Log in with a one-time code', timeout=3)
                        if otp_btn:
                            old_url = page.url
                            otp_btn.click()
                            wait_for_url_change(page, old_url, timeout=10)
                            continue
                except Exception:
                    pass

                log.step("等待密码输入框...")
                password_input = wait_for_element(page, 'css:input[type="password"]', timeout=15)
                if not password_input:
                    log.error("无法找到密码输入框")
                    return False

                human_delay()  # 模拟人类思考时间
                log.step("输入密码...")
                type_slowly(page, 'css:input[type="password"]', password)
                log.success("密码已输入")

                # 点击继续
                human_delay(0.5, 1.2)
                log.step("点击继续...")
                continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=5)
                if continue_btn:
                    old_url = page.url
                    continue_btn.click()
                    # 等待页面变化，检测是否密码错误
                    time.sleep(2)
                    
                    # 检查是否出现密码错误提示
                    try:
                        error_text = page.ele('text:Incorrect email address or password', timeout=1)
                        if error_text and error_text.states.is_displayed:
                            log.warning("密码错误，尝试使用一次性验证码登录...")
                            otp_btn = wait_for_element(page, 'text=使用一次性验证码登录', timeout=3)
                            if not otp_btn:
                                otp_btn = wait_for_element(page, 'text=Log in with a one-time code', timeout=3)
                            if otp_btn:
                                otp_btn.click()
                                wait_for_url_change(page, old_url, timeout=10)
                                continue
                    except Exception:
                        pass
                    
                    wait_for_url_change(page, old_url, timeout=8)
                continue

            # 步骤3: 验证码页面
            if "auth.openai.com/email-verification" in current_url:
                break  # 跳出循环，进入验证码流程

            # 步骤4: 姓名/年龄页面 (账号已存在)
            if "auth.openai.com/about-you" in current_url:
                break  # 跳出循环，进入补充信息流程

            # 处理错误
            if check_and_handle_error(page):
                time.sleep(0.5)
                continue

            # 短暂等待页面变化
            time.sleep(0.5)

        # === 根据 URL 快速判断页面状态 ===
        current_url = page.url

        # 如果是 chatgpt.com 首页，说明已注册成功
        if "chatgpt.com" in current_url and "auth.openai.com" not in current_url:
            try:
                if is_logged_in(page):
                    log.success("检测到已登录，账号已注册成功")
                    return True
            except Exception:
                pass

        # 检测到姓名/年龄输入页面 (账号已存在，只需补充信息)
        if "auth.openai.com/about-you" in current_url:
            log_current_url(page, "个人信息页面")
            log.info("检测到姓名输入页面，账号已存在，补充信息...")

            # 等待页面加载
            name_input = wait_for_element(page, 'css:input[name="name"]', timeout=5)
            if not name_input:
                name_input = wait_for_element(page, 'css:input[autocomplete="name"]', timeout=3)
            
            # 输入姓名
            random_name = get_random_name()
            log.step(f"输入姓名: {random_name}")
            type_slowly(page, 'css:input[name="name"], input[autocomplete="name"]', random_name)

            # 输入生日 (与正常注册流程一致)
            birthday = get_random_birthday()
            log.step(f"输入生日: {birthday['year']}/{birthday['month']}/{birthday['day']}")

            # 年份
            year_input = wait_for_element(page, 'css:[data-type="year"]', timeout=10)
            if year_input:
                year_input.click()
                time.sleep(0.15)
                year_input.input(birthday['year'], clear=True)
                time.sleep(0.2)

            # 月份
            month_input = wait_for_element(page, 'css:[data-type="month"]', timeout=5)
            if month_input:
                month_input.click()
                time.sleep(0.15)
                month_input.input(birthday['month'], clear=True)
                time.sleep(0.2)

            # 日期
            day_input = wait_for_element(page, 'css:[data-type="day"]', timeout=5)
            if day_input:
                day_input.click()
                time.sleep(0.15)
                day_input.input(birthday['day'], clear=True)

            log.success("生日已输入")

            # 点击提交
            log.step("点击最终提交...")
            time.sleep(0.5)
            submit_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=5)
            if submit_btn:
                submit_btn.click()

            time.sleep(2)
            log.success(f"注册完成: {email}")
            return True

        # 检测到验证码页面
        needs_verification = "auth.openai.com/email-verification" in current_url

        if needs_verification:
            log_current_url(page, "邮箱验证码页面")

        if not needs_verification:
            # 检查验证码输入框是否存在
            code_input = wait_for_element(page, 'css:input[name="code"]', timeout=3)
            if code_input:
                needs_verification = True
                log_current_url(page, "邮箱验证码页面")

        # 只有在 chatgpt.com 页面且已登录才能判断为成功
        if not needs_verification:
            try:
                if "chatgpt.com" in page.url and is_logged_in(page):
                    log.success("账号已注册成功")
                    return True
            except Exception:
                pass
            log.error("注册流程异常，未到达预期页面")
            return False

        # 获取验证码
        log.step("等待验证码邮件...")
        verification_code, error, email_time = unified_get_verification_code(email)

        if not verification_code:
            verification_code = input("   ⚠️ 请手动输入验证码: ").strip()

        if not verification_code:
            log.error("无法获取验证码")
            return False

        # 验证码重试循环 (最多重试 3 次)
        max_code_retries = 3
        for code_attempt in range(max_code_retries):
            # 输入验证码
            log.step(f"输入验证码: {verification_code}")
            while check_and_handle_error(page):
                time.sleep(1)

            # 重新获取输入框 (可能页面已刷新)
            code_input = wait_for_element(page, 'css:input[name="code"]', timeout=10)
            if not code_input:
                code_input = wait_for_element(page, 'css:input[placeholder*="代码"]', timeout=5)

            if not code_input:
                # 再次检查是否已登录
                try:
                    if is_logged_in(page):
                        log.success("检测到已登录，跳过验证码输入")
                        return True
                except Exception:
                    pass
                log.error("无法找到验证码输入框")
                return False

            # 清空并输入验证码
            try:
                code_input.clear()
            except Exception:
                pass
            type_slowly(page, 'css:input[name="code"], input[placeholder*="代码"]', verification_code, base_delay=0.08)
            time.sleep(0.5)

            # 点击继续
            log.step("点击继续...")
            for attempt in range(3):
                try:
                    continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=10)
                    if continue_btn:
                        continue_btn.click()
                        break
                except Exception:
                    time.sleep(0.5)

            time.sleep(2)
            
            # 检查是否出现"代码不正确"错误
            try:
                error_text = page.ele('text:代码不正确', timeout=1)
                if not error_text:
                    error_text = page.ele('text:incorrect', timeout=1)
                if not error_text:
                    error_text = page.ele('text:Invalid code', timeout=1)
                    
                if error_text and error_text.states.is_displayed:
                    if code_attempt < max_code_retries - 1:
                        log.warning(f"验证码错误，尝试重新获取 ({code_attempt + 1}/{max_code_retries})...")
                        
                        # 点击"重新发送电子邮件"
                        resend_btn = page.ele('text:重新发送电子邮件', timeout=3)
                        if not resend_btn:
                            resend_btn = page.ele('text:Resend email', timeout=2)
                        if not resend_btn:
                            resend_btn = page.ele('text:resend', timeout=2)
                        
                        if resend_btn:
                            resend_btn.click()
                            log.info("已点击重新发送，等待新验证码...")
                            time.sleep(3)
                            
                            # 重新获取验证码
                            verification_code, error, email_time = unified_get_verification_code(email)
                            if not verification_code:
                                verification_code = input("   ⚠️ 请手动输入验证码: ").strip()
                            if verification_code:
                                continue  # 继续下一次尝试
                        
                        log.warning("无法重新发送验证码")
                    else:
                        log.error("验证码多次错误，放弃")
                        return False
                else:
                    # 没有错误，验证码正确，跳出循环
                    break
            except Exception:
                # 没有检测到错误，继续
                break
            
            while check_and_handle_error(page):
                time.sleep(0.5)

        # 记录当前页面 (应该是 about-you 个人信息页面)
        log_current_url(page, "验证码通过后-个人信息页面")

        # 输入姓名 (随机外国名字)
        random_name = get_random_name()
        log.step(f"输入姓名: {random_name}")
        name_input = wait_for_element(page, 'css:input[name="name"]', timeout=15)
        if not name_input:
            name_input = wait_for_element(page, 'css:input[autocomplete="name"]', timeout=5)
        type_slowly(page, 'css:input[name="name"], input[autocomplete="name"]', random_name)

        # 输入生日 (随机 2000-2005)
        birthday = get_random_birthday()
        log.step(f"输入生日: {birthday['year']}/{birthday['month']}/{birthday['day']}")

        # 年份
        year_input = wait_for_element(page, 'css:[data-type="year"]', timeout=10)
        if year_input:
            year_input.click()
            time.sleep(0.15)
            year_input.input(birthday['year'], clear=True)
            time.sleep(0.2)

        # 月份
        month_input = wait_for_element(page, 'css:[data-type="month"]', timeout=5)
        if month_input:
            month_input.click()
            time.sleep(0.15)
            month_input.input(birthday['month'], clear=True)
            time.sleep(0.2)

        # 日期
        day_input = wait_for_element(page, 'css:[data-type="day"]', timeout=5)
        if day_input:
            day_input.click()
            time.sleep(0.15)
            day_input.input(birthday['day'], clear=True)

        log.success("生日已输入")

        # 最终提交
        log.step("点击最终提交...")
        continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=10)
        if continue_btn:
            continue_btn.click()

        # 等待并检查是否出现 "email not supported" 错误
        time.sleep(2)
        try:
            error_text = page.ele('text:The email you provided is not supported', timeout=2)
            if error_text and error_text.states.is_displayed:
                log.error("邮箱域名不被支持，需要加入黑名单")
                return "domain_blacklisted"
        except Exception:
            pass

        log.success(f"注册完成: {email}")
        time.sleep(1)
        return True

    except Exception as e:
        log.error(f"注册失败: {e}")
        return False


def perform_codex_authorization(page, email: str, password: str) -> dict:
    """执行 Codex 授权流程

    Args:
        page: 浏览器实例
        email: 邮箱地址
        password: 密码

    Returns:
        dict: codex_data 或 None
    """
    log.info(f"开始 Codex 授权: {email}", icon="code")

    # 生成授权 URL
    auth_url, session_id = crs_generate_auth_url()
    if not auth_url or not session_id:
        log.error("无法获取授权 URL")
        return None

    # 打开授权页面
    log.step("打开授权页面...")
    log.info(f"[URL] 授权URL: {auth_url}", icon="browser")
    page.get(auth_url)
    wait_for_page_stable(page, timeout=5)
    log_current_url(page, "授权页面加载完成", force=True)

    try:
        # 输入邮箱
        log.step("输入邮箱...")
        email_input = wait_for_element(page, 'css:input[type="email"]', timeout=10)
        if not email_input:
            email_input = wait_for_element(page, 'css:input[name="email"]', timeout=5)
        if not email_input:
            email_input = wait_for_element(page, '#email', timeout=5)
        type_slowly(page, 'css:input[type="email"], input[name="email"], #email', email, base_delay=0.06)

        # 点击继续
        log.step("点击继续...")
        continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=5)
        if continue_btn:
            old_url = page.url
            continue_btn.click()
            wait_for_url_change(page, old_url, timeout=8)
            log_url_change(page, old_url, "输入邮箱后点击继续")

    except Exception as e:
        log.warning(f"邮箱输入步骤异常: {e}")

    log_current_url(page, "邮箱步骤完成后")

    try:
        # 输入密码
        log.step("输入密码...")
        password_input = wait_for_element(page, 'css:input[type="password"]', timeout=10)
        if not password_input:
            password_input = wait_for_element(page, 'css:input[name="password"]', timeout=5)
        type_slowly(page, 'css:input[type="password"], input[name="password"]', password, base_delay=0.06)

        # 点击继续
        log.step("点击继续...")
        continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=5)
        if continue_btn:
            old_url = page.url
            continue_btn.click()
            wait_for_url_change(page, old_url, timeout=8)
            log_url_change(page, old_url, "输入密码后点击继续")

    except Exception as e:
        log.warning(f"密码输入步骤异常: {e}")

    log_current_url(page, "密码步骤完成后")

    # 等待授权回调
    max_wait = 45  # 减少等待时间
    start_time = time.time()
    code = None
    progress_shown = False
    last_url_in_loop = None
    log.step(f"等待授权回调 (最多 {max_wait}s)...")

    while time.time() - start_time < max_wait:
        try:
            current_url = page.url

            # 记录URL变化
            if current_url != last_url_in_loop:
                log_current_url(page, "等待回调中")
                last_url_in_loop = current_url

            # 检查是否到达回调页面
            if "localhost:1455/auth/callback" in current_url and "code=" in current_url:
                if progress_shown:
                    log.progress_clear()
                log.success("获取到回调 URL")
                log.info(f"[URL] 回调地址: {current_url}", icon="browser")
                code = extract_code_from_url(current_url)
                if code:
                    log.success("提取授权码成功")
                    break

            # 尝试点击授权按钮
            try:
                buttons = page.eles('css:button[type="submit"]')
                for btn in buttons:
                    if btn.states.is_displayed and btn.states.is_enabled:
                        btn_text = btn.text.lower()
                        if any(x in btn_text for x in ['allow', 'authorize', 'continue', '授权', '允许', '继续', 'accept']):
                            if progress_shown:
                                log.progress_clear()
                                progress_shown = False
                            log.step(f"点击按钮: {btn.text}")
                            btn.click()
                            time.sleep(1.5)  # 减少等待
                            break
            except Exception:
                pass

            elapsed = int(time.time() - start_time)
            log.progress_inline(f"[等待中... {elapsed}s]")
            progress_shown = True
            time.sleep(1.5)  # 减少轮询间隔

        except Exception as e:
            if progress_shown:
                log.progress_clear()
                progress_shown = False
            log.warning(f"检查异常: {e}")
            time.sleep(1.5)

    if not code:
        if progress_shown:
            log.progress_clear()
        log.warning("授权超时")
        try:
            current_url = page.url
            if "code=" in current_url:
                code = extract_code_from_url(current_url)
        except Exception:
            pass

    if not code:
        log.error("无法获取授权码")
        return None

    # 交换 tokens
    log.step("交换 tokens...")
    codex_data = crs_exchange_code(code, session_id)

    if codex_data:
        log.success("Codex 授权成功")
        return codex_data
    else:
        log.error("Token 交换失败")
        return None


def perform_codex_authorization_with_otp(page, email: str) -> dict:
    """执行 Codex 授权流程 (使用一次性验证码登录，适用于已注册的 Team Owner)

    Args:
        page: 浏览器页面实例
        email: 邮箱地址

    Returns:
        dict: codex_data 或 None
    """
    log.info("开始 Codex 授权 (OTP 登录)...", icon="auth")

    # 生成授权 URL
    auth_url, session_id = crs_generate_auth_url()
    if not auth_url or not session_id:
        log.error("无法获取授权 URL")
        return None

    # 打开授权页面
    log.step("打开授权页面...")
    log.info(f"[URL] 授权URL: {auth_url}", icon="browser")
    page.get(auth_url)
    wait_for_page_stable(page, timeout=5)
    log_current_url(page, "OTP授权页面加载完成", force=True)

    try:
        # 输入邮箱
        log.step("输入邮箱...")
        email_input = wait_for_element(page, 'css:input[type="email"]', timeout=10)
        if not email_input:
            email_input = wait_for_element(page, 'css:input[name="email"]', timeout=5)
        type_slowly(page, 'css:input[type="email"], input[name="email"], #email', email, base_delay=0.06)

        # 点击继续
        log.step("点击继续...")
        continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=5)
        if continue_btn:
            old_url = page.url
            continue_btn.click()
            wait_for_url_change(page, old_url, timeout=8)
            log_url_change(page, old_url, "OTP流程-输入邮箱后")

    except Exception as e:
        log.warning(f"邮箱输入步骤异常: {e}")

    log_current_url(page, "OTP流程-邮箱步骤完成后")

    try:
        # 检查是否在密码页面，如果是则点击"使用一次性验证码登录"
        current_url = page.url
        if "/log-in/password" in current_url or "/password" in current_url:
            log.step("检测到密码页面，点击使用一次性验证码登录...")
            otp_btn = wait_for_element(page, 'text=使用一次性验证码登录', timeout=5)
            if not otp_btn:
                otp_btn = wait_for_element(page, 'text=Log in with a one-time code', timeout=3)
            if not otp_btn:
                # 尝试通过按钮文本查找
                buttons = page.eles('css:button')
                for btn in buttons:
                    btn_text = btn.text.lower()
                    if '一次性验证码' in btn_text or 'one-time' in btn_text:
                        otp_btn = btn
                        break
            
            if otp_btn:
                old_url = page.url
                otp_btn.click()
                log.success("已点击一次性验证码登录按钮")
                wait_for_url_change(page, old_url, timeout=8)
                log_url_change(page, old_url, "点击OTP按钮后")
            else:
                log.warning("未找到一次性验证码登录按钮")
        else:
            # 不在密码页面，尝试直接找 OTP 按钮
            log.step("点击使用一次性验证码登录...")
            otp_btn = wait_for_element(page, 'css:button[value="passwordless_login_send_otp"]', timeout=10)
            if not otp_btn:
                otp_btn = wait_for_element(page, 'css:button._inlinePasswordlessLogin', timeout=5)
            if not otp_btn:
                buttons = page.eles('css:button')
                for btn in buttons:
                    if '一次性验证码' in btn.text or 'one-time' in btn.text.lower():
                        otp_btn = btn
                        break

            if otp_btn:
                otp_btn.click()
                log.success("已点击一次性验证码登录按钮")
                time.sleep(2)
            else:
                log.warning("未找到一次性验证码登录按钮，尝试继续...")

    except Exception as e:
        log.warning(f"点击 OTP 按钮异常: {e}")

    log_current_url(page, "OTP流程-准备获取验证码")

    # 等待并获取验证码
    log.step("等待验证码邮件...")
    verification_code, error, email_time = unified_get_verification_code(email)

    if not verification_code:
        log.warning(f"自动获取验证码失败: {error}")
        # 手动输入
        verification_code = input("⚠️ 请手动输入验证码: ").strip()
        if not verification_code:
            log.error("未输入验证码")
            return None

    # 验证码重试循环 (最多重试 3 次)
    max_code_retries = 3
    for code_attempt in range(max_code_retries):
        try:
            # 输入验证码
            log.step(f"输入验证码: {verification_code}")
            code_input = wait_for_element(page, 'css:input[name="otp"]', timeout=10)
            if not code_input:
                code_input = wait_for_element(page, 'css:input[type="text"]', timeout=5)
            if not code_input:
                code_input = wait_for_element(page, 'css:input[autocomplete="one-time-code"]', timeout=5)

            if code_input:
                # 清空并输入验证码
                try:
                    code_input.clear()
                except Exception:
                    pass
                type_slowly(page, 'css:input[name="otp"], input[type="text"], input[autocomplete="one-time-code"]', verification_code, base_delay=0.08)
                log.success("验证码已输入")
            else:
                log.error("未找到验证码输入框")
                return None

            # 点击继续/验证按钮
            log.step("点击继续...")
            time.sleep(1)
            continue_btn = wait_for_element(page, 'css:button[type="submit"]', timeout=5)
            if continue_btn:
                old_url = page.url
                continue_btn.click()
                time.sleep(2)
                
            # 检查是否出现"代码不正确"错误
            try:
                error_text = page.ele('text:代码不正确', timeout=1)
                if not error_text:
                    error_text = page.ele('text:incorrect', timeout=1)
                if not error_text:
                    error_text = page.ele('text:Invalid code', timeout=1)
                    
                if error_text and error_text.states.is_displayed:
                    if code_attempt < max_code_retries - 1:
                        log.warning(f"验证码错误，尝试重新获取 ({code_attempt + 1}/{max_code_retries})...")
                        
                        # 点击"重新发送电子邮件"
                        resend_btn = page.ele('text:重新发送电子邮件', timeout=3)
                        if not resend_btn:
                            resend_btn = page.ele('text:Resend email', timeout=2)
                        if not resend_btn:
                            resend_btn = page.ele('text:resend', timeout=2)
                        
                        if resend_btn:
                            resend_btn.click()
                            log.info("已点击重新发送，等待新验证码...")
                            time.sleep(3)
                            
                            # 重新获取验证码
                            verification_code, error, email_time = unified_get_verification_code(email)
                            if not verification_code:
                                verification_code = input("   ⚠️ 请手动输入验证码: ").strip()
                            if verification_code:
                                continue  # 继续下一次尝试
                        
                        log.warning("无法重新发送验证码")
                    else:
                        log.error("验证码多次错误，放弃")
                        return None
                else:
                    # 没有错误，验证码正确，跳出循环
                    break
            except Exception:
                # 没有检测到错误元素，说明验证码正确，继续
                break

        except Exception as e:
            log.warning(f"验证码输入步骤异常: {e}")
            break

    # 等待授权回调
    max_wait = 45
    start_time = time.time()
    code = None
    progress_shown = False
    last_url_in_loop = None
    log.step(f"等待授权回调 (最多 {max_wait}s)...")

    while time.time() - start_time < max_wait:
        try:
            current_url = page.url

            # 记录URL变化
            if current_url != last_url_in_loop:
                log_current_url(page, "OTP流程-等待回调中")
                last_url_in_loop = current_url

            # 检查是否到达回调页面
            if "localhost:1455/auth/callback" in current_url and "code=" in current_url:
                if progress_shown:
                    log.progress_clear()
                log.success("获取到回调 URL")
                log.info(f"[URL] 回调地址: {current_url}", icon="browser")
                code = extract_code_from_url(current_url)
                if code:
                    log.success("提取授权码成功")
                    break

            # 尝试点击授权按钮
            try:
                buttons = page.eles('css:button[type="submit"]')
                for btn in buttons:
                    if btn.states.is_displayed and btn.states.is_enabled:
                        btn_text = btn.text.lower()
                        if any(x in btn_text for x in ['allow', 'authorize', 'continue', '授权', '允许', '继续', 'accept']):
                            if progress_shown:
                                log.progress_clear()
                                progress_shown = False
                            log.step(f"点击按钮: {btn.text}")
                            btn.click()
                            time.sleep(1.5)
                            break
            except Exception:
                pass

            elapsed = int(time.time() - start_time)
            log.progress_inline(f"[等待中... {elapsed}s]")
            progress_shown = True
            time.sleep(1.5)

        except Exception as e:
            if progress_shown:
                log.progress_clear()
                progress_shown = False
            log.warning(f"检查异常: {e}")
            time.sleep(1.5)

    if not code:
        if progress_shown:
            log.progress_clear()
        log.warning("授权超时")
        try:
            current_url = page.url
            if "code=" in current_url:
                code = extract_code_from_url(current_url)
        except Exception:
            pass

    if not code:
        log.error("无法获取授权码")
        return None

    # 交换 tokens
    log.step("交换 tokens...")
    codex_data = crs_exchange_code(code, session_id)

    if codex_data:
        log.success("Codex 授权成功 (OTP)")
        return codex_data
    else:
        log.error("Token 交换失败")
        return None


def login_and_authorize_with_otp(email: str) -> tuple[bool, dict]:
    """Team Owner 专用: 使用一次性验证码登录并完成 Codex 授权

    Args:
        email: 邮箱地址

    Returns:
        tuple: (success, codex_data)
    """
    with browser_context_with_retry(max_browser_retries=2) as ctx:
        for attempt in ctx.attempts():
            try:
                # 直接进行 Codex 授权 (使用 OTP 登录)
                codex_data = perform_codex_authorization_with_otp(ctx.page, email)

                if codex_data:
                    return True, codex_data
                else:
                    if attempt < ctx.max_retries - 1:
                        log.warning("授权失败，准备重试...")
                        continue
                    return False, None

            except Exception as e:
                ctx.handle_error(e)
                if ctx.current_attempt >= ctx.max_retries - 1:
                    return False, None

    return False, None


def register_and_authorize(email: str, password: str) -> tuple:
    """完整流程: 注册 OpenAI + Codex 授权 (带重试机制)

    Args:
        email: 邮箱地址
        password: 密码

    Returns:
        tuple: (register_success, codex_data)
        - register_success: True/False/"domain_blacklisted"
    """
    with browser_context_with_retry(max_browser_retries=2) as ctx:
        for attempt in ctx.attempts():
            try:
                # 注册 OpenAI
                register_result = register_openai_account(ctx.page, email, password)

                # 检查是否是域名黑名单错误
                if register_result == "domain_blacklisted":
                    ctx.stop()
                    return "domain_blacklisted", None

                if not register_result:
                    if attempt < ctx.max_retries - 1:
                        log.warning("注册失败，准备重试...")
                        continue
                    return False, None

                # 短暂等待确保注册完成
                time.sleep(0.5)

                # Codex 授权
                codex_data = perform_codex_authorization(ctx.page, email, password)

                return True, codex_data

            except Exception as e:
                ctx.handle_error(e)
                if ctx.current_attempt >= ctx.max_retries - 1:
                    return False, None

    return False, None


def authorize_only(email: str, password: str) -> tuple[bool, dict]:
    """仅执行 Codex 授权 (适用于已注册但未授权的账号)

    Args:
        email: 邮箱地址
        password: 密码

    Returns:
        tuple: (success, codex_data)
    """
    with browser_context_with_retry(max_browser_retries=2) as ctx:
        for attempt in ctx.attempts():
            try:
                # 直接进行 Codex 授权 (使用密码登录)
                log.info("已注册账号，直接进行 Codex 授权...", icon="auth")
                codex_data = perform_codex_authorization(ctx.page, email, password)

                if codex_data:
                    return True, codex_data
                else:
                    if attempt < ctx.max_retries - 1:
                        log.warning("授权失败，准备重试...")
                        continue
                    return False, None

            except Exception as e:
                ctx.handle_error(e)
                if ctx.current_attempt >= ctx.max_retries - 1:
                    return False, None

    return False, None
