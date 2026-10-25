# IntentLock

A hands-off issue-to-production loop where the agent must declare what it is allowed to change **before** it writes code, and a deterministic check holds the diff to that contract.

> Status: skeleton. Gates, agents and Cloud Run deploy land over the weekend.

## Run locally

```bash
pip install -r requirements.txt
python -m pytest
uvicorn app.main:app --reload
```

## Layout

```
app/        FastAPI demo service (pricing rules)
tests/      unit tests
ci/         deterministic gates (drift_check, verify, injection_screen, receipt)
agents/     agent prompts
flows/      flow definition
```

## License

MIT
