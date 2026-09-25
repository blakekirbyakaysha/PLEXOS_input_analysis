# Demand–weather materiality check (NEM)

This is a first-pass, exploratory analysis. It asks whether daily NEM regional electricity demand responds to heating and cooling degree days (HDD/CDD) strongly and stably enough to justify giving AEMO OPSO reference-year traces different annual and seasonal energy by weather year. AEMO currently grows every reference-year trace to the same annual energy target. This is not a forecast, a package or a production pipeline.

- **Spec and phase task cards:** [docs/PLAN.md](docs/PLAN.md)
- **State between sessions:** [docs/PROGRESS.md](docs/PROGRESS.md). Read it first, every session.
- Reference PDFs: `docs/reference/`. Example of house style and QueryTool use: `docs/examples/monthly_update.ipynb` (reference only).

## How to run a phase (orchestrating session)

1. Read `docs/PROGRESS.md`. Confirm the previous phase is `Reviewed`. If not, stop and tell the user.
2. Set the phase to `In progress`. Spawn one implementation agent with `Agent(model="sonnet", subagent_type="general-purpose")`. Its prompt must contain:
   - the phase task card from `docs/PLAN.md`, verbatim
   - every Spec section the card references, verbatim
   - the handover notes of earlier phases from `docs/PROGRESS.md`
   - these hard rules
3. When the agent finishes, review its work yourself:
   - read the code
   - run the acceptance checks and the reviewer checks listed on the card
   - look at outputs and figures
4. If there are problems, send fixes back to the same agent (SendMessage), or fix small issues directly.
5. Record the review in `docs/PROGRESS.md`: status `Reviewed` or `Needs fixes`, plus review notes.
6. Commit with message `Phase N: <summary>`, then report to the user.

Phase 5 (`findings.md`) is written by the orchestrating session itself, not delegated.

## Hard rules (for every agent)

- Follow the Spec. If the Spec is wrong or ambiguous, stop and record it under "Open issues" in PROGRESS. Do not improvise.
- No silent imputation, guessing of columns, units, timestamps or IDs, or fallback behaviour. Fail loudly with a clear message.
- Keep it minimal: plain scripts and notebooks. No packages, config frameworks, logging, CLIs, classes-for-the-sake-of-it or GUIs.
- Do not edit files owned by earlier phases unless the task card says so. `helper_functions.py` is read-only; reuse `qt_post_request`.
- Python: `C:/anaconda3/python.exe` (pandas 2.2, statsmodels 0.14, pyarrow 19, matplotlib 3.10). Run with `-W ignore`; the helper uses `verify=False`.
- `NEMPOINT_API_KEY` is already set in the environment. Only Phase 1 may query QueryTool. Later phases read parquet from `data/`.
- Large QueryTool queries time out (HTTP 524). Chunk them as the task card says.
- Charts: consult the `dataviz` skill first. Use the Akaysha colour constants from `docs/examples/monthly_update.ipynb` (PINE `#003723`, MOSS `#00743C`, JADE `#007864`, SPRING `#46C86E`, LIME `#C7F77A`, AMARANTH `#E75751`, AMBER `#F69B4E`, AQUA `#99D9E7`, AZURE `#509EE3`). Do not load the Inter font (the file is absent). Save PNGs to `outputs/figures/`.
- Before finishing, update your phase section of `docs/PROGRESS.md` with:
  - files created
  - commands run
  - key numbers
  - deviations from the Spec
  - open issues

  Then set the status to `Done – awaiting review`. Do not start the next phase.
