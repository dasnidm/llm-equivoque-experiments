# 첫 안정판 실행 뒤의 기술점검 변경

첫 실서버 안정판 stage `stable-b1-rpm80-p4`에서 429가 아닌 로컬 오류
`failed to initialize sqlite state runtime` 및 BrokenPipe가 관측됐다.
성공 1턴 이후 stage를 중단했다. 기존 실패·중단·pending checkpoint를
보존하며 이 시행들을 재개하거나 같은 trial ID로 대체하지 않는다.

업그레이드 전 snapshot과 비교하면 공유 state DB에는 migration 59~62,
thread history DB에는 migration 8이 새로 적용돼 있다. 동시 초기화 또는
다른 버전과의 공유가 원인일 수 있지만, 실패 메시지만으로 락 경합을 확정하지 않는다.
OOM 기록은 0이다. 공유 원본 DB를 되돌리거나 인증을 복제하지 않는다.

공식 CLI 소스는 기존 버전과 최신 안정판 모두에서 `CODEX_SQLITE_HOME`을
지원한다. 인증·설정이 있는 `CODEX_HOME`을 그대로 쓰고, 자식 프로세스의
SQLite 위치만 stage별 별도 디렉터리로 지정한다. pool 시작 전 한 프로세스에서
`initialize`/`initialized`만 수행하여 migration을 마친다. 이 단계에는
`thread/start`나 `turn/start` 및 실제 모델 요청이 없다.

이 변경은 새로운 기술점검 프로필로 남긴다. 기존 → 안정판 → 시험판 →
안정판 → 기존의 비교를 새 stage ID와 동일한 DB 격리 조건으로 수행한다.
각 stage의 원본 RPC, SQLite snapshot, shim 소스와 hash를 보존한다.
기존 본실험 STOP과 freeze는 변경하지 않는다.

버전 간 로컬 모델 입력 비교에서는 시스템 지침, 개발자 텍스트, 사용자
환경/질문 텍스트가 일치했지만 `additional_tools`의 도구 설명과 일부
도구 목록이 달랐다. 따라서 이후 속도 비교는 버전 업그레이드의 전체 효과를
측정하며, 모델이 보는 전체 입력을 고정한 순수 바이너리 효과라고 해석하지 않는다.
