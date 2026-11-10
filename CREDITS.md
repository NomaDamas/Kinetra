# CREDITS

<!-- 이 파일은 `tools/assets/credits.py`가 `assets/LEDGER.csv`에서 생성한다. 직접 고치지 않는다. -->

## 에셋 (asset)

(없음)

## 의존성 (dependency)

### dep-mujoco-4.0.0

- 표기: MuJoCo, Copyright Google DeepMind. Apache License 2.0.
- 저작자: Google DeepMind
- 라이선스: Apache-2.0
- 원본: https://pypi.org/project/mujoco/4.0.0/ https://github.com/google-deepmind/mujoco https://github.com/google-deepmind/mujoco/blob/main/LICENSE
- 경로: `spikes/mujoco-limits/scale.py`
- 용도: 실행 의존성: MuJoCo 한계 측정 스파이크(A0-01a)의 물리 시뮬레이션
- 변경 내역: 없음(PEP 723 헤더에서 mujoco==4.0.0 고정, 수정 없이 사용)
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:c503ff7003dd7dfee19b575aed6a409fb9bc15bf9f1c4053892c793e05b5edb3`
- 확인자: omp

### dep-numpy-2.5.4

- 표기: NumPy, Copyright (c) 2005-2026, NumPy Developers. BSD 3-Clause License.
- 저작자: NumPy Developers
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/numpy/2.5.4/ https://github.com/numpy/numpy https://github.com/numpy/numpy/blob/main/LICENSE.txt
- 경로: `spikes/mujoco-limits/scale.py`
- 용도: 실행 의존성: MuJoCo 한계 측정 스파이크(A0-01a)의 수치 계산
- 변경 내역: 없음(PEP 723 헤더에서 numpy==2.5.4 고정, 수정 없이 사용). NumPy 자체의 라이선스는 BSD-3-Clause(저장소 LICENSE.txt). PyPI 메타데이터 license_expression은 휠에 번들된 구성요소까지 합쳐 'BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0'이다
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:9a94cf751c9ad8ebaa835bcd3d40dacf8534ad086b88c38029b65123c7999d2a`
- 확인자: omp

### dep-pyyaml-6.0.3

- 표기: PyYAML, Copyright (c) 2017-2021 Ingy döt Net, (c) 2006-2016 Kirill Simonov. MIT License.
- 저작자: Ingy döt Net; Kirill Simonov
- 라이선스: MIT
- 원본: https://pypi.org/project/PyYAML/6.0.3/ https://github.com/yaml/pyyaml https://github.com/yaml/pyyaml/blob/main/LICENSE
- 경로: `pyproject.toml`
- 용도: 개발 도구: issues.yaml 파싱(GitHub 라벨·마일스톤 부트스트랩, 이슈 일괄 등록)
- 변경 내역: 없음(수정 없이 사용). 루트 pyproject.toml 의 dev 그룹(pyyaml>=6)과 uv.lock 에서 6.0.3 으로 고정, `scripts/gh/bootstrap.sh`·`seed_issues.sh` 는 `uv run --with pyyaml` 로도 실행
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f`
- 확인자: omp
