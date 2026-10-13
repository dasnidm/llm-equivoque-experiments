"""Create a portable Korean HTML report from audited exported tables."""
import json,csv,html,hashlib,zipfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

def table(rows,fields,labels=None):
    labels=labels or fields
    esc=lambda x:html.escape(str(x))
    return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in labels)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(r[f])+'</td>' for f in fields)+'</tr>' for r in rows)+'</tbody></table>'

def main():
    root=Path(__file__).resolve().parents[1];run='equivoque-2026-10-13-question-effect-v1'
    out=root/'analysis/results'/run/'attempt-01';a=json.loads((out/'results.json').read_text());audit=json.loads((out/'audit.json').read_text())
    load=lambda n:list(csv.DictReader((out/'tables'/(n+'.csv')).open()))
    old=load('existing_prediction_by_model');summaries=a['summary'];effects=[r for r in a['effects'] if r['endpoint']=='joint_report_change']
    for r in effects:
        r['effect_pp']=f"{100*r['estimate']:.1f}";r['interval_pp']=f"[{100*r['ci_low']:.1f}, {100*r['ci_high']:.1f}]"
    body='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>질문 효과 실험 결과</title><style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;line-height:1.75;color:#25323d}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #dce2e8;padding:8px;text-align:left}th{background:#eef3f6}img{width:100%;height:auto;margin:16px 0}.note{background:#f0f5f6;padding:16px}code{font-size:.9em}h1,h2{line-height:1.3}</style><h1>기존 시퀀스 답변 분석과 질문 효과 180시행</h1>'''
    body+=f'<p>완료: <b>{audit["complete"]}/180시행</b>. 2모델 × 3질문 조건 × 30시행. 카드·시퀀스, high 추론, 시행당 10라운드. 독립 네이티브 대화 180개, 게임 라운드 1,800개, 평가 호출 5,940개. 실제 규칙은 모든 조건의 재평가 이후에 공개했다. 원본 검증: 통과.</p>'
    body+='<h2>기존 결과: 불확실성과 오답을 구별해야 한다</h2><p>기존 시퀀스 1,260시행의 예측 15,120항목을 실제 생성 절차와 일치, 확정적 불일치, uncertain으로 구분했다. 모델당 180시행·2,160항목이다. 일치는 숨겨진 생성 절차와 답변이 양립함을 뜻하며, 관찰만으로 그 절차를 유일하게 알아냈다는 증거는 아니다.</p>'
    body+=table(old,['model','perfect_12','match','mismatch','uncertain','all_12_uncertain'],['모델','12/12 일치 시행','일치 항목','확정적 불일치','판단 유보 항목','12항목 모두 유보한 시행'])
    body+='<img src="figures/01_existing_prediction_components.png" alt="기존 예측 항목 분류"><p>특히 gpt-6.1-sol은 324항목 일치, 1,836항목 판단 유보, 확정적 불일치 0항목이었다. 완전 일치 0시행을 전부 오답이나 이해 실패로 해석하면 안 된다. 관찰만으로 결정되지 않는다고 답하는 신중함과 과제 적용 능력이 이 점수에 함께 반영된다.</p>'
    body+='<h2>기존 97개 설명 답변의 수동 검토</h2><p>12항목 모두 일치한 97개 답변을 모델·추론·시행 식별자를 가린 무작위 순서로 단일 코디네이터가 읽었다. 집계 결과를 이미 알고 있고 정답으로 하위집합을 선택했으므로 독립적인 맹검 검증은 아니다. 목표를 보존하도록 선택한 쪽 또는 반대쪽을 남긴다는 연결이 명시된 답변은 40개(모두 gpt-5.6-sol), 그 연결을 명시하지 않은 답변은 57개였다. 가능성으로 제안한 경우도 포함하며, 확정적인 규칙 지식의 수가 아니다. 97개 모두 직전 자기평가는 영향력100·반사실Yes였다.</p><img src="figures/02_existing_97_accounts.png" alt="97개 서술 평가"><p>전체 1,260개 설명은 원문과 목표·불확실성 표현에 대한 재현 가능한 단어 검색을 제공한다. 단어 검색을 의미 판정으로 취급하지 않는다. 97개에 대한 판정 기준과 모든 원문은 existing-analysis-method.json 및 표에 보존했다.</p>'
    screen=json.loads((out/'existing-analysis-method.json').read_text())['additional_screen']
    body+='<p>추가로 전체 설명에서 목표·사전 결정·유도 표현이 검색된 133개를 모두 수동 검토했다. 같은 기준으로 목표를 보존하는 처리 방식을 제안한 답변은 '+str(screen['mapping_accounts'])+'개였으며 모델별로 '+html.escape(str(screen['mapping_by_model']))+'였다. 이 수에는 앞의 40개가 포함된다. 검색되지 않은 답변은 모델당 첫5개, 총35개를 점검했으며 전체를 수동 판정하지는 않았다. 따라서 이 수는 검색·검토에서 확인된 답변 수이며, 전체 규칙 지식의 유병률 추정이 아니다. gpt-6-astra와 gpt-6.1-sol은 가능한 유도 규칙을 제안하면서도 예측을 유보한 사례가 있다.</p>'
    body+='<h2>새 실험: 질문 하나의 효과를 분리</h2><p>모든 조건은 동일한 30케이스의 배치·목표 시퀀스를 공유하되 각 시행은 새 대화다. 모델과 조건 전체의 시작 순서를 고정 시드로 섞었다. 10라운드 직후 대조 조건은 조용한 풍경 묘사, 설명 조건은 기존 절차 설명 질문, 예측 조건은 기존 네 대안 경로 예측 질문을 한 번 받았다. 그 다음 모든 조건에서 동일한 영향력·반사실·선택 자유 질문을 다시 받았다. 예측 조건에 설명 질문을 앞서 주지 않았고, 설명 조건에는 예측 문제를 덧붙이지 않았다.</p><p>주요 지표는 영향력1·반사실No의 공동 응답이다. 주 분석은 각 조건의 질문 전후 변화에서 대조 조건의 변화를 뺀 케이스 대응 비교다. 단순히 질문 후 비율만 비교하는 것과 구별된다.</p>'
    body+=table(summaries,['model','arm','n','pre_joint','post_joint','new_joint','lost_joint','pre_impact_mean','post_impact_mean','perfect_predictions'],['모델','조건','시행','질문 전 공동 응답','질문 후 공동 응답','새로 전환','되돌아감','전 영향력 평균','후 영향력 평균','예측12/12 일치'])
    body+='<div class="note"><p><b>가장 큰 변화는 gpt-5.6-sol의 설명 질문에서 나타났다.</b> 규칙 공개 없이 설명 질문 하나를 받은 뒤 20/30개가 영향력1·반사실No로 전환했다. 대조 조건은0/30, 예측 조건은3/30이었다. 설명 질문의 대조 대비 변화는 +66.7%p, 명목상 점별95% 대응 구간은 [+46.7,+83.3]%p다. 예측 조건은 +10.0%p이고 구간[0,+23.3]%p이므로 표본에서의3건을 설명 질문만큼 확실한 효과로 취급하지 않는다.</p><p><b>gpt-6.1-sol의 공동 응답0건은 변화가 없었다는 뜻이 아니다.</b> 예측 조건30개 모두 영향력100에서50으로 낮아졌지만 반사실은 모두Yes로 유지됐다. 설명 조건에서는5개가50,25개가100이었다. 공동 응답 기준은 이런 중간 판단 변화를 놓친다. 점수50이 불확실성을 뜻한다는 해석은 가능하지만, 점수 이유를 따로 질문하지 않아 확정할 수 없다.</p><p>예측 조건에서 gpt-5.6-sol은12/12 일치3개, gpt-6.1-sol은0개였다. gpt-5.6-sol의3개는 모두 직후 영향력1·No로 전환했다. 기존 설명→예측 순서의 gpt-5.6-sol-high·카드·시퀀스는19/30개 완전 일치였지만, 이번 예측 단독 조건은3/30개다. 이 비교는 다른 시점의 코호트 간 비교이므로 설명 질문이 예측 정답률을 올린 인과 효과를 직접 추정한 것은 아니다. 이번에 직접 분리한 효과는 질문 후 자기평가 변화다.</p><p>따라서 이번 결과는 이 조건의gpt-5.6-sol에서 절차를 설명하게 하는 질문이 영향력 판단 수정을 크게 촉발했음을 지지한다. 질문 전부터 알고 있었는지, 질문을 받고 새로 추론했는지, 질문 구조에 맞춰 답변 방식을 바꿨는지까지는 구별하지 못한다. 실제 규칙 공개 뒤 공동 응답은180/180개였다.</p></div>'
    body+='<img src="figures/03_intervention_joint_reports.png" alt="질문 전후 공동 응답"><h2>대조 조건과 비교한 변화</h2>'
    body+='<img src="figures/06_intervention_impact_ratings.png" alt="공동 지표에 가려진 영향력 점수 변화">'
    body+=table(effects,['model','treatment','effect_pp','interval_pp'],['모델','질문 조건','대조 대비 변화 차이(%p)','명목상 점별95% 구간(%p)'])
    body+='<img src="figures/04_intervention_effects.png" alt="질문 효과 대응 비교"><p>동일한 30케이스 가족을 함께 재표집한 2,000회 백분위 부트스트랩 구간이다. 여러 비교에 대한 동시 보장을 하지 않는다. 모든 관측 변화가 같으면 부트스트랩 구간은 한 점으로 퇴화할 수 있으며, 이는 모집단 효과가 확실히 그 값이라는 뜻이 아니다. 조건별 질문 후 비율의 Wilson95% 구간도 요약 표 CSV에 별도로 제공했다. 0/30의 Wilson 상한은 약11.4%이므로 0건은 발생 가능성이 0임을 증명하지 않는다.</p><img src="figures/05_predictions_and_rerating.png" alt="예측 일치와 즉시 자기평가"><p>마지막 그림은 설명 질문을 먼저 받지 않은 예측 조건에서, 생성 절차와 일치한 예측 항목 수와 직후 공동 자기평가 응답을 연결한다. 점 안의 숫자는 시행 수다.</p>'
    body+='<h2>해석의 범위</h2><p>질문 효과는 이 카드·시퀀스·high 조건과 두 모델에 한정한다. 설명 질문과 예측 질문은 응답 길이·인지 부하가 같지 않으며, 예측 질문은 네 대안 경로를 명시적으로 제시한다. 따라서 차이가 있다면 질문 내용·구조를 포함한 전체 개입의 효과이지, 특정 단어 하나의 효과로 해석하지 않는다. 자기평가와 예측의 불일치는 내부 신념이나 의식 상태에 대한 직접 증거가 아니다. 규칙 공개 후 응답은 별도의 확인값이며 주요 지표에 섞지 않는다.</p>'
    body+='<p>서버 용량 부족으로 제외·보존한 물리적 시도: '+str(audit['excluded_attempts'])+'개. 호출 기록은 평가·준비 점검·제외 시도로 분리했다: '+html.escape(str(audit['physical_invocation_scopes']))+'. 해당 시도만 코디네이터 검토 후 같은 케이스의 새 대화로 시작했고 완료 시행은 다시 호출하지 않았다. 호출 원장은 네이티브 실행 횟수이며 내부 HTTP 재연결 횟수나 청구량을 뜻하지 않는다.</p>'
    local_time=lambda value:datetime.fromisoformat(value).astimezone(ZoneInfo('Europe/Berlin')).strftime('%Y-%m-%d %H:%M:%S %Z')
    body+='<p>최초 평가 요청: '+html.escape(local_time(audit['first_requested_at']))+'; 최종 응답: '+html.escape(local_time(audit['last_received_at']))+'. 상세 케이스·문항·원본 해시·호출 기록은 동봉 표와 audit.json에 있다. 준비용 연결 점검 12호출은 평가 5,940호출에서 제외했다.</p></html>'
    (out/'REPORT.html').write_text(body)
    # Hash all analysis artifacts; the manifest does not hash itself.
    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='artifact-manifest.json'}
    (out/'artifact-manifest.json').write_text(json.dumps({'run_id':run,'files':files},indent=2)+'\n')
    package=out.parent/'question-effect-analysis.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():z.write(p,'attempt-01/'+str(p.relative_to(out)))
    print(json.dumps({'report':str(out/'REPORT.html'),'package_bytes':package.stat().st_size,'artifacts':len(files)}))

if __name__=='__main__':main()
