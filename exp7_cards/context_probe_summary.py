"""Summarize a separately retained technical trial, without exposing raw text or IDs."""
from pathlib import Path
import json


def summarize(root):
    root = Path(root)
    state = json.loads((root / 'state.json').read_text())
    trial, turns = state['trial'], state['turns']
    session_ids = {t.get('session_id') for t in turns if t.get('ok')}
    process_ids = {t.get('process_pid') for t in turns if t.get('ok')}
    usage = []
    raw_compactions = 0
    files = sorted(root.glob('native/*/turn-*/rpc-received.jsonl'))
    for path in files:
        count = int(path.parent.name.split('-')[-1])
        last = None
        for line in path.read_text().splitlines():
            message = json.loads(line)
            method = str(message.get('method', ''))
            params = message.get('params', {})
            item_type = str(params.get('item', {}).get('type', '')) if isinstance(params, dict) else ''
            if 'compact' in method.lower() or 'compact' in item_type.lower():
                raw_compactions += 1
            if method == 'thread/tokenUsage/updated':
                record = params.get('tokenUsage', {})
                last = {'turn': count, 'context_window': record.get('modelContextWindow'),
                        'last_total_tokens': record.get('last', {}).get('totalTokens'),
                        'last_input_tokens': record.get('last', {}).get('inputTokens'),
                        'last_output_tokens': record.get('last', {}).get('outputTokens')}
        if last is not None:
            usage.append(last)
    usage.sort(key=lambda x: x['turn'])
    return {'technical_only': True, 'model': trial['model'], 'effort': trial['effort'],
            'frame': trial['frame'], 'game': trial['game'], 'trial_status': state['status'],
            'turns_received': len(turns), 'all_turns_ok': all(t.get('ok') for t in turns),
            'same_session': len(session_ids) == 1 and None not in session_ids,
            'same_process': len(process_ids) == 1 and None not in process_ids,
            'state_recorded_compaction_events': sum(t.get('compaction_events', 0) for t in turns),
            'raw_rpc_compaction_notifications': raw_compactions,
            'usage_telemetry_turns': len(usage), 'usage_by_turn': usage}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    print(json.dumps(summarize(p.parse_args().root), ensure_ascii=False, indent=2))
