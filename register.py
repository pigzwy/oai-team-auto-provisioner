import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import random
import string
import csv
import os
import re
import json
from urllib.parse import urlparse, parse_qs


def create_session_with_retry():
    session = requests.Session()
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


http_session = create_session_with_retry()

# 注册账号数量
TOTAL_ACCOUNTS = 1


WORKER_DOMAIN = ""
ADMIN_TOKEN = ""

CSV_FILE = "registered_accounts.csv"
INVITE_TRACKER_FILE = "invite_tracker.json"

CRS_API_BASE = ""
CRS_ADMIN_TOKEN = ""

TEAMS = [
    {
        "name": "Team1",
        "account_id": "",
        "auth_token": "",
        "max_invites": 4
    },
    {
        "name": "Team2",
        "account_id": "",
        "auth_token": "",
        "max_invites": 4
    }
]




def crs_generate_auth_url():
    headers = {
        "accept": "*/*",
        "authorization": f"Bearer {CRS_ADMIN_TOKEN}",
        "content-type": "application/json",
        "origin": CRS_API_BASE,
        "referer": f"{CRS_API_BASE}/admin-next/accounts",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    }
    try:
        response = http_session.post(
            f"{CRS_API_BASE}/admin/openai-accounts/generate-auth-url",
            headers=headers,
            json={},
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                auth_url = result["data"]["authUrl"]
                session_id = result["data"]["sessionId"]
                print(f"✅ Generated auth URL")
                print(f"   Session ID: {session_id}")
                return auth_url, session_id
        print(f"❌ Failed to generate auth URL: {response.status_code}")
        return None, None
    except Exception as e:
        print(f"❌ CRS API error: {e}")
        return None, None


def crs_exchange_code(code: str, session_id: str):
    headers = {
        "accept": "*/*",
        "authorization": f"Bearer {CRS_ADMIN_TOKEN}",
        "content-type": "application/json",
        "origin": CRS_API_BASE,
        "referer": f"{CRS_API_BASE}/admin-next/accounts",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    }
    payload = {"code": code, "sessionId": session_id}
    try:
        response = http_session.post(
            f"{CRS_API_BASE}/admin/openai-accounts/exchange-code",
            headers=headers,
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                print(f"✅ Successfully exchanged code for tokens")
                return result["data"]
        print(f"❌ Failed to exchange code: {response.status_code}")
        print(f"   Response: {response.text[:300]}")
        return None
    except Exception as e:
        print(f"❌ CRS exchange error: {e}")
        return None


def crs_add_account(email: str, codex_data: dict):
    headers = {
        "accept": "*/*",
        "authorization": f"Bearer {CRS_ADMIN_TOKEN}",
        "content-type": "application/json",
        "origin": CRS_API_BASE,
        "referer": f"{CRS_API_BASE}/admin-next/accounts",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    }
    payload = {
        "name": email,
        "description": "",
        "accountType": "shared",
        "proxy": None,
        "openaiOauth": {
            "idToken": codex_data.get("tokens", {}).get("idToken"),
            "accessToken": codex_data.get("tokens", {}).get("accessToken"),
            "refreshToken": codex_data.get("tokens", {}).get("refreshToken"),
            "expires_in": codex_data.get("tokens", {}).get("expires_in", 864000)
        },
        "accountInfo": codex_data.get("accountInfo", {}),
        "priority": 50
    }
    try:
        response = http_session.post(
            f"{CRS_API_BASE}/admin/openai-accounts",
            headers=headers,
            json=payload,
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            if result.get("success"):
                account_id = result.get("data", {}).get("id")
                print(f"✅ Account added to CRS database")
                print(f"   CRS Account ID: {account_id}")
                return result["data"]
        print(f"❌ Failed to add account to CRS: {response.status_code}")
        print(f"   Response: {response.text[:300]}")
        return None
    except Exception as e:
        print(f"❌ CRS add account error: {e}")
        return None


def extract_code_from_url(url: str):
    if not url:
        return None
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        return code
    except Exception as e:
        print(f"❌ Failed to parse URL: {e}")
        return None


def perform_codex_authorization(driver, email: str, password: str):
    print("\n🔐 Starting Codex authorization...")
    auth_url, session_id = crs_generate_auth_url()
    if not auth_url or not session_id:
        print("❌ Failed to get auth URL, skipping Codex authorization")
        return False
    
    print(f"📡 Navigating to auth URL...")
    driver.get(auth_url)
    time.sleep(3)
    
    try:
        print("📧 Entering email for authorization...")
        email_input = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[type="email"], input[name="email"], input[id="email"]'))
        )
        email_input.clear()
        time.sleep(0.3)
        for char in email:
            email_input.send_keys(char)
            time.sleep(0.03)
        print(f"   Entered email: {email}")
        time.sleep(1)
        print("   Clicking Continue...")
        continue_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]'))
        )
        driver.execute_script("arguments[0].click();", continue_btn)
        time.sleep(3)
    except Exception as e:
        print(f"⚠️ Email input step error: {e}")
    
    try:
        print("🔑 Entering password...")
        password_input = WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[type="password"], input[name="password"]'))
        )
        password_input.clear()
        time.sleep(0.3)
        for char in password:
            password_input.send_keys(char)
            time.sleep(0.03)
        print("   Entered password")
        time.sleep(1)
        print("   Clicking Continue...")
        continue_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]'))
        )
        driver.execute_script("arguments[0].click();", continue_btn)
        time.sleep(3)
    except Exception as e:
        print(f"⚠️ Password input step error: {e}")
    
    max_wait = 60
    start_time = time.time()
    code = None
    print(f"⏳ Waiting for authorization callback (max {max_wait}s)...")
    
    while time.time() - start_time < max_wait:
        try:
            current_url = driver.current_url
            if "localhost:1455/auth/callback" in current_url and "code=" in current_url:
                print(f"\n✅ Got callback URL")
                code = extract_code_from_url(current_url)
                if code:
                    print(f"✅ Extracted authorization code")
                    break
            try:
                buttons = driver.find_elements(By.CSS_SELECTOR, 'button[type="submit"]')
                for btn in buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        btn_text = btn.text.lower()
                        if any(x in btn_text for x in ['allow', 'authorize', 'continue', '授权', '允许', '继续', 'accept']):
                            print(f"\n🔘 Clicking button: {btn.text}")
                            driver.execute_script("arguments[0].click();", btn)
                            time.sleep(2)
                            break
            except Exception:
                pass
            elapsed = int(time.time() - start_time)
            print(f"  Waiting... ({elapsed}s)", end='\r')
            time.sleep(2)
        except Exception as e:
            print(f"  Check error: {e}")
            time.sleep(2)
    
    if not code:
        print("\n⏰ Timeout waiting for authorization code")
        try:
            current_url = driver.current_url
            if "code=" in current_url:
                code = extract_code_from_url(current_url)
        except Exception:
            pass
    
    if not code:
        print("❌ Failed to get authorization code")
        return False
    
    print("\n🔄 Exchanging code for tokens...")
    codex_data = crs_exchange_code(code, session_id)
    
    if codex_data:
        print("\n📥 Adding account to CRS database...")
        crs_result = crs_add_account(email, codex_data)
        if crs_result:
            print("🎉 Codex authorization & CRS registration completed!")
            return True
        else:
            print("⚠️ Tokens obtained but failed to add to CRS database")
            return False
    else:
        print("❌ Failed to exchange code for tokens")
        return False


def load_invite_tracker():
    if os.path.exists(INVITE_TRACKER_FILE):
        try:
            with open(INVITE_TRACKER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Failed to load invite tracker: {e}")
    return {"teams": {team["account_id"]: [] for team in TEAMS}}


def save_invite_tracker(tracker):
    try:
        with open(INVITE_TRACKER_FILE, 'w', encoding='utf-8') as f:
            json.dump(tracker, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Failed to save invite tracker: {e}")


def get_available_team(tracker):
    for team in TEAMS:
        account_id = team["account_id"]
        invited = tracker["teams"].get(account_id, [])
        if len(invited) < team["max_invites"]:
            return team
    return None


def invite_to_team(email: str, team: dict):
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "authorization": team["auth_token"],
        "chatgpt-account-id": team["account_id"],
        "content-type": "application/json",
        "origin": "https://chatgpt.com",
        "referer": "https://chatgpt.com/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    }
    payload = {
        "email_addresses": [email],
        "role": "standard-user",
        "resend_emails": True
    }
    invite_url = f"https://chatgpt.com/backend-api/accounts/{team['account_id']}/invites"
    try:
        response = requests.post(invite_url, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            result = response.json()
            if result.get("account_invites"):
                print(f"✅ Successfully invited {email} to {team['name']}")
                return True
            elif result.get("errored_emails"):
                print(f"⚠️ Invite error for {email}: {result['errored_emails']}")
                return False
        else:
            print(f"❌ Failed to invite {email}: HTTP {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False
    except Exception as e:
        print(f"❌ Invite request failed: {e}")
        return False


def auto_invite_to_team(email: str):
    tracker = load_invite_tracker()
    for account_id, emails in tracker["teams"].items():
        if email in emails:
            print(f"⚠️ {email} already invited to a team, skipping...")
            return False
    team = get_available_team(tracker)
    if not team:
        print("❌ All teams are full (4 accounts each)")
        return False
    if invite_to_team(email, team):
        account_id = team["account_id"]
        if account_id not in tracker["teams"]:
            tracker["teams"][account_id] = []
        tracker["teams"][account_id].append(email)
        save_invite_tracker(tracker)
        print(f"   Team status: {team['name']} has {len(tracker['teams'][account_id])}/{team['max_invites']} invites")
        return True
    return False


def get_random_user_agent():
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"


def generate_random_password(length=16):
    chars = string.ascii_letters + string.digits + "!@#$%"
    password = ''.join(random.choice(chars) for _ in range(length))
    password = (random.choice(string.ascii_uppercase) + 
                random.choice(string.ascii_lowercase) + 
                random.choice(string.digits) + 
                random.choice("!@#$%") + 
                password[4:])
    print(f"✅ Generated password: {password}")
    return password


def create_temp_email():
    print("Creating temporary email...")
    headers = {
        "Authorization": f"Bearer {ADMIN_TOKEN}",
        "User-Agent": get_random_user_agent()
    }
    try:
        response = http_session.get(
            f"{WORKER_DOMAIN}/api/generate",
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            email = result.get('email')
            if email:
                print(f"✅ Email created: {email}")
                return email
    except Exception as e:
        print(f"❌ Email creation failed: {e}")
    return None


def fetch_emails(email: str):
    headers = {
        "Authorization": f"Bearer {ADMIN_TOKEN}",
        "User-Agent": get_random_user_agent()
    }
    try:
        response = http_session.get(
            f"{WORKER_DOMAIN}/api/emails",
            params={"mailbox": email},
            headers=headers,
            timeout=30
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"  Fetch emails error: {e}")
    return None


def extract_verification_code(email_content: str):
    if not email_content:
        return None
    patterns = [
        r'代码为\s*(\d{6})',
        r'code is\s*(\d{6})',
        r'(\d{6})',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, email_content)
        if matches:
            code = matches[0]
            print(f"  ✅ Extracted code: {code}")
            return code
    return None


def wait_for_verification_email(email: str, timeout: int = 120):
    print(f"Waiting for verification email (max {timeout}s)...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        emails = fetch_emails(email)
        if emails and len(emails) > 0:
            for email_item in emails:
                sender = email_item.get('from', '').lower()
                subject = email_item.get('subject', '')
                if 'openai' in sender or 'chatgpt' in subject.lower():
                    email_id = email_item.get('id')
                    if email_id:
                        headers = {
                            "Authorization": f"Bearer {ADMIN_TOKEN}",
                            "User-Agent": get_random_user_agent()
                        }
                        detail_response = http_session.get(
                            f"{WORKER_DOMAIN}/api/email/{email_id}",
                            headers=headers,
                            timeout=30
                        )
                        if detail_response.status_code == 200:
                            detail = detail_response.json()
                            content = (detail.get('html_content') or 
                                     detail.get('content') or 
                                     detail.get('text', '') or
                                     subject)
                            code = extract_verification_code(content)
                            if code:
                                return code
                            code = extract_verification_code(subject)
                            if code:
                                return code
        elapsed = int(time.time() - start_time)
        print(f"  Waiting... ({elapsed}s)", end='\r')
        time.sleep(3)
    print("\n⏰ Timeout waiting for email")
    return None


def save_to_csv(email: str, password: str):
    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['email', 'password', 'timestamp'])
        writer.writerow([email, password, time.strftime('%Y-%m-%d %H:%M:%S')])
    print(f"✅ Saved to {CSV_FILE}")


def check_and_handle_error(driver, max_retries=5):
    for attempt in range(max_retries):
        try:
            page_source = driver.page_source.lower()
            error_keywords = ['出错', 'error', 'timed out', 'operation timeout', 'route error', 'invalid content']
            has_error = any(keyword in page_source for keyword in error_keywords)
            if has_error:
                try:
                    retry_btn = driver.find_element(By.CSS_SELECTOR, 'button[data-dd-action-name="Try again"]')
                    print(f"⚠️ Error page detected, clicking retry (attempt {attempt + 1}/{max_retries})...")
                    driver.execute_script("arguments[0].click();", retry_btn)
                    wait_time = 5 + (attempt * 2)
                    print(f"  Waiting {wait_time}s before continuing...")
                    time.sleep(wait_time)
                    return True
                except Exception:
                    time.sleep(2)
                    continue
            return False
        except Exception as e:
            print(f"  Error check exception: {e}")
            return False
    return False


def register_one_account():
    options = uc.ChromeOptions()
    print("Initializing undetected Chrome driver...")
    driver = uc.Chrome(options=options, use_subprocess=True)
    email = None
    password = None
    success = False
    
    try:
        email = create_temp_email()
        if not email:
            print("Failed to get email, aborting.")
            return None, None, False
        
        password = generate_random_password()
        url = "https://chat.openai.com/chat"
        print(f"Navigating to {url}...")
        driver.get(url)
        time.sleep(3)
        
        wait = WebDriverWait(driver, 600)
        
        print("Waiting for signup button...")
        signup_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '[data-testid="signup-button"]')))
        signup_button.click()
        print("Clicked signup button.")
        
        print("Waiting for email input...")
        email_input = WebDriverWait(driver, 120).until(EC.visibility_of_element_located((By.ID, "email")))
        email_input.clear()
        email_input.send_keys(email)
        print(f"Entered email: {email}")
        
        print("Clicking Continue button...")
        continue_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]')))
        continue_btn.click()
        print("Clicked Continue.")
        time.sleep(2)
        
        print("Waiting for password input...")
        password_input = WebDriverWait(driver, 120).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[autocomplete="new-password"]'))
        )
        password_input.clear()
        time.sleep(0.5)
        for char in password:
            password_input.send_keys(char)
            time.sleep(0.05)
        print(f"Entered password.")
        time.sleep(2)
        
        print("Clicking Continue button...")
        for attempt in range(3):
            try:
                continue_btn = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]'))
                )
                driver.execute_script("arguments[0].click();", continue_btn)
                print("Clicked Continue.")
                break
            except Exception as e:
                print(f"  Attempt {attempt + 1} failed, retrying...")
                time.sleep(2)
        
        time.sleep(3)
        while check_and_handle_error(driver):
            time.sleep(2)
        
        time.sleep(5)
        verification_code = wait_for_verification_email(email)
        
        if not verification_code:
            verification_code = input("Please enter the verification code manually: ").strip()
        
        if not verification_code:
            print("❌ No verification code, aborting.")
            return email, password, False
        
        print("Entering verification code...")
        while check_and_handle_error(driver):
            time.sleep(2)
        
        code_input = WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[name="code"], input[placeholder*="代码"], input[aria-label*="代码"]'))
        )
        code_input.clear()
        time.sleep(0.5)
        for char in verification_code:
            code_input.send_keys(char)
            time.sleep(0.1)
        print(f"Entered code: {verification_code}")
        time.sleep(2)
        
        print("Clicking Continue button...")
        for attempt in range(3):
            try:
                continue_btn = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]'))
                )
                driver.execute_script("arguments[0].click();", continue_btn)
                print("Clicked Continue.")
                break
            except Exception as e:
                print(f"  Attempt {attempt + 1} failed, retrying...")
                time.sleep(2)
        
        time.sleep(3)
        while check_and_handle_error(driver):
            time.sleep(2)
        
        print("Waiting for name input...")
        name_input = WebDriverWait(driver, 60).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, 'input[name="name"], input[autocomplete="name"]'))
        )
        name_input.clear()
        time.sleep(0.5)
        for char in "xiaochuan sun":
            name_input.send_keys(char)
            time.sleep(0.05)
        print("Entered name: xiaochuan sun")
        time.sleep(1)
        
        print("Entering birthday...")
        time.sleep(1)
        
        year_input = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-type="year"]'))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", year_input)
        time.sleep(0.5)
        
        actions = ActionChains(driver)
        actions.click(year_input).perform()
        time.sleep(0.3)
        year_input.send_keys(Keys.CONTROL + "a")
        time.sleep(0.1)
        for char in "1990":
            year_input.send_keys(char)
            time.sleep(0.1)
        time.sleep(0.5)
        
        month_input = driver.find_element(By.CSS_SELECTOR, '[data-type="month"]')
        actions = ActionChains(driver)
        actions.click(month_input).perform()
        time.sleep(0.3)
        month_input.send_keys(Keys.CONTROL + "a")
        time.sleep(0.1)
        for char in "05":
            month_input.send_keys(char)
            time.sleep(0.1)
        time.sleep(0.5)
        
        day_input = driver.find_element(By.CSS_SELECTOR, '[data-type="day"]')
        actions = ActionChains(driver)
        actions.click(day_input).perform()
        time.sleep(0.3)
        day_input.send_keys(Keys.CONTROL + "a")
        time.sleep(0.1)
        for char in "12":
            day_input.send_keys(char)
            time.sleep(0.1)
        
        print("Entered birthday: 1990/05/12")
        time.sleep(1)
        
        print("Clicking final Continue button...")
        continue_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[type="submit"]')))
        continue_btn.click()
        print("Clicked Continue.")
        
        save_to_csv(email, password)
        
        print("\n📨 Sending team invitation...")
        auto_invite_to_team(email)
        
        print("\n⏳ Waiting for team invitation to take effect...")
        time.sleep(5)
        
        perform_codex_authorization(driver, email, password)
        
        print("\n" + "="*50)
        print("🎉 Registration & Codex Authorization completed!")
        print(f"Email: {email}")
        print(f"Password: {password}")
        print("="*50)
        
        success = True
        print("Waiting before closing...")
        time.sleep(10)
        
    except Exception as e:
        print(f"An error occurred: {e}")
        if email and password:
            save_to_csv(email, password)
    finally:
        print("Closing browser...")
        driver.quit()
    
    return email, password, success


def run_batch():
    print("\n" + "="*60)
    print(f"🚀 Starting batch registration for {TOTAL_ACCOUNTS} accounts")
    print("="*60 + "\n")
    
    success_count = 0
    fail_count = 0
    registered_accounts = []
    
    for i in range(TOTAL_ACCOUNTS):
        print("\n" + "#"*60)
        print(f"📝 Registering account {i + 1}/{TOTAL_ACCOUNTS}")
        print("#"*60 + "\n")
        
        email, password, success = register_one_account()
        
        if success:
            success_count += 1
            registered_accounts.append((email, password))
        else:
            fail_count += 1
        
        print("\n" + "-"*40)
        print(f"📊 Progress: {i + 1}/{TOTAL_ACCOUNTS}")
        print(f"   ✅ Success: {success_count}")
        print(f"   ❌ Failed: {fail_count}")
        print("-"*40)
        
        if i < TOTAL_ACCOUNTS - 1:
            wait_time = random.randint(5, 15)
            print(f"\n⏳ Waiting {wait_time}s before next registration...")
            time.sleep(wait_time)
    
    print("\n" + "="*60)
    print("🏁 BATCH REGISTRATION COMPLETED")
    print("="*60)
    print(f"Total: {TOTAL_ACCOUNTS}")
    print(f"✅ Success: {success_count}")
    print(f"❌ Failed: {fail_count}")
    print("\nRegistered accounts:")
    for email, password in registered_accounts:
        print(f"  - {email}")
    print("="*60)


if __name__ == "__main__":
    run_batch()
