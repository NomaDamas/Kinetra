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

모든 속도 값은 **[추정: 부하 아래 측정, 한가한 머신 재측정은 확인 필요]**이고, 같은 장면을 반복해도 값이 크게 흔들린다(아래). 숫자 하나가 아니라 자릿수로 읽는다.

- **실시간 배속(1.0 = 실시간), 기본 스레드, 2 s 시뮬(낙하 초기 구간), 반복 2회 범위:** 박스 200개 **0.26~0.37**, 1,000개 **0.13~0.19**, 5,000개 **0.033~0.037**, 결합 해제 100건(박스 100개) **3.2~3.6**, 1,000개 + 해제 100건 합친 장면 **0.18~0.19**. 해제 100건은 모든 장면에서 **100/100 처리**됐다(남은 6DOF 결합 0).
- 계획의 문턱 [제안] "S1은 200개 실시간"에 **기본 스레드로는 못 닿았다**(0.26~0.37). 워커 풀을 1스레드로 줄인 한 번의 실행은 1.21로 닿았다. "최종 버전 후보는 1,000개 실시간"에는 못 닿았다(0.13~0.19, 1스레드도 0.21). 박스 100개 + 해제 100건 단독 장면은 실시간을 넘었다(3.2~3.6).
- **같은 장면의 값이 부하 시점에 따라 크게 바뀐다**: 박스 100개 + 해제 100건은 이번 실행에서 3.2~3.6이었는데 몇 시간 전 부하가 더 심한 때(`a0-03a-small.json`) 같은 장면이 0.22~0.24였다(약 15배). 200개도 0.16~0.19 대 0.26~0.37. 이 머신의 값은 엔진 성능이 아니라 그때의 부하를 크게 섞는다.
- **결정론: 측정한 5개 장면 모두 일치.** 같은 빌드·시드·**별도 프로세스** 2회와 워커 1스레드 1회의 상태 해시가 공통 체크포인트(10스텝마다) 전부에서 같았다(5,000개는 상한으로 일찍 멈춘 실행과 비교해 공통 98개와 61개). 스레드 수를 바꿔도 같았다.
- 범위: 같은 플랫폼(macOS arm64)·같은 바이너리·같은 머신이다. 플랫폼 간 결정론은 범위 밖이다. #54 코멘트(2026-11-10)의 MuJoCo 플랫폼 간 불일치와 같은 한계가 Jolt에도 있을 수 있다 [확인 필요: Linux 빌드로 같은 해시를 비교]. Godot의 Jolt 모듈 빌드 스크립트(`modules/jolt_physics/SCsub`)에서 `JPH_CROSS_PLATFORM_DETERMINISTIC` 정의를 찾지 못했다. 즉 켜져 있지 않을 가능성이 높다 [추정].

### 방법

| 항목 | 값 |
|---|---|
| 명령 | `uv run python tools/dev/resource_guard.py --profile heavy -- uv run spikes/godot-jolt/scale.py --threads1 --json spikes/godot-jolt/results/a0-03a-main.json` (전체 행렬, 결과 `results/a0-03a-main.json`). 가드 밖에서 먼저 돌린 작은 실행: `uv run spikes/godot-jolt/scale.py --bodies 200 --break-pile 0 --threads1 --json spikes/godot-jolt/results/a0-03a-small.json` |
| 장면 `pile-N` | 한 변 0.1 m 정육면체(1 kg = 밀도 1,000) N개를 5층 격자(간격 0.18 m, ±0.01 m 지터, 임의 요 + ±0.15 rad 기울임, 초기 xy 속도 ±0.3 m/s)로 바닥 위 최대 약 0.8 m에서 낙하. 사방은 벽. MuJoCo `scale.py`와 **같은 조립법**이다. 난수열은 Godot의 것이라 위치 값은 MuJoCo와 같지 않다(같은 조립법이지 같은 수가 아니다). 마찰 1.0, 반발 0 |
| 장면 `break-N` | 박스 100개, 10개씩 10개 기둥. 맨 아래는 월드에, 나머지는 바로 아래에 **완전히 잠근 6DOF 결합**(선·각 한계를 0으로 켠 `joint_make_generic_6dof`)으로 붙임(총 100건). 0.2~1.2 s 구간에 시드로 섞은 순서로 균등 간격에 `PhysicsServer3D.free_rid(joint)`로 하나씩 해제. N>0이면 같은 세계에 pile N개를 합침 |
| 배속 | `rtf = 시뮬 시간 / (물리 콜백과 다음 콜백 사이 벽시계 시간의 합)`. 스크립트가 쓴 시간(상태 읽기, 해시)은 콜백 안이라 제외한다. 이 구간은 엔진 한 스텝(Jolt 스텝 + 서버 동기화) + 루프 오버헤드다. `--fixed-fps 500`이라 렌더·실시간 대기는 없다. 장면 구성 시간은 `build_s`로 따로 기록 |
| 상한 | 장면마다 스텝 구간 벽시계 60 s 또는 시뮬 2 s 중 먼저 오는 쪽(`--wall-cap 60`). 5,000개의 두 실행은 상한에 걸려 985스텝(반복 1)과 617스텝(1스레드)에서 멈췄고, 나머지는 완주("상한" 열) |
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

### 결과 표 1: 배속

시드 0, 0.002 s 간격, 목표 2.0 s(1,000스텝). 명령은 위 방법의 `scale.py` 전체 행렬. `부하`는 실행 전 → 후의 1분 load average. 반복 0, 1은 같은 설정의 별도 프로세스, `threads-1`은 워커 풀 1스레드.

| 장면 | 변형 | 스텝 | 시뮬(s) | 벽시계 스텝(s) | **배속(rtf)** | 구성(s) | 해제 | 상한 | 더미 z 최대(m) | 부하 |
|---|---|---|---|---|---|---|---|---|---|---|
| pile-200 | 반복 0 | 1,000 | 2.00 | 7.59 | **0.264** | 0.002 | 0 | 완주 | 0.451 | 36 → 45 |
| pile-200 | 반복 1 | 1,000 | 2.00 | 5.47 | **0.366** | 0.002 | 0 | 완주 | 0.451 | 45 → 46 |
| pile-200 | threads-1 | 1,000 | 2.00 | 1.65 | 1.215 | 0.003 | 0 | 완주 | 0.451 | 46 → 47 |
| pile-1000 | 반복 0 | 1,000 | 2.00 | 14.92 | **0.134** | 0.005 | 0 | 완주 | 0.452 | 47 → 51 |
| pile-1000 | 반복 1 | 1,000 | 2.00 | 10.31 | **0.194** | 0.005 | 0 | 완주 | 0.452 | 51 → 50 |
| pile-1000 | threads-1 | 1,000 | 2.00 | 9.56 | 0.209 | 0.006 | 0 | 완주 | 0.452 | 50 → 47 |
| pile-5000 | 반복 0 | 1,000 | 2.00 | 54.44 | **0.0367** | 0.054 | 0 | 완주 | 0.457 | 47 → 61 |
| pile-5000 | 반복 1 | 985 | 1.97 | 60.06 | **0.0328** | 0.040 | 0 | 60 s 상한 | 0.457 | 61 → 74 |
| pile-5000 | threads-1 | 617 | 1.23 | 60.00 | 0.0206 | 0.124 | 0 | 60 s 상한 | 0.457 | 74 → 60 |
| break-0 (100개 + 해제 100건) | 반복 0 | 1,000 | 2.00 | 0.559 | **3.576** | 0.004 | 100 | 완주 | 0.950 | 60 → 58 |
| break-0 | 반복 1 | 1,000 | 2.00 | 0.630 | **3.174** | 0.004 | 100 | 완주 | 0.950 | 58 → 58 |
| break-0 | threads-1 | 1,000 | 2.00 | 0.558 | 3.584 | 0.003 | 100 | 완주 | 0.950 | 58 → 58 |
| break-1000 (1,000개 + 해제 100건) | 반복 0 | 1,000 | 2.00 | 10.46 | **0.191** | 0.013 | 100 | 완주 | 0.952 | 58 → 56 |
| break-1000 | 반복 1 | 1,000 | 2.00 | 11.13 | **0.180** | 0.012 | 100 | 완주 | 0.952 | 56 → 58 |
| break-1000 | threads-1 | 1,000 | 2.00 | 8.93 | 0.224 | 0.012 | 100 | 완주 | 0.952 | 58 → 57 |

읽는 법과 한계:

- **같은 설정 반복의 흔들림이 크다**: pile-200 0.264 vs 0.366(약 40%), pile-1000 0.134 vs 0.194(약 45%). 부하 때문이다. 더 일찍 돌린 작은 실행(`a0-03a-small.json`, 부하 약 63~79)은 pile-200 0.16~0.19, break-0 0.22~0.24, 1스레드 break-0 1.04였다. 같은 장면이 시점에 따라 최대 약 15배 다르다.
- **1스레드가 기본 스레드보다 빠르거나 느린 것은 일관되지 않다**(pile-200 3~5배 빠름, pile-1000 비슷, pile-5000 느림, break-1000 약간 빠름, break-0 같음). 한 장면 한 번씩이라 일반화하지 않는다. 이 머신의 부하(코어의 4~7배)가 여러 워커 스레드의 대기 비용을 키웠을 가능성이 있다 [추정].
- pile-5000의 두 실행은 60 s 상한에 걸렸다(반복 1은 985/1,000스텝, 1스레드는 617스텝). 배속은 그 구간의 값이다.
- 시뮬은 낙하·초기 접촉 구간이 대부분이라 정착한 더미의 배속이 아니다. 슬립은 껐다. 모든 바디 좌표는 유한했다(`finite=true`).
- 해제 직전 기둥의 최대 이동은 1e-4 m(해제 전 고정이 유지됨). 두 `break` 장면 모두 100건이 해제됐고 남은 결합은 0이었다.
- 구성 시간은 배속에 넣지 않았다. 5,000개 구성이 0.04~0.12 s로, MuJoCo A0-01a의 컴파일(42~47 s)과 비교가 안 된다(하는 일이 다르다: Godot는 서버 호출로 바디를 만들고, MuJoCo는 XML 컴파일).
- **MuJoCo A0-01a와 같은 장면 크기의 배속 비교(이 머신, 이 설정):** 200개 0.02~0.03 대 Jolt 0.26~0.37(약 10배), 1,000개 약 0.007 대 0.13~0.19(약 20~30배), 5,000개 0.002~0.003 대 0.033~0.037(약 12~15배), 해제 100건 0.5~0.6 대 3.2~3.6(약 6배), 1,000개 + 해제 0.007 대 0.18~0.19(약 25배), 해제 100건 100/100 완주(MuJoCo는 합친 장면에서 30~31건까지). 두 스파이크의 부하 시점이 다르고(MuJoCo는 load 50~195) 솔버·접촉 모델·적분이 다르며 더미가 같은 조립법일 뿐 같은 수가 아니다. **방향(Jolt가 한 자릿수~두 자릿수 배 빠르다)만 읽는다. 배수는 근거가 약하다** [추정].

### 측정 상태: 요구 장면 대비

| 이슈 요구 | 상태 |
|---|---|
| 강체 200개 | **측정함**(0.264, 0.366) |
| 강체 1,000개 | **측정함**(0.134, 0.194) |
| 강체 5,000개 | **측정함**(0.0367 완주, 0.0328 상한) |
| 결합 해제 100건 | **측정함**: 박스 100개 단독(3.576, 3.174)과 1,000개 합친 장면(0.191, 0.180) 모두 100/100 해제 |
| 같은 빌드 반복 상태 해시 | **측정함**(5개 장면 모두 일치) |

### 결과 표 2: 같은 시드 반복 실행의 상태 해시

해시는 10스텝마다 모든 동적 바디의 변환(float32 12개)을 sha256 체인에 누적한 값이다. "공통 체크포인트"는 두 실행이 모두 도달한 수다. 전부 같으면 일치.

| 장면 | 실행 | 공통 체크포인트 | 일치 | 마지막 해시(앞 16자) |
|---|---|---|---|---|
| pile-200 | 별도 프로세스 2회 | 100 | **예** | d8878d41021da9d8 |
| pile-200 | 기본 스레드 vs 워커 1스레드 | 100 | **예** | 같음 |
| pile-1000 | 별도 프로세스 2회 | 100 | **예** | 88f7f968a4ab467b |
| pile-1000 | 기본 vs 1스레드 | 100 | **예** | 같음 |
| pile-5000 | 별도 프로세스 2회 | 98 (반복 1이 985스텝에서 상한 종료) | **예** | 완주한 반복 0의 마지막: 5e7ce0f822059c3c |
| pile-5000 | 기본 vs 1스레드 | 61 (1스레드가 617스텝에서 상한 종료) | **예** | 공통 구간만 비교 |
| break-0 | 별도 프로세스 2회 | 100 | **예** | f8d8bbe8db70b914 |
| break-0 | 기본 vs 1스레드 | 100 | **예** | 같음 |
| break-1000 | 별도 프로세스 2회 | 100 | **예** | 9a0921bf2c917586 |
| break-1000 | 기본 vs 1스레드 | 100 | **예** | 같음 |

의미: **같은 빌드, 같은 머신, 같은 시드에서는 결정론적이다. 부하와 스레드 수는 궤적에 영향을 주지 않았다.** 플랫폼 간·다른 Godot/Jolt 버전 간 일치는 범위 밖이다. 5,000개의 비교는 상한으로 일찍 멈춘 실행과의 공통 구간이라 끝까지 간 같은 스텝 수의 비교가 아니다. 원본 JSON(실행별 체크포인트, 부하, 시각)은 `results/a0-03a-main.json`(전체 행렬)과 `results/a0-03a-small.json`(먼저 돌린 200개·해제 100건).

### 재현 방법

저장소 루트에서. Godot 바이너리는 저장소에 없다(위 "Godot 바이너리"). 없으면 `scale.py`가 종료 코드 4로 끝난다.

```
# 빠른 확인(가드 불필요): 200개 + 해제 100건, 별도 프로세스 2회 + 1스레드 1회
uv run spikes/godot-jolt/scale.py --bodies 200 --break-pile 0 --threads1
# 전체 행렬(1,000개 이상이 있어 무거운 실행): 가드 아래에서만 돈다(이번에 실제로 돈 명령)
uv run python tools/dev/resource_guard.py --profile heavy -- uv run spikes/godot-jolt/scale.py --threads1 --json spikes/godot-jolt/results/a0-03a-main.json
# 장면 하나를 직접(이슈의 검증 명령의 완성형)
~/.cache/kinetra-godot/Godot.app/Contents/MacOS/Godot --headless --fixed-fps 500 --path spikes/godot-jolt --script scale.gd -- --scene pile --n 200
# 하니스 점검(오프라인, 속도·해시 값은 단언하지 않음; Godot 불필요)
uv run spikes/godot-jolt/test_scale.py
```

`test_scale.py`(18건)는 해시 비교(일치, 접두 일치, 불일치와 첫 불일치 위치, 단일 실행·빈 체크포인트는 비교 불가), `RESULT` 줄 파싱, 장면 인자, 명령에 `--headless`·`--fixed-fps 500`·`--script`가 있는지, Godot 없음 → 종료 코드 4, `--repeats 0` 거부를 단언한다. 무거운 실행 문턱(1,000개)을 **시뮬레이션하는 전체 강체 수**(자유 더미 + 해제 장면의 100개)로 세는지(`total_bodies`: 더미 900 + 해제 장면 = 1,000 → 가드 호출, 899 → 호출 안 함), `scale.gd`가 같은 합(`n_pile + n_break`)을 쓰는지 단언한다. 또 커밋된 `results/a0-03a-main.json`을 읽기만 해서(새 측정 없음) DoD 사실을 단언한다: 장면 200/1,000/5,000개와 해제 장면이 있고, 해제 장면은 모든 실행에서 결합 100건 중 100건 해제·잔존 결합 0, 같은 빌드 해시 일치 플래그와 1스레드 대 기본 비교 플래그가 모두 참, 배속이 양수이고 load average(실행 전·후)가 함께 기록돼 있다. 속도 문턱이나 고정 해시 값은 단언하지 않는다. `scale.gd`는 시뮬레이션하는 강체가 합쳐 1,000개 이상이면 가드 밖(`KINETRA_GUARD_PASSED` 없음)에서 시작할 때 종료 코드 2로 거절한다(이전에는 더미와 해제 개수 중 큰 값을 세어 더미 900개 + 해제 100개 같은 합 1,000개 실행이 가드를 우회할 수 있었다).

### 자원 기록 (P0-09)

- 실행: `uv run python tools/dev/resource_guard.py --profile heavy -- uv run spikes/godot-jolt/scale.py --threads1 --json spikes/godot-jolt/results/a0-03a-main.json` (2026-11-11 00:20~00:56경, 한 번에 하나)
- 가드: **통과(경고 있음)**, 임계 배지 [기본값], 프로필 heavy. 경고: 스왑 사용률 94.1%(14.1/15.0 GiB)
- 머신: macOS 15.6.1 arm64 M2 Pro, SSD 여유 10.33 GiB, 부하 36~74(1분 평균)

| 항목 | 전 | 후 | 변화 | 실행 중 최악 |
|---|---|---|---|---|
| SSD 여유 GiB | 10.33 | 10.68 | +0.35 | 10.21 |
| 스왑 사용 GiB | 14.12 | 13.88 | -0.24 | 14.12 |
| 스왑 사용률 % | 94.1 | 92.5 | -1.6 | |
| 메모리 압력 | normal | normal | | |

- 종료 코드 0. 장면별 프로세스 시간은 `results/a0-03a-main.json`의 `process_wall_s`(5,000개 두 실행이 각 약 1분).
- 이 실행 전에 같은 명령을 가드가 여러 번 **차단**했다(ssd_free 1.1~8.4 GiB < 10 GiB, 메모리 압력이 한때 critical). 임계를 낮추지 않았고 여유가 10 GiB를 넘은 뒤 다시 시도해 통과했다. 그 사이 내 것만 정리했다(`uv cache prune` 약 0.9 GiB). 내려받은 Godot 앱 338 MiB(`~/.cache/kinetra-godot`)와 웹 템플릿 20 MiB(`~/Library/Application Support/Godot/export_templates/4.7.2.stable`)는 의존성이다.
- 한계: 같은 설정의 반복 간 40~45% 흔들림, 부하 36~74에서 잰 비관적 값. 가드 통과 시 SSD 여유가 10.2~10.7 GiB로 임계 바로 위였다.

### 의존성 라이선스 (원장 `assets/LEDGER.csv`)

| 의존성 | 라이선스 | 출처 |
|---|---|---|
| Godot 4.7.2 (바이너리, 저장소 밖) | MIT | https://github.com/godotengine/godot/blob/4.7.2-stable/LICENSE.txt |
| Jolt Physics 5.5.0 (Godot에 번들) | MIT | https://github.com/jrouwe/JoltPhysics |

### 알려진 한계 (정직성)

- 부하가 심해 배속은 비관적이고 흔들림이 크다(같은 장면이 시점에 따라 최대 약 15배). 한가한 머신 재측정이 필요하다 [확인 필요].
- 5,000개의 두 실행은 60 s 상한에 걸려 2 s 시뮬을 못 채웠다.
- 장면은 낙하 초기 구간이다. 슬립·정착 후 값이 아니다.
- 박스 모양, 마찰, 솔버 설정 하나만 측정했다. Jolt 설정 튜닝은 하지 않았다. 멀티스레드는 기본/1스레드 두 가지만 봤다.
- 결정론은 같은 바이너리·같은 머신 안에서만 봤다.
- MuJoCo와의 배속 배수는 부하 시점·모델이 달라 근거가 약하다.

## A0-03b. 웹 내보내기, OpenXR, MuJoCo 대비 오차 (이슈 #52)

### 결론 먼저

- **4륜차 두 장면에서 Godot 4.7.2 + Jolt와 MuJoCo 4.0.0의 궤적은 같은 장면 수치(질량, 치수, 마찰, 시간 간격, 구동 토크)로 시작해도 갈린다.** 경사 주행(4 s, 이동 경로 8.14 m)에서 차체 위치 차이는 **끝에서 최대 49.4 mm**(경로의 0.61%), 자세 차이 최대 0.27 mrad. 낙하(3 s)에서 위치 차이는 **착지 직후(스텝 236, 0.472 s) 최대 22.7 mm**, 끝에서 20.5 mm, 자세 차이 최대 **0.0386 rad(2.2°)**. 값은 모두 시뮬(`시뮬` 배지)이고 엔진 둘의 접촉·바퀴 모델 차이를 합친 것이다. 어느 쪽이 "현실에 가깝다"는 뜻이 아니다.
- **같은 빌드 반복은 비트 단위로 같다**: 두 장면 모두 Godot CSV의 sha256이 별도 프로세스 2회에서 같았다.
- **이 차이를 어떻게 읽나(노이즈 바닥과 함께).** MuJoCo 쪽 설정만 바꿔도 같은 크기의 차이가 난다: 적분기를 `implicitfast`로 바꾸면 1e-8 m(무시), 시간 간격 2 ms → 1 ms면 경사 2.2 mm, 낙하 3.8 mm, 접촉 강성 `solref` 0.02 → 0.004면 경사 9.3 mm, 낙하 **118 mm**(낙하 3.4 m 경로의 3.5%). Godot 쪽도 시작 높이를 1 µm만 흔들면 경사 0.68 mm, 낙하 **6.8 mm**로 커진다(접촉 뒤 증폭). 즉 낙하의 22.7 mm는 "엔진이 다르다"와 "접촉이 있는 궤적은 작은 차이를 키운다"가 섞인 값이고, 경사의 49 mm는 같은 방향으로 쌓이는 체계 오차(Godot의 차가 더 멀리 간다)다 [추정: 바퀴·접촉의 마찰·감쇠 모델 차이가 원인 후보이고 이번에 분해하지 않았다].
- **웹 내보내기는 된다, 그러나 이 헤드리스 브라우저에서 스레드 있는 빌드는 끝까지 못 돌았다.** 헤드리스로 `--export-release Web`이 두 변형(스레드 있음/없음)에서 끝났다. **번들 크기는 약 39 MB(gzip 약 10.3 MB, brotli 약 7.2 MB)이고 거의 전부 엔진 `.wasm`**이다. 내 장면 쪽(`.pck`)은 3.9 KB. 헤드리스 Chromium(SwiftShader)에서 스레드 있는 변형은 **페이지 로드 이벤트 355 ms(성능 타이밍 207 ms)에 페이지가 뜨고, 엔진 자체 시계로 약 1.1 s에 엔진이 시작해 Jolt를 선택했으며(`physics_engine=Jolt Physics`; 이 값은 엔진이 켜진 뒤부터 센 값이라 **페이지 탐색 시작부터의 로딩 시간이 아니다**, 아래), 이어서 `PAGEERROR memory access out of bounds`로 죽어 1,000스텝 결과를 내지 못했다**(120 s 대기 후 `ran=false`). 원인은 분해하지 않았다(1회 실행, 부하 아래, 소프트웨어 렌더러, 이 장면의 박스 200개 설정 중 어느 것인지 불명) [확인 필요]. **그 뒤 수정한 것(미검증)**: 측정 장면 `web/main.gd`가 `World3D`를 `_ready()`의 지역 변수로 들고 있어, 참조 계수 객체인 `World3D`(와 그것이 가진 물리 공간)가 `_ready()`가 끝나면 해제될 수 있었다. 멤버 변수로 바꿔 장면 수명 동안 붙잡는다. 이것이 위 `memory access out of bounds`의 원인인지는 모른다 [추정]. **수정한 장면을 다시 내보냈지만(두 변형) 가드가 SSD 여유 부족(7.7 GiB < 10 GiB)으로 차단해 다시 재지 못했다: 수정 효과는 [측정 대기: 디스크]이고, 위 크래시 기록은 수정 전 빌드의 것이다.**
- **OpenXR: 이 머신에서 `initialize()`가 `false`를 돌려줬고, 설치된 OpenXR 런타임은 찾지 못했다 [추정: 다른 원인 미배제]**(헤드리스 실행, `xr/openxr/enabled=false` 등 다른 원인은 로더 오류 로그로 배제하지 않았다). macOS 바이너리에는 `OpenXRInterface`가 등록돼 있다(아래). 실기·에뮬레이터 프레임률은 이번 범위 밖이다.

### 방법: 4륜차 장면

장면 수치는 `car_scene.json` 한 파일이고 MuJoCo 쪽(`car.py`)과 Godot 쪽(`car.gd`)이 같은 파일을 읽는다. `test_car.py`가 이 파일이 `make_params()`와 같다고 단언한다. Z 위, SI, 시간 간격 0.002 s(500 Hz), 중력 9.80665.

| 항목 | 값 |
|---|---|
| 차체 | 상자 반치수 0.5 × 0.25 × 0.1 m, 질량 10 kg |
| 바퀴 4개 | 원기둥 반지름 0.15 m, 반폭 0.05 m, 각 1 kg, 차체 기준 위치 (±0.35, ±0.30, −0.05), 힌지 축 = 차체 y. 바퀴-차체 충돌은 제외(MuJoCo는 부모-자식 기본, Godot는 `joint_disable_collisions_between_bodies`) |
| 재질 | 모든 접촉 마찰 계수 1.0(MuJoCo `friction="1 0 0"` = 구름·비틀림 마찰 없음, Jolt는 한 계수), 반발 0. Jolt는 두 마찰의 최솟값을 쓰고(`SetCombineFriction`) MuJoCo는 최댓값이라, 같은 값으로 맞춰 차이를 없앴다 |
| 구동 | 경사 장면만: 뒤 바퀴 둘에 각 3.0 N·m 일정 토크(바퀴에 +, 차체에 −, MuJoCo `<motor gear=1>`과 같은 작용). Godot는 `body_apply_torque`를 스텝마다 준다 |
| 경사 장면 `slope` | 지면 기울기 10°(+x가 오르막), 출발 시 바퀴 아래와 지면 사이 0.5 mm, 정지에서 시작, 2,000스텝(4 s) |
| 낙하 장면 `drop` | 평평한 바닥 위 1.2 m(바퀴 아래 1.0 m), 롤 3°·피치 5° 기울임, 전진 속도 1 m/s, 1,500스텝(3 s) |
| MuJoCo | 4.0.0, Euler, `timestep=0.002`, 기본 솔버(Newton, pyramidal), 접촉 파라미터 기본. 자유 관절 + 힌지 4개 |
| Godot | 4.7.2 + Jolt 5.5.0, 같은 시간 간격, 지면은 큰 정적 상자, 바퀴 힌지는 `joint_make_hinge`, 슬립 끔 |
| 비교 | 매 스텝 차체 위치(m)와 자세(두 쿼터니언 사이의 측지 각, rad). 행 0 = 첫 스텝 전 |
| 노이즈 바닥 | MuJoCo 변형 4개(적분기 `implicitfast`, 시간 간격 0.001(2스텝마다 비교), `solref=0.004 1`, 시작 높이 +1 µm)와 Godot 시작 높이 +1 µm을 같은 기준 궤적(MuJoCo Euler 0.002)과 비교 |
| 실행 | `uv run spikes/godot-jolt/car.py --json spikes/godot-jolt/results/a0-03b-car.json` (가드 불필요: 몇 초짜리 가벼운 실행) |

머신은 위 A0-03a와 같다. 이 실행의 load average는 180~190(`results/a0-03b-car.json`의 `machine.loadavg`). 궤적 값은 부하와 무관하다(같은 스텝 수의 결정론적 계산).

### 결과 표: Godot + Jolt 대 MuJoCo (4륜차)

| 장면 | 이동 경로(m) | 위치 차 최대(mm) | 최대 위치(스텝) | 끝 위치 차(mm) | 위치 차 RMS(mm) | 끝에서 경로 대비 | 자세 차 최대(rad) | 끝 자세 차(rad) |
|---|---|---|---|---|---|---|---|---|
| slope (2,000스텝) | 8.143 | **49.42** | 2000 | 49.42 | 26.19 | 0.61% | 0.00027 | 0.00003 |
| drop (1,500스텝) | 3.375 | **22.74** | 236 | 20.46 | 10.78 | 0.61% | **0.0386** | 0.0063 |

끝 상태(x, y, z): slope Godot (6.99936, 0.00021, 1.43690) vs MuJoCo (6.95065, 0.0, 1.42853). drop Godot (2.69196, 0.04394, 0.19998) vs MuJoCo (2.67593, 0.03124, 0.19986). 낙하 충돌 시각(차체 수직 속도 최소 시점): Godot 0.438 s, MuJoCo 0.440 s(속도는 위치의 유한차분).

### 노이즈 바닥 (같은 기준 궤적과의 위치 차 최대, mm / 자세 차 최대 rad)

| 변형 | slope | drop |
|---|---|---|
| MuJoCo `implicitfast` | 0.00001 / 4e-8 | 0.00003 / 6e-8 |
| MuJoCo 시간 간격 0.001 s | 2.2 / 5e-5 | 3.8 / 0.0091 |
| MuJoCo `solref=0.004` | 9.3 / 3.5e-4 | **117.9 / 0.063** |
| MuJoCo 시작 높이 +1 µm | 0.001 / 7e-8 | 0.001 / 1.4e-6 |
| **Godot** 시작 높이 +1 µm (Godot 기준) | 0.68 / 1.3e-4 | **6.8 / 0.0028** |
| Godot 대 MuJoCo(위 표) | **49.4** / 2.7e-4 | **22.7** / 0.0386 |

- MuJoCo는 1 µm 흔들림을 1 µm 안에 둔다(drop 1.3e-6 rad). Godot는 같은 흔들림을 낙하에서 약 6,800배(6.8 mm)로 키웠다. 이 값이 "Godot 쪽 재현성의 한계"는 아니다. 같은 입력에는 비트 단위로 같다(위). 입력의 작은 차이에 대한 민감도다.
- 낙하의 Godot 대 MuJoCo 22.7 mm는 MuJoCo 접촉 강성을 5배 올린 변형의 118 mm보다 작고 시간 간격을 반으로 줄인 3.8 mm보다 크다. **허용 차이를 정하는 근거로 쓰려면 장면 수와 접촉 설정이 더 필요하다**: 이 측정은 장면 2개, 각 1회이다. 계획의 "측정 후 정한다"에 대한 입력일 뿐 문턱이 아니다.

### 웹 내보내기

| 항목 | 값 |
|---|---|
| 내보내기 | `godot --headless --path spikes/godot-jolt/web --export-release Web index.html`, Godot 4.7.2, 공식 웹 템플릿 `web_release.zip`(sha256 `02f0dca1…67a3`)과 `web_nothreads_release.zip`(`d3ee2f08…32a0`)(범위 요청으로 `.tpz` 1.19 GiB 전체를 받지 않고 이 둘만 꺼냄). 렌더러 `gl_compatibility`(웹은 WebGL 2만 가능, 공식 문서) |
| 내보낸 앱 | 장면 하나, 에셋 없음. 물리 서버 직접 호출로 박스 200개를 1,000스텝(500 Hz) 돌리고 `window.__godot_result`와 콘솔에 결과를 남긴다(`web/main.gd`). 내보내기 시간 약 70 s(부하 아래) |

번들 크기(`/tmp`에 내보낸 두 폴더의 바이트). 압축 크기는 서버 설정에 따라 달라진다. **스레드 있음 열**은 `measure.mjs`가 Node `zlib`으로 잰 값이다(gzip 레벨 6, brotli 기본 품질 11, `results/a0-03b-web-threads.json`). **스레드 없음 열**의 압축 값은 측정 하니스가 아니라 이쪽에서 따로 계산한 값이다(Python gzip 레벨 6, `brotli -q 5`)이라 위 열과 직접 비교하지 않는다.

| 파일 | 스레드 있음(바이트) | 스레드 없음(바이트) |
|---|---|---|
| `index.wasm` | 38,820,072 (gzip 10,222,942 / brotli 7,082,995) | 39,514,754 (gzip 10,114,291 / brotli q5 8,326,654) |
| `index.js` | 314,653 (gzip 75,003 / brotli 63,750) | 279,815 (gzip 68,740) |
| `index.pck` (내 장면) | 3,944 | 3,944 |
| `index.html` + 워크릿 2 + `index.png` | 약 37,000 | 약 37,000 |
| **합계** | **39,175,688** (gzip 10,325,928 / brotli 7,173,257) | **39,835,533** (gzip 10,210,865) |

- 번들의 99%가 엔진 `.wasm`이다. 에셋을 더해도 이 바닥(압축 후 약 7~10 MB)은 줄지 않는다. 엔진을 필요한 모듈만 넣어 다시 빌드하면 줄일 수 있다는 것은 공식 문서의 말이고(`optimizing_for_size`) **이번에 시험하지 않았다**.
- 스레드 있는 변형은 `SharedArrayBuffer`가 필요해 **COOP/COEP 헤더**(`same-origin` / `require-corp`)를 서버가 보내야 한다(공식 문서). 스레드 없는 변형은 헤더가 필요 없지만 공식 문서가 "성능이 낮다"고 적는다. 우리 공유 링크가 정적 호스팅이면 헤더 제약이 걸린다.
- 공식 문서의 웹 제약(원문 확인): Godot 4의 C#은 웹 내보내기 불가, WebGL 2만 대상, Safari에 알려진 문제, 탭이 비활성이면 `_physics_process`가 멈춤.
- **Jolt가 웹 빌드에도 들어 있다**: 내보낸 앱은 `physics/3d/physics_engine="Jolt Physics"`로 내보냈고, 브라우저 안에서 시작 로그가 `physics_engine=Jolt Physics`를 출력했다. `.wasm`은 38.8 MB(MuJoCo WASM 11.2 MB의 3.5배). 박스 200개 시뮬이 브라우저에서 완주하는지는 확인하지 못했다(위).

로딩·실행 측정: `pnpm --dir spikes/godot-jolt measure -- --dir <export> --name <name> [--isolated] --out <json>`은 헤드리스 Chromium(Playwright 1.65.0 `chromium-headless-shell-1254`을 재사용, 새 브라우저 설치 없음, 158.0.8127.18) + 이 디렉터리의 정적 서버로 내보낸 폴더를 열고, `load` 이벤트 시각과 `window.__godot_result`가 생길 때까지 시간(상한 120 s)을 기록한다. 가드 밖에서 시작하면 종료 코드 2다. 가드 아래(통과, 경고: 스왑 93%)에서 돌렸다. 소프트웨어 렌더러(SwiftShader)라서 **실제 GPU 로딩 시간이 아니다**.

| 변형 | 로드 이벤트(ms, `Date.now()` 차) | 엔진 시계 기준 준비 시각(ms, `engine_clock_ready_ms` = 엔진 시작부터, 로딩 시간 아님) | 페이지 결과 | 격리(`crossOriginIsolated`, SAB) | 비고 |
|---|---|---|---|---|---|
| 스레드 있음 + COOP/COEP | 355 (DOMContentLoaded 207) | 1,092 (수정 전 `ready_ms`라는 이름으로 기록, 같은 값) | **없음**: `PAGEERROR memory access out of bounds`, 120 s 후 `ran=false` | true / true | Godot 로그: "Emscripten 4.0.20, multi-threaded", `physics_engine=Jolt Physics`, 4.7.2-stable. 1회 실행 |
| 스레드 없음 | [측정 대기: 디스크] | | | | 가드가 SSD 여유 부족으로 차단 중(7.7 GiB < 10 GiB). 같은 명령으로 채운다. 이 칸이 비어 있는 동안 PR은 닫지 않는다 |

- **필드가 뜻하는 것(수정)**: `engine_clock_ready_ms`는 Godot `Time.get_ticks_msec()`, 곧 엔진이 시작한 시점부터 센 값이다. 다운로드·`.wasm` 컴파일이 끝난 **뒤**에 0이 되므로 로딩 시간이 아니다(이전 이름 `ready_ms`가 그렇게 읽혔다). 탐색 시작부터의 시간은 두 가지로 따로 잰다: `ready_since_navigation_ms_in_page` = 엔진이 준비된 순간 페이지 안에서 읽은 `performance.now()`(`performance.timeOrigin` = 탐색 시작 기준), `ready_since_navigation_ms_harness` = 하니스가 같은 로그 줄을 받은 `Date.now()`에서 `performance.timeOrigin`을 뺀 값(콘솔 전달 지연이 섞임). 위 표의 355 ms·1,092 ms는 **수정 전 하니스가 기록한 값**이라 탐색 기준 값이 없다. 수정 후 값은 다시 재야 채워진다 [측정 대기: 디스크].
- 이 한 번의 실행으로 말할 수 있는 것: **엔진 시작과 Jolt 선택까지는 브라우저에서 된다.** 말할 수 없는 것: 박스 200개 물리가 브라우저에서 돈다. 그 단계에서 죽었고 원인(스레드 빌드의 메모리 한도, 소프트웨어 렌더러, 내 장면 설정, 엔진 버그 중 어느 것인지)을 분해하지 않았다. 재실행·스레드 없음 변형·실제 GPU 브라우저에서의 확인이 필요하다 [확인 필요].
- 자원 기록(가드 통과, 경고 있음): 명령 `resource_guard.py --profile heavy -- pnpm --dir spikes/godot-jolt measure -- --dir /tmp/godot-web-out --name threads --isolated ...`, 284.8 s, 종료 코드 0. SSD 여유 11.16 → 7.00 GiB(실행 중 최악 6.99), 스왑 13.88 → 16.79 GiB(실행 중 최악 17.32), 메모리 압력 normal. SSD 감소는 다른 프로세스의 영향과 섞였다(이 실행은 내보낸 폴더를 읽기만 한다).

### OpenXR 지원 상태

| 항목 | 확인 | 근거 |
|---|---|---|
| 엔진에 OpenXR이 있나 | **예** (`OpenXRInterface`, `OpenXRAPIExtension`, `WebXRInterface`, `XROrigin3D`, `XRController3D`, `XRCamera3D`가 이 macOS 바이너리에 모두 있다) | `xr_probe.gd` → `results/a0-03b-xr.json` |
| 이 머신에서 시작되나 | **아니오**. `XRServer`에 `OpenXR`가 등록돼 있고(`interfaces_registered: ["Native mobile","OpenXR"]`) `initialize()` → `false` | 같은 파일. 공식 문서도 "등록됨 = 사용 가능일 뿐, 호스트가 지원하지 않으면 초기화가 실패한다"고 적는다 |
| 왜 | **`initialize()`가 `false`를 돌려줬고 설치된 OpenXR 런타임은 찾지 못했다 [추정: 다른 원인 미배제]**. 근거는 `XR_RUNTIME_JSON` 비어 있음, `/usr/local/share/openxr`·`/etc/xdg/openxr`·`~/.config/openxr` 없음뿐이다. 프로브는 `initialize()`의 반환값만 모으고(`xr_probe.gd`), 같은 결과 JSON에 `xr/openxr/enabled=false`도 기록돼 있으며, 헤드리스 실행이나 초기화 설정 같은 다른 원인은 로더·초기화 오류 로그로 배제하지 않았다. macOS에 대한 일반적 지원 여부는 문서에서 확인하지 못했다 | 위 명령 |
| 공식 지원 범위(문서) | SteamVR로 되는 데스크톱 헤드셋(OpenXR), Quest 링크·Android XR 다이렉트·Pico 커넥트, 안드로이드 독립형 헤드셋(Quest 1/2/3/Pro, Pico 4, Magic Leap 2, Lynx R1, HTC Vive Focus Vision, Android XR), Linux 독립형 Steam Frame, **visionOS는 "제한적: 평면 위 앱만, 몰입형은 아직 안 됨"** | `godot-docs` `about/list_of_features.rst` 4.x 최신(master) |
| 웹 XR | `WebXRInterface` 클래스가 있다. 이번에 브라우저에서 실행하지 않았다 | 클래스 존재만 확인 |
| 실기·에뮬레이터 프레임률 | **측정하지 않았다** (범위 밖. A0-02b는 WebXR 쪽) | |

계획 5.2절의 "OpenXR, 더 강하다 [확인 필요]"에 대한 이번 답: **엔진 지원 문서는 웹 클라이언트(WebXR)보다 폭이 넓다(독립형 헤드셋 직접 지원)는 쪽이지만, 이 머신에서는 런타임이 없어 실제 구동을 확인하지 못했다.** 헤드셋에서의 성능 비교는 하지 않았다.

### 재현 방법

저장소 루트에서(A0-03a와 같은 Godot 바이너리 필요).

```
uv run spikes/godot-jolt/car.py --json spikes/godot-jolt/results/a0-03b-car.json    # 4륜차 2장면 대 MuJoCo
uv run spikes/godot-jolt/test_car.py                                                # 오프라인 점검(Godot 불필요)
godot --headless --path spikes/godot-jolt --script xr_probe.gd                      # OpenXR 상태 한 줄(`XR {json}`)
godot --headless --path spikes/godot-jolt/web --export-release Web /tmp/godot-web-out/index.html   # 웹 내보내기(웹 템플릿 필요)
uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/godot-jolt measure -- --dir /tmp/godot-web-out --name threads --isolated --out spikes/godot-jolt/results/a0-03b-web-threads.json
pnpm --dir spikes/godot-jolt install --frozen-lockfile && pnpm --dir spikes/godot-jolt test   # 서버 단위 시험(CI가 돌린다)
```

`test_car.py`(18건)는 장면 수치 파일이 생성기와 같은지, 경사 출발 높이·각도, MuJoCo 낙하가 착지해 유한하고 전진 속도를 유지하는지, 같은 실행 두 번이 비트 같음, 구동 토크가 오르막 거리를 늘리는지, 차이 계산(0, 위치+회전 값, `q`와 `−q` 같음, 두 궤적의 길이가 다르면 **오류**이지 짧은 쪽에 맞춰 자르지 않음), 측정 구간 단언(`require_full`: 장면의 `steps+1`행·유한 값이 아니면 오류, 두 엔진이 같은 구간을 덮는다), CSV 읽기(스텝 열이 0,1,2,…가 아니면 오류), 웹 장면이 `World3D`를 멤버로 붙잡는지(소스 검사)를 단언한다. 차이의 크기는 단언하지 않는다. pnpm 시험(2건)은 정적 서버의 경로 탈출 거부, COOP/COEP 유무, wasm 타입, 404, 루프백만을 단언한다.

### 의존성 라이선스 (원장)

| 의존성 | 라이선스 | 비고 |
|---|---|---|
| Godot 4.7.2 + 웹 내보내기 템플릿 | MIT | 위 원장 행 `dep-godot-4.7.2`가 템플릿도 같은 릴리스로 포함한다 |
| playwright-core 1.65.0 | Apache-2.0 | 이미 원장에 있음(`dep-playwright-core-1.65.0`). 이 스파이크도 같은 버전을 pnpm으로 고정 |
| mujoco 4.0.0, numpy 2.5.4 | Apache-2.0, BSD-3-Clause | 이미 원장에 있음(`car.py` PEP 723 고정) |

### 알려진 한계 (정직성)

- 장면 2개, 각 1회, 차 하나. 바퀴 마찰은 MuJoCo(구름 마찰 없음)와 Jolt(단일 마찰 계수) 모델이 같지 않아 같은 계수를 줘도 거동이 같지 않다. 차이를 모델 항목별로 분해하지 않았다.
- MuJoCo 쪽은 기본 접촉 설정이고 Godot 쪽은 Jolt 기본값이다. 각자의 기본값이 "자연스러운" 짝이라고 보장하지 않는다. 노이즈 바닥 표가 설정 민감도를 보인다.
- 웹: 번들 크기는 실제 내보낸 파일이다. 스레드 있는 변형은 헤드리스 Chromium에서 시작까지만 되고 물리 실행 중 죽었다(위, 1회). 스레드 없는 변형의 로딩은 [측정 대기: 디스크]이고, `World3D` 수명 수정 뒤 스레드 있는 변형의 재측정도 [측정 대기: 디스크](수정은 미검증). 헤드리스 Chromium(SwiftShader)이므로 실제 GPU 로딩 시간이 아니다.
- OpenXR: 존재와 이 머신의 시작 실패만 확인했다. 헤드셋이 없다.
- 플랫폼 간·다른 버전 간 결정론은 범위 밖(#54 코멘트의 MuJoCo 플랫폼 간 불일치 관찰과 같은 한계가 있을 수 있다).
