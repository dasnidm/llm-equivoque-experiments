#!/usr/bin/env python3
"""Render README figures from the preserved statistical audit; no new tests or model calls.

Run normally to build, or use --check to reproduce into a temporary directory.
The published audit and its generated guides are read-only inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import tempfile

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("docs/data/statistics-2026-10-23")
OUTPUT = Path("docs/data/statistical-figures-2026-10-23")
GUIDE = Path("docs/STATISTICAL_FIGURES.md")
VERSION = "2026-10-23-figures-v1"
SOURCE_COMMIT = "f07f66c6406b65ca37ac46b18f7024ab59853cbb"
TEAL, GRAY, INK = "#0f766e", "#64748b", "#142c40"
MODELS = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol", "gpt-6-luna",
          "gpt-6-sol", "gpt-6-astra", "gpt-6.1-sol"]
OVERVIEW = [
    ("s1:phase:post-minus-pre:all:impact", "1 · Single-round study",
     "After disclosure minus before", "Impact change (score points)", (-105, 5)),
    ("s2:phase:r3-minus-r1:all:impact", "2 · Three repeated rounds",
     "Round 3 minus round 1", "Impact change (score points)", (-30, 5)),
    ("s3:claim:conflicting-minus-neutral:all:transfer_accuracy", "3 · Supplied-rule transfer",
     "Conflicting minus neutral host claim", "Transfer-accuracy difference (pp)", (-1, 1)),
    (None, "4 · Thirty-round pilot", "Constant target versus sequence", None, None),
    ("s5:kind:obj-minus-seq:r10;all:joint", "5 · Ten-round replication",
     "Constant target minus sequence", "Joint-report difference (pp)", (-5, 40)),
    ("s6:arm:explanation-minus-control:model=gpt-5.6-sol:joint", "6 · Question intervention",
     "gpt-5.6-sol: explanation minus control", "Joint-report change difference (pp)", (-5, 100)),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def p_text(p):
    if not np.isfinite(p) or not 0 < p <= 1:
        raise ValueError(f"Expected an estimable nonzero p-value, received {p}")
    return f"{p:.2e}" if p < .001 else "1.00" if p == 1 else f"{p:.3g}"


def load_inputs():
    expected = json.loads((ROOT / SOURCE / "reproduction.json").read_text())
    inputs = {}
    for name in ["contrasts.csv", "descriptives.csv", "source_manifest.json"]:
        path = ROOT / SOURCE / name
        observed = digest(path)
        if observed != expected["deterministic_output_sha256"][name]:
            raise ValueError(f"Published statistical input hash mismatch: {name}")
        inputs[str(SOURCE / name)] = observed
    tests = pd.read_csv(ROOT / SOURCE / "contrasts.csv")
    if not tests.test_id.is_unique:
        raise ValueError("Statistical contrast IDs must be unique")
    descriptions = pd.read_csv(ROOT / SOURCE / "descriptives.csv")
    principal = int(((tests.inference_scope == "case_block_reference") & tests.p_value.notna()).sum())
    metadata = json.loads((ROOT / SOURCE / "source_manifest.json").read_text())
    if principal != metadata["test_counts"]["principal"]:
        raise ValueError("Principal-test multiplicity family does not match its manifest")
    return tests.set_index("test_id", drop=False), descriptions, inputs, principal


class Figures:
    def __init__(self, destination):
        self.destination = destination
        self.tests, self.descriptions, self.inputs, self.principal = load_inputs()
        self.plotted = {}
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
            "text.color": INK, "axes.labelcolor": INK, "axes.titlecolor": INK,
            "axes.spines.top": False, "axes.spines.right": False,
            "axes.edgecolor": "#cbd5e1", "svg.hashsalt": VERSION,
            "savefig.facecolor": "white"})

    def row(self, test_id, figure, label):
        row = self.tests.loc[test_id]
        if row.inference_scope != "case_block_reference" or row.unit != "case_id":
            raise ValueError(f"A principal figure requires case-block inference: {test_id}")
        values = row[["estimate_display_units", "ci_low_display_units", "ci_high_display_units"]].to_numpy(float)
        if not np.isfinite(values).all() or not values[1] <= values[0] <= values[2]:
            raise ValueError(f"Invalid plotted effect/interval: {test_id}")
        p_text(row.p_value)
        p_text(row.p_holm_global)
        if row.p_holm_global + 1e-15 < row.p_value:
            raise ValueError(f"Invalid adjusted probability: {test_id}")
        self.plotted[(figure, test_id)] = dict(figure=figure, label=label, **row.to_dict())
        return row

    def save(self, fig, name):
        fig.savefig(self.destination / f"{name}.png", dpi=180, bbox_inches="tight",
                    metadata={"Software": VERSION})
        svg = self.destination / f"{name}.svg"
        fig.savefig(svg, bbox_inches="tight", metadata={"Date": None})
        # Matplotlib path lines contain trailing spaces; normalize only new SVGs.
        svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
        plt.close(fig)

    @staticmethod
    def point(ax, row, y):
        significant = row.p_holm_global < .05
        color = TEAL if significant else GRAY
        effect, low, high = row[["estimate_display_units", "ci_low_display_units", "ci_high_display_units"]]
        ax.errorbar(effect, y, xerr=[[effect-low], [high-effect]], fmt="o",
            color=color, markerfacecolor=color if significant else "white",
            markeredgewidth=1.6, markersize=7, linewidth=2, capsize=3, zorder=3)

    def overview(self):
        fig, axes = plt.subplots(3, 2, figsize=(13.8, 11.5))
        fig.subplots_adjust(left=.035, right=.975, top=.89, bottom=.095, hspace=.18, wspace=.10)
        fig.suptitle("Six completed studies, with statistical uncertainty", x=.035, y=.974,
                     ha="left", fontsize=21, weight="bold")
        fig.text(.035, .935, f"Representative contrasts from the retrospective audit | global Holm family: {self.principal:,} tests",
                 fontsize=12, color=GRAY)
        for card, (test_id, title, contrast, xlabel, limits) in zip(axes.flat, OVERVIEW):
            card.set_axis_off()
            card.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=.01,rounding_size=.025",
                transform=card.transAxes, facecolor="#f8fafc", edgecolor="#dce5ed", clip_on=False))
            card.text(.04, .89, title, transform=card.transAxes, fontsize=14, weight="bold")
            card.text(.04, .77, contrast, transform=card.transAxes, fontsize=11.6)
            if test_id is None:
                self.pilot_card(card)
                continue
            row = self.row(test_id, "study_overview", contrast)
            effect, low, high = row[["estimate_display_units", "ci_low_display_units", "ci_high_display_units"]]
            unit = "pp" if row.units == "percentage points" else "points"
            card.text(.04, .62, f"{effect:+.2f} {unit}", transform=card.transAxes, fontsize=22,
                      color=TEAL if row.p_holm_global < .05 else GRAY, weight="bold")
            card.text(.04, .50, f"Pointwise 95% CI [{low:+.2f}, {high:+.2f}]", transform=card.transAxes, fontsize=11)
            ax = card.inset_axes([.07, .31, .86, .12])
            self.point(ax, row, 0)
            ax.axvline(0, color="#94a3b8", linestyle="--", linewidth=1)
            ax.set(xlim=limits, ylim=(-1, 1), yticks=[])
            ax.spines.left.set_visible(False)
            ax.tick_params(axis="x", labelsize=9, pad=1)
            ax.set_xlabel(xlabel, fontsize=9, labelpad=1)
            card.text(.04, .135, f"Raw p={p_text(row.p_value)}   |   Global Holm p={p_text(row.p_holm_global)}",
                      transform=card.transAxes, fontsize=10.6)
            card.text(.04, .045, f"{int(row.n_pairs):,} matched pairs · {int(row.n_blocks)} case families",
                      transform=card.transAxes, fontsize=10, color=GRAY)
        fig.text(.035, .050, "Filled teal: global Holm p < .05. Open markers: p ≥ .05. Intervals are pointwise and do not invert the adjusted tests.", fontsize=10)
        fig.text(.035, .027, "Joint report = impact 1 AND counterfactual no. The pilot is descriptive; reports do not directly measure private mechanism knowledge.", fontsize=10)
        self.save(fig, "study_overview")

    def pilot_card(self, card):
        d = self.descriptions
        d = d[(d.study == "s4") & (d.phase == "r30") & (d.metric == "joint") & (d.aggregation == "condition")].set_index("kind")
        if set(d.index) != {"obj", "seq"} or not (d.n_cases == 1).all():
            raise ValueError("Pilot denominators do not represent a single shared case")
        counts = [f"{int(d.loc[k, 'events'])}/{int(d.loc[k, 'n_valid'])}" for k in ["obj", "seq"]]
        card.text(.04, .61, " versus ".join(counts), transform=card.transAxes, fontsize=22, color=GRAY, weight="bold")
        card.text(.04, .49, "Final joint reports · descriptive comparison", transform=card.transAxes, fontsize=11)
        ax = card.inset_axes([.23, .32, .68, .12])
        ax.barh([1, 0], [100*d.loc[k, "mean"] for k in ["obj", "seq"]], height=.55, color=["#829bb0", "#cbd5e1"])
        ax.set(xlim=(0, 100), yticks=[1, 0], yticklabels=["Constant", "Sequence"], xticks=[0, 50, 100])
        ax.tick_params(labelsize=9, length=0)
        ax.spines.left.set_visible(False)
        ax.set_xlabel("Joint reports (%)", fontsize=9, labelpad=0)
        card.text(.04, .135, "Case-level p-value unavailable: one shared case", transform=card.transAxes, fontsize=10.6)
        card.text(.04, .045, f"{int(d.n_valid.sum())} conversations · fixed seven-model panel", transform=card.transAxes, fontsize=10, color=GRAY)

    def forest_table(self, fig, slots, rows, labels, *, title, xlabel, limits, show_labels):
        ax, table = [fig.add_subplot(slot) for slot in slots]
        count = len(rows)
        for y, row in enumerate(rows):
            if y % 2 == 0:
                ax.axhspan(y-.45, y+.45, color="#f1f5f9", zorder=0)
                table.axhspan(y-.45, y+.45, color="#f1f5f9", zorder=0)
            self.point(ax, row, y)
            color = TEAL if row.p_holm_global < .05 else INK
            table.text(.02, y, f"{row.estimate_display_units:+.1f}", va="center", fontsize=10.5, color=color)
            table.text(.48, y, p_text(row.p_holm_global), va="center", fontsize=10.5, color=color)
        ax.set(xlim=limits, ylim=(count-.5, -.75), yticks=range(count),
               yticklabels=labels if show_labels else [""]*count, xlabel=xlabel)
        ax.axvline(0, color="#94a3b8", linewidth=1, linestyle="--")
        ax.grid(axis="x", color="#e2e8f0", linewidth=.7)
        ax.tick_params(axis="y", length=0, labelsize=11, pad=8)
        ax.spines.left.set_visible(False)
        ax.set_title(title, fontsize=13, weight="bold", loc="left", pad=32)
        table.set(xlim=(0, 1), ylim=ax.get_ylim())
        table.set_axis_off()
        table.text(.02, 1.025, "Effect", transform=table.transAxes, fontsize=10, weight="bold")
        table.text(.48, 1.025, "Holm p", transform=table.transAxes, fontsize=10, weight="bold")

    def detailed_figure(self, name, title, subtitle, specs, labels, footer):
        count = len(labels)
        fig = plt.figure(figsize=(14.5, max(6.8, 3.2 + .48*count)))
        grid = fig.add_gridspec(1, 4, width_ratios=[3.2, 1.35, 3.2, 1.35],
                               left=.16, right=.98, top=.765, bottom=.245, wspace=.11)
        fig.suptitle(title, x=.035, y=.98, ha="left", fontsize=20, weight="bold")
        fig.text(.035, .91, subtitle, fontsize=11.5, color=GRAY)
        for index, (heading, ids, xlabel, limits) in enumerate(specs):
            rows = [self.row(test_id, name, label) for test_id, label in zip(ids, labels)]
            if not all(row.n_blocks == 30 for row in rows):
                raise ValueError(f"Expected 30 case families in {name}")
            self.forest_table(fig, [grid[2*index], grid[2*index+1]], rows, labels,
                              title=heading, xlabel=xlabel, limits=limits, show_labels=index == 0)
        handles = [Line2D([], [], marker="o", color=TEAL, linestyle="none", label="Global Holm p < .05"),
                   Line2D([], [], marker="o", color=GRAY, markerfacecolor="white", linestyle="none", label="Global Holm p ≥ .05")]
        fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(.03, .085), frameon=False, ncol=2, fontsize=10.5)
        fig.text(.035, .060, footer, fontsize=10)
        fig.text(.035, .026, "Pointwise 95% case-block bootstrap intervals; global Holm covers all principal audit tests. No new significance tests are run here.", fontsize=9.7)
        self.save(fig, name)

    def replication(self):
        scopes = ["all"] + [f"model={model}" for model in MODELS]
        labels = ["All tested models"] + MODELS
        specs = [
            ("Constant target minus sequence", [f"s5:kind:obj-minus-seq:r10;{scope}:joint" for scope in scopes],
             "Joint-report difference (pp)", (-12, 82)),
            ("Cards minus cats · constant target", [f"s5:frame:cards-minus-cats:r10;kind=obj;{scope}:joint" for scope in scopes],
             "Joint-report difference (pp)", (-12, 82)),
        ]
        self.detailed_figure("replication_by_model", "Schedule and framing differences depend on the model",
            "Study 5 · round 10 · three effort settings averaged · 30 shared case families · model order is not a ranking",
            specs, labels, "All-model contrasts: 1,260 schedule pairs / 630 frame pairs. Per model: 180 / 90 pairs. Frames bundle wording, labels and feedback.")

    def questions(self):
        combinations = [(model, arm) for model in ["gpt-5.6-sol", "gpt-6.1-sol"] for arm in ["explanation", "prediction"]]
        labels = [f"{model}\n{arm.capitalize()} − control" for model, arm in combinations]
        specs = []
        for metric, title, xlabel, limits in [
            ("joint", "Change in joint reports", "Difference in change (pp)", (-6, 95)),
            ("impact", "Change in influence rating", "Difference in change (score points)", (-95, 6)),
        ]:
            ids = [f"s6:arm:{arm}-minus-control:model={model}:{metric}" for model, arm in combinations]
            specs.append((title, ids, xlabel, limits))
        self.detailed_figure("question_contrasts", "Question effects differ across models and endpoints",
            "Study 6 · high effort · cards · sequence targets · pre-disclosure rerating · 30 matched cases per contrast",
            specs, labels, "All 30 gpt-6.1-sol prediction-arm ratings changed 100 → 50; joint reports stayed zero. Constant data can give degenerate intervals.")


def make_guide(principal):
    lines = ["# Statistical figures for the completed studies",
        "These figures visualize the preserved **2026-10-23 retrospective exploratory audit**. They introduce no new significance tests or model calls. "
        f"Global Holm p-values use all **{principal:,} estimable principal tests** in that audit. Filled markers indicate global Holm p < .05; open markers indicate p ≥ .05. "
        "Intervals are nominal pointwise 95% case-block bootstrap intervals, not simultaneous intervals or inversions of the adjusted tests.",
        "[Statistical results](STATISTICS.md) · [한국어 요약](STATISTICS.ko.md) · [Methods](STATISTICAL_METHODS.md)",
        "## Six-study overview", "![Six-study statistical overview](data/statistical-figures-2026-10-23/study_overview.png)",
        "[PNG](data/statistical-figures-2026-10-23/study_overview.png) · [SVG](data/statistical-figures-2026-10-23/study_overview.svg)",
        "One representative contrast is shown per study. The full audit also includes other endpoints, route associations, trajectories, predictions and model/effort comparisons. "
        "Study 4 has only one shared case and is shown descriptively, without a case-level p-value. Study 6's overview card concerns gpt-5.6-sol's explanation arm only.",
        "## Replication: schedule and frame by model", "![Case-block schedule and framing differences by requested model](data/statistical-figures-2026-10-23/replication_by_model.png)",
        "[PNG](data/statistical-figures-2026-10-23/replication_by_model.png) · [SVG](data/statistical-figures-2026-10-23/replication_by_model.svg)",
        "Both panels show round-10 joint-report differences in percentage points, with three effort settings averaged. "
        "The schedule contrast pools the two frames; the frame contrast uses constant targets. "
        "The all-model row averages a fixed panel and shares data with the model rows. It is not an additional independent replication. "
        "Each row has 30 case families. Frames bundle nouns, labels, action verbs and feedback. Model order is not a capability ranking.",
        "## Question intervention: two different endpoints", "![Question contrasts on joint reports and influence ratings](data/statistical-figures-2026-10-23/question_contrasts.png)",
        "[PNG](data/statistical-figures-2026-10-23/question_contrasts.png) · [SVG](data/statistical-figures-2026-10-23/question_contrasts.svg)",
        "Each contrast compares pre/post change with the control arm, using 30 matched case families. The left panel uses the joint endpoint; "
        "the right uses the continuous impact rating. For gpt-6.1-sol, a zero joint-report change coexists with a 50-point impact reduction in the prediction arm. "
        "Constant observations can yield a zero-width bootstrap interval; this does not establish zero population uncertainty. "
        "An open marker may have a pointwise interval excluding zero because that interval and the global Holm test use different constructions and multiplicity treatment.",
        "## Values shown in the figures", "All plotted inferential values, including raw and adjusted p-values, sample units, effects and intervals, are retained in "
        "[plotted_contrasts.csv](data/statistical-figures-2026-10-23/plotted_contrasts.csv). The [complete audit CSV](data/statistics-2026-10-23/contrasts.csv) "
        "also retains non-significant, constant and non-estimable comparisons. A joint report is `impact=1 AND counterfactual=no`, not private mechanism knowledge.",
        "## Reproduce", "```bash\npython scripts/visualize_statistics.py\npython scripts/visualize_statistics.py --check\npython scripts/validate_repository_docs.py\n```",
        "The script reads only existing audit exports, verifies their hashes against the published reproduction record and writes a separate figure directory. "
        "PNG and SVG versions are supplied for each figure. The [manifest](data/statistical-figures-2026-10-23/manifest.json) records the source audit commit, input and output hashes, "
        "plotting code hash and versions. Byte comparison requires the recorded library/font environment. Original scientific records, statistical tables and generated audit guides remain unchanged."]
    return "\n\n".join(lines) + "\n"


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    figures = Figures(destination)
    figures.overview()
    figures.replication()
    figures.questions()
    table = pd.DataFrame(list(figures.plotted.values())).sort_values(["figure", "test_id"])
    table.to_csv(destination / "plotted_contrasts.csv", index=False, float_format="%.17g", lineterminator="\n")
    guide = make_guide(figures.principal)
    manifest = dict(version=VERSION, source_audit_commit=SOURCE_COMMIT,
        inference="Display of existing retrospective case-block tests; no new tests or multiplicity families",
        principal_test_family=figures.principal, plotted_rows=len(table), inputs_sha256=figures.inputs,
        plotting_code_sha256=digest(Path(__file__)),
        versions=dict(python=platform.python_version(), numpy=np.__version__, pandas=pd.__version__, matplotlib=matplotlib.__version__),
        outputs_sha256={p.name:digest(p) for p in sorted(destination.iterdir()) if p.is_file() and p.name != "manifest.json"},
        guide_sha256=hashlib.sha256(guide.encode()).hexdigest())
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest, guide


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Reproduce figures and guide and compare every output byte")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="equivoque-figures-") as temporary:
            observed, guide = build(Path(temporary))
            expected = json.loads((ROOT / OUTPUT / "manifest.json").read_text())
            if observed != expected or (ROOT / GUIDE).read_text() != guide:
                raise AssertionError("Statistical figure reproduction mismatch")
            for name, sha in expected["outputs_sha256"].items():
                if digest(ROOT / OUTPUT / name) != sha:
                    raise AssertionError(f"Published figure/output differs from its manifest: {name}")
        print("PASS: all three PNG/SVG figures, plotted values, manifest and guide reproduce byte for byte; no new tests or model calls.")
    else:
        _, guide = build(ROOT / OUTPUT)
        (ROOT / GUIDE).write_text(guide)
        print(f"Generated three statistical figures and their source values in {OUTPUT}; existing audit unchanged.")


if __name__ == "__main__":
    main()
