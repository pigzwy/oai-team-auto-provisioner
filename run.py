# ==================== 主入口文件 ====================
# ChatGPT Team 批量注册自动化 - 主程序
#
# 流程:
#   1. 检查未完成账号 (自动恢复)
#   2. 批量创建邮箱 (4个)
#   3. 一次性邀请到 Team
#   4. 逐个注册 OpenAI 账号
#   5. 逐个 Codex 授权
#   6. 逐个添加到 CRS
#   7. 切换下一个 Team

import time
import random
import signal
import sys
import atexit

from config import (
    TEAMS, ACCOUNTS_PER_TEAM, DEFAULT_PASSWORD,
    add_domain_to_blacklist, get_domain_from_email, is_email_blacklisted
)
from email_service import batch_create_emails, unified_create_email
from team_service import batch_invite_to_team, print_team_summary, check_available_seats, invite_single_to_team
from crs_service import crs_add_account, crs_sync_team_owners, add_team_owners_to_tracker
from browser_automation import register_and_authorize, login_and_authorize_with_otp, authorize_only
from utils import (
    save_to_csv,
    load_team_tracker,
    save_team_tracker,
    add_account_with_password,
    update_account_status,
    remove_account_from_tracker,
    get_incomplete_accounts,
    get_all_incomplete_accounts,
    print_summary,
    Timer
)
from logger import log


# ==================== 全局状态 ====================
_tracker = None
_current_results = []
_shutdown_requested = False


def _save_state():
    """保存当前状态 (用于退出时保存)"""
    global _tracker
    if _tracker:
        log.info("保存状态...", icon="save")
        save_team_tracker(_tracker)
        log.success("状态已保存到 team_tracker.json")


def _signal_handler(signum, frame):
    """处理 Ctrl+C 信号"""
    global _shutdown_requested
    if _shutdown_requested:
        log.warning("强制退出...")
        sys.exit(1)

    _shutdown_requested = True
    log.warning("收到中断信号，正在安全退出...")
    _save_state()

    if _current_results:
        log.info("当前进度:")
        print_summary(_current_results)

    log.info("提示: 下次运行将自动从未完成的账号继续")
    sys.exit(0)


# 注册信号处理器
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
atexit.register(_save_state)


def process_single_team(team: dict) -> list:
    """处理单个 Team 的完整流程

    Args:
        team: Team 配置

    Returns:
        list: 处理结果列表
    """
    global _tracker, _current_results, _shutdown_requested

    results = []
    team_name = team["name"]

    # 只在 _tracker 为空时加载，避免覆盖已有的修改
    if _tracker is None:
        _tracker = load_team_tracker()

    # 分离 Owner 和普通成员
    all_accounts = _tracker.get("teams", {}).get(team_name, [])
    owner_accounts = [acc for acc in all_accounts if acc.get("role") == "owner" and acc.get("status") != "crs_added"]
    member_accounts = [acc for acc in all_accounts if acc.get("role") != "owner"]
    
    # 统计完成数量 (只统计普通成员)
    completed_count = sum(1 for acc in member_accounts if acc.get("status") == "crs_added")
    member_count = len(member_accounts)

    # 如果普通成员已完成目标数量，且没有未完成的 Owner，跳过
    owner_incomplete = len(owner_accounts)
    if member_count >= ACCOUNTS_PER_TEAM and completed_count == member_count and owner_incomplete == 0:
        print_team_summary(team)
        log.success(f"{team_name} 已完成 {completed_count}/{ACCOUNTS_PER_TEAM} 个成员账号，跳过")
        return results

    # 有未完成的才打印详细信息
    log.header(f"开始处理 {team_name}")

    # 打印 Team 当前状态
    print_team_summary(team)

    if completed_count > 0:
        log.success(f"已完成 {completed_count} 个成员账号")

    # ========== 检查可用席位 (用于邀请新成员) ==========
    available_seats = check_available_seats(team)
    log.info(f"Team 可用席位: {available_seats}")

    # ========== 检查未完成的普通成员账号 ==========
    incomplete_members = [acc for acc in member_accounts if acc.get("status") != "crs_added"]
    
    invited_accounts = []

    if incomplete_members:
        # 有未完成的普通成员账号，优先处理
        log.warning(f"发现 {len(incomplete_members)} 个未完成成员账号:")
        for acc in incomplete_members:
            log.step(f"{acc['email']} (状态: {acc.get('status', 'unknown')})")

        invited_accounts = [{
            "email": acc["email"],
            "password": acc.get("password", DEFAULT_PASSWORD),
            "status": acc.get("status", ""),
            "role": acc.get("role", "member")
        } for acc in incomplete_members]
        log.info("继续处理未完成成员账号...", icon="start")
    elif member_count >= ACCOUNTS_PER_TEAM:
        # 普通成员已达到目标数量
        log.success(f"已有 {member_count} 个成员账号，无需邀请新成员")
    elif available_seats > 0:
        # 需要邀请新成员
        need_count = min(ACCOUNTS_PER_TEAM - member_count, available_seats)

        if need_count > 0:
            log.info(f"已有 {member_count} 个成员账号，可用席位 {available_seats}，将创建 {need_count} 个")

            # ========== 阶段 1: 批量创建邮箱 ==========
            log.section(f"阶段 1: 批量创建 {need_count} 个邮箱")

            with Timer("邮箱创建"):
                accounts = batch_create_emails(need_count)

            if len(accounts) > 0:
                # ========== 阶段 2: 批量邀请到 Team ==========
                log.section(f"阶段 2: 批量邀请 {len(accounts)} 个邮箱到 {team_name}")

                emails = [acc["email"] for acc in accounts]

                with Timer("批量邀请"):
                    invite_result = batch_invite_to_team(emails, team)

                # 更新追踪记录 (带密码) - 立即保存
                for acc in accounts:
                    if acc["email"] in invite_result.get("success", []):
                        add_account_with_password(_tracker, team_name, acc["email"], acc["password"], "invited")
                save_team_tracker(_tracker)
                log.success("邀请记录已保存")

                # 筛选成功邀请的账号
                invited_accounts = [{
                    "email": acc["email"],
                    "password": acc["password"],
                    "status": "invited",
                    "role": "member"
                } for acc in accounts if acc["email"] in invite_result.get("success", [])]
    else:
        log.warning(f"Team {team_name} 没有可用席位，无法邀请新成员")

    # ========== 阶段 3: 处理普通成员 (注册 + Codex 授权 + CRS) ==========
    if invited_accounts:
        log.section(f"阶段 3: 逐个注册 OpenAI + Codex 授权 + CRS 入库")
        member_results = process_accounts(invited_accounts, team_name)
        results.extend(member_results)

    # Owner 不在这里处理，统一放到所有 Team 处理完后

    # ========== Team 处理完成 ==========
    success_count = sum(1 for r in results if r["status"] == "success")
    if results:
        log.success(f"{team_name} 成员处理完成: {success_count}/{len(results)} 成功")
    
    # 返回未完成的 Owner 列表供后续统一处理
    return results, owner_accounts


def _get_team_by_name(team_name: str) -> dict:
    """根据名称获取 Team 配置"""
    for team in TEAMS:
        if team["name"] == team_name:
            return team
    return {}


def process_accounts(accounts: list, team_name: str) -> list:
    """处理账号列表 (注册/授权/CRS)
    
    Args:
        accounts: 账号列表 [{"email", "password", "status", "role"}]
        team_name: Team 名称
        
    Returns:
        list: 处理结果
    """
    global _tracker, _current_results, _shutdown_requested
    
    results = []
    
    for i, account in enumerate(accounts):
        if _shutdown_requested:
            log.warning("检测到中断请求，停止处理...")
            break

        email = account["email"]
        password = account["password"]
        role = account.get("role", "member")

        # 检查邮箱域名是否在黑名单中
        if is_email_blacklisted(email):
            domain = get_domain_from_email(email)
            log.warning(f"邮箱域名 {domain} 在黑名单中，跳过: {email}")
            
            # 从 tracker 中移除
            remove_account_from_tracker(_tracker, team_name, email)
            save_team_tracker(_tracker)
            
            # 尝试创建新邮箱替代
            if role != "owner":
                log.info("尝试创建新邮箱替代...")
                new_email, new_password = unified_create_email()
                if new_email and not is_email_blacklisted(new_email):
                    # 邀请新邮箱
                    if invite_single_to_team(new_email, _get_team_by_name(team_name)):
                        add_account_with_password(_tracker, team_name, new_email, new_password, "invited")
                        save_team_tracker(_tracker)
                        # 更新当前账号信息继续处理
                        email = new_email
                        password = new_password
                        account["email"] = email
                        account["password"] = password
                        log.success(f"已创建新邮箱替代: {email}")
                    else:
                        log.error("新邮箱邀请失败")
                        continue
                else:
                    log.error("无法创建有效的新邮箱")
                    continue
            else:
                continue

        log.separator("#", 50)
        log.info(f"处理账号 {i + 1}/{len(accounts)}: {email}", icon="account")
        log.separator("#", 50)

        result = {
            "team": team_name,
            "email": email,
            "password": password,
            "status": "failed",
            "crs_id": ""
        }

        # 检查是否是 Team Owner (需要 OTP 登录)
        is_team_owner = role == "owner" or account.get("status") == "team_owner"

        # 检查账号状态，决定处理流程
        account_status = account.get("status", "")
        # 已注册但未授权的状态
        need_auth_only = account_status in ["registered", "authorized", "auth_failed", "partial"]

        # 标记为处理中
        update_account_status(_tracker, team_name, email, "processing")
        save_team_tracker(_tracker)

        with Timer(f"账号 {email}"):
            if is_team_owner:
                # Team Owner: 使用 OTP 登录授权
                log.info("Team Owner 账号，使用一次性验证码登录...", icon="auth")
                auth_success, codex_data = login_and_authorize_with_otp(email)
                register_success = auth_success
            elif need_auth_only:
                # 已注册账号: 直接进行 Codex 授权
                log.info(f"已注册账号 (状态: {account_status})，直接进行 Codex 授权...", icon="auth")
                auth_success, codex_data = authorize_only(email, password)
                register_success = True
            else:
                # 新账号: 注册 + Codex 授权
                register_success, codex_data = register_and_authorize(email, password)
                
                # 检查是否是域名黑名单错误
                if register_success == "domain_blacklisted":
                    domain = get_domain_from_email(email)
                    log.error(f"域名 {domain} 不被支持，加入黑名单")
                    add_domain_to_blacklist(domain)
                    
                    # 从 tracker 中移除
                    remove_account_from_tracker(_tracker, team_name, email)
                    save_team_tracker(_tracker)
                    
                    # 尝试创建新邮箱替代
                    log.info("尝试创建新邮箱替代...")
                    new_email, new_password = unified_create_email()
                    if new_email and not is_email_blacklisted(new_email):
                        # 邀请新邮箱
                        if invite_single_to_team(new_email, _get_team_by_name(team_name)):
                            add_account_with_password(_tracker, team_name, new_email, new_password, "invited")
                            save_team_tracker(_tracker)
                            log.success(f"已创建新邮箱: {new_email}，将在下次运行时处理")
                        else:
                            log.error("新邮箱邀请失败")
                    else:
                        log.error("无法创建有效的新邮箱")
                    
                    continue  # 跳过当前账号，继续下一个

            if register_success and register_success != "domain_blacklisted":
                update_account_status(_tracker, team_name, email, "registered")
                save_team_tracker(_tracker)

                if codex_data:
                    update_account_status(_tracker, team_name, email, "authorized")
                    save_team_tracker(_tracker)

                    # 添加到 CRS
                    log.step("添加到 CRS...")
                    crs_result = crs_add_account(email, codex_data)

                    if crs_result:
                        crs_id = crs_result.get("id", "")
                        result["status"] = "success"
                        result["crs_id"] = crs_id

                        update_account_status(_tracker, team_name, email, "crs_added")
                        save_team_tracker(_tracker)

                        log.success(f"账号处理完成: {email}")
                    else:
                        log.warning("CRS 入库失败，但注册和授权成功")
                        result["status"] = "partial"
                        update_account_status(_tracker, team_name, email, "partial")
                        save_team_tracker(_tracker)
                else:
                    log.warning("Codex 授权失败")
                    result["status"] = "auth_failed"
                    update_account_status(_tracker, team_name, email, "auth_failed")
                    save_team_tracker(_tracker)
            elif register_success != "domain_blacklisted":
                if is_team_owner:
                    log.error(f"OTP 登录授权失败: {email}")
                else:
                    log.error(f"注册失败: {email}")
                update_account_status(_tracker, team_name, email, "register_failed")
                save_team_tracker(_tracker)

        # 保存到 CSV
        save_to_csv(
            email=email,
            password=password,
            team_name=team_name,
            status=result["status"],
            crs_id=result.get("crs_id", "")
        )

        results.append(result)
        _current_results.append(result)

        # 账号之间的间隔
        if i < len(accounts) - 1 and not _shutdown_requested:
            wait_time = random.randint(5, 15)
            log.info(f"等待 {wait_time}s 后处理下一个账号...", icon="wait")
            time.sleep(wait_time)

    return results


def run_all_teams():
    """主函数: 遍历所有 Team"""
    global _tracker, _current_results, _shutdown_requested

    log.header("ChatGPT Team 批量注册自动化")
    log.info(f"共 {len(TEAMS)} 个 Team 待处理", icon="team")
    log.info(f"每个 Team 邀请 {ACCOUNTS_PER_TEAM} 个账号", icon="account")
    log.info(f"统一密码: {DEFAULT_PASSWORD}", icon="code")
    log.info("按 Ctrl+C 可安全退出并保存进度")
    log.separator()

    # 先显示整体状态
    _tracker = load_team_tracker()
    all_incomplete = get_all_incomplete_accounts(_tracker)

    if all_incomplete:
        total_incomplete = sum(len(accs) for accs in all_incomplete.values())
        log.warning(f"发现 {total_incomplete} 个未完成账号，将优先处理")

    _current_results = []
    all_pending_owners = []  # 收集所有待处理的 Owner

    with Timer("全部流程"):
        # ========== 第一阶段: 处理所有 Team 的普通成员 ==========
        for i, team in enumerate(TEAMS):
            if _shutdown_requested:
                log.warning("检测到中断请求，停止处理...")
                break

            log.separator("★", 60)
            log.info(f"Team {i + 1}/{len(TEAMS)}: {team['name']}", icon="team")
            log.separator("★", 60)

            results, pending_owners = process_single_team(team)
            
            # 收集待处理的 Owner
            if pending_owners:
                for owner in pending_owners:
                    all_pending_owners.append({
                        "team_name": team["name"],
                        "email": owner["email"],
                        "password": owner.get("password", DEFAULT_PASSWORD),
                        "status": owner.get("status", "team_owner"),
                        "role": "owner"
                    })

            # Team 之间的间隔
            if i < len(TEAMS) - 1 and not _shutdown_requested:
                wait_time = 3
                log.countdown(wait_time, "下一个 Team")

        # ========== 第二阶段: 统一处理所有 Team Owner 的 CRS 授权 ==========
        if all_pending_owners and not _shutdown_requested:
            log.separator("★", 60)
            log.header(f"统一处理 Team Owner CRS 授权 ({len(all_pending_owners)} 个)")
            log.separator("★", 60)
            
            for i, owner in enumerate(all_pending_owners):
                if _shutdown_requested:
                    log.warning("检测到中断请求，停止处理...")
                    break
                
                log.separator("#", 50)
                log.info(f"Owner {i + 1}/{len(all_pending_owners)}: {owner['email']} ({owner['team_name']})", icon="account")
                log.separator("#", 50)
                
                owner_results = process_accounts([owner], owner["team_name"])
                _current_results.extend(owner_results)
                
                # Owner 之间的间隔
                if i < len(all_pending_owners) - 1 and not _shutdown_requested:
                    wait_time = random.randint(5, 15)
                    log.info(f"等待 {wait_time}s 后处理下一个 Owner...", icon="wait")
                    time.sleep(wait_time)

    # 打印总结
    print_summary(_current_results)

    return _current_results


def run_single_team(team_index: int = 0):
    """只运行单个 Team (用于测试)

    Args:
        team_index: Team 索引 (从 0 开始)
    """
    global _current_results
    
    if team_index >= len(TEAMS):
        log.error(f"Team 索引超出范围 (0-{len(TEAMS) - 1})")
        return

    team = TEAMS[team_index]
    log.info(f"单 Team 模式: {team['name']}", icon="start")

    _current_results = []
    results, pending_owners = process_single_team(team)
    _current_results.extend(results)
    
    # 单 Team 模式下也处理 Owner
    if pending_owners:
        log.section(f"处理 Team Owner ({len(pending_owners)} 个)")
        for owner in pending_owners:
            owner_data = {
                "email": owner["email"],
                "password": owner.get("password", DEFAULT_PASSWORD),
                "status": owner.get("status", "team_owner"),
                "role": "owner"
            }
            owner_results = process_accounts([owner_data], team["name"])
            _current_results.extend(owner_results)
    
    print_summary(_current_results)

    return _current_results


def test_email_only():
    """测试模式: 只创建邮箱和邀请，不注册"""
    global _tracker

    log.info("测试模式: 仅邮箱创建 + 邀请", icon="debug")

    if len(TEAMS) == 0:
        log.error("没有配置 Team")
        return

    team = TEAMS[0]
    team_name = team["name"]
    log.step(f"使用 Team: {team_name}")

    # 创建邮箱
    accounts = batch_create_emails(2)  # 测试只创建 2 个

    if accounts:
        # 批量邀请
        emails = [acc["email"] for acc in accounts]
        result = batch_invite_to_team(emails, team)

        # 保存到 tracker
        _tracker = load_team_tracker()
        for acc in accounts:
            if acc["email"] in result.get("success", []):
                add_account_with_password(_tracker, team_name, acc["email"], acc["password"], "invited")
        save_team_tracker(_tracker)

        log.success(f"测试完成: {len(result.get('success', []))} 个邀请成功")
        log.info("记录已保存到 team_tracker.json", icon="save")


def show_status():
    """显示当前状态"""
    log.header("当前状态")

    tracker = load_team_tracker()

    if not tracker.get("teams"):
        log.info("没有任何记录")
        return

    total_accounts = 0
    total_completed = 0
    total_incomplete = 0

    for team_name, accounts in tracker["teams"].items():
        log.info(f"{team_name}:", icon="team")
        status_count = {}
        for acc in accounts:
            total_accounts += 1
            status = acc.get("status", "unknown")
            status_count[status] = status_count.get(status, 0) + 1

            if status == "crs_added":
                total_completed += 1
                log.success(f"{acc['email']} ({status})")
            elif status in ["invited", "registered", "authorized", "processing"]:
                total_incomplete += 1
                log.warning(f"{acc['email']} ({status})")
            else:
                total_incomplete += 1
                log.error(f"{acc['email']} ({status})")

        log.info(f"统计: {status_count}")

    log.separator("-", 40)
    log.info(f"总计: {total_accounts} 个账号")
    log.success(f"完成: {total_completed}")
    log.warning(f"未完成: {total_incomplete}")
    log.info(f"最后更新: {tracker.get('last_updated', 'N/A')}", icon="time")


if __name__ == "__main__":
    # 启动时将 Team Owner 添加到 tracker (如果配置开启)
    # 这样 Team Owner 会走正常的 Codex 授权流程
    _tracker = load_team_tracker()
    add_team_owners_to_tracker(_tracker, DEFAULT_PASSWORD)
    save_team_tracker(_tracker)

    if len(sys.argv) > 1:
        arg = sys.argv[1]

        if arg == "test":
            # 测试模式
            test_email_only()
        elif arg == "single":
            # 单 Team 模式
            team_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0
            run_single_team(team_idx)
        elif arg == "status":
            # 显示状态
            show_status()
        else:
            log.error(f"未知参数: {arg}")
            log.info("用法:")
            log.info("python run.py          # 运行 (自动恢复未完成账号)")
            log.info("python run.py single 0 # 只运行第 1 个 Team")
            log.info("python run.py status   # 查看当前状态")
            log.info("python run.py test     # 测试模式 (仅邮箱+邀请)")
    else:
        # 默认运行所有 Team
        run_all_teams()
