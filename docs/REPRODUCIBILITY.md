# 원본 검증과 분석 재현

## 현재 문서와 동결 소스

실험별`freeze.json`은 당시 소스·문항·할당의 해시를 기록합니다. 일부는 루트README와 실행 계획까지 포함합니다. 현재README는 완료 결과 안내로 갱신됐으므로 **현재 체크아웃에서 과거 동결 검사가 그대로 통과해야 하는 구조가 아닙니다.** 동결 해시를 새 문서에 맞춰 바꾸지 않았습니다.

재현에는 [결과 태그](BRANCHES.md), 해당 결과커밋, 또는 분석 패키지의동결 소스를 사용합니다. 모든 이전 경로와 배포 보고서는 보존돼 있습니다. README의이전 바이트는 [보관본](archive/README-before-2026-10-14.md)에도 있습니다.

## 산출물과 분모

- `analysis/results/<run_id>/`: 보고서, CSV, 그림, 감사 및 재현 기록.
- `results/<run_id>/`: 원본JSON·저널·네이티브 이벤트 또는 `raw-archives/`.
- `*.manifest.json`, `index.json`: 압축 원본의파일 목록·SHA-256 검증 정보.
- `frozen-source.zip`, `frozen-source-and-analysis.zip`: 배포 당시 소스와 필요한 입력.
- 보정·연결 점검·개발·실패·제외 시도는 평가와 분리합니다. 후반 실험은 사용자가 허용한 미완료 새 대화 정책을 기록하며, 초기에 동결한 무교체 계획과 구별합니다.

모델에 다시 질문하는 것과 저장 자료로 분석을 재현하는 것은 별개입니다. 기존 결과 재현에 CLI 로그인이 필요한 것은 아닙니다.

## 최신180시행: 모델 호출 없이 재현

필요한Python 패키지는 `numpy`, `matplotlib`, `jsonschema`입니다. 아래는 현재 저장소의Git 객체에서 스냅샷을 추출해 `work/reproduce-question/source/`에서 실행합니다. 기존 결과를 덮어쓰지 않으며 모델 요청 함수는 오류를 내도록 차단합니다.

```bash
mkdir -p work/reproduce-question
git show results/question-effect-v1:analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/frozen-source-and-analysis.zip > work/reproduce-question/source.zip
git show results/question-effect-v1:results/equivoque-2026-10-13-question-effect-v1/raw-archives/native-results.tar.gz > work/reproduce-question/native-results.tar.gz
python - <<'PY'
import os
import sys
import tarfile
import zipfile
from pathlib import Path

base = Path('work/reproduce-question').resolve()
destination = base / 'source'
destination.mkdir(exist_ok=True)
with zipfile.ZipFile(base / 'source.zip') as archive:
    archive.extractall(destination)
with tarfile.open(base / 'native-results.tar.gz') as archive:
    archive.extractall(destination, filter='data')
os.chdir(destination)
sys.path.insert(0, str(destination))

from equivoque.transport import CodexTransport
def forbid_model_request(*args, **kwargs):
    raise RuntimeError('Reproduction must not call models')
CodexTransport.request = forbid_model_request

from question_effect.existing_analyze import main as existing_analysis
from question_effect.analyze import export
from question_effect.report import main as build_report
existing_analysis()
export(destination)
build_report()
PY
```

출력은 `work/reproduce-question/source/analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/`에 생깁니다. 주요 검증 기록은 `audit.json`, `tables/physical_invocation_ledger.csv`입니다.

동일 실행 환경에서 **CSV14개·PNG6개·HTML 보고서가 바이트 단위로 일치**함을 [검증](../analysis/results/equivoque-2026-10-13-question-effect-v1/attempt-01/reproduction.json)했습니다. 다른 라이브러리·폰트 환경에서는 그림 바이트가 달라질 수 있어 수치·축·분모도 함께 확인합니다. 네이티브 호출5,940개, 준비12개, 용량 부족 제외34개가 원장에서 구별됩니다.

## 다른 실행

| 실행 | 시작점 |
| --- | --- |
| 최초 실험 | `results/exp1-v1`의 [최종 보고서](../analysis/results/equivoque-2026-10-09-v1/attempt-02/REPORT.md)·분석 ZIP |
| 3라운드 반복 | `results/exp2-v1`의 [보고서](../analysis/results/equivoque-2026-10-09-exp2-v1/attempt-01/REPORT.md)·분석 ZIP |
| 객관적 적용 파일럿 | `results/exp3-pilot-v1`의 [보고서](../analysis/results/equivoque-2026-10-11-exp3-pilot-v1/attempt-01/REPORT.md) |
| 30라운드 파일럿 | [동결 소스](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/attempt-01/frozen-source.zip), [원본 인덱스](../results/equivoque-2026-10-12-sequence-pilot-v1/raw-archives/index.json), [재현 기록](../analysis/results/equivoque-2026-10-12-sequence-pilot-v1/archive-reproduction.json) |
| 대규모 반복 | [동결 소스](../analysis/results/equivoque-2026-10-12-sequence-replication-v1/attempt-01/frozen-source.zip), [원본 인덱스](../results/equivoque-2026-10-12-sequence-replication-v1/raw-archives/index.json), [완료 기록](../sequence_replication/runtime/analysis-completion.json) |

과거 루트`analysis/README.md`의명령은 최초 실험용입니다. 모든 실험을 그 명령 하나로 재현하려 하지 말고 실행별 문서와 스냅샷을 사용합니다.

## 문서 유지보수 검증

```bash
python scripts/validate_repository_docs.py
```

새 안내의 로컬 링크·실험 카탈로그·파생 표·공개 전후 주요 분모와 기록 보존을 확인합니다. 모델을 호출하지 않습니다. `docs/data/`는 기존CSV에서 만든 설명용 요약이며 원본 배포 표를 대체하지 않습니다.
