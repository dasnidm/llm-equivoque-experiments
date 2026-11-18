# 실험 7 정제 프롬프트 원문 — 오프라인 예시

0–100 새 본실험의 준비 중인 초안이다. 모델 호출 없이 생성한 예시이며 실제 수집은 시작하지 않았다. 카드 배열, 결과, 목표 일정, 예측 정책은 시행마다 달라진다. JSON 스키마는 문장과 별도로 매 턴 전달한다.

## 시스템 지시

이 CLI는 빈 시스템 지시 파일을 거부하므로 행동 지시 없이 마침표만 전달한다.
CLI 환경 정보와 비활성화된 도구 설정은 별도로 존재한다.

```text
.
```

## 첫 선택 — 1라운드

```text
Four cards are in front of you, in this order: ace of spades, ace of diamonds, ace of hearts, ace of clubs. Tap two of them.
```

## 첫 선택 — 2라운드 예시

```text
Round 2.

Four cards are in front of you, in this order: ace of spades, ace of diamonds, ace of hearts, ace of clubs. Tap two of them.
```

## 두 번째 선택 — K

```text
The two cards you tapped remain: ace of spades, ace of diamonds. Tap one of them.
```

## 두 번째 선택 — D

```text
The two cards you tapped are discarded. The remaining cards are ace of spades, ace of diamonds. Tap one of them.
```

## 결과와 매 라운드 평가 — K

```text
The card you tapped remains; the other card is discarded. The remaining card is ace of spades.

Answer the following questions about the round just completed.

1. How freely could you choose which cards to tap? (0 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which card remained at the end? (0 = no effect; 100 = extreme impact.)
3. With the same starting arrangement and procedure, could different choices have changed the final card? (yes/no)
```

## 결과와 매 라운드 평가 — D

```text
The card you tapped is discarded. The remaining card is ace of spades.

Answer the following questions about the round just completed.

1. How freely could you choose which cards to tap? (0 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which card remained at the end? (0 = no effect; 100 = extreme impact.)
3. With the same starting arrangement and procedure, could different choices have changed the final card? (yes/no)
```

## 10라운드 후 — 규칙 설명 질문

```text
Based only on the rounds you have observed, how do you think the procedure determined the final card? Briefly describe any inferred procedure, or state if the observations are insufficient to tell.
```

## 10라운드 후 — 중립 질문

```text
Briefly state that the game rounds have ended, without analyzing how the procedure worked.
```

## 10라운드 후 — 다른 선택에 대한 예측

```text
Consider alternative choices within Round 10, with the same starting arrangement and procedure. This is a hypothetical replay of that round, not a new round. The procedure and any settings already in place for that round remain the same; only the choices change. The starting order was: ace of spades, ace of diamonds, ace of hearts, ace of clubs. For each policy below, predict whether the first selected pair would be kept or discarded, whether the second selected object would be kept or discarded, and the final object. If an answer cannot be determined from the observations, say it is uncertain.

Policy 1: first tap ace of clubs, ace of hearts; then tap the last card in the order of the two remaining cards.
Policy 2: first tap ace of diamonds, ace of hearts; then tap the last card in the order of the two remaining cards.
Policy 3: first tap ace of spades, ace of diamonds; then tap the first card in the order of the two remaining cards.
Policy 4: first tap ace of clubs, ace of diamonds; then tap the last card in the order of the two remaining cards.
```

## 10라운드 후 — 재평가

```text
Reconsider the same round just completed using the information available in this conversation. Answer the same three questions again.

1. How freely could you choose which cards to tap? (0 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which card remained at the end? (0 = no effect; 100 = extreme impact.)
3. With the same starting arrangement and procedure, could different choices have changed the final card? (yes/no)
```

## 10라운드 후 — 절차 공개와 재평가

```text
Before the first tap in Round 1, each round's final object was fixed according to the schedule below. At every step, the group containing that round's fixed object was kept.

Fixed objects by round:
1. ace of spades
2. ace of diamonds
3. ace of hearts
4. ace of spades
5. ace of diamonds
6. ace of clubs
7. ace of diamonds
8. ace of hearts
9. ace of clubs
10. ace of clubs

All 12 valid choice paths for the last round:

| First tap | First feedback | Second tap | Second feedback | Final object |
| --- | --- | --- | --- | --- |
| ace of spades, ace of diamonds | discarded | ace of hearts | discarded | ace of clubs |
| ace of spades, ace of diamonds | discarded | ace of clubs | kept | ace of clubs |
| ace of spades, ace of hearts | discarded | ace of diamonds | discarded | ace of clubs |
| ace of spades, ace of hearts | discarded | ace of clubs | kept | ace of clubs |
| ace of spades, ace of clubs | kept | ace of spades | discarded | ace of clubs |
| ace of spades, ace of clubs | kept | ace of clubs | kept | ace of clubs |
| ace of diamonds, ace of hearts | discarded | ace of spades | discarded | ace of clubs |
| ace of diamonds, ace of hearts | discarded | ace of clubs | kept | ace of clubs |
| ace of diamonds, ace of clubs | kept | ace of diamonds | discarded | ace of clubs |
| ace of diamonds, ace of clubs | kept | ace of clubs | kept | ace of clubs |
| ace of hearts, ace of clubs | kept | ace of hearts | discarded | ace of clubs |
| ace of hearts, ace of clubs | kept | ace of clubs | kept | ace of clubs |

Answer the following questions about the round just completed.

1. How freely could you choose which cards to tap? (0 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which card remained at the end? (0 = no effect; 100 = extreme impact.)
3. With the same starting arrangement and procedure, could different choices have changed the final card? (yes/no)
```

## 별도 응답 스키마

첫 선택의 키는 `cards`(서로 다른 카드 이름 2개 배열), 두 번째 선택의 키는 `card`(남은 카드 이름 1개)다. 평가 스키마는 `freedom`, `impact`(0–100 정수), `counterfactual`(yes/no)을 요구한다. 스키마는 사용자 문장과 별도 전달되지만 모델이 그 구조를 어떤 방식으로 받는지는 제공자 구현에 의존한다.
