# Statistical figures for the completed studies

These figures visualize the preserved **2026-10-23 retrospective exploratory audit**. They introduce no new significance tests or model calls. Global Holm p-values use all **2,889 estimable principal tests** in that audit. Filled markers indicate global Holm p < .05; open markers indicate p ≥ .05. Intervals are nominal pointwise 95% case-block bootstrap intervals, not simultaneous intervals or inversions of the adjusted tests.

[Statistical results](STATISTICS.md) · [한국어 요약](STATISTICS.ko.md) · [Methods](STATISTICAL_METHODS.md)

## Six-study overview

![Six-study statistical overview](data/statistical-figures-2026-10-23/study_overview.png)

[PNG](data/statistical-figures-2026-10-23/study_overview.png) · [SVG](data/statistical-figures-2026-10-23/study_overview.svg)

One representative contrast is shown per study. The full audit also includes other endpoints, route associations, trajectories, predictions and model/effort comparisons. Study 4 has only one shared case and is shown descriptively, without a case-level p-value. Study 6's overview card concerns gpt-5.6-sol's explanation arm only.

## Replication: schedule and frame by model

![Case-block schedule and framing differences by requested model](data/statistical-figures-2026-10-23/replication_by_model.png)

[PNG](data/statistical-figures-2026-10-23/replication_by_model.png) · [SVG](data/statistical-figures-2026-10-23/replication_by_model.svg)

Both panels show round-10 joint-report differences in percentage points, with three effort settings averaged. The schedule contrast pools the two frames; the frame contrast uses constant targets. The all-model row averages a fixed panel and shares data with the model rows. It is not an additional independent replication. Each row has 30 case families. Frames bundle nouns, labels, action verbs and feedback. Model order is not a capability ranking.

## Question intervention: two different endpoints

![Question contrasts on joint reports and influence ratings](data/statistical-figures-2026-10-23/question_contrasts.png)

[PNG](data/statistical-figures-2026-10-23/question_contrasts.png) · [SVG](data/statistical-figures-2026-10-23/question_contrasts.svg)

Each contrast compares pre/post change with the control arm, using 30 matched case families. The left panel uses the joint endpoint; the right uses the continuous impact rating. For gpt-6.1-sol, a zero joint-report change coexists with a 50-point impact reduction in the prediction arm. Constant observations can yield a zero-width bootstrap interval; this does not establish zero population uncertainty. An open marker may have a pointwise interval excluding zero because that interval and the global Holm test use different constructions and multiplicity treatment.

## Values shown in the figures

All plotted inferential values, including raw and adjusted p-values, sample units, effects and intervals, are retained in [plotted_contrasts.csv](data/statistical-figures-2026-10-23/plotted_contrasts.csv). The [complete audit CSV](data/statistics-2026-10-23/contrasts.csv) also retains non-significant, constant and non-estimable comparisons. A joint report is `impact=1 AND counterfactual=no`, not private mechanism knowledge.

## Reproduce

```bash
python scripts/visualize_statistics.py
python scripts/visualize_statistics.py --check
python scripts/validate_repository_docs.py
```

The script reads only existing audit exports, verifies their hashes against the published reproduction record and writes a separate figure directory. PNG and SVG versions are supplied for each figure. The [manifest](data/statistical-figures-2026-10-23/manifest.json) records the source audit commit, input and output hashes, plotting code hash and versions. Byte comparison requires the recorded library/font environment. Original scientific records, statistical tables and generated audit guides remain unchanged.
