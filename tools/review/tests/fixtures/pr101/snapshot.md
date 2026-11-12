# PR #101: [P0-99] 샘플 변경

https://github.com/o/r/pull/101
기준 main ← p0-99-sample @ 0123456789ab
라벨: type:infra

## PR 본문
## 대목표
G0 — 샘플.

## 문제
Closes #77

## 연결 이슈 #77 [P0-99] 샘플 이슈
라벨: area:process, prio:P0, stage:S0-process, type:infra

## 완료 정의 (DoD)
- [ ] 샘플 문서가 있다
- [ ] 샘플 도구가 값을 돌려준다

## 핵심 가치 원본 (docs/plan/values.md, 기준 브랜치)
# 샘플 핵심 가치

- **V3 한 번에 100%** — 작은 단위를 증거와 함께 완전히 끝낸다.

## "100% 완료" 정의 (docs/process/done-definition.md, 기준 브랜치)
# 샘플 완료 정의

1. 이슈 DoD 체크박스가 모두 증거와 함께 닫혔다.

## 계획 발췌 (docs/plan/studio-plan.md, 라벨: area:process, stage:S0-process)

## 1. 한 줄 정의

핵심 가치 절 본문.

```
## 이 줄은 코드 펜스 안이라 제목이 아니다
```

## 12. 개발 루프

루프 절 본문.

### S0

S0 표.

## 13. 비판

위험 절 본문.

### 13.1 하위 절

13절에 딸린 하위 절.

## 변경 파일 (제외된 파일은 diff 본문이 없다)
| 경로 | 상태 | 줄 | 제외 사유 |
|---|---|---|---|
| `CREDITS.md` | modified | +1/-0 | 생성물(assets/LEDGER.csv에서 생성) |
| `assets/LEDGER.csv` | modified | +1/-0 |  |
| `assets/models/box.glb` | added | +0/-0 | 에셋·바이너리 |
| `docs/process/sample.md` | added | +3/-0 |  |
| `old/legacy.py` | deleted | +0/-2 |  |
| `pnpm-lock.yaml` | modified | +1/-1 | lock |
| `tools/sample/thing.py` | modified | +2/-1 |  |

## 삭제된 파일 1개(내용 생략)
old/legacy.py

## diff (부분 1/1; 생성물·lock·번들·에셋 제외)
diff --git a/assets/LEDGER.csv b/assets/LEDGER.csv
index 3333333..4444444 100644
--- a/assets/LEDGER.csv
+++ b/assets/LEDGER.csv
@@ -1,2 +1,3 @@
 header
+row
 end
diff --git a/docs/process/sample.md b/docs/process/sample.md
new file mode 100644
index 0000000..6666666
--- /dev/null
+++ b/docs/process/sample.md
@@ -0,0 +1,3 @@
+# 샘플
+
+본문
diff --git a/tools/sample/thing.py b/tools/sample/thing.py
index aaaaaaa..bbbbbbb 100644
--- a/tools/sample/thing.py
+++ b/tools/sample/thing.py
@@ -1,3 +1,4 @@
 def thing():
-    return 1
+    return 2
+# 새 줄

