"""Flet 版本 GUI（现代 UI / 跨平台）。

目标：
- 复用现有业务逻辑：`tk_gui/worker.py`
- 配置：使用内部存储（Windows 注册表）`internal_config_store.py`
- 输出：使用内部存储（SQLite）`internal_output_store.py`
- 提供：运行、日志、配置编辑、状态、数据/导出
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback
from typing import Any, Callable, Optional

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

import flet as ft

import internal_config_store
import internal_output_store
from tk_gui import runtime
from tk_gui.io_redirect import 输出重定向
from tk_gui import worker


_MAX_LOG_CHARS = 300_000


@dataclass
class _任务状态:
    运行中: bool = False
    模式: Optional[str] = None
    启动时间戳: Optional[float] = None
    结束时间戳: Optional[float] = None
    最后错误: Optional[str] = None


class _任务运行器:
    """后台任务运行器：负责启动/停止与日志捕获。"""

    def __init__(self, log_q: "queue.Queue[str]", notify: Callable[[dict[str, Any]], None]) -> None:
        self._log_q = log_q
        self._notify = notify
        self._lock = threading.Lock()
        self._stop_event: Optional[threading.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._state = _任务状态()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._thread is not None and self._thread.is_alive()),
                "mode": self._state.模式,
                "started_at": self._state.启动时间戳,
                "ended_at": self._state.结束时间戳,
                "last_error": self._state.最后错误,
            }

    def start(self, mode: str, params: dict[str, Any]) -> tuple[bool, str | None]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False, "已有任务正在运行"

            stop_event = threading.Event()
            self._stop_event = stop_event
            self._state = _任务状态(运行中=True, 模式=mode, 启动时间戳=time.time(), 最后错误=None)

            t = threading.Thread(
                target=self._run,
                args=(mode, params, stop_event),
                daemon=True,
                name="flet-gui-worker",
            )
            self._thread = t
            t.start()

        self._notify({"type": "state", "state": self.snapshot()})
        return True, None

    def stop(self) -> None:
        with self._lock:
            if self._stop_event is not None:
                self._stop_event.set()
        self._notify({"type": "toast", "message": "已发送停止请求（会在下一边界生效）"})

    def _run(self, mode: str, params: dict[str, Any], stop_event: threading.Event) -> None:
        try:
            with 输出重定向(self._log_q):
                print(f"[GUI] 开始任务: {mode}")
                self._dispatch(mode, params, stop_event)
                print(f"[GUI] 任务结束: {mode}")
        except Exception:
            err = traceback.format_exc()
            self._log_q.put(err + "\n")
            with self._lock:
                self._state.最后错误 = err
        finally:
            with self._lock:
                self._state.运行中 = False
                self._state.结束时间戳 = time.time()
                self._stop_event = None
            self._notify({"type": "state", "state": self.snapshot()})

    def _dispatch(self, mode: str, params: dict[str, Any], stop_event: threading.Event) -> None:
        if mode == "all":
            worker.run_all(stop_event)
            return

        if mode == "single":
            worker.run_single(team_index=int(params.get("team_index", 0)), stop_event=stop_event)
            return

        if mode == "test":
            worker.test_email_only(stop_event)
            return

        if mode == "status":
            worker.show_status()
            return

        if mode == "register":
            worker.batch_register_openai(
                count=int(params.get("count", 1)),
                email_source=str(params.get("email_source", "domain")),
                stop_event=stop_event,
            )
            return

        raise ValueError(f"未知模式: {mode}")


def _normalize_toml_text(text: str) -> str:
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in s.split("\n")]
    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    return out


def _load_saved_or_example(run_dirs: runtime.运行目录) -> tuple[str, str, bool]:
    payload = internal_config_store.读取配置() or {}
    config_text = payload.get("config_toml") if isinstance(payload, dict) else None
    team_text = payload.get("team_json") if isinstance(payload, dict) else None

    exists = bool(isinstance(config_text, str) and config_text.strip()) or bool(
        isinstance(team_text, str) and team_text.strip()
    )
    if exists:
        return str(config_text or ""), str(team_text or ""), True

    cfg_tpl = runtime.获取模板路径(run_dirs, "config.toml.example")
    team_tpl = runtime.获取模板路径(run_dirs, "team.json.example")
    cfg = cfg_tpl.read_text(encoding="utf-8") if cfg_tpl and cfg_tpl.exists() else ""
    team = team_tpl.read_text(encoding="utf-8") if team_tpl and team_tpl.exists() else ""
    return cfg, team, False


def _validate_and_format(config_text: str, team_text: str) -> tuple[bool, str, str, str | None]:
    try:
        tomllib.loads(config_text or "")
    except Exception as e:
        return False, config_text, team_text, f"config.toml 校验失败：{e}"

    try:
        team_obj = json.loads(team_text or "")
    except Exception as e:
        return False, config_text, team_text, f"team.json 校验失败：{e}"

    formatted_config = _normalize_toml_text(config_text or "")
    formatted_team = json.dumps(team_obj, ensure_ascii=False, indent=2) + "\n"
    return True, formatted_config, formatted_team, None


def _open_in_explorer(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
    except Exception:
        pass


def main() -> None:
    run_dirs = runtime.获取运行目录()
    runtime.切换工作目录(run_dirs.工作目录)

    log_q: "queue.Queue[str]" = queue.Queue()

    def app(page: ft.Page) -> None:
        page.title = "OAI Team Auto Provisioner (Flet)"
        page.theme_mode = ft.ThemeMode.DARK
        page.window.width = 1240
        page.window.height = 820
        page.window.min_width = 980
        page.window.min_height = 680
        page.padding = 16

        state = {"running": False, "mode": None}

        def toast(msg: str) -> None:
            page.snack_bar = ft.SnackBar(content=ft.Text(msg))
            page.snack_bar.open = True
            page.update()

        def notify(message: dict[str, Any]) -> None:
            try:
                page.pubsub.send_all(message)
            except Exception:
                pass

        runner = _任务运行器(log_q=log_q, notify=notify)

        # ---------------- 日志 ----------------
        log_box = ft.TextField(
            value="",
            multiline=True,
            read_only=True,
            expand=True,
            min_lines=10,
            border=ft.InputBorder.OUTLINE,
        )

        def _append_log(text: str) -> None:
            if not text:
                return
            log_box.value = (log_box.value or "") + text
            if len(log_box.value) > _MAX_LOG_CHARS:
                log_box.value = log_box.value[-_MAX_LOG_CHARS :]
            log_box.update()

        def _clear_log(_e=None) -> None:
            log_box.value = ""
            log_box.update()

        def _export_log(_e=None) -> None:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            filename = f"oai-team-flet-log-{ts}.txt"
            path = (run_dirs.工作目录 / filename).resolve()
            try:
                path.write_text(log_box.value or "", encoding="utf-8")
                toast(f"已导出：{filename}")
                _open_in_explorer(path)
            except Exception as e:
                toast(f"导出失败：{e}")

        # ---------------- 配置 ----------------
        cfg_text, team_text, _has_saved = _load_saved_or_example(run_dirs)
        config_editor = ft.TextField(
            value=cfg_text,
            multiline=True,
            expand=True,
            min_lines=20,
            border=ft.InputBorder.OUTLINE,
        )
        team_editor = ft.TextField(
            value=team_text,
            multiline=True,
            expand=True,
            min_lines=20,
            border=ft.InputBorder.OUTLINE,
        )

        def _load_config(_e=None) -> None:
            cfg, team, exists = _load_saved_or_example(run_dirs)
            config_editor.value = cfg
            team_editor.value = team
            config_editor.update()
            team_editor.update()
            toast("已加载已保存的配置" if exists else "已加载示例模板（尚未保存）")

        def _save_config(_e=None) -> None:
            ok, cfg, team, err = _validate_and_format(config_editor.value or "", team_editor.value or "")
            if not ok:
                toast(str(err or "校验失败"))
                return

            config_editor.value = cfg
            team_editor.value = team
            config_editor.update()
            team_editor.update()

            payload = {
                "config_toml": cfg,
                "team_json": team,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            if not internal_config_store.保存配置(payload):
                toast("保存失败：无法写入内部存储（注册表）")
                return
            toast("校验通过，并已保存到程序内部配置")

        def _create_from_example(_e=None) -> None:
            payload = internal_config_store.读取配置() or {}
            has_any = bool(
                isinstance(payload, dict)
                and (str(payload.get("config_toml", "")).strip() or str(payload.get("team_json", "")).strip())
            )
            if has_any:
                toast("已存在内部配置，未覆盖（如需覆盖请先清空配置）")
                return
            cfg_tpl = runtime.获取模板路径(run_dirs, "config.toml.example")
            team_tpl = runtime.获取模板路径(run_dirs, "team.json.example")
            if not cfg_tpl or not cfg_tpl.exists():
                toast("未找到模板：config.toml.example")
                return
            if not team_tpl or not team_tpl.exists():
                toast("未找到模板：team.json.example")
                return
            config_editor.value = cfg_tpl.read_text(encoding="utf-8")
            team_editor.value = team_tpl.read_text(encoding="utf-8")
            config_editor.update()
            team_editor.update()
            toast("已加载模板到编辑器（请点击保存配置写入内部存储）")

        # ---------------- 状态（tracker） ----------------
        status_summary = ft.Text("", selectable=True)
        status_list = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=8)

        def _render_status() -> None:
            tracker = internal_output_store.load_team_tracker()
            teams_obj = tracker.get("teams", {}) if isinstance(tracker, dict) else {}
            last_updated = tracker.get("last_updated") if isinstance(tracker, dict) else None

            if not isinstance(teams_obj, dict) or not teams_obj:
                status_summary.value = f"暂无追踪记录\nstorage: {internal_output_store.get_db_path()}\n"
                status_list.controls = []
                status_summary.update()
                status_list.update()
                return

            total = 0
            completed = 0
            incomplete = 0
            cards: list[ft.Control] = []

            for team_name, accounts in teams_obj.items():
                if not isinstance(accounts, list):
                    continue

                sc: dict[str, int] = {}
                team_total = 0
                team_done = 0
                team_todo = 0
                inc_lines: list[str] = []

                for acc in accounts:
                    if not isinstance(acc, dict):
                        continue
                    team_total += 1
                    total += 1
                    st = str(acc.get("status", "unknown"))
                    sc[st] = sc.get(st, 0) + 1
                    email = str(acc.get("email", ""))
                    if st == "crs_added":
                        team_done += 1
                        completed += 1
                    else:
                        team_todo += 1
                        incomplete += 1
                        if len(inc_lines) < 10:
                            inc_lines.append(f"- {email} ({st})")

                cards.append(
                    ft.Card(
                        content=ft.Container(
                            padding=12,
                            content=ft.Column(
                                [
                                    ft.Row(
                                        [
                                            ft.Text(str(team_name), weight=ft.FontWeight.BOLD),
                                            ft.Text(
                                                f"total {team_total} · done {team_done} · todo {team_todo}",
                                                color=ft.Colors.GREY_400,
                                            ),
                                        ],
                                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    ),
                                    ft.Text(
                                        f"status_count: {json.dumps(sc, ensure_ascii=False)}",
                                        color=ft.Colors.GREY_400,
                                        size=12,
                                    ),
                                    ft.Text("\n".join(inc_lines) if inc_lines else "无未完成账号", size=12),
                                ],
                                spacing=6,
                            ),
                        )
                    )
                )

            status_summary.value = (
                f"storage: {internal_output_store.get_db_path()}\n"
                f"last_updated: {last_updated or 'N/A'}\n"
                f"总计: {total} · 完成: {completed} · 未完成: {incomplete}\n"
            )
            status_list.controls = cards
            status_summary.update()
            status_list.update()

        # ---------------- 数据/导出 ----------------
        data_summary = ft.Text("", selectable=True)

        accounts_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("created_at")),
                ft.DataColumn(ft.Text("team")),
                ft.DataColumn(ft.Text("status")),
                ft.DataColumn(ft.Text("email")),
                ft.DataColumn(ft.Text("password")),
                ft.DataColumn(ft.Text("crs_id")),
            ],
            rows=[],
            expand=True,
        )

        credentials_table = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("created_at")),
                ft.DataColumn(ft.Text("source")),
                ft.DataColumn(ft.Text("email")),
                ft.DataColumn(ft.Text("password")),
            ],
            rows=[],
            expand=True,
        )

        def _render_data() -> None:
            counts = internal_output_store.get_counts()
            tracker = internal_output_store.load_team_tracker()
            last_updated = tracker.get("last_updated") if isinstance(tracker, dict) else None
            data_summary.value = (
                f"storage: {internal_output_store.get_db_path()}\n"
                f"账号记录: {counts.get('accounts', 0)} · 凭据记录: {counts.get('credentials', 0)} · 追踪更新时间: {last_updated or 'N/A'}\n"
                f"导出位置: {run_dirs.工作目录 / 'exports'}\n"
            )
            data_summary.update()

            accounts = internal_output_store.list_accounts(limit=50)
            credentials = internal_output_store.list_created_credentials(limit=50)

            accounts_table.rows = [
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(r.get("created_at", "")))),
                        ft.DataCell(ft.Text(str(r.get("team", "")))),
                        ft.DataCell(ft.Text(str(r.get("status", "")))),
                        ft.DataCell(ft.Text(str(r.get("email", "")))),
                        ft.DataCell(ft.Text(str(r.get("password", "")))),
                        ft.DataCell(ft.Text(str(r.get("crs_id", "")))),
                    ]
                )
                for r in accounts
            ]
            credentials_table.rows = [
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(str(r.get("created_at", "")))),
                        ft.DataCell(ft.Text(str(r.get("source", "")))),
                        ft.DataCell(ft.Text(str(r.get("email", "")))),
                        ft.DataCell(ft.Text(str(r.get("password", "")))),
                    ]
                )
                for r in credentials
            ]
            accounts_table.update()
            credentials_table.update()

        def _export_accounts(_e=None) -> None:
            path = (run_dirs.工作目录 / "exports" / "accounts.csv").resolve()
            ok = internal_output_store.export_accounts_csv(path)
            if ok:
                toast("已导出：exports/accounts.csv")
                _open_in_explorer(path)
            else:
                toast("导出失败")

        def _export_credentials(_e=None) -> None:
            path = (run_dirs.工作目录 / "exports" / "created_credentials.csv").resolve()
            ok = internal_output_store.export_created_credentials_csv(path)
            if ok:
                toast("已导出：exports/created_credentials.csv")
                _open_in_explorer(path)
            else:
                toast("导出失败")

        def _export_tracker(_e=None) -> None:
            path = (run_dirs.工作目录 / "exports" / "team_tracker.json").resolve()
            ok = internal_output_store.export_tracker_json(path)
            if ok:
                toast("已导出：exports/team_tracker.json")
                _open_in_explorer(path)
            else:
                toast("导出失败")

        # ---------------- 左侧：运行控制 ----------------
        mode_group = ft.RadioGroup(
            value="all",
            content=ft.Column(
                [
                    ft.Radio(value="all", label="全量：所有 Team 依次执行"),
                    ft.Radio(value="single", label="单 Team：按索引执行"),
                    ft.Radio(value="test", label="测试：仅邮箱创建 + 邀请"),
                    ft.Radio(value="status", label="状态：输出当前进度"),
                    ft.Radio(value="register", label="批量注册：仅注册 OpenAI"),
                ],
                spacing=6,
            ),
        )

        team_index = ft.TextField(label="Team 索引（从 0 开始）", value="0", width=220)
        single_extra = ft.Container(content=team_index, visible=False)

        reg_count = ft.TextField(label="注册数量", value="5", width=220)
        reg_source = ft.RadioGroup(
            value="domain",
            content=ft.Column(
                [
                    ft.Radio(value="domain", label="域名邮箱（Cloud Mail）"),
                    ft.Radio(value="gptmail", label="随机邮箱（GPTMail）"),
                ],
                spacing=6,
            ),
        )
        register_extra = ft.Container(
            visible=False,
            content=ft.Column(
                [
                    reg_count,
                    ft.Text("邮箱来源", weight=ft.FontWeight.BOLD, size=12, color=ft.Colors.GREY_400),
                    reg_source,
                    ft.Text(
                        "凭据会写入程序内部存储，可在「数据/导出」页查看并导出。",
                        size=12,
                        color=ft.Colors.GREY_400,
                    ),
                ],
                spacing=10,
            ),
        )

        status_chip_text = ft.Text("空闲", size=12)
        status_chip = ft.Container(
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border_radius=999,
            bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.GREY),
            content=status_chip_text,
        )

        start_btn = ft.FilledButton(text="开始", icon=ft.Icons.PLAY_ARROW)
        stop_btn = ft.FilledButton(text="停止", icon=ft.Icons.STOP, disabled=True)

        def _sync_run_ui() -> None:
            running = bool(state.get("running"))
            status_chip_text.value = "运行中" if running else "空闲"
            status_chip.bgcolor = ft.Colors.with_opacity(0.18, ft.Colors.GREEN if running else ft.Colors.GREY)
            start_btn.disabled = running
            stop_btn.disabled = not running
            mode_group.disabled = running
            team_index.disabled = running
            reg_count.disabled = running
            reg_source.disabled = running
            page.update()

        def _on_mode_change(_e=None) -> None:
            mode = mode_group.value or "all"
            single_extra.visible = mode == "single"
            register_extra.visible = mode == "register"
            single_extra.update()
            register_extra.update()

        mode_group.on_change = _on_mode_change

        def _validate_before_start(mode: str, params: dict[str, Any]) -> str | None:
            if mode not in {"all", "single", "test", "status", "register"}:
                return f"未知模式: {mode}"

            payload = internal_config_store.读取配置() or {}
            has_cfg = bool(str(payload.get("config_toml", "")).strip())
            has_team = bool(str(payload.get("team_json", "")).strip())

            if mode in {"all", "single", "test"}:
                if not has_cfg:
                    return "未保存配置：请先在「配置编辑」页填写并保存"
                if not has_team:
                    return "未保存 Team 配置：请先在「配置编辑」页填写并保存"

            if mode == "register":
                if not has_cfg:
                    return "未保存配置：请先在「配置编辑」页填写并保存"
                try:
                    c = int(params.get("count", 1))
                except Exception:
                    return "注册数量必须是整数"
                if c <= 0:
                    return "注册数量必须大于 0"
                if c > 500:
                    return "注册数量过大（>500），建议分批执行"
                src = str(params.get("email_source", "domain")).strip()
                if src not in {"domain", "gptmail"}:
                    return "邮箱来源仅支持 domain 或 gptmail"

            if mode == "single":
                try:
                    idx = int(params.get("team_index", 0))
                except Exception:
                    return "Team 索引必须是整数"
                if idx < 0:
                    return "Team 索引不能小于 0"

            return None

        def _start(_e=None) -> None:
            mode = mode_group.value or "all"
            params: dict[str, Any] = {}
            if mode == "single":
                params["team_index"] = team_index.value or "0"
            if mode == "register":
                params["count"] = reg_count.value or "1"
                params["email_source"] = reg_source.value or "domain"

            err = _validate_before_start(mode, params)
            if err:
                toast(err)
                return

            ok, reason = runner.start(mode, params)
            if not ok:
                toast(str(reason or "启动失败"))
                return
            toast("任务已启动")

        def _stop(_e=None) -> None:
            runner.stop()

        start_btn.on_click = _start
        stop_btn.on_click = _stop

        def _open_workdir(_e=None) -> None:
            _open_in_explorer(run_dirs.工作目录)

        def _open_exports(_e=None) -> None:
            p = (run_dirs.工作目录 / "exports").resolve()
            p.mkdir(parents=True, exist_ok=True)
            _open_in_explorer(p)

        left_panel = ft.Container(
            width=360,
            padding=12,
            border_radius=12,
            bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
            content=ft.Column(
                [
                    ft.Row(
                        [ft.Text("运行", size=16, weight=ft.FontWeight.BOLD), status_chip],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Divider(height=1),
                    ft.Text("模式", weight=ft.FontWeight.BOLD, size=12, color=ft.Colors.GREY_400),
                    mode_group,
                    single_extra,
                    register_extra,
                    ft.Row([start_btn, stop_btn], spacing=10),
                    ft.Divider(height=1),
                    ft.Text("快捷操作", weight=ft.FontWeight.BOLD, size=12, color=ft.Colors.GREY_400),
                    ft.Row(
                        [
                            ft.OutlinedButton("打开目录", icon=ft.Icons.FOLDER_OPEN, on_click=_open_workdir),
                            ft.OutlinedButton("打开导出", icon=ft.Icons.DOWNLOAD, on_click=_open_exports),
                        ],
                        wrap=True,
                    ),
                    ft.Text(
                        f"工作目录：{run_dirs.工作目录}\n"
                        f"配置：内部存储（注册表）\n"
                        f"输出：{internal_output_store.get_db_path()}",
                        size=12,
                        color=ft.Colors.GREY_400,
                        selectable=True,
                    ),
                ],
                scroll=ft.ScrollMode.AUTO,
                spacing=10,
            ),
        )

        # ---------------- Tabs ----------------
        tabs = ft.Tabs(
            tabs=[
                ft.Tab(
                    text="日志",
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.OutlinedButton("清空", icon=ft.Icons.DELETE_OUTLINE, on_click=_clear_log),
                                    ft.OutlinedButton("导出", icon=ft.Icons.SAVE_ALT, on_click=_export_log),
                                ],
                                spacing=10,
                            ),
                            log_box,
                        ],
                        expand=True,
                        spacing=10,
                    ),
                ),
                ft.Tab(
                    text="配置编辑",
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.FilledButton("加载配置", icon=ft.Icons.REFRESH, on_click=_load_config),
                                    ft.FilledButton("保存配置", icon=ft.Icons.SAVE, on_click=_save_config),
                                    ft.OutlinedButton(
                                        "从 example 生成（不覆盖）",
                                        icon=ft.Icons.AUTO_FIX_HIGH,
                                        on_click=_create_from_example,
                                    ),
                                ],
                                wrap=True,
                                spacing=10,
                            ),
                            ft.Row(
                                [
                                    ft.Column([ft.Text("config.toml", weight=ft.FontWeight.BOLD), config_editor], expand=True),
                                    ft.Column([ft.Text("team.json", weight=ft.FontWeight.BOLD), team_editor], expand=True),
                                ],
                                expand=True,
                            ),
                        ],
                        expand=True,
                        spacing=10,
                    ),
                ),
                ft.Tab(
                    text="状态",
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.FilledButton(
                                        "刷新",
                                        icon=ft.Icons.REFRESH,
                                        on_click=lambda e: (_render_status(), toast("状态已刷新")),
                                    )
                                ],
                                spacing=10,
                            ),
                            ft.Container(
                                padding=12,
                                border_radius=12,
                                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                                content=status_summary,
                            ),
                            status_list,
                        ],
                        expand=True,
                        spacing=10,
                    ),
                ),
                ft.Tab(
                    text="数据/导出",
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.FilledButton(
                                        "刷新",
                                        icon=ft.Icons.REFRESH,
                                        on_click=lambda e: (_render_data(), toast("数据已刷新")),
                                    ),
                                    ft.OutlinedButton("导出 accounts.csv", icon=ft.Icons.DOWNLOAD, on_click=_export_accounts),
                                    ft.OutlinedButton(
                                        "导出 created_credentials.csv",
                                        icon=ft.Icons.DOWNLOAD,
                                        on_click=_export_credentials,
                                    ),
                                    ft.OutlinedButton(
                                        "导出 team_tracker.json",
                                        icon=ft.Icons.DOWNLOAD,
                                        on_click=_export_tracker,
                                    ),
                                ],
                                wrap=True,
                                spacing=10,
                            ),
                            ft.Container(
                                padding=12,
                                border_radius=12,
                                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
                                content=data_summary,
                            ),
                            ft.Row(
                                [
                                    ft.Column([ft.Text("账号记录（最近 50）", weight=ft.FontWeight.BOLD), accounts_table], expand=True),
                                    ft.Column(
                                        [ft.Text("凭据记录（最近 50）", weight=ft.FontWeight.BOLD), credentials_table],
                                        expand=True,
                                    ),
                                ],
                                expand=True,
                            ),
                        ],
                        expand=True,
                        spacing=10,
                    ),
                ),
            ],
            expand=True,
        )

        # ---------------- PubSub：接收后台消息并更新 UI ----------------
        def on_message(_topic: str, message: Any) -> None:
            if not isinstance(message, dict):
                return
            mtype = message.get("type")
            if mtype == "log":
                _append_log(str(message.get("text", "")))
                return
            if mtype == "toast":
                toast(str(message.get("message", "")))
                return
            if mtype == "state":
                st = message.get("state") or {}
                state["running"] = bool(st.get("running"))
                state["mode"] = st.get("mode")
                _sync_run_ui()
                if not state["running"]:
                    _render_status()
                    _render_data()
                return

        page.pubsub.subscribe(on_message)

        # ---------------- 后台：转发日志队列 -> pubsub ----------------
        def log_forwarder() -> None:
            buf: list[str] = []
            while True:
                try:
                    s = log_q.get(timeout=0.25)
                    if s:
                        buf.append(s)
                    if len(buf) >= 40:
                        notify({"type": "log", "text": "".join(buf)})
                        buf.clear()
                except queue.Empty:
                    if buf:
                        notify({"type": "log", "text": "".join(buf)})
                        buf.clear()

        threading.Thread(target=log_forwarder, daemon=True, name="flet-log-forwarder").start()

        _on_mode_change()
        _sync_run_ui()
        _render_status()
        _render_data()

        page.add(ft.Row([left_panel, tabs], expand=True, spacing=12))
        toast("Flet GUI 已启动：配置/输出均为内部存储，导出在「数据/导出」页")

    ft.app(target=app)
