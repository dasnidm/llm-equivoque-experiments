# 완료된 실험과 산출물

아래6개는 서로 다른 실험 단위를 갖습니다. 실험3은 단일 응답 과제이고, 나머지는 한 대화 안의 게임입니다. 초기 미보존 프로토타입과 준비용 연결 점검은 평가 결과에 합치지 않습니다. `attempt-02`가 있는 실험1은 최종 표시판을 연결하며, 최초 분석도 보존돼 있습니다.

| 순서 | Run ID | 완료 단위 | 평가 네이티브 호출 | 보존 태그 |
| --- | --- | ---: | ---: | --- |
| 1 | `equivoque-2026-10-09-v1` | 2,093/2,100대화 | 8,392 | `results/exp1-v1` |
| 2 | `equivoque-2026-10-09-exp2-v1` | 420/420대화 | 4,200 | `results/exp2-v1` |
| 3 | `equivoque-2026-10-11-exp3-pilot-v1` | 2,016/2,016과제 | 2,016 | `results/exp3-pilot-v1` |
| 4 | `equivoque-2026-10-12-sequence-pilot-v1` | 28/28대화 | 2,604 | `results/sequence-pilot-v1` |
| 5 | `equivoque-2026-10-12-sequence-replication-v1` | 2,520/2,520대화 | 83,160 | `results/sequence-replication-v1` |
| 6 | `equivoque-2026-10-13-question-effect-v1` | 180/180대화 | 5,940 | `results/question-effect-v1` |

호출 수는 평가 기록의 네이티브 실행 단위입니다. 별도 보정·개발·교체 전 제외 시도와 내부 HTTP 재연결을 합친 청구량이 아닙니다. 실패·제외 정책은 실행마다 다르며 [현재 상태](STATUS.md)와 원본 보고서를 함께 읽습니다.

<a id="exp1"></a>
## 1. 최초 단일 라운드 실험

7모델 ×3추론 ×2프레임 ×50공유 케이스로2,100대화를 배정했습니다. 목표를 남기는 한 게임 후 자기평가를 받고, 실제 규칙과 전체 경로 증거를 공개한 뒤 다시 평가했습니다.

공개 전 유효 영향력2,096개 중2,092개가100이었습니다. 공개 후 유효2,093개 모두 영향력1·반사실No였습니다. 경로별 차이는 거의 변화가 없는 상단 경계 응답 때문에 해석이 제한됩니다. 경로는 모델의 선택에서 생기므로 그 차이는 무작위 인과 효과가 아닙니다. 7개 미완료 안의 유효 부분 관측도 해당 분모에 남아 있습니다.

[보고서](../analysis/results/equivoque-2026-10-09-v1/attempt-02/REPORT.md) · [분석 ZIP](../analysis/results/equivoque-2026-10-09-v1/equivoque-analysis.zip) · [표](../analysis/results/equivoque-2026-10-09-v1/attempt-02/tables/) · [원본](../results/equivoque-2026-10-09-v1/) · [감사](../analysis/results/equivoque-2026-10-09-v1/attempt-02/union_audit.json)

<a id="exp2"></a>
## 2. 3라운드 반복

21모델·추론 조합 ×2프레임 ×10케이스 =420대화입니다. 목표는 동일하게 유지하고 라운드별 배치를 바꿨습니다. 세 라운드를 모두 진행한 뒤 규칙을 공개했습니다.

영향력 평균은100→96.229→82.793이었고, 반사실No는0→16→72개였습니다. 공개 후420개 모두1·No였습니다. 추가 경험·반복 자기평가·대화 길이가 함께 바뀌므로 반복 횟수만의 인과 효과를 분리한 설계는 아닙니다.

[보고서](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/REPORT.md) · [분석 ZIP](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01-analysis.zip) · [표](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/tables/) · [원본](../results/equivoque-2026-10-09-exp2-v1/) · [감사](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/union_audit.json)

<a id="exp3"></a>
## 3. 객관적 규칙 적용 파일럿

21조합 ×2프레임 ×2절차 ×3진행자 주장 ×8케이스 =2,016개 단일 응답 과제입니다. 규칙·전체 표·진행자 의견을 제공하고 조회와 전이를 물었습니다. 목표를 강제하는 절차와 선택을 남기는 절차를 모두 포함했습니다.

전이 문항2–4의 평균 정확도는98.446%였습니다. 진행자 상충−중립 주장 대비는+0.050%포인트였습니다. 높은 정확도는 제공된 규칙을 적용하는 능력의 결과이며, 숨겨진 규칙을 스스로 발견했다는 결과가 아닙니다. 정확도가 상단에 몰려 진행자 의견의 작은 효과를 구분하기 어려울 수 있습니다.

[보고서](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01/REPORT.md) · [분석 ZIP](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01-analysis.zip) · [표](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01/tables/) · [원본](../results/equivoque-2026-10-11-exp3-pilot-v1/) · [감사](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01/union_audit.json)

<a id="sequence-pilot"></a>
## 4. 30라운드 시퀀스 파일럿

7모델의low 추론 ×2프레임 ×고정/시퀀스 =28대화, 총840게임 라운드입니다. 코드 폴더 `experiment7/`은 이 실행의 역사적 이름이며, 별도의 일곱 번째 완료 실험으로 이중 계산하지 않습니다.

30라운드 종료 시 고정5/14개, 시퀀스0/14개가1·No였습니다. 고정 조건의 영향력1은3–7라운드에 처음 나타나 이후 유지됐습니다. 모든 자유 점수는100이었고 공개 후28개 모두1·No였습니다. 한 셀당 한 대화·공유 시퀀스 한 개이므로 모델 순위나 일반적 발견 시간을 추정하지 않습니다.

[보고서](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/attempt-01/REPORT.md) · [분석 ZIP](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/sequence-pilot-analysis.zip) · [표](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/attempt-01/tables/) · [압축 원본](../results/equivoque-2026-10-12-sequence-pilot-v1/raw-archives/) · [원본만으로 재현한 검증](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/archive-reproduction.json)

<a id="sequence-replication"></a>
## 5. 10라운드 대규모 반복

7모델 ×3추론 ×2프레임 ×2조건 =84조합, 조합당30대화로2,520대화·25,200게임 라운드입니다. 대화 내 배치는 고정하고30공유 케이스 가족을 사용했습니다. 설명 질문·예측 질문은 모두10라운드 자기평가 이후, 규칙 공개 전에 나왔습니다.

10라운드의1·No는 고정319/1,260개(25.3%), 시퀀스1/1,260개(0.08%)였습니다. 고정 조건에서 이른 전환 후284/300개(94.7%)가 이후 모든 라운드에 걸쳐 유지됐습니다. 카드·고양이 차이는 모델별로 달랐습니다. 예측12/12일치는 고정540/1,260개, 시퀀스97/1,260개였습니다. 나머지를 모두 오답으로 묶지 않습니다.

[보고서](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/REPORT.md) · [분석 ZIP](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/sequence-replication-analysis.zip) · [표](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables/) · [압축 원본](../results/equivoque-2026-10-12-sequence-replication-v1/raw-archives/) · [감사](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/union_audit.json)

<a id="question-effect"></a>
## 6. 질문 효과180시행

gpt-5.6-sol·gpt-6.1-sol의high 추론, 카드·시퀀스만 사용했습니다. 두 모델 ×대조/설명/예측 ×30공유 케이스 =180개의 새 대화입니다. 라운드10 뒤 질문 하나를 준 다음 규칙 공개 전 자기평가를 반복했습니다.

질문 전180개 모두100·Yes였습니다. gpt-5.6-sol은 대조0/30, 설명20/30, 예측3/30개가1·No로 바뀌었습니다. gpt-6.1-sol은 공동 지표 전환은 없었지만 예측 조건30개 모두 영향력100→50이었습니다. 설명이 이후 자기평가를 바꿀 수 있으나, 질문 전부터 알았는지 또는 질문이 새 추론을 촉발했는지까지 분리하지는 못합니다.

[읽기용 요약](RESULTS.md#question-effects) · [분석 ZIP](../analysis/results/equivoque-2026-10-13-question-effect-v1/question-effect-analysis.zip) · [HTML 보고서 소스](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/REPORT.html) · [표](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/tables/) · [압축 원본](../results/equivoque-2026-10-13-question-effect-v1/raw-archives/) · [재현 검증](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/reproduction.json)

GitHub는 저장소의HTML을 웹 보고서처럼 실행하지 않습니다. 읽기용 문서는 위 요약을 사용하고, 그림이 포함된HTML은 ZIP을 내려받아 압축을 푼 후 브라우저로 여세요.
