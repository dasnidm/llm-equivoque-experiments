# 실험 7 작업 현황

**ENABLED — 작업 선점·실행 허용**

- 실행: `equivoque-2026-11-07-exp7-main-v2`
- 갱신 시각: 2026-11-08T00:38:14+00:00 (UTC)
- 상태 사유: Reviewed CLI catalog429 after cooldown; user-authorized Astra2 continuation, preserve interruptions
- 예약 병렬 수 / 전역 상한: **18 / 30**
- 배정: **77,856대화 · 2,600작업**
- 보고된 대화: 완료 **981**, 실패 **6**, 중단 **18**, 미시작·미보고 **76,851**
- 보고된 논리 호출: **33,683 / 2,647,104**

[전체 작업·소유권·결과 참조 JSON](board.json)

대화·호출 집계는 작업 결과가 게시될 때 갱신된다. 미시작·미보고에는 아직 결과가 게시되지 않은 실행 중 작업도 포함된다. 예약 병렬 수는 실제 진행 중인 요청 수가 아니다. STOP 전파에는 작업자의 확인 주기와 진행 중 요청 종료 시간이 필요하다.

| 모델 | 담당 VM | 예약 병렬 | 작업 상태¹ | 대화 상태² | 보고 호출 | 마지막 heartbeat (UTC) |
|---|---|---:|---|---|---:|---|
| gpt-5.6-luna | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-5.6-sol | vm-505937635844 | 10 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | 2026-11-07T13:26:04+00:00 |
| gpt-5.6-terra | vm-f92ddb80580d | 5 | 308/0/1/8/6/2 | 423/6/6/9,297 | 14,531 | 2026-11-08T00:37:10+00:00 |
| gpt-6-astra | cloud-astra-01 | 2 | 305/0/1/15/4/0 | 558/0/12/9,162 | 19,152 | 2026-11-08T00:38:14+00:00 |
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
| model-03-job-0006 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/a8a3823e084cee2848d8401ba726ef5d4a7edfbb/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0006.jsonl.gz) |
| model-04-job-0014 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/657d059bfef3e4966e98c5cd0c5b7061aef453f0/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0014.jsonl.gz) |
| model-03-job-0005 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/e827c1f27b9fdea62db095b6798f9f7e22c2487f/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0005.jsonl.gz) |
| model-03-job-0004 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/18d8c76083dff2bb3c3307323586ed6fe2e15060/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0004.jsonl.gz) |
| model-04-job-0013 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/dc06c062674c7b8063ad807e86b99fa1af367b7e/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0013.jsonl.gz) |

작업은 원격 선점 확인 후 실행한다. 중단·응답 불확실·보류 작업은 자동으로 재배정하지 않는다.
