"""Offline deadline scenarios; does not alter an allocation or launch models."""
from collections import Counter
from datetime import datetime, timezone
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    bundle = Path('manifests/equivoque-2026-11-08-exp7-persistent-v1')
    rows = [json.loads(line) for line in gzip.open(bundle/'assignments.jsonl.gz','rt')]
    evidence = json.loads(Path('analysis/exp7_capacity_20261108_final/results.json').read_text())
    fast = evidence['efficient_observed_configuration']['successful_turns_per_minute']
    margin = next(s['successful_turns_per_minute'] for s in evidence['request_rate_frontier']['stages'] if s['stage']=='rpm80-p4')
    selected_stages = [s for s in evidence['suite']['stages']+evidence['request_rate_frontier']['stages']
                       if s['stage'] in ('confirm-p4','rpm80-p4','rpm100-p6')]
    input_mean = sum(evidence['derived_timing_and_usage'][s['stage']]['input_tokens_summed'] for s in selected_stages)/sum(s['successful_turns'] for s in selected_stages)
    cells = Counter((r['model'],r['effort'],r['frame'],r['arm'],r['game']) for r in rows)
    pair = {'gpt-6-astra','gpt-5.6-sol'}
    a = {k:v for k,v in cells.items() if k[0] in pair and k[1]=='medium'}
    b = {k:80 for k in cells if k[3]=='en_schema' and k[4] in ('obj','seq')}
    assert sum(a.values())==6488 and len(a)==120
    assert sum(b.values())==7680 and len(b)==96
    blocks = Counter('R_A' if r['arm']=='R_A' else 'core_obj_seq' if r['game'] in ('obj','seq') else 'fixed_rule_controls' for r in rows)
    options = {'full_unchanged':len(rows), 'A_two_models_medium_full_cells':sum(a.values()),
               'B_all_profiles_core80_english_schema':sum(b.values()),
               'B96_all_profiles_core96_english_schema':96*96,
               'B120_all_profiles_core120_english_schema':96*120,
               'C_one_model_all_efforts_full_cells':sum(r['model']=='gpt-6-astra' for r in rows)}
    def timing(n):
        turns=n*34
        return {'conversations':n,'turns':turns,
            'hours_at_fast_test':turns/fast/60,'hours_at_margin_test':turns/margin/60,
            'hours_at_fast_with_20percent_lower_rate':turns/(fast*.8)/60,
            'hours_at_margin_with_20percent_lower_rate':turns/(margin*.8)/60}
    result = {'status':'proposal_only_no_collection','created_at':datetime.now(timezone.utc).isoformat(),
        'original_freeze_sha256':hashlib.sha256((bundle/'freeze.json').read_bytes()).hexdigest(),
        'rates':{'fast_tested_turns_per_minute':fast,'margin_tested_turns_per_minute':margin},
        'measured_rate_scope':'Astra and 5.6 Sol, medium, fixed English/schema sequence; not all profiles or full format mixture',
        'original_allocation_blocks':dict(blocks),'scenarios':{k:timing(v) for k,v in options.items()},
        'full_design_required_rates':{str(days):{'sustained_turns_per_minute':len(rows)*34/(days*1440),
            'capacity_if_20percent_unavailable':len(rows)*34/(days*1440*.8),
            'illustrative_input_tokens_per_minute':len(rows)*34/(days*1440)*input_mean} for days in (2,3)},
        'illustrative_mean_input_tokens_per_turn':input_mean,
        'current_eight_worker_nominal_ceiling_per_minute':480,
        'full_design_days_at_that_client_ceiling':len(rows)*34/(480*1440),
        'notes':['No original manifest, freeze, result, STOP or worker was modified.',
                 'The 20-percent loss is a scenario assumption, not a measured deadline forecast.',
                 'A and B are smaller first-stage scopes, not completion of all original 24-profile/all-format goals.',
                 'A preserves within-cell counts and all formats/games/R for two medium profiles; omits other profiles.',
                 'B retains all 24 profiles and both frames for English/schema obj/seq; other formats/controls/R deferred.',
                 'B proposes 40 development and 40 holdout conversations per cell, target-balanced for obj; not instantiated.']}
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'scenarios.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    with (args.output/'proposed_cell_counts.csv').open('x',newline='') as f:
        w=csv.writer(f,lineterminator='\n');w.writerow(['proposal','model','effort','frame','arm','game','conversations'])
        for label,table in [('A',a),('B',b)]:
            for key,value in sorted(table.items()):w.writerow([label,*key,value])
    lines=['# 실험 7의 2~3일 완료 방안 — 미실행 제안','',
      '기존 전체 배정과 freeze 및 STOP을 유지한다. 이 문서는 실행 승인이 아니라 범위와 용량을 선택하기 위한 계산이다.', '',
      f'전체 77,856대화·2,647,104턴을 3일에 완료하려면 평균 612.8턴/분, 2일이면 919.1턴/분이 필요하다. '
      f'최근 최고 통과 속도 {fast:.1f}턴/분의 약 7.3~11배다. '
      '기존 8개 worker의 최소 1초 간격만으로도 명목 상한은 480턴/분이라, 서버 제한이 없어도 약 3.8일이 하한이다.', '',
      '| 후보 | 대화 | 턴 | 83.7턴/분 가정 | 66.7턴/분 가정 | 범위 변화 |',
      '|---|---:|---:|---:|---:|---|']
    text = {'full_unchanged':'원래 전체 설계', 'A_two_models_medium_full_cells':'A: 두 모델 medium, 모든 조건·셀별 표본 유지',
            'B_all_profiles_core80_english_schema':'B: 24 profile, 영어/schema obj·seq 각 80회',
            'B96_all_profiles_core96_english_schema':'B96: 같은 핵심 범위 각 96회',
            'B120_all_profiles_core120_english_schema':'B120: 같은 핵심 범위 각 120회',
            'C_one_model_all_efforts_full_cells':'C: 한 모델의 low/medium/high, 모든 조건·셀별 표본 유지'}
    for name,s in result['scenarios'].items():
        lines.append(f"| {name} | {s['conversations']:,} | {s['turns']:,} | {s['hours_at_fast_test']:.1f}시간 | {s['hours_at_margin_test']:.1f}시간 | {text[name]} |")
    lines.extend(['', '## 가장 현실적인 두 제안','',
      'A는 현재 측정한 Astra와 5.6 Sol의 medium 두 profile에 집중한다. 카드/고양이, 네 언어·형식, obj/seq, KK/KD/DK/DD, R을 포함하고 해당 셀의 120·30·32회 배정은 그대로 유지한다. '
      '6,488대화·220,592턴이며, 4 pool/합계 80회/분 시험에서 관측한 66.7턴/분을 적용하면 약 55.1시간이다. '
      '처리량이 여기서 20% 더 낮아진다고 가정하면 약 68.9시간으로 3일 안의 계획 범위에 든다. '
      '다른 모델 및 low/high는 후속 단계로 남으므로 원래 전체 설계 완료를 뜻하지 않는다.', '',
      'B는 모델별 계산 모델과 전이 곡선의 폭을 우선한다. 8모델×3effort×2frame×obj/seq를 유지하고 영어/schema에서 각 80회만 먼저 수집한다. '
      '7,680대화·261,120턴이며 83.7턴/분에서 약 52.0시간, 처리량이 20% 낮아지면 약 65.0시간이다. '
      '다른 모델·high effort에서 그 속도는 아직 검증되지 않았다. 다른 형식, 고정규칙 대조, R 대조는 후속 단계가 된다. '
      '각 셀 120→80으로 줄어 사건 수와 전이 곡선의 정밀도가 낮아지고, 희귀 사건 profile에서는 여전히 추정이 어려울 수 있다.', '',
      'C는 한 모델의 추론 수준 비교를 모두 유지하는 대안이지만 최고 시험 속도에서도 약 65.9시간이고 운영 손실 여유가 작다. '
      '단일 모델이 동일 합계 속도를 낼 수 있는지도 아직 검증하지 않았다.', '',
      '## 전체 설계를 그대로 유지하는 경우','',
      '실제로 613~919턴/분을 처리할 수 있는 상류 용량이 필요하다. 두 모델 시험만으로 8개 모델의 모든 한도를 확정한 것은 아니다. '
      '모델별 독립 할당량 확인, 제공자의 정식 한도 증설, 지원 API 경로 전환이 후보지만 그 처리량은 아직 입증되지 않았다. '
      '3일 기준 613턴/분을 지속해야 하며, 20% 운영 손실을 허용하려면 약 766턴/분 용량이 필요하다. '
      '2일은 각각 919·1,149턴/분이다. 모델 목록은 API 지원과 1.5~2배 Fast tier 설명을 제공하지만 실제 계정 할당량, 가격, SLA 또는 그런 처리량을 보장하지 않는다. '
      f'현재 두 모델의 일부 완료 시험에서 평균 입력은 약 {input_mean:,.0f}토큰/턴으로, 이를 단순 적용한 3일 목표는 분당 약 {len(rows)*34/(3*1440)*input_mean/1e6:.1f}백만 입력 토큰에 해당한다. 캐시 포함 처리와 실제 요금·한도는 별도 확인이 필요하다. '
      '유료 mode는 활성화하지 않았다. 서비스·실행 경로 변경은 새 실행 프로필과 freeze, 원본 보존 및 별도 cohort 기록이 필요하다.', '',
      '단순 VM 추가는 같은 계정의 제공자 한도를 늘리지 않는다. 후속 네 질문을 전부 생략해도 호출 감소는 약 11.8%로, 현재 최고 시험 속도에서 약 19.4일이 남는다. '
      '라운드 안의 응답은 앞선 선택·피드백에 의존하므로 34턴을 한 번에 요청하는 것은 같은 실험이 아니다. '
      '비동기 Batch도 그 의존성을 없애지 않으며, 24시간 완료 window를 전체 대화의 24시간 완료 보장으로 해석할 수 없다.', '',
      '## 변경 절차','',
      '선택 후 새 범위·셀별 수·분석 분할·목표와 한계를 먼저 기록하고 별도 manifest와 실행 프로필을 만든다. '
      '기존 실패·중단·전환 전 데이터는 그대로 보존하고 예비실험으로 재분류하지 않는다. '
      '기존 실패 시행을 임의로 대체하거나 관측된 응답 내용에 따라 셀을 고르지 않는다. 현재 문서는 어떠한 변경도 실행하지 않았다.', ''])
    (args.output/'PLAN.ko.md').write_text('\n'.join(lines))
    print(json.dumps({'output':str(args.output),'scenarios':result['scenarios']},ensure_ascii=False))


if __name__=='__main__':
    main()
