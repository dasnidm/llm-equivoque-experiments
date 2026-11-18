"""Durable counts and a public, aggregate-only GitHub dashboard."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from zoneinfo import ZoneInfo

from .schedule import MODELS, EFFORTS


class StatusDB:
    def __init__(self, path, trials):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS trials (id TEXT PRIMARY KEY, model TEXT, effort TEXT, game TEXT, wave TEXT, status TEXT, turns INTEGER, archive TEXT, archive_sha TEXT, archive_bytes INTEGER, scratch TEXT, backup_commit TEXT, error TEXT)')
        if self.db.execute('SELECT count(*) FROM trials').fetchone()[0]:
            raise RuntimeError('Existing run requires explicit crash reconciliation')
        self.db.executemany('INSERT INTO trials (id,model,effort,game,wave,status,turns) VALUES (?,?,?,?,?,?,?)',
            [(t['trial_id'],t['model'],t['effort'],t['game'],t['stage'],'unstarted',0) for t in trials])
        self.db.commit()

    @classmethod
    def attach(cls,path,trials):
        """Open an existing run without inserting or restarting assignments."""
        obj=cls.__new__(cls);obj.lock=threading.RLock()
        obj.db=sqlite3.connect(path,check_same_thread=False,timeout=3)
        obj.db.execute('PRAGMA journal_mode=WAL');obj.db.execute('PRAGMA synchronous=FULL')
        existing=obj.db.execute('SELECT id,model,effort,game,wave FROM trials').fetchall()
        expected={(t['trial_id'],t['model'],t['effort'],t['game'],t['stage']) for t in trials}
        if len(existing)!=len(expected) or set(existing)!=expected:
            obj.db.close();raise ValueError('Existing run does not match frozen assignments')
        return obj

    def resume_snapshot(self):
        with self.lock:
            rows=self.db.execute('SELECT id,status FROM trials').fetchall()
        return dict(rows)

    def hold_active(self, expected_ids):
        """Atomically classify previously running samples without replaying them."""
        expected=set(expected_ids)
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            current={row[0] for row in self.db.execute("SELECT id FROM trials WHERE status='active'")}
            if current!=expected:
                self.db.rollback();raise ValueError('Active trial set changed while preparing recovery')
            self.db.executemany("UPDATE trials SET status='held',error='previous_controller_paused' WHERE id=?",
                                [(x,) for x in expected])
            self.db.commit()

    def update(self, ident, status, **kwargs):
        allowed={'turns','archive','archive_sha','archive_bytes','scratch','backup_commit','error'}
        if not set(kwargs)<=allowed:raise ValueError('Unexpected status field')
        fields={'status':status,**kwargs}
        with self.lock:
            result=self.db.execute('UPDATE trials SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',
                                   [*fields.values(),ident])
            if result.rowcount!=1:raise ValueError('Unknown trial')
            self.db.commit()

    def pending(self, limit=20):
        with self.lock:
            rows=self.db.execute("SELECT id,archive,archive_sha,archive_bytes,scratch,status FROM trials WHERE status IN ('complete_pending_backup','failed_pending_backup') ORDER BY rowid LIMIT ?",(limit,)).fetchall()
        return [{'trial_id':a,'archive':b,'sha256':c,'bytes':d,'scratch':e,'status':f} for a,b,c,d,e,f in rows]

    def counts(self):
        with self.lock:
            rows=self.db.execute('SELECT model,effort,game,wave,status,count(*) FROM trials GROUP BY model,effort,game,wave,status').fetchall()
        return rows


def render(db, transport, run_state, backup_error=None):
    rows=db.counts(); totals={}
    for _,_,_,_,status,n in rows:totals[status]=totals.get(status,0)+n
    wave1=sum(n for _,_,_,w,s,n in rows if w=='wave-1' and s=='complete')
    wave2=sum(n for _,_,_,w,s,n in rows if w=='wave-2' and s=='complete')
    current_time=datetime.now(timezone.utc).astimezone(ZoneInfo('Europe/Berlin')).strftime('%Y-%m-%d %H:%M:%S %Z')
    lines=['# 실험 7 본 실험 현황판 — 카드, 0~100','',
           f'갱신: {current_time} · 약 30초 간격, 페이지 새로고침 필요',
           f'상태: **{run_state}**',
           '42개 조합 × 200개 = 8,400개. 1차 100개씩 종료 후 2차 100개씩 진행.',
           '각 시행은 한 CLI 프로세스와 세션에서 10라운드 및 후속 질문을 진행한다.',
           '실패한 429는 살아 있는 세션에서 안전하게 이력을 확인한 뒤 같은 턴을 재시도한다.', '',
           '## 전체 현황', '', '| 항목 | 상태 |', '| --- | ---: |',
           f"| 완료·비공개 백업 확인 | **{totals.get('complete',0):,} / 8,400** |",
           f'| 1차 완료 | {wave1:,} / 4,200 |',f'| 2차 완료 | {wave2:,} / 4,200 |',
           f"| 진행 중 | {totals.get('active',0):,} |",
           f"| 실패 | {totals.get('failed',0):,} |",f"| 보류 | {totals.get('held',0):,} |",
           f"| 백업 대기 | {totals.get('complete_pending_backup',0)+totals.get('failed_pending_backup',0):,} |",
           f"| 성공 턴 | {transport.attempt_counts.get('success',0):,} |",
           f"| RPC 429 / 재대기 | {transport.attempt_counts.get('rpc_429',0):,} / {transport.attempt_counts.get('requeued',0):,} |",
           f"| 기타 재시도 가능 오류 | {max(0,transport.attempt_counts.get('retryable',0)-transport.attempt_counts.get('rpc_429',0)):,} |",
           f"| 비공개 백업 | {'오류 — 새 요청 대기' if backup_error else '정상 또는 대기 중'} |",'',
           '## 조합별 진행', '',
           '각 칸은 백업 확인까지 마친 완료 시행 수 / 100이다. 실패와 보류는 별도 집계한다.', '',
           '| 모델 | 추론 수준 | obj 1차 | seq 1차 | obj 2차 | seq 2차 | 실패 | 보류 |',
           '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for m in MODELS:
      for e in EFFORTS:
        counts={(g,w,s):n for mm,ee,g,w,s,n in rows if (mm,ee)==(m,e)}
        done=[counts.get((g,w,'complete'),0) for w in ('wave-1','wave-2') for g in ('obj','seq')]
        failed=sum(n for (g,w,s),n in counts.items() if s=='failed')
        held=sum(n for (g,w,s),n in counts.items() if s=='held')
        lines.append(f'| {m} | {e} | {done[0]} / 100 | {done[1]} / 100 | {done[2]} / 100 | {done[3]} / 100 | {failed} | {held} |')
    lines += ['', '원본 대화는 [비공개 원본 저장소](https://github.com/dasnidm/llm-equivoque-exp7-raw/tree/raw/equivoque-exp7-cards-0to100-100x2-20261118)에 보관하며 이 현황판에는 게시하지 않는다. 원본 브랜치는 첫 백업 후 생성된다.',
              '원격 제어 파일: [control.json](control.json). `stop`을 true로 바꾸면 이미 보낸 턴을 임의로 취소하지 않고 새로운 전송을 대기한다.',
              '업데이트 시각이 오래되면 실행 상태를 별도로 확인해야 한다.', '']
    return '\n'.join(lines)


class Dashboard:
    def __init__(self, repo):
        self.repo=Path(repo);self.last_success=0;self.error=None

    def git(self,*args):
        result=subprocess.run(['git','-C',str(self.repo),*args],capture_output=True,
                              timeout=90,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'})
        if result.returncode:raise RuntimeError('Dashboard Git operation failed: '+args[0])
        return result.stdout.decode().strip()

    def sync(self):
        branch=self.git('branch','--show-current')
        if not branch:raise RuntimeError('Dashboard branch is not checked out')
        tracking='refs/remotes/origin/'+branch
        self.git('fetch','-q','--no-tags','origin','refs/heads/'+branch+':'+tracking)
        self.git('merge','--ff-only','-q',tracking)

    def publish(self,text):
        self.sync()
        (self.repo/'README.md').write_text(text)
        self.git('add','README.md')
        self.git('commit','-q','-m','Update experiment 7 progress')
        self.git('push','-q')
        self.last_success=time.monotonic();self.error=None


class RemoteControl:
    def __init__(self, remote, branch, cache, run_id):
        self.remote,self.branch,self.cache,self.run_id=remote,branch,Path(cache),run_id
        self.lock=threading.Lock();self.last=0;self.stopped=True
        subprocess.run(['git','init','--bare','-q',str(self.cache)],check=True)

    def check_once(self):
        with self.lock:
            if time.monotonic()-self.last<10:return not self.stopped
            subprocess.run(['git','--git-dir',str(self.cache),'fetch','-q','--no-tags',self.remote,
                            'refs/heads/'+self.branch+':refs/remotes/exp7/control'],check=True,
                           capture_output=True,timeout=45,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'})
            text=subprocess.check_output(['git','--git-dir',str(self.cache),'show','refs/remotes/exp7/control:control.json'],timeout=30)
            info=json.loads(text)
            if info.get('run_id')!=self.run_id or type(info.get('stop')) is not bool:
                raise ValueError('Invalid remote control')
            self.stopped=info['stop'];self.last=time.monotonic()
            return not self.stopped
