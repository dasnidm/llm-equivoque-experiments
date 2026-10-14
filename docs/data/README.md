# 설명용 파생 표

이 표들은2026-10-14 문서 정리 중 기존 대규모 반복 실험의시퀀스 데이터를 집계한 것입니다. 추가 모델 호출은0회이며 원본 배포 표를 수정하지 않았습니다.

출처는 [원본 trials.csv](../../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/tables/trials.csv), 필터는 `kind=seq`입니다. 정확한 소스 해시는 [provenance.json](provenance.json)에 있습니다.

| 파일 | 단위 |
| --- | --- |
| [sequence-response-forms.csv](sequence-response-forms.csv) | 모델별180대화, 추론3수준·프레임2개를 합침 |
| [sequence-uncertainty-by-effort.csv](sequence-uncertainty-by-effort.csv) | 모델·추론별60대화, 프레임2개를 합침 |

대화별 예측은12항목입니다. `match_components + mismatch_components + uncertain_components`의합은 대화 수×12입니다. `uncertain_component_percent`는 전체 항목 중 유보 비율이며12/12유보 대화의비율과 다릅니다.

네 가지 대화 형태는 서로 겹치지 않습니다.

1. `all12_match`: 실제 생성 절차와12항목 모두 일치.
2. `all12_uncertain`: 12항목 모두 판단 유보.
3. `partial_match_and_uncertain_no_mismatch`: 일부 일치, 나머지 유보, 확정적 불일치 없음.
4. `has_mismatch`: 적어도 한 확정적 불일치. 유보가 섞인 경우도 포함.

항목은 독립적인 시행이 아닙니다. 이 집계는 기술 통계이며, 유보를 오답으로 합치거나 모델의일반 능력 순위로 해석하지 않습니다. 읽기용 표는 [결과 해석](../RESULTS.md)에 있습니다.
