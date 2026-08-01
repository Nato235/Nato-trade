"""
API HTTP + lancement du moteur d'analyse en tâche de fond.
Sur Render (plan gratuit), un seul type de service est autorisé sans carte
bancaire : un "Web Service" qui répond aux requêtes HTTP. On fait donc tourner
la boucle d'analyse (normalement dans main.py) dans un thread à part au sein
de ce même processus, pour n'avoir qu'un seul service à déployer.

Lancement : uvicorn app.api:app --host 0.0.0.0 --port $PORT
"""

import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import config, database
from .main import run_forever

app = FastAPI(title="Nato Trade API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_scalping_state = {"enabled": config.SCALPING_ENABLED}


@app.on_event("startup")
def start_analysis_engine():
    thread = threading.Thread(target=run_forever, daemon=True)
    thread.start()


@app.get("/")
def root():
    return {"status": "Nato Trade en ligne"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/assets")
def get_assets():
    return {"assets": config.ASSETS}


@app.get("/scalping")
def get_scalping_state():
    return _scalping_state


@app.post("/scalping/{state}")
def set_scalping_state(state: str):
    if state not in ("on", "off"):
        raise HTTPException(status_code=400, detail="state doit être 'on' ou 'off'")
    _scalping_state["enabled"] = state == "on"
    return _scalping_state


@app.get("/signals")
def get_signals(asset: str = None, mode: str = None, limit: int = 50):
    query = "SELECT * FROM signals WHERE 1=1"
    params = []
    if asset:
        query += " AND asset = ?"
        params.append(asset)
    if mode:
        query += " AND mode = ?"
        params.append(mode)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with database.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return {"signals": [dict(row) for row in rows]}


@app.get("/performance")
def get_performance():
    return {"summary": database.get_performance_summary()}
