# 실험 7 작업 현황

**ENABLED — 작업 선점·실행 허용**

- 실행: `equivoque-2026-11-07-exp7-main-v2`
- 갱신 시각: 2026-11-07T14:50:04+00:00 (UTC)
- 상태 사유: Astra catalog refresh429 mitigation validated; fresh c10-02 technical check under pinned metadata; primary held until pass
- 예약 병렬 수 / 전역 상한: **20 / 30**
- 배정: **77,856대화 · 2,600작업**
- 보고된 대화: 완료 **83**, 실패 **0**, 중단 **3**, 미시작·미보고 **77,770**
- 보고된 논리 호출: **2,863 / 2,647,104**

[전체 작업·소유권·결과 참조 JSON](board.json)

대화·호출 집계는 작업 결과가 게시될 때 갱신된다. 미시작·미보고에는 아직 결과가 게시되지 않은 실행 중 작업도 포함된다. 예약 병렬 수는 실제 진행 중인 요청 수가 아니다. STOP 전파에는 작업자의 확인 주기와 진행 중 요청 종료 시간이 필요하다.

| 모델 | 담당 VM | 예약 병렬 | 작업 상태¹ | 대화 상태² | 보고 호출 | 마지막 heartbeat (UTC) |
|---|---|---:|---|---|---:|---|
| gpt-5.6-luna | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-5.6-sol | vm-505937635844 | 10 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | 2026-11-07T13:26:04+00:00 |
| gpt-5.6-terra | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-6-astra | cloud-astra-01 | 10 | 321/0/0/2/0/2 | 83/0/3/9,646 | 2,863 | 2026-11-07T13:25:54+00:00 |
| gpt-6-luna | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-6-sol | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-6.1-sol | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-6.1-terra | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |

¹ 작업: 미배정 / 선점 / 실행 / 완료 / 일부 실패 / 보류.
² 대화: 완료 / 실패 / 중단 / 미시작·미보고.

## 동결 정보

- 소스 commit: [`a47a3ad8e945497eb5fcbeb140bef8a198a25c1f`](https://github.com/dasnidm/llm-equivoque-experiments/tree/a47a3ad8e945497eb5fcbeb140bef8a198a25c1f)
- 배정 요약 SHA-256: `238ee4af8674ac16554bb67a998b974d00b3e62ae9b461a72bc26583bb1838ed`
- 실행 계약 SHA-256: `9e3a965baf54d243b8ff84c532ae5f273b054a440ce8fdb9423ebccca22247dd`

## 최근 게시 결과

최근 20개까지 표시한다. 전체 목록과 결과 SHA-256은 board.json에 보존한다.

| 작업 | 모델 | 상태 | 결과 |
|---|---|---|---|
| model-04-job-0003 | gpt-6-astra | blocked | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/84db8338d81e2497005722ffc7a3674e25245686/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0003.jsonl.gz) |
| model-04-job-0002 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/ce6ad2f03be015d1dc80cce82071f348ca297427/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0002.jsonl.gz) |
| model-04-job-0001 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/b904a7f54474174bc7bc786e2d7b978399ae0113/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0001.jsonl.gz) |

작업은 원격 선점 확인 후 실행한다. 중단·응답 불확실·보류 작업은 자동으로 재배정하지 않는다.
