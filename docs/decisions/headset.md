# 결정: XR 헤드셋 (A0-07)

- 상태: **미확보, 구매 예정** (창업자 답변, 2026-11-10). 기종과 구매 날짜는 아직 정하지 않았다.
- 결정권자: 창업자. 기록: omp.

## 후보

| 기종 | 브라우저 | WebXR 몰입 세션 | WebXR 손 추적 | 출처 |
|---|---|---|---|---|
| Meta Quest 3 / 3S | Meta Quest Browser | 지원 | 지원(WebXR Hand Input) | [Meta: WebXR Hands](https://developers.meta.com/horizon/documentation/web/webxr-hands) |
| Apple Vision Pro | Safari (visionOS 2 이상) | 지원 | 시선·손가락 집기 기반 "natural input"; 관절 단위 손 추적의 노출 범위는 [확인 필요] | [WWDC24 WebXR](https://developer.apple.com/videos/play/wwdc2024/10066), [WebKit: Natural Input for WebXR](https://webkit.org/blog/15162/introducing-natural-input-for-webxr-in-apple-vision-pro/) |
| Android XR (예: Galaxy XR) | Chrome | 지원 | [확인 필요] | [WebXR 브라우저 목록](https://sparksbud.com/guides/webxr-browsers/) (2차 출처) |

**권고 [추정]:** Meta Quest 3 계열. WebXR 손 추적이 문서화돼 있고, S1 XR 범위(잡기·놓기·회전·스냅, 손목 팔레트)가 관절 단위 손 입력에 기대기 때문이다. 가격과 구매 시점은 창업자가 정한다.

## 헤드셋이 오기 전의 개발 경로

- WebXR 에뮬레이터(브라우저 확장 또는 `@pmndrs/xr` 개발 모드)로 개발한다. 실기에서만 보이는 것(손 추적 지연, 프레임률, 시야 내 판독성)은 증명되지 않는다.
- **자원 수칙(창업자 지시):** 에뮬레이터와 3D 런타임은 메모리를 많이 쓴다. 무거운 실행 전에 스왑 사용량과 SSD 여유를 확인하고, 여유가 부족하면 실행하지 않는다. 구체 문턱은 개발 자원 가드 이슈에서 정한다.

## 위험

- **XR-07a(#223) 실기 시험을 막는다.** 헤드셋이 S1 10~11주 전에 오지 않으면 XR 완성은 에뮬레이터 기준으로만 증명되고, 이 사실을 S1 Go 판정(V-05)에 그대로 적는다.
- 기종을 늦게 정하면 Vision Pro와 Quest의 입력 모델 차이(관절 손 추적 대 시선·집기)를 S1 설계에 반영하지 못한다. 기종은 XR 에픽 착수(S1 10주) 4주 전까지 정하는 것을 권한다 [제안].
