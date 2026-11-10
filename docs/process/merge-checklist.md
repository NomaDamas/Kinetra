# 머지 체크리스트와 브랜치 보호 (P0-07)

머지는 이 목록을 위에서부터 모두 채운 PR만 한다. 하나라도 빠지면 머지하지 않는다(`done-definition.md`). 흐름 전체는 `review-rubric.md`, 지적 처리 양식은 `triage.md`다.

## 머지 전 체크리스트

PR 본문이나 머지 직전 코멘트에 항목마다 확인 근거를 남긴다. 기계가 보는 것은 "CI"로 표시했다.

1. **본문 형식 (CI `pr-body`).** `.github/pull_request_template.md` 순서: 대목표 → 핵심 가치(`values.md` 원문 인용과 "이 PR이 없으면…") → 문제(`Closes #N` 정확히 하나) → 완료 정의 대조 → 범위 밖 → 검증 방법 → 의존성 → 정직성·라이선스 → 디자인 승인본.
2. **필수 CI 초록 (보호 규칙이 강제).** `pytest`(워크플로 `engine`), `web`(워크플로 `web`). 이 둘이 초록이 아니면 GitHub가 머지를 막는다. 아래 "보호 규칙" 참고.
3. **그 밖의 CI 확인.** `ledger`(원장 검사), `pr-body`는 필수로 걸지 않았지만 빨간 채로 머지하지 않는다. 건너뛴 테스트가 늘었으면 이유를 본문에 적는다.
4. **"100% 완료" 8항목** (`done-definition.md`, `issues.yaml`의 `done_definition`). 이슈 DoD 체크박스마다 증거 링크나 실제 출력이 있다.
5. **계획 부합.** DoD 밖 코드가 없다. 대목표·핵심 가치와 변경이 이어진다. 루브릭 1번의 금지 사항을 어기지 않는다.
6. **크기와 WIP.** 생성물·에셋을 뺀 변경이 400줄 이하(넘으면 이유를 본문에 적는다). 진행 중인 잎 3개 이하, 열린 PR 2개 이하.
7. **리뷰와 트리아지.** Sol 리뷰(`openai/gpt-6.1-sol`, reasoning `high`)를 받았고 모든 지적이 `triage.md` 표에서 수용·기각·이월 중 하나로 처리됐다. 리뷰는 최대 2회. 2회 뒤에도 차단(`block`)이 남으면 머지하지 않고 창업자에게 올린다.
8. **창업자 승인.** `triage.md`의 "창업자 승인 대상"에 걸리면 승인 기록(이슈나 PR 코멘트 링크)이 있다. 승인 요청은 `needs-founder` 라벨로 모은다.
9. **의존성.** 선행 이슈가 닫혔다. 뒤따르는 이슈가 이 PR의 가정에 기대면 그 이슈 본문을 고치지 않고 코멘트로 알린다.
10. **머지 방식.** **squash만.** 제목은 `[이슈ID] 제목 (#PR번호)`, 본문은 비워도 된다. 머지 커밋과 리베이스 머지는 저장소 설정에서 꺼져 있다.

## 머지 뒤

1. 이슈가 `Closes #N`으로 닫혔는지 본다. 닫히지 않았으면 증거 링크(머지 커밋, CI 실행)를 적고 닫는다.
2. DoD 밖에서 발견해 `triage.md`에서 이월한 일은 새 이슈로 등록돼 있고 번호가 PR 코멘트에 적혀 있다.
3. 브랜치와 임시 worktree를 지운다(`git worktree remove /tmp/kin-<branch>`; `docs/process/dev-resources.md`가 있으면 정리 절차를 따른다).
4. 다음 잎: 의존성이 풀린 것 중 이번 마일스톤의 P0부터.

## 보호 규칙 (main)

main은 PR로만 들어가고(직접 푸시 금지), 필수 CI가 초록이어야 PR이 들어가고, 머지는 squash만 된다. 아래는 2026-11-10에 `gh api`로 적용한 값 그대로이며 `gh api repos/NomaDamas/Kinetra/branches/main/protection`의 출력으로 확인했다.

### 적용한 설정

저장소(머지 방식):

```
gh api -X PATCH repos/NomaDamas/Kinetra \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false
```

적용 전: `allow_squash_merge=true, allow_merge_commit=true, allow_rebase_merge=true`. 그 밖의 저장소 설정(`delete_branch_on_merge` 등)은 건드리지 않았다.

브랜치 보호(`main`):

```
gh api -X PUT repos/NomaDamas/Kinetra/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {
    "strict": false,
    "checks": [
      {"context": "pytest", "app_id": 15368},
      {"context": "web", "app_id": 15368}
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0, "dismiss_stale_reviews": false, "require_code_owner_reviews": false},
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

적용 전: 보호 없음(`Branch not protected`, HTTP 404). `app_id` 15368은 GitHub Actions다.

| 설정 | 값 | 이유 |
|---|---|---|
| 필수 상태 검사 | `pytest`, `web` | DoD "CI 필수". 둘 다 main에서 이미 도는 잡이다(`engine.yml`, `web.yml`) |
| 최신 브랜치 필수(`strict`) | 끔 | 켜면 PR마다 main 위로 다시 올려 CI를 다시 돌려야 해서 WIP 한도 안의 병렬 PR이 줄줄이 막힌다. 충돌은 GitHub가 막고, 의미 충돌은 머지 뒤 main의 CI가 잡는다 |
| 관리자에게도 적용 | 켬 | 저장소 소유자 계정도 직접 푸시할 수 없다. 이게 꺼져 있으면 DoD "직접 푸시 금지"가 소유자에게는 성립하지 않는다 |
| PR 필수 | 켬, 승인 수 0 | main에는 PR로만 들어간다(직접 푸시 금지의 실체). 승인 수를 0으로 둔 이유: 리뷰는 Sol 봇과 omp 트리아지가 하고, 계정이 하나라 자기 PR을 승인할 수 없다. 사람 승인이 필요한 건 창업자 승인 대상(위 8번)이며 기록으로 남긴다 |
| 선형 이력 | 켬 | squash만 쓰므로 어차피 성립한다. 머지 커밋이 들어오는 길을 한 번 더 막는다 |
| 강제 푸시, 삭제 | 금지 | |
| 머지 방식 | squash만 | DoD |

### 일부러 필수로 걸지 않은 것

- `ledger`, `pr-body`: 위 3번처럼 빨간 채 머지하지 않지만 보호 규칙의 필수 검사에는 넣지 않았다. 이 PR을 만들 때 `ledger`는 main에 있었으나 `pr-body`는 `pull_request`에서만 돌아 main 커밋에는 결과가 없다. 필수 검사 이름이 한 번이라도 보고되지 않으면 GitHub 설정 화면에서 고르기 어렵다. 필요하면 창업자 승인 없이 omp가 `PUT .../required_status_checks`로 더한다.
- 리뷰 봇(P0-06)이 생겨도 봇의 판정은 필수 검사로 걸지 않는다. 판정은 `triage.md`를 거쳐 사람이 아닌 omp가 정한다.

### 확인과 되돌리기

```
gh api repos/NomaDamas/Kinetra/branches/main/protection        # 현재 보호 규칙(증거)
gh api repos/NomaDamas/Kinetra --jq '{allow_squash_merge,allow_merge_commit,allow_rebase_merge}'
gh api -X DELETE repos/NomaDamas/Kinetra/branches/main/protection/enforce_admins   # 긴급 시 관리자 예외. 쓰면 이슈에 이유를 적고 곧 다시 켠다
```

보호 규칙을 바꾸는 일은 이 문서의 표와 함께 PR로 고친다. 규칙을 약하게 바꾸는 변경은 창업자 승인 대상이다(`triage.md`).
