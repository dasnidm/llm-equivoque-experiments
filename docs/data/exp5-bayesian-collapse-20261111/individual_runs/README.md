# 시행 하나당 그래프 하나: K/D surprisal

실험 5에서 **독립 대화 한 개를 그래프 한 개로** 분리했다. 각 그래프는 1~10라운드를 이어 보여준다. 각 모델·추론 수준 PDF에는 obj/seq × 카드/고양이의 120개 대화가 들어 있다.

| 모델 | Low | Medium | High |
| --- | --- | --- | --- |
| gpt-5.6-luna | [전체 PDF](gpt-5.6-luna-low.pdf) · [예시](gpt-5.6-luna-low-example.png) | [전체 PDF](gpt-5.6-luna-medium.pdf) · [예시](gpt-5.6-luna-medium-example.png) | [전체 PDF](gpt-5.6-luna-high.pdf) · [예시](gpt-5.6-luna-high-example.png) |
| gpt-5.6-terra | [전체 PDF](gpt-5.6-terra-low.pdf) · [예시](gpt-5.6-terra-low-example.png) | [전체 PDF](gpt-5.6-terra-medium.pdf) · [예시](gpt-5.6-terra-medium-example.png) | [전체 PDF](gpt-5.6-terra-high.pdf) · [예시](gpt-5.6-terra-high-example.png) |
| gpt-5.6-sol | [전체 PDF](gpt-5.6-sol-low.pdf) · [예시](gpt-5.6-sol-low-example.png) | [전체 PDF](gpt-5.6-sol-medium.pdf) · [예시](gpt-5.6-sol-medium-example.png) | [전체 PDF](gpt-5.6-sol-high.pdf) · [예시](gpt-5.6-sol-high-example.png) |
| gpt-6-luna | [전체 PDF](gpt-6-luna-low.pdf) · [예시](gpt-6-luna-low-example.png) | [전체 PDF](gpt-6-luna-medium.pdf) · [예시](gpt-6-luna-medium-example.png) | [전체 PDF](gpt-6-luna-high.pdf) · [예시](gpt-6-luna-high-example.png) |
| gpt-6-sol | [전체 PDF](gpt-6-sol-low.pdf) · [예시](gpt-6-sol-low-example.png) | [전체 PDF](gpt-6-sol-medium.pdf) · [예시](gpt-6-sol-medium-example.png) | [전체 PDF](gpt-6-sol-high.pdf) · [예시](gpt-6-sol-high-example.png) |
| gpt-6-astra | [전체 PDF](gpt-6-astra-low.pdf) · [예시](gpt-6-astra-low-example.png) | [전체 PDF](gpt-6-astra-medium.pdf) · [예시](gpt-6-astra-medium-example.png) | [전체 PDF](gpt-6-astra-high.pdf) · [예시](gpt-6-astra-high-example.png) |
| gpt-6.1-sol | [전체 PDF](gpt-6.1-sol-low.pdf) · [예시](gpt-6.1-sol-low-example.png) | [전체 PDF](gpt-6.1-sol-medium.pdf) · [예시](gpt-6.1-sol-medium-example.png) | [전체 PDF](gpt-6.1-sol-high.pdf) · [예시](gpt-6.1-sol-high-example.png) |

## 보는 법

- 파란 선 하나는 대화 하나다. 색은 라운드별 K/D를 구분하지 않는다.
- X축은 1~10라운드이고, 각 라운드 아래의 `KK`, `KD`, `DK`, `DD`는 그 라운드의 첫 번째·두 번째 피드백이다.
- Y축은 그 라운드 두 피드백에 대한 **surprisal의 합(bits)**이다. K/D가 처음 50:50이라는 사전에서 출발해 대화별 관측 순서대로 확률을 갱신한다. [계산 방법과 데이터](../kd_surprisal/README.md).
- 빨간 별은 처음 `impact=1`과 `counterfactual=no`가 함께 나타난 라운드다. 별이 없으면 그 보고가 10라운드 안에 관찰되지 않은 것이다. 그래프는 첫 보고 이후에도 10라운드까지 계속된다.
- 각 PDF는 12페이지다. obj 카드·obj 고양이·seq 카드·seq 고양이 순으로 각각 30개 대화를 세 페이지에 나눈다. 각 페이지에는 서로 다른 대화 10개의 그래프가 있다. PDF의 `no transition by round 10`은 10라운드 내 공동 보고가 없었다는 뜻이다.
- 예시 이미지는 네 조건에서 각각 한 대화를 보여준다. 해당 조건에 전환 대화가 있으면 그중 하나, 없으면 첫 대화를 표시한다. 예시는 전체 분포를 대표하도록 선정한 표본이 아니다.

그래프는 LLM의 실제 내적 믿음, 인간의 오류 전위, 통제감 자체를 직접 측정하지 않는다. 놀람이 높아진 라운드와 보고 변화의 관계는 별도의 통계적 검증이 필요하다.

## 재생성

저장소 루트에서 먼저 `python docs/data/exp5-bayesian-collapse-20261111/generate_kd_surprisal.py`, 이어서 `python docs/data/exp5-bayesian-collapse-20261111/generate_individual_runs.py`를 실행한다. `numpy`, `pandas`, `matplotlib`, `reportlab` 및 Noto Sans CJK 글꼴이 필요하다. 새 LLM 호출은 없다.
