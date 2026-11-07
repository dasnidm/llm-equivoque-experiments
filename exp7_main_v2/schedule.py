"""Same assignments and design, with a separate operational run identity."""
from exp7_main.schedule import (
    SEED, MODELS, EFFORTS, FRAMES, FORMATS, ARMS, GAMES, ORDER,
    COMMON_SEQUENCE, CALLS_PER_SESSION, build as _build,
    build_jobs, audit, save_bundle, load_bundle,
)

RUN_ID = 'equivoque-2026-11-07-exp7-main-v2'


def build(run_id=RUN_ID, seed=SEED):
    plan = _build(run_id=run_id, seed=seed)
    plan['operations_version'] = 'verified-compressed-job-storage-v2'
    plan['scientific_design_changed_from_v1'] = False
    return plan


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(save_bundle(build(), args.output), ensure_ascii=False, indent=2))
