# 실험 7 작업 현황

**STOP — 새 호출 중단**

- 실행: `equivoque-2026-11-07-exp7-main-v2`
- 갱신 시각: 2026-11-08T01:04:40+00:00 (UTC)
- 상태 사유: Capacity/authentication diagnostic observed; preserve requests and inspect before resuming
- 예약 병렬 수 / 전역 상한: **18 / 30**
- 배정: **77,856대화 · 2,600작업**
- 보고된 대화: 완료 **1,074**, 실패 **7**, 중단 **25**, 미시작·미보고 **76,750**
- 보고된 논리 호출: **37,012 / 2,647,104**

[전체 작업·소유권·결과 참조 JSON](board.json)

대화·호출 집계는 작업 결과가 게시될 때 갱신된다. 미시작·미보고에는 아직 결과가 게시되지 않은 실행 중 작업도 포함된다. 예약 병렬 수는 실제 진행 중인 요청 수가 아니다. STOP 전파에는 작업자의 확인 주기와 진행 중 요청 종료 시간이 필요하다.

| 모델 | 담당 VM | 예약 병렬 | 작업 상태¹ | 대화 상태² | 보고 호출 | 마지막 heartbeat (UTC) |
|---|---|---:|---|---|---:|---|
| gpt-5.6-luna | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-5.6-sol | vm-505937635844 | 10 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | 2026-11-07T13:26:04+00:00 |
| gpt-5.6-terra | vm-f92ddb80580d | 5 | 306/0/0/9/7/3 | 482/7/11/9,232 | 16,647 | 2026-11-08T01:02:27+00:00 |
| gpt-6-astra | cloud-astra-01 | 2 | 304/0/0/16/4/1 | 592/0/14/9,126 | 20,365 | 2026-11-08T01:04:34+00:00 |
| gpt-6-luna | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-6-sol | vm-097705819101 | 1 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | 2026-11-07T15:49:47+00:00 |
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
| model-04-job-0021 | gpt-6-astra | blocked | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/03c5b3f9e593e88d958eea7e6ec9b9f81bf1e8c8/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0021.jsonl.gz) |
| model-03-job-0019 | gpt-5.6-terra | blocked | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/4a9eec5be87ed6ff1d6fc5aa2002aa29ebfb51dc/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0019.jsonl.gz) |
| model-03-job-0018 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/bfe92ef21d6e27b3d398e5c7d12e9ef00c7c81f9/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0018.jsonl.gz) |
| model-04-job-0020 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/282aa452f997c54fc3ad80ebb86d5cbcb6ce1e09/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0020.jsonl.gz) |
| model-03-job-0017 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/7e5fc689b1fbc6f1586976ff3e02550d08f46d76/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0017.jsonl.gz) |
| model-03-job-0016 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/b1172b1156996de86a599b108e5d6c0b13aa359d/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0016.jsonl.gz) |
| model-04-job-0019 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/5a3eaa9e18e4698f5bbaaf5ce24f584e1efe582c/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0019.jsonl.gz) |
| model-03-job-0015 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/8acc334bf40c58c3ed1b24b31a6afa7d9ec92fdc/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0015.jsonl.gz) |
| model-03-job-0014 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/3c473b7797cb1859872650d0d1ea79436fa953c7/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0014.jsonl.gz) |
| model-04-job-0018 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/ce07b049ee0877d8d921f87ea20ac004a4986e87/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0018.jsonl.gz) |
| model-03-job-0013 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/edb1be40003046b3bdd46e38df481c9c89b3db4d/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0013.jsonl.gz) |
| model-03-job-0012 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/099c6196132d5f37da6c98a9d52ac2252dbcf0c8/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0012.jsonl.gz) |
| model-04-job-0017 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/ea350b5cbb0415dd73ae6c21d3fdfb97d9943034/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0017.jsonl.gz) |
| model-03-job-0011 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/0ffdd6a74b30493f2fdb00adaaa0b09fb4a546e4/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0011.jsonl.gz) |
| model-03-job-0010 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/8ad27adcc4bd24f730cfa4b3fb86f111265a333f/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0010.jsonl.gz) |
| model-04-job-0016 | gpt-6-astra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/501482ad12e4266d366904262270ae789f1f46c7/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0016.resume-job16-01.jsonl.gz) |
| model-03-job-0009 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/0605497414bbdb50ba7c9ce79ea80af4c97a908d/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0009.jsonl.gz) |
| model-03-job-0008 | gpt-5.6-terra | blocked | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/a4fb952b7963b4a2c7037e419a5dbc07d22294a6/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0008.jsonl.gz) |
| model-03-job-0007 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/1762efaa057ddfa511044c1f38ea724e6f9e7b9b/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0007.jsonl.gz) |
| model-04-job-0015 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/21e7dacff3f6e4e74ae8535cf007049a55f9f8c8/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0015.jsonl.gz) |

작업은 원격 선점 확인 후 실행한다. 중단·응답 불확실·보류 작업은 자동으로 재배정하지 않는다.
