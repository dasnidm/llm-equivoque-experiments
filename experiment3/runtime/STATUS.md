# Experiment 3 pilot preparation status

Run `equivoque-2026-10-11-exp3-pilot-v1`: pilot only, 2,016 assigned single-turn tasks. No evaluation task has been requested.

All existing 20 tests and 8 new pilot checks passed, including the full 2,016-task simulation, rule/rename invariants, disjoint assignment, strict response parsing, failure/no-replay, missingness and native archive tampering checks. Both earlier freezes remain unchanged. The new freeze covers 115 files. Preparation commit: fdf738ba0d574021c30c0854b2f5ef60230f0e85. Twenty separate worker worktrees are prepared at that source.

Actual inference probes of gpt-6-sol/low and gpt-6.1-sol/low each failed HTTP 401 authentication. They are separately retained calibration failures, not evaluation. The initial catalog did not advertise gpt-6.1-sol; because the actual token cannot refresh, this cached catalog does not establish account access. Reauthenticate and rerun shared readiness in a fresh numbered directory, then all twenty worker checks, before releasing the coordinator gate. Never substitute models or replay uncertain tasks.

Active network policy is unrestricted/enforced at revision 31. The inference endpoint was reached and rejected the authentication token. GitHub authentication works. Device-login codes and credentials are not included in repository artifacts.
