"""Retain operational progress and publish immutable checkpoints every 150 trials."""
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
RUN='equivoque-2026-10-09-v1'
STATUS=ROOT/'preparation/current-runtime/collection-progress.json'
HISTORY=ROOT/'preparation/current-runtime/expanded-progress-history.jsonl'
baseline=json.loads(STATUS.read_text())['completed']
while True:
    p=json.loads(STATUS.read_text())
    record={k:p[k]for k in ('updated_at','completed','attempted','subject_invocations','active_limit','halted')}
    record['active_executors']=sum(e['process_running']for e in p['executors'].values())
    start=datetime.datetime.fromisoformat('2026-10-09T21:13:08.589333+00:00')
    seconds=(datetime.datetime.fromisoformat(p['updated_at'])-start).total_seconds()
    record['elapsed_since_expansion_seconds']=seconds
    record['completed_since_expansion']=p['completed']-877
    record['average_trials_per_minute_since_expansion']=(p['completed']-877)*60/seconds
    with HISTORY.open('a')as handle:handle.write(json.dumps(record)+'\n')
    print(json.dumps(record),flush=True)
    if p['halted']or all(e['exit_code']==0 for e in p['executors'].values()):break
    if p['completed']-baseline>=150:
        subprocess.run([sys.executable,str(ROOT/'work/coordinator/checkpoint_expanded.py')],cwd=ROOT,check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        baseline=p['completed']
    time.sleep(30)
