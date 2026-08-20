const SVG_ATTRS =
  'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';

const ICONS = {
  blocked: `<svg viewBox="0 0 24 24" ${SVG_ATTRS}><path d="M12 3 2.5 20h19z"/><path d="M12 9v5"/><path d="M12 17.5v.01"/></svg>`,
  working: `<svg viewBox="0 0 24 24" ${SVG_ATTRS}><path d="M3 12h4l2-6 4 12 2-6h6"/></svg>`,
  settled: `<svg viewBox="0 0 24 24" ${SVG_ATTRS}><circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/></svg>`,
  agent: `<svg viewBox="0 0 24 24" ${SVG_ATTRS}><rect x="5" y="8" width="14" height="10" rx="2"/><path d="M12 8V5"/><circle cx="12" cy="4" r="1.3"/><path d="M9 13v.01"/><path d="M15 13v.01"/></svg>`,
  window: `<svg viewBox="0 0 24 24" ${SVG_ATTRS}><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3"/><path d="M13 15h4"/></svg>`,
  reply: `<svg viewBox="0 0 24 24" ${SVG_ATTRS}><path d="M9 14 4 9l5-5"/><path d="M4 9h9a7 7 0 0 1 7 7v3"/></svg>`,
};

const COLUMNS = [
  ["blocked", "待确认", "BLOCKED", ICONS.blocked, "等待你确认 / 输入"],
  ["working", "执行中", "WORKING", ICONS.working, "正在跑"],
  ["settled", "已就绪", "SETTLED", ICONS.settled, "空闲 / 完成"],
];

const state = {
  snapshot: null,
  online: false,
  view: "board",
  family: "all",
  selected: null, // { pane_id, title, agent_label, kind }
  sending: false,
  outputKey: null,
  lastViewKey: null,
  lastFingerprint: null,
  lastBlockedCount: 0,
  cleanup: {
    threshold: 1800, // 0 = 不限 / 300 = 5m / 1800 = 30m / 7200 = 2h
    scan: null, // 最近一次 cleanup_scan 的结果
    checked: new Set(), // 勾选的 pane_id
    applying: false,
  },
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

function statusIcon(tone) {
  if (tone === "blocked") return ICONS.blocked;
  if (tone === "working") return ICONS.working;
  if (tone === "settled") return ICONS.settled;
  return ICONS.window;
}

function card(item) {
  const selected = state.selected && state.selected.pane_id === item.pane_id;
  const isAgent = item.kind === "agent";
  const replyBtn = isAgent
    ? `<button class="card-reply" data-reply="${esc(item.pane_id)}" title="回复该 Agent" aria-label="回复该 Agent">${ICONS.reply}</button>`
    : "";
  const tone = isAgent
    ? ["idle", "done"].includes(item.status) ? "settled" : item.status || "unknown"
    : "window";
  const kindIcon = isAgent ? ICONS.agent : ICONS.window;
  const strongTitle = item.secondary_title || item.title;
  const description =
    [item.activity_title, item.secondary_title, item.title, item.workspace].find((t) => t && t !== strongTitle) || "";
  const descHtml = description ? `<p class="card-desc">${esc(description)}</p>` : "";
  const cwd = item.project || item.cwd_short || "";
  const metaParts = [item.tab, cwd, item.last_active_label].filter(Boolean);
  // 框架标签（OMP / PI / Claude…）退居角落：小号、弱化、小写，不再占整行
  const cornerTag = item.agent_label
    ? `<span class="card-corner" title="框架：${esc(item.agent_label)}">${kindIcon}<span class="card-corner-text">${esc(String(item.agent_label).toLowerCase())}</span></span>`
    : "";
  return `
    <article class="card tone-${esc(tone)} ${item.focused ? "focused" : ""} ${selected ? "selected" : ""}"
      data-pane="${esc(item.pane_id)}"
      data-active="${item.activity_active ? "true" : "false"}"
      tabindex="0"
      aria-label="${esc(strongTitle + " · " + item.agent_label + " · " + item.status_label)}"
      title="${esc(item.terminal_title_raw || item.terminal_title || item.title)}">
      <div class="card-head">
        <h3 class="title">${esc(strongTitle)}</h3>
        ${cornerTag}
      </div>
      ${descHtml}
      <div class="card-meta">
        <span class="card-pill">${esc(item.status_label)}${item.focused ? " · 当前" : ""}</span>
        <span class="card-meta-icon">${statusIcon(tone)}</span>
        <span class="card-meta-text"><strong>${esc(item.workspace)}</strong>${metaParts.length ? `<span>·</span>${esc(metaParts.join(" · "))}` : ""}</span>
        ${replyBtn}
      </div>
      <div class="activity-rail" aria-hidden="true"><i></i></div>
    </article>
  `;
}

function renderStats(snapshot) {
  const c = snapshot?.counts || {};
  const spaces = snapshot?.spaces || [];
  const connection = state.online ? "1" : "0";
  $("rail-stats").innerHTML = [
    ["connection", connection, "连接", state.online ? "" : "err"],
    ["agents", c.agents ?? 0, "Agents", ""],
    ["windows", c.windows ?? 0, "Windows", ""],
    ["workspaces", spaces.length, "Workspaces", ""],
  ]
    .map(
      ([cls, val, label, extra]) =>
        `<div class="rail-stat ${cls} ${extra}"><span>${label}</span><b>${esc(val)}</b></div>`
    )
    .join("");
  $("nav-count-board").textContent = c.agents ?? 0;
  $("nav-count-spaces").textContent = spaces.length;
  $("nav-count-windows").textContent = c.windows ?? 0;
}

function setHeaderStatus() {
  const sys = $("sys-status");
  if (state.online) {
    sys.textContent = "LIVE";
    sys.classList.remove("err");
    $("agents-online").textContent = state.snapshot?.counts?.agents ?? 0;
  } else {
    sys.textContent = "OFFLINE";
    sys.classList.add("err");
    const agents = state.snapshot?.counts?.agents;
    $("agents-online").textContent = agents == null ? "—" : agents;
  }
}

function renderFilters(snapshot) {
  const chips = [{ key: "all", label: "全部", count: (snapshot.items || []).length }, ...families(snapshot.items || [])];
  $("filters").innerHTML = chips
    .map(
      (chip) =>
        `<button class="chip ${state.family === chip.key ? "on" : ""}" data-family="${esc(chip.key)}"><span>${esc(chip.label)}</span><span class="chip-count">${chip.count}</span></button>`
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
  $("stage").innerHTML = visibleColumns.map(([key, title, code, icon, hint]) => {
    const items = key === "blocked" ? blockedItems : (columns[key] || []).filter(matches);
    const body = items.length ? items.map(card).join("") : `<div class="empty">这一列暂时是空的</div>`;
    return `<section class="col ${key} ${appear}"><div class="col-head"><strong>${icon}<span>${title}</span></strong><em><span class="col-code">${code}</span><span class="col-count">${items.length}</span></em></div><div class="col-cards" data-col="${key}">${body}</div></section>`;
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
  state.online = false;
  $("pulse").classList.add("err");
  setHeaderStatus();
  renderStats(state.snapshot);
  const detail = message ? ` · ${message}` : "";
  $("meta").textContent = `连接暂时中断 · 保留上次数据 · 自动重试中${detail}`;
}

function captureScroll() {
  const stage = $("stage");
  const active = document.activeElement;
  const focusedCard = active?.closest?.("[data-pane]");
  const focus = focusedCard && stage.contains(active)
    ? {
        paneId: focusedCard.dataset.pane,
        reply: Boolean(active.closest("[data-reply]")),
      }
    : null;
  const positions = {
    stageTop: stage.scrollTop,
    stageLeft: stage.scrollLeft,
    focus,
  };
  document.querySelectorAll(".col-cards").forEach((el) => {
    positions[`col-${el.dataset.col}`] = el.scrollTop;
  });
  return positions;
}

function restoreScroll(positions) {
  const stage = $("stage");
  if (positions.focus) {
    const cardEl = [...stage.querySelectorAll("[data-pane]")]
      .find((el) => el.dataset.pane === positions.focus.paneId);
    const focusTarget = positions.focus.reply
      ? cardEl?.querySelector("[data-reply]")
      : cardEl;
    if (focusTarget) {
      try {
        focusTarget.focus({ preventScroll: true });
      } catch {
        focusTarget.focus();
      }
    }
  }
  stage.scrollTop = positions.stageTop ?? 0;
  stage.scrollLeft = positions.stageLeft ?? 0;
  document.querySelectorAll(".col-cards").forEach((el) => {
    el.scrollTop = positions[`col-${el.dataset.col}`] ?? 0;
  });
}

function render(snapshot, force = false) {
  if (snapshot.ok === false) {
    state.online = false;
    if (state.snapshot?.ok) {
      markOffline(snapshot.error || "采集失败");
      return;
    }
    $("clock").textContent = snapshot.clock || "--:--:--";
    markOffline(snapshot.error || "无法读取 Herdr 状态");
    $("stage").innerHTML = `<div class="error">${esc(snapshot.error || "无法读取 Herdr 状态")}<br><small>看板会自动重连</small></div>`;
    return;
  }

  const connectionChanged = !state.online;
  state.online = true;
  state.snapshot = snapshot;
  $("clock").textContent = snapshot.clock || "--:--:--";
  $("pulse").classList.remove("err");
  $("meta").textContent = `v${snapshot.version || "?"} · ${snapshot.updated_at || ""}`;
  setHeaderStatus();

  const viewKey = `${state.view}|${state.family}`;
  const viewChanged = state.lastViewKey !== viewKey;
  const dataChanged = snapshot.fingerprint !== state.lastFingerprint;
  if (!dataChanged && !viewChanged && !force) {
    // 数据没变：只更新轻量状态；重连时同步侧栏连接指示。
    if (connectionChanged) renderStats(snapshot);
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
    const snapshot = await res.json();
    render(snapshot);
    if (pendingSelect && snapshot.ok && findItem(pendingSelect)) {
      openComposerFor(pendingSelect);
      pendingSelect = null;
    }
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
  const paneId = state.selected?.pane_id;
  $("composer").hidden = true;
  state.outputKey = null;
  $("composer-output").hidden = true;
  if (paneId) {
    requestAnimationFrame(() => {
      const cardEl = [...$("stage").querySelectorAll("[data-pane]")]
        .find((el) => el.dataset.pane === paneId);
      const focusTarget = cardEl?.querySelector("[data-reply]") || cardEl;
      if (!focusTarget) return;
      try {
        focusTarget.focus({ preventScroll: true });
      } catch {
        focusTarget.focus();
      }
    });
  }
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
  const firstForSelection = state.outputKey === null || !state.outputKey.startsWith(`${item.pane_id}\u0000`);
  if (state.outputKey === key) return;
  state.outputKey = key;
  box.hidden = false;
  $("composer-output-head").textContent = text
    ? `最近输出 · ${item.last_output_label || "刚刚"}`
    : "最近输出 · 暂无";
  const outputText = $("composer-output-text");
  const nearBottom = outputText.scrollHeight - outputText.scrollTop - outputText.clientHeight < 48;
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

/* ---------- 释放闲置 Pane ---------- */

async function fetchCleanup(idle) {
  const res = await fetch(`/api/cleanup?idle=${encodeURIComponent(idle)}`, { cache: "no-store" });
  const payload = await res.json();
  if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
  return payload;
}

function updateCleanupBadge(count) {
  const badge = $("cleanup-count");
  if (!badge) return;
  badge.textContent = count > 0 ? String(count) : "";
  badge.hidden = !(count > 0);
}

// 懒刷新角标：页面加载时 + 每次执行释放后各扫一次（扫描约 1s，不进 1.5s 轮询）
async function refreshCleanupCount() {
  try {
    const payload = await fetchCleanup(state.cleanup.threshold);
    updateCleanupBadge(payload.counts?.preselected ?? 0);
  } catch {
    // 服务不可用时静默降级，角标保持隐藏
    updateCleanupBadge(0);
  }
}

function cleanupSelectedCount() {
  return state.cleanup.checked.size;
}

function updateCleanupSelected() {
  const total = state.cleanup.scan?.candidates?.length ?? 0;
  const n = cleanupSelectedCount();
  $("cleanup-selected").textContent = `已选 ${n} / 共 ${total}`;
  $("cleanup-apply").disabled = n === 0 || state.cleanup.applying;
}

function renderCleanup() {
  const scan = state.cleanup.scan;
  const body = $("cleanup-body");
  const candidates = scan?.candidates || [];
  if (!candidates.length) {
    body.innerHTML = `<div class="cleanup-empty">没有可释放的闲置 Pane（换个阈值试试？）</div>`;
    $("cleanup-protected").innerHTML = "";
    $("cleanup-selected").textContent = "已选 0 / 共 0";
    $("cleanup-apply").disabled = true;
    return;
  }
  const checked = state.cleanup.checked;
  body.innerHTML = candidates
    .map((c) => {
      const riskAgent = c.risk === "agent";
      const quiet = c.quiet_label || `${c.quiet_seconds}s`;
      const meta = [c.workspace, c.tab, c.pane_id, c.process, `静默 ${quiet}`].filter(Boolean).join(" · ");
      const tags = [
        riskAgent ? `<span class="cleanup-tag tag-agent">Agent</span>` : "",
        c.in_focused_tab ? `<span class="cleanup-tag tag-warn">当前标签页</span>` : "",
      ].join("");
      const hints = c.last_in_workspace
        ? `<span class="cleanup-row-hint">→ 连带释放 workspace ${esc(c.workspace)}</span>`
        : "";
      return `
        <label class="cleanup-row ${riskAgent ? "risk-agent" : ""}" data-pane="${esc(c.pane_id)}">
          <input type="checkbox" value="${esc(c.pane_id)}" ${checked.has(c.pane_id) ? "checked" : ""}>
          <span class="cleanup-row-main">
            <span class="cleanup-row-title">${esc(c.title)}${tags}</span>
            <span class="cleanup-row-meta">${esc(meta)}</span>
            <span class="cleanup-row-reason">${esc(c.reason)}</span>
            ${hints}
          </span>
        </label>
      `;
    })
    .join("");
  const protectedList = (scan.protected || []).map((p) => `
    <li><code>${esc(p.pane_id)}</code><span>${esc(p.title)}</span><em>${esc(p.reason)}</em></li>
  `).join("");
  $("cleanup-protected").innerHTML = protectedList
    ? `<details class="cleanup-protected-details"><summary>已保护 ${(scan.protected || []).length} 项 · 不会自动释放</summary><ul>${protectedList}</ul></details>`
    : "";
  updateCleanupSelected();
}

function setAllCleanup(checked) {
  $("cleanup-body").querySelectorAll("input[type=checkbox]").forEach((box) => {
    box.checked = checked;
  });
  state.cleanup.checked = checked
    ? new Set((state.cleanup.scan?.candidates || []).map((c) => c.pane_id))
    : new Set();
  updateCleanupSelected();
}

function cleanupScanStatus(text) {
  const msg = $("cleanup-msg");
  msg.textContent = text;
  msg.className = "cleanup-msg err";
}

async function loadCleanupScan() {
  $("cleanup-msg").textContent = "";
  $("cleanup-msg").className = "cleanup-msg";
  $("cleanup-apply").textContent = "释放选中";
  $("cleanup-apply").disabled = true;
  $("cleanup-body").innerHTML = `<div class="cleanup-empty">扫描中…</div>`;
  $("cleanup-protected").innerHTML = "";
  try {
    state.cleanup.scan = await fetchCleanup(state.cleanup.threshold);
    state.cleanup.checked = new Set(
      (state.cleanup.scan.candidates || []).filter((c) => c.preselect).map((c) => c.pane_id)
    );
    updateCleanupBadge(state.cleanup.scan.counts?.preselected ?? 0);
    renderCleanup();
    return true;
  } catch (err) {
    $("cleanup-body").innerHTML = `<div class="cleanup-empty">扫描失败：${esc(err.message)}</div>`;
    return false;
  }
}

async function openCleanup() {
  const dialog = $("cleanup");
  dialog.hidden = false;
  $("cleanup-threshold").value = String(state.cleanup.threshold);
  if (!(await loadCleanupScan())) return;
  // 焦点移入面板：优先第一个勾选框，其次面板本身
  const first = dialog.querySelector("input[type=checkbox]");
  if (first) first.focus();
  else dialog.querySelector(".cleanup-dialog").focus();
}

function closeCleanup() {
  const dialog = $("cleanup");
  if (dialog.hidden) return;
  dialog.hidden = true;
  state.cleanup.applying = false;
  const openBtn = $("cleanup-open");
  if (openBtn) openBtn.focus();
}

let toastTimer = null;
function showToast(text) {
  const toast = $("toast");
  toast.textContent = text;
  toast.hidden = false;
  toast.classList.remove("toast-out");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.add("toast-out");
    setTimeout(() => {
      toast.hidden = true;
    }, 320);
  }, 4200);
}

async function applyCleanup() {
  if (state.cleanup.applying) return;
  const paneIds = [...state.cleanup.checked];
  if (!paneIds.length) return;
  state.cleanup.applying = true;
  const applyBtn = $("cleanup-apply");
  applyBtn.disabled = true;
  applyBtn.textContent = "释放中…";
  try {
    const res = await fetch("/api/cleanup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pane_ids: paneIds, idle_seconds: state.cleanup.threshold }),
    });
    const payload = await res.json();
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    const r = payload.result || {};
    const parts = [];
    if ((r.closed || []).length) parts.push(`已释放 ${r.closed.length} 个 pane`);
    if ((r.freed?.workspaces || 0) > 0) parts.push(`回收 ${r.freed.workspaces} 个 workspace`);
    if ((r.skipped || []).length) parts.push(`${r.skipped.length} 项已变为活跃，已跳过`);
    state.cleanup.applying = false;
    applyBtn.textContent = "释放选中";
    if ((r.failed || []).length) {
      // 有失败：留在面板里展示首个错误，方便重试
      cleanupScanStatus(
        `释放失败 ${r.failed.length} 项：${r.failed[0].error}${(r.closed || []).length ? `（已释放 ${r.closed.length} 项）` : ""}`
      );
      applyBtn.disabled = cleanupSelectedCount() === 0;
      load();
      refreshCleanupCount();
      return;
    }
    showToast(parts.length ? parts.join(" · ") : "没有可释放的 Pane");
    closeCleanup();
    load();
    refreshCleanupCount(); // 释放后懒刷新角标
  } catch (err) {
    state.cleanup.applying = false;
    applyBtn.textContent = "释放选中";
    applyBtn.disabled = cleanupSelectedCount() === 0;
    cleanupScanStatus(`请求失败：${err.message}`);
  }
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
  document.querySelectorAll(".modes button").forEach((el) => {
    const on = el.dataset.view === state.view;
    el.classList.toggle("on", on);
    el.setAttribute("aria-selected", on ? "true" : "false");
  });
}

document.querySelector(".modes").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) return;
  state.view = button.dataset.view;
  if (state.view === "windows") state.family = "all";
  updateModeButtons();
  if (state.snapshot) render(state.snapshot);
});

function activateCard(paneId) {
  selectPane(paneId);
  focusPane(paneId);
}

$("stage").addEventListener("click", (event) => {
  const reply = event.target.closest("[data-reply]");
  if (reply) {
    event.stopPropagation();
    openComposerFor(reply.dataset.reply);
    return;
  }
  const cardEl = event.target.closest("[data-pane]");
  if (!cardEl) return;
  activateCard(cardEl.dataset.pane);
});

$("stage").addEventListener("keydown", (event) => {
  if (event.target.closest("button, textarea, input, a")) return;
  if (event.key !== "Enter" && event.key !== " ") return;
  const cardEl = event.target.closest("[data-pane]");
  if (!cardEl) return;
  event.preventDefault();
  activateCard(cardEl.dataset.pane);
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

/* ---------- 释放闲置：事件 ---------- */

$("cleanup-open").addEventListener("click", openCleanup);
$("cleanup-close").addEventListener("click", closeCleanup);
$("cleanup-cancel").addEventListener("click", closeCleanup);
$("cleanup-apply").addEventListener("click", applyCleanup);
$("cleanup-all").addEventListener("click", () => setAllCleanup(true));
$("cleanup-none").addEventListener("click", () => setAllCleanup(false));
$("cleanup").addEventListener("click", (event) => {
  // 点击遮罩（面板外）关闭
  if (event.target === $("cleanup")) closeCleanup();
});
$("cleanup-body").addEventListener("change", (event) => {
  const box = event.target;
  if (!box.matches("input[type=checkbox]")) return;
  if (box.checked) state.cleanup.checked.add(box.value);
  else state.cleanup.checked.delete(box.value);
  updateCleanupSelected();
});
$("cleanup-threshold").addEventListener("change", async (event) => {
  state.cleanup.threshold = parseInt(event.target.value, 10) || 0;
  await loadCleanupScan();
});
document.addEventListener("keydown", (event) => {
  // Esc：关闭面板（先于其它 Esc 消费方判断，面板打开时优先）
  if (event.key === "Escape" && !$("cleanup").hidden) {
    event.preventDefault();
    closeCleanup();
    return;
  }
  // 全局快捷键 x / X 打开释放面板；输入场景与组合键一律放行
  if (event.key !== "x" && event.key !== "X") return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const target = event.target;
  if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable]")) return;
  event.preventDefault();
  if ($("cleanup").hidden) openCleanup();
});

/* ---------- 主题 ---------- */

const THEME_KEY = "herdr-portal-theme-v3";
function applyTheme(theme) {
  document.body.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  document.querySelectorAll(".themes button").forEach((el) => {
    const on = el.dataset.theme === theme;
    el.classList.toggle("on", on);
    el.setAttribute("aria-selected", on ? "true" : "false");
  });
}
applyTheme(localStorage.getItem(THEME_KEY) || "command");
document.querySelector(".themes").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-theme]");
  if (button) applyTheme(button.dataset.theme);
});

/* ---------- 品牌开场 ---------- */

const intro = $("intro");
if (intro) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion) {
    // 不播放淡出动画，但仍保留约 1.2 秒的品牌展示
    window.setTimeout(() => intro.remove(), 1200);
  } else {
    window.setTimeout(() => intro.classList.add("intro-out"), 1200);
    window.setTimeout(() => intro.remove(), 1650);
  }
}

/* ---------- 启动 ---------- */

// 支持 URL 参数：?view=windows 直接打开窗口视图；?select=<pane_id> 自动选中并展开回复区
const urlParams = new URLSearchParams(location.search);
if (urlParams.get("view") === "windows") {
  state.view = "windows";
  state.family = "all";
  updateModeButtons();
}
let pendingSelect = urlParams.get("select");

load();
refreshCleanupCount(); // 懒刷新「释放闲置」角标（不进 1.5s 轮询）
setInterval(load, 1500);
