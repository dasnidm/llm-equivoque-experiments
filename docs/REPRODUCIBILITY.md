# Source verification and analysis reproduction

## Current documentation and frozen source

Each study's `freeze.json` records hashes of its original source, questions, and allocations. Some freezes also include the root README and execution plans. The living README now guides readers through completed results, so **historical source-freeze checks need their historical source snapshot**. Freeze hashes have not been changed to accommodate documentation updates.

Use a [result tag](BRANCHES.md), the corresponding result commit, or the frozen source in an analysis package. Previous paths and published reports are preserved. The exact previous README is also [archived](archive/README-before-2026-10-14.md).

## Artifacts and denominators

- `analysis/results/<run_id>/`: reports, CSV tables, figures, audits, and reproduction records.
- `results/<run_id>/`: original JSON, journals, native events, or `raw-archives/`.
- `*.manifest.json`, `index.json`: archive file inventories and SHA-256 verification information.
- `frozen-source.zip`, `frozen-source-and-analysis.zip`: source and required inputs as published.
- Calibration, connectivity checks, development, failed attempts, and excluded attempts are recorded separately from evaluation. Later studies document the user-authorized policy of restarting unfinished conversations; this differs from the initially frozen no-replacement plan.

Reanalyzing saved records and asking models new questions are separate operations. Reproducing existing results does not require a CLI login.

## Latest 180 conversations: reproduce without model calls

Required Python packages: `numpy`, `matplotlib`, and `jsonschema`. The commands below extract the preserved snapshot from Git objects and run under `work/reproduce-question/source/`. They leave published outputs intact and block the model-request function by making it raise an error.

```bash
mkdir -p work/reproduce-question
git show results/question-effect-v1:analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/frozen-source-and-analysis.zip > work/reproduce-question/source.zip
git show results/question-effect-v1:results/equivoque-2026-10-13-question-effect-v1/raw-archives/native-results.tar.gz > work/reproduce-question/native-results.tar.gz
python - <<'PY'
import os
import sys
import tarfile
import zipfile
from pathlib import Path

base = Path('work/reproduce-question').resolve()
destination = base / 'source'
destination.mkdir(exist_ok=True)
with zipfile.ZipFile(base / 'source.zip') as archive:
    archive.extractall(destination)
with tarfile.open(base / 'native-results.tar.gz') as archive:
    archive.extractall(destination, filter='data')
os.chdir(destination)
sys.path.insert(0, str(destination))

from equivoque.transport import CodexTransport
def forbid_model_request(*args, **kwargs):
    raise RuntimeError('Reproduction must not call models')
CodexTransport.request = forbid_model_request

from question_effect.existing_analyze import main as existing_analysis
from question_effect.analyze import export
from question_effect.report import main as build_report
existing_analysis()
export(destination)
build_report()
PY
```

Outputs appear in `work/reproduce-question/source/analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/`. Important audit records include `audit.json` and `tables/physical_invocation_ledger.csv`.

In the same execution environment, **all 14 CSV files, six PNG figures, and the HTML report reproduced byte for byte**, as recorded in the [verification](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/reproduction.json). Other library or font environments may change image bytes; also compare values, axes, and denominators. The ledger separates 5,940 evaluation calls, 12 calibration calls, and 34 excluded capacity-failure calls.

## Other studies

| Study | Starting point |
| --- | --- |
| Single round | [Final report](../analysis/results/equivoque-2026-10-09-v1/attempt-02/REPORT.md) and analysis ZIP at `results/exp1-v1` |
| Three repeated rounds | [Report](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/REPORT.md) and analysis ZIP at `results/exp2-v1` |
| Supplied-rule transfer pilot | [Report](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01/REPORT.md) at `results/exp3-pilot-v1` |
| Thirty-round sequence pilot | [Frozen source](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/attempt-01/frozen-source.zip), [native index](../results/equivoque-2026-10-12-sequence-pilot-v1/raw-archives/index.json), [reproduction record](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/archive-reproduction.json) |
| Ten-round replication | [Frozen source](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/frozen-source.zip), [native index](../results/equivoque-2026-10-12-sequence-replication-v1/raw-archives/index.json), [completion record](../sequence_replication/runtime/analysis-completion.json) |

Commands in the historical root `analysis/README.md` apply to the first study. Use each study's documentation and snapshot to reproduce that study.

## Documentation maintenance checks

```bash
python scripts/validate_repository_docs.py
```

This checks local links, the study catalog, derived tables, key pre/post-disclosure denominators, and record preservation without making model calls. Tables in `docs/data/` are explanatory summaries derived from existing CSV files; they do not replace published tables.
