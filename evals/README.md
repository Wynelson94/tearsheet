# Trust evaluation harness

Live qualification runs for the probation question: **does tearsheet ever fail silently?**

```bash
.venv/bin/python evals/run_eval.py               # full corpus (~40 items) + burst mode
.venv/bin/python evals/run_eval.py --skip-burst
.venv/bin/python evals/run_eval.py --only quo,heyrosie
```

- `corpus.json` — the target manifest. Volatile pages are scored by INVARIANT
  (no figure the page carries may go missing silently); immutable pages get exact
  baselines pinned in `baselines/` on first run.
- `run_eval.py` — isolated cache per run, independent lxml oracle (never the tool's
  own text function), evidence archived per item, count-based gates, and a verdict
  that refuses to exist when the corpus isn't reachable.
- `reports/<date>/report.md` — the scorecard. `reports/<date>/evidence/<id>/` — raw
  bytes + returned strings for human re-adjudication after pages drift.
- Failures get demoted into permanent offline fixtures (`tests/fixtures/probation/`).

Run before any probation-lift decision and after every dependency upgrade.
