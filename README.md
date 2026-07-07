# CHI Packet Tracer

A Python-first visual simulator for a small Arm CHI-style coherent fabric. The current slice focuses on a colorful topology view, a transaction timeline, credit returns, cache state, and snoop filter state for:

- `ReadShared`
- `WriteUnique`
- `CleanShared`
- `MakeInvalid`

The protocol engine lives in Python so the transaction rules and topology can be extended without a JavaScript build chain.

## Run

> **Note:** Requires Python 3.10+ (the `match` statement is used by dependencies). If your system `python` is older, use the full path to a newer Python installation.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000`.

## Structure

- `app/models.py`: API and UI data models
- `app/protocol.py`: CHI simulation logic and state transitions
- `app/main.py`: FastAPI app and endpoints
- `static/`: HTML, CSS, and JavaScript frontend
- `tests/test_protocol.py`: basic regression tests for read and write flows

## Extending

- Add or reposition nodes in `app/protocol.py`
- Add more opcode handlers in `Simulator.simulate`
- Expand the address map through the UI or `app/protocol.py`

This is a visual teaching/debugging tool, not a cycle-accurate CHI verification environment.
