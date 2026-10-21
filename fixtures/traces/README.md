# fixtures/traces

This folder will hold recorded runs of the demo sites: one `<site_id>.jsonl` per site, one UI event per line, plus optional failing-step screenshots in `<site_id>/`. The replay player streams them back when `MODE=replay` or when a run asks for replay.
Phase 5 records them against the live sites. The hand-written `../sample-run.jsonl` comes from Phase 1.
