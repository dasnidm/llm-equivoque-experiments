# 모델·추론 조합별 카드와 고양이 분리 그래프

각 모델 × 추론 수준 조합에 **카드 그래프 하나와 고양이 그래프 하나**, 총 42개를 만들었다. 각 그래프는 그 소재에서 obj 30개와 seq 30개, 총 60개 대화를 겹친다.

| 모델 | Low | Medium | High |
| --- | --- | --- | --- |
| gpt-5.6-luna | [카드](gpt-5.6-luna-low-cards.png) · [고양이](gpt-5.6-luna-low-cats.png) | [카드](gpt-5.6-luna-medium-cards.png) · [고양이](gpt-5.6-luna-medium-cats.png) | [카드](gpt-5.6-luna-high-cards.png) · [고양이](gpt-5.6-luna-high-cats.png) |
| gpt-5.6-terra | [카드](gpt-5.6-terra-low-cards.png) · [고양이](gpt-5.6-terra-low-cats.png) | [카드](gpt-5.6-terra-medium-cards.png) · [고양이](gpt-5.6-terra-medium-cats.png) | [카드](gpt-5.6-terra-high-cards.png) · [고양이](gpt-5.6-terra-high-cats.png) |
| gpt-5.6-sol | [카드](gpt-5.6-sol-low-cards.png) · [고양이](gpt-5.6-sol-low-cats.png) | [카드](gpt-5.6-sol-medium-cards.png) · [고양이](gpt-5.6-sol-medium-cats.png) | [카드](gpt-5.6-sol-high-cards.png) · [고양이](gpt-5.6-sol-high-cats.png) |
| gpt-6-luna | [카드](gpt-6-luna-low-cards.png) · [고양이](gpt-6-luna-low-cats.png) | [카드](gpt-6-luna-medium-cards.png) · [고양이](gpt-6-luna-medium-cats.png) | [카드](gpt-6-luna-high-cards.png) · [고양이](gpt-6-luna-high-cats.png) |
| gpt-6-sol | [카드](gpt-6-sol-low-cards.png) · [고양이](gpt-6-sol-low-cats.png) | [카드](gpt-6-sol-medium-cards.png) · [고양이](gpt-6-sol-medium-cats.png) | [카드](gpt-6-sol-high-cards.png) · [고양이](gpt-6-sol-high-cats.png) |
| gpt-6-astra | [카드](gpt-6-astra-low-cards.png) · [고양이](gpt-6-astra-low-cats.png) | [카드](gpt-6-astra-medium-cards.png) · [고양이](gpt-6-astra-medium-cats.png) | [카드](gpt-6-astra-high-cards.png) · [고양이](gpt-6-astra-high-cats.png) |
| gpt-6.1-sol | [카드](gpt-6.1-sol-low-cards.png) · [고양이](gpt-6.1-sol-low-cats.png) | [카드](gpt-6.1-sol-medium-cards.png) · [고양이](gpt-6.1-sol-medium-cats.png) | [카드](gpt-6.1-sol-high-cards.png) · [고양이](gpt-6.1-sol-high-cats.png) |

[42개 그래프 전체 PDF](all_42_graphs.pdf) · [하이브리드 모델과 개별 시행](../hybrid_model/README.md) · [카드·고양이를 합친 이전 그래프](../hybrid_combined/README.md)

## 보는 법

- 한 선은 한 대화의 10라운드다. 파랑은 동일 목표(obj), 주황은 변동 목표(seq)이며 색은 K/D 조합을 뜻하지 않는다. 두 조건이 같은 값을 가질 때 선이 겹치거나 색이 섞여 보일 수 있다.
- 빨간 별은 `impact=1 AND counterfactual=no` 공동 보고가 처음 나타난 지점이다. 별 옆 `×숫자`는 그 위치에 겹친 전환 수다. 위치는 이동하지 않았으며 D값의 소수점 여섯째 자리까지 같으면 동일 위치로 센다.
- 제목의 `첫 공동 보고`는 10라운드 안의 대화 수를 조건별로 나타낸다. 별이 없으면 그 기간에 공동 보고가 없었다는 의미다.
- Y축 D는 첫 라벨을 앵커로 둔 뒤 각 K/D의 surprisal을 더한 값이다. 예측이 맞는 라벨에서도 대체로 증가하므로, 값의 증가나 높은 값만으로 오류 전위, 주관적 통제감의 붕괴 또는 임계점을 입증할 수 없다.
- 각 대화의 K/D는 겹친 그래프에서 식별되지 않는다. [시행별 PDF](../hybrid_model/README.md)와 [라운드별 계산 데이터](../hybrid_model/hybrid_rounds.csv.gz)에서 확인할 수 있다.

## 재생성

저장소 루트에서 `python docs/data/exp5-bayesian-collapse-20261111/generate_hybrid_model.py` 실행 후 `python docs/data/exp5-bayesian-collapse-20261111/generate_hybrid_by_frame.py`를 실행한다. 기존 실험 자료를 읽고 새 LLM 호출은 하지 않는다.
