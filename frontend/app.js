// ✅ ТВОЙ ПРОД-БЭК (Render)
const API = "https://tradebull-backend.onrender.com";

const el = (id) => document.getElementById(id);
const fmt = (n) => (n === null || n === undefined) ? "—" : (typeof n === "number" ? n.toFixed(2) : String(n));

async function jget(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function jpost(path, body) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(body)
  });
  const txt = await res.text();
  if (!res.ok) throw new Error(txt);
  return JSON.parse(txt);
}

// ===== Telegram user_id (если не Telegram — test1) =====
function getUserId() {
  try {
    const tg = window.Telegram?.WebApp;
    const id = tg?.initDataUnsafe?.user?.id;
    if (id) return String(id);
  } catch {}
  return "test1";
}

function setupTelegramUI() {
  try {
    const tg = window.Telegram?.WebApp;
    if (tg) { tg.ready(); tg.expand(); }
  } catch {}
}

// ===== Lightweight Charts =====
let chart, candleSeries;
let lastRoundId = null;

function initChart() {
  const container = document.getElementById("tvchart");

  // window.LightweightCharts из standalone build
  const { createChart } = window.LightweightCharts;

  chart = createChart(container, {
    layout: {
      background: { color: "#0f1722" },
      textColor: "#cfe0f5",
    },
    grid: {
      vertLines: { color: "#1b2735" },
      horzLines: { color: "#1b2735" },
    },
    rightPriceScale: {
      borderColor: "#1b2735",
    },
    timeScale: {
      borderColor: "#1b2735",
      timeVisible: true,
      secondsVisible: true,
    },
    crosshair: { mode: 1 },
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: "#2ecc71",
    downColor: "#e74c3c",
    borderVisible: false,
    wickUpColor: "#2ecc71",
    wickDownColor: "#e74c3c",
  });

  // адаптация под ресайз
  const ro = new ResizeObserver(() => {
    const r = container.getBoundingClientRect();
    chart.applyOptions({ width: Math.floor(r.width), height: Math.floor(r.height) });
  });
  ro.observe(container);
}

// points[] -> candles[] (OHLC) по чанкам
function pointsToCandles(points, baseTimeSec, candlesCount) {
  if (!points || points.length < 2) return [];

  // хотим candlesCount свечей, например 60
  const total = points.length;
  const chunk = Math.max(2, Math.floor(total / candlesCount));

  const candles = [];
  let t = baseTimeSec;

  for (let i = 0; i < total; i += chunk) {
    const slice = points.slice(i, Math.min(total, i + chunk));
    if (slice.length < 2) break;

    const o = slice[0];
    const c = slice[slice.length - 1];
    let h = -Infinity, l = Infinity;
    for (const p of slice) { if (p > h) h = p; if (p < l) l = p; }

    candles.push({
      time: t, // seconds
      open: o,
      high: h,
      low: l,
      close: c,
    });

    t += 1; // 1 сек на свечу (визуально биржево)
  }

  return candles;
}

function updateTimer(phase, server_ms, start_ms, end_ms) {
  let text = "";
  if (phase === "BET") {
    const left = Math.max(0, start_ms - server_ms);
    text = "BET: " + (left/1000).toFixed(1) + "s";
  } else if (phase === "RUN") {
    const left = Math.max(0, end_ms - server_ms);
    text = "RUN: " + (left/1000).toFixed(1) + "s";
  } else if (phase === "DONE") {
    text = "DONE";
  } else {
    text = phase;
  }
  el("timer").textContent = text;
}

async function refresh() {
  const user_id = getUserId();
  el("userLabel").textContent = user_id;

  const init = await jget(`/init?user_id=${encodeURIComponent(user_id)}`);
  el("balance").textContent = fmt(init.balance);

  const s = await jget(`/series`);

  el("roundId").textContent = String(s.round_id);
  el("phase").textContent = s.phase;
  el("gold").textContent = s.gold_mult ? ("x" + s.gold_mult) : "—";
  updateTimer(s.phase, s.server_ms, s.start_ms, s.end_ms);

  // если сменился раунд — перерисуем весь датасет
  if (lastRoundId !== s.round_id) {
    lastRoundId = s.round_id;

    // 60 свечей для видимого окна (можно 90/120)
    const baseTime = Math.floor(Date.now() / 1000) - 60;
    const candles = pointsToCandles(s.points, baseTime, 60);

    candleSeries.setData(candles);

    // gold: если есть gold_mult — сделаем ПОСЛЕДНЮЮ свечу "золотой" визуально
    // (потом можно сделать детерминированный индекс по seed)
    if (s.gold_mult && candles.length) {
      const last = candles[candles.length - 1];
      candleSeries.setData(candles); // уже стоит
      // Простой лайфхак: меняем цвета серии под gold на пару секунд,
      // чтобы было видно событие. Потом вернем обратно.
      candleSeries.applyOptions({
        upColor: "#f5c542",
        downColor: "#f5c542",
        wickUpColor: "#f5c542",
        wickDownColor: "#f5c542",
      });
      setTimeout(() => {
        candleSeries.applyOptions({
          upColor: "#2ecc71",
          downColor: "#e74c3c",
          wickUpColor: "#2ecc71",
          wickDownColor: "#e74c3c",
        });
      }, 900);
    }
  }

  const my = await jget(`/mybet?user_id=${encodeURIComponent(user_id)}`);
  if (my.bet) {
    el("status").innerHTML =
      `Your bet: <b>${my.bet.side}</b> amount <b>${my.bet.amount}</b> insurance <b>${my.bet.insurance ? "ON" : "OFF"}</b>`;
  } else {
    el("status").textContent = "No bet in this round";
  }
}

async function placeBet(side) {
  try {
    const user_id = getUserId();
    const amount = parseFloat(el("amount").value || "0");
    const insurance = !!el("insurance").checked;

    const resp = await jpost("/bet", { user_id, side, amount, insurance });

    el("status").innerHTML = `<span class="ok">BET OK</span> round ${resp.round_id}, balance ${resp.balance}`;
    el("balance").textContent = fmt(resp.balance);
  } catch (e) {
    el("status").innerHTML = `<span class="warn">ERROR</span> ${String(e)}`;
  }
}

setupTelegramUI();
initChart();

refresh().catch(err => el("status").textContent = String(err));
setInterval(() => refresh().catch(()=>{}), 1000);

// чтобы onclick работал
window.placeBet = placeBet;
