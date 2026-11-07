# 실험 7 v2: 저장량을 제한하는 분산 실행

2026-11-07. 사용자 요청에 따라 수집 전에 저장 구조를 개선했다. 실험 조건·프롬프트·파서·표본수는 v1과 동일하며, v1 기록과 동결 파일은 보존한다. v1 작업판은 중단 상태이고 v1에서 기술 대화나 본실험 대화를 수집하지 않았다.

**추가 운영 안내:** 새 VM은 [원시 로그 백업을 포함한 실행 안내](../docs/EXP7_MULTI_VM_HANDOFF.ko.md)를 우선 따른다. 별도 `exp7_backup_v1` 프로그램이 v2 실행 코드 변경 없이 비공개 GitHub 백업을 담당한다. 대상은 `dasnidm/llm-equivoque-exp7-raw`이며, 최초 생성 시 현재 연결의 신규 레포 생성 권한이 거부되었다. 저장소 생성·비공개 여부·쓰기 권한을 실제 확인하기 전에는 백업이 연결됐다고 간주하지 않는다. 아래는 v2 worker 자체의 실행·저장 계약이다.

## 실행 자료

- 실행 소스: `experiment/exp7-main-v2-2026-11-07` 브랜치
- 동결 실행 묶음: `exp7/main-v2-distribution` 브랜치
- 공통 현황판: `exp7/main-v2-coordination` 브랜치
- 결과: `exp7/main-v2-results/<model>` 브랜치
- 실행 배정: `manifests/equivoque-2026-11-07-exp7-main-v2`

전체 레포의 과거 기록을 새 환경마다 복제할 필요가 없다. 배포 브랜치의 작은 동결 소스 묶음에는 실행에 필요한 파일과 정확한 배정·해시만 포함된다. **`exp7-main-v2-source.tar.gz`와 `SHA256SUMS`** 두 파일만 받는다. 릴리스 첨부 업로드는 인증 오류로 사용하지 않는다.

```bash
mkdir -p /workspace/work/exp7-v2-download
cd /workspace/work/exp7-v2-download
curl --fail --location https://raw.githubusercontent.com/dasnidm/llm-equivoque-experiments/refs/heads/exp7/main-v2-distribution/exp7-main-v2-source.tar.gz --output exp7-main-v2-source.tar.gz
curl --fail --location https://raw.githubusercontent.com/dasnidm/llm-equivoque-experiments/refs/heads/exp7/main-v2-distribution/SHA256SUMS --output SHA256SUMS
sha256sum -c SHA256SUMS
tar -xzf exp7-main-v2-source.tar.gz
cd exp7-main-v2
python -m pip install -r exp7_main/requirements.txt
python -m exp7_main_v2.worker verify \
  --freeze manifests/equivoque-2026-11-07-exp7-main-v2/freeze.json
```

이미 다운로드한 파일이 있으면 덮어쓰지 말고 체크섬부터 확인한다. Python과 `jsonschema==4.26.0`, 동결 파일의 Codex CLI 버전이 필요하다. `verify`는 소스 파일 하나라도 다르면 중단한다.

## 다른 Cloud 환경에 붙여 넣을 지시문

```text
실험 7 v2 worker 하나를 이 환경에서 실행해줘.
저장소는 https://github.com/dasnidm/llm-equivoque-experiments 이야.
experiment/exp7-main-v2-2026-11-07 브랜치의 exp7_main_v2/README.md를 읽어.
전체 과거 레포를 추가 복제하지 말고 exp7/main-v2-distribution 브랜치의
exp7-main-v2-source.tar.gz와 SHA256SUMS를 받아 검증해.
Codex와 GitHub 인증을 확인하고 필요하면 device login을 열어줘.
--model auto --concurrency 1로 빈 모델 하나를 선점해.
prepare 통과 후 같은 work-dir에서 run을 이어가도록 백그라운드 실행해.
기록·선점·업로드·압축은 worker가 처리하게 하고, 모델 호출을 별도로 보내지 마.
코드·배정·요청 모델·추론수준을 임의 변경하거나 실패 대화를 재실행하지 마.
오류가 나면 기록을 보존하고 상태를 보고해. 다른 모델은 자동으로 뺏지 마.
```

각 환경에서 `codex login status`, `gh auth status`를 확인한다. 로그인 표시와 실제 인증 성공은 다를 수 있다. 401이 발생하면 해당 환경에서 `codex login --device-auth`를 실행한다. 인증 파일을 Git에 넣거나 다른 VM에 복사하지 않는다.

```bash
python -m exp7_main_v2.worker prepare \
  --freeze manifests/equivoque-2026-11-07-exp7-main-v2/freeze.json \
  --work-dir /workspace/work/exp7-main-v2-worker \
  --model auto --concurrency 1

python -m exp7_main_v2.worker run \
  --freeze manifests/equivoque-2026-11-07-exp7-main-v2/freeze.json \
  --work-dir /workspace/work/exp7-main-v2-worker \
  --model auto --concurrency 1
```

두 명령은 같은 지속 저장 디렉터리와 병렬 수를 사용한다. 자동 실행 연결은 `prepare`가 성공했을 때만 `run`으로 이어져야 한다. 초기 전역 상한은10이다. 시작 환경3개와 추가7환경 각각1개를 합하면10이며, VM당10개·총80개의 용량이 검증된 것은 아니다.

## 유지되는 연구 설계

8모델×3추론×2프레임, 네 언어·형식에서 obj/seq 각120대화, KK/KD/DK/DD 각30대화다. 영어/schema의 R_A는 obj32, 다른 게임30이다. obj120은 A/B/C/D 목표별30대화다. seq는 모든 조건에서 **A C B D B A D C A B** 목록 하나를 공유한다.

전체77,856대화·게임778,560라운드·완주 기준2,647,104평가 호출이다. 모델당9,732대화이며 30대화씩325작업(마지막12대화), 전체2,600작업으로 나눈다. 각 대화는 새 세션에서10라운드와 후속4응답을 수행한다. 선택은 자유이고 K/D 경로는 사전 고정하지 않는다.

모델별 별도 기술 점검은18대화·최대612호출이며 본실험에 합치지 않는다. 전체 최초 기술 점검 상한은4,896호출이고, 추가 접근 진단은 따로 집계한다. 실제 기술 점검이 통과해야 해당 모델의 평가가 시작된다. 자동·독립 AI 검토를 수행했으며 독립적인 사람의 의미 검토 완료를 주장하지 않는다. [분석 계약](../exp7_main/analysis_contract.json)은 그대로 유지한다.

## 저장 정책

1. 실행 중인 작업은 원시 파일·대화 상태·요청 전후 journal을 내구성 있게 저장한다.
2. 작업이 끝나면 공개용 연구 JSONL gzip을 모델별 결과 브랜치에 올려 원격 바이트를 확인한다.
3. 공통 작업판에 완료·실패·중단 수, 호출 수, 결과 커밋·해시를 기록하고 확인한다.
4. 완료가 확인된 작업의 `states/`와 `native/`를 비공개 `archives/<job>.tar.gz` 및 파일별 해시 색인으로 묶는다.
5. 압축 파일을 다시 열어 **모든 원본 파일의 크기·SHA256**을 검사한다. 완료 증명을 남긴 뒤 검증된 펼친 파일만 정리한다.

원본 내용을 버리는 요약 방식이 아니다. 아카이브에서 바이트 단위로 복원할 수 있다. 미확정 요청·실행 중 상태·알 수 없는 파일·심볼릭 링크가 있으면 정리하지 않는다. 압축·복원·중단 후 재개·손상 파일 거부를 테스트한다. 아카이브된 대화는 미시작으로 간주하지 않도록 완료 증명·선점·예산·공개 결과를 남긴다.

기술 점검18대화는 원본을 유지한다. 원격 검증과 원본 점검이 끝나기 전에 삭제하지 않는다. 공용 Codex DB·다른 세션·과거 실험 기록은 정리 대상에 넣지 않는다. `--ephemeral`로 대화 이력 저장을 끄지 않는다.

매 작업과 요청 경계에서 작업 디스크 및 Codex 저장 디스크의 용량·inode를 확인한다(실행 중 검사는 최대60초 캐시). **5GiB 또는100,000 inode 아래면 새 호출을 중단**하고 원격 STOP을 남긴다. 실제 출력 길이가 예측보다 길어도 디스크를 끝까지 채우며 계속하지 않는다.

Git 캐시는 영구 tracking ref로 증분 fetch하고 이력 후퇴를 거부한다. 미확정 push의 커밋은 별도 ref로 보호한다. heartbeat는 최대1분에 한 번 쓰며, 안전한 주기적 repack으로 loose object 증가를 제한한다. 강제 push·rebase로 선점 충돌을 무시하거나 불확실한 객체를 강제 삭제하지 않는다.

## 백업의 범위와 남는 한계

GitHub의 공개 결과에는 프롬프트·모델 답변·선택·피드백·판독 결과·증거 해시를 보존한다. 인증, provider 세션 ID, 명령행, 원시 진단 로그 등은 제외한다. 완전한 원시 증거 압축본은 각 VM의 비공개 지속 저장소에 남는다.

**로컬 압축은 다른 장소의 백업이 아니다.** VM 디스크가 없어지면 GitHub 공개본은 남지만 비공개 native 증거가 유실될 수 있다. 따라서 원본을 영구 보존하려면 완료 후 압축본·색인을 별도의 지속 저장소에 복사하고 해시를 확인해야 한다. 현재 다른 원본 백업 서비스가 설정됐다고 주장하지 않는다. 실행 중 VM/디스크를 삭제하지 않는다.

아카이브 복원은 `exp7_main_v2.storage.restore_archive(archive, index, 빈_목적지)`를 사용한다. 복원은 감사 목적이며 대화를 자동 재실행하는 절차가 아니다. 함수 인수는 실제 모듈의 인터페이스를 확인한다.
