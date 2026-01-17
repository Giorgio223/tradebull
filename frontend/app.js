// В проде тут будет твой домен API (например https://api.tradebull.xyz)
// Пока локально:
const API = "http://127.0.0.1:8000";

const el = (id) => document.getElementById(id);

function fmt(n) {
  if (n === null || n === undefined) return "—";
  return (typeof n === "number") ? n.toFixed(2) : String(n);
}

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

function getUserId() {
  try {
    const tg = window.Telegram?.WebApp;
    if (tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.id) {
      return String(tg.initDataUnsafe.user.id);
    }
  } catch {}
  return "test1";
}

function setupTelegramUI() {
  try {
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
    }
  } catch {}
}

function draw(points) {
  const c = el("chart");
  const ctx = c.getContext("2d");
  ctx.clearRect(0,0,c.width,c.height);

  if (!points || points.length < 2) {
    ctx.fillText("no data", 20, 20);
    return;
  }

  const pad = 18;
  const w = c.width - pad*2;
  const h = c.height - pad*2;

  let mn = Math.min(...points);
  let mx = Math.max(...points);
  if (mx - mn < 1e-6) { mx += 1; mn -= 1; }

  ctx.strokeRect(pad, pad, w, h);

  ctx.beginPath();
  for (let i=0;i<points.length;i++) {
    const x = pad + (i/(points.length-1))*w;
    const y = pad + (1 - (points[i]-mn)/(mx-mn))*h;
    if (i===0) ctx.moveTo(x,y);
    else ctx.lineTo(x,y);
  }
  ctx.stroke();

  ctx.fillText("max " + mx.toFixed(2), pad+6, pad+12);
  ctx.fillText("min " + mn.toFixed(2), pad+6, pad+h-6);
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

  const series = await jget(`/series`);
  el("roundId").textContent = String(series.round_id);
  el("phase").textContent = series.phase;
  el("gold").textContent = series.gold_mult ? ("x" + series.gold_mult) : "—";
  updateTimer(series.phase, series.server_ms, series.start_ms, series.end_ms);
  draw(series.points);

  const my = await jget(`/mybet?user_id=${encodeURIComponent(user_id)}`);
  if (my.bet) {
    el("status").innerHTML =
      `Your bet: <b>${my.bet.side}</b> amount <b>${my.bet.amount}</b> insurance <b>${my.bet.insurance ? "ON" : "OFF"}</b>`;
  } else {
    el("status").textContent = "No bet in this round";
  }

  el("debug").textContent = JSON.stringify({
    round_id: series.round_id,
    phase: series.phase,
    gold_mult: series.gold_mult
  }, null, 2);
}

async function placeBet(side) {
  try {
    const user_id = getUserId();
    const amount = parseFloat(el("amount").value || "0");
    const insurance = !!el("insurance").checked;

    const resp = await jpost("/bet", { user_id, side, amount, insurance });

    el("status").innerHTML = `<span style="color:#0a7a0a;font-weight:700">BET OK</span> round ${resp.round_id}, balance ${resp.balance}`;
    el("balance").textContent = fmt(resp.balance);
  } catch (e) {
    el("status").innerHTML = `<span style="color:#b00020;font-weight:700">ERROR</span> ${String(e)}`;
  }
}

setupTelegramUI();

refresh().catch(err => el("status").textContent = String(err));
setInterval(() => refresh().catch(()=>{}), 1000);

// делаем функции доступными из HTML onclick
window.placeBet = placeBet;
