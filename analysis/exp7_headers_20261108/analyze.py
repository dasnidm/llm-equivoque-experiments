"""Reproduce the header diagnosis locally; never send requests or load auth."""
import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read(path):
    return json.loads(path.read_text())


def seconds(value):
    return dt.datetime.fromisoformat(value).timestamp()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/workspace/work"))
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "results")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    roots = {phase: args.root / f"exp7-header-probe-20261108-{phase}-v1"
             for phase in ("canary", "load")}
    summaries = {phase: read(root / "summary.json") for phase, root in roots.items()}
    profiles = {phase: read(root / "profile.json") for phase, root in roots.items()}
    retries = {phase: read(root / "native-retry-audit.json") for phase, root in roots.items()}
    for phase, root in roots.items():
        scan = read(root / "credential-scan.json")
        if scan["matched_files"] or scan["skipped_files"] or not summaries[phase]["credential_scan_clean"]:
            raise ValueError("Private evidence did not pass its in-memory credential scan")
    records = sorted((json.loads(line) for line in
                      (roots["load"] / "http-responses.jsonl").read_text().splitlines()),
                     key=lambda row: row["started_monotonic"])
    success = [row for row in records if row["status"] == 200]
    errors = [row for row in records if row["status"] >= 400]
    start = min(seconds(row["started_at"]) for row in records)
    end = max(seconds(row["ended_at"]) for row in records)
    events = sorted((seconds(row[key]), delta) for row in records
                    for key, delta in (("started_at", 1), ("ended_at", -1)))
    count = peak = 0
    area = 0.0
    previous = start
    occupancy = [(0.0, 0)]
    for time, delta in events:
        area += (time - previous) * count
        count += delta
        peak = max(peak, count)
        occupancy.append((time - start, count))
        previous = time
    durations = [row["duration_seconds"] for row in success]
    stop = read(roots["load"] / "HEADER_STOP.json")
    states = []
    for path in sorted((roots["load"] / "states").glob("*.json")):
        state = read(path)
        turns = state["turns"]
        successful = [turn for turn in turns if turn.get("ok")]
        states.append({"trial_id": state["trial"]["trial_id"],
                       "model": state["trial"]["model"], "status": state["status"],
                       "successful_turns": len(successful),
                       "unsuccessful_recorded_turns": len(turns) - len(successful),
                       "unsent_pending_turn": state.get("pending_turn") is not None,
                       "successful_turn_pid_count": len({t["process_pid"] for t in successful}),
                       "successful_turn_thread_count": len({t["session_id"] for t in successful}),
                       "actual_tool_events": sum(t.get("tool_events", 0) for t in turns)})
    total_ok = sum(row["successful_turns"] for row in states)
    if total_ok != len(success):
        raise ValueError("HTTP success and successful logical turn evidence disagree")
    receipts = {phase: read(args.root / "backups" / root.name / "receipt.json")
                for phase, root in roots.items()}
    repo = Path(__file__).resolve().parents[2]
    freeze_sha = hashlib.sha256((repo / "manifests" /
                                "equivoque-2026-11-08-exp7-persistent-v1" /
                                "freeze.json").read_bytes()).hexdigest()
    metrics = {
        "run_id": profiles["load"]["run_id"],
        "sample_role": "technical header diagnosis; main samples=0",
        "source_sha256": profiles["load"]["source_sha256"],
        "cli_version": profiles["load"]["cli_version"],
        "binary_sha256": profiles["load"]["binary_sha256"],
        "models": sorted({row["model"] for row in states}), "effort": "medium",
        "transport": profiles["load"]["transport"],
        "configured_pool": profiles["load"]["pool"],
        "configured_minimum_start_interval_seconds": profiles["load"]["minimum_upstream_start_interval"],
        "configured_start_ceiling_per_minute": 60 / profiles["load"]["minimum_upstream_start_interval"],
        "load": {"upstream_requests": len(records), "successful_logical_turns": total_ok,
                 "status_counts": summaries["load"]["status_counts"],
                 "loopback_http_attempts": summaries["load"]["loopback_http_attempts"],
                 "local_gate_denials_not_upstream": summaries["load"]["locally_denied_requests"],
                 "first_start": records[0]["started_at"],
                 "first_429_start": next(row["started_at"] for row in records if row["status"] == 429),
                 "first_429_headers_at": next(row["headers_at"] for row in records if row["status"] == 429),
                 "last_response_closed": max(row["ended_at"] for row in records),
                 "admission_span_seconds": records[-1]["started_monotonic"] - records[0]["started_monotonic"],
                 "elapsed_first_start_to_last_response_seconds": end - start,
                 "short_burst_successes_per_minute_not_sustained": total_ok / (end - start) * 60,
                 "actual_peak_inflight_http": peak,
                 "mean_inflight_http": area / (end - start),
                 "success_latency_median_seconds": statistics.median(durations),
                 "success_latency_p95_seconds_inclusive": statistics.quantiles(durations, n=100, method="inclusive")[94],
                 "native_retry_warning_records": retries["load"]["native_429_retry_log_records"],
                 "new_upstream_starts_after_stop": sum(seconds(row["started_at"]) > seconds(stop["at"]) for row in records),
                 "conversation_status_counts": dict(collections.Counter(row["status"] for row in states)),
                 "conversations": states},
        "canary": {key: summaries["canary"][key] for key in
                   ("upstream_requests", "status_counts", "credential_scan_clean")},
        "all_live_upstream_requests_canary_plus_load": sum(s["upstream_requests"] for s in summaries.values()),
        "main_freeze_sha256": freeze_sha,
        "main_freeze_unchanged": all(freeze_sha == profile["main_freeze_sha256"] for profile in profiles.values()),
        "main_STOP_preserved": all(summary["main_STOP_unchanged"] for summary in summaries.values()),
        "old_technical_HALT_preserved": (args.root / "exp7-cli-upgrade-20261108" / "HALT").is_file(),
        "credential_scan_clean_both_phases": all(summary["credential_scan_clean"] for summary in summaries.values()),
        "private_backup_readback_receipts": receipts,
    }
    write(args.out / "metrics.json", metrics)
    # These values were explicitly allowlisted by the relay. Request headers,
    # cookies, credits/balances and original RPC contents never enter this report.
    example = max(success, key=lambda row: row["started_monotonic"])
    write(args.out / "headers-and-error.json", {
        "last_success_selected_response_headers": example["headers"],
        "errors": [{"ticket": row["ticket"], "status": row["status"],
                    "started_at": row["started_at"], "headers_at": row["headers_at"],
                    "selected_response_headers": row["headers"], "error": row.get("error"),
                    "private_error_body_sha256": [body["sha256"] for body in row.get("error_bodies", [])]}
                   for row in errors],
        "fixed_RPM_or_TPM_limit_present": any(key.startswith(("x-ratelimit-limit", "ratelimit-limit"))
                                               for row in records for key in row["headers"]),
    })
    with (args.out / "timeline.csv").open("w", newline="") as stream:
        fields = ["ticket", "started_at", "headers_at", "ended_at", "status", "duration_seconds"]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True, constrained_layout=True,
                             gridspec_kw={"height_ratios": [2, 1]})
    x_start = [seconds(row["started_at"]) - start for row in records]
    x_done = sorted(seconds(row["ended_at"]) - start for row in success)
    axes[0].step([0] + x_start, [0] + list(range(1, len(records) + 1)),
                 where="post", label=f"Upstream starts ({len(records)})", color="#3269b2")
    axes[0].step([0] + x_done, [0] + list(range(1, len(success) + 1)),
                 where="post", label=f"Successful turns ({len(success)})", color="#178064")
    error_at = seconds(errors[0]["headers_at"]) - start
    axes[0].annotate("HTTP 429: turn_rate_limit_exceeded\nRetry-After: 22 seconds",
                     xy=(error_at, 104), xytext=(10, 75),
                     arrowprops={"arrowstyle": "->", "color": "#b62f3d"}, color="#b62f3d")
    axes[0].set(ylabel="Cumulative requests / turns", title="Codex header diagnostic: bounded load, no retries")
    axes[0].legend(loc="upper left")
    axes[1].step([point[0] for point in occupancy], [point[1] for point in occupancy],
                 where="post", color="#3269b2")
    axes[1].set(xlabel="Seconds since first upstream request", ylabel="In-flight HTTP", ylim=(-.2, 8.8))
    axes[1].set_yticks([0, 2, 4, 6, 8])
    for ax in axes:
        ax.axvline(error_at, color="#b62f3d", linestyle="--", linewidth=1)
        ax.grid(alpha=.2)
    fig.savefig(args.out / "request_timeline.png", dpi=170)
    plt.close(fig)
    print(json.dumps({"output": str(args.out), "load_requests": len(records),
                      "successful_turns": total_ok, "actual_peak_inflight": peak,
                      "new_upstream_starts_after_stop": metrics["load"]["new_upstream_starts_after_stop"],
                      "main_freeze_unchanged": metrics["main_freeze_unchanged"]}))


if __name__ == "__main__":
    main()
