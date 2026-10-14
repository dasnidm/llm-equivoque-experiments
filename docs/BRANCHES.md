# 브랜치와 결과 보존

## 현재 구조

`main`에서 현재 설명과6개 완료 결과를 찾습니다. 결과 스냅샷 브랜치는 기존 링크와 당시 소스를 보존하기 위해 유지합니다. 완료된 결과 브랜치를 새 실험용으로 재사용하지 않습니다.

| 결과 | 보존 브랜치 | 결과 태그 |
| --- | --- | --- |
| 최초 실험 | `integration/equivoque-2026-10-09-v1` | `results/exp1-v1` |
| 3라운드 반복 | `integration/equivoque-2026-10-09-exp2-v1` | `results/exp2-v1` |
| 객관적 적용 파일럿 | `integration/equivoque-2026-10-11-exp3-pilot-v1` | `results/exp3-pilot-v1` |
| 30라운드 파일럿 | `integration/equivoque-2026-10-12-sequence-pilot-v1` | `results/sequence-pilot-v1` |
| 대규모 반복 | `integration/equivoque-2026-10-12-sequence-replication-v1` | `results/sequence-replication-v1` |
| 질문 효과 | `experiment/equivoque-2026-10-13-question-effect-v1` | `results/question-effect-v1` |

새 변경은 현재`main`에서 짧은 작업 브랜치를 만들고, 새 실험은 별도의run ID·설계·기록을 둡니다. 결과 태그는 당시 스냅샷이며 이동시키지 않습니다.

## 2026-10-14 정리

원격99브랜치에서 **main+결과6개 =7개**를 유지하고, 완료된 임시92개를 정리합니다.

| 임시 종류 | 수 | 보존 |
| --- | ---: | --- |
| worker | 87 | 최신 결과 및main의 병합 이력에서 도달 가능 |
| preparation | 3 | 동일 |
| planning | 1 | 동일 |
| snapshot | 1 | 독립 이력이므로 `archive/2026-10-14/snapshot-live-01` 태그로 보존 |

삭제 전의 모든 이름과 정확한 커밋은 [브랜치 목록 JSON](archive/branches-2026-10-14.json)에 있습니다. 결과 브랜치6개는 그대로 남겨 이전 채팅과 보고서의 링크를 유지합니다. 커밋을 재작성하거나 원본 자료를 삭제하는 정리는 하지 않습니다. 로컬 작업 디렉터리와 작업 중 파일도 보존합니다.

과거 검토 초안 PR [35](https://github.com/dasnidm/llm-equivoque-experiments/pull/35), [56](https://github.com/dasnidm/llm-equivoque-experiments/pull/56), [97](https://github.com/dasnidm/llm-equivoque-experiments/pull/97), [158](https://github.com/dasnidm/llm-equivoque-experiments/pull/158)은 완료 결과가main에 포함된 후 열린 대기 상태를 정리합니다. 실제 병합 여부와 종료 상태는 각 PR 기록을 기준으로 읽으며, 종료를 별도 실험 검증으로 취급하지 않습니다.

## 과거 브랜치 복원

목록의커밋 SHA에서 로컬 브랜치를 다시 만들 수 있습니다.

```bash
git switch -c recovered-worker <목록의-commit-sha>
```

별도 스냅샷은 다음처럼 확인합니다.

```bash
git show archive/2026-10-14/snapshot-live-01
```

과거 결과를 읽기만 하려면 [결과 태그](EXPERIMENTS.md)나 해당커밋의GitHub 화면을 사용하면 됩니다.
