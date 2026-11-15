"""Card dashboard on top of the tested Git-coordination state machine."""
from exp7_main_v2.coordination import *  # noqa: F401,F403
from exp7_main_v2.coordination import GitCoordinator as _GitCoordinator
from exp7_main.coordination import _github_repository_url
from pathlib import Path
import json
import tempfile


def card_readme(board, remote=None):
    text = render_readme(board, _github_repository_url(remote) if remote else None)
    initial = [j for j in board['jobs'].values() if j.get('stage') == 'initial-50']
    counts = {k: sum(j['counts'][k] for j in initial)
              for k in ('complete', 'failed', 'interrupted', 'unstarted')}
    lines = ['', '## 카드 실험 초기 50개 단계', '',
             f"배정 {sum(j['n_trials'] for j in initial):,}개 · 완료 {counts['complete']:,}개 · "
             f"실패 {counts['failed']:,}개 · 중단 {counts['interrupted']:,}개 · "
             f"미시작 또는 진행 중 {counts['unstarted']:,}개", '',
             '초기 50개 단계 이후 나머지 150개는 자동 시작하지 않는다.', '',
             '## 모델별 기술 점검', '', '| 모델 | 완료 / 배정 | 상태 |', '|---|---:|---|']
    for model, item in sorted(board['models'].items()):
        progress = item.get('technical_progress', {})
        n = progress.get('finished', 0)
        status = '실패' if progress.get('failed') else '완료' if n == 3 else '진행 중' if item.get('owner') else '대기'
        lines.append(f'| {model} | {n} / 3 | {status} |')
    return text.rstrip() + '\n' + '\n'.join(lines) + '\n'


class GitCoordinator(_GitCoordinator):
    def _commit(self, parent, board, message):
        validate_board(board)
        content = json.dumps(board, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
        blob = self._git('hash-object', '-w', '--stdin', input_text=content).strip()
        readme = self._git('hash-object', '-w', '--stdin', input_text=card_readme(board, self.remote)).strip()
        with tempfile.TemporaryDirectory(prefix='coord-index-', dir=self.cache_dir) as tmp:
            env = {'GIT_INDEX_FILE': str(Path(tmp) / 'index')}
            self._git('read-tree', parent if parent else '--empty', env_extra=env)
            self._git('update-index', '--add', '--cacheinfo', '100644', blob, BOARD_PATH, env_extra=env)
            self._git('update-index', '--add', '--cacheinfo', '100644', readme, 'README.md', env_extra=env)
            tree = self._git('write-tree', env_extra=env).strip()
        args = ['commit-tree', tree]
        if parent:
            args += ['-p', parent]
        return self._git(*args, input_text=message+'\n').strip()
