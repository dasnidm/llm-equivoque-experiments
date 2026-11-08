# 실험 5 속도와 실험 7 예상 시간의 비교

실험 5의 최종 `turns.csv` 83,160행에서 최초 요청은 2026-10-12 17:38:31.933399 UTC, 마지막 응답은 2026-10-13 04:33:44.155571 UTC다. 최종 완료 현황판 갱신은 04:34:43 UTC다. 약 10시간 56분에 최종 2,520대화·83,160호출을 완료했으며, 완료된 호출 기준 전체 처리량은 약 127회/분이다. 원본 재확인 결과 coordinator 공개 시각 전의 최종 평가 호출은 없다. 완전한 한 시간 구간에서는 최고 약 144회/분이었다.

| 항목 | 실험 5 | 실험 7 새 전체 계획 / 최근 부하 시험 |
|---|---:|---:|
| 전체 계획 대화 | 2,520 | 77,856 |
| 대화당 턴 | 33 | 34 |
| 전체 계획 턴 | 83,160 | 2,647,104 |
| 병렬 설정 | 최대 40 executor | 최근 최고 통과 총 6 persistent 대화 |
| 관측 완료 속도 | 전체 약 127턴/분 | 두 모델 medium 시험 약 83.7턴/분 |
| 경과시간의 성격 | 실제 약 11시간 | 현재 시험 속도를 전체 물량에 적용하면 약 22일 |

전체 호출량은 31.83배다. 실험 5의 약 127회/분을 그대로 유지하더라도 새 전체 계획에는 약 14.5일이 필요하다. 최근 시험 속도는 그 약 66%이며, 이를 대입하면 약 22일이다. 이 계산은 전체 모델·effort·형식·운영 중단을 측정한 예측이 아니라 물량과 가정 속도의 산술 비교다. 이전 답변의 운영 손실 20~30% 또한 관측 예측이 아니라 가정이다.

실험 5는 `Admission`의 전역 큐와 요청 슬롯을 사용했고, 슬롯은 매 턴 CLI 시작·응답·종료까지 포함했다. 40 executor가 40개의 공급자 내부 추론 동시 실행을 뜻하지 않는다. 현재 persistent 대화 pool 및 송신 상한과 직접 동일시할 수 없다. 당시 15개 모델 용량 실패가 있었고, 명시적으로 분류된 capacity 오류는 해당 worker에 격리했으며 미완료 대화는 사용자의 명시 지시로 대체했다. 현재 미분류 응답 429는 공통 STOP으로 전파하고 실패·불확실 시행은 대체하지 않는다.

따라서 최근 시험의 6병렬은 현재 두 모델/medium/송신 간격에서 가장 빠르게 통과한 시험값이다. 과거보다 낮아진 영구 서버 한도나 보편적인 최적 병렬 수를 식별한 것이 아니다.

출처:

- `sequence_replication/runtime/coordinator-launch-01.json`
- `sequence_replication/runtime/direct-progress.json`
- `sequence_replication/runtime/supervisor-status.json`
- `sequence_replication/runtime/direct-capacity-adapter-01.json`
- `sequence_replication/runtime/expansion-01/code/expanded.py`
- `analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables/turns.csv`
- 같은 디렉터리의 `REPORT.ko.md` 및 `results.json`
