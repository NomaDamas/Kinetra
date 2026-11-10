# Godot + Jolt 한계 측정 (A0-03)

이 파일은 A0-03의 하위 이슈(a, b)가 각자 자기 절만 채운다. 측정만 하고 최적화는 하지 않는다. `spikes/mujoco-limits/REPORT.md`(A0-01)와 같은 규칙(시드 고정, 부하 기록, 값마다 명령과 머신, 값 배지)을 따른다. 모든 속도 수치는 **[추정: 부하 아래 측정, 한가한 머신 재측정은 확인 필요]**다.

## Godot 바이너리 (저장소 밖)

| 항목 | 값 |
|---|---|
| 내려받은 것 | 공식 `Godot_v4.7.2-stable_macos.universal.zip` ([릴리스 4.7.2-stable](https://github.com/godotengine/godot/releases/tag/4.7.2-stable), 2026-08-18), 170,622,178 B(162 MiB) |
| zip sha256 | `c58a24e31d720be9d62f60cb5627c4e695fb72f21b0cfe1bc9ccaa9a3b3ba63e` |
| zip sha512 | `38aa16e5bba2083941fc5b3e54be0089bd4cc35e32415f5b9fd9a8a6a7b9818255d44532ea8ef94b5aef56c4b407c2d634fa4f657e4ebe681ebbf59b7bac69ca` = 릴리스의 `SHA512-SUMS.txt` 줄과 같다 |
| 실행 파일 sha256 | `c7cccbf8fb143e34e02fd6521e09be2c2b974f0d5db080b19071c9c570718ccf` (`Godot.app/Contents/MacOS/Godot`, `scale.py`가 매 실행에 기록) |
| 위치 | `~/.cache/kinetra-godot/Godot.app` (저장소 밖. zip은 풀고 지웠다. 앱 338 MiB) |
| 버전 | `godot --version` → `4.7.2.stable.official.ed1daf0bf` (엔진 해시 `ed1daf0bf001b61586d9930840f2f1394092c079`) |
| 라이선스 | Godot: MIT. 번들 **Jolt Physics 5.5.0** (Jorrit Rouwe, MIT): 소스 `thirdparty/README.md`의 "jolt_physics … Version: 5.5.0 (23dadd0e…), License: MIT", 바이너리의 `Engine.get_copyright_info()`에도 "Jolt Physics … Expat"가 있다. 원장 행 `dep-godot-4.7.2` |
| 물리 엔진 선택 | 프로젝트 설정 `physics/3d/physics_engine="Jolt Physics"`. 확인: 같은 스크립트가 설정 없이는 `GodotPhysicsDirectBodyState3D`, 설정하면 `JoltPhysicsDirectBodyState3D`를 돌려준다(`PhysicsServer3D.body_get_direct_state(...).get_class()`) |
| 서명 | 받은 앱은 `com.apple.provenance` 속성만 있었고 `--headless` 실행에 문제가 없었다 |

받기 전 확인한 것: 릴리스 파일 크기(macOS universal 162 MiB, 내보내기 템플릿 전체 `.tpz` 1.19 GiB). 웹 내보내기 템플릿은 `.tpz` 전체를 받지 않고 HTTP 범위 요청으로 `web_release.zip`(9.8 MiB)과 `web_nothreads_release.zip`(9.8 MiB)만 꺼냈다(A0-03b).

### 헤드리스로 되는 것

- `godot --headless --path spikes/godot-jolt --script scale.gd -- ...`가 돈다. 물리는 `PhysicsServer3D` 직접 호출(노드·씬 없음)이다.
- **`--headless`만으로는 물리 스텝이 실시간에 묶인다**: `common/physics_ticks_per_second=500`일 때 1,000스텝이 2.000 s(벽시계 = 시뮬 시간)였다. `--fixed-fps 500`을 더하면 같은 1,000스텝이 0.012 s(빈 세계)였다. 그래서 측정은 `--headless --fixed-fps 500`으로 한다. 이슈의 검증 명령 `godot --headless --script spikes/godot-jolt/scale.gd`는 그대로는 이 때문에 의미 있는 배속을 못 잰다(실시간에 맞춰 기다리므로 배속이 항상 약 1.0) [추정 아님: 위 두 실행을 직접 비교]. 같은 이유로 `scale.py`가 인자를 모두 채운 명령을 만든다.
- 시간 간격은 MuJoCo 스파이크와 같은 0.002 s(500 Hz). Z가 위, SI, `default_gravity_vector=(0,0,-1)`, 감쇠 0.
- 스크립트가 `--script`로 SceneTree를 직접 돌리므로 에디터 임포트도 필요 없다. 실행 뒤 `~/Library/Application Support/Godot/app_userdata/`에 빈 로그 폴더가 생긴다(`file_logging`을 꺼 두었다).

## A0-03a. 다물체·파단 스케일과 결정론 (이슈 #51)

### 결론 먼저

- **[측정 대기: 디스크]** 박스 1,000개·5,000개와 1,000개+결합 해제 100건 합친 장면은 `resource_guard.py --profile heavy`가 SSD 여유 부족(측정 기간 1.1~8.4 GiB, 임계 10 GiB)으로 차단해 **재지 못했다**. 아래 "측정 상태" 표의 빈 칸이다. 임계를 낮추거나 가드를 우회하지 않았다. 값이 생기면 이 절에 같은 표로 채운다. (같은 이유로 아래 두 장면만 가드 없이 돌렸고, 이 두 장면은 `scale.gd`의 무거운 실행 기준 1,000개 미만이라 가드가 요구하지 않는다.)
- 잰 것: **박스 200개 낙하 더미(2 s 시뮬)의 실시간 배속 0.16~0.19**, **결합 해제 100건 장면(박스 100개, 2 s)의 배속 0.22~0.24**(기본 스레드). 실시간(1.0)에 못 미친다. 부하가 심한 머신(load average 60~130)의 비관적 값이다.
- 결합 해제 100건은 **모두 처리됐다**(해제 100/100, 남은 6DOF 결합 0, 해제 직전 기둥 이동 최대 1e-4 m = 해제 전에는 고정이 유지됨).
- **결정론: 측정한 2개 장면 모두 일치.** 같은 빌드, 같은 시드, **별도 프로세스** 2회 + 워커 스레드 1개로 제한한 1회, 총 3실행의 상태 해시가 100개 체크포인트(10스텝마다) 전부에서 같았다. 스레드 수를 바꿔도 같았다는 것이 Jolt 쪽에서 의미 있는 결과다(MuJoCo 스파이크는 단일 스레드만 봤다).
- 범위: 같은 플랫폼(macOS arm64)·같은 바이너리·같은 머신이다. 플랫폼 간 결정론은 이 측정의 범위 밖이다. #54 코멘트(2026-11-10)의 MuJoCo 플랫폼 간 불일치 관찰과 같은 한계가 Jolt에도 있을 수 있다 [확인 필요: Linux 빌드로 같은 해시를 비교]. Jolt 문서의 크로스 플랫폼 결정론은 Godot 빌드 옵션(`JPH_CROSS_PLATFORM_DETERMINISTIC`)에 달려 있고 이 빌드가 그렇게 빌드됐는지는 확인하지 못했다(`modules/jolt_physics/SCsub`에서 그 정의를 찾지 못함, 즉 켜져 있지 않을 가능성이 높다) [추정].

### 방법

| 항목 | 값 |
|---|---|
| 명령 | `uv run python tools/dev/resource_guard.py --profile heavy -- uv run spikes/godot-jolt/scale.py --threads1 --json spikes/godot-jolt/results/a0-03a-main.json` (전체 행렬). 이번에 실제로 돈 것: `uv run spikes/godot-jolt/scale.py --bodies 200 --break-pile 0 --threads1 --json spikes/godot-jolt/results/a0-03a-small.json` |
| 장면 `pile-N` | 한 변 0.1 m 정육면체(1 kg = 밀도 1,000) N개를 5층 격자(간격 0.18 m, ±0.01 m 지터, 임의 요 + ±0.15 rad 기울임, 초기 xy 속도 ±0.3 m/s)로 바닥 위 최대 약 0.8 m에서 낙하. 사방은 벽. MuJoCo `scale.py`와 **같은 조립법**이다. 난수열은 Godot의 것이라 위치 값은 MuJoCo와 같지 않다(같은 조립법이지 같은 수가 아니다). 마찰 1.0, 반발 0 |
| 장면 `break-N` | 박스 100개, 10개씩 10개 기둥. 맨 아래는 월드에, 나머지는 바로 아래에 **완전히 잠근 6DOF 결합**(선·각 한계를 0으로 켠 `joint_make_generic_6dof`)으로 붙임(총 100건). 0.2~1.2 s 구간에 시드로 섞은 순서로 균등 간격에 `PhysicsServer3D.free_rid(joint)`로 하나씩 해제. N>0이면 같은 세계에 pile N개를 합침 |
| 배속 | `rtf = 시뮬 시간 / (물리 콜백과 다음 콜백 사이 벽시계 시간의 합)`. 스크립트가 쓴 시간(상태 읽기, 해시)은 콜백 안이라 제외한다. 이 구간은 엔진 한 스텝(Jolt 스텝 + 서버 동기화) + 루프 오버헤드다. `--fixed-fps 500`이라 렌더·실시간 대기는 없다. 장면 구성 시간은 `build_s`로 따로 기록 |
| 상한 | 장면마다 스텝 구간 벽시계 60 s 또는 시뮬 2 s 중 먼저 오는 쪽(`--wall-cap 60`). 이번 두 장면은 상한에 걸리지 않고 완주 |
| 결정론 | 10스텝마다 모든 동적 바디의 변환(위치 + 기저 3열, float32 12개)을 sha256 체인에 누적. 같은 장면을 **새 Godot 프로세스**로 2회 반복(기본 스레드) + 워커 풀 1스레드(`threads1/project.godot`) 1회, 공통 체크포인트 전부 비교. 비교 불가(<2회 또는 체크포인트 0)는 일치로 세지 않는다 |
| 시드 | 0 (배치 `seed`, 초기 속도 `seed+1`, 해제 순서 `seed+2`) |
| 측정 | 순수 측정. 솔버 반복, 슬립, 스레드, 접촉 캐시 등 Jolt 설정은 Godot 4.7.2 기본값 그대로(`velocity_steps=10`, `position_steps=2`, 슬립 끔: 바디에 `can_sleep=false`). 임시 메모리 버퍼만 512 MiB로 키움(기본 32 MiB를 넘는다는 경고가 나서; 측정 값이 아니라 경고 제거) |

### 머신과 소프트웨어

| 항목 | 값 | 출처 명령 |
|---|---|---|
| CPU | Apple M2 Pro | `sysctl -n machdep.cpu.brand_string` |
| 코어 | 논리 10 / 물리 10 | `sysctl -n hw.ncpu`, `hw.physicalcpu` |
| RAM | 32 GiB | `sysctl -n hw.memsize` |
| OS | macOS 15.6.1 (arm64) | `platform.platform()` |
| Godot | 4.7.2.stable.official.ed1daf0bf, Jolt Physics 5.5.0 | `godot --version`, `thirdparty/README.md` |
| Python | 3.12.11 | 드라이버 `scale.py`는 표준 라이브러리만 쓴다 |

### 결과 표 1: 배속 (이번에 잰 장면)

시드 0, 0.002 s 간격, 2.0 s(1,000스텝). `부하`는 실행 전 → 후의 `loadavg` 1분(`os.getloadavg()`). 반복 0, 1은 같은 설정의 별도 프로세스다. `threads-1`은 워커 풀 1스레드.

| 장면 | 변형 | 시뮬(s) | 벽시계 스텝(s) | **배속(rtf)** | 장면 구성(s) | 해제 | 더미 z 범위(m) | load avg |
|---|---|---|---|---|---|---|---|---|
| pile-200 | 반복 0 | 2.0 | 10.71 | **0.187** | 0.016 | 0 | 0.050~0.451 | 72 → 67 |
| pile-200 | 반복 1 | 2.0 | 12.37 | **0.162** | 0.003 | 0 | 0.050~0.451 | 67 → 63 |
| pile-200 | threads-1 | 2.0 | 17.68 | 0.113 | 0.001 | 0 | 0.050~0.451 | 63 → 70 |
| break-0 (100개 + 해제 100건) | 반복 0 | 2.0 | 8.17 | **0.245** | 0.057 | 100 | 0.050~0.950 | 70 → 73 |
| break-0 | 반복 1 | 2.0 | 9.14 | **0.219** | 0.130 | 100 | 0.050~0.950 | 73 → 79 |
| break-0 | threads-1 | 2.0 | 1.93 | 1.04 | 0.005 | 100 | 0.050~0.950 | 79 → 82 |

읽는 법과 한계:

- **같은 설정을 반복한 값이 약 15~25% 흔들린다**(pile-200 0.187 vs 0.162, break-0 0.245 vs 0.219). 부하 때문이다. 자릿수로만 읽는다.
- **`threads-1`의 break-0가 기본 스레드보다 4~5배 빠른 것은 엔진이 빨라서가 아니라 이 머신의 부하 탓이다 [추정]**: load average가 코어 수(10)의 6~13배라서 여러 워커 스레드가 스케줄링 대기와 동기화 대기에 시간을 쓰고, 한 스레드는 그 비용을 안 낸다. pile-200은 반대로 느려졌다(0.113). 한 장면의 한 번 실행이라 일반화하지 않는다. 한가한 머신에서 다시 재야 한다.
- 이 장면은 더미가 정착하기 전 구간(낙하·초기 접촉)이 대부분이다. 정착한 더미의 배속이 아니다. 슬립은 껐다.
- 더미 z 범위의 최댓값 0.451 m는 맨 위 층이 아직 떨어지는 중이거나 쌓인 높이다. 모든 바디의 좌표는 유한했다(`finite=true`).
- 모델 구성 시간은 배속에 넣지 않았다. 구성(`build_s`)은 200개에서 0.003~0.016 s로 MuJoCo의 컴파일(0.01~0.17 s)보다 짧다 [같은 조건 비교 아님: 컴파일과 서버 호출은 하는 일이 다르다].
- MuJoCo A0-01a와 같은 장면 크기(200개)의 배속은 0.02~0.03(`rtf_cpu` 약 0.2)이었다. 이번 Jolt 값은 0.16~0.19로 **이 머신 이 설정에서 약 6~8배 빠르다**. 단 두 스파이크의 부하가 같지 않고(MuJoCo 쪽 load 89~91, 이번 63~73), 솔버·접촉 모델·시간 적분이 다르며, 더미 구성이 같은 조립법일 뿐 같은 수가 아니다. **차이의 크기는 근거가 약하고 방향(Jolt가 더 빠르다)만 읽는다** [추정].

### 측정 상태: 요구 장면 대비

| 이슈 요구 | 상태 |
|---|---|
| 강체 200개 | **측정함**(0.162, 0.187) |
| 강체 1,000개 | **[측정 대기: 디스크]** 가드 차단(SSD 여유 < 10 GiB) |
| 강체 5,000개 | **[측정 대기: 디스크]** 같은 이유 |
| 결합 해제 100건 | **측정함**(박스 100개 단독, 100건 모두 처리, 0.219, 0.245). 1,000개와 합친 장면은 **[측정 대기: 디스크]** |
| 같은 빌드 반복 상태 해시 | **측정함**(200개, 해제 100건: 일치) |

### 결과 표 2: 같은 시드 반복 실행의 상태 해시

| 장면 | 실행 | 공통 체크포인트(10스텝 간격) | 일치 | 마지막 해시(앞 16자) |
|---|---|---|---|---|
| pile-200 | 별도 프로세스 2회(기본 스레드) | 100 | **예** | d8878d41021da9d8 |
| pile-200 | 기본 스레드 vs 워커 1스레드 | 100 | **예** | 같음 |
| break-0 | 별도 프로세스 2회(기본 스레드) | 100 | **예** | f8d8bbe8db70b914 |
| break-0 | 기본 스레드 vs 워커 1스레드 | 100 | **예** | 같음 |

의미: **같은 빌드, 같은 머신, 같은 시드에서는 결정론적이다. 부하와 스레드 수는 궤적에 영향을 주지 않았다.** 플랫폼 간·다른 Godot/Jolt 버전 간 일치는 범위 밖이다. 원본 JSON(실행별 체크포인트, 부하, 시각)은 `results/a0-03a-small.json`.

### 재현 방법

저장소 루트에서. Godot 바이너리는 저장소에 없다(위 "Godot 바이너리"). 없으면 `scale.py`가 종료 코드 4로 끝난다.

```
# 빠른 확인(가드 불필요): 200개 + 해제 100건, 별도 프로세스 2회 + 1스레드 1회
uv run spikes/godot-jolt/scale.py --bodies 200 --break-pile 0 --threads1
# 전체 행렬(1,000개 이상이 있어 무거운 실행): 가드 아래에서만 돈다
uv run python tools/dev/resource_guard.py --profile heavy -- uv run spikes/godot-jolt/scale.py --threads1 --json spikes/godot-jolt/results/a0-03a-main.json
# 장면 하나를 직접(이슈의 검증 명령의 완성형)
~/.cache/kinetra-godot/Godot.app/Contents/MacOS/Godot --headless --fixed-fps 500 --path spikes/godot-jolt --script scale.gd -- --scene pile --n 200
# 하니스 점검(오프라인, 속도·해시 값은 단언하지 않음; Godot 불필요)
uv run spikes/godot-jolt/test_scale.py
```

`test_scale.py`(10건)는 해시 비교(일치, 접두 일치, 불일치와 첫 불일치 위치, 단일 실행·빈 체크포인트는 비교 불가), `RESULT` 줄 파싱, 장면 인자, 명령에 `--headless`·`--fixed-fps 500`·`--script`가 있는지, Godot 없음 → 종료 코드 4, `--repeats 0` 거부를 단언한다. 속도 문턱이나 고정 해시 값은 단언하지 않는다. `scale.gd`는 1,000개 이상을 가드 밖(`KINETRA_GUARD_PASSED` 없음)에서 시작하면 종료 코드 2로 거절한다.

### 자원 기록 (P0-09)

- 가드: 1,000개 이상 실행은 `resource_guard.py --profile heavy`로 시도했고 **차단**(ssd_free 1.1~8.4 GiB < 10 GiB, 메모리 압력이 한때 critical)이라 시작되지 않았다. 차단 동안 내 것만 정리했다(`uv cache prune` 약 0.9 GiB). 내려받기: Godot 앱 338 MiB(`~/.cache/kinetra-godot`), 웹 템플릿 20 MiB(`~/Library/Application Support/Godot/export_templates/4.7.2.stable`). 다른 사람의 파일은 지우지 않았다.
- 가드 밖에서 돈 것: 200개·break-0(각 3회, 가드 임계 1,000개 미만), 한 번에 하나씩.
- 머신 상태는 측정 내내 SSD 여유 1~8 GiB(99~100% 사용), 스왑 90~100%, load average 60~250이었다.

### 의존성 라이선스 (원장 `assets/LEDGER.csv`)

| 의존성 | 라이선스 | 출처 |
|---|---|---|
| Godot 4.7.2 (바이너리, 저장소 밖) | MIT | https://github.com/godotengine/godot/blob/4.7.2-stable/LICENSE.txt |
| Jolt Physics 5.5.0 (Godot에 번들) | MIT | https://github.com/jrouwe/JoltPhysics |

### 알려진 한계 (정직성)

- 1,000개·5,000개·합친 장면은 못 쟀다(위). 이 값 없이는 계획의 문턱 [제안] "최종 버전 후보는 1,000개 실시간"에 대한 Jolt 쪽 답이 없다.
- 부하가 심해 배속은 비관적이고 흔들림이 크다. 한가한 머신 재측정이 필요하다 [확인 필요].
- 장면은 낙하 초기 구간이다. 슬립·정착 후 값이 아니다.
- 박스 모양, 마찰, 솔버 설정 하나만 측정했다. Jolt 설정 튜닝은 하지 않았다.
- 결정론은 같은 바이너리·같은 머신 안에서만 봤다.
