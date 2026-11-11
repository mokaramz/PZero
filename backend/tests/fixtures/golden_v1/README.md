# Golden fixtures v1 — protected ranking rules

Copied unchanged from the old repository `Desktop\project-zero` at revision
`6c739b9cb6ca2517b845e381d39a36c50eccc59e`, `backend/tests/fixtures/golden/`. They were generated there by
`_generate.py` from the ORIGINAL v1 modules (git tag `v1-legacy`) on the frozen parity snapshot.

| File | sha256 | Content |
|---|---|---|
| `inbox_sample.json` | `a1af71497d308111e4c204e0348cf9a8b8fae078cfb0052894ce06e768398571` | input: 141 candidates (every 4th of the parity snapshot), `last_run` 2026-09-27 19:50:11 |
| `attention_themes.json` | `fc938d48ecb16c4d356cba4648b3b4bf9096a21a7961a3d14eb894e192ea1dfe` | v1 outputs per candidate: gate, entity_type/info, score_v2, differentiation, annotate, annotate_v3, annotate_v31, themes_for, lens_signals, technical_founder_evidence; constants |
| `connectors_text.json` | `f1220f27c10ba8df62b9bc7f9196460ddb1bb51e0dd4645772c33fa0399feaa6` | v1 text helpers per candidate (only `norm_company` is used by the ranking port) |

Never regenerate these from the NEW code: they are the oracle. `tests/dealflow/test_ranking_golden.py` checks the
sha256 values above before comparing anything.
