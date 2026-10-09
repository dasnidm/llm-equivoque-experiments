"""Retain operational progress and publish immutable checkpoints every 100 trials or five minutes."""
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
last_checkpoint=time.monotonic()
while True:
    p=json.loads(STATUS.read_text())
    record={k:p[k]for k in ('updated_at','completed','attempted','subject_invocations','active_limit','halted')}
    record['active_executors']=sum(e['process_running']for e in p['executors'].values())
    epoch=p.get('execution_epoch','resume-03')
    gate=json.loads((ROOT/'preparation/current-runtime/coordinator-launch-05.json').read_text())
    start=datetime.datetime.fromisoformat(gate['released_at'])
    seconds=(datetime.datetime.fromisoformat(p['updated_at'])-start).total_seconds()
    record['execution_epoch']=epoch
    record['elapsed_since_expansion_seconds']=seconds
    record['completed_since_expansion']=p['completed']-1622
    record['average_trials_per_minute_since_expansion']=(p['completed']-1622)*60/seconds
    with HISTORY.open('a')as handle:handle.write(json.dumps(record)+'\n')
    print(json.dumps(record),flush=True)
    if p['halted']or all(e['exit_code']==0 for e in p['executors'].values()):break
    if p['completed']-baseline>=100 or time.monotonic()-last_checkpoint>=300:
        subprocess.run([sys.executable,str(ROOT/'work/coordinator/checkpoint_expanded.py')],cwd=ROOT,check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        baseline=p['completed'];last_checkpoint=time.monotonic()
    time.sleep(30)
