from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from upstash_redis import Redis
from dotenv import load_dotenv
import os
import time
import secrets
import json
import math

load_dotenv()

app = FastAPI()

# ===== CORS (чтобы фронт мог дергать API) =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://127.0.0.1:8080",
        "https://tradebull-ten.vercel.app",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "file://",
        "null",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RUN_SEC = 30
BET_SEC = 7

# ===== Upstash Redis =====
REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
if not REDIS_URL or not REDIS_TOKEN:
    raise RuntimeError("Missing UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN in .env")

r = Redis(url=REDIS_URL, token=REDIS_TOKEN)

P = "tb:"
KEY_STATE = P + "state"
KEY_HISTORY = P + "history"

def now_ms() -> int:
    return int(time.time() * 1000)

def new_seed() -> int:
    return int.from_bytes(secrets.token_bytes(4), "big")

def gen_gold_mult(seed: int) -> int:
    return (1 + (seed % 7)) if (seed % 100 == 0) else 0

def calc_open_close(seed: int, base: float = 100.0):
    x = (seed % 2000) / 1000.0
    delta = (x - 1.0) * 2.0
    return base, base + delta

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

def bal_key(user_id: str) -> str:
    return P + "bal:" + user_id

def bets_key(round_id: int) -> str:
    return P + f"bets:{round_id}"

def last_key(user_id: str) -> str:
    return P + "last:" + user_id

def get_state():
    st = r.get(KEY_STATE)
    if st is None:
        return None
    if isinstance(st, (dict, list)):
        return st
    return json.loads(st)

def set_state(st: dict):
    r.set(KEY_STATE, json.dumps(st))

def history_push(item: dict, limit: int = 50):
    r.lpush(KEY_HISTORY, json.dumps(item))
    r.ltrim(KEY_HISTORY, 0, limit - 1)

def history_get(limit: int = 20):
    arr = r.lrange(KEY_HISTORY, 0, limit - 1) or []
    out = []
    for x in arr:
        try:
            out.append(json.loads(x))
        except Exception:
            pass
    return out

def get_balance(user_id: str) -> float:
    v = r.get(bal_key(user_id))
    if v is None:
        return 0.0
    return float(v)

def set_balance(user_id: str, value: float):
    r.set(bal_key(user_id), str(float(value)))

def get_bet(round_id: int, user_id: str):
    v = r.hget(bets_key(round_id), user_id)
    if v is None:
        return None
    return json.loads(v)

def set_bet(round_id: int, user_id: str, bet: dict):
    r.hset(bets_key(round_id), user_id, json.dumps(bet))

def del_bets(round_id: int):
    r.delete(bets_key(round_id))

def set_last_result(user_id: str, result: dict):
    r.set(last_key(user_id), json.dumps(result))

def get_last_result(user_id: str):
    v = r.get(last_key(user_id))
    if v is None:
        return None
    return json.loads(v)

def settle_round(st: dict):
    rid = int(st["round_id"])
    open_p = float(st["open"])
    close_p = float(st["close"])
    up = close_p > open_p
    gold = int(st.get("gold_mult", 0) or 0)

    all_bets = r.hgetall(bets_key(rid)) or {}
    if not all_bets:
        history_push({"round_id": rid, "open": open_p, "close": close_p, "gold_mult": gold, "ts_ms": now_ms()})
        return

    for user_id, raw in all_bets.items():
        b = json.loads(raw)
        side = b["side"]
        amount = float(b["amount"])
        insurance = bool(b.get("insurance", False))

        win = (side == "LONG" and up) or (side == "SHORT" and (not up))

        payout = 0.0
        if win:
            payout = amount * 2.0
            if gold > 0:
                payout *= gold
            set_balance(user_id, get_balance(user_id) + payout)
        else:
            if insurance:
                payout = amount * 0.5
                set_balance(user_id, get_balance(user_id) + payout)

        set_last_result(user_id, {
            "round_id": rid,
            "win": win,
            "payout": payout,
            "gold_mult": gold,
            "open": open_p,
            "close": close_p,
            "side": side,
            "amount": amount,
            "insurance": insurance,
        })

    history_push({"round_id": rid, "open": open_p, "close": close_p, "gold_mult": gold, "ts_ms": now_ms()})
    del_bets(rid)

def ensure_round():
    t = now_ms()
    st = get_state()

    if st is None:
        seed = new_seed()
        gold = gen_gold_mult(seed)
        o, c = calc_open_close(seed, 100.0)

        st = {
            "round_id": 1,
            "phase": "BET",
            "start_ms": t + BET_SEC * 1000,
            "end_ms": t + (BET_SEC + RUN_SEC) * 1000,
            "seed": seed,
            "gold_mult": gold,
            "open": o,
            "close": c,
        }
        set_state(st)
        return st

    phase = st["phase"]

    if phase == "BET" and t >= int(st["start_ms"]):
        st["phase"] = "RUN"
        set_state(st)
        return st

    if phase == "RUN" and t >= int(st["end_ms"]):
        st["phase"] = "DONE"
        set_state(st)
        settle_round(st)
        return st

    if phase == "DONE":
        rid = int(st["round_id"]) + 1
        seed = new_seed()
        gold = gen_gold_mult(seed)
        base = float(st["close"])
        o, c = calc_open_close(seed, base)

        st = {
            "round_id": rid,
            "phase": "BET",
            "start_ms": t + BET_SEC * 1000,
            "end_ms": t + (BET_SEC + RUN_SEC) * 1000,
            "seed": seed,
            "gold_mult": gold,
            "open": o,
            "close": c,
        }
        set_state(st)
        return st

    return st

class BetReq(BaseModel):
    user_id: str
    side: str
    amount: float
    insurance: bool = False

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/init")
def init(user_id: str):
    b = get_balance(user_id)
    if b == 0.0:
        set_balance(user_id, 10.0)
        b = 10.0
    return {"user_id": user_id, "balance": b}

@app.get("/round")
def round_state():
    st = ensure_round()
    return {
        "round_id": int(st["round_id"]),
        "phase": st["phase"],
        "server_ms": now_ms(),
        "start_ms": int(st["start_ms"]),
        "end_ms": int(st["end_ms"]),
        "seed": int(st["seed"]),
        "open": float(st["open"]),
        "close": float(st["close"]),
        "gold_mult": int(st.get("gold_mult", 0) or 0),
        "bet_sec": BET_SEC,
        "run_sec": RUN_SEC,
    }

@app.get("/series")
def series():
    st = ensure_round()
    rid = int(st["round_id"])
    n = RUN_SEC * 10
    pts = series_points(int(st["seed"]), float(st["open"]), float(st["close"]), n)
    return {
        "round_id": rid,
        "phase": st["phase"],
        "server_ms": now_ms(),
        "start_ms": int(st["start_ms"]),
        "end_ms": int(st["end_ms"]),
        "gold_mult": int(st.get("gold_mult", 0) or 0),
        "points": pts,
    }

@app.post("/bet")
def bet(req: BetReq):
    st = ensure_round()
    if st["phase"] != "BET":
        raise HTTPException(400, "Betting closed (phase is not BET)")

    if req.side not in ("LONG", "SHORT"):
        raise HTTPException(400, "side must be LONG or SHORT")
    if req.amount <= 0:
        raise HTTPException(400, "amount must be > 0")

    insurance_fee = 0.5 if req.insurance else 0.0
    total_cost = float(req.amount) + insurance_fee

    b = get_balance(req.user_id)
    if b == 0.0:
        set_balance(req.user_id, 10.0)
        b = 10.0

    if b < total_cost:
        raise HTTPException(400, "Not enough balance")

    set_balance(req.user_id, b - total_cost)

    rid = int(st["round_id"])
    set_bet(rid, req.user_id, {"side": req.side, "amount": req.amount, "insurance": req.insurance})

    return {
        "ok": True,
        "round_id": rid,
        "balance": get_balance(req.user_id),
        "bet": get_bet(rid, req.user_id),
        "insurance_fee": insurance_fee,
    }

@app.get("/balance")
def balance(user_id: str):
    b = get_balance(user_id)
    if b == 0.0:
        set_balance(user_id, 10.0)
        b = 10.0
    return {"user_id": user_id, "balance": b}

@app.get("/mybet")
def mybet(user_id: str):
    st = ensure_round()
    rid = int(st["round_id"])
    return {"round_id": rid, "bet": get_bet(rid, user_id)}

@app.get("/bet_of_round")
def bet_of_round(user_id: str, round_id: int):
    return {"round_id": int(round_id), "bet": get_bet(int(round_id), user_id)}

@app.get("/last_result")
def last_result(user_id: str):
    return {"result": get_last_result(user_id)}

@app.get("/history")
def history(limit: int = 20):
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    return {"items": history_get(limit)}
