/* XAU/USD Minimal Pro Terminal */

const DEFAULT_AUTH_HASH = "9b3d275b0c617fae57e3e5bf9270181ac952904ac6575f3f79c9740a459b75f7";

const STORAGE_KEYS = {
  AUTH_HASH: "gold_dash_auth_hash",
  SESSION: "gold_dash_session",
  JOURNAL: "gold_dash_journal_v1",
  SETTINGS: "gold_dash_settings_v1",
};

const PROVIDER_DEFAULTS = {
  gemini: { model: "gemini-2.5-flash", endpoint: "" },
  groq: { model: "llama-3.3-70b-versatile", endpoint: "https://api.groq.com/openai/v1/chat/completions" },
  openrouter: { model: "google/gemini-2.0-flash-001", endpoint: "https://openrouter.ai/api/v1/chat/completions" },
  openai: { model: "gpt-4o-mini", endpoint: "https://api.openai.com/v1/chat/completions" },
};

let dashboardData = null;
let liveBrowserQuote = null;
let currentFilter = "ALL";
let currentChartTf = "15";
let activeView = "terminal";
let chatHistory = [];
let initialized = false;

// ─── Utilities ──────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function sha256Fallback(ascii) {
  const rightRotate = (v, amt) => (v >>> amt) | (v << (32 - amt));
  const maxWord = Math.pow(2, 32);
  let result = "";
  const words = [];
  const asciiBitLength = ascii.length * 8;
  const hash = (sha256Fallback.h = sha256Fallback.h || []);
  const k = (sha256Fallback.k = sha256Fallback.k || []);
  let primeCounter = k.length;
  const isComposite = {};
  for (let candidate = 2; primeCounter < 64; candidate++) {
    if (!isComposite[candidate]) {
      for (let i = 0; i < 313; i += candidate) isComposite[i] = candidate;
      hash[primeCounter] = (Math.pow(candidate, 0.5) * maxWord) | 0;
      k[primeCounter++] = (Math.pow(candidate, 1 / 3) * maxWord) | 0;
    }
  }
  ascii += "\x80";
  while ((ascii.length % 64) - 56) ascii += "\x00";
  for (let i = 0; i < ascii.length; i++) {
    words[i >> 2] |= ascii.charCodeAt(i) << (((3 - i) % 4) * 8);
  }
  words[words.length] = (asciiBitLength / maxWord) | 0;
  words[words.length] = asciiBitLength;

  const h = hash.slice(0, 8);
  for (let j = 0; j < words.length; ) {
    const w = words.slice(j, (j += 16));
    const oldHash = h.slice(0);
    for (let i = 0; i < 64; i++) {
      const w15 = w[i - 15], w2 = w[i - 2];
      const a = h[0], e = h[4];
      const temp1 =
        h[7] +
        (rightRotate(e, 6) ^ rightRotate(e, 11) ^ rightRotate(e, 25)) +
        ((e & h[5]) ^ (~e & h[6])) +
        k[i] +
        (w[i] =
          i < 16
            ? w[i]
            : (w[i - 16] +
                (rightRotate(w15, 7) ^ rightRotate(w15, 18) ^ (w15 >>> 3)) +
                w[i - 7] +
                (rightRotate(w2, 17) ^ rightRotate(w2, 19) ^ (w2 >>> 10))) |
              0);
      const temp2 =
        (rightRotate(a, 2) ^ rightRotate(a, 13) ^ rightRotate(a, 22)) +
        ((a & h[1]) ^ (a & h[2]) ^ (h[1] & h[2]));
      h.unshift((temp1 + temp2) | 0);
      h.pop();
      h[4] = (h[4] + temp1) | 0;
    }
    for (let i = 0; i < 8; i++) h[i] = (h[i] + oldHash[i]) | 0;
  }
  for (let i = 0; i < 8; i++) {
    for (let j = 3; j + 1; j--) {
      const b = (h[i] >> (j * 8)) & 255;
      result += (b < 16 ? "0" : "") + b.toString(16);
    }
  }
  return result;
}

async function sha256Hex(text) {
  if (window.crypto && window.crypto.subtle) {
    const buf = new TextEncoder().encode(text);
    const digest = await window.crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }
  return sha256Fallback(unescape(encodeURIComponent(text)));
}

function getSettings() {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEYS.SETTINGS) || "{}");
    const provider = parsed.aiProvider || "gemini";
    return {
      aiProvider: provider,
      aiKey: parsed.aiKey || "",
      aiModel: parsed.aiModel || PROVIDER_DEFAULTS[provider].model,
      aiEndpoint: parsed.aiEndpoint || "",
      geminiSearch: parsed.geminiSearch !== false,
      defaultRisk: Number(parsed.defaultRisk) > 0 ? Number(parsed.defaultRisk) : 10,
    };
  } catch {
    return {
      aiProvider: "gemini",
      aiKey: "",
      aiModel: "gemini-2.5-flash",
      aiEndpoint: "",
      geminiSearch: true,
      defaultRisk: 10,
    };
  }
}

function saveSettings(next) {
  localStorage.setItem(STORAGE_KEYS.SETTINGS, JSON.stringify(next));
}

function getJournal() {
  try {
    const arr = JSON.parse(localStorage.getItem(STORAGE_KEYS.JOURNAL) || "[]");
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function saveJournal(entries) {
  localStorage.setItem(STORAGE_KEYS.JOURNAL, JSON.stringify(entries));
}

function formatMoney(num) {
  const n = Number(num) || 0;
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

// ─── Navigation ─────────────────────────────────────────────────────────────

function switchView(viewName) {
  activeView = viewName;
  document.querySelectorAll(".hdr-tab").forEach((b) => {
    b.classList.toggle("active", b.getAttribute("data-view") === viewName);
  });
  document.getElementById("view-terminal").classList.toggle("hidden", viewName !== "terminal");
  document.getElementById("view-journal").classList.toggle("hidden", viewName !== "journal");
  if (viewName === "journal") {
    requestAnimationFrame(() => renderJournal());
  }
}

function setupNavigationAndRail() {
  document.querySelectorAll(".hdr-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.getAttribute("data-view")));
  });

  document.querySelectorAll("#rail-tabs .rail-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-rail");
      document.querySelectorAll("#rail-tabs .rail-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      ["signals", "indicators", "news"].forEach((name) => {
        document.getElementById(`rail-${name}`).classList.toggle("hidden", name !== target);
      });
    });
  });
}

// ─── Auth ───────────────────────────────────────────────────────────────────

function isLoggedIn() {
  const hash = localStorage.getItem(STORAGE_KEYS.AUTH_HASH) || DEFAULT_AUTH_HASH;
  return (
    localStorage.getItem(STORAGE_KEYS.SESSION) === hash ||
    sessionStorage.getItem(STORAGE_KEYS.SESSION) === hash
  );
}

function showApp() {
  document.getElementById("login-overlay").classList.add("hidden");
  document.getElementById("app-shell").classList.remove("hidden");
  document.getElementById("ai-fab").classList.remove("hidden");
  initDashboard();
}

function setupLogin() {
  if (isLoggedIn()) {
    showApp();
    return;
  }
  const form = document.getElementById("login-form");
  const errEl = document.getElementById("login-error");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errEl.classList.add("hidden");
    const user = document.getElementById("login-user").value.trim();
    const pass = document.getElementById("login-pass").value;
    const remember = document.getElementById("login-remember").checked;
    const targetHash = localStorage.getItem(STORAGE_KEYS.AUTH_HASH) || DEFAULT_AUTH_HASH;
    const computed = await sha256Hex(`${user}:${pass}`);

    if (computed === targetHash) {
      if (remember) localStorage.setItem(STORAGE_KEYS.SESSION, targetHash);
      else sessionStorage.setItem(STORAGE_KEYS.SESSION, targetHash);
      showApp();
    } else {
      errEl.classList.remove("hidden");
    }
  });
}

// ─── TradingView Chart ──────────────────────────────────────────────────────

function renderTradingView(tf = currentChartTf) {
  currentChartTf = tf;
  const container = document.getElementById("tv-chart-container");
  container.innerHTML = "";

  if (typeof TradingView === "undefined" || !TradingView.widget) {
    container.innerHTML = `<div class="muted" style="padding:2rem;text-align:center">TradingView chart unavailable.</div>`;
    return;
  }

  new TradingView.widget({
    autosize: true,
    symbol: "OANDA:XAUUSD",
    interval: tf,
    timezone: "Asia/Tehran",
    theme: "dark",
    style: "1",
    locale: "en",
    enable_publishing: false,
    hide_top_toolbar: false,
    hide_legend: false,
    save_image: false,
    container_id: "tv-chart-container",
    backgroundColor: "#050608",
    gridColor: "#141820",
    overrides: {
      "paneProperties.background": "#050608",
      "paneProperties.backgroundType": "solid",
      "paneProperties.vertGridProperties.color": "#141820",
      "paneProperties.horzGridProperties.color": "#141820",
      "mainSeriesProperties.candleStyle.upColor": "#0ecb81",
      "mainSeriesProperties.candleStyle.downColor": "#f6465d",
      "mainSeriesProperties.candleStyle.borderUpColor": "#0ecb81",
      "mainSeriesProperties.candleStyle.borderDownColor": "#f6465d",
      "mainSeriesProperties.candleStyle.wickUpColor": "#0ecb81",
      "mainSeriesProperties.candleStyle.wickDownColor": "#f6465d",
    },
  });
}

// ─── Data Fetching & Rendering ──────────────────────────────────────────────

async function fetchBotData() {
  try {
    const res = await fetch(`data/dashboard_data.json?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    dashboardData = await res.json();
    renderBotSnapshot();
  } catch (err) {
    console.warn("Could not load dashboard_data.json:", err);
  }
}

async function fetchLiveBrowserPrice() {
  try {
    const res = await fetch("https://scanner.tradingview.com/cfd/scan", {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body: JSON.stringify({
        symbols: { tickers: ["OANDA:XAUUSD"] },
        columns: ["close", "change"],
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const row = data?.data?.[0]?.d;
    if (row && Number(row[0]) > 0) {
      liveBrowserQuote = {
        price: Number(row[0]),
        change_24h: Number(row[1] || 0),
        source: "LIVE",
      };
      renderLiveHeaderPrice();
    }
  } catch {
    renderLiveHeaderPrice();
  }
}

function getEffectiveMarketPrice() {
  if (liveBrowserQuote?.price) return liveBrowserQuote;
  const m = dashboardData?.market;
  if (m?.price) {
    const updatedStr = dashboardData?.updated_at_tehran || "";
    const shortTs = updatedStr.length >= 16 ? updatedStr.slice(5, 16) : updatedStr || "JSON";
    return {
      price: Number(m.price),
      change_24h: Number(m.change_24h || 0),
      source: shortTs,
    };
  }
  return null;
}

function renderLiveHeaderPrice() {
  const q = getEffectiveMarketPrice();
  if (!q) return;

  const chg = Number(q.change_24h || 0);
  const priceEl = document.getElementById("live-price");
  priceEl.textContent = `$${q.price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  priceEl.className = `mono ticker-val ${chg >= 0 ? "text-bull" : "text-bear"}`;

  const chgEl = document.getElementById("live-change");
  chgEl.textContent = `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`;
  chgEl.className = `mono ticker-chg ${chg >= 0 ? "text-bull" : "text-bear"}`;

  document.getElementById("live-feed-badge").textContent = q.source;
}

function renderBotSnapshot() {
  if (!dashboardData) return;
  renderLiveHeaderPrice();

  const m = dashboardData.market || {};
  document.getElementById("last-updated-text").textContent = dashboardData.updated_at_tehran || "--";

  const biasEl = document.getElementById("htf-bias-badge");
  const bias = m.htf_bias || "NEUTRAL";
  biasEl.textContent =
    bias === "BULLISH" ? "MACRO BULL" : bias === "BEARISH" ? "MACRO BEAR" : "MACRO NEUTRAL";
  biasEl.className = `mono bias-ind ${bias === "BULLISH" ? "text-bull" : bias === "BEARISH" ? "text-bear" : "muted"}`;

  const i4h = m.indicators_4h || {};
  const i1h = m.indicators_1h || {};
  const i30 = m.indicators_30m || {};
  const i15 = m.indicators_15m || {};
  const i5 = m.indicators_5m || {};
  const rows = [
    ["RSI / ADX (4H)", i4h.rsi != null ? `${i4h.rsi} / ${i4h.adx ?? "-"}` : "--"],
    ["EMA50 / 200 (4H)", i4h.ema_50 != null ? `$${i4h.ema_50} / $${i4h.ema_200 ?? "-"}` : "--"],
    ["RSI 1H (14)", i1h.rsi ?? "--"],
    ["ADX 1H", i1h.adx ?? "--"],
    ["EMA200 (1H)", i1h.ema_200 != null ? `$${i1h.ema_200}` : "--"],
    ["BB 1H", i1h.bb_lower != null ? `${i1h.bb_lower} - ${i1h.bb_upper}` : "--"],
    ["RSI 30M (14 / 7)", i30.rsi != null ? `${i30.rsi} / ${i30.rsi_7 ?? "-"}` : "--"],
    ["Stoch 30M (K/D)", i30.osc_k != null ? `${i30.osc_k} / ${i30.osc_d}` : "--"],
    ["RSI 15M (7)", i15.rsi_7 ?? "--"],
    ["Stoch 15M (K/D)", i15.osc_k != null ? `${i15.osc_k} / ${i15.osc_d}` : "--"],
    ["EMA200 (15M)", i15.ema_200 != null ? `$${i15.ema_200}` : "--"],
    ["ATR 1H / 15M", i1h.atr != null ? `${i1h.atr} / ${i15.atr ?? "-"}` : "--"],
    ["RSI 5M (7)", i5.rsi_7 ?? "--"],
  ];

  document.getElementById("indicators-grid").innerHTML = rows
    .map(([k, v]) => `<div class="kv-row"><span class="muted">${escapeHtml(k)}</span><strong class="mono">${escapeHtml(v)}</strong></div>`)
    .join("");

  document.getElementById("bot-reason-box").textContent = m.reason_1h || "در انتظار اسکن بعدی...";

  renderNews(dashboardData.news || []);
  renderBotSignals(dashboardData.signals || []);
}

function renderNews(news) {
  const el = document.getElementById("news-list");
  if (!news.length) {
    el.innerHTML = `<div class="muted" style="padding:20px;text-align:center">خبر USD مهمی وجود ندارد.</div>`;
    return;
  }

  const sorted = [...news].sort((a, b) => {
    if (a.is_today !== b.is_today) return a.is_today ? -1 : 1;
    return (a.date_utc || "").localeCompare(b.date_utc || "");
  });

  el.innerHTML = sorted
    .map((ev) => {
      const impactTag =
        ev.impact === "High"
          ? `<span class="tag tag-bear mono">HIGH</span>`
          : `<span class="tag tag-muted mono">MED</span>`;
      const todayTag = ev.is_today ? `<span class="tag tag-bull">امروز</span>` : "";
      const meta = [
        ev.forecast ? `Fc:${ev.forecast}` : "",
        ev.previous ? `Pr:${ev.previous}` : "",
        ev.actual ? `Ac:${ev.actual}` : "",
      ]
        .filter(Boolean)
        .join(" ");

      return `
        <div class="news-item ${ev.is_today ? "today" : ""}">
          <div>
            <div style="font-weight:600;font-size:12px">${escapeHtml(ev.title)}</div>
            <div class="muted mono">${escapeHtml(ev.tehran_date)} ${escapeHtml(ev.tehran_time)}${meta ? ` • ${escapeHtml(meta)}` : ""}</div>
          </div>
          <div class="row-xs">${todayTag}${impactTag}</div>
        </div>
      `;
    })
    .join("");
}

function renderBotSignals(signals) {
  const el = document.getElementById("bot-signals-list");
  document.getElementById("signals-count-badge").textContent = String(signals.length);

  if (!signals.length) {
    el.innerHTML = `<div class="muted" style="padding:22px 12px;text-align:center">سیگنال جدیدی ثبت نشده. معاملات شخصی را در تب ژورنال ثبت کنید.</div>`;
    return;
  }

  const loggedIds = new Set(getJournal().map((j) => j.signalId).filter(Boolean));

  el.innerHTML = signals
    .map((s) => {
      const dirTag =
        s.direction === "BUY"
          ? `<span class="tag tag-bull mono">BUY</span>`
          : `<span class="tag tag-bear mono">SELL</span>`;

      let autoTag = "";
      if (s.auto_outcome === "TP_HIT") autoTag = `<span class="tag tag-bull mono">TP</span>`;
      if (s.auto_outcome === "SL_HIT") autoTag = `<span class="tag tag-bear mono">SL</span>`;

      const loggedTag = loggedIds.has(s.id) ? `<span class="tag tag-muted">ثبت‌شده</span>` : "";

      return `
        <div class="sig-row">
          <div class="sig-top">
            <div class="row-xs">
              ${dirTag}
              <strong style="font-size:12px">${escapeHtml(s.strategy_name)}</strong>
            </div>
            <div class="row-xs">
              ${autoTag}
              ${loggedTag}
              <span class="muted mono">${escapeHtml(s.timestamp_tehran)}</span>
            </div>
          </div>
          <div class="sig-lvl mono">
            <div><span class="muted">IN</span><span>$${escapeHtml(s.entry)}</span></div>
            <div><span class="muted">SL</span><span class="text-bear">$${escapeHtml(s.stop_loss)}</span></div>
            <div><span class="muted">TP</span><span class="text-bull">$${escapeHtml(s.take_profit)}</span></div>
            <div><span class="muted">R:R</span><span>1:${escapeHtml(s.rr_ratio)}</span></div>
          </div>
          <div class="sig-act-row">
            <button class="mini-act w" data-sig-action="TP" data-sig-id="${escapeHtml(s.id)}">تارگت</button>
            <button class="mini-act l" data-sig-action="SL" data-sig-id="${escapeHtml(s.id)}">استاپ</button>
            <button class="mini-act w" data-sig-action="MANUAL_PROFIT" data-sig-id="${escapeHtml(s.id)}">+ سود دستی</button>
            <button class="mini-act l" data-sig-action="MANUAL_LOSS" data-sig-id="${escapeHtml(s.id)}">- ضرر دستی</button>
            <button class="mini-act n" data-sig-action="BE" data-sig-id="${escapeHtml(s.id)}">BE</button>
          </div>
        </div>
      `;
    })
    .join("");

  el.querySelectorAll("[data-sig-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sigId = btn.getAttribute("data-sig-id");
      const action = btn.getAttribute("data-sig-action");
      const sig = signals.find((x) => x.id === sigId);
      if (sig) handleSignalQuickAction(sig, action);
    });
  });
}

function setDirectionState(dir) {
  document.getElementById("tf-direction").value = dir;
  document.querySelectorAll("#dir-switch .dir-btn").forEach((b) => {
    b.classList.toggle("active", b.getAttribute("data-dir") === dir);
  });
}

function setOutcomeState(outcome) {
  document.getElementById("tf-outcome").value = outcome;
  document.querySelectorAll("#outcome-grid .out-btn").forEach((b) => {
    b.classList.toggle("active", b.getAttribute("data-preset") === outcome);
  });
}

function handleSignalQuickAction(sig, action) {
  const alreadyLogged = getJournal().some((j) => j.signalId === sig.id);
  if (alreadyLogged) {
    const ok = confirm("این سیگنال قبلاً در ژورنال ثبت شده است. آیا می‌خواهید دوباره آن را ثبت کنید؟");
    if (!ok) return;
  }

  const settings = getSettings();
  const baseRisk = settings.defaultRisk || 10;

  let engineValue = "Manual";
  if (sig.timeframe.includes("30M")) engineValue = "30M";
  else if (sig.timeframe.includes("15M")) engineValue = "15M";
  else if (sig.timeframe.includes("5M")) engineValue = "5M";
  else if (sig.timeframe.includes("1H")) engineValue = "1H";

  switchView("journal");

  document.getElementById("tf-signal-id").value = sig.id;
  setDirectionState(sig.direction);
  document.getElementById("tf-engine").value = engineValue;
  setOutcomeState(action);
  document.getElementById("tf-note").value = `${sig.strategy_name} (${sig.entry})`;

  const pnlInput = document.getElementById("tf-pnl");
  if (action === "TP") pnlInput.value = (baseRisk * Number(sig.rr_ratio || 2)).toFixed(2);
  else if (action === "SL") pnlInput.value = (-baseRisk).toFixed(2);
  else if (action === "BE") pnlInput.value = "0";
  else {
    pnlInput.value = "";
    pnlInput.focus();
  }
}

// ─── Journal Analytics & Equity Curve ───────────────────────────────────────

function computeJournalStats(journal) {
  const total = journal.length;
  let wins = 0;
  let losses = 0;
  let bes = 0;
  let grossProfit = 0;
  let grossLoss = 0;
  let maxStreak = 0;
  let curStreak = 0;
  const byEngine = {};

  const chrono = [...journal].sort((a, b) => (a.createdAt || "").localeCompare(b.createdAt || ""));
  const equityPoints = [0];

  chrono.forEach((t) => {
    const pnl = Number(t.pnl) || 0;
    const isWin = t.outcome === "TP" || t.outcome === "MANUAL_PROFIT" || (t.outcome !== "BE" && pnl > 0);
    const isLoss = t.outcome === "SL" || t.outcome === "MANUAL_LOSS" || (t.outcome !== "BE" && pnl < 0);

    if (t.outcome === "BE" || pnl === 0) {
      bes++;
      curStreak = 0;
    } else if (isWin) {
      wins++;
      grossProfit += Math.abs(pnl);
      curStreak++;
      if (curStreak > maxStreak) maxStreak = curStreak;
    } else if (isLoss) {
      losses++;
      grossLoss += Math.abs(pnl);
      curStreak = 0;
    }

    equityPoints.push(equityPoints[equityPoints.length - 1] + pnl);

    const eng = t.engine || "Manual";
    if (!byEngine[eng]) byEngine[eng] = { wins: 0, losses: 0, bes: 0, pnl: 0, total: 0 };
    byEngine[eng].total++;
    byEngine[eng].pnl += pnl;
    if (t.outcome === "BE" || pnl === 0) byEngine[eng].bes++;
    else if (isWin) byEngine[eng].wins++;
    else byEngine[eng].losses++;
  });

  const decided = wins + losses;
  const winRate = decided > 0 ? (wins / decided) * 100 : 0;
  const netPnl = grossProfit - grossLoss;
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? 99.9 : 0;
  const avgWin = wins > 0 ? grossProfit / wins : 0;
  const avgLoss = losses > 0 ? grossLoss / losses : 0;

  return {
    total,
    wins,
    losses,
    bes,
    winRate,
    netPnl,
    grossProfit,
    grossLoss,
    profitFactor,
    avgWin,
    avgLoss,
    maxStreak,
    equityPoints,
    byEngine,
  };
}

function renderEquityCurve(points) {
  const canvas = document.getElementById("equity-canvas");
  if (!canvas || !canvas.parentElement) return;
  const parentWidth = canvas.parentElement.clientWidth;
  if (parentWidth <= 0) return;

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(240, parentWidth - 28);
  const height = 165;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);

  if (!points || points.length < 2) {
    ctx.fillStyle = "#76808f";
    ctx.font = "12px Vazirmatn, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("پس از ثبت اولین معامله، نمودار رشد سرمایه اینجا رسم می‌شود.", width / 2, height / 2);
    return;
  }

  const padX = 12;
  const padY = 16;
  const minVal = Math.min(...points, 0);
  const maxVal = Math.max(...points, 0);
  const span = maxVal - minVal || 1;

  const toX = (i) => padX + (i / (points.length - 1)) * (width - padX * 2);
  const toY = (v) => height - padY - ((v - minVal) / span) * (height - padY * 2);

  const zeroY = toY(0);
  ctx.strokeStyle = "#1b2029";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(padX, zeroY);
  ctx.lineTo(width - padX, zeroY);
  ctx.stroke();
  ctx.setLineDash([]);

  const lastVal = points[points.length - 1];
  const lineColor = lastVal >= 0 ? "#0ecb81" : "#f6465d";

  const grad = ctx.createLinearGradient(0, 0, 0, height);
  grad.addColorStop(0, lastVal >= 0 ? "rgba(14,203,129,0.22)" : "rgba(246,70,93,0.22)");
  grad.addColorStop(1, "rgba(5,6,8,0)");

  ctx.beginPath();
  points.forEach((v, i) => {
    const x = toX(i);
    const y = toY(v);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = lineColor;
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.lineTo(toX(points.length - 1), height - padY);
  ctx.lineTo(toX(0), height - padY);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  points.forEach((v, i) => {
    if (i === 0) return;
    ctx.beginPath();
    ctx.arc(toX(i), toY(v), 2.5, 0, Math.PI * 2);
    ctx.fillStyle = v >= points[i - 1] ? "#0ecb81" : "#f6465d";
    ctx.fill();
  });
}

function outcomeTag(outcome) {
  switch (outcome) {
    case "TP": return `<span class="tag tag-bull">TP</span>`;
    case "SL": return `<span class="tag tag-bear">SL</span>`;
    case "MANUAL_PROFIT": return `<span class="tag tag-bull">سود دستی</span>`;
    case "MANUAL_LOSS": return `<span class="tag tag-bear">ضرر دستی</span>`;
    case "BE": return `<span class="tag tag-muted">BE</span>`;
    default: return escapeHtml(outcome);
  }
}

function renderJournal() {
  const journal = getJournal();
  const stats = computeJournalStats(journal);

  const wrEl = document.getElementById("kpi-winrate");
  wrEl.textContent = `${stats.winRate.toFixed(1)}%`;
  wrEl.className = `mono tel-val ${stats.winRate >= 50 ? "text-bull" : stats.total ? "text-bear" : ""}`;
  document.getElementById("kpi-record").textContent = `${stats.wins}W / ${stats.losses}L / ${stats.bes}BE`;

  const pnlEl = document.getElementById("kpi-pnl");
  pnlEl.textContent = formatMoney(stats.netPnl);
  pnlEl.className = `mono tel-val ${stats.netPnl > 0 ? "text-bull" : stats.netPnl < 0 ? "text-bear" : ""}`;
  document.getElementById("kpi-gross").textContent = `+$${stats.grossProfit.toFixed(1)} / -$${stats.grossLoss.toFixed(1)}`;

  document.getElementById("kpi-pf").textContent = stats.profitFactor >= 99 ? "∞" : stats.profitFactor.toFixed(2);
  document.getElementById("kpi-avg-rr").textContent = `Avg +$${stats.avgWin.toFixed(1)} / -$${stats.avgLoss.toFixed(1)}`;

  document.getElementById("kpi-total").textContent = String(stats.total);
  document.getElementById("kpi-streak").textContent = `Streak: ${stats.maxStreak}`;

  renderEquityCurve(stats.equityPoints);

  const bdEl = document.getElementById("engine-breakdown");
  const engines = Object.entries(stats.byEngine);
  if (!engines.length) {
    bdEl.innerHTML = "";
  } else {
    bdEl.innerHTML = engines
      .map(([eng, info]) => {
        const dec = info.wins + info.losses;
        const wr = dec > 0 ? ((info.wins / dec) * 100).toFixed(0) : "0";
        return `
          <div class="bd-cell">
            <strong class="mono">${escapeHtml(eng)}</strong>
            <span class="mono muted">${wr}% (${info.wins}W/${info.losses}L)</span>
            <span class="mono ${info.pnl >= 0 ? "text-bull" : "text-bear"}">${formatMoney(info.pnl)}</span>
          </div>
        `;
      })
      .join("");
  }

  const filtered = journal.filter((t) => {
    const pnl = Number(t.pnl) || 0;
    if (currentFilter === "WIN") return pnl > 0 || t.outcome === "TP" || t.outcome === "MANUAL_PROFIT";
    if (currentFilter === "LOSS") return pnl < 0 || t.outcome === "SL" || t.outcome === "MANUAL_LOSS";
    return true;
  });

  const tbody = document.getElementById("journal-tbody");
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted" style="text-align:center;padding:24px">معامله‌ای ثبت نشده است.</td></tr>`;
  } else {
    tbody.innerHTML = filtered
      .map((t) => {
        const pnl = Number(t.pnl) || 0;
        const dirTag = t.direction === "BUY" ? `<span class="text-bull">BUY</span>` : `<span class="text-bear">SELL</span>`;
        return `
          <tr>
            <td class="mono muted">${escapeHtml(t.dateLabel)}</td>
            <td class="mono">${dirTag}</td>
            <td class="mono">${escapeHtml(t.engine)}</td>
            <td>${outcomeTag(t.outcome)}</td>
            <td class="mono ${pnl > 0 ? "text-bull" : pnl < 0 ? "text-bear" : ""}">${formatMoney(pnl)}</td>
            <td title="${escapeHtml(t.note)}">${escapeHtml((t.note || "-").slice(0, 28))}</td>
            <td><button class="btn-ghost danger" data-del-trade="${escapeHtml(t.id)}">حذف</button></td>
          </tr>
        `;
      })
      .join("");

    tbody.querySelectorAll("[data-del-trade]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-del-trade");
        saveJournal(getJournal().filter((x) => x.id !== id));
        renderJournal();
        if (dashboardData) renderBotSignals(dashboardData.signals || []);
      });
    });
  }
}

function setupTradeForm() {
  const form = document.getElementById("trade-form");
  const pnlInput = document.getElementById("tf-pnl");

  document.querySelectorAll("#dir-switch .dir-btn").forEach((btn) => {
    btn.addEventListener("click", () => setDirectionState(btn.getAttribute("data-dir")));
  });

  document.querySelectorAll("#outcome-grid .out-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const preset = btn.getAttribute("data-preset");
      setOutcomeState(preset);
      const risk = getSettings().defaultRisk || 10;
      if (preset === "BE") pnlInput.value = "0";
      else if (preset === "SL" && !pnlInput.value) pnlInput.value = (-risk).toFixed(2);
      else if (preset === "TP" && !pnlInput.value) pnlInput.value = (risk * 2).toFixed(2);
      else pnlInput.focus();
    });
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const outcome = document.getElementById("tf-outcome").value;
    let pnlVal = Number(pnlInput.value || 0);

    if ((outcome === "SL" || outcome === "MANUAL_LOSS") && pnlVal > 0) pnlVal = -pnlVal;
    if ((outcome === "TP" || outcome === "MANUAL_PROFIT") && pnlVal < 0) pnlVal = Math.abs(pnlVal);
    if (outcome === "BE") pnlVal = 0;

    const now = new Date();
    const entry = {
      id: `tr_${Date.now()}_${Math.random().toString(16).slice(2, 6)}`,
      signalId: document.getElementById("tf-signal-id").value || null,
      createdAt: now.toISOString(),
      dateLabel: now.toLocaleString("fa-IR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }),
      direction: document.getElementById("tf-direction").value,
      engine: document.getElementById("tf-engine").value,
      outcome,
      pnl: Number(pnlVal.toFixed(2)),
      note: document.getElementById("tf-note").value.trim(),
    };

    const journal = getJournal();
    journal.unshift(entry);
    saveJournal(journal);

    form.reset();
    document.getElementById("tf-signal-id").value = "";
    setDirectionState("BUY");
    setOutcomeState("TP");
    renderJournal();
    if (dashboardData) renderBotSignals(dashboardData.signals || []);
  });

  document.querySelectorAll("#journal-filter-btns .tf-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#journal-filter-btns .tf-item").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentFilter = btn.getAttribute("data-filter");
      renderJournal();
    });
  });

  document.getElementById("btn-export-json").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(getJournal(), null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `gold_journal_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  document.getElementById("btn-export-csv").addEventListener("click", () => {
    const rows = [["Date", "Direction", "Engine", "Outcome", "PnL", "Note"]];
    getJournal().forEach((t) => {
      rows.push([t.createdAt, t.direction, t.engine, t.outcome, t.pnl, (t.note || "").replace(/"/g, '""')]);
    });
    const csv = rows.map((r) => r.map((c) => `"${c}"`).join(",")).join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `gold_journal_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  document.getElementById("input-import-json").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const imported = JSON.parse(await file.text());
      if (!Array.isArray(imported)) throw new Error("Invalid");
      const current = getJournal();
      const seen = new Set(current.map((x) => x.id));
      const merged = [...current];
      imported.forEach((item) => {
        if (item?.id && !seen.has(item.id)) {
          merged.push(item);
          seen.add(item.id);
        }
      });
      merged.sort((a, b) => (b.createdAt || "").localeCompare(a.createdAt || ""));
      saveJournal(merged);
      renderJournal();
      alert(`${imported.length} رکورد ایمپورت شد.`);
    } catch {
      alert("فایل JSON معتبر نیست.");
    }
    e.target.value = "";
  });

  document.getElementById("btn-clear-journal").addEventListener("click", () => {
    if (confirm("کل تاریخچه ژورنال پاک شود؟")) {
      saveJournal([]);
      renderJournal();
      if (dashboardData) renderBotSignals(dashboardData.signals || []);
    }
  });
}

function setupLotCalculator() {
  const bal = document.getElementById("calc-balance");
  const rPct = document.getElementById("calc-risk-pct");
  const sl = document.getElementById("calc-sl-dist");

  const recalc = () => {
    const b = Math.max(0, Number(bal.value) || 0);
    const p = Math.max(0, Number(rPct.value) || 0);
    const s = Math.max(0.1, Number(sl.value) || 0.1);
    const riskUsd = b * (p / 100);
    const lot = riskUsd / (s * 100);
    document.getElementById("calc-lot-out").textContent = lot.toFixed(2);
    document.getElementById("calc-risk-usd").textContent = `$${riskUsd.toFixed(2)}`;
    document.getElementById("calc-tp2-usd").textContent = `+$${(riskUsd * 2).toFixed(2)}`;
  };

  [bal, rPct, sl].forEach((el) => el.addEventListener("input", recalc));
  recalc();
}

// ─── AI Mini Chatbot ────────────────────────────────────────────────────────

function buildLiveAiContext() {
  const q = getEffectiveMarketPrice();
  const m = dashboardData?.market || {};
  const stats = computeJournalStats(getJournal());
  const todayNews = (dashboardData?.news || []).filter((n) => n.is_today);
  const recentSignals = (dashboardData?.signals || []).slice(0, 5);

  return `تو دستیار تریدر طلا (XAU/USD) هستی. به فارسی دقیق، کوتاه و بدون حاشیه جواب بده. فقط به اعداد واقعی زیر استناد کن:

[بازار و قیمت]
- قیمت XAU/USD: ${q ? `$${q.price} (${q.change_24h >= 0 ? "+" : ""}${q.change_24h}%, ${q.source})` : "نامشخص"}
- آخرین آپدیت ربات: ${dashboardData?.updated_at_tehran || "--"} تهران
- جهت کلان: ${m.htf_text || m.htf_bias || "--"} | وضعیت 1H: ${m.reason_1h || "--"}
- اندیکاتور 4H: ${JSON.stringify(m.indicators_4h || {})}
- اندیکاتور 1H: ${JSON.stringify(m.indicators_1h || {})}
- اندیکاتور 30M: ${JSON.stringify(m.indicators_30m || {})}
- اندیکاتور 15M: ${JSON.stringify(m.indicators_15m || {})}
- اندیکاتور 5M: ${JSON.stringify(m.indicators_5m || {})}

[اخبار USD امروز]
${todayNews.length ? todayNews.map((n) => `- ${n.tehran_time} | ${n.impact} | ${n.title} | پیش‌بینی:${n.forecast || "-"} قبلی:${n.previous || "-"} واقعی:${n.actual || "-"}`).join("\n") : "- خبر مهمی برای امروز ثبت نشده است."}

[سیگنال‌های اخیر]
${recentSignals.length ? recentSignals.map((s) => `- ${s.timestamp_tehran} | ${s.direction} | ${s.strategy_name} (${s.timeframe}) | E:${s.entry} SL:${s.stop_loss} TP:${s.take_profit} RR:${s.rr_ratio} | ${s.auto_outcome}`).join("\n") : "- سیگنالی ثبت نشده است."}

[آمار ژورنال]
- کل:${stats.total} | برد:${stats.wins} | باخت:${stats.losses} | WR:${stats.winRate.toFixed(1)}% | Net PnL:${formatMoney(stats.netPnl)} | PF:${stats.profitFactor.toFixed(2)}`;
}

async function callAiProvider(userPrompt) {
  const s = getSettings();
  if (!s.aiKey) {
    return "ابتدا از بخش API Key / تنظیمات، کلید سرویس‌دهنده AI خودت را وارد کن.";
  }

  const systemPrompt = buildLiveAiContext();

  if (s.aiProvider === "gemini") {
    const model = s.aiModel || "gemini-2.5-flash";
    const url = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(s.aiKey)}`;
    const contents = [
      ...chatHistory.slice(-6).map((m) => ({
        role: m.role === "user" ? "user" : "model",
        parts: [{ text: m.text }],
      })),
      { role: "user", parts: [{ text: userPrompt }] },
    ];
    const body = {
      system_instruction: { parts: [{ text: systemPrompt }] },
      contents,
    };
    if (s.geminiSearch) body.tools = [{ google_search: {} }];

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data?.error?.message || `Gemini HTTP ${res.status}`);
    return data?.candidates?.[0]?.content?.parts?.map((p) => p.text).filter(Boolean).join("\n") || "پاسخی دریافت نشد.";
  }

  const endpoint = s.aiEndpoint || PROVIDER_DEFAULTS[s.aiProvider]?.endpoint || "https://api.openai.com/v1/chat/completions";
  const model = s.aiModel || PROVIDER_DEFAULTS[s.aiProvider]?.model || "gpt-4o-mini";
  const messages = [
    { role: "system", content: systemPrompt },
    ...chatHistory.slice(-6).map((m) => ({ role: m.role === "user" ? "user" : "assistant", content: m.text })),
    { role: "user", content: userPrompt },
  ];

  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${s.aiKey}`,
  };
  if (s.aiProvider === "openrouter") {
    headers["HTTP-Referer"] = window.location.origin;
    headers["X-Title"] = "Gold Terminal";
  }

  const res = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify({ model, messages, temperature: 0.3 }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data?.error?.message || `AI HTTP ${res.status}`);
  return data?.choices?.[0]?.message?.content || "پاسخی دریافت نشد.";
}

function appendChatMessage(role, text) {
  const container = document.getElementById("ai-messages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function setupAiChatbot() {
  const fab = document.getElementById("ai-fab");
  const drawer = document.getElementById("ai-drawer");
  const input = document.getElementById("ai-input");

  fab.addEventListener("click", () => {
    drawer.classList.remove("hidden");
    fab.classList.add("hidden");
    input.focus();
  });

  document.getElementById("ai-btn-close").addEventListener("click", () => {
    drawer.classList.add("hidden");
    fab.classList.remove("hidden");
  });

  document.getElementById("ai-btn-settings").addEventListener("click", openSettingsModal);

  document.getElementById("ai-btn-clear").addEventListener("click", () => {
    chatHistory = [];
    document.getElementById("ai-messages").innerHTML =
      `<div class="msg bot">چت پاک شد. سوالت رو بپرس.</div>`;
  });

  const sendPrompt = async (q) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    appendChatMessage("user", trimmed);
    const loadingEl = appendChatMessage("bot", "در حال بررسی...");
    try {
      const reply = await callAiProvider(trimmed);
      loadingEl.textContent = reply;
      chatHistory.push({ role: "user", text: trimmed }, { role: "bot", text: reply });
    } catch (err) {
      loadingEl.textContent = `خطا: ${err.message}`;
    }
  };

  document.getElementById("ai-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value;
    input.value = "";
    sendPrompt(q);
  });

  document.querySelectorAll(".q-chip").forEach((chip) => {
    chip.addEventListener("click", () => sendPrompt(chip.getAttribute("data-q")));
  });
}

// ─── Settings Modal ─────────────────────────────────────────────────────────

function openSettingsModal() {
  const s = getSettings();
  document.getElementById("set-ai-provider").value = s.aiProvider;
  document.getElementById("set-ai-key").value = s.aiKey;
  document.getElementById("set-ai-model").value = s.aiModel;
  document.getElementById("set-ai-endpoint").value = s.aiEndpoint;
  document.getElementById("set-gemini-search").checked = s.geminiSearch;
  document.getElementById("set-default-risk").value = s.defaultRisk;
  document.getElementById("set-new-user").value = "";
  document.getElementById("set-new-pass").value = "";
  toggleProviderFields(s.aiProvider);
  document.getElementById("settings-modal").classList.remove("hidden");
}

function toggleProviderFields(provider) {
  document.getElementById("gemini-search-wrap").classList.toggle("hidden", provider !== "gemini");
  document.getElementById("custom-endpoint-wrap").classList.toggle("hidden", provider === "gemini");
}

function setupSettingsModal() {
  const modal = document.getElementById("settings-modal");
  const providerEl = document.getElementById("set-ai-provider");
  const modelEl = document.getElementById("set-ai-model");
  const endpointEl = document.getElementById("set-ai-endpoint");

  document.getElementById("btn-open-settings").addEventListener("click", openSettingsModal);
  document.getElementById("btn-close-settings").addEventListener("click", () => modal.classList.add("hidden"));
  document.getElementById("btn-cancel-settings").addEventListener("click", () => modal.classList.add("hidden"));

  providerEl.addEventListener("change", () => {
    const p = providerEl.value;
    toggleProviderFields(p);
    modelEl.value = PROVIDER_DEFAULTS[p]?.model || "";
    endpointEl.value = PROVIDER_DEFAULTS[p]?.endpoint || "";
  });

  document.getElementById("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const provider = providerEl.value;
    saveSettings({
      aiProvider: provider,
      aiKey: document.getElementById("set-ai-key").value.trim(),
      aiModel: modelEl.value.trim() || PROVIDER_DEFAULTS[provider].model,
      aiEndpoint: endpointEl.value.trim(),
      geminiSearch: document.getElementById("set-gemini-search").checked,
      defaultRisk: Number(document.getElementById("set-default-risk").value) || 10,
    });

    const newUser = document.getElementById("set-new-user").value.trim();
    const newPass = document.getElementById("set-new-pass").value;
    if (newUser && newPass) {
      const nextHash = await sha256Hex(`${newUser}:${newPass}`);
      localStorage.setItem(STORAGE_KEYS.AUTH_HASH, nextHash);
      localStorage.setItem(STORAGE_KEYS.SESSION, nextHash);
    }

    document.getElementById("ai-provider-label").textContent = `${provider.toUpperCase()} • LIVE DATA`;
    modal.classList.add("hidden");
  });
}

// ─── Init ───────────────────────────────────────────────────────────────────

function initDashboard() {
  if (initialized) return;
  initialized = true;

  setupNavigationAndRail();
  renderTradingView("15");

  document.querySelectorAll("#tv-tf-buttons .tf-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#tv-tf-buttons .tf-item").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderTradingView(btn.getAttribute("data-tf"));
    });
  });

  setupTradeForm();
  setupLotCalculator();
  setupAiChatbot();
  setupSettingsModal();
  renderJournal();

  const s = getSettings();
  if (s.aiKey) {
    document.getElementById("ai-provider-label").textContent = `${s.aiProvider.toUpperCase()} • LIVE DATA`;
  }

  document.getElementById("btn-refresh").addEventListener("click", () => {
    fetchBotData();
    fetchLiveBrowserPrice();
  });

  document.getElementById("btn-logout").addEventListener("click", () => {
    localStorage.removeItem(STORAGE_KEYS.SESSION);
    sessionStorage.removeItem(STORAGE_KEYS.SESSION);
    window.location.reload();
  });

  fetchBotData();
  fetchLiveBrowserPrice();
  setInterval(fetchLiveBrowserPrice, 15000);
  setInterval(fetchBotData, 60000);
  window.addEventListener("resize", () => {
    if (activeView === "journal") renderJournal();
  });
}

document.addEventListener("DOMContentLoaded", setupLogin);
