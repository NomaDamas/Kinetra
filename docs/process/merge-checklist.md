# 머지 체크리스트

머지는 omp가 한다. 아래를 모두 확인한 PR만 squash 머지한다.

1. PR 본문이 템플릿 순서(대목표 → 핵심 가치 → 문제 `Closes #N`)를 지킨다. `pr-body` 체크가 초록이다.
2. CI(`engine`, `web`, `assets`, `pr-body`)가 모두 초록이다.
3. Sol 리뷰 코멘트가 있고, 모든 지적에 수용·기각·이월 판정이 기록됐다(`triage.md`).
4. "100% 완료" 8항목(`done-definition.md`)이 PR 본문에서 하나씩 대조됐다.
5. 창업자 승인 대상(`review-rubric.md`)이면 승인 코멘트가 있다.
6. squash 머지만 쓴다. main에 직접 푸시하지 않는다.
