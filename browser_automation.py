# ==================== 浏览器自动化模块 ====================
# 处理 OpenAI 注册、Codex 授权等浏览器自动化操作
# 使用 DrissionPage 替代 Selenium

import time
import random
from DrissionPage import ChromiumPage, ChromiumOptions

from config import (
    BROWSER_WAIT_TIMEOUT,
    BROWSER_SHORT_WAIT,
    get_random_name,
    get_random_birthday
)
from email_service import get_verification_code
from crs_service import crs_generate_auth_url, crs_exchange_code, crs_add_account, extract_code_from_url
from logger import log


def init_browser():
    """初始化 DrissionPage 浏览器 (每次都是新的无痕窗口)

    Returns:
        ChromiumPage: 浏览器实例
    """
    log.info("初始化浏览器...", icon="browser")

    try:
        co = ChromiumOptions()
        co.set_argument('--no-first-run')
        co.set_argument('--disable-infobars')
        co.set_argument('--incognito')  # 无痕模式
        co.auto_port()  # 自动分配端口，确保每次都是新实例

        log.step("启动 Chrome (无痕模式)...")
        page = ChromiumPage(co)
        log.success("浏览器启动成功")
        return page

    except Exception as e:
        log.error(f"浏览器启动失败: {e}")
        raise


def type_slowly(page, selector_or_element, text, base_delay=0.12):
    """缓慢输入文本 (模拟真人输入)

    Args:
        page: 浏览器页面对象 (用于重新获取元素)
        selector_or_element: CSS 选择器字符串或元素对象
        text: 要输入的文本
        base_delay: 基础延迟 (秒)，实际延迟会在此基础上随机浮动
    """
    # 获取元素 (如果传入的是选择器则查找，否则直接使用)
    if isinstance(selector_or_element, str):
        element = page.ele(selector_or_element, timeout=10)
    else:
        element = selector_or_element

    # 使用 input 的 clear=True 一次性清空并输入第一个字符
    # 这样避免单独调用 clear() 导致元素失效
    if text:
        element.input(text[0], clear=True)
        time.sleep(random.uniform(0.3, 0.6))

        # 逐个输入剩余字符
        for char in text[1:]:
            # 每次重新获取元素，避免 DOM 更新导致失效
            if isinstance(selector_or_element, str):
                element = page.ele(selector_or_element, timeout=5)
            element.input(char, clear=False)
            # 随机延迟: 基础延迟 ± 50% 浮动，模拟真人打字节奏
            actual_delay = base_delay * random.uniform(0.5, 1.5)
            # 遇到空格或特殊字符时稍微停顿更久
            if char in ' @._-':
                actual_delay *= random.uniform(1.2, 1.8)
            time.sleep(actual_delay)


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
                        wait_time = 5 + (attempt * 2)
                        time.sleep(wait_time)
                        return True
                except Exception:
                    time.sleep(2)
                    continue
            return False
        except Exception:
            return False
    return False


def is_logged_in(page) -> bool:
    """检测是否已登录 ChatGPT (通过 API 请求判断)

    通过请求 /api/auth/session 接口判断:
    - 已登录: 返回包含 user 字段的 JSON
    - 未登录: 返回 {}
    """
    try:
        # 使用 JavaScript 请求 session API
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
        time.sleep(2)

        # 检测是否已登录 (通过 API 判断)
        if is_logged_in(page):
            log.success("检测到已登录，跳过注册步骤")
            return True

        # 点击"免费注册"按钮
        log.step("点击免费注册...")
        signup_btn = page.ele('css:[data-testid="signup-button"]', timeout=3)
        if not signup_btn:
            signup_btn = page.ele('text:免费注册', timeout=2)
        if not signup_btn:
            signup_btn = page.ele('text:Sign up', timeout=2)
        if signup_btn:
            signup_btn.click()

        # 等待页面跳转到 auth.openai.com
        log.step("等待跳转到登录页面...")
        for _ in range(15):  # 最多等待 15 秒
            current_url = page.url
            if "auth.openai.com" in current_url:
                break
            time.sleep(1)

        current_url = page.url
        log.step(f"当前页面: {current_url}")

        # === 使用循环处理整个注册流程 ===
        max_steps = 10  # 防止无限循环
        for step in range(max_steps):
            current_url = page.url
            log.step(f"当前页面: {current_url}")

            # 如果在 chatgpt.com 且已登录，注册成功
            if "chatgpt.com" in current_url and "auth.openai.com" not in current_url:
                if is_logged_in(page):
                    log.success("检测到已登录，账号已注册成功")
                    return True

            # 步骤1: 输入邮箱 (在 log-in-or-create-account 页面)
            if "auth.openai.com/log-in-or-create-account" in current_url:
                log.step("等待邮箱输入框...")
                email_input = page.ele('css:input[type="email"]', timeout=30)
                if not email_input:
                    log.error("无法找到邮箱输入框")
                    return False

                log.step("输入邮箱...")
                type_slowly(page, 'css:input[type="email"]', email)
                log.success("邮箱已输入")

                # 点击继续
                log.step("点击继续...")
                continue_btn = page.ele('css:button[type="submit"]', timeout=10)
                if continue_btn:
                    continue_btn.click()

                # 等待 URL 变化（离开当前页面）
                log.step("等待页面跳转...")
                for _ in range(15):
                    if "log-in-or-create-account" not in page.url:
                        break
                    time.sleep(1)
                continue  # 继续下一步

            # 步骤2: 输入密码 (在密码页面: log-in/password 或 create-account/password)
            if "auth.openai.com/log-in/password" in current_url or "auth.openai.com/create-account/password" in current_url:
                log.step("等待密码输入框...")
                password_input = page.ele('css:input[type="password"]', timeout=30)
                if not password_input:
                    log.error("无法找到密码输入框")
                    return False

                log.step("输入密码...")
                type_slowly(page, 'css:input[type="password"]', password)
                log.success("密码已输入")

                # 点击继续
                log.step("点击继续...")
                continue_btn = page.ele('css:button[type="submit"]', timeout=10)
                if continue_btn:
                    continue_btn.click()

                # 等待 URL 变化（离开当前页面）
                log.step("等待页面跳转...")
                for _ in range(15):
                    if "/password" not in page.url:
                        break
                    time.sleep(1)
                continue  # 继续下一步

            # 步骤3: 验证码页面
            if "auth.openai.com/email-verification" in current_url:
                break  # 跳出循环，进入验证码流程

            # 处理错误
            if check_and_handle_error(page):
                time.sleep(1)
                continue

            # 等待页面变化
            time.sleep(1)

        # === 根据最终 URL 判断状态 ===
        current_url = page.url
        log.step(f"当前页面: {current_url}")

        # 如果是 chatgpt.com 首页，说明已注册成功
        if "chatgpt.com" in current_url and "auth.openai.com" not in current_url:
            if is_logged_in(page):
                log.success("检测到已登录，账号已注册成功")
                return True

        # 如果是验证码页面，需要获取验证码
        needs_verification = "auth.openai.com/email-verification" in current_url

        if not needs_verification:
            # 检查验证码输入框是否存在
            code_input = page.ele('css:input[name="code"]', timeout=3)
            if code_input:
                needs_verification = True

        # 只有在 chatgpt.com 页面且已登录才能判断为成功
        if not needs_verification:
            if "chatgpt.com" in page.url and is_logged_in(page):
                log.success("账号已注册成功")
                return True
            else:
                log.error("注册流程异常，未到达预期页面")
                return False

        # 获取验证码
        log.step("等待验证码邮件...")
        verification_code, error, email_time = get_verification_code(email)

        if not verification_code:
            verification_code = input("   ⚠️ 请手动输入验证码: ").strip()

        if not verification_code:
            log.error("无法获取验证码")
            return False

        # 输入验证码
        log.step(f"输入验证码: {verification_code}")
        while check_and_handle_error(page):
            time.sleep(2)

        # 重新获取输入框 (可能页面已刷新)
        code_input = page.ele('css:input[name="code"]', timeout=10)
        if not code_input:
            code_input = page.ele('css:input[placeholder*="代码"]', timeout=5)

        if not code_input:
            # 再次检查是否已登录
            if is_logged_in(page):
                log.success("检测到已登录，跳过验证码输入")
                return True
            log.error("无法找到验证码输入框")
            return False

        type_slowly(page, 'css:input[name="code"], input[placeholder*="代码"]', verification_code, base_delay=0.1)
        time.sleep(1)

        # 点击继续
        log.step("点击继续...")
        for attempt in range(3):
            try:
                continue_btn = page.ele('css:button[type="submit"]', timeout=15)
                continue_btn.click()
                break
            except Exception:
                time.sleep(1)

        time.sleep(2)
        while check_and_handle_error(page):
            time.sleep(1)

        # 输入姓名 (随机外国名字)
        random_name = get_random_name()
        log.step(f"输入姓名: {random_name}")
        name_input = page.ele('css:input[name="name"]', timeout=30)
        if not name_input:
            name_input = page.ele('css:input[autocomplete="name"]', timeout=5)
        type_slowly(page, 'css:input[name="name"], input[autocomplete="name"]', random_name)

        # 输入生日 (随机 2000-2005)
        birthday = get_random_birthday()
        log.step(f"输入生日: {birthday['year']}/{birthday['month']}/{birthday['day']}")

        # 年份
        year_input = page.ele('css:[data-type="year"]', timeout=10)
        year_input.click()
        time.sleep(0.2)
        year_input.input(birthday['year'], clear=True)
        time.sleep(0.3)

        # 月份
        month_input = page.ele('css:[data-type="month"]')
        month_input.click()
        time.sleep(0.2)
        month_input.input(birthday['month'], clear=True)
        time.sleep(0.3)

        # 日期
        day_input = page.ele('css:[data-type="day"]')
        day_input.click()
        time.sleep(0.2)
        day_input.input(birthday['day'], clear=True)

        log.success("生日已输入")

        # 最终提交
        log.step("点击最终提交...")
        continue_btn = page.ele('css:button[type="submit"]', timeout=15)
        continue_btn.click()

        log.success(f"注册完成: {email}")
        time.sleep(2)
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
    page.get(auth_url)
    time.sleep(2)

    try:
        # 输入邮箱
        log.step("输入邮箱...")
        email_input = page.ele('css:input[type="email"]', timeout=15)
        if not email_input:
            email_input = page.ele('css:input[name="email"]', timeout=5)
        if not email_input:
            email_input = page.ele('#email', timeout=5)
        type_slowly(page, 'css:input[type="email"], input[name="email"], #email', email, base_delay=0.08)

        # 点击继续
        log.step("点击继续...")
        continue_btn = page.ele('css:button[type="submit"]', timeout=10)
        continue_btn.click()
        time.sleep(2)

    except Exception as e:
        log.warning(f"邮箱输入步骤异常: {e}")

    try:
        # 输入密码
        log.step("输入密码...")
        password_input = page.ele('css:input[type="password"]', timeout=15)
        if not password_input:
            password_input = page.ele('css:input[name="password"]', timeout=5)
        type_slowly(page, 'css:input[type="password"], input[name="password"]', password, base_delay=0.08)

        # 点击继续
        log.step("点击继续...")
        continue_btn = page.ele('css:button[type="submit"]', timeout=10)
        continue_btn.click()
        time.sleep(2)

    except Exception as e:
        log.warning(f"密码输入步骤异常: {e}")

    # 等待授权回调
    max_wait = 60
    start_time = time.time()
    code = None
    progress_shown = False  # 追踪是否已显示进度指示器
    log.step(f"等待授权回调 (最多 {max_wait}s)...")

    while time.time() - start_time < max_wait:
        try:
            current_url = page.url

            # 检查是否到达回调页面
            if "localhost:1455/auth/callback" in current_url and "code=" in current_url:
                if progress_shown:
                    print()  # 清除进度行
                log.success("获取到回调 URL")
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
                                print()  # 清除进度行
                                progress_shown = False
                            log.step(f"点击按钮: {btn.text}")
                            btn.click()
                            time.sleep(2)
                            break
            except Exception:
                pass

            elapsed = int(time.time() - start_time)
            print(f"\r  [等待中... {elapsed}s]", end='', flush=True)
            progress_shown = True
            time.sleep(2)

        except Exception as e:
            if progress_shown:
                print()
                progress_shown = False
            log.warning(f"检查异常: {e}")
            time.sleep(2)

    if not code:
        if progress_shown:
            print()  # 换行
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


def register_and_authorize(email: str, password: str) -> tuple[bool, dict]:
    """完整流程: 注册 OpenAI + Codex 授权

    Args:
        email: 邮箱地址
        password: 密码

    Returns:
        tuple: (register_success, codex_data)
    """
    page = None
    try:
        page = init_browser()

        # 注册 OpenAI
        register_success = register_openai_account(page, email, password)
        if not register_success:
            return False, None

        # 等待一下确保注册完成
        time.sleep(1)

        # Codex 授权
        codex_data = perform_codex_authorization(page, email, password)

        return True, codex_data

    except Exception as e:
        log.error(f"流程异常: {e}")
        return False, None

    finally:
        if page:
            log.step("关闭浏览器...")
            page.quit()
