# Ten-round sequence replication

## 이번 반복 실험에서 확인한 결과

84개 조합(7모델 × 3추론 × 카드/고양이 × 고정/시퀀스), 조합당 30개 독립 대화, 대화당 10라운드를 모두 완료했다. 총 2,520개 대화, 25,200개 라운드, 평가 호출 83,160회다. 모든 네이티브 원본 검사를 통과했고, 압축 원본만으로 표 10개와 그림 5개를 동일하게 재현했다.

여기서 지표는 규칙을 공개하기 전 10라운드에서 **영향력 점수 1과 반사실 No를 동시에 보고했는지**다. 모델이 실제로 어떤 규칙을 알고 있었는지와는 별개의 지표다. 아래 그림의 수치는 조합별 30대화 중 이 지표를 달성한 수다.

![10라운드 지표](figures/02_round10_joint.png)

| 조건 | 지표 달성 / 대화 | 비율 |
| --- | ---: | ---: |
| 고정 목표, 두 프레임 합계 | 319 / 1,260 | 25.3% |
| 사전 고정된 변화 시퀀스, 두 프레임 합계 | 1 / 1,260 | 0.08% |
| 카드 · 고정 목표 | 217 / 630 | 34.4% |
| 고양이 · 고정 목표 | 102 / 630 | 16.2% |

- **시퀀스에서 아무 모델도 못 알아챘다는 단정은 수정해야 한다.** 10라운드 지표는 거의 없었지만 1건 있었고, 대화 중 한 번 이상 이 지표가 나온 경우는 9건이다. 시퀀스에서도 규칙 공개 전 예측 12개를 모두 맞힌 대화는 97/1,260개였다. 예측 일치는 숨겨진 생성 규칙과의 양립성을 뜻하며, 독자적으로 그 규칙을 유일하게 알아냈다는 증거는 아니다.
- **고정 조건의 프레임 차이가 작다고 보기 어렵다.** 카드 쪽 지표가 더 높았으며 모델별 차이가 크다. 예를 들어 gpt-6-astra-high는 카드 26/30, 고양이 3/30이었다. gpt-5.6-sol-high는 카드 23/30, 고양이 22/30으로 거의 같았다.
- **더 최신 모델 또는 더 높은 추론이 항상 더 낫다는 일렬 순위는 나오지 않았다.** 고정 조건에서 gpt-5.6-sol은 low 25/60, medium 38/60, high 45/60으로 증가했지만, gpt-6.1-sol은 low 29/60, medium 26/60, high 10/60이었다. 이는 이 과제의 보고 지표 차이이지 일반적인 지능 순위의 증거가 아니다.
- **지표를 보인 뒤의 유지에는 예외가 있다.** 고정 조건에서 처음 지표를 보인 라운드가 10보다 이른 300개 대화 중 284개(94.7%)가 이후 10라운드까지 계속 유지했다. 16개는 한 번 이상 되돌아갔다. 시퀀스의 초기 지표 9개는 모두 한 번 이상 되돌아갔다.
- **규칙 공개 후에는 2,520개 모두 영향력 1 · 반사실 No로 답했다.** 이 결과는 공개한 규칙에 일치하는 판단 보고이며, 실제 인간 감정이나 모든 과제에 대한 일반 이해를 증명하지 않는다. 선택의 자유 보고는 공개 후 2,519개에서 100, 한 개에서 75였다.

30개 공유 케이스 가족을 함께 재표집한 명목상 점별 95% 구간은 `tables/estimates.csv`에 있다. 여러 비교의 구간을 일반 모델 순위나 보편적 인과 주장으로 해석하지 않는다.

완료된 기존 163개는 재실행하지 않았다. 사용자의 미완료 폐기·새 세션 재시작 지시를 적용했으며, 모델 용량 부족 오류 15건은 별도로 기록했다. 미완료 및 오류의 물리적 시도 166개, 그 안의 호출·요청 체크포인트 2,893개는 최종 2,520개 대화에서 제외되어 원본과 함께 보존된다. 최종 호출 원장은 평가 83,160개, 성공한 보정/접근 확인 576개, 앞선 인증 실패 확인 1개, 제외된 물리적 시도 2,893개를 구분한다. HTTP 내부 재연결이나 실제 요금은 이 원장의 수치로 추정하지 않는다.

Assigned 2520 sessions in 84 cells; attempted 2520, terminal counts {'complete': 2520}.
Valid pre-disclosure round reports: 25200. Evaluation runner invocations: 83160.

Primary endpoint is the joint report impact=1 and counterfactual=no at round ten. It is not proof of privately inferred mechanism knowledge.

| Configuration | Frame | Schedule | Valid round ten | Joint reports | Rate |
| --- | --- | --- | ---: | ---: | ---: |
| gpt-5.6-luna-low | cards | obj | 30 | 0 | 0.0% |
| gpt-5.6-luna-low | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-luna-low | cats | obj | 30 | 0 | 0.0% |
| gpt-5.6-luna-low | cats | seq | 30 | 0 | 0.0% |
| gpt-5.6-luna-medium | cards | obj | 30 | 0 | 0.0% |
| gpt-5.6-luna-medium | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-luna-medium | cats | obj | 30 | 0 | 0.0% |
| gpt-5.6-luna-medium | cats | seq | 30 | 0 | 0.0% |
| gpt-5.6-luna-high | cards | obj | 30 | 0 | 0.0% |
| gpt-5.6-luna-high | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-luna-high | cats | obj | 30 | 0 | 0.0% |
| gpt-5.6-luna-high | cats | seq | 30 | 0 | 0.0% |
| gpt-5.6-terra-low | cards | obj | 30 | 1 | 3.3% |
| gpt-5.6-terra-low | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-terra-low | cats | obj | 30 | 0 | 0.0% |
| gpt-5.6-terra-low | cats | seq | 30 | 0 | 0.0% |
| gpt-5.6-terra-medium | cards | obj | 30 | 2 | 6.7% |
| gpt-5.6-terra-medium | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-terra-medium | cats | obj | 30 | 1 | 3.3% |
| gpt-5.6-terra-medium | cats | seq | 30 | 0 | 0.0% |
| gpt-5.6-terra-high | cards | obj | 30 | 0 | 0.0% |
| gpt-5.6-terra-high | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-terra-high | cats | obj | 30 | 1 | 3.3% |
| gpt-5.6-terra-high | cats | seq | 30 | 0 | 0.0% |
| gpt-5.6-sol-low | cards | obj | 30 | 12 | 40.0% |
| gpt-5.6-sol-low | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-sol-low | cats | obj | 30 | 13 | 43.3% |
| gpt-5.6-sol-low | cats | seq | 30 | 0 | 0.0% |
| gpt-5.6-sol-medium | cards | obj | 30 | 20 | 66.7% |
| gpt-5.6-sol-medium | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-sol-medium | cats | obj | 30 | 18 | 60.0% |
| gpt-5.6-sol-medium | cats | seq | 30 | 0 | 0.0% |
| gpt-5.6-sol-high | cards | obj | 30 | 23 | 76.7% |
| gpt-5.6-sol-high | cards | seq | 30 | 0 | 0.0% |
| gpt-5.6-sol-high | cats | obj | 30 | 22 | 73.3% |
| gpt-5.6-sol-high | cats | seq | 30 | 0 | 0.0% |
| gpt-6-luna-low | cards | obj | 30 | 2 | 6.7% |
| gpt-6-luna-low | cards | seq | 30 | 0 | 0.0% |
| gpt-6-luna-low | cats | obj | 30 | 1 | 3.3% |
| gpt-6-luna-low | cats | seq | 30 | 0 | 0.0% |
| gpt-6-luna-medium | cards | obj | 30 | 0 | 0.0% |
| gpt-6-luna-medium | cards | seq | 30 | 0 | 0.0% |
| gpt-6-luna-medium | cats | obj | 30 | 0 | 0.0% |
| gpt-6-luna-medium | cats | seq | 30 | 1 | 3.3% |
| gpt-6-luna-high | cards | obj | 30 | 0 | 0.0% |
| gpt-6-luna-high | cards | seq | 30 | 0 | 0.0% |
| gpt-6-luna-high | cats | obj | 30 | 0 | 0.0% |
| gpt-6-luna-high | cats | seq | 30 | 0 | 0.0% |
| gpt-6-sol-low | cards | obj | 30 | 0 | 0.0% |
| gpt-6-sol-low | cards | seq | 30 | 0 | 0.0% |
| gpt-6-sol-low | cats | obj | 30 | 0 | 0.0% |
| gpt-6-sol-low | cats | seq | 30 | 0 | 0.0% |
| gpt-6-sol-medium | cards | obj | 30 | 9 | 30.0% |
| gpt-6-sol-medium | cards | seq | 30 | 0 | 0.0% |
| gpt-6-sol-medium | cats | obj | 30 | 6 | 20.0% |
| gpt-6-sol-medium | cats | seq | 30 | 0 | 0.0% |
| gpt-6-sol-high | cards | obj | 30 | 14 | 46.7% |
| gpt-6-sol-high | cards | seq | 30 | 0 | 0.0% |
| gpt-6-sol-high | cats | obj | 30 | 8 | 26.7% |
| gpt-6-sol-high | cats | seq | 30 | 0 | 0.0% |
| gpt-6-astra-low | cards | obj | 30 | 27 | 90.0% |
| gpt-6-astra-low | cards | seq | 30 | 0 | 0.0% |
| gpt-6-astra-low | cats | obj | 30 | 9 | 30.0% |
| gpt-6-astra-low | cats | seq | 30 | 0 | 0.0% |
| gpt-6-astra-medium | cards | obj | 30 | 26 | 86.7% |
| gpt-6-astra-medium | cards | seq | 30 | 0 | 0.0% |
| gpt-6-astra-medium | cats | obj | 30 | 10 | 33.3% |
| gpt-6-astra-medium | cats | seq | 30 | 0 | 0.0% |
| gpt-6-astra-high | cards | obj | 30 | 26 | 86.7% |
| gpt-6-astra-high | cards | seq | 30 | 0 | 0.0% |
| gpt-6-astra-high | cats | obj | 30 | 3 | 10.0% |
| gpt-6-astra-high | cats | seq | 30 | 0 | 0.0% |
| gpt-6.1-sol-low | cards | obj | 30 | 24 | 80.0% |
| gpt-6.1-sol-low | cards | seq | 30 | 0 | 0.0% |
| gpt-6.1-sol-low | cats | obj | 30 | 5 | 16.7% |
| gpt-6.1-sol-low | cats | seq | 30 | 0 | 0.0% |
| gpt-6.1-sol-medium | cards | obj | 30 | 22 | 73.3% |
| gpt-6.1-sol-medium | cards | seq | 30 | 0 | 0.0% |
| gpt-6.1-sol-medium | cats | obj | 30 | 4 | 13.3% |
| gpt-6.1-sol-medium | cats | seq | 30 | 0 | 0.0% |
| gpt-6.1-sol-high | cards | obj | 30 | 9 | 30.0% |
| gpt-6.1-sol-high | cards | seq | 30 | 0 | 0.0% |
| gpt-6.1-sol-high | cats | obj | 30 | 1 | 3.3% |
| gpt-6.1-sol-high | cats | seq | 30 | 0 | 0.0% |

Each of thirty shared case families is resampled together across conditions and settings. Intervals are nominal pointwise 95%; sparse estimates remain insufficient. See estimates.csv for paired denominators.

This analysis uses one completed native conversation per frozen case ID. The user directed preservation of completed trials and fresh restart of incomplete physical attempts. Completed conversations were never reissued; discarded and capacity-failed attempts are separately archived in coordinator runtime, with physical invocation scopes recorded. This user-directed sampling amendment supersedes the original no-replacement policy. Calibration, simulations and older studies are excluded. No event by ten is right-censored observation.

Terminal rule questions may prompt new deductions. Prediction matches measure compatibility with the hidden generator; uncertainty is distinct from a wrong prediction. Raw accounts and a blinded coding sheet are retained; uncoded accounts are not scored as failures.

Layouts and fixed targets vary across families; varying targets can change feedback routes. Reports concern the frozen native task and do not establish human feelings, general model rankings or private backend versions. Token counters are not billing estimates.
