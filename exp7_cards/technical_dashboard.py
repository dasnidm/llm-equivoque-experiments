"""Publish aggregate technical progress only to a new, dedicated Git branch."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time


def snapshot(root, running):
    root = Path(root)
    stages = sorted(p for p in root.glob('stage-*') if p.is_dir())
    lines = ['# 실험 7: 최대 속도 기술 점검 현황', '',
             '본수집이 아닌 별도 기술 시험이다. 응답 원문과 인증 정보는 게시하지 않는다.', '',
             '기존 [본 실험 현황판](https://github.com/dasnidm/llm-equivoque-experiments/tree/exp7/cards-200-coordination-20261115)은 중단 상태다.', '',
             f'갱신: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
             f'기술 시험 프로세스: {"실행 중" if running else "종료됨 — 아래 단계 결과 확인"}', '']
    if not stages:
        return '\n'.join(lines + ['단계 준비 중.', ''])
    for stage in stages:
        lines += [f'## {stage.name}', '']
        profile = stage/'profile.json'
        summary = stage/'summary.json'
        if profile.exists():
            p = json.loads(profile.read_text())
            limit = '없음' if p['target_rpm'] is None else f"{p['target_rpm']:g}회/분"
            lines += [f"요청 상한 {limit} · 동시 대화 {p['concurrency']}개", '']
        if summary.exists():
            s = json.loads(summary.read_text())
            lines += [f"완료 대화 {s['session_statuses'].get('complete', 0)}개 / {s['planned_sessions']}개 · "
                      f"성공 턴 {s['successful_calls']}개 · 관측 처리량 {s['observed_successes_per_minute']:.1f}회/분",
                      f"미확정 대화 {s['uncertain_sessions']}개 · 도구 이벤트 {s['forbidden_tool_events']}개 · "
                      f"컨텍스트 압축 {s['compaction_events']}개 · native 429 기록 {s['native_429_retry_log_records']}", '']
            if 'rpc_429_error_attempts' in s:
                lines += [f"RPC 429 오류 {s['rpc_429_error_attempts']}개 · 재시도 가능한 오류 {s['retryable_error_attempts']}개", '']
        else:
            lines += ['| 모델 | 추론 수준 | 상태 | 완료 턴 / 34 |', '|---|---|---|---:|']
            for path in sorted((stage/'states').glob('tech-*.json')):
                try:
                    s = json.loads(path.read_text())
                    lines.append(f"| {s['trial']['model']} | {s['trial']['effort']} | {s['status']} | {len(s['turns'])} / 34 |")
                except (OSError, json.JSONDecodeError, KeyError):
                    continue
            lines.append('')
    sweep = root/'sweep-summary.json'
    if sweep.exists():
        s = json.loads(sweep.read_text())
        lines += [f"자동 속도 탐색 상태: `{s['status']}`", '']
    return '\n'.join(lines)


def active(pid):
    try:
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes()
        return b'exp7_cards.technical_sweep' in cmd or b'exp7_cards.max_retry_stage' in cmd
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--branch', required=True)
    parser.add_argument('--remote', required=True)
    parser.add_argument('--pid', required=True, type=int)
    args = parser.parse_args()
    if args.repo.exists():
        raise RuntimeError('Dashboard repo already exists; inspect before starting another publisher')
    head = subprocess.check_output(['git', 'ls-remote', '--heads', args.remote, 'refs/heads/'+args.branch])
    if head.strip():
        raise RuntimeError('Dashboard branch already exists; do not overwrite it')
    args.repo.mkdir(parents=True)
    def git(*cmd):
        return subprocess.run(['git', '-C', str(args.repo), *cmd], check=True, capture_output=True)
    git('init', '-q')
    git('config', 'user.name', 'Exp7 dashboard')
    git('config', 'user.email', 'exp7-dashboard@localhost')
    git('remote', 'add', 'origin', args.remote)
    git('checkout', '-q', '-b', args.branch)
    while True:
        running = active(args.pid)
        (args.repo/'README.md').write_text(snapshot(args.root, running))
        git('add', 'README.md')
        git('commit', '-q', '-m', 'Update technical throughput progress')
        git('push', '-q', 'origin', 'HEAD:refs/heads/'+args.branch)
        if not running:
            break
        time.sleep(45)


if __name__ == '__main__':
    main()
