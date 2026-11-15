# 실험 7: 최대 속도 기술 점검 현황

본수집이 아닌 별도 기술 시험이다. 응답 원문과 인증 정보는 게시하지 않는다.

기존 [본 실험 현황판](https://github.com/dasnidm/llm-equivoque-experiments/tree/exp7/cards-200-coordination-20261115)은 중단 상태다.

갱신: 2026-11-15 14:55:23 UTC
기술 시험 프로세스: 실행 중

## stage-01

요청 상한 100회/분 · 동시 대화 7개

완료 대화 7개 / 7개 · 성공 턴 238개 · 관측 처리량 75.5회/분
미확정 대화 0개 · 도구 이벤트 0개 · 컨텍스트 압축 0개 · native 429 기록 0

## stage-02

요청 상한 100회/분 · 동시 대화 14개

| 모델 | 추론 수준 | 상태 | 완료 턴 / 34 |
|---|---|---|---:|
| gpt-5.6-luna | low | active | 30 / 34 |
| gpt-5.6-terra | medium | active | 32 / 34 |
| gpt-5.6-sol | high | active | 26 / 34 |
| gpt-6-luna | low | complete | 34 / 34 |
| gpt-6-sol | medium | active | 25 / 34 |
| gpt-6-astra | high | active | 29 / 34 |
| gpt-6.1-sol | low | complete | 34 / 34 |
| gpt-5.6-luna | high | active | 28 / 34 |
| gpt-5.6-terra | low | active | 28 / 34 |
| gpt-5.6-sol | medium | active | 31 / 34 |
| gpt-6-luna | high | active | 26 / 34 |
| gpt-6-sol | low | active | 25 / 34 |
| gpt-6-astra | medium | active | 27 / 34 |
| gpt-6.1-sol | high | active | 31 / 34 |

자동 속도 탐색 상태: `increase_concurrency`
