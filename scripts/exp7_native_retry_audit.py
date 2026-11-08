"""Read-only audit of native retry warnings that may be absent from RPC/stderr.

Work on temporary database copies, including WAL files. Never infer an HTTP
attempt count from a warning count, and never treat an arbitrary '429' substring
(such as retry_429=false, UUIDs or token counts) as an actual rate-limit error.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

RATE = re.compile(r'last status:\s*429\b|\b429 Too Many Requests\b', re.I)


def audit_native_retries(directory):
    directory = Path(directory)
    source = directory / 'native-sqlite'
    database = source / 'logs_2.sqlite'
    if not database.is_file():
        return {'available': False, 'native_429_retry_log_records': None,
                'other_native_retry_log_records': None, 'events': [],
                'note': 'No per-stage native SQLite telemetry; zero RPC errors does not establish zero native retries.'}
    models = {}
    for path in (directory / 'states').glob('*.json'):
        state = json.loads(path.read_text())
        for turn in state.get('turns', []):
            if turn.get('session_id'):
                models[turn['session_id']] = state['trial']['model']
        if (state.get('pending_turn') or {}).get('session_id_before'):
            models[state['pending_turn']['session_id_before']] = state['trial']['model']
    events = []
    with tempfile.TemporaryDirectory(prefix='native-retry-audit-') as temporary:
        for path in source.glob('logs*'):
            if path.is_file():
                shutil.copyfile(path, Path(temporary) / path.name)
        connection = sqlite3.connect('file:' + str(Path(temporary) / database.name) + '?mode=ro', uri=True)
        total_rows = connection.execute('select count(*) from logs').fetchone()[0]
        rows = connection.execute(
            "select id,ts,ts_nanos,thread_id,feedback_log_body from logs where target='codex_core::responses_retry' order by ts,ts_nanos,id").fetchall()
        for row_id, seconds, nanos, thread, body in rows:
            if 'retrying sampling request' not in body:
                continue
            delay = re.search(r'\bin ([0-9.]+)s', body)
            retry = re.search(r'\bretries=(\d+)', body)
            value = float(delay.group(1)) if delay else None
            timestamp = seconds + nanos / 1e9 if 0 <= nanos < 1e9 else seconds
            events.append({'sqlite_row_id': row_id,
                           'utc': datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                           'model': models.get(thread), 'is_response_429': bool(RATE.search(body)),
                           'retry_count': int(retry.group(1)) if retry else None,
                           'retry_delay_seconds': value,
                           'logged_retry_deadline_utc': datetime.fromtimestamp(timestamp + value, timezone.utc).isoformat() if value is not None else None,
                           'message_sha256': hashlib.sha256(body.encode()).hexdigest()})
        connection.close()
    return {'available': True, 'sqlite_log_rows': total_rows,
            'native_429_retry_log_records': sum(e['is_response_429'] for e in events),
            'other_native_retry_log_records': sum(not e['is_response_429'] for e in events),
            'events': events, 'database_sha256': hashlib.sha256(database.read_bytes()).hexdigest(),
            'note': 'Counts are retained retry warning records, not a count of all HTTP attempts or provider executions. No raw message, credential or account balance is emitted.'}


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    result = {path.parent.name: audit_native_retries(path.parent)
              for path in sorted(args.root.glob('*/summary.json'))
              if (args.root / (path.parent.name + '.comparison-profile.json')).exists()}
    with args.output.open('x') as out:
        json.dump(result, out, indent=2); out.write('\n')
    print(json.dumps({name: {k: value[k] for k in ('available', 'native_429_retry_log_records', 'other_native_retry_log_records')}
                      for name, value in result.items()}, indent=2))


if __name__ == '__main__':
    main()
