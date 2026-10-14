# Repository guide

- Start with `README.md`, `docs/STATUS.md`, and `docs/EXPERIMENTS.md`.
- Six recorded experiments/pilots are complete. Historical handoffs, plans, and
  runtime files describe their dates, not a current request to start collection.
- Treat `protocol/`, experiment-specific frozen source, `manifests/`, `results/`,
  and existing `analysis/results/` artifacts as scientific records. Keep those
  bytes unchanged during documentation maintenance. Add clearly labeled derived
  summaries under `docs/` rather than silently revising a published result.
- The living root README differs from the README in historical freezes. Use a
  result tag or the frozen-source archive for source validation/reproduction.
  Never regenerate historical freeze hashes merely to accommodate new docs.
- Documentation checks: `python scripts/validate_repository_docs.py`. This reads
  local records/Git objects and does not make model calls. Do not launch inference
  as a routine check for documentation changes.
- `docs/data/` contains derived summaries with explicit source references. Keep
  predictions matching the generator, mismatches, and uncertainty separate.
- Preserve independent conversations, rounds, and prediction components as
  different units. A joint impact1/counterfactual-no report is not a private
  mechanism-knowledge score. State limitations of small samples and exploratory
  intervals.
- Branch policy and recovery information: `docs/BRANCHES.md`. Preserve completed
  result branches/tags and existing worktrees. Use a short-lived work branch for
  future changes; archive unique commits before retiring an obsolete branch.
