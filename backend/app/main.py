import time
import random
import secrets
import math
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TradeBull API", version="0.1.0")

# ===== CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tradebull-ten.vercel.app",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BET_SEC = 7
RUN_SEC = 30

# ===== in-memory storage (MVP) =====
users: Dict[str, float] = {}
bets: Dict[str, Dict[str, Any]] = {}
last_results: Dict[str, Dict[str, Any]] = {}

def now_ms() -> int:
    return int(time.time() * 1000)

def new_seed() -> int:
    return int.from_bytes(secrets.token_bytes(4), "big")

def gen_gold_mult(seed: int) -> int:
    return (1 + (seed % 7)) if (seed % 100 == 0) else 0

def calc_open_close(seed: int, base: float = 100.0):
    x = (seed % 2000) / 1000.0
    delta = (x - 1.0) * 2.0
    return base, round(base + delta, 3)

def series_points(seed: int, open_p: float, close_p: float, n: int):
    if n < 2:
        return [open_p]

    amp = max(0.05, abs(close_p - open_p) * 0.35 + 0.08)
    pts = []
    for i in range(n):
        t = i / (n - 1)
        base = open_p + (close_p - open_p) * t

        a = (seed % 997) / 997.0
        b = (seed % 389) / 389.0
        c = (seed % 127) / 127.0

        w1 = math.sin((t * math.tau) * (2.0 + 6.0 * a) + (seed % 1000) * 0.001)
        w2 = math.sin((t * math.tau) * (5.0 + 9.0 * b) + (seed % 777) * 0.002)
        w3 = math.sin((t * math.tau) * (9.0 + 7.0 * c) + (seed % 555) * 0.003)

        noise = (w1 * 0.55 + w2 * 0.30 + w3 * 0.15) * amp
        pts.append(base + noise)

    pts[0] = open_p
    pts[-1] = close_p
    return pts

# ===== round state =====
state = {
    "round_id": 1,
    "phase": "BET",     # BET | RUN | DONE
    "start_ms": now_ms() + BET_SEC * 1000,
    "end_ms": now_ms() + (BET_SEC + RUN_SEC) * 1000,
    "seed": new_seed(),
    "gold_mult": 0,
    "open": 100.0,
    "close": 100.0,
}

def ensure_user(user_id: str):
    if user_id not in users:
        users[user_id] = 10.0

def settle_round():
    rid = int(state["round_id"])
    o = float(state["open"])
    c = float(state["close"])
    up = c > o
    gold = int(state.get("gold_mult", 0) or 0)

    for user_id, bet in list(bets.items()):
        side = bet["side"]
        amount = float(bet["amount"])
        insurance = bool(bet.get("insurance", False))

        win = (side == "LONG" and up) or (side == "SHORT" and (not up))
        payout = 0.0

        if win:
            payout = amount * 2.0
            if gold > 0:
                payout *= gold
        else:
            payout = amount * (0.5 if insurance else 0.0)

        users[user_id] += payout

        last_results[user_id] = {
            "round_id": rid,
            "win": win,
            "payout": payout,
            "gold_mult": gold,
            "open": o,
            "close": c,
            "side": side,
            "amount": amount,
            "insurance": insurance,
        }

def next_round():
    base = float(state["close"])
    seed = new_seed()
    gold = gen_gold_mult(seed)
    o, c = calc_open_close(seed, base)

    state["round_id"] = int(state["round_id"]) + 1
    state["phase"] = "BET"
    state["start_ms"] = now_ms() + BET_SEC * 1000
    state["end_ms"] = now_ms() + (BET_SEC + RUN_SEC) * 1000
    state["seed"] = seed
    state["gold_mult"] = gold
    state["open"] = o
    state["close"] = c

    bets.clear()

def ensure_round():
    t = now_ms()

    if state["phase"] == "BET" and t >= int(state["start_ms"]):
        state["phase"] = "RUN"

    if state["phase"] == "RUN" and t >= int(state["end_ms"]):
        state["phase"] = "DONE"
        settle_round()

    if state["phase"] == "DONE":
        # даём маленькое окно DONE, чтобы фронт успел увидеть (опционально)
        # но можно сразу начинать новый раунд
        next_round()

# ===== models =====
class BetReq(BaseModel):
    user_id: str
    side: str
    amount: float
    insurance: Optional[bool] = False

@app.get("/")
def root():
    return {"ok": True, "hint": "Use /health /docs /series"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/init")
def init(user_id: str):
    ensure_user(user_id)
    return {"user_id": user_id, "balance": users[user_id]}

@app.get("/round")
def round_state():
    ensure_round()
    return {
        "round_id": int(state["round_id"]),
        "phase": state["phase"],
        "server_ms": now_ms(),
        "start_ms": int(state["start_ms"]),
        "end_ms": int(state["end_ms"]),
        "seed": int(state["seed"]),
        "open": float(state["open"]),
        "close": float(state["close"]),
        "gold_mult": int(state.get("gold_mult", 0) or 0),
        "bet_sec": BET_SEC,
        "run_sec": RUN_SEC,
    }

@app.get("/series")
def series():
    ensure_round()
    n = RUN_SEC * 10
    pts = series_points(int(state["seed"]), float(state["open"]), float(state["close"]), n)
    return {
        "round_id": int(state["round_id"]),
        "phase": state["phase"],
        "server_ms": now_ms(),
        "start_ms": int(state["start_ms"]),
        "end_ms": int(state["end_ms"]),
        "gold_mult": int(state.get("gold_mult", 0) or 0),
        "points": pts,
    }

@app.post("/bet")
def bet(req: BetReq):
    ensure_round()
    if state["phase"] != "BET":
        raise HTTPException(status_code=400, detail="Betting closed (phase is not BET)")

    ensure_user(req.user_id)

    if req.side not in ("LONG", "SHORT"):
        raise HTTPException(status_code=400, detail="side must be LONG or SHORT")
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")

    insurance_fee = 0.5 if req.insurance else 0.0
    total_cost = float(req.amount) + insurance_fee

    if users[req.user_id] < total_cost:
        raise HTTPException(status_code=400, detail="Not enough balance")

    users[req.user_id] -= total_cost

    bets[req.user_id] = {
        "side": req.side,
        "amount": float(req.amount),
        "insurance": bool(req.insurance),
    }

    return {
        "ok": True,
        "round_id": int(state["round_id"]),
        "balance": users[req.user_id],
        "bet": bets[req.user_id],
        "insurance_fee": insurance_fee,
    }

@app.get("/mybet")
def mybet(user_id: str):
    ensure_round()
    return {"round_id": int(state["round_id"]), "bet": bets.get(user_id)}

@app.get("/last_result")
def last_result(user_id: str):
    return {"result": last_results.get(user_id)}
