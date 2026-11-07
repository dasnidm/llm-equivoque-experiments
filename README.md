# 실험 7 작업 현황

**ENABLED — 작업 선점·실행 허용**

- 실행: `equivoque-2026-11-07-exp7-main-v2`
- 갱신 시각: 2026-11-07T21:23:35+00:00 (UTC)
- 상태 사유: Explicit user continue after successful gpt-6-sol device reauthentication; fresh calibration02 at concurrency1; preserve failed01
- 예약 병렬 수 / 전역 상한: **19 / 30**
- 배정: **77,856대화 · 2,600작업**
- 보고된 대화: 완료 **627**, 실패 **3**, 중단 **10**, 미시작·미보고 **77,216**
- 보고된 논리 호출: **21,505 / 2,647,104**

[전체 작업·소유권·결과 참조 JSON](board.json)

대화·호출 집계는 작업 결과가 게시될 때 갱신된다. 미시작·미보고에는 아직 결과가 게시되지 않은 실행 중 작업도 포함된다. 예약 병렬 수는 실제 진행 중인 요청 수가 아니다. STOP 전파에는 작업자의 확인 주기와 진행 중 요청 종료 시간이 필요하다.

| 모델 | 담당 VM | 예약 병렬 | 작업 상태¹ | 대화 상태² | 보고 호출 | 마지막 heartbeat (UTC) |
|---|---|---:|---|---|---:|---|
| gpt-5.6-luna | 미배정 | 0 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | — |
| gpt-5.6-sol | vm-505937635844 | 10 | 325/0/0/0/0/0 | 0/0/0/9,732 | 0 | 2026-11-07T13:26:04+00:00 |
| gpt-5.6-terra | vm-f92ddb80580d | 5 | 317/0/1/3/3/1 | 186/3/1/9,542 | 6,371 | 2026-11-07T21:22:29+00:00 |
| gpt-6-astra | cloud-astra-01 | 3 | 309/0/1/12/3/0 | 441/0/9/9,282 | 15,134 | 2026-11-07T21:23:35+00:00 |
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
| model-03-job-0007 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/1762efaa057ddfa511044c1f38ea724e6f9e7b9b/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0007.jsonl.gz) |
| model-04-job-0015 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/21e7dacff3f6e4e74ae8535cf007049a55f9f8c8/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0015.jsonl.gz) |
| model-03-job-0006 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/a8a3823e084cee2848d8401ba726ef5d4a7edfbb/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0006.jsonl.gz) |
| model-04-job-0014 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/657d059bfef3e4966e98c5cd0c5b7061aef453f0/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0014.jsonl.gz) |
| model-03-job-0005 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/e827c1f27b9fdea62db095b6798f9f7e22c2487f/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0005.jsonl.gz) |
| model-03-job-0004 | gpt-5.6-terra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/18d8c76083dff2bb3c3307323586ed6fe2e15060/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0004.jsonl.gz) |
| model-04-job-0013 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/dc06c062674c7b8063ad807e86b99fa1af367b7e/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0013.jsonl.gz) |
| model-03-job-0003 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/1f3495c8b0b49427c284fc3533e20dfbf4bcb106/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0003.jsonl.gz) |
| model-04-job-0012 | gpt-6-astra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/ee0763ab898f99832f112d61f0b839afd0e2b1ab/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0012.resume-job12-01.jsonl.gz) |
| model-03-job-0002 | gpt-5.6-terra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/eebd36196be12f5382504017450d7e1ac8c710e7/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0002.jsonl.gz) |
| model-04-job-0011 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/3b770a5027ada1b2fe28a1bd14f1a4b732a9e69d/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0011.jsonl.gz) |
| model-04-job-0010 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/0f53e97dee976921c372c55a8d4e1b061e68f3b8/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0010.jsonl.gz) |
| model-04-job-0009 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/603befcd909d08ea92bf91219f04d35db5c3f68f/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0009.jsonl.gz) |
| model-04-job-0008 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/d81b81cc87ac7ede69cc05a595f9ba6e5d3dcfc1/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0008.jsonl.gz) |
| model-04-job-0007 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/1ef76bc2d7aec8ab5651b575052c66cdef7bd356/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0007.jsonl.gz) |
| model-04-job-0006 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/4870c9628aed988259798adc92af48d52d7571da/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0006.jsonl.gz) |
| model-04-job-0005 | gpt-6-astra | complete | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/4cc3b98bec1b3216f8452a11ce6abda1eac39248/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0005.jsonl.gz) |
| model-03-job-0001 | gpt-5.6-terra | blocked | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/6c4fac18cf6ebcf1bf9e9bb6b4f090cd5e964dff/results/equivoque-2026-11-07-exp7-main-v2/gpt-5.6-terra/model-03-job-0001.jsonl.gz) |
| model-04-job-0004 | gpt-6-astra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/c3f97a87aa682c1421b0ad8ff9d7123b95f2a467/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0004.resume-job4-01.jsonl.gz) |
| model-04-job-0003 | gpt-6-astra | partial_failed | [결과 보기](https://github.com/dasnidm/llm-equivoque-experiments/blob/f34cf639eb445e0fdc11a0555bdbfdb2395a8cf7/results/equivoque-2026-11-07-exp7-main-v2/gpt-6-astra/model-04-job-0003.continuation-01.jsonl.gz) |

작업은 원격 선점 확인 후 실행한다. 중단·응답 불확실·보류 작업은 자동으로 재배정하지 않는다.
