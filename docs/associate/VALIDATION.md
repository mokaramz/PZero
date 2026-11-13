# Validating Project Zero (for reviewers and agents)

Everything below runs offline against **copies** of data. Never point any tool at the real `project-zero-data`
folder, and never use port 8177 (the owner's running instance).

## 1. One command

```
powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -E2E
```
Runs ruff, pytest, TypeScript, vitest, the production build, then boots v2 on :8179 with the seed data and runs every
Playwright spec. Exit code 0 = all green.

## 2. Behaviour parity with v1

```
cd backend
.venv\Scripts\python scripts\parity.py --post          # expect: 208/208 endpoints identical
.venv\Scripts\python scripts\parity.py --only people,events -v
```
v1 is rebuilt from git tag `v1-legacy` (cached in `%TEMP%\pz-v1-legacy`). Both servers run on fresh copies of
`.parity-snapshot/` (a frozen copy of real data, git-ignored; delete it and parity can't run). POST scenarios live in
`scripts/parity_posts.json`. To look at v1 in a browser: `scripts\run_legacy.py --port 8190`.

## 3. Visual evidence

Screenshots are in `screenshots/` — see [screenshots/README.md](../screenshots/README.md). Regenerate:

```
# start v2 against a data copy (example)
set PZ_DATA=%TEMP%\pz-v2-shots&& xcopy /E /I /Q .parity-snapshot %TEMP%\pz-v2-shots
cd backend && .venv\Scripts\python -m projectzero --port 8179 --no-browser
# in another shell
cd e2e && set PZ_BASE_URL=http://127.0.0.1:8179&& npx playwright test tests/smoke.spec.ts
```
`smoke.spec.ts` uses no API mocks: it visits all 16 views and fails on any page error, console error, 5xx API
response or horizontal overflow (1440px and 1366×768 @150%). Single ad-hoc captures: `node e2e/tools/shoot.mjs <url> <out.png> [--full] [--zoom 1.5]`.

## 4. Current results (2026-09-27)

| Check | Result |
|---|---|
| Backend tests | 536 passed |
| Frontend unit tests | 13 passed (Deal Flow routing/attention rules, formatting, navigation) |
| ruff / tsc | clean |
| Parity v1↔v2 | 208/208 identical (GET + POST scenarios, real-data snapshot) |
| Browser E2E | 79 feature tests + 18 unmocked smoke tests passed against the production build |
