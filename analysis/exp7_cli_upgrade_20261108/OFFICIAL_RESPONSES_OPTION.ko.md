# 추가로 확인한 공식 ChatGPT 구독 연동 경로

공식 문서는 사용자가 별도의 오픈소스 도구에 ChatGPT 사용 권한을 부여한 뒤
**공개 `https://api.openai.com/v1/responses`**를 호출하는 OAuth 흐름을 제공한다.
별도의 유료 API 키나 partner API key가 필수인 방식은 아니다.
`dynamic_agent_client`로 첫 등록을 시작하고, 사용자가 승인한 실제 도구 이름과
발급된 client ID를 보존한다. 기존 Codex 인증 파일에서 토큰을 꺼내 다른
클라이언트에 복제하는 방식으로 구현하지 않는다.

공식 문서:

- [등록과 로그인](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [모델 조회와 추론](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [app-server 설정](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server)
- [제약사항](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)

## 우리 실험에 적용하는 두 방식

1. **app-server 유지:** 공식 custom provider 설정으로 공개 Responses API에
   연결한다. 한 시행의 프로세스·thread와 34턴 구조를 유지할 수 있다.
   이 경로의 문서 예시는 HTTP/SSE를 쓰고 `supports_websockets=false`로 설정한다.
   기존 Codex backend 경로와 구별한 새 실행 프로필이 필요하다.
2. **직접 Responses 사용:** 연구용 클라이언트에서 실험 지침, 대화 이력,
   스키마와 effort만 전송한다. CLI가 추가하는 도구 설명 및 에이전트 환경
   문구를 제거할 수 있어, 실험 입력을 더 간단하게 통제하고 HTTP 상태·오류
   본문·허용된 rate-limit header를 직접 보존할 수 있다.

두 방식 모두 `store=false`, `stream=true`가 요구된다. HTTP에서는
`previous_response_id`와 영구 서버 대화 저장에 기대지 않고 필요한 이력을
매번 전송해야 한다. 직접 클라이언트의 자동 retry는 0으로 두고,
`response.completed`까지 읽어야 성공이다. 중간에 스트림이 끝나거나
`response.failed`가 나오면 미확정/실패로 보존한다. 모델 목록은 실제
OAuth 계정으로 다시 조회해야 하며 기존 catalog만으로 8모델 접근을 단정하지 않는다.

## 현재 검증 수준

이 경로의 **존재와 설정 요건은 공식 문서에서 확인**했다. 우리 실험 도구로
별도 OAuth 등록·사용자 승인을 받지 않았으므로 실제 모델 호출, 처리량,
8모델 접근 권한은 아직 검증하지 않았다. 기존 인증을 복제하거나 추가 요금이
발생하는 paid API/Fast tier를 임의로 켜지 않았다.

**같은 구독의 허용량을 사용하는 공식 연동이며, 계정 제한을 없애는 방법이 아니다.**
공개 paid API 문서의 RPM/TPM 표를 이 구독 OAuth 경로의 보장량으로 적용할 수 없다.
따라서 이 경로가 2~3일 완료를 가능하게 한다고 아직 결론 낼 수 없다.
다만 CLI/backend 경로의 문제를 분리하고, 불필요한 도구 입력을 줄이며,
429를 훨씬 구체적으로 기록하는 추가 비교 대상으로 적합하다.
