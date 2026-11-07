# 실험 7: 다른 VM에 넘길 실행 안내

2026-11-07. 이 문서는 이미 동결된 실험 7 v2에 운영·원본 백업 프로그램을 덧붙여 다른 VM에서 실행하는 안내다. 기존 v1/v2 코드·프롬프트·배정·분석 계약을 바꾸지 않는다. 백업 프로그램은 별도 `exp7_backup_v1`에 있고, 모델 호출은 기존 v2 worker가 수행한다.

## 새 VM에 그대로 붙여 넣을 지시문

```text
이 VM에서 실험 7 v2의 worker 하나를 실행해줘.

먼저 아래 최신 인계 문서를 읽고 그대로 진행해.
https://github.com/dasnidm/llm-equivoque-experiments/blob/experiment/exp7-main-v2-2026-11-07/docs/EXP7_MULTI_VM_HANDOFF.ko.md

전체 과거 레포를 추가 clone하지 말고, 문서의 exp7-main-v2-with-backup.tar.gz와
BACKUP_SHA256SUMS를 받아 검증해. 이 묶음은 동결 실험 코드와 별도 백업 실행기를 포함해.
동결 파일 해시·Codex CLI 버전·의존성, Codex 인증과 두 GitHub 저장소의 권한을 확인해.
원본 저장소 dasnidm/llm-equivoque-exp7-raw가 실제로 비공개이고 쓰기 가능한지 확인해.
저장소가 없거나 인증/권한이 안 되면 독립적으로 가능한 준비를 마치고 필요한 조치를 알려줘.
인증 토큰을 채팅이나 Git에 넣거나 다른 VM에서 복사하지 마.

실행은 python -m exp7_backup_v1.launch를 사용하고,
--model auto --concurrency 1과 /workspace/work/exp7-main-v2-worker를 사용해.
auto는 공통 GitHub 작업판에서 아직 담당자가 없는 모델 하나를 원자적으로 선점해.
실행 전에 해당 work-dir의 기존 identity·PID·잠금을 확인해 중복 worker를 만들지 마.
이미 배정된 모델이나 실행 중인 작업을 가져오지 마.

백그라운드 supervisor를 실행해 prepare가 성공했을 때만 run으로 이어가게 해.
PID와 로그 위치를 기록하고, 모델 선점 및 기술 점검 진행까지 실제로 확인해.
worker의 공개 결과 게시와 별도 비공개 원본 백업을 각각 확인해.
실패 대화 재시도, 완료 작업 재실행, STOP 해제, 코드·모델·추론·동시성 변경은 하지 마.
오류가 나면 원본과 작업 소유권을 보존하고 상태·원인을 보고해.
완료했다고 말하기 전에 실제 프로세스·원격 작업판·백업 상태를 확인해.
```

위 지시문은 **새 VM 하나에 한 번씩** 사용한다. 이미 실행 중인 Astra 환경에 새 launcher를 추가로 띄우지 않는다. 그 환경의 원본 백업은 기존 worker를 유지한 채 백업 프로그램만 연결한다.

## 저장소와 현황판

| 역할 | 위치 | 공개 범위 |
|---|---|---|
| 동결 코드·배포·연구 결과 | `dasnidm/llm-equivoque-experiments` | 공개 |
| 원본 tar.gz·파일별 검증 색인 | `dasnidm/llm-equivoque-exp7-raw` | **비공개여야 함** |
| 전체 작업 현황 | [공통 현황판](https://github.com/dasnidm/llm-equivoque-experiments/tree/exp7/main-v2-coordination) | 공개 |
| 배포 묶음 | [배포 브랜치](https://github.com/dasnidm/llm-equivoque-experiments/tree/exp7/main-v2-distribution) | 공개 |

원본 저장소의 존재·비공개 설정·실제 쓰기 권한은 각 VM의 `check`와 launcher 사전 검사로 확인한다. 문서에 저장소 이름이 있다고 생성·인증·업로드가 완료됐다고 가정하지 않는다. 저장소 생성 권한이 없는 VM에서 비공개 요구를 해제하거나 공개 저장소로 대체하지 않는다.

전체 배정은 **77,856대화, 2,600작업**이다. 모델 하나는 **9,732대화, 325작업**이며 마지막 작업은12대화, 나머지는30대화다. 현재 초기 운영 설정은 Astra 환경이3동시, 추가7개 환경은 각각1동시로 **전역 예약 상한10** 안에서 진행한다. 이는 VM당10개 또는 전체80개가 허용됐다는 뜻이 아니다.

작업판의 `미시작·미보고`에는 아직 작업 결과가 게시되지 않은 실행 중 대화도 포함된다. `완료0`이어도 기술 점검이나 첫 작업이 진행 중일 수 있다. 기술 점검18대화·최대612호출은 본실험 집계와 별도다. 모델별 담당자와 실행 작업 상태를 함께 확인한다. 예약 병렬 수는 그 순간 실제 요청 수와 다르다.

공통 작업판의 완료는 **공개 연구 결과 게시와 완료 기록 확인**을 뜻한다. 비공개 원본 백업 완료는 각 VM의 `backup-v1` 상태·원격 확인 증명으로 따로 판단한다. 공개 작업판 숫자만 보고 원본까지 외부 보관됐다고 해석하지 않는다.

## 다운로드와 검증

다음은 새 VM에서의 명령이다. 이미 같은 작업 디렉터리나 실행 프로세스가 있다면 먼저 기존 상태를 확인하고 이어서 사용한다. 기존 동결 파일이나 진행 중인 work-dir을 덮어쓰지 않는다.

```bash
mkdir -p /workspace/work/exp7-v2-handoff
cd /workspace/work/exp7-v2-handoff
curl --fail --location https://raw.githubusercontent.com/dasnidm/llm-equivoque-experiments/refs/heads/exp7/main-v2-distribution/exp7-main-v2-with-backup.tar.gz --output exp7-main-v2-with-backup.tar.gz
curl --fail --location https://raw.githubusercontent.com/dasnidm/llm-equivoque-experiments/refs/heads/exp7/main-v2-distribution/BACKUP_SHA256SUMS --output BACKUP_SHA256SUMS
sha256sum -c BACKUP_SHA256SUMS
test ! -e exp7-main-v2
tar -xzf exp7-main-v2-with-backup.tar.gz
cd exp7-main-v2
python -m pip install -r exp7_main/requirements.txt
python -m exp7_main_v2.worker verify \
  --freeze manifests/equivoque-2026-11-07-exp7-main-v2/freeze.json
```

각 단계가 성공했을 때만 다음 단계를 진행한다. HTTP404라면 새 묶음 게시가 아직 완료되지 않은 것이다. 오래된 백업 미포함 묶음으로 바꿔 원본 백업 검사를 생략하지 않는다. 이 배포 묶음은 코드와 계획 자료이며 provider 원본 로그·인증 자료를 포함하면 안 된다.

동결 CLI는 **`codex-cli 0.159.0-alpha.3`**, 판독 의존성은 **`jsonschema==4.26.0`**이다. `verify`가 실패하면 자동으로 해시나 버전을 바꾸지 않고 원인을 확인한다. 동결 파일의 CLI 버전이 실제 기준이며 다른 버전의 결과를 같은 실행으로 섞지 않는다.

## 인증과 저장소 사전 검사

```bash
codex login status
gh auth status
gh repo view dasnidm/llm-equivoque-experiments --json nameWithOwner,viewerPermission
python -m exp7_backup_v1 check --repository dasnidm/llm-equivoque-exp7-raw
```

공개 실험 저장소에 push할 수 있어야 하고, 원본 저장소는 비공개·쓰기 가능 상태여야 한다. 공개 저장소를 읽을 수 있다는 사실만으로 push 권한이 확인되지는 않는다. 인증 표시가 있더라도 실제 호출에서401이 나오면 그 환경의 재인증이 필요할 수 있다.

Codex 재인증이 필요하면 해당 VM에서 `codex login --device-auth`를 실행하고 사용자에게 로그인 안내를 전달한다. GitHub 인증이 필요하면 그 환경의 연결 또는 `gh auth login` 절차를 사용한다. 비밀 토큰을 채팅으로 요청하거나 파일 내용을 출력하지 않는다. 공용 Codex SQLite·인증 파일·다른 작업의 rollout은 원본 백업 대상이 아니다.

## 한 번의 launcher로 기술 점검과 본실험 연결

다음 foreground 명령은 동작 확인용이다. 장시간 실행은 다음 절의 background 방법으로 **둘 중 하나만** 시작한다.

```bash
python -m exp7_backup_v1.launch \
  --freeze manifests/equivoque-2026-11-07-exp7-main-v2/freeze.json \
  --work-dir /workspace/work/exp7-main-v2-worker \
  --repository dasnidm/llm-equivoque-exp7-raw \
  --model auto \
  --concurrency 1
```

launcher는 사전 검사를 수행하고 백업 프로그램을 연결한다. `prepare`가 통과해야 같은 work-dir·모델 소유권으로 `run`에 진입한다. worker와 launcher의 잠금 및 `identity.private.json`은 재시작 후에도 보존한다.

`--model auto`는 최초 실행에서 빈 모델 하나를 고르는 옵션이다. 한번 모델이 배정되면 같은 work-dir은 그 모델에 고정된다. 모든 모델에 담당자가 있거나 전역 용량이 부족하거나 STOP 상태면 새 호출을 시작하지 않는다. 이때 다른 VM의 소유권을 지우거나 별도 work-dir을 만들어 다시 선점하지 않는다.

본실험이 시작되면 그 모델의 다음 미배정 작업을 순서대로 가져와 최대325작업까지 계속한다. 모델 하나의 작업을 마쳤다고 다른 VM에 배정된 모델로 자동 이동하지 않는다. 새 VM의 병렬 수는1이며, 각 VM에10개 또는24개를 띄우는 실행 안내가 아니다.

## background 실행과 확인

동결 묶음의 `exp7-main-v2` 디렉터리에서 실행한다. Python은 caller와 같은 환경·인터프리터를 사용하며 stdin을 닫고 새 세션으로 분리한다. 인증이 필요한 상태를 background로 숨기지 않도록 사전 검사를 먼저 마친다.

```python
import json
import os
from pathlib import Path
import subprocess
import sys

source = Path.cwd().resolve()
work = Path('/workspace/work/exp7-main-v2-worker')
work.mkdir(parents=True, exist_ok=True)
pid_file = work / 'launcher-pid.private.json'
if pid_file.exists():
    old = json.loads(pid_file.read_text())
    try:
        os.kill(int(old['pid']), 0)
    except ProcessLookupError:
        pass
    else:
        raise RuntimeError('Existing launcher PID is alive; inspect it instead of launching another.')

command = [
    sys.executable, '-m', 'exp7_backup_v1.launch',
    '--freeze', 'manifests/equivoque-2026-11-07-exp7-main-v2/freeze.json',
    '--work-dir', str(work),
    '--repository', 'dasnidm/llm-equivoque-exp7-raw',
    '--model', 'auto', '--concurrency', '1',
]
with (work / 'launcher.log').open('ab', buffering=0) as log:
    process = subprocess.Popen(command, cwd=source, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT,
                               start_new_session=True)
pid_file.write_text(json.dumps({'pid': process.pid, 'source': str(source)}, indent=2))
os.chmod(pid_file, 0o600)
print({'pid': process.pid, 'log': str(work / 'launcher.log')})
```

PID 파일 생성은 정상 가동의 증거가 아니다. 직후 launcher 로그·프로세스 생존·`launch-v1` 상태를 확인하고, 공통 작업판에서 모델 담당자가 기록됐는지 확인한다. 기술 점검이 시작됐는지, 통과 후 첫 본실험 작업이 시작됐는지도 확인한다. 백그라운드 프로세스는 VM 종료·삭제 후까지 실행을 보장하지 않는다.

## 비공개 백업만 연결하거나 확인하기

이미 실행 중인 worker에는 launcher를 중복 실행하지 않는다. 같은 work-dir에 백업 프로그램 하나만 연결할 때는 다음 명령을 사용한다.

```bash
python -m exp7_backup_v1 watch \
  --work-dir /workspace/work/exp7-main-v2-worker \
  --repository dasnidm/llm-equivoque-exp7-raw \
  --interval 60
```

한 번만 확인·동기화하려면 `watch` 대신 `once`를 쓰고 `--interval`은 제외한다. 실제 Astra 환경은 위 예시 경로와 다를 수 있으므로 해당 worker가 사용 중인 정확한 work-dir을 사용한다. launcher가 이미 백업 프로그램을 실행했다면 별도 `watch`를 추가하지 않는다.

백업 상태와 확인 증명은 같은 work-dir의 `backup-v1` 아래에 남는다. 완료·검증된 작업별 아카이브와 색인만 대상이며, 진행 중인 raw 디렉터리나 인증·공용 DB를 통째로 올리지 않는다. 업로드 실패 시 로컬 아카이브를 보존하고 백업 미완료로 보고한다. 로컬 압축 성공과 원격 백업 성공은 구분한다.

**시작 전 원본 저장소 검사 실패는 새 worker 시작을 막는다. 실행 중 업로드 실패는 로컬 아카이브를 보존하고 다음 동기화에서 재확인하지만, 그 자체로 공통 STOP을 설정하거나 실행 중인 worker를 종료하지 않는다.** launcher는 기술 점검에서 본실험으로 넘어갈 때 백업 프로세스의 생존을 확인한다. 이후 백업이 지연되는 동안 본실험이 계속될 수 있으며 기존 디스크·inode 가드는 유지된다. 따라서 원격 백업 지연은 별도로 감시해야 한다. 이 재확인은 백업 전송에 한하며 모델 대화 재실행을 뜻하지 않는다.

## 장애·중단 시

- 기술 점검 실패 시 본실험으로 넘어가지 않는다. 실패한 점검 기록을 지우거나 같은 대화를 자동 재시도하지 않는다.
- 401·429·저장 여유 부족·작업 소유권 불일치·불확실한 요청은 worker의 중단 규약을 따른다. 다른 VM이 STOP을 임의로 해제하지 않는다.
- 원본 백업 실패는 `backup-v1` 상태와 로그로 확인하고 로컬 아카이브를 유지한다. 이미 전송한 모델 요청이 소급 취소된다고 가정하지 않는다.
- `failed`, `interrupted`, `blocked`, pending 상태를 `open`으로 되돌리거나 완료 파일을 삭제해 다시 실행하지 않는다.
- 배정된 모델·work-dir·owner·병렬 수를 보존한다. 같은 work-dir의 작업이 안전하게 재개 가능한지는 원격 선점과 로컬 요청 원장을 함께 확인한다.
- VM을 삭제하거나 디스크를 초기화하기 전에 모든 원본 백업의 원격 확인 증명을 점검한다. 코드 저장소의 완료 숫자만으로 이 조건을 대신하지 않는다.

종료 보고에는 모델·담당자·기술 점검 상태·본실험 작업 상태·공개 결과 게시 상태·비공개 원본 백업 상태·남은 장애를 구분한다. 토큰·provider 세션 ID·전체 원시 진단 로그를 공개 채팅이나 공개 현황판에 붙이지 않는다.

## 참조

- [동결 v2 실행·보관 안내](../exp7_main_v2/README.md)
- [저장 위험과 개선 근거](EXP7_STORAGE_REVIEW.ko.md)
- [공통 작업 현황판](https://github.com/dasnidm/llm-equivoque-experiments/tree/exp7/main-v2-coordination)

이 인계 문서는 운영 추가분이다. 본실험의 과학적 기준이나 이미 동결된 파일을 수정하는 지침이 아니다.
