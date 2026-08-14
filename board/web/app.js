const COLUMNS = [
  ["blocked", "待确认", "等待你确认 / 输入"],
  ["working", "执行中", "正在跑"],
  ["settled", "已就绪", "空闲 / 完成"],
];

const state = {
  snapshot: null,
  view: "board",
  family: "all",
  selected: null, // { pane_id, title, agent_label, kind }
  sending: false,
  outputKey: null,
  lastViewKey: null,
  lastFingerprint: null,
  lastBlockedCount: 0,
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function matches(item) {
  if (state.family === "all") return true;
  if (state.family === "windows") return item.kind === "window";
  return item.family === state.family || item.agent === state.family;
}

function families(items) {
  const seen = new Map();
  for (const item of items) {
    const key = item.kind === "window" ? "windows" : item.family || item.agent;
    const label = item.kind === "window" ? "窗口" : item.agent_label || item.agent;
    if (!seen.has(key)) seen.set(key, { key, label, count: 0 });
    seen.get(key).count += 1;
  }
  return [...seen.values()];
}

function card(item) {
  const selected = state.selected && state.selected.pane_id === item.pane_id;
  const replyBtn = item.kind === "agent"
    ? `<button class="card-reply" data-reply="${esc(item.pane_id)}" title="回复该 Agent">↩</button>`
    : "";
  const secondary = item.secondary_title && item.secondary_title !== item.activity_title
    ? `<p class="secondary-title"><span>↳</span>${esc(item.secondary_title)}</p>`
    : "";
  const cwd = item.project || item.cwd_short || "";
  const metaParts = [item.tab, cwd, item.last_active_label].filter(Boolean);
  const titleKind = item.pane_title ? "PANE" : item.session_title ? "SESSION" : "WINDOW";
  const tone = item.kind === "window"
    ? "window"
    : ["idle", "done"].includes(item.status) ? "settled" : item.status || "unknown";
  const activityTitle = item.activity_title || item.secondary_title || item.title;
  const tool = item.activity_tool || (item.kind === "window" ? "terminal" : "agent");
  return `
    <article class="card tone-${esc(tone)} ${item.focused ? "focused" : ""} ${selected ? "selected" : ""}"
      data-pane="${esc(item.pane_id)}"
      data-active="${item.activity_active ? "true" : "false"}"
      title="${esc(item.terminal_title_raw || item.terminal_title || item.title)}">
      <div class="card-top">
        <span class="badge ${esc(item.family)}">${esc(item.agent_label)}</span>
        <span class="card-top-right">
          <span class="card-state">${esc(item.status_label)}${item.focused ? " · 当前" : ""}</span>
          ${replyBtn}
        </span>
      </div>
      <div class="title-row">
        <h3 class="title">${esc(item.title)}</h3>
        <span class="title-kind">${titleKind}</span>
      </div>
      ${secondary}
      <section class="activity">
        <div class="activity-head">
          <span class="activity-phase"><i></i>${esc(item.activity_phase || "当前进展")}</span>
          <span class="activity-tool">${esc(tool)}</span>
        </div>
        <p class="activity-title">${esc(activityTitle)}</p>
      </section>
      <p class="meta"><strong>${esc(item.workspace)}</strong>${metaParts.length ? `<span>·</span>${esc(metaParts.join(" · "))}` : ""}</p>
    </article>
  `;
}

function renderStats(snapshot) {
  const c = snapshot.counts || {};
  $("stats").innerHTML = [
    ["blocked", c.blocked, "待确认", c.blocked > 0 ? "alert" : ""],
    ["working", c.working, "执行中", ""],
    ["idle", c.idle, "空闲", ""],
    ["done", c.done, "完成", ""],
    ["window", c.windows, "窗口", ""],
  ]
    .map(([cls, n, label, extra]) => `<div class="stat ${cls} ${extra}"><b>${n || 0}</b><span>${label}</span></div>`)
    .join("");
}

function renderFilters(snapshot) {
  const chips = [{ key: "all", label: "全部", count: (snapshot.items || []).length }, ...families(snapshot.items || [])];
  $("filters").innerHTML = chips
    .map(
      (chip) =>
        `<button class="chip ${state.family === chip.key ? "on" : ""}" data-family="${esc(chip.key)}">${esc(chip.label)} ${chip.count}</button>`
    )
    .join("");
}

function renderBoard(snapshot) {
  const columns = snapshot.columns || {};
  const blockedItems = (columns.blocked || []).filter(matches);
  const showBlocked = blockedItems.length > 0;
  const visibleColumns = showBlocked
    ? COLUMNS
    : COLUMNS.filter(([key]) => key !== "blocked");
  const appear = showBlocked && !(state.lastBlockedCount > 0) ? "col-in" : "";
  state.lastBlockedCount = blockedItems.length;

  $("stage").className = `stage board cols-${visibleColumns.length}`;
  $("stage").innerHTML = visibleColumns.map(([key, title, hint]) => {
    const items = key === "blocked" ? blockedItems : (columns[key] || []).filter(matches);
    const body = items.length ? items.map(card).join("") : `<div class="empty">这一列暂时是空的</div>`;
    return `<section class="col ${key} ${appear}"><div class="col-head"><strong>${title}</strong><em>${items.length} · ${hint}</em></div><div class="col-cards" data-col="${key}">${body}</div></section>`;
  }).join("");
}

function renderWindows(snapshot) {
  $("stage").className = "stage windows";
  const items = (snapshot.items || [])
    .filter((item) => item.kind === "window")
    .filter(matches);
  $("stage").innerHTML = items.length
    ? `<div class="windows-grid">${items.map(card).join("")}</div>`
    : `<div class="error">当前没有普通窗口 Pane（SSH / Shell）</div>`;
}

function renderSpaces(snapshot) {
  $("stage").className = "stage spaces";
  const spaces = snapshot.spaces || [];
  if (!spaces.length) {
    $("stage").innerHTML = `<div class="error">当前没有工作区</div>`;
    return;
  }
  $("stage").innerHTML = spaces
    .map((space) => {
      const items = (space.items || []).filter(matches);
      return `
        <section class="space">
          <h2>${esc(space.label)}${space.focused ? " · 当前" : ""}</h2>
          <div class="space-grid">${items.length ? items.map(card).join("") : `<div class="empty">没有匹配的 pane</div>`}</div>
        </section>
      `;
    })
    .join("");
}

function markOffline(message) {
  $("pulse").classList.add("err");
  const detail = message ? ` · ${message}` : "";
  $("meta").textContent = `连接暂时中断 · 保留上次数据 · 自动重试中${detail}`;
}

function captureScroll() {
  const positions = { stage: $("stage").scrollTop };
  document.querySelectorAll(".col-cards").forEach((el) => {
    positions[`col-${el.dataset.col}`] = el.scrollTop;
  });
  return positions;
}

function restoreScroll(positions) {
  $("stage").scrollTop = positions.stage ?? 0;
  document.querySelectorAll(".col-cards").forEach((el) => {
    el.scrollTop = positions[`col-${el.dataset.col}`] ?? 0;
  });
}

function render(snapshot, force = false) {
  if (snapshot.ok === false) {
    if (state.snapshot?.ok) {
      markOffline(snapshot.error || "采集失败");
      return;
    }
    $("clock").textContent = snapshot.clock || "--:--:--";
    markOffline(snapshot.error || "无法读取 Herdr 状态");
    $("stage").innerHTML = `<div class="error">${esc(snapshot.error || "无法读取 Herdr 状态")}<br><small>看板会自动重连</small></div>`;
    return;
  }

  state.snapshot = snapshot;
  $("clock").textContent = snapshot.clock || "--:--:--";
  $("pulse").classList.remove("err");
  $("meta").textContent = `v${snapshot.version || "?"} · ${snapshot.updated_at || ""}`;

  const viewKey = `${state.view}|${state.family}`;
  const viewChanged = state.lastViewKey !== viewKey;
  const dataChanged = snapshot.fingerprint !== state.lastFingerprint;
  if (!dataChanged && !viewChanged && !force) {
    // 数据没变：只更新时钟，不重建 DOM（省 CPU / 减少 GC 压力）
    syncComposer();
    return;
  }
  state.lastFingerprint = snapshot.fingerprint;

  // 同一视图/筛选下的数据刷新：保留滚动位置，避免刷新打断滚动
  const preserve = state.lastViewKey === viewKey;
  const scrolls = preserve ? captureScroll() : null;
  renderStats(snapshot);
  renderFilters(snapshot);
  if (state.view === "spaces") renderSpaces(snapshot);
  else if (state.view === "windows") renderWindows(snapshot);
  else renderBoard(snapshot);
  state.lastViewKey = viewKey;
  if (scrolls) restoreScroll(scrolls);
  syncComposer();
}

async function load() {
  try {
    const res = await fetch("/api/snapshot", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    render(await res.json());
  } catch (err) {
    render({ ok: false, error: String(err), clock: new Date().toLocaleTimeString() });
  }
}

async function focusPane(paneId) {
  await fetch("/api/focus", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pane_id: paneId }),
  });
  load();
}

/* ---------- 网页端输入 / 回复 ---------- */

function findItem(paneId) {
  return (state.snapshot?.items || []).find((item) => item.pane_id === paneId) || null;
}

function showComposer() {
  $("composer").hidden = false;
}

function hideComposer() {
  $("composer").hidden = true;
  state.outputKey = null;
  $("composer-output").hidden = true;
}

function syncComposer() {
  const input = $("composer-input");
  if (!state.selected) return;
  const item = findItem(state.selected.pane_id);
  if (!item) {
    hideComposer();
    return;
  }
  state.selected = { pane_id: item.pane_id, title: item.title, agent_label: item.agent_label, kind: item.kind };
  const target = `${item.agent_label} · ${item.title}`;
  $("composer-target").textContent = `发送给 ${target}`;
  if (item.kind !== "agent") {
    input.disabled = true;
    $("composer-send").disabled = true;
    setHint("该 Pane 不是 Agent，网页端暂只支持向 Agent 发送文字", "err");
  } else if (!state.sending) {
    input.disabled = false;
    $("composer-send").disabled = false;
    setHint(`将直接输入到 ${target} 的终端 · 支持粘贴多行文字`);
  }
  updateOutput(item);
}

function updateOutput(item) {
  const box = $("composer-output");
  if (item.kind !== "agent") {
    box.hidden = true;
    return;
  }
  const text = item.last_output || "";
  const key = `${item.pane_id}\u0000${text.length}\u0000${text.slice(0, 60)}\u0000${text.slice(-60)}`;
  if (state.outputKey === key) return;
  state.outputKey = key;
  box.hidden = false;
  $("composer-output-head").textContent = text
    ? `最近输出 · ${item.last_output_label || "刚刚"}`
    : "最近输出 · 暂无";
  const outputText = $("composer-output-text");
  const nearBottom = outputText.scrollHeight - outputText.scrollTop - outputText.clientHeight < 48;
  const firstForSelection = state.outputKey === null;
  if (text) {
    outputText.innerHTML = mdRender(text);
  } else {
    outputText.textContent = "该 Agent 还没有输出内容，开始执行后会实时更新。";
  }
  // 仅在首次显示或用户本来就停在底部时才自动跟随最新内容，不打断向上翻阅
  if (firstForSelection || nearBottom) {
    outputText.scrollTop = outputText.scrollHeight;
  }
}

function setHint(message, kind = "") {
  const hint = $("composer-hint");
  hint.textContent = message;
  hint.className = `composer-hint ${kind}`;
}

function selectPane(paneId) {
  const item = findItem(paneId);
  if (!item) return;
  state.selected = { pane_id: item.pane_id, title: item.title, agent_label: item.agent_label, kind: item.kind };
  if (state.snapshot) render(state.snapshot, true);
}

function openComposerFor(paneId) {
  const item = findItem(paneId);
  if (!item) return;
  state.selected = { pane_id: item.pane_id, title: item.title, agent_label: item.agent_label, kind: item.kind };
  state.outputKey = null;
  showComposer();
  syncComposer();
  if (item.kind === "agent") $("composer-input").focus();
  if (state.snapshot) render(state.snapshot, true);
}

async function sendMessage() {
  if (state.sending || !state.selected) return;
  const item = findItem(state.selected.pane_id);
  if (!item || item.kind !== "agent") return;
  const text = $("composer-input").value;
  if (!text.trim()) return;

  state.sending = true;
  $("composer-send").disabled = true;
  $("composer-input").disabled = true;
  setHint("发送中…");
  try {
    const res = await fetch("/api/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pane_id: item.pane_id, text }),
    });
    const payload = await res.json();
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    $("composer-input").value = "";
    autosize();
    setHint(`✓ 已发送 · ${payload.result?.path === "prompt" ? "已作为新输入提交" : "已模拟键盘输入"}`);
  } catch (err) {
    setHint(`✗ 发送失败 · ${err.message}`, "err");
  } finally {
    state.sending = false;
    $("composer-input").disabled = false;
    $("composer-send").disabled = false;
    $("composer-input").focus();
    load();
  }
}

function autosize() {
  const input = $("composer-input");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
}

/* ---------- 事件 ---------- */

$("filters").addEventListener("click", (event) => {
  const chip = event.target.closest("[data-family]");
  if (!chip) return;
  state.family = chip.dataset.family;
  if (state.family === "windows" && state.view !== "windows") state.view = "windows";
  else if (state.family !== "windows" && state.view === "windows") state.view = "board";
  updateModeButtons();
  if (state.snapshot) render(state.snapshot);
});

function updateModeButtons() {
  document.querySelectorAll(".modes button").forEach((el) => el.classList.toggle("on", el.dataset.view === state.view));
}

document.querySelector(".modes").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) return;
  state.view = button.dataset.view;
  if (state.view === "windows") state.family = "all";
  updateModeButtons();
  if (state.snapshot) render(state.snapshot);
});

$("stage").addEventListener("click", (event) => {
  const reply = event.target.closest("[data-reply]");
  if (reply) {
    event.stopPropagation();
    openComposerFor(reply.dataset.reply);
    return;
  }
  const cardEl = event.target.closest("[data-pane]");
  if (!cardEl) return;
  const paneId = cardEl.dataset.pane;
  selectPane(paneId);
  focusPane(paneId);
});

$("composer-close").addEventListener("click", hideComposer);

$("composer-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendMessage();
  } else if (event.key === "Escape") {
    event.preventDefault();
    hideComposer();
  }
});

$("composer-input").addEventListener("input", autosize);

$("composer-send").addEventListener("click", sendMessage);

/* ---------- 主题 ---------- */

const THEME_KEY = "herdr-portal-theme";
function applyTheme(theme) {
  document.body.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  $("theme-toggle").textContent = theme === "dark" ? "切浅色" : "切深色";
}
applyTheme(localStorage.getItem(THEME_KEY) || "light");
$("theme-toggle").addEventListener("click", () => {
  applyTheme(document.body.dataset.theme === "dark" ? "light" : "dark");
});

/* ---------- 启动 ---------- */

load();
setInterval(load, 1500);
