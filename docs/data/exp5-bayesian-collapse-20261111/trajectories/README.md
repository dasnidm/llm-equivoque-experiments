# 대화별 K/D 경로와 강제 확률 변화

실험 5의 **각 대화를 10라운드 동안 따라간 탐색적 그래프**다. 모델과 추론 수준을 고르면 obj/seq × 카드/고양이의 네 패널이 나온다.

| 모델 | Low | Medium | High |
| --- | --- | --- | --- |
| gpt-5.6-luna | [Low](gpt-5.6-luna-low.png) | [Medium](gpt-5.6-luna-medium.png) | [High](gpt-5.6-luna-high.png) |
| gpt-5.6-terra | [Low](gpt-5.6-terra-low.png) | [Medium](gpt-5.6-terra-medium.png) | [High](gpt-5.6-terra-high.png) |
| gpt-5.6-sol | [Low](gpt-5.6-sol-low.png) | [Medium](gpt-5.6-sol-medium.png) | [High](gpt-5.6-sol-high.png) |
| gpt-6-luna | [Low](gpt-6-luna-low.png) | [Medium](gpt-6-luna-medium.png) | [High](gpt-6-luna-high.png) |
| gpt-6-sol | [Low](gpt-6-sol-low.png) | [Medium](gpt-6-sol-medium.png) | [High](gpt-6-sol-high.png) |
| gpt-6-astra | [Low](gpt-6-astra-low.png) | [Medium](gpt-6-astra-medium.png) | [High](gpt-6-astra-high.png) |
| gpt-6.1-sol | [Low](gpt-6.1-sol-low.png) | [Medium](gpt-6.1-sol-medium.png) | [High](gpt-6.1-sol-high.png) |

[21개 조합 전체 PDF](all_21_configurations.pdf) · [라운드별 데이터 CSV.gz](trajectories.csv.gz) · [모델 설명과 이전 산점도](../README.md)

## 보는 법

- 각 패널에는 **독립 대화 30개**가 있다. 한 선은 한 대화의 1~10라운드 확률을 연결한다. 전환 후에도 10라운드까지 계속 표시한다.
- X축은 라운드, Y축은 매 라운드의 선택·K/D 피드백과 결과를 본 다음 계산한 **강제 가설 사후확률**이다. LLM의 실제 내적 확신을 측정한 값이나 전환 자체의 확률은 아니다.
- 선분의 색은 **그 선분이 끝나는 라운드의 K/D**를 나타낸다. 예를 들어 2→3 구간이 `KD` 색이면 3라운드의 첫 단계가 K이고 두 번째 단계가 D다. 1라운드는 작은 점의 색으로 표시한다.
- 빨간 별은 대화에서 처음 `impact=1`과 `counterfactual=no`가 동시에 보고된 라운드다. 별이 없으면 그 공동 보고가 10라운드까지 관찰되지 않았다는 뜻이다.
- 같은 궤적과 별은 서로 겹칠 수 있어, 보이는 선·별 개수와 실제 대화 수가 다를 수 있다. 그래프 제목의 대화 수와 전환 건수를 함께 보거나 CSV.gz에서 각 `trial_id`의 `round`, `route`, `p_forced`, `first_event`를 확인한다.

그래프는 2,520개 대화, 25,200개 라운드, 최초 전환 342건을 포함한다. 두 강제 가설의 사전확률과 우도는 [임시 모델 설명](../README.md)을 따른다. 강제 확률이 높아지는 현상이나 별이 모인 위치만으로 임계값·LLM 내부 추론·인간의 주관적 SoA를 입증할 수 없다.

## 재생성

저장소 루트에서 먼저 `python docs/data/exp5-bayesian-collapse-20261111/bayesian_prototype.py`를 실행하고, 이어서 `python docs/data/exp5-bayesian-collapse-20261111/generate_trajectories.py`를 실행한다. 새 LLM 호출은 없다. 원본 실험 기록은 수정하지 않는다.
