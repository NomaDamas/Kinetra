# CREDITS

<!-- 이 파일은 `tools/assets/credits.py`가 `assets/LEDGER.csv`에서 생성한다. 직접 고치지 않는다. -->

## 에셋 (asset)

(없음)

## 의존성 (dependency)

### dep-@types/node-26.6.6

- 표기: @types/node, DefinitelyTyped contributors. MIT License.
- 저작자: DefinitelyTyped contributors
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/@types/node/v/26.6.6 https://github.com/DefinitelyTyped/DefinitelyTyped https://github.com/DefinitelyTyped/DefinitelyTyped/blob/master/LICENSE
- 경로: `tools/design/package.json`
- 용도: 개발 도구: tools/design 의 node:* 타입
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. tools/design/package.json 의 devDependencies와 pnpm-lock.yaml 에서 26.6.6 로 고정.
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:7ef006842f7a647868e9d53588148cb058008b107aea6a728143730bee020456`
- 확인자: omp

### dep-@types/pngjs-6.0.5

- 표기: @types/pngjs, DefinitelyTyped contributors. MIT License.
- 저작자: DefinitelyTyped contributors
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/@types/pngjs/v/6.0.5 https://github.com/DefinitelyTyped/DefinitelyTyped https://github.com/DefinitelyTyped/DefinitelyTyped/blob/master/LICENSE
- 경로: `tools/design/package.json`
- 용도: 개발 도구: pngjs 타입(tsc lint)
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. tools/design/package.json 의 devDependencies와 pnpm-lock.yaml 에서 6.0.5 로 고정.
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:db919544cdd5c9bd50928619fee0498341e4c0845b03d38752b510cff3994e07`
- 확인자: omp

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

### dep-mujoco-wasm-4.0.0

- 표기: MuJoCo, Copyright Google DeepMind. Apache License 2.0.
- 저작자: Google DeepMind
- 라이선스: Apache-2.0
- 원본: https://www.npmjs.com/package/@mujoco/mujoco/v/4.0.0 https://github.com/google-deepmind/mujoco/tree/4.0.0/wasm https://github.com/google-deepmind/mujoco/blob/main/LICENSE
- 경로: `spikes/mujoco-wasm/package.json`
- 용도: 실행 의존성: 브라우저 WASM 실행과 네이티브 대비 궤적 차이 측정 스파이크(A0-01b). 공식 MuJoCo JavaScript/WASM 바인딩
- 변경 내역: 없음(npm 패키지 @mujoco/mujoco 4.0.0 을 pnpm-lock 으로 고정, 수정 없이 사용). 해시는 `npm pack @mujoco/mujoco@4.0.0` 이 만든 tgz 의 sha256
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:66b97038b28d323dee676cf6c696074ef57e5e6f62521a5f48045ebaebdd27a0`
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

### dep-pixelmatch-8.0.0

- 표기: pixelmatch, Copyright (c) 2025, Mapbox. ISC License.
- 저작자: Mapbox
- 라이선스: ISC
- 원본: https://www.npmjs.com/package/pixelmatch/v/8.0.0 https://github.com/mapbox/pixelmatch https://github.com/mapbox/pixelmatch/blob/main/LICENSE
- 경로: `tools/design/package.json`
- 용도: 개발 도구: 디자인 대조(D0-04)의 픽셀 비교와 차이 이미지
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. tools/design/package.json 의 devDependencies와 pnpm-lock.yaml 에서 8.0.0 로 고정.
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:ab59d4c4ec73fbf456c72cbd8200b1529a76142fd9291de72a62ba6e3a845e75`
- 확인자: omp

### dep-playwright-1.65.0

- 표기: Playwright, Copyright (c) Microsoft Corporation. Apache License 2.0.
- 저작자: Microsoft Corporation
- 라이선스: Apache-2.0
- 원본: https://www.npmjs.com/package/playwright/v/1.65.0 https://github.com/microsoft/playwright https://github.com/microsoft/playwright/blob/main/LICENSE
- 경로: `spikes/mujoco-wasm/package.json`
- 용도: 개발 도구: A0-01b 측정 페이지를 헤드리스 Chromium 에서 구동해 프레임률과 궤적을 수집(measure.mjs)
- 변경 내역: 없음(devDependency, pnpm-lock 으로 고정, 수정 없이 사용). 해시는 `npm pack playwright@1.65.0` tgz 의 sha256. 추이 의존성 playwright-core 1.65.0 도 Apache-2.0. 브라우저는 `playwright install chromium-headless-shell` 로 받은 Playwright 자체 빌드(Chrome Headless Shell 158.0.8127.18)이며 저장소에 넣지 않음
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:5c535e6d0b00411c7b926f2f39aeaa80b9daa9ccfa2dd5c21db718cd8808aa42`
- 확인자: omp

### dep-playwright-core-1.65.0

- 표기: Playwright, Copyright (c) Microsoft Corporation. Apache License 2.0.
- 저작자: Microsoft Corporation
- 라이선스: Apache-2.0
- 원본: https://www.npmjs.com/package/playwright-core/v/1.65.0 https://github.com/microsoft/playwright https://github.com/microsoft/playwright/blob/main/LICENSE
- 경로: `tools/design/package.json`
- 용도: 개발 도구: 디자인 대조(D0-04)의 헤드리스 Chromium 스크린샷. 브라우저 바이너리는 Playwright 캐시(~/Library/Caches/ms-playwright 의 chromium_headless_shell-1254)이며 저장소에 들어오지 않는다
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. tools/design/package.json 의 devDependencies와 pnpm-lock.yaml 에서 1.65.0 로 고정.
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:315247c55a793ca760b2f05bdcee0e6a53fd65b1f22d1d3de8323c8c9395add3`
- 확인자: omp

### dep-pngjs-7.0.0

- 표기: pngjs, Copyright (c) 2015 Luke Page & Original Contributors, (c) 2012 Kuba Niegowski. MIT License.
- 저작자: Luke Page; Kuba Niegowski; pngjs contributors
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/pngjs/v/7.0.0 https://github.com/pngjs/pngjs https://github.com/pngjs/pngjs/blob/master/LICENSE
- 경로: `tools/design/package.json`
- 용도: 개발 도구: 디자인 대조(D0-04)의 PNG 읽기·쓰기
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. tools/design/package.json 의 devDependencies와 pnpm-lock.yaml 에서 7.0.0 로 고정.
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:c4b71873d48a692dd5eeb1dcb62185c7aafe40f2180c7cc7f30ec71e89a080be`
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

### dep-typescript-7.0.2

- 표기: TypeScript, Copyright (c) Microsoft Corporation. Apache License 2.0.
- 저작자: Microsoft Corp.
- 라이선스: Apache-2.0
- 원본: https://www.npmjs.com/package/typescript/v/7.0.2 https://github.com/microsoft/TypeScript https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt
- 경로: `tools/design/package.json`
- 용도: 개발 도구: tools/design 의 타입 검사(lint)
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. tools/design/package.json 의 devDependencies와 pnpm-lock.yaml 에서 7.0.2 로 고정.
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:da2513f4b95176d6dde8b51aab7afe8a927656c9d277369793f77f7e59371c08`
- 확인자: omp
