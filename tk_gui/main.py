"""CustomTkinter 图形界面主程序。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from .io_redirect import 输出重定向
from . import runtime
from . import worker


@dataclass
class 运行状态:
    正在运行: bool = False
    停止事件: threading.Event | None = None
    线程: threading.Thread | None = None


class 主窗口(ctk.CTkFrame):
    def __init__(self, master: ctk.CTk):
        super().__init__(master)
        self.master = master
        self.pack(fill="both", expand=True)

        self._run_dirs = runtime.获取运行目录()
        runtime.切换工作目录(self._run_dirs.工作目录)

        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._state = 运行状态()

        self._build_ui()
        self._refresh_team_list()
        self._start_log_poller()

    # ---------------- UI 构建 ----------------
    def _build_ui(self) -> None:
        self.master.title("OpenAI Team 自动批量注册")
        self.master.geometry("1100x750")

        # 使用 CTkTabview 替代 ttk.Notebook
        self._tabview = ctk.CTkTabview(self, segmented_button_selected_color="#3b82f6")
        self._tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self._tab_run = self._tabview.add("运行")
        self._tab_cfg = self._tabview.add("配置")

        self._build_run_tab(self._tab_run)
        self._build_cfg_tab(self._tab_cfg)

    def _build_run_tab(self, parent: ctk.CTkFrame) -> None:
        # 顶部工作目录和快捷按钮
        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=5, pady=(5, 10))

        ctk.CTkLabel(top, text=f"工作目录：{self._run_dirs.工作目录}", font=("Microsoft YaHei UI", 12)).pack(side="left")

        btns = ctk.CTkFrame(top, fg_color="transparent")
        btns.pack(side="right")

        # 快捷按钮
        ctk.CTkButton(btns, text="📁 工作目录", command=self._open_work_dir,
                      fg_color="#6366f1", hover_color="#4f46e5", width=100).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="📄 credentials", command=self._open_created_credentials,
                      fg_color="#8b5cf6", hover_color="#7c3aed", width=100).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="📄 accounts", command=self._open_accounts_csv,
                      fg_color="#06b6d4", hover_color="#0891b2", width=100).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="📄 tracker", command=self._open_tracker_json,
                      fg_color="#f59e0b", hover_color="#d97706", width=100).pack(side="left", padx=3)

        # 任务控制区
        ctrl = ctk.CTkFrame(parent)
        ctrl.pack(fill="x", padx=5, pady=5)

        ctrl_title = ctk.CTkLabel(ctrl, text="任务控制", font=("Microsoft YaHei UI", 13, "bold"))
        ctrl_title.pack(anchor="w", padx=10, pady=(10, 5))

        # 模式选择（带详细说明）
        self._mode_var = tk.StringVar(value="all")
        modes = [
            ("全部 Team", "all", "遍历所有 Team，批量创建邮箱→邀请→注册→入库"),
            ("单个 Team", "single", "只处理指定索引的 Team"),
            ("仅注册账号", "register", "只创建邮箱并注册 OpenAI，不邀请不入库"),
            ("仅邮箱+邀请", "test", "只创建邮箱并邀请到 Team，不注册"),
            ("查看状态", "status", "显示当前 Team 的处理进度"),
        ]

        row_mode = ctk.CTkFrame(ctrl, fg_color="transparent")
        row_mode.pack(fill="x", padx=10, pady=5)
        for text, val, _ in modes:
            ctk.CTkRadioButton(
                row_mode,
                text=text,
                variable=self._mode_var,
                value=val,
                command=self._on_mode_change,
                font=("Microsoft YaHei UI", 12),
            ).pack(side="left", padx=10)

        # 模式说明标签
        self._mode_desc_var = tk.StringVar(value=modes[0][2])
        mode_desc_label = ctk.CTkLabel(
            ctrl, textvariable=self._mode_desc_var,
            font=("Microsoft YaHei UI", 11), text_color="#666"
        )
        mode_desc_label.pack(anchor="w", padx=15, pady=(0, 5))

        # 保存模式说明映射
        self._mode_descriptions = {val: desc for text, val, desc in modes}

        # Team 索引
        row_team = ctk.CTkFrame(ctrl, fg_color="transparent")
        row_team.pack(fill="x", padx=10, pady=5)
        self._team_index_var = tk.IntVar(value=0)
        ctk.CTkLabel(row_team, text="Team 索引：", font=("Microsoft YaHei UI", 12)).pack(side="left")
        # CustomTkinter 没有 Spinbox，使用 ttk.Spinbox
        self._team_spin = ttk.Spinbox(row_team, from_=0, to=999, textvariable=self._team_index_var, width=6)
        self._team_spin.pack(side="left", padx=(5, 15))
        ctk.CTkButton(row_team, text="🔄 刷新列表", command=self._refresh_team_list,
                      fg_color="#8b5cf6", hover_color="#7c3aed", width=100).pack(side="left")

        # 注册数量和邮箱来源
        row_reg = ctk.CTkFrame(ctrl, fg_color="transparent")
        row_reg.pack(fill="x", padx=10, pady=(5, 10))
        self._count_var = tk.IntVar(value=4)
        ctk.CTkLabel(row_reg, text="注册数量：", font=("Microsoft YaHei UI", 12)).pack(side="left")
        self._count_spin = ttk.Spinbox(row_reg, from_=1, to=999, textvariable=self._count_var, width=6)
        self._count_spin.pack(side="left", padx=(5, 20))

        self._email_source_var = tk.StringVar(value="domain")
        ctk.CTkLabel(row_reg, text="邮箱来源：", font=("Microsoft YaHei UI", 12)).pack(side="left")
        self._rb_domain = ctk.CTkRadioButton(
            row_reg, text="域名邮箱(Cloud Mail)", variable=self._email_source_var, value="domain",
            font=("Microsoft YaHei UI", 12)
        )
        self._rb_gptmail = ctk.CTkRadioButton(
            row_reg, text="随机邮箱(GPTMail)", variable=self._email_source_var, value="gptmail",
            font=("Microsoft YaHei UI", 12)
        )
        self._rb_domain.pack(side="left", padx=(5, 15))
        self._rb_gptmail.pack(side="left")

        # 操作按钮
        act = ctk.CTkFrame(parent, fg_color="transparent")
        act.pack(fill="x", padx=5, pady=10)

        self._btn_start = ctk.CTkButton(
            act, text="▶ 开始", command=self._start_task,
            fg_color="#10b981", hover_color="#059669",
            font=("Microsoft YaHei UI", 13, "bold"), width=120, height=40
        )
        self._btn_stop = ctk.CTkButton(
            act, text="■ 停止", command=self._stop_task, state="disabled",
            fg_color="#ef4444", hover_color="#dc2626",
            font=("Microsoft YaHei UI", 13, "bold"), width=120, height=40
        )
        self._btn_start.pack(side="left", padx=5)
        self._btn_stop.pack(side="left", padx=5)

        self._status_var = tk.StringVar(value="就绪")
        ctk.CTkLabel(act, textvariable=self._status_var, font=("Microsoft YaHei UI", 12)).pack(side="left", padx=15)

        # 提示
        tip = ctk.CTkLabel(
            parent,
            text="提示：输出记录已写入程序内部存储；需要文件请在 WebView GUI 的「数据/导出」页导出。",
            font=("Microsoft YaHei UI", 11),
            text_color="#666"
        )
        tip.pack(fill="x", padx=10, pady=(0, 5))

        # 日志区
        log_frame = ctk.CTkFrame(parent)
        log_frame.pack(fill="both", expand=True, padx=5, pady=5)

        log_title = ctk.CTkLabel(log_frame, text="日志", font=("Microsoft YaHei UI", 13, "bold"))
        log_title.pack(anchor="w", padx=10, pady=(10, 5))

        self._log_text = ctk.CTkTextbox(log_frame, font=("Consolas", 11), wrap="word")
        self._log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._log_text.configure(state="disabled")

    def _build_cfg_tab(self, parent: ctk.CTkFrame) -> None:
        # 配置文件路径
        paths = ctk.CTkFrame(parent)
        paths.pack(fill="x", padx=5, pady=5)

        paths_title = ctk.CTkLabel(paths, text="配置文件", font=("Microsoft YaHei UI", 13, "bold"))
        paths_title.pack(anchor="w", padx=10, pady=(10, 5))

        self._config_path, self._team_path = runtime.获取外部配置路径(self._run_dirs)

        self._config_path_var = tk.StringVar(value=str(self._config_path))
        self._team_path_var = tk.StringVar(value=str(self._team_path))

        # config.toml 行
        row1 = ctk.CTkFrame(paths, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(row1, text="config.toml：", font=("Microsoft YaHei UI", 12), width=100).pack(side="left")
        ctk.CTkEntry(row1, textvariable=self._config_path_var, state="readonly", width=500).pack(side="left", padx=5)
        ctk.CTkButton(row1, text="📂 打开", command=self._open_config,
                      fg_color="#3b82f6", hover_color="#2563eb", width=80).pack(side="left", padx=3)
        ctk.CTkButton(row1, text="✨ 从示例生成", command=self._create_config_from_example,
                      fg_color="#10b981", hover_color="#059669", width=100).pack(side="left", padx=3)

        # team.json 行
        row2 = ctk.CTkFrame(paths, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(row2, text="team.json：", font=("Microsoft YaHei UI", 12), width=100).pack(side="left")
        ctk.CTkEntry(row2, textvariable=self._team_path_var, state="readonly", width=500).pack(side="left", padx=5)
        ctk.CTkButton(row2, text="📂 打开", command=self._open_team,
                      fg_color="#3b82f6", hover_color="#2563eb", width=80).pack(side="left", padx=3)
        ctk.CTkButton(row2, text="✨ 从示例生成", command=self._create_team_from_example,
                      fg_color="#10b981", hover_color="#059669", width=100).pack(side="left", padx=3)

        # 编辑器 Tabview
        editors = ctk.CTkTabview(parent, segmented_button_selected_color="#3b82f6")
        editors.pack(fill="both", expand=True, padx=5, pady=5)

        tab_cfg = editors.add("编辑 config.toml")
        tab_team = editors.add("编辑 team.json")

        # config.toml 编辑器
        self._cfg_text = ctk.CTkTextbox(tab_cfg, font=("Consolas", 11), wrap="none")
        self._cfg_text.pack(fill="both", expand=True, padx=5, pady=5)

        btn_cfg = ctk.CTkFrame(tab_cfg, fg_color="transparent")
        btn_cfg.pack(fill="x", padx=5, pady=5)
        ctk.CTkButton(btn_cfg, text="🔄 加载", command=self._load_config_text,
                      fg_color="#6366f1", hover_color="#4f46e5", width=100).pack(side="left", padx=3)
        ctk.CTkButton(btn_cfg, text="💾 保存", command=self._save_config_text,
                      fg_color="#10b981", hover_color="#059669", width=100).pack(side="left", padx=3)

        # team.json 编辑器
        self._team_text = ctk.CTkTextbox(tab_team, font=("Consolas", 11), wrap="none")
        self._team_text.pack(fill="both", expand=True, padx=5, pady=5)

        btn_team = ctk.CTkFrame(tab_team, fg_color="transparent")
        btn_team.pack(fill="x", padx=5, pady=5)
        ctk.CTkButton(btn_team, text="🔄 加载", command=self._load_team_text,
                      fg_color="#6366f1", hover_color="#4f46e5", width=100).pack(side="left", padx=3)
        ctk.CTkButton(btn_team, text="💾 保存", command=self._save_team_text,
                      fg_color="#10b981", hover_color="#059669", width=100).pack(side="left", padx=3)

        # 初始加载
        self._load_config_text(silent=True)
        self._load_team_text(silent=True)

    # ---------------- 日志输出 ----------------
    def _append_log(self, text: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _start_log_poller(self) -> None:
        def poll():
            try:
                while True:
                    msg = self._log_q.get_nowait()
                    self._append_log(msg)
            except queue.Empty:
                pass
            self.after(80, poll)

        poll()

    # ---------------- 配置文件操作 ----------------
    def _choose_config(self) -> None:
        p = filedialog.askopenfilename(title="选择 config.toml", filetypes=[("TOML", "*.toml"), ("所有文件", "*.*")])
        if p:
            self._config_path_var.set(p)

    def _choose_team(self) -> None:
        p = filedialog.askopenfilename(title="选择 team.json", filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if p:
            self._team_path_var.set(p)

    def _open_config(self) -> None:
        self._open_path(Path(self._config_path_var.get()))

    def _open_team(self) -> None:
        self._open_path(Path(self._team_path_var.get()))

    def _create_config_from_example(self) -> None:
        dst = Path(self._config_path_var.get())
        if dst.exists():
            if not messagebox.askyesno("确认", "config.toml 已存在，是否覆盖？"):
                return
        tpl = runtime.获取模板路径(self._run_dirs, "config.toml.example")
        if not tpl or not tpl.exists():
            messagebox.showerror("错误", "找不到 config.toml.example 模板文件")
            return
        dst.write_text(tpl.read_text(encoding="utf-8"), encoding="utf-8")
        self._load_config_text()
        messagebox.showinfo("完成", f"已生成：{dst}")

    def _create_team_from_example(self) -> None:
        dst = Path(self._team_path_var.get())
        if dst.exists():
            if not messagebox.askyesno("确认", "team.json 已存在，是否覆盖？"):
                return
        tpl = runtime.获取模板路径(self._run_dirs, "team.json.example")
        if not tpl or not tpl.exists():
            messagebox.showerror("错误", "找不到 team.json.example 模板文件")
            return
        dst.write_text(tpl.read_text(encoding="utf-8"), encoding="utf-8")
        self._load_team_text()
        messagebox.showinfo("完成", f"已生成：{dst}")

    def _load_config_text(self, silent: bool = False) -> None:
        p = Path(self._config_path_var.get())
        if not p.exists():
            if not silent:
                messagebox.showwarning("提示", f"文件不存在：{p}")
            return
        self._cfg_text.delete("1.0", "end")
        self._cfg_text.insert("1.0", p.read_text(encoding="utf-8", errors="replace"))

    def _save_config_text(self) -> None:
        p = Path(self._config_path_var.get())
        p.write_text(self._cfg_text.get("1.0", "end"), encoding="utf-8")
        messagebox.showinfo("完成", f"已保存：{p}")

    def _load_team_text(self, silent: bool = False) -> None:
        p = Path(self._team_path_var.get())
        if not p.exists():
            if not silent:
                messagebox.showwarning("提示", f"文件不存在：{p}")
            return
        self._team_text.delete("1.0", "end")
        self._team_text.insert("1.0", p.read_text(encoding="utf-8", errors="replace"))

    def _save_team_text(self) -> None:
        p = Path(self._team_path_var.get())
        raw = self._team_text.get("1.0", "end")
        try:
            json.loads(raw)
        except Exception as e:
            messagebox.showerror("错误", f"team.json 不是有效 JSON：{e}")
            return
        p.write_text(raw, encoding="utf-8")
        messagebox.showinfo("完成", f"已保存：{p}")
        self._refresh_team_list()

    # ---------------- 运行控制 ----------------
    def _on_mode_change(self) -> None:
        val = self._mode_var.get()
        # 更新模式说明
        if hasattr(self, '_mode_descriptions'):
            self._mode_desc_var.set(self._mode_descriptions.get(val, ""))
        # 控制 Team 索引输入框
        self._team_spin.configure(state="normal" if val == "single" else "disabled")
        # 控制注册相关选项
        reg_state = "normal" if val == "register" else "disabled"
        self._count_spin.configure(state=reg_state)
        self._rb_domain.configure(state=reg_state)
        self._rb_gptmail.configure(state=reg_state)

    def _refresh_team_list(self) -> None:
        """尝试解析 team.json 来更新可选索引范围。"""
        team_path = Path(self._team_path_var.get())
        if not team_path.exists():
            self._team_spin.configure(to=0)
            return
        try:
            data = json.loads(team_path.read_text(encoding="utf-8"))
            teams = data if isinstance(data, list) else [data]
            max_idx = max(0, len(teams) - 1)
            self._team_spin.configure(to=max_idx)
        except Exception:
            self._team_spin.configure(to=999)

        self._on_mode_change()

    def _start_task(self) -> None:
        if self._state.正在运行:
            return

        mode = self._mode_var.get()
        team_idx = int(self._team_index_var.get())
        count = int(self._count_var.get())
        email_source = self._email_source_var.get().strip()

        # 确保配置存在
        if mode in ["all", "single", "test", "register"]:
            if not Path(self._config_path_var.get()).exists():
                messagebox.showerror("错误", "找不到 config.toml，请先在【配置】页生成或选择。")
                return
        if mode in ["all", "single", "test"]:
            if not Path(self._team_path_var.get()).exists():
                messagebox.showerror("错误", "找不到 team.json，请先在【配置】页生成或选择。")
                return
        if mode == "register" and count <= 0:
            messagebox.showerror("错误", "注册数量必须大于 0。")
            return

        stop_event = threading.Event()
        self._state = 运行状态(正在运行=True, 停止事件=stop_event, 线程=None)

        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._status_var.set("运行中…")

        def target():
            with 输出重定向(self._log_q, strip_ansi=True):
                try:
                    if mode == "all":
                        worker.run_all(stop_event)
                    elif mode == "single":
                        worker.run_single(team_idx, stop_event)
                    elif mode == "register":
                        worker.batch_register_openai(count=count, email_source=email_source, stop_event=stop_event)
                    elif mode == "test":
                        worker.test_email_only(stop_event)
                    elif mode == "status":
                        worker.show_status()
                    else:
                        print(f"未知模式：{mode}")
                except worker.任务异常 as e:
                    print(f"任务错误：{e}")
                except Exception as e:
                    print(f"未处理异常：{e}")
                finally:
                    self.after(0, self._on_task_finished)

        th = threading.Thread(target=target, name="oai-worker", daemon=True)
        self._state.线程 = th
        th.start()

    def _stop_task(self) -> None:
        if not self._state.正在运行 or not self._state.停止事件:
            return
        self._status_var.set("正在停止…")
        self._state.停止事件.set()

    def _on_task_finished(self) -> None:
        self._state.正在运行 = False
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._status_var.set("已结束")

    # ---------------- 打开文件/目录 ----------------
    def _open_work_dir(self) -> None:
        self._open_path(self._run_dirs.工作目录)

    def _open_accounts_csv(self) -> None:
        self._open_path(self._run_dirs.工作目录 / "accounts.csv")

    def _open_tracker_json(self) -> None:
        self._open_path(self._run_dirs.工作目录 / "team_tracker.json")

    def _open_created_credentials(self) -> None:
        self._open_path(self._run_dirs.工作目录 / "created_credentials.csv")

    def _open_path(self, p: Path) -> None:
        try:
            if not p.exists():
                messagebox.showwarning("提示", f"路径不存在：{p}")
                return
            os.startfile(str(p))  # Windows 专用
        except Exception as e:
            messagebox.showerror("错误", f"无法打开：{p}\n{e}")


def main() -> None:
    # 设置外观模式和颜色主题
    ctk.set_appearance_mode("light")  # light / dark / system
    ctk.set_default_color_theme("blue")  # blue / green / dark-blue

    root = ctk.CTk()
    app = 主窗口(root)
    app._on_mode_change()
    root.mainloop()


if __name__ == "__main__":
    main()
