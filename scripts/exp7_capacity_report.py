"""Render derived capacity evidence; never changes frozen data or resumes work."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    suite = json.loads((root / 'suite-summary.json').read_text())
    history = json.loads((root / 'historical-summary.json').read_text())
    quota = json.loads((root / 'quota-metadata-summary.json').read_text())
    frontier = json.loads((root / 'frontier-summary.json').read_text()) if (root/'frontier-summary.json').exists() else None
    evidence = {'suite': suite, 'historical_checkpoint_summary': history, 'historical_quota_metadata': quota,
                'stage_source_sha256': {s['stage']: hashlib.sha256((root/s['stage']/'summary.json').read_bytes()).hexdigest()
                                        for s in suite['stages']}}
    if frontier:
        evidence['request_rate_frontier'] = frontier
        evidence['stage_source_sha256'].update({s['stage']: hashlib.sha256((root/s['stage']/'summary.json').read_bytes()).hexdigest()
                                               for s in frontier['stages']})
    (output / 'results.json').write_text(json.dumps(evidence, indent=2) + '\n')
    stages = suite['stages'] + (frontier['stages'] if frontier else [])
    lines = ['# Persistent 실험 7의 429 및 병렬 효율', '',
        '본실험은 STOP을 유지했다. 아래 부하 측정은 별도 기술 실행이며 본실험에 포함하지 않는다.', '',
        '두 worker의 1초 간격 제한은 각자 적용되어 합계 요청량을 통제하지 못했다. 기존 오류는 응답 RPC의 '
        '`responseTooManyFailedAttempts/httpStatusCode:429`이고, 목록 조회 오류는 관측되지 않았다. '
        '당시 계정 상태에는 사용량 63%가 표시됐고 소진 표시는 없었다. 이것은 순간 부하 원인을 지지하지만 '
        '원래 실패 응답의 HTTP 헤더가 없어 RPM·TPM·동시 요청·중간 게이트웨이 제한 중 하나로 확정할 수 없다.', '',
        '기존 두 VM의 checkpoint 기록 합계는 최대 122회/60초였다. checkpoint는 송신 전 대기를 포함하므로 '
        '공급자에게 실제 도착한 HTTP 요청 수로 해석하지 않는다. CLI 내부 HTTP 재시도 횟수도 확인되지 않았다.', '',
        '새 측정은 Astra와 5.6 Sol의 medium/영어/schema/cards/seq를 사용했다. 전체 turn/start 송신 간격을 '
        '1초로 공유해 계정 전체 부하를 제한했다. 모든 대화는 새 프로세스·대화로 시작했고 34턴 원본 감사를 수행했다.', '',
        '| 단계 | pool | 합계 송신 상한/분 | 완료 대화 | 성공 턴 | 성공 턴/분 | p95 초 | 429 진단 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in stages:
        rate = s.get('successful_turns_per_minute')
        latency = s.get('p95_response_seconds')
        rate_text = f'{rate:.1f}' if rate is not None else '—'
        latency_text = f'{latency:.2f}' if latency is not None else '—'
        ceiling = 60 / s['account_interval_seconds']
        lines.append(f"| {s['stage']} | {s['pool']} | {ceiling:.0f} | {s['sessions_complete']}/{s['sessions_planned']} | "
                     f"{s['successful_turns']} | {rate_text} | {latency_text} | {sum(s['diagnostics'].values())} |")
    chosen = suite.get('recommended_tested_pool')
    lines.extend(['', f'선택된 시험상 효율 pool: {chosen if chosen is not None else "미확정"}.', '',
        '선택 규칙은 429·미확정 요청이 없고 감사가 통과한 단계 중 최대 관측 처리량의 95% 이내에 드는 '
        '가장 작은 pool이다. 별도 확인 단계도 보존한다. 이 숫자는 두 모델/medium 및 시험 시점의 조건에 한정한다. '
        '계정 공통 간격 1초 비교와 더 빠른 요청 경계 시험은 별도의 설정이다. 단계를 순서대로 수행해 시점과 캐시 상태는 무작위 통제하지 않았다. '
        'p95는 로컬 adapter 측정이며 일부 admission 대기를 포함할 수 있다. 한 VM의 공유 limiter 검증이 여러 VM 사이의 분산 제한 구현을 검증하는 것은 아니다. '
        '영구적으로 429가 없다는 보장은 아니며, 다른 모델·effort·context 길이에서는 재평가해야 한다.', '',
        '본실험의 기존 실패·중단 시행과 원본 로그는 보존했고 재전송·대체하지 않았다.', ''])
    (output / 'REPORT.ko.md').write_text('\n'.join(lines))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    normal = [s for s in suite['stages'] if not s['stage'].startswith('confirm')]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    pools = [s['pool'] for s in normal]
    axes[0].plot(pools, [s['successful_turns_per_minute'] for s in normal], 'o-', color='#2463ad')
    axes[0].axhline(60, color='#888888', linestyle='--', linewidth=1, label='1-second send ceiling')
    axes[0].set(xlabel='Total conversation pool', ylabel='Successful turns / minute', title='Measured throughput')
    axes[0].legend(fontsize=8)
    axes[1].plot(pools, [s['p95_response_seconds'] for s in normal], 'o-', color='#b1522d')
    axes[1].set(xlabel='Total conversation pool', ylabel='p95 response seconds', title='Response latency')
    for ax in axes:
        ax.set_xticks(pools)
        ax.grid(alpha=.2)
    fig.suptitle('Two-model technical load test | shared admission: 1 turn/second', fontsize=11)
    fig.savefig(output / 'capacity.png', dpi=180)
    plt.close(fig)
    print(json.dumps({'output': str(output), 'recommended_tested_pool': chosen}))


if __name__ == '__main__':
    main()
