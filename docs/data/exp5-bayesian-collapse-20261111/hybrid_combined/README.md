# 조합별 전체 시행: 누적 의심 D

모델 × 추론 수준 **한 조합의 120개 대화를 하나의 그래프**에 겹쳤다. 각 대화의 첫 공동 보고 위치는 빨간 별이다. 점과 선은 서로 겹칠 수 있으며, 같은 위치에 겹친 별은 `×숫자`로 건수를 표시한다.

| 모델 | Low | Medium | High |
| --- | --- | --- | --- |
| gpt-5.6-luna | [Low](gpt-5.6-luna-low.png) | [Medium](gpt-5.6-luna-medium.png) | [High](gpt-5.6-luna-high.png) |
| gpt-5.6-terra | [Low](gpt-5.6-terra-low.png) | [Medium](gpt-5.6-terra-medium.png) | [High](gpt-5.6-terra-high.png) |
| gpt-5.6-sol | [Low](gpt-5.6-sol-low.png) | [Medium](gpt-5.6-sol-medium.png) | [High](gpt-5.6-sol-high.png) |
| gpt-6-luna | [Low](gpt-6-luna-low.png) | [Medium](gpt-6-luna-medium.png) | [High](gpt-6-luna-high.png) |
| gpt-6-sol | [Low](gpt-6-sol-low.png) | [Medium](gpt-6-sol-medium.png) | [High](gpt-6-sol-high.png) |
| gpt-6-astra | [Low](gpt-6-astra-low.png) | [Medium](gpt-6-astra-medium.png) | [High](gpt-6-astra-high.png) |
| gpt-6.1-sol | [Low](gpt-6.1-sol-low.png) | [Medium](gpt-6.1-sol-medium.png) | [High](gpt-6.1-sol-high.png) |

[21개 조합 PDF](all_21_configurations.pdf) · [한 시행씩 분리한 그래프와 모델 설명](../hybrid_model/README.md) · [라운드별 원본 계산값](../hybrid_model/hybrid_rounds.csv.gz)

## 보는 법

- 한 선은 한 대화의 10라운드다. **파랑은 obj, 주황은 seq**이며 실선은 카드, 점선은 고양이다. 색은 K/D 구분이 아니다. 각 조합에는 obj 60개·seq 60개, 각 소재 30개씩 있다.
- 빨간 별은 첫 `impact=1 AND counterfactual=no` 공동 보고다. 별 옆 `×숫자`는 같은 라운드·같은 D값(소수점 여섯 자리 기준)에 겹친 첫 보고 수다. 별 위치는 이동하지 않았고 텍스트만 옆에 표시한다.
- 패널 안의 건수는 10라운드 안에 첫 공동 보고가 있던 대화 수다. 별이 없으면 공동 보고가 그 기간에 관찰되지 않은 것이며 영원히 없다는 뜻은 아니다.
- Y축 D는 첫 K/D 다음부터 각 피드백의 `-log2(예측 확률)`을 합산한 누적 surprisal이다. 예측이 맞아도 보통 양수가 더해지므로, 상승 자체가 오류 전위나 심리적 손상을 의미하지 않는다.
- 동일한 D와 라운드에 여러 경로가 놓일 수 있다. **K/D의 구체적인 경로는 이 합쳐진 그래프에서 구분하지 않는다.** 개별 시행별 PDF와 CSV에서 확인할 수 있다.

초기 앵커, H0/H1/H2의 사전, 예비 적합과 결과 반복의 별도 계산 및 한계는 [하이브리드 모델 설명](../hybrid_model/README.md)에 명시했다. 높은 D나 별의 분포만으로 LLM의 실제 믿음이나 붕괴 임계점을 입증할 수 없다.

## 재생성

저장소 루트에서 `python docs/data/exp5-bayesian-collapse-20261111/generate_hybrid_model.py`를 먼저 실행한 후, `python docs/data/exp5-bayesian-collapse-20261111/generate_hybrid_combined.py`를 실행한다. 새 LLM 호출은 없다.
