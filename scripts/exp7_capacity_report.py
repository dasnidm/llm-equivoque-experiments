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
    mixed_path = root/'mixed80-p4'/'summary.json'
    mixed = json.loads(mixed_path.read_text()) if mixed_path.exists() else None
    diagnostics_path = root/'frontier-diagnostics.json'
    diagnostics = json.loads(diagnostics_path.read_text()) if diagnostics_path.exists() else None
    evidence = {'suite': suite, 'historical_checkpoint_summary': history, 'historical_quota_metadata': quota,
                'stage_source_sha256': {s['stage']: hashlib.sha256((root/s['stage']/'summary.json').read_bytes()).hexdigest()
                                        for s in suite['stages']}}
    if frontier:
        evidence['request_rate_frontier'] = frontier
        evidence['stage_source_sha256'].update({s['stage']: hashlib.sha256((root/s['stage']/'summary.json').read_bytes()).hexdigest()
                                               for s in frontier['stages']})
    if mixed:
        evidence['mixed_design_validation'] = mixed
        evidence['stage_source_sha256']['mixed80-p4'] = hashlib.sha256(mixed_path.read_bytes()).hexdigest()
    if diagnostics:
        evidence['frontier_diagnostics'] = diagnostics
    (output / 'results.json').write_text(json.dumps(evidence, indent=2) + '\n')
    stages = suite['stages'] + (frontier['stages'] if frontier else [])
    timing = {}
    for stage in stages:
        directory = root / stage['stage']
        records = [json.loads(line) for line in (directory/'meter.jsonl').read_text().splitlines()]
        first = records[0]['monotonic'] if records else 0
        last = records[-1]['monotonic'] if records else 0
        steady = [r for r in records if r['kind']=='turn/completed' and r.get('status')=='completed'
                  and first+20 <= r['monotonic'] < first+140]
        turns = [t for path in (directory/'states').glob('*.json') for t in json.loads(path.read_text()).get('turns',[])]
        timing[stage['stage']] = {'fixed_20_to_140_seconds_turns_per_minute': len(steady)/2 if last-first>=140 else None,
            'max_recorded_duration_seconds':max((t.get('duration_seconds',0) for t in turns),default=None),
            'input_tokens_summed':sum(t.get('usage_last',{}).get('input_tokens',0) for t in turns),
            'cached_input_tokens_summed':sum(t.get('usage_last',{}).get('cached_input_tokens',0) for t in turns)}
    evidence['derived_timing_and_usage'] = timing
    valid = [s for s in stages if s['sessions_complete']==s['sessions_planned'] and s['complete_session_audits_ok']
             and not s['uncertain_pending_states'] and not s['stop_reason'] and not any(s['diagnostics'].values())]
    fastest = max(valid, key=lambda s:s['successful_turns_per_minute']) if valid else None
    if fastest:
        candidates = [s for s in valid if s['successful_turns_per_minute'] >= .95*fastest['successful_turns_per_minute']]
        efficient = min(candidates, key=lambda s:(s['pool'],60/s['account_interval_seconds']))
        evidence['efficient_observed_configuration'] = {k:efficient[k] for k in ('stage','pool','account_interval_seconds',
            'successful_turns_per_minute','successful_turns','sessions_complete')}
    (output / 'results.json').write_text(json.dumps(evidence, indent=2) + '\n')
    lines = ['# Persistent 실험 7의 429 및 병렬 효율', '',
        '본실험은 STOP을 유지했다. 아래 부하 측정은 별도 기술 실행이며 본실험에 포함하지 않는다.', '',
        '시행 하나는 10라운드와 후속 질문을 합친 34턴이다. persistent는 프로세스와 대화를 재사용하지만 '
        '매 턴의 모델 추론 요청을 한 번으로 합치는 기능은 아니다. 대화가 길어지면 각 요청의 입력 context도 커진다. '
        'ThreadPool의 대화 수, 실제 진행 중인 RPC 턴, 분당 송신 수, 입력 토큰량을 별도로 관리해야 한다.', '',
        '두 worker의 1초 간격 제한은 각자 적용되어 합계 요청량을 통제하지 못했다. 기존 오류는 응답 RPC의 '
        '`responseTooManyFailedAttempts/httpStatusCode:429`이고, 목록 조회 오류는 관측되지 않았다. '
        '당시 계정 상태에는 사용량 63%가 표시됐고 소진 표시는 없었다. 이것은 순간 부하 원인을 지지하지만 '
        '원래 실패 응답의 HTTP 헤더가 없어 RPM·TPM·동시 요청·중간 게이트웨이 제한 중 하나로 확정할 수 없다.', '',
        '기존 두 VM의 checkpoint 기록 합계는 최대 122회/60초였다. checkpoint는 송신 전 대기를 포함하므로 '
        '공급자에게 실제 도착한 HTTP 요청 수로 해석하지 않는다. CLI 내부 HTTP 재시도 횟수도 확인되지 않았다.', '',
        '새 측정은 Astra와 5.6 Sol의 medium/영어/schema/cards/seq를 사용했다. 기본 pool 비교는 전체 turn/start 송신 간격을 '
        '1초로 공유했고, 후속 요청 속도 경계 시험은 표의 다른 간격을 사용했다. 모든 대화는 새 프로세스·대화로 시작했고 완료된 대화에 34턴 원본 감사를 수행했다.', '',
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
    lines.extend(['', f'합계 송신 상한 60회/분에서 선택된 시험상 효율 pool: {chosen if chosen is not None else "미확정"}.', '',
        '선택 규칙은 429·미확정 요청이 없고 감사가 통과한 단계 중 최대 관측 처리량의 95% 이내에 드는 '
        '가장 작은 pool이다. 별도 확인 단계도 보존한다. 이 숫자는 두 모델/medium 및 시험 시점의 조건에 한정한다. '
        '계정 공통 간격 1초 비교와 더 빠른 요청 경계 시험은 별도의 설정이다. 단계를 순서대로 수행해 시점과 캐시 상태는 무작위 통제하지 않았다. '
        'p95는 로컬 adapter 측정이며 일부 admission 대기를 포함할 수 있다. 한 VM의 공유 limiter 검증이 여러 VM 사이의 분산 제한 구현을 검증하는 것은 아니다. '
        '영구적으로 429가 없다는 보장은 아니며, 다른 모델·effort·context 길이에서는 재평가해야 한다.', '',
        '본실험의 기존 실패·중단 시행과 원본 로그는 보존했고 재전송·대체하지 않았다.', ''])
    if fastest:
        lines.extend([f"오류 없이 통과한 전체 설정 중 최고 관측 처리량의 95% 이내에 드는 가장 작은 pool은 "
                      f"`{efficient['stage']}`: pool {efficient['pool']}, 합계 송신 간격 {efficient['account_interval_seconds']:.3f}초, "
                      f"관측 {efficient['successful_turns_per_minute']:.1f}턴/분이다.", ''])
    if mixed:
        mixed_ok = (mixed['sessions_complete']==6 and mixed['complete_session_audits_ok']
                    and not mixed['uncertain_pending_states'] and not mixed['stop_reason'] and not any(mixed['diagnostics'].values()))
        lines.extend([f"혼합 조건 별도 확인: 4 pool, 합계 상한 80회/분, 완료 {mixed['sessions_complete']}/6, "
                      f"성공 {mixed['successful_turns']}턴, 관측 {mixed['successful_turns_per_minute']:.1f}턴/분, "
                      f"429 진단 {sum(mixed['diagnostics'].values())}, 전체 통과 {mixed_ok}.",
                      '혼합 확인은 두 모델에서 각 low·medium·high 한 개씩, 여섯 game·네 format·R 조건을 포함한 작은 확인이며 전체 교차 설계나 다른 모델에 일반화하지 않는다.', ''])
    elif frontier and frontier.get('stopped_at'):
        lines.extend(['경계 시험의 첫 429에서 신규 송신을 중단했으므로 이후 120회/분과 혼합 조건 검증은 수행하지 않았다.', ''])
    if diagnostics:
        lines.extend(['실제 로컬 turn/start admission의 최대 60초 창 횟수는 ' + ', '.join(
            f"{name}: {item['peak_rolling60_actual_turn_start_admissions']}회" for name,item in diagnostics.items()) +
            '였다. 이 횟수는 공급자 내부 HTTP 재시도까지 세는 값은 아니다.', ''])
    (output / 'REPORT.ko.md').write_text('\n'.join(lines))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    normal = [s for s in suite['stages'] if not s['stage'].startswith('confirm')]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    pools = [s['pool'] for s in normal]
    axes[0].plot(pools, [s['successful_turns_per_minute'] for s in normal], 'o-', color='#2463ad', label='Full-stage completion rate')
    axes[0].plot(pools, [timing[s['stage']]['fixed_20_to_140_seconds_turns_per_minute'] for s in normal], 's--', color='#24918b', label='Fixed seconds 20-140')
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
    if frontier:
        fig, ax = plt.subplots(figsize=(7,4), constrained_layout=True)
        passed = [s for s in frontier['stages'] if s in valid]
        failed = [s for s in frontier['stages'] if s not in valid]
        if passed:
            ax.plot([60/s['account_interval_seconds'] for s in passed],
                    [s['successful_turns_per_minute'] for s in passed], 'o-',label='Completed, audited, no 429')
        if failed:
            ax.scatter([60/s['account_interval_seconds'] for s in failed],
                       [s['successful_turns_per_minute'] for s in failed],marker='x',s=80,color='#b52d2d',label='Stopped: partial rate before failure')
        ax.set(xlabel='Configured aggregate send ceiling / minute',ylabel='Observed successful turns / minute',
               title='Two independently paced model workers with shared account admission')
        ax.grid(alpha=.2);ax.legend(fontsize=8)
        fig.savefig(output/'request_rate_frontier.png',dpi=180)
        plt.close(fig)
    print(json.dumps({'output': str(output), 'recommended_tested_pool': chosen}))


if __name__ == '__main__':
    main()
