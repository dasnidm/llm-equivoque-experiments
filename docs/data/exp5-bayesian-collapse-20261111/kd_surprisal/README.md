# K/D 예측과 라운드별 surprisal

기존 강제 가설 모델과 별도로, **K와 D의 관측 빈도를 바탕으로 다음 피드백을 예상**하는 탐색적 모델이다. 실험 5의 대화들을 사용하며 새 LLM 호출은 없다.

[시행별로 선 하나씩 분리한 그래프](../individual_runs/README.md)

| 모델 | Low | Medium | High |
| --- | --- | --- | --- |
| gpt-5.6-luna | [Low](gpt-5.6-luna-low.png) | [Medium](gpt-5.6-luna-medium.png) | [High](gpt-5.6-luna-high.png) |
| gpt-5.6-terra | [Low](gpt-5.6-terra-low.png) | [Medium](gpt-5.6-terra-medium.png) | [High](gpt-5.6-terra-high.png) |
| gpt-5.6-sol | [Low](gpt-5.6-sol-low.png) | [Medium](gpt-5.6-sol-medium.png) | [High](gpt-5.6-sol-high.png) |
| gpt-6-luna | [Low](gpt-6-luna-low.png) | [Medium](gpt-6-luna-medium.png) | [High](gpt-6-luna-high.png) |
| gpt-6-sol | [Low](gpt-6-sol-low.png) | [Medium](gpt-6-sol-medium.png) | [High](gpt-6-sol-high.png) |
| gpt-6-astra | [Low](gpt-6-astra-low.png) | [Medium](gpt-6-astra-medium.png) | [High](gpt-6-astra-high.png) |
| gpt-6.1-sol | [Low](gpt-6.1-sol-low.png) | [Medium](gpt-6.1-sol-medium.png) | [High](gpt-6.1-sol-high.png) |

[21개 조합 PDF](all_21_configurations.pdf) · [라운드별 예측과 surprisal 데이터](kd_surprisal.csv.gz) · [기존 강제 확률 모델](../README.md)

## 계산 방법

대화마다 `Beta(1,1)`로 시작한다. 따라서 처음 K와 D의 예측 확률은 각각 50%다. 이전에 K를 `k`회, D를 `d`회 보았다면 다음 피드백의 예측은 다음과 같다.

```text
P(K | 이전 피드백) = (k + 1) / (k + d + 2)
P(D | 이전 피드백) = (d + 1) / (k + d + 2)
surprisal = -log2(실제로 나온 피드백의 예측 확률)
```

예를 들어 K가 다섯 번 연속으로 나왔다면 다음 D의 예측 확률은 1/7이다. 그때 D가 나오면 약 2.81 bits로, 확률이 1/2인 사건의 1 bit보다 놀람이 크다. 피드백마다 사전을 갱신한다.

두 선택 단계는 **하나의 시간순 흐름**으로 계산한다. 1라운드 첫 단계 → 1라운드 둘째 단계 → 2라운드 첫 단계 순서다. 따라서 첫 단계 피드백을 본 뒤 갱신한 확률을 둘째 단계에 사용한다. Y축은 **해당 라운드의 두 피드백 surprisal 합**이다. 두 단계의 평균이나 시간에 따른 누적 합이 아니다.

이 모델은 K/D의 누적 빈도를 학습한다. 1단계와 2단계를 별도 학습하지 않으며, `KDKDKD` 같은 주기나 최근 전환만을 별도로 배우지는 않는다. 매 단계 K/D가 50:50인 상태로 고정되는 모델도 아니다. 동일 피드백이 연속해서 늘어날수록 그 피드백의 예측 확률이 높아진다.

## 보는 법과 한계

- 각 패널은 obj/seq × 카드/고양이 중 하나이며 독립 대화 30개를 포함한다. 선 하나는 한 대화의 10라운드 궤적이다. 선분 색은 **끝나는 라운드의 K/D 경로**이고, 첫 라운드는 점 색이다.
- 빨간 별은 `impact=1`과 `counterfactual=no`의 첫 공동 보고 시점이다. 이후 라운드도 표시한다. 10라운드까지 보고가 없으면 별이 없다. 선과 별은 서로 겹칠 수 있다.
- Y축의 단위는 **bits**이며, 높은 값은 그 라운드 피드백이 이 모델에서 예상 밖이라는 뜻이다. 강제 확률, 실제 LLM의 확신, 응답 전환 확률, EEG 전위를 측정한 값이 아니다.
- 이 모델은 **최종 결과의 반복을 입력하지 않는다.** 따라서 이전의 강제 확률 모델과 서로 다른 질문을 다룬다. 시각적으로 별과 높은 점이 겹친다고 가설이 검증되거나 임계점이 확정되는 것은 아니다.
- 시행별 값은 압축 CSV의 `trial_id`, `round`, `route`, `p_first_observed`, `p_second_observed`, `surprisal_round_bits`, `first_event`로 확인할 수 있다. 2,520개 대화의 25,200개 라운드와 최초 전환 342건이다.

## 재생성

저장소 루트에서 `python docs/data/exp5-bayesian-collapse-20261111/generate_kd_surprisal.py`를 실행한다. 보존된 실험 5의 `choices.csv`와 `measurements.csv`만 읽으며 원본을 변경하거나 LLM을 호출하지 않는다. `numpy`, `pandas`, `matplotlib`, Noto Sans CJK 글꼴이 필요하다.
