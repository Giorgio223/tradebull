const API = "https://tradebull-backend.onrender.com";

const el = (id) => document.getElementById(id);
const fmt = (n) => (n === null || n === undefined) ? "—" : (typeof n === "number" ? n.toFixed(2) : String(n));

async function jget(path) {
  const res = await fetch(API + path);
  const txt = await res.text();
  if (!res.ok) throw new Error(txt);
  return JSON.parse(txt);
}

async function jpost(path, body) {
  const res = await fetch(API + path, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(body),
  });
  const txt = await res.text();
  if (!res.ok) throw new Error(txt);
  return JSON.parse(txt);
}

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

// ===== Chart =====
let chart, candleSeries;
let lastRoundId = null;

// “лента” свечей (вся история)
let allCandles = [];
let lastCandleTime = Math.floor(Date.now() / 1000) - 120;

// чтобы “достраивать” свечи по мере прихода points
let lastVisiblePoints = 0;

// настройка: 1 свеча = 10 points (то есть 1 сек раунда)
const POINTS_PER_CANDLE = 10;

function initChart() {
  const container = document.getElementById("tvchart");
  const { createChart } = window.LightweightCharts;

  chart = createChart(container, {
    layout: { background: { color: "#0f1722" }, textColor: "#cfe0f5" },
    grid: { vertLines: { color: "#1b2735" }, horzLines: { color: "#1b2735" } },
    rightPriceScale: { borderColor: "#1b2735" },
    timeScale: {
      borderColor: "#1b2735",
      timeVisible: true,
      secondsVisible: true,
      rightOffset: 5,
      barSpacing: 6, // “ближе друг к другу”
    },
    crosshair: { mode: 1 },
  });

  candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: "#2ecc71",
    downColor: "#e74c3c",
    borderVisible: false,
    wickUpColor: "#2ecc71",
    wickDownColor: "#e74c3c",
  });

  const ro = new ResizeObserver(() => {
    const r = container.getBoundingClientRect();
    chart.applyOptions({ width: Math.floor(r.width), height: Math.floor(r.height) });
  });
  ro.observe(container);
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

// Берём новые points и превращаем в новые свечи (по 10 точек на свечу)
function appendCandlesFromPoints(points, fromIndex) {
  // fromIndex — сколько points мы уже обработали
  // делаем свечи только из “полных” чанков по 10
  const maxFull = Math.floor(points.length / POINTS_PER_CANDLE) * POINTS_PER_CANDLE;
  let i = Math.floor(fromIndex / POINTS_PER_CANDLE) * POINTS_PER_CANDLE;

  const out = [];
  for (; i + POINTS_PER_CANDLE <= maxFull; i += POINTS_PER_CANDLE) {
    const slice = points.slice(i, i + POINTS_PER_CANDLE);
    const open = slice[0];
    const close = slice[slice.length - 1];
    let high = -Infinity, low = Infinity;
    for (const p of slice) { if (p > high) high = p; if (p < low) low = p; }

    lastCandleTime += 1;
    out.push({ time: lastCandleTime, open, high, low, close });
  }
  return { candles: out, newIndex: maxFull };
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

  // новый раунд? — не очищаем график, просто начинаем “строить” новые свечи
  if (lastRoundId !== s.round_id) {
    lastRoundId = s.round_id;
    lastVisiblePoints = 0; // для нового раунда начинаем с нуля points
  }

  // ДОБАВЛЯЕМ новые свечи, а не перерисовываем всё
  const { candles, newIndex } = appendCandlesFromPoints(s.points, lastVisiblePoints);
  lastVisiblePoints = newIndex;

  for (const c of candles) {
    allCandles.push(c);
    candleSeries.update(c);
  }

  // ставка
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
// 1 раз в секунду — нормальная скорость “как биржа”
setInterval(() => refresh().catch(()=>{}), 1000);

window.placeBet = placeBet;
