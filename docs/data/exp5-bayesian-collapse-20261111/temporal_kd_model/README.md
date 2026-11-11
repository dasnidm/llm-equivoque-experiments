# 하나의 시간순 K/D 흐름을 학습하는 베이지안 모델

실험 5의 각 대화에서 라운드별 K/D를 **끊지 않고 한 줄로 연결**해 다음 피드백을 예측한다. 예를 들어 `KK | DD | DD`는 `KKDDDD`이며, K→D 전환이 한 번이다. 이것은 기존 자료에 적용한 탐색적 모델이며 새 LLM 호출은 없다.

| 모델 | Low | Medium | High |
| --- | --- | --- | --- |
| gpt-5.6-luna | [카드](gpt-5.6-luna-low-cards.png) · [고양이](gpt-5.6-luna-low-cats.png) | [카드](gpt-5.6-luna-medium-cards.png) · [고양이](gpt-5.6-luna-medium-cats.png) | [카드](gpt-5.6-luna-high-cards.png) · [고양이](gpt-5.6-luna-high-cats.png) |
| gpt-5.6-terra | [카드](gpt-5.6-terra-low-cards.png) · [고양이](gpt-5.6-terra-low-cats.png) | [카드](gpt-5.6-terra-medium-cards.png) · [고양이](gpt-5.6-terra-medium-cats.png) | [카드](gpt-5.6-terra-high-cards.png) · [고양이](gpt-5.6-terra-high-cats.png) |
| gpt-5.6-sol | [카드](gpt-5.6-sol-low-cards.png) · [고양이](gpt-5.6-sol-low-cats.png) | [카드](gpt-5.6-sol-medium-cards.png) · [고양이](gpt-5.6-sol-medium-cats.png) | [카드](gpt-5.6-sol-high-cards.png) · [고양이](gpt-5.6-sol-high-cats.png) |
| gpt-6-luna | [카드](gpt-6-luna-low-cards.png) · [고양이](gpt-6-luna-low-cats.png) | [카드](gpt-6-luna-medium-cards.png) · [고양이](gpt-6-luna-medium-cats.png) | [카드](gpt-6-luna-high-cards.png) · [고양이](gpt-6-luna-high-cats.png) |
| gpt-6-sol | [카드](gpt-6-sol-low-cards.png) · [고양이](gpt-6-sol-low-cats.png) | [카드](gpt-6-sol-medium-cards.png) · [고양이](gpt-6-sol-medium-cats.png) | [카드](gpt-6-sol-high-cards.png) · [고양이](gpt-6-sol-high-cats.png) |
| gpt-6-astra | [카드](gpt-6-astra-low-cards.png) · [고양이](gpt-6-astra-low-cats.png) | [카드](gpt-6-astra-medium-cards.png) · [고양이](gpt-6-astra-medium-cats.png) | [카드](gpt-6-astra-high-cards.png) · [고양이](gpt-6-astra-high-cats.png) |
| gpt-6.1-sol | [카드](gpt-6.1-sol-low-cards.png) · [고양이](gpt-6.1-sol-low-cats.png) | [카드](gpt-6.1-sol-medium-cards.png) · [고양이](gpt-6.1-sol-medium-cats.png) | [카드](gpt-6.1-sol-high-cards.png) · [고양이](gpt-6.1-sol-high-cats.png) |

[42개 그래프 PDF](all_42_graphs.pdf) · [라운드별 계산값](temporal_kd_rounds.csv.gz) · [이전 전환 횟수 가설 모델](../hybrid_model/README.md)

## 모델: 전환 횟수에 대한 범주형 가설을 두지 않는다

`H0=전환 없음`, `H1=한 번`, `H2=여러 번`이라는 사전 가설은 사용하지 않는다. 대신 한 대화 안에서 직전 라벨이 K였을 때와 D였을 때를 각각 기억해, **바로 다음 라벨**을 예상한다. `N_AB`는 지금까지 A 다음에 B가 나온 횟수다. K 다음에는 다음처럼 갱신한다.

```text
P(K | 이전 K) = (N_KK + 1) / (N_KK + N_KD + 2)
P(D | 이전 K) = (N_KD + 1) / (N_KK + N_KD + 2)
```

D 다음도 동일하게 `N_DK`, `N_DD`로 계산한다. 두 행의 사전은 각각 `Beta(1,1)`이므로 어느 맥락에서도 처음에는 다음 K와 D가 50:50이다. 첫 K/D는 앵커로 삼고 그 다음부터 전환과 surprisal을 기록한다. 피드백 하나가 나올 때마다 **예측 → 실제 피드백 확인 → 해당 행 업데이트**를 수행한다. 10라운드인지, 20스텝인지 미리 알아야 할 필요는 없다.

### 예: `KK | DD | DD` = `KKDDDD`

| 시간순 라벨 | 첫 K | K | D | D | D | D |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 관측한 라벨의 예측 확률 | 1/2 | 1/2 | 1/3 | 1/2 | 2/3 | 3/4 |

첫 K는 앵커이므로 누적에서 제외한다. 인접 라벨 사이의 전환은 세 번째 라벨에서 K→D **한 번**이다. 이 여섯 라벨 다음에는 D→D가 세 번 관찰됐으므로 `P(다음 D | 현재 D)=(3+1)/(3+2)=4/5`다. K 다음 D가 자주 나오고 D 다음 K도 자주 나오면 반복적인 교대도 학습할 수 있다. 이는 매 단계가 무조건 번갈아 나올 것으로 미리 가정한다는 뜻은 아니다.

## 그래프와 변수

- 각 그래프는 모델 × 추론 수준 × 소재 한 조합의 **60개 대화**를 겹친다. 파랑은 obj, 주황은 seq이며 한 선은 한 대화의 10라운드다. 색은 K/D 종류가 아니다.
- Y축은 앵커 이후 관측 라벨의 surprisal 합 `D = sum(-log2 P(실제 라벨 | 이전 라벨과 이전 기록))`이다. 라운드마다 실제로 발생한 두 피드백을 순서대로 계산하고, 라운드가 끝난 지점에 D를 그린다. **시간순 상태는 라운드 사이에 초기화되지 않는다.**
- 빨간 별은 실제 `impact=1 AND counterfactual=no`가 처음 보고된 라운드다. `×숫자`는 소수점 여섯째 자리에서 같은 라운드·같은 D에 겹친 별의 수다. 보고 전환과 K/D 라벨의 전환은 다른 사건이다.
- 각 시행의 `route`, 두 단계 예측 `p_first/p_second`, `cumulative_switches`, 네 전환 횟수 `count_KK/KD/DK/DD`, 누적 surprisal과 실제 보고는 [CSV](temporal_kd_rounds.csv.gz)에 들어 있다. 첫 전환 라벨은 `.5`의 앵커이며 첫 surprisal은 0으로 기록한다.
- 비교용 `cumulative_violation`은 피드백이 대안보다 엄격히 덜 예상된 경우에만 `1-P(관측)`을 더한다. 이 대체 정의는 그래프의 주된 D가 아니며 별도의 경험적 비교가 필요하다.

## 한계와 구별

이 모델은 각 직전 라벨에서 다음 라벨이 나올 비율을 배운다. 라벨의 시간에 따른 단기 변화나 더 긴 맥락, 결과의 반복, 최초 선택과 끝 선택의 의미 차이를 별도 입력하지 않는다. 라운드와 선택 단계의 차이를 무시하는 것은 하나의 가정이며, 해당 차이를 반영하는 모델과 비교할 필요가 있다.

누적 surprisal에는 예상이 맞은 사건도 보통 양의 값을 더한다. 따라서 선이 계속 상승한다고 해서 심리적 손상이나 EEG 전위가 누적됐다는 뜻은 아니다. Y축은 *강제 확률*, LLM의 실제 내적 믿음, 보고 전환의 확률이 아니다. 별이 특정 구간에 모이는 것만으로 임계값이나 인과관계가 입증되지는 않는다. 결과 반복을 이 D에 독립 증거처럼 합산하지 않았고, SoA·임계값을 적합하지 않았다.

## 재생성

저장소 루트에서 `python docs/data/exp5-bayesian-collapse-20261111/generate_temporal_kd_model.py`, 다음에 `python docs/data/exp5-bayesian-collapse-20261111/generate_temporal_kd_figures.py`를 실행한다. 2,520개 대화의 보존된 `choices.csv`, `measurements.csv`만 읽으며 원본은 변경하지 않는다. `numpy`, `pandas`, `matplotlib`, Noto Sans CJK 글꼴이 필요하다.
