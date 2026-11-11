# 최초 규칙·전환 가설·의심 누적: 임시 하이브리드 모델

사용자가 제시한 *Equivoque Hybrid Cognitive Model*을 실험 5 기록에 맞게 구체화한 **탐색적 모델**이다. 10라운드의 두 K/D 피드백을 순서대로 처리하고, 선택 의미가 유지되는지 혹은 전환되는지를 베이지안 가설로 추론한다. 새 LLM 호출은 없다.

[모델·추론 수준별로 120개 시행을 합친 그래프](../hybrid_combined/README.md)

[모델·추론 수준별로 카드와 고양이를 분리한 그래프](../hybrid_by_frame/README.md)

[전환 횟수 범주 대신 시간순 K/D 전이로 수정한 후속 모델](../temporal_kd_model/README.md)

| 모델 | Low | Medium | High |
| --- | --- | --- | --- |
| gpt-5.6-luna | [전체 PDF](gpt-5.6-luna-low.pdf) · [예시](gpt-5.6-luna-low-example.png) | [전체 PDF](gpt-5.6-luna-medium.pdf) · [예시](gpt-5.6-luna-medium-example.png) | [전체 PDF](gpt-5.6-luna-high.pdf) · [예시](gpt-5.6-luna-high-example.png) |
| gpt-5.6-terra | [전체 PDF](gpt-5.6-terra-low.pdf) · [예시](gpt-5.6-terra-low-example.png) | [전체 PDF](gpt-5.6-terra-medium.pdf) · [예시](gpt-5.6-terra-medium-example.png) | [전체 PDF](gpt-5.6-terra-high.pdf) · [예시](gpt-5.6-terra-high-example.png) |
| gpt-5.6-sol | [전체 PDF](gpt-5.6-sol-low.pdf) · [예시](gpt-5.6-sol-low-example.png) | [전체 PDF](gpt-5.6-sol-medium.pdf) · [예시](gpt-5.6-sol-medium-example.png) | [전체 PDF](gpt-5.6-sol-high.pdf) · [예시](gpt-5.6-sol-high-example.png) |
| gpt-6-luna | [전체 PDF](gpt-6-luna-low.pdf) · [예시](gpt-6-luna-low-example.png) | [전체 PDF](gpt-6-luna-medium.pdf) · [예시](gpt-6-luna-medium-example.png) | [전체 PDF](gpt-6-luna-high.pdf) · [예시](gpt-6-luna-high-example.png) |
| gpt-6-sol | [전체 PDF](gpt-6-sol-low.pdf) · [예시](gpt-6-sol-low-example.png) | [전체 PDF](gpt-6-sol-medium.pdf) · [예시](gpt-6-sol-medium-example.png) | [전체 PDF](gpt-6-sol-high.pdf) · [예시](gpt-6-sol-high-example.png) |
| gpt-6-astra | [전체 PDF](gpt-6-astra-low.pdf) · [예시](gpt-6-astra-low-example.png) | [전체 PDF](gpt-6-astra-medium.pdf) · [예시](gpt-6-astra-medium-example.png) | [전체 PDF](gpt-6-astra-high.pdf) · [예시](gpt-6-astra-high-example.png) |
| gpt-6.1-sol | [전체 PDF](gpt-6.1-sol-low.pdf) · [예시](gpt-6.1-sol-low-example.png) | [전체 PDF](gpt-6.1-sol-medium.pdf) · [예시](gpt-6.1-sol-medium-example.png) | [전체 PDF](gpt-6.1-sol-high.pdf) · [예시](gpt-6.1-sol-high-example.png) |

[대화·라운드별 값](hybrid_rounds.csv.gz) · [첫 전환의 교차검증 예측](hazard_crossvalidated.csv.gz) · [적합 결과](fit_results.json) · [이전 K/D 빈도 모델](../kd_surprisal/README.md)

## 그래프 읽기

한 그래프는 독립 대화 하나의 10라운드다. X축 아래 `KK`, `KD`, `DK`, `DD`는 첫 번째·두 번째 선택이 각각 유지(K) 또는 제거(D)된 순서다. 파란 선은 **최초 라벨 다음부터 누적한 surprisal D(bits)**이고, 빨간 별은 최초 `impact=1 AND counterfactual=no` 보고다. 별이 없다는 것은 10라운드 안에 그 공동 보고가 없었다는 뜻이다. 각 PDF는 120개 시행, 12페이지이며 obj 카드·obj 고양이·seq 카드·seq 고양이 순서다.

## 1. 가설과 사전확률

한 대화는 20개 K/D 피드백과 최대 19개 전환 경계를 가진다고 모델이 가정한다. 첫 라벨은 K/D 50:50에서 출발해 초기 앵커로 삼고 D 계산에서는 제외한다.

- H0: 19개 경계에서 전환 0회, 사전확률 0.50.
- H1: 전환 정확히 1회, 사전확률 0.25.
- H2: 전환 2~19회, 사전확률 0.25. 그 안에서 최종 전환 수는 균등하다.

최종 전환 수 `m`이 주어지면 그 위치는 19개 경계의 조합 중 균등하게 선택한다고 가정한다. 이것은 모델을 실행하기 위한 잠정적인 사전·시간 범위이지, LLM이 실제로 그 믿음이나 20단계 계획을 가졌다고 관측한 결과가 아니다. 최초 라벨 직후 다음 피드백을 계산할 때 이 사전 때문에 유지 확률은 약 84.9%, 전환 확률은 약 15.1%다. 첫 라벨 자체의 사전 50:50과 구분한다.

## 2. 구조와 추론

구조 변수 `i`는 직전 K/D와 현재 K/D가 다른 횟수이며, 라운드 경계를 포함해 시간순으로 센다. 매 단계 현재 가설의 전환 위치 가능성을 업데이트하고 다음 라벨의 확률 `p_t=P(r_t | r_<t)`을 계산한다.

```text
현재와 직전이 다르면 전환 s_t = 1, 같으면 0
구조 변수 i_t = sum(s_j), j = 2 ... t
누적 surprisal D_t = sum(-log2(p_j)), j = 2 ... t
```

`hybrid_rounds.csv.gz`에는 각 단계의 `p_first`, `p_second`, 라운드별 `cumulative_switches`, 세 가설의 사후확률 `p_H0/p_H1/p_Hmulti`, 주된 `cumulative_surprise_bits`가 있다. 비교용 비대칭 지표 `cumulative_violation`은 관측값이 대안보다 **엄격히 덜 예상될 때만** `1-p_t`를 더하고 같거나 더 예상되면 0을 더한다. 본 그림은 사용자가 준 첫 번째 정의인 누적 surprisal만 표시한다.

전환이 실제로 한 번이라도 보이면 H0, 두 번 이상 보이면 H1의 사후확률은 0이다. 이것은 라벨 오류가 없고 가설의 전환 수가 정확하다는 모델 가정의 결과다. 단계별 규칙이 다른 경우에도 경계를 하나의 시간순 흐름으로 취급하므로, 반복되는 `KD | KD`도 시간순 전환으로 기록된다.

## 3. 보고와 임계점: 예비 적합

원문의 형태 `S(D)=1 / (1 + exp(k*(D-theta)))`를 계산적 지표로 두고, 관측된 **첫 공동 보고**에 대해서만 `P(이번 라운드 첫 공동 보고 | 이전 보고 없음)=1-S(D)`를 탐색적으로 적합했다. 이것은 인간의 느낌이나 LLM의 숨은 SoA를 직접 측정한 값이 아니며, 첫 사건 위험과 매 라운드의 일반적 통제감은 같지 않다. 더 복잡한 보고·복귀 모델은 여기에 포함되지 않는다.

공동 보고 전 23,657개 라운드, 342건에서 30개 사례 패밀리를 기준으로 5개 분할을 사용했다. 대화와 같은 사례 패밀리의 조건들이 학습·평가에 섞이지 않도록 분리했다. 누적 surprisal 모형의 전체 적합값은 `k≈0.0465`, `theta≈102.44 bits`다. 그러나 관측된 위험 구간의 D는 최대 약 **22.67 bits**이므로 50% 전환 위치인 theta는 데이터 범위 밖이다. 이는 붕괴점이 102.44 bits라는 근거가 아니다. 자료에서 임계점이 확인되지 않았다.

사례 패밀리 교차검증 로그 손실은 누적 surprisal 0.07489, 비대칭 의심 0.07469, 라운드만 쓰는 비교 모델 0.07560이다. 작은 차이는 사후 탐색이며, 가설·사전·모델 선택의 불확실성이나 인간/LLM 기제를 검증하지 않는다. seq 최초 공동 보고는 9건이라 그 조건의 별도 적합은 매우 불안정하다. 모델·추론 설정 및 조건별 차이를 별도 추정하지 않은 단일 풀링 모델이다.

## 결과 반복과 최종 놀라움

결과 반복은 `outcome_log_bf`라는 **별도 진단**으로만 계산한다. 고정 결과 모델(95% 목표 유지, 5% 균등 무작위)과 매 라운드 균등 무작위 결과의 로그 우도비이며 양수는 이 두 가정에서 고정 결과 설명에 유리하다. 실제 seq의 균형 일정은 독립 균등 과정과 같지 않다. 관찰된 최종 위치는 이 강제 게임에서 기록된 결과다.

선택과 K/D, 결과는 구조적으로 연결되므로, 이 반복 지표를 라벨 기반 D에 독립 증거인 것처럼 합산하지 않았다. 원문의 최종 놀라움 `A = SoA × S_base`는 `S_base`와 놀라움 관측치가 정해지지 않아 계산하거나 적합하지 않았다.

## 중요한 제한

누적 surprisal은 예측이 맞는 라벨에서도 대개 증가한다. 무작위 관찰도 정보량을 만들므로, 증가 자체는 오류 축적이나 심리적 손상을 입증하지 않는다. 비대칭 지표는 이 문제를 다르게 다루는 비교안일 뿐이다. 각 그래프의 D와 red star만으로 기제, 인과관계, 임계점을 확인할 수 없다.

## 재생성

저장소 루트에서 `python docs/data/exp5-bayesian-collapse-20261111/generate_hybrid_model.py` 다음 `python docs/data/exp5-bayesian-collapse-20261111/generate_hybrid_figures.py`를 실행한다. `numpy`, `pandas`, `scipy`, `scikit-learn`, `matplotlib`, `reportlab` 및 Noto Sans CJK 글꼴이 필요하다. 실험 5의 보존된 `choices.csv`, `measurements.csv`만 읽는다.
