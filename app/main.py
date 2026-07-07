from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .models import (
    AddressMapUpdateModel,
    LayoutUpdateModel,
    SimulationResultModel,
    SimulationSnapshotModel,
    TransactionRequestModel,
)
from .protocol import SIMULATOR


ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(
    title="CHI Packet Tracer",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/state", response_model=SimulationSnapshotModel)
def get_state() -> SimulationSnapshotModel:
    return SIMULATOR.snapshot()


@app.get("/api/topology", response_model=SimulationSnapshotModel)
def get_topology() -> SimulationSnapshotModel:
    return SIMULATOR.snapshot()


@app.post("/api/reset", response_model=SimulationSnapshotModel)
def reset() -> SimulationSnapshotModel:
    SIMULATOR.reset()
    return SIMULATOR.snapshot()


@app.post("/api/layout", response_model=SimulationSnapshotModel)
def update_layout(update: LayoutUpdateModel) -> SimulationSnapshotModel:
    return SIMULATOR.update_layout(update)


@app.post("/api/address-map", response_model=SimulationSnapshotModel)
def update_address_map(update: AddressMapUpdateModel) -> SimulationSnapshotModel:
    return SIMULATOR.update_address_map(update)


@app.post("/api/transaction", response_model=SimulationResultModel)
def run_transaction(request: TransactionRequestModel) -> SimulationResultModel:
    return SIMULATOR.simulate(request)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
