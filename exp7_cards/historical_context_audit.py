"""Read-only historical context-event and usage-counter audit; no model calls."""
from collections import Counter, defaultdict
from pathlib import Path
import json
import statistics

from .schedule import EFFORTS, MODELS


def collect(root):
    root = Path(root)
    results = root / 'results/equivoque-2026-10-12-sequence-replication-v1'
    files = sorted(results.glob('worker-*/trials/*__cards__*.json'))
    stats = defaultdict(list)
    event_count = 0
    ids = set()
    for path in files:
        state = json.loads(path.read_text())
        t, trial = state['turns'], state['trial']
        if (state.get('status') != 'complete' or len(t) != 33 or trial.get('frame') != 'cards'
                or state.get('session_id') in ids or not state.get('session_id')):
            raise ValueError('Expected unique, completed, 33-turn historical card sessions')
        ids.add(state['session_id'])
        if any(not r.get('ok') or r.get('turn') != i for i, r in enumerate(t, 1)):
            raise ValueError('Missing or failed historical turn')
        values = [r['usage']['input_tokens'] for r in t[:30]]
        if any(b < a for a, b in zip(values, values[1:])):
            raise ValueError('Usage counters are not monotone')
        stats[(trial['model'], trial['effort'])].append(values[29] - values[28])
        for row in t:
            for event in row.get('events', []):
                if ('compact' in str(event.get('type', '')).lower()
                        or 'compact' in str(event.get('item', {}).get('type', '')).lower()):
                    event_count += 1
    if len(files) != 1260 or set(stats) != {(m, e) for m in MODELS for e in EFFORTS}:
        raise ValueError('Unexpected number of card sessions or model/effort combinations')
    if any(len(v) != 60 for v in stats.values()):
        raise ValueError('Unexpected historical per-configuration sample size')
    audit = json.loads((root / 'analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/union_audit.json').read_text())
    if not audit.get('integrity_ok') or audit.get('assigned') != 2520:
        raise ValueError('Historical union audit is unavailable or invalid')
    catalog = json.loads((root / 'manifests/equivoque-2026-11-08-exp7-persistent-v1/model-catalog.json').read_text())
    windows = {m['slug']: m.get('context_window') for m in catalog['models'] if m['slug'] in MODELS}
    return {'historical_card_sessions': len(files), 'observed_event_types_with_compact': event_count,
            'full_exp5_sessions': audit['assigned'], 'full_exp5_audited_compaction_events': len(audit['compaction_events']),
            'context_catalog_is_historical': True, 'historical_catalog_context_windows': windows,
            'turn30_input_counter_increment': [
                {'model': m, 'effort': e, 'sessions': len(values), 'min': min(values),
                 'median': statistics.median(values), 'max': max(values)}
                for (m, e), values in sorted(stats.items())],
            'interpretation': 'Counter increments are not a direct measurement of current context occupancy.',
            'no_new_model_calls': True}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    print(json.dumps(collect(parser.parse_args().root), ensure_ascii=False, indent=2))
