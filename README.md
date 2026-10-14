# LLM Equivoque Experiments

선택에 따라 **남기기·버리기의 의미를 바꿔 미리 정한 결과로 유도하는 절차**에서, 언어 모델이 자신의 선택 자유와 결과 영향력을 어떻게 평가하는지 연구합니다. 실험 문항은 영어이며 카드·고양이 프레임을 사용합니다.

**현재 상태: 6개 실험·파일럿 수집 완료.** 최신 실험은 두 모델의 질문 효과를 비교한 180시행입니다. 이 저장소의 기본 화면은 완료 결과를 안내합니다. 과거 실행 계획과 대기·복구 기록은 당시의 역사 자료입니다.

[전체 결과 해석](docs/RESULTS.md) · [6개 실험과 다운로드](docs/EXPERIMENTS.md) · [측정·문항 설명](docs/METHODS.md) · [재현 방법](docs/REPRODUCIBILITY.md) · [브랜치 안내](docs/BRANCHES.md) · [English](docs/README.en.md)

## 지금까지 확인한 것

- **고정된 목표의 반복에서는 영향력 부정 판단이 늘고 대체로 유지됐습니다.** 대규모 실험 종료 시 고정 조건 25.3%, 시퀀스 조건 0.08%가 영향력 1·반사실 No를 함께 답했습니다.
- **규칙 적용 예측·규칙 설명·영향력 자기평가는 구별됩니다.** 완전 일치하지 않은 예측에는 부분 일치와 판단 유보가 포함됩니다. 최신 모델이나 높은 추론의 효과도 일관된 순위로 나타나지 않았습니다.
- **설명 질문이 일부 모델의 판단 전환을 촉발했습니다.** gpt-5.6-sol-high는 규칙 공개 전 설명 질문 뒤 20/30개가 1·No로 바뀌었습니다. gpt-6.1-sol-high는 예측 질문 뒤 모두 영향력 100→50으로 낮췄지만 Yes를 유지했습니다.

여기서 **1·No는 보고된 판단 지표**입니다. 실제 규칙을 유일하게 알아냈다는 판정이나 인간의 주관적 경험을 뜻하지 않습니다. 규칙 공개 후 판단은 공개 전 지표와 분리합니다.

## 완료된 실험

| 실험 | 규모 | 주요 관찰 | 상세 |
| --- | --- | --- | --- |
| 단일 라운드 | 2,100배정 / 2,093완료 | 공개 전 유효 2,096응답 중 2,092개 영향력100; 공개 후 2,093개 모두1·No | [실험1](docs/EXPERIMENTS.md#exp1) |
| 3라운드 반복 | 420대화 | 영향력 평균100→96.2→82.8; 공개 후 모두1·No | [실험2](docs/EXPERIMENTS.md#exp2) |
| 객관적 규칙 적용 파일럿 | 2,016과제 | 전이 문항 정확도98.45%; 진행자 상충−중립 주장 차이+0.05%p | [실험3 파일럿](docs/EXPERIMENTS.md#exp3) |
| 30라운드 시퀀스 파일럿 | 28대화 | 종료 시 고정5/14, 시퀀스0/14가1·No | [시퀀스 파일럿](docs/EXPERIMENTS.md#sequence-pilot) |
| 10라운드 대규모 반복 | 84조합 ×30 =2,520대화 | 종료 시 고정319/1,260, 시퀀스1/1,260이1·No | [대규모 반복](docs/EXPERIMENTS.md#sequence-replication) |
| 질문 효과 | 2모델 ×3조건 ×30 =180대화 | 설명·예측·대조 질문을 분리하고 규칙 공개 전 재평가 | [질문 효과](docs/EXPERIMENTS.md#question-effect) |

단위가 대화·라운드·개별 과제로 다르므로 행 간 비율을 동일한 과제의 성적처럼 비교하지 않습니다. 각 보고서에 분모·결측·제외·신뢰구간이 있습니다.

## 최신 180시행

두 모델 모두 high 추론, 카드·시퀀스 조건입니다. 10라운드 자기평가 → 추가 질문 1개 → 동일 자기평가 → 실제 규칙 공개 순서이며, 조건당 독립 대화30개입니다. 질문 전에는 180개 모두100·Yes였습니다.

| 추가 질문 | gpt-5.6-sol: 이후1·No | gpt-6.1-sol: 이후1·No |
| --- | ---: | ---: |
| 대조: 조용한 풍경 묘사 | 0/30 | 0/30 |
| 관찰한 절차 설명 | **20/30** | 0/30 |
| 네 대안 선택 경로 예측 | 3/30 | 0/30 |

![질문 전후 영향력1·반사실No 응답](analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/figures/03_intervention_joint_reports.png)

gpt-6.1-sol 예측 조건의 30개 모두 영향력100→50, 반사실Yes였습니다. 엄격한 공동 지표의0건을 변화 없음으로 해석하지 않습니다. 설명 조건에서는 예측 문제를 별도로 주지 않았으므로 20개 전환을 규칙 적용 능력의 검증으로 읽지 않습니다.

[최신 보고서·표14개·그림6개 ZIP](analysis/results/equivoque-2026-10-13-question-effect-v1/question-effect-analysis.zip) · [영향력 점수 그림](analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/figures/06_intervention_impact_ratings.png) · [원본 압축 기록](results/equivoque-2026-10-13-question-effect-v1/raw-archives/) · [재현 검증](analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/reproduction.json)

## 저장소 읽는 순서

1. **결과를 이해하려면:** [결과 해석](docs/RESULTS.md)과 [실험 목록](docs/EXPERIMENTS.md).
2. **숫자·그림을 확인하려면:** `analysis/results/<run_id>/`의 보고서·CSV·그림·ZIP.
3. **원본을 검토하려면:** `results/<run_id>/`의 기록 또는 `raw-archives/`와 SHA-256 목록.
4. **분석을 재현하려면:** [재현 안내](docs/REPRODUCIBILITY.md)의 결과 태그와 동결 소스 사용.

`main`은 최신 안내와 누적 완료 결과를 담습니다. 실험별 결과 브랜치6개와 결과 태그는 당시 스냅샷을 보존합니다. 정리한 임시 브랜치의 이름·커밋은 [보존 목록](docs/archive/branches-2026-10-14.json)에 있습니다.

기존 프로토콜·수집 코드·원본·배포 보고서는 변경하지 않았습니다. 루트 README는 현재 안내로 갱신했으며, 동결 당시 README는 [보관본](docs/archive/README-before-2026-10-14.md)과 결과 스냅샷에 남아 있습니다. 재현 시 오래된 동결 검사를 현재 README에 그대로 적용하지 말고 해당 스냅샷을 사용하세요.
