import os
import time
import random
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# =========================
# APP
# =========================
app = FastAPI(title="TradeBull API", version="0.1.0")

# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://localhost:3000",
        "https://tradebull-ten.vercel.app",  # ✅ VERCEL
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# IN-MEMORY STATE (MVP)
# =========================
users = {}
current_round = {
    "round_id": 1,
    "phase": "BET",  # BET | RUN | DONE
    "start_ms": int(time.time() * 1000),
    "end_ms": int(time.time() * 1000) + 30000,
    "open": 100.0,
    "close": 100.0,
    "gold_mult": 0,
}

bets = {}

BET_SEC = 7
RUN_SEC = 30

# =========================
# MODELS
# =========================
class BetReq(BaseModel):
    user_id: str
    side: str  # LONG | SHORT
    amount: float
    insurance: Optional[bool] = False


# =========================
# HELPERS
# =========================
def ensure_user(user_id: str):
    if user_id not in users:
        users[user_id] = 10.0


def new_round():
    global current_round, bets

    gold_mult = 0
    if random.random() <= 0.01:  # 1% шанс
        gold_mult = random.randint(1, 7)

    current_round = {
        "round_id": current_round["round_id"] + 1,
        "phase": "BET",
        "start_ms": int(time.time() * 1000),
        "end_ms": int(time.time() * 1000) + (BET_SEC + RUN_SEC) * 1000,
        "open": 100.0,
        "close": round(100 + random.uniform(-2, 2), 3),
        "gold_mult": gold_mult,
    }
    bets = {}


# =========================
# ROUTES
# =========================
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/init")
def init():
    return {"ok": True}


@app.get("/round")
def round_state():
    now = int(time.time() * 1000)

    if current_round["phase"] == "BET" and now > current_round["start_ms"] + BET_SEC * 1000:
        current_round["phase"] = "RUN"

    if current_round["phase"] == "RUN" and now > current_round["end_ms"]:
        current_round["phase"] = "DONE"

    return {
        **current_round,
        "server_ms": now,
        "bet_sec": BET_SEC,
        "run_sec": RUN_SEC,
    }


@app.post("/bet")
def bet(req: BetReq):
    ensure_user(req.user_id)

    if current_round["phase"] != "BET":
        raise HTTPException(status_code=400, detail="Betting closed (phase is not BET)")

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")

    insurance_fee = 0.5 if req.insurance else 0.0
    total_cost = req.amount + insurance_fee

    if users[req.user_id] < total_cost:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    users[req.user_id] -= total_cost

    bets[req.user_id] = {
        "side": req.side,
        "amount": req.amount,
        "insurance": req.insurance,
    }

    return {
        "ok": True,
        "round_id": current_round["round_id"],
        "balance": users[req.user_id],
        "bet": bets[req.user_id],
        "insurance_fee": insurance_fee,
    }


@app.get("/balance")
def balance(user_id: str):
    ensure_user(user_id)
    return {"user_id": user_id, "balance": users[user_id]}


@app.get("/resolve")
def resolve():
    if current_round["phase"] != "DONE":
        raise HTTPException(status_code=400, detail="Round not finished")

    result_side = "LONG" if current_round["close"] >= current_round["open"] else "SHORT"

    results = {}

    for user_id, bet in bets.items():
        win = bet["side"] == result_side
        payout = 0.0

        if win:
            mult = 2
            if current_round["gold_mult"] > 0:
                mult *= current_round["gold_mult"]
            payout = bet["amount"] * mult
        else:
            payout = bet["amount"] * (0.5 if bet["insurance"] else 0)

        users[user_id] += payout

        results[user_id] = {
            "win": win,
            "payout": payout,
            "gold_mult": current_round["gold_mult"],
            "side": bet["side"],
            "amount": bet["amount"],
            "insurance": bet["insurance"],
        }

    new_round()
    return results
