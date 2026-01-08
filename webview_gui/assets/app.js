function $(id) {
  return document.getElementById(id);
}

function setHidden(el, hidden) {
  el.classList.toggle("hidden", hidden);
}

function toast(msg, ms = 2600) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  window.clearTimeout(toast._t);
  toast._t = window.setTimeout(() => el.classList.add("hidden"), ms);
}

function setPill(running) {
  const pill = $("status-pill");
  if (running) {
    pill.textContent = "运行中";
    pill.classList.remove("pill-idle");
    pill.classList.add("pill-running");
  } else {
    pill.textContent = "空闲";
    pill.classList.add("pill-idle");
    pill.classList.remove("pill-running");
  }
}

function appendLog(text) {
  if (!text) return;
  const logEl = $("log");
  logEl.textContent += text;

  // 控制最大长度，避免长期运行导致内存膨胀
  const maxChars = 300_000;
  if (logEl.textContent.length > maxChars) {
    logEl.textContent = logEl.textContent.slice(-maxChars);
  }

  if ($("auto-scroll").checked) {
    logEl.scrollTop = logEl.scrollHeight;
  }
}

function switchTab(tab) {
  $("tab-logs").classList.toggle("tab-active", tab === "logs");
  $("tab-config").classList.toggle("tab-active", tab === "config");
  $("view-logs").classList.toggle("view-active", tab === "logs");
  $("view-config").classList.toggle("view-active", tab === "config");
}

function updateModeExtras() {
  const mode = $("mode").value;
  setHidden($("mode-single"), mode !== "single");
  setHidden($("mode-register"), mode !== "register");
}

async function safeCall(fn, ...args) {
  try {
    const res = await fn(...args);
    if (!res || res.ok !== true) {
      const err = res && res.error ? res.error : "未知错误";
      throw new Error(err);
    }
    return res;
  } catch (e) {
    toast(String(e));
    throw e;
  }
}

async function loadFiles() {
  const cfg = await safeCall(window.pywebview.api.read_file, "config.toml");
  const team = await safeCall(window.pywebview.api.read_file, "team.json");
  $("config-text").value = cfg.content || "";
  $("team-text").value = team.content || "";
  toast("已加载配置");
}

async function saveFiles() {
  await safeCall(window.pywebview.api.write_file, "config.toml", $("config-text").value);
  await safeCall(window.pywebview.api.write_file, "team.json", $("team-text").value);
  toast("已保存配置");
}

async function createFromExample() {
  const res = await safeCall(window.pywebview.api.create_from_example, false);
  const summary = (res.results || [])
    .map((x) => `${x.name}: ${x.status}`)
    .join("\n");
  toast(`完成：\n${summary || "无变更"}`);
  await loadFiles();
}

async function startTask() {
  const mode = $("mode").value;
  const params = {};
  if (mode === "single") {
    params.team_index = Number($("team-index").value || 0);
  }
  if (mode === "register") {
    params.count = Number($("reg-count").value || 1);
    params.email_source = $("reg-source").value;
  }

  await safeCall(window.pywebview.api.start_task, mode, params);
  toast("任务已启动");
}

async function stopTask() {
  await safeCall(window.pywebview.api.stop_task);
  toast("已发送停止请求（会在下一边界生效）");
}

async function pollLoop() {
  if (pollLoop._busy) return;
  pollLoop._busy = true;
  try {
    const res = await safeCall(window.pywebview.api.poll_logs, 400);
    appendLog(res.text || "");
    setPill(Boolean(res.running));
  } catch (_e) {
    // safeCall 已 toast，这里避免重复弹窗
  } finally {
    pollLoop._busy = false;
  }
}

function wireUi(paths) {
  $("mode").addEventListener("change", updateModeExtras);
  updateModeExtras();

  $("tab-logs").addEventListener("click", () => switchTab("logs"));
  $("tab-config").addEventListener("click", () => switchTab("config"));

  $("btn-load").addEventListener("click", loadFiles);
  $("btn-save").addEventListener("click", saveFiles);
  $("btn-from-example").addEventListener("click", createFromExample);

  $("btn-start").addEventListener("click", startTask);
  $("btn-stop").addEventListener("click", stopTask);

  $("btn-clear-log").addEventListener("click", async () => {
    await safeCall(window.pywebview.api.clear_logs);
    $("log").textContent = "";
    toast("已清空日志");
  });

  $("btn-copy-log").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("log").textContent || "");
      toast("已复制到剪贴板");
    } catch (e) {
      toast(`复制失败: ${e}`);
    }
  });

  $("btn-open-workdir").addEventListener("click", () =>
    safeCall(window.pywebview.api.open_path, ".")
  );
  $("btn-open-config").addEventListener("click", () =>
    safeCall(window.pywebview.api.open_path, "config.toml")
  );
  $("btn-open-team").addEventListener("click", () =>
    safeCall(window.pywebview.api.open_path, "team.json")
  );
  $("btn-open-credentials").addEventListener("click", () =>
    safeCall(window.pywebview.api.open_path, "created_credentials.csv")
  );

  const hint = $("paths-hint");
  hint.textContent =
    `工作目录：${paths.work_dir}\n` +
    `config：${paths.config_path}\n` +
    `team：${paths.team_path}\n` +
    `credentials：${paths.credentials_path}`;
}

window.addEventListener("pywebviewready", async () => {
  try {
    await safeCall(window.pywebview.api.ping);
    const paths = await safeCall(window.pywebview.api.get_paths);
    wireUi(paths);
    await loadFiles();

    setInterval(pollLoop, 500);
  } catch (_e) {
    // safeCall 已 toast
  }
});

