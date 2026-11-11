# CREDITS

<!-- 이 파일은 `tools/assets/credits.py`가 `assets/LEDGER.csv`에서 생성한다. 직접 고치지 않는다. -->

## 에셋 (asset)

### asset-acg-NightSkyHDRI008-1k

- 표기: Night Sky HDRI 008, ambientCG.com. CC0 1.0.
- 저작자: ambientCG
- 라이선스: CC0-1.0
- 원본: https://ambientcg.com/a/NightSkyHDRI008 https://ambientcg.com/get?file=NightSkyHDRI008_1K.zip https://docs.ambientcg.com/license/
- 경로: `assets/scene/moon/NightSkyHDRI008_1K_HDR.exr`
- 용도: HDRI(하늘과 조명): 달 평지의 검은 하늘과 별. 대기가 없는 하늘의 시각 대용이며 달에서 본 실제 별자리가 아니다. W-02c 가 쓴다
- 변경 내역: 없음(ambientCG 의 NightSkyHDRI008_1K.zip(sha256:68cdee7909e0b22a8495da003190e2c6dbc63f68a6b6cbce343733be2b2818d9)에서 NightSkyHDRI008_1K_HDR.exr 한 파일만 꺼내 수정 없이 사용, 나머지 zip 내용은 저장소에 넣지 않음). ambientCG 는 에셋을 CC0 1.0 으로 배포한다(https://docs.ambientcg.com/license/)
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:6ef147a43547248fca1954e82dea8744e35477c49c7dd768a0362bc224f856e2`
- 확인자: omp

### asset-fleurs-ko-1701

- 표기: FLEURS (Google), Copyright Google LLC, CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ . 변경: 16 kHz mono FLAC 로 변환.
- 저작자: Alexis Conneau et al. (Google)
- 라이선스: CC-BY-4.0
- 원본: https://huggingface.co/datasets/google/fleurs https://arxiv.org/abs/2205.12446 https://creativecommons.org/licenses/by/4.0/
- 경로: `packages/engine/tests/fixtures/stt/fleurs-ko-1701.flac`
- 용도: 테스트 픽스처: 한국어 받아쓰기(I-01a) 고정 음성의 인식 결과 단언. packages/engine/tests/test_stt.py
- 변경 내역: 16 kHz mono 16-bit FLAC 로 변환(ffmpeg -ar 16000 -ac 1 -sample_fmt s16). 내용은 자르거나 고치지 않았다. 원본은 google/fleurs ko_kr test 의 id 1701 음성(float WAV 16 kHz)이고 원본 해시는 그 WAV 의 sha256 이라 저장소 파일과 비교하지 않는다. 창업자 승인(approved_by: founder, 2026-11-11, CC0 가 아닌 에셋): https://github.com/NomaDamas/Kinetra/pull/483 의 승인 코멘트
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:989020dedbda7fa529b0b4e876f236e79b25a2915d093e23de94c8456e72b7b4`
- 확인자: omp

### asset-fleurs-ko-1883

- 표기: FLEURS (Google), Copyright Google LLC, CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ . 변경: 16 kHz mono FLAC 로 변환.
- 저작자: Alexis Conneau et al. (Google)
- 라이선스: CC-BY-4.0
- 원본: https://huggingface.co/datasets/google/fleurs https://arxiv.org/abs/2205.12446 https://creativecommons.org/licenses/by/4.0/
- 경로: `packages/engine/tests/fixtures/stt/fleurs-ko-1883.flac`
- 용도: 테스트 픽스처: 한국어 받아쓰기(I-01a) 고정 음성의 인식 결과 단언. packages/engine/tests/test_stt.py
- 변경 내역: 16 kHz mono 16-bit FLAC 로 변환(ffmpeg -ar 16000 -ac 1 -sample_fmt s16). 내용은 자르거나 고치지 않았다. 원본은 google/fleurs ko_kr test 의 id 1883 음성(float WAV 16 kHz)이고 원본 해시는 그 WAV 의 sha256 이라 저장소 파일과 비교하지 않는다. 창업자 승인(approved_by: founder, 2026-11-11, CC0 가 아닌 에셋): https://github.com/NomaDamas/Kinetra/pull/483 의 승인 코멘트
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:e6bc095e55046de927d7c937f036f96ebb506570648ad9ae7c6576febfc4746a`
- 확인자: omp

### asset-fleurs-ko-1929

- 표기: FLEURS (Google), Copyright Google LLC, CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ . 변경: 16 kHz mono FLAC 로 변환.
- 저작자: Alexis Conneau et al. (Google)
- 라이선스: CC-BY-4.0
- 원본: https://huggingface.co/datasets/google/fleurs https://arxiv.org/abs/2205.12446 https://creativecommons.org/licenses/by/4.0/
- 경로: `packages/engine/tests/fixtures/stt/fleurs-ko-1929.flac`
- 용도: 테스트 픽스처: 한국어 받아쓰기(I-01a) 고정 음성의 인식 결과 단언. packages/engine/tests/test_stt.py
- 변경 내역: 16 kHz mono 16-bit FLAC 로 변환(ffmpeg -ar 16000 -ac 1 -sample_fmt s16). 내용은 자르거나 고치지 않았다. 원본은 google/fleurs ko_kr test 의 id 1929 음성(float WAV 16 kHz)이고 원본 해시는 그 WAV 의 sha256 이라 저장소 파일과 비교하지 않는다. 창업자 승인(approved_by: founder, 2026-11-11, CC0 가 아닌 에셋): https://github.com/NomaDamas/Kinetra/pull/483 의 승인 코멘트
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:a5a400dda19a17f0ceb0c4a2542387ae376e3f0518ba0f9769564402df55affd`
- 확인자: omp

### asset-ph-grass_ground-diff-1k

- 표기: grass_ground (albedo(색)), Charlotte Baglioni, Poly Haven. CC0 1.0.
- 저작자: Charlotte Baglioni
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/grass_ground/grass_ground_diff_1k.jpg https://polyhaven.com/a/grass_ground https://api.polyhaven.com/files/grass_ground https://polyhaven.com/license
- 경로: `assets/scene/earth/grass_ground_diff_1k.jpg`
- 용도: 시각(지면 재질): 지구 평지 지면 albedo(색). 풀과 흙. W-02a 가 쓴다
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:a79cc5ed65af0f80261b39a383b64a8c5272c5144d724deb43dbc29f0e4cd19b`
- 확인자: omp

### asset-ph-grass_ground-nor_gl-1k

- 표기: grass_ground (법선(OpenGL, Y+)), Charlotte Baglioni, Poly Haven. CC0 1.0.
- 저작자: Charlotte Baglioni
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/grass_ground/grass_ground_nor_gl_1k.jpg https://polyhaven.com/a/grass_ground https://api.polyhaven.com/files/grass_ground https://polyhaven.com/license
- 경로: `assets/scene/earth/grass_ground_nor_gl_1k.jpg`
- 용도: 시각(지면 재질): 지구 평지 지면 법선(OpenGL, Y+). 풀과 흙. W-02a 가 쓴다
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:7000e2ccd479bb7b66dcdf4faef7b47554324566886314ca620cbf03e274e826`
- 확인자: omp

### asset-ph-grass_ground-rough-1k

- 표기: grass_ground (거칠기), Charlotte Baglioni, Poly Haven. CC0 1.0.
- 저작자: Charlotte Baglioni
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/grass_ground/grass_ground_rough_1k.jpg https://polyhaven.com/a/grass_ground https://api.polyhaven.com/files/grass_ground https://polyhaven.com/license
- 경로: `assets/scene/earth/grass_ground_rough_1k.jpg`
- 용도: 시각(지면 재질): 지구 평지 지면 거칠기. 풀과 흙. W-02a 가 쓴다
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:111341f948b7e073edf7ac6add8777e1bf10df8959400df3863243e89bbc8c08`
- 확인자: omp

### asset-ph-kloofendal_43d_clear_puresky-1k

- 표기: kloofendal_43d_clear_puresky, Greg Zaal, Poly Haven. CC0 1.0.
- 저작자: Greg Zaal
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/kloofendal_43d_clear_puresky_1k.hdr https://polyhaven.com/a/kloofendal_43d_clear_puresky https://api.polyhaven.com/files/kloofendal_43d_clear_puresky https://polyhaven.com/license
- 경로: `assets/scene/earth/kloofendal_43d_clear_puresky_1k.hdr`
- 용도: HDRI(하늘과 조명): 지구 평지. 맑은 낮 하늘(지평선 아래 지면을 뺀 pure sky). W-02a 가 쓴다
- 변경 내역: 없음(Poly Haven 1k hdr 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:de7ba9d0b070470dbb70d0144294c8708068df353537b26ab59c394707e84377`
- 확인자: omp

### asset-ph-moon_01-diff-1k

- 표기: moon_01 (albedo(색)), Greg Zaal; Rico Cilliers; Jenelle van Heerden (촬영), Dario Barresi (가공), Poly Haven. CC0 1.0.
- 저작자: Greg Zaal; Rico Cilliers; Jenelle van Heerden (촬영), Dario Barresi (가공)
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/moon_01/moon_01_diff_1k.jpg https://polyhaven.com/a/moon_01 https://api.polyhaven.com/files/moon_01 https://polyhaven.com/license
- 경로: `assets/scene/moon/moon_01_diff_1k.jpg`
- 용도: 시각(지면 재질): 달 평지 지면 albedo(색). 달 레골리스 모사토(simulant, Spaceport Rostock 실험실에서 지구 암석 분말을 촬영). 달 표면의 측정 사진이 아니다(시각 대용). W-02c 가 쓴다
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:ebe99635c8babc05620fb532eba8459b9168b5b09f9704e320938c231900ed62`
- 확인자: omp

### asset-ph-moon_01-nor_gl-1k

- 표기: moon_01 (법선(OpenGL, Y+)), Greg Zaal; Rico Cilliers; Jenelle van Heerden (촬영), Dario Barresi (가공), Poly Haven. CC0 1.0.
- 저작자: Greg Zaal; Rico Cilliers; Jenelle van Heerden (촬영), Dario Barresi (가공)
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/moon_01/moon_01_nor_gl_1k.jpg https://polyhaven.com/a/moon_01 https://api.polyhaven.com/files/moon_01 https://polyhaven.com/license
- 경로: `assets/scene/moon/moon_01_nor_gl_1k.jpg`
- 용도: 시각(지면 재질): 달 평지 지면 법선(OpenGL, Y+). 달 레골리스 모사토(simulant, Spaceport Rostock 실험실에서 지구 암석 분말을 촬영). 달 표면의 측정 사진이 아니다(시각 대용). W-02c 가 쓴다
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:cd0f110d7a5079fa2ae3739f91cad85480b5314fd2b414998a08f1f444c6a110`
- 확인자: omp

### asset-ph-moon_01-rough-1k

- 표기: moon_01 (거칠기), Greg Zaal; Rico Cilliers; Jenelle van Heerden (촬영), Dario Barresi (가공), Poly Haven. CC0 1.0.
- 저작자: Greg Zaal; Rico Cilliers; Jenelle van Heerden (촬영), Dario Barresi (가공)
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/moon_01/moon_01_rough_1k.jpg https://polyhaven.com/a/moon_01 https://api.polyhaven.com/files/moon_01 https://polyhaven.com/license
- 경로: `assets/scene/moon/moon_01_rough_1k.jpg`
- 용도: 시각(지면 재질): 달 평지 지면 거칠기. 달 레골리스 모사토(simulant, Spaceport Rostock 실험실에서 지구 암석 분말을 촬영). 달 표면의 측정 사진이 아니다(시각 대용). W-02c 가 쓴다
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:483d2254502ddfd8a2310ec623418477e8a55e4d150717aef049ab3588506ba6`
- 확인자: omp

### asset-ph-syferfontein_1d_clear_puresky-1k

- 표기: syferfontein_1d_clear_puresky, Greg Zaal (원본), Jarod Guest (하늘 편집), Poly Haven. CC0 1.0.
- 저작자: Greg Zaal (원본), Jarod Guest (하늘 편집)
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/syferfontein_1d_clear_puresky_1k.hdr https://polyhaven.com/a/syferfontein_1d_clear_puresky https://api.polyhaven.com/files/syferfontein_1d_clear_puresky https://polyhaven.com/license
- 경로: `assets/scene/mars/syferfontein_1d_clear_puresky_1k.hdr`
- 용도: HDRI(하늘과 조명): 화성 평지. 지평선 근처 낮은 해의 맑은 하늘. 화성의 하늘 색을 재현하지 않는 시각 대용이다. W-02b 가 쓴다
- 변경 내역: 없음(Poly Haven 1k hdr 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:d598873ab0acb88af990c54fd7a1634564d9ead0d5fd36f7a40da38c90632de2`
- 확인자: omp

### asset-ph-terrain_red_01-diff-1k

- 표기: terrain_red_01 (albedo(색)), Rob Tuytel, Poly Haven. CC0 1.0.
- 저작자: Rob Tuytel
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/terrain_red_01/terrain_red_01_diff_1k.jpg https://polyhaven.com/a/terrain_red_01 https://api.polyhaven.com/files/terrain_red_01 https://polyhaven.com/license
- 경로: `assets/scene/mars/terrain_red_01_diff_1k.jpg`
- 용도: 시각(지면 재질): 화성 평지 지면 albedo(색). 붉은 흙과 자갈. W-02b 가 쓴다. 화성 표면의 측정 사진이 아니라 지구의 붉은 지면 사진이다(시각 대용)
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:f3f3fa6ebcddce22ece1fc8a343b469cbf67faefafac453ba53bce1fa28fc4b0`
- 확인자: omp

### asset-ph-terrain_red_01-nor_gl-1k

- 표기: terrain_red_01 (법선(OpenGL, Y+)), Rob Tuytel, Poly Haven. CC0 1.0.
- 저작자: Rob Tuytel
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/terrain_red_01/terrain_red_01_nor_gl_1k.jpg https://polyhaven.com/a/terrain_red_01 https://api.polyhaven.com/files/terrain_red_01 https://polyhaven.com/license
- 경로: `assets/scene/mars/terrain_red_01_nor_gl_1k.jpg`
- 용도: 시각(지면 재질): 화성 평지 지면 법선(OpenGL, Y+). 붉은 흙과 자갈. W-02b 가 쓴다. 화성 표면의 측정 사진이 아니라 지구의 붉은 지면 사진이다(시각 대용)
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:97b57469b655d40c2e4c39b7c5f8deb9cbaee2af16c0ee19cd85f435f48f1da6`
- 확인자: omp

### asset-ph-terrain_red_01-rough-1k

- 표기: terrain_red_01 (거칠기), Rob Tuytel, Poly Haven. CC0 1.0.
- 저작자: Rob Tuytel
- 라이선스: CC0-1.0
- 원본: https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/terrain_red_01/terrain_red_01_rough_1k.jpg https://polyhaven.com/a/terrain_red_01 https://api.polyhaven.com/files/terrain_red_01 https://polyhaven.com/license
- 경로: `assets/scene/mars/terrain_red_01_rough_1k.jpg`
- 용도: 시각(지면 재질): 화성 평지 지면 거칠기. 붉은 흙과 자갈. W-02b 가 쓴다. 화성 표면의 측정 사진이 아니라 지구의 붉은 지면 사진이다(시각 대용)
- 변경 내역: 없음(Poly Haven 1k jpg 를 수정 없이 사용). Poly Haven 은 모든 에셋을 CC0 로 배포한다(https://polyhaven.com/license). 받은 파일의 md5 는 Poly Haven files API 가 알려 준 값과 일치
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:d28d3cb3cb1cff885eff978ebab96e2e887aad9c82294978554bc09ae00b2832`
- 확인자: omp

## 의존성 (dependency)

### dep-@pmndrs/handle-6.6.32

- 표기: @pmndrs/handle, Copyright 2024 Bela Bohlender; Copyright 2023 Coconut Capital. MIT License.
- 저작자: Bela Bohlender; Coconut Capital
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/@pmndrs/handle/v/6.6.32 https://github.com/pmndrs/xr https://github.com/pmndrs/xr/blob/main/LICENSE
- 경로: `spikes/webxr/package.json`
- 용도: 실행 의존성: WebXR 스파이크(A0-02b)의 잡고 옮기기(HandleStore). 부품 하나를 컨트롤러로 잡아 옮긴다
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. spikes/webxr/package.json 의 dependencies 와 pnpm-lock.yaml 에서 6.6.32 로 고정. package.json 의 license 필드는 'SEE LICENSE IN LICENSE' 이고 패키지에 든 LICENSE 파일 본문은 MIT 라이선스(Copyright 2024 Bela Bohlender; Copyright 2023 Coconut Capital)다
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:30f1aef478daa0baeee96289fe22f9d75fd94d0fff3f9ad3331b4ddde79b5a0c`
- 확인자: omp

### dep-@pmndrs/pointer-events-6.6.32

- 표기: @pmndrs/pointer-events, Copyright 2024 Bela Bohlender; Copyright 2023 Coconut Capital. MIT License.
- 저작자: Bela Bohlender; Coconut Capital
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/@pmndrs/pointer-events/v/6.6.32 https://github.com/pmndrs/xr https://github.com/pmndrs/xr/blob/main/LICENSE
- 경로: `spikes/webxr/package.json`
- 용도: 실행 의존성: WebXR 스파이크(A0-02b)의 오프라인 테스트가 실제 grab 포인터를 쓴다. @pmndrs/xr 과 @pmndrs/handle 의 추이 의존성이기도 하다
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. spikes/webxr/package.json 의 dependencies 와 pnpm-lock.yaml 에서 6.6.32 로 고정. package.json 의 license 필드는 'SEE LICENSE IN LICENSE' 이고 패키지에 든 LICENSE 파일 본문은 MIT 라이선스(Copyright 2024 Bela Bohlender; Copyright 2023 Coconut Capital)다
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:abe6e4e612e621647cbeda56e82394b393573724dc258286baf7e5877bb3a634`
- 확인자: omp

### dep-@pmndrs/xr-6.6.32

- 표기: @pmndrs/xr, Copyright 2024 Bela Bohlender; Copyright 2023 Coconut Capital. MIT License.
- 저작자: Bela Bohlender; Coconut Capital
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/@pmndrs/xr/v/6.6.32 https://github.com/pmndrs/xr https://github.com/pmndrs/xr/blob/main/LICENSE
- 경로: `spikes/webxr/package.json`
- 용도: 실행 의존성: WebXR 스파이크(A0-02b)의 three.js XR 입력(컨트롤러 포인터 이벤트)과 세션 진입. 추이 의존성 zustand 4.5.7, meshline 3.3.1, @iwer/devui 1.1.2, @iwer/sem 0.2.5(모두 MIT)는 이 패키지의 것이다
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. spikes/webxr/package.json 의 dependencies 와 pnpm-lock.yaml 에서 6.6.32 로 고정. package.json 의 license 필드는 'SEE LICENSE IN LICENSE' 이고 패키지에 든 LICENSE 파일 본문은 MIT 라이선스(Copyright 2024 Bela Bohlender; Copyright 2023 Coconut Capital)다
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:0ba098818d9442c9fdf9852c7e3ee59585d245e53842bedc061f03806e7f9bb6`
- 확인자: omp

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

### dep-annotated-types-0.8.0

- 표기: annotated-types, Copyright (c) 2022 the contributors. MIT License.
- 저작자: Adrian Garcia Badaracco; Samuel Colvin; Zac Hatfield-Dodds
- 라이선스: MIT
- 원본: https://pypi.org/project/annotated-types/0.8.0/ https://github.com/annotated-types/annotated-types
- 경로: `packages/core/pyproject.toml`
- 용도: pydantic 의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). packages/core/pyproject.toml 의 pydantic>=2.14,<3 과 uv.lock 에서 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:13b2beaad985e05e2d6407ee4c4f35590b11f8d693a258a561055cac8f64cab7`
- 확인자: omp

### dep-anyio-4.16.0

- 표기: anyio, MIT.
- 저작자: Alex Grönholm
- 라이선스: MIT
- 원본: https://pypi.org/project/anyio/4.16.0/ https://github.com/agronholm/anyio
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: httpx2 이(가) 요구하며 uv.lock 에서 4.16.0 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:59bb03251907983d1603d27c3087ddb1e93299ea2163adcdba37899a4fb12ffb`
- 확인자: omp

### dep-attrs-26.1.0

- 표기: attrs, Copyright (c) 2015 Hynek Schlawack and the attrs contributors. MIT License.
- 저작자: Hynek Schlawack; attrs contributors
- 라이선스: MIT
- 원본: https://pypi.org/project/attrs/26.1.0/ https://github.com/python-attrs/attrs
- 경로: `pyproject.toml`
- 용도: jsonschema 의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 루트 pyproject.toml 의 dev 그룹(jsonschema>=4.26)과 uv.lock 에서 26.1.0 로 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:d03ceb89cb322a8fd706d4fb91940737b6642aa36998fe130a9bc96c985eff32`
- 확인자: omp

### dep-av-18.1.0

- 표기: PyAV, Copyright (c) 2008-2023 Mike Boers, Jeremy Lainé and contributors. BSD-3-Clause License. 휠에 번들된 FFmpeg, libx264, libx265 는 각각 LGPL/GPL 이다(결정 대기: I-01c).
- 저작자: PyAV contributors
- 라이선스: BSD-3-Clause AND LGPL-2.1-or-later AND GPL-2.0-or-later
- 원본: https://pypi.org/project/av/18.1.0/ https://github.com/PyAV-Org/PyAV https://github.com/PyAV-Org/PyAV/blob/main/LICENSE.txt
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 받아쓰기 입력 오디오 디코딩(wav, mp3, ogg, webm/opus, m4a)
- 변경 내역: 없음(수정 없이 사용). faster-whisper 1.2.1 의 의존성이며 packages/engine/pyproject.toml 의 `av>=11,<19` 와 uv.lock 에서 18.1.0 으로 고정(faster-whisper 1.2.1 이 av 19 가 없앤 av.open(metadata_errors=...)를 부른다). 해시는 sdist. **휠은 실제로 배포되는 묶음 기준으로 GPL-2.0-or-later 다.** 위 표현식은 그 묶음의 구성요소를 모두 적은 것이다(PyAV 코드 BSD-3-Clause, FFmpeg 계열 LGPL, libx264/libx265 GPL-2.0-or-later). libx264 와 libx265 가 같은 휠 안에서 libavcodec 에 링크되므로 휠 전체를 받는 쪽에 유효한 조건은 GPL 쪽이다. PyAV 코드는 BSD-3-Clause 이고 번들 FFmpeg 는 `--enable-version3`(LGPL-3.0-or-later 로 구성, avcodec_license() 가 `LGPL version 3 or later`, `--enable-gpl` 없음)이지만 같은 휠에 별도 공유 라이브러리로 libx264 와 libx265(둘 다 GPL-2.0-or-later 로 배포)가 들어 있고 libavcodec 이 링크한다(macOS arm64 휠 `otool -L` 과 Linux x86-64 휠 av.libs 목록에서 확인). 상류 유지보수자는 휠을 "LGPLv2.1+ OR GPLv2+"로 설명한다(PyAV-Org/PyAV#2270). `import av` 하면 GPL 라이브러리가 프로세스에 올라온다. 배포(설치 프로그램, 이미지, 호스팅 빌드) 전에 창업자 결정이 필요하다: 이슈 [I-01c] PyAV 휠의 GPL 구성요소 배포 결정. 그 전까지 개발 환경(uv sync)에서만 쓴다. LicenseRef 가 아니라 SPDX 표현식으로 적었다
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:47bfc286e1bc9de7ab4681fc2b575cd2460a66919d31ffe1bd5aa54fae531a28`
- 확인자: omp

### dep-click-8.5.1

- 표기: click, BSD-3-Clause.
- 저작자: Pallets
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/click/8.5.1/ https://github.com/pallets/click
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: huggingface-hub 이(가) 요구하며 uv.lock 에서 8.5.1 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:9bbfada76703fd1d784b83eea012e3e8c6a001a876543ef104fa56aaaeb072b4`
- 확인자: omp

### dep-ctranslate2-4.9.0

- 표기: CTranslate2, Copyright (c) 2018 OpenNMT. MIT License. Linux 휠: Intel oneMKL (Intel Simplified Software License), oneDNN (Apache-2.0), libgomp (GPL-3.0-or-later WITH GCC-exception-3.1).
- 저작자: OpenNMT / SYSTRAN
- 라이선스: MIT AND Apache-2.0 AND LicenseRef-Intel-ISSL AND GPL-3.0-or-later WITH GCC-exception-3.1
- 원본: https://pypi.org/project/ctranslate2/4.9.0/ https://github.com/OpenNMT/CTranslate2 https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: Whisper 모델 추론 엔진(CPU int8). 로컬 받아쓰기(I-01a)
- 변경 내역: 없음(수정 없이 사용). faster-whisper 1.2.1 의 의존성(ctranslate2<5,>=4.0)이며 uv.lock 에서 4.9.0 으로 고정. 해시는 macOS arm64 cp312 휠(sdist 없음). 다른 플랫폼의 휠 해시는 uv.lock. LicenseRef 사유: ctranslate2 자체는 MIT 이다. **Linux x86-64 휠(CI 와 배포가 설치하는 것, sha256 5d9b3edd73ba665f16a19cd3a498ce74fbfb6204bc0ac321f00f2600a41e8810)의 libctranslate2 에는 Intel oneMKL(바이너리로 정적 포함, 문자열 `Intel oneMKL …`)과 oneDNN(Apache-2.0)이 들어 있고 libgomp(GPL-3.0-or-later WITH GCC-exception-3.1, SBOM: almalinux libgomp 8.5.0)가 함께 온다.** oneMKL 은 Intel Simplified Software License(October 2022, https://www.intel.com/content/www/us/en/developer/articles/license/end-user-license-agreement.html)이다: 바이너리 재배포를 허용하되 저작권 고지와 약관을 배포물과 문서에 재현해야 하고(휠에는 그 라이선스 파일이 없다 [확인 필요]), 이름을 홍보에 쓸 수 없으며, 역공학·수정이 금지된다. 로열티와 재배포 수 제한은 없다(Intel oneMKL License FAQ 2019, `인용`). macOS arm64 휠에는 MKL 이 없다(Accelerate/Ruy 경로, libctranslate2.4.9.0.dylib 만 번들). 재배포하는 순간(S1 에는 없음) 고지문을 만들어야 한다
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:ca2cc29f5d561e231c15e9e97b13dcbd1913d6615b727fafa1eeffcb0c1f242a`
- 확인자: omp

### dep-esbuild-0.28.2

- 표기: esbuild, Copyright (c) 2020 Evan Wallace. MIT License.
- 저작자: Evan Wallace
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/esbuild/v/0.28.2 https://github.com/evanw/esbuild https://github.com/evanw/esbuild/blob/main/LICENSE.md
- 경로: `spikes/webxr/package.json`
- 용도: 개발 도구: WebXR 스파이크(A0-02b)의 페이지 번들(build.mjs). 번들은 dist/ 에 만들어지고 저장소에 들어오지 않는다
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. spikes/webxr/package.json 의 devDependencies 와 pnpm-lock.yaml 에서 0.28.2 로 고정. 플랫폼 바이너리 @esbuild/darwin-arm64 0.28.2(MIT)는 이 패키지의 선택 의존성
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:e045f94c235c7adc50e77ba2a579c7bec41b496b6b47c3a7845f7c1e19959a88`
- 확인자: omp

### dep-esbuild-0.28.2-web-client

- 표기: esbuild, Copyright (c) 2020 Evan Wallace. MIT License.
- 저작자: Evan Wallace
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/esbuild/v/0.28.2 https://github.com/evanw/esbuild https://github.com/evanw/esbuild/blob/main/LICENSE.md
- 경로: `spikes/web-client/package.json`
- 용도: 개발 도구: A0-02c 공유 페이지 스크립트(three.js 포함)를 하나의 번들로 묶고 줄이는 빌드. 측정용 스파이크이며 제품 코드가 아님
- 변경 내역: 없음(수정 없이 사용). 해시는 `npm pack esbuild@0.28.2` tgz 의 sha256. spikes/web-client/package.json 의 devDependencies 와 pnpm-lock.yaml 에서 0.28.2 로 고정
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:e045f94c235c7adc50e77ba2a579c7bec41b496b6b47c3a7845f7c1e19959a88`
- 확인자: omp

### dep-faster-whisper-1.2.1

- 표기: faster-whisper, Copyright (c) 2023 SYSTRAN. MIT License.
- 저작자: SYSTRAN
- 라이선스: MIT
- 원본: https://pypi.org/project/faster-whisper/1.2.1/ https://github.com/SYSTRAN/faster-whisper https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 한국어 받아쓰기(I-01a) kinetra_engine.stt. 결정과 근거는 docs/decisions/stt.md
- 변경 내역: 없음(수정 없이 사용). packages/engine/pyproject.toml 의 dependencies(faster-whisper==1.2.1)와 uv.lock 에서 고정. 해시는 PyPI 의 py3-none-any 휠(sdist 없음). 휠에 Silero VAD v6 ONNX(MIT)가 들어 있다
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:79a66ad50688c0b794dd501dc340a736992a6342f7f95e5811be60b5224a26a7`
- 확인자: omp

### dep-filelock-4.2.10

- 표기: filelock, MIT.
- 저작자: Bernát Gábor and contributors
- 라이선스: MIT
- 원본: https://pypi.org/project/filelock/4.2.10/ https://github.com/tox-dev/filelock
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: huggingface-hub 이(가) 요구하며 uv.lock 에서 4.2.10 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:fcc3c0cb8bfe7f4b3bb0e231c04b15dbad068cb3c2515f343d8fde4dce93bd5d`
- 확인자: omp

### dep-flatbuffers-25.12.19

- 표기: flatbuffers, Apache-2.0.
- 저작자: Google (Derek Bailey)
- 라이선스: Apache-2.0
- 원본: https://pypi.org/project/flatbuffers/25.12.19/ https://github.com/google/flatbuffers
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: onnxruntime 이(가) 요구하며 uv.lock 에서 25.12.19 로 고정(루트는 faster-whisper). 해시는 PyPI 휠 flatbuffers-25.12.19-py2.py3-none-any.whl(sdist 없음)
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:7634f50c427838bb021c2d66a3d1168e9d199b0607e6329399f04846d42e20b4`
- 확인자: omp

### dep-fsspec-2026.9.0

- 표기: fsspec, BSD-3-Clause.
- 저작자: Martin Durant and contributors
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/fsspec/2026.9.0/ https://github.com/fsspec/filesystem_spec
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: huggingface-hub 이(가) 요구하며 uv.lock 에서 2026.9.0 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:0f08147951c8cb31d844c3547d631053b127863b60be04cf06e121333ee0e2fe`
- 확인자: omp

### dep-glfw-2.11.0

- 표기: pyGLFW, Copyright (c) 2013-2019 Florian Rhiem. MIT License.
- 저작자: Florian Rhiem
- 라이선스: MIT
- 원본: https://pypi.org/project/glfw/2.11.0/ https://github.com/FlorianRhiem/pyGLFW https://github.com/FlorianRhiem/pyGLFW/blob/master/LICENSE.txt
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: mujoco 4.0.0 이 끌고 오는 추이 의존성(X-01a). 저장소 코드는 창을 열지 않는다
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: mujoco 4.0.0 이(가) 요구하며 uv.lock 에서 2.11.0 으로 고정. 해시는 PyPI sdist. 휠에 GLFW 라이브러리(libglfw, Zlib)가 들어 있다
- 받은 날짜: 2026-11-12
- 원본 해시: `sha256:4bd3a462ed02ae25455dceaeb76d154faf08b48962c0cb2cf685419a34a71305`
- 확인자: omp

### dep-gltf-validator-2.0.0-dev.3.10

- 표기: glTF Validator, Copyright The Khronos Group Inc. Apache License 2.0. 컴파일된 코드에 Dart SDK(Copyright 2012 the Dart project authors, BSD-3-Clause), yaml(Kirill Simonov, MIT), node_preamble(Michael Bullington, MIT), PrismJS(Lea Verou, MIT), vector_math(Andrew Magill 외, Zlib).
- 저작자: The Khronos Group Inc.
- 라이선스: Apache-2.0 AND BSD-3-Clause AND MIT AND Zlib
- 원본: https://www.npmjs.com/package/gltf-validator/v/2.0.0-dev.3.10 https://github.com/KhronosGroup/glTF-Validator https://github.com/KhronosGroup/glTF-Validator/blob/main/LICENSE
- 경로: `tools/gltf-check/package.json`
- 용도: 테스트 도구: B-01c 부품 glTF 를 Khronos 공식 검증기로 검증(tools/gltf-check validate). 제품 코드에 들어가지 않는다
- 변경 내역: 없음(수정 없이 사용). 해시는 npm 배포 tarball 의 sha256. tools/gltf-check/package.json 의 devDependencies 와 pnpm-lock.yaml 에서 2.0.0-dev.3.10 으로 고정. 패키지 자신은 Apache-2.0, 동봉된 NOTICES 는 컴파일된 JS 에 들어 있는 Dart SDK(BSD-3-Clause, Copyright 2012 the Dart project authors), yaml(MIT, Kirill Simonov), node_preamble(MIT, Michael Bullington), PrismJS(MIT, Lea Verou), vector_math(Zlib, Andrew Magill 의 코드)를 적는다
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:4e03dbdc3bc0d1342afd5d2d7ae341a7e3474502ccb872b02dbbaddaee0fdec6`
- 확인자: omp

### dep-godot-4.7.2

- 표기: Godot Engine, Copyright (c) 2014-present Godot Engine contributors, (c) 2007-2014 Juan Linietsky, Ariel Manzur. MIT License. Jolt Physics, Copyright (c) 2021 Jorrit Rouwe. MIT License.
- 저작자: Godot Engine contributors; Juan Linietsky, Ariel Manzur (Jolt Physics: Jorrit Rouwe)
- 라이선스: MIT
- 원본: https://godotengine.org/ https://github.com/godotengine/godot/releases/tag/4.7.2-stable https://github.com/godotengine/godot/blob/4.7.2-stable/LICENSE.txt https://github.com/godotengine/godot/blob/4.7.2-stable/thirdparty/README.md
- 경로: `spikes/godot-jolt/scale.py`
- 용도: 실행 의존성: Godot + Jolt 한계 측정 스파이크(A0-03a/b)의 헤드리스 물리 실행과 웹 내보내기. 저장소에 들어오지 않고 제품 코드가 의존하지 않는다
- 변경 내역: 없음(공식 macOS universal 빌드 Godot_v4.7.2-stable_macos.universal.zip 을 수정 없이 사용. 해시는 그 zip 의 sha256; 릴리스의 SHA512-SUMS.txt 와도 일치(sha512 38aa16e5…69ca). 바이너리는 저장소 밖 ~/.cache/kinetra-godot 에 둔다. 번들 Jolt Physics 5.5.0 (MIT, Jorrit Rouwe, thirdparty/jolt_physics)은 같은 바이너리에 들어 있어 별도 행이 없다)
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:c58a24e31d720be9d62f60cb5627c4e695fb72f21b0cfe1bc9ccaa9a3b3ba63e`
- 확인자: omp

### dep-h11-0.16.0

- 표기: h11, MIT.
- 저작자: Nathaniel J. Smith
- 라이선스: MIT
- 원본: https://pypi.org/project/h11/0.16.0/ https://github.com/python-hyper/h11
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: httpcore2 이(가) 요구하며 uv.lock 에서 0.16.0 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:4e35b956cf45792e4caa5885e69fba00bdbc6ffafbfa020300e549b208ee5ff1`
- 확인자: omp

### dep-hf-xet-1.8.0

- 표기: hf-xet, Apache-2.0.
- 저작자: Hugging Face
- 라이선스: Apache-2.0
- 원본: https://pypi.org/project/hf-xet/1.8.0/ https://github.com/huggingface/xet-core
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: huggingface-hub 이(가) 요구하며 uv.lock 에서 1.8.0 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:10ed23b51dacf7917d64f335c25048deb470efa755e9989b218fc0531386138e`
- 확인자: omp

### dep-httpcore2-2.16.0

- 표기: httpcore2, BSD-3-Clause.
- 저작자: Tom Christie
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/httpcore2/2.16.0/ https://github.com/pydantic/httpx2
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: httpx2 이(가) 요구하며 uv.lock 에서 2.16.0 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:c72cd0413563b17e1cd8354677dff887466f8ec2551679759e93126534428643`
- 확인자: omp

### dep-httpx2-2.16.0

- 표기: httpx2, BSD-3-Clause.
- 저작자: Tom Christie
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/httpx2/2.16.0/ https://github.com/pydantic/httpx2
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: huggingface-hub 이(가) 요구하며 uv.lock 에서 2.16.0 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:0d54c98128e8f2ff7fbbde0fca8c359e5f032edeaaaac443cdb7f31f685bcd7f`
- 확인자: omp

### dep-httpx2-jsfetch-1.0

- 표기: httpx2-jsfetch, BSD-3-Clause.
- 저작자: Hood Chatham
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/httpx2-jsfetch/1.0/ https://pypi.org/project/httpx2-jsfetch/1.0/
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: httpx2 이(가) 요구하며 uv.lock 에서 1.0 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:70a0e3eabfef7cce5ad9c629f7d01ca05e418f586646f4ddf14782e4c1454c60`
- 확인자: omp

### dep-huggingface-hub-2.4.0

- 표기: huggingface_hub, Copyright Hugging Face Inc. Apache License 2.0.
- 저작자: Hugging Face
- 라이선스: Apache-2.0
- 원본: https://pypi.org/project/huggingface-hub/2.4.0/ https://github.com/huggingface/huggingface_hub https://github.com/huggingface/huggingface_hub/blob/main/LICENSE
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 고정 리비전의 모델 내려받기와 로컬 캐시 조회(I-01a)
- 변경 내역: 없음(수정 없이 사용). faster-whisper 1.2.1 의 의존성(huggingface-hub>=0.21)이며 uv.lock 에서 고정. 해시는 sdist. `python -m kinetra_engine.stt fetch` 만 네트워크로 모델을 받고, Transcriber 는 local_files_only 로 읽는다
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:13a6158b9e3393d9d3f248ce99074d50c2a0a1449fb9d8e2f710751e2084c188`
- 확인자: omp

### dep-idna-3.20

- 표기: idna, BSD-3-Clause.
- 저작자: Kim Davies
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/idna/3.20/ https://github.com/kjd/idna
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: anyio, httpx2 이(가) 요구하며 uv.lock 에서 3.20 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:a7db850025b95ded1eae8a46181a1a6c56c92c96f0e2b005d9ff8dc0210cab44`
- 확인자: omp

### dep-iwer-2.8.0

- 표기: IWER (Immersive Web Emulation Runtime), Copyright (c) Meta Platforms, Inc. and affiliates. MIT License.
- 저작자: Meta Platforms, Inc. and affiliates (Felix Zhang)
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/iwer/v/2.8.0 https://github.com/meta-quest/immersive-web-emulation-runtime https://github.com/meta-quest/immersive-web-emulation-runtime/blob/main/LICENSE
- 경로: `spikes/webxr/package.json`
- 용도: 실행 의존성: WebXR 스파이크(A0-02b)의 WebXR 에뮬레이터(Meta Quest 3 프로필). 헤드셋 없이 immersive-vr 세션과 컨트롤러를 스크립트로 구동한다
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. spikes/webxr/package.json 의 dependencies 와 pnpm-lock.yaml 에서 2.8.0 으로 고정. 추이 의존성 gl-matrix 3.4.4(MIT), webxr-layers-polyfill 1.1.0(Apache-2.0)
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:dd945dce10f8e8561615214a0015918296c93732d25c1fbd917b7de262cd977a`
- 확인자: omp

### dep-jsonschema-4.26.0

- 표기: jsonschema, Copyright (c) 2013 Julian Berman. MIT License.
- 저작자: Julian Berman
- 라이선스: MIT
- 원본: https://pypi.org/project/jsonschema/4.26.0/ https://github.com/python-jsonschema/jsonschema
- 경로: `pyproject.toml`
- 용도: 개발 의존성: C-01d 의 스키마 검증 테스트(packages/core/tests/test_schema_export.py). 생성한 JSON Schema 가 예시를 받고 잘못된 입력을 거부하는지 확인
- 변경 내역: 없음(수정 없이 사용). 루트 pyproject.toml 의 dev 그룹(jsonschema>=4.26)과 uv.lock 에서 4.26.0 로 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:0c26707e2efad8aa1bfc5b7ce170f3fccc2e4918ff85989ba9ffa9facb2be326`
- 확인자: omp

### dep-jsonschema-specifications-2025.9.1

- 표기: jsonschema-specifications, Copyright (c) 2022 Julian Berman. MIT License.
- 저작자: Julian Berman
- 라이선스: MIT
- 원본: https://pypi.org/project/jsonschema-specifications/2025.9.1/ https://github.com/python-jsonschema/jsonschema-specifications
- 경로: `pyproject.toml`
- 용도: jsonschema 의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 루트 pyproject.toml 의 dev 그룹(jsonschema>=4.26)과 uv.lock 에서 2025.9.1 로 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:b540987f239e745613c7a9176f3edb72b832a4ac465cf02712288397832b5e8d`
- 확인자: omp

### dep-model-faster-whisper-small-536b0662

- 표기: Whisper small (CTranslate2 변환: Systran/faster-whisper-small), Copyright (c) 2022 OpenAI. MIT License.
- 저작자: OpenAI (원 모델), SYSTRAN (CTranslate2 변환)
- 라이선스: MIT
- 원본: https://huggingface.co/Systran/faster-whisper-small/tree/536b0662742c02347bc0e980a01041f333bce120 https://github.com/openai/whisper https://github.com/openai/whisper/blob/main/LICENSE
- 경로: `packages/engine/src/kinetra_engine/stt/transcriber.py`
- 용도: 실행 의존성: 로컬 한국어 받아쓰기 모델(I-01a). 선택 근거와 정확도 한계는 docs/decisions/stt.md
- 변경 내역: 없음(수정 없이 사용). model.bin 의 sha256(483,546,902 B, Hugging Face LFS oid 와 내려받은 파일의 shasum 이 일치). 저장소에 넣지 않고 사용자 캐시(~/.cache/huggingface 또는 KINETRA_STT_MODEL_DIR)에 `python -m kinetra_engine.stt fetch` 로 받는다. 리비전과 해시는 transcriber.py 의 MODEL_REVISION, MODEL_SHA256 이 고정하고 불일치하면 ModelMissing
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`
- 확인자: omp

### dep-mujoco-4.0.0

- 표기: MuJoCo, Copyright Google DeepMind. Apache License 2.0.
- 저작자: Google DeepMind
- 라이선스: Apache-2.0
- 원본: https://pypi.org/project/mujoco/4.0.0/ https://github.com/google-deepmind/mujoco https://github.com/google-deepmind/mujoco/blob/main/LICENSE
- 경로: `spikes/mujoco-limits/scale.py`
- 용도: 실행 의존성: MuJoCo 한계 측정 스파이크(A0-01a)의 물리 시뮬레이션과 물 스파이크(FL-01 spikes/mujoco-water/mujoco_water.py. 같은 고정 버전)
- 변경 내역: 없음(PEP 723 헤더에서 mujoco==4.0.0 고정, 수정 없이 사용)
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:c503ff7003dd7dfee19b575aed6a409fb9bc15bf9f1c4053892c793e05b5edb3`
- 확인자: omp

### dep-mujoco-core-4.0.0

- 표기: MuJoCo (mujoco-core), Copyright Google DeepMind. Apache License 2.0.
- 저작자: Google DeepMind
- 라이선스: Apache-2.0
- 원본: https://pypi.org/project/mujoco-core/4.0.0/ https://github.com/google-deepmind/mujoco https://github.com/google-deepmind/mujoco/blob/main/LICENSE
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: MuJoCo 엔진 코어(X-01a 가 packages/engine 의 의존성 mujoco==4.0.0 으로 추가, 결정은 docs/decisions/engine.md). 컴파일한 MJCF 를 실제 로더로 읽어 geom_size, 질량을 시험한다
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: mujoco 4.0.0 이(가) 요구하며 uv.lock 에서 4.0.0 으로 고정. 해시는 PyPI sdist(uv.lock 의 sdist 항목). mujoco 와 같은 프로젝트의 엔진 코어 배포본
- 받은 날짜: 2026-11-12
- 원본 해시: `sha256:7300cc232f27ceb8694aa45b26c790667eebd4a06286156b49b9726e3bf1d7cf`
- 확인자: omp

### dep-mujoco-studio-4.0.0

- 표기: MuJoCo (mujoco-studio), Copyright Google DeepMind. Apache License 2.0.
- 저작자: Google DeepMind
- 라이선스: Apache-2.0
- 원본: https://pypi.org/project/mujoco-studio/4.0.0/ https://github.com/google-deepmind/mujoco https://github.com/google-deepmind/mujoco/blob/main/LICENSE
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: mujoco 4.0.0 이 끌고 오는 추이 의존성(X-01a). 저장소 코드는 쓰지 않는다
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: mujoco 4.0.0 이(가) 요구하며 uv.lock 에서 4.0.0 으로 고정. 해시는 PyPI sdist. 시각화 도구이고 이 저장소는 import 하지 않는다. mujoco-studio 가 websockets 를 요구하며 uv.lock 은 이미 고정한 17.4 를 쓴다
- 받은 날짜: 2026-11-12
- 원본 해시: `sha256:19714399ab9870e7775018fe343c0b729103a8b9e6c814ad535ec108a74989dd`
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

### dep-numpy-2.4.6

- 표기: numpy, BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0.
- 저작자: NumPy Developers
- 라이선스: BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0
- 원본: https://pypi.org/project/numpy/2.4.6/ https://github.com/numpy/numpy
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성(Python 3.12 미만에서만 이 버전, 이상은 numpy 2.5.4 행): ctranslate2, onnxruntime 이(가) 요구하며 uv.lock 에서 2.4.6 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:f3a3570c4a2a16746ac2c31a7c7c7b0c186b95ce902e33db6f28094ed7387dda`
- 확인자: omp

### dep-numpy-2.5.4

- 표기: NumPy, Copyright (c) 2005-2026, NumPy Developers. BSD 3-Clause License.
- 저작자: NumPy Developers
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/numpy/2.5.4/ https://github.com/numpy/numpy https://github.com/numpy/numpy/blob/main/LICENSE.txt
- 경로: `spikes/mujoco-limits/scale.py`
- 용도: 실행 의존성: MuJoCo 한계 측정 스파이크(A0-01a)의 수치 계산과 물 스파이크(FL-01 spikes/mujoco-water/mujoco_water.py. 같은 고정 버전)
- 변경 내역: 없음(PEP 723 헤더에서 numpy==2.5.4 고정, 수정 없이 사용). NumPy 자체의 라이선스는 BSD-3-Clause(저장소 LICENSE.txt). PyPI 메타데이터 license_expression은 휠에 번들된 구성요소까지 합쳐 'BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0'이다
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:9a94cf751c9ad8ebaa835bcd3d40dacf8534ad086b88c38029b65123c7999d2a`
- 확인자: omp

### dep-onnxruntime-1.31.1

- 표기: ONNX Runtime, Copyright (c) Microsoft Corporation. MIT License.
- 저작자: Microsoft
- 라이선스: MIT
- 원본: https://pypi.org/project/onnxruntime/1.31.1/ https://github.com/microsoft/onnxruntime https://github.com/microsoft/onnxruntime/blob/main/LICENSE
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 음성 구간 검출(Silero VAD) 추론. 로컬 받아쓰기(I-01a)
- 변경 내역: 없음(수정 없이 사용). faster-whisper 1.2.1 의 의존성(onnxruntime<2,>=1.14)이며 uv.lock 에서 고정. 해시는 macOS arm64 cp312 휠(sdist 없음)
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:96dd2564b10ea7153ad9c207e7cd8e5917cb3ba521e0e0a62ac03486fdc8d56c`
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

### dep-protobuf-7.36.2

- 표기: protobuf, BSD-3-Clause.
- 저작자: Google
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/protobuf/7.36.2/ https://github.com/protocolbuffers/protobuf
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: onnxruntime 이(가) 요구하며 uv.lock 에서 7.36.2 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:497d0463ff3316681da6c0b9e8d06cb465d61abce00b613ab42226175644d1bb`
- 확인자: omp

### dep-pydantic-2.14.3

- 표기: pydantic, Copyright (c) 2017 to present Pydantic Services Inc. and individual contributors. MIT License.
- 저작자: Samuel Colvin; Eric Jolibois; Hasan Ramezani; Adrian Garcia Badaracco; pydantic contributors
- 라이선스: MIT
- 원본: https://pypi.org/project/pydantic/2.14.3/ https://github.com/pydantic/pydantic
- 경로: `packages/core/pyproject.toml`
- 용도: 실행 의존성: kinetra-core 의 Project 모델(Material, PartDef)과 JSON Schema 내보내기
- 변경 내역: 없음(수정 없이 사용). packages/core/pyproject.toml 의 pydantic>=2.14,<3 과 uv.lock 에서 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:1054f237f4d4733e5a30e1e2333bd33a2004ab9ab1510bd053a9a31bb48e232d`
- 확인자: omp

### dep-pydantic-core-2.50.4

- 표기: pydantic-core, Copyright (c) 2022 Samuel Colvin. MIT License.
- 저작자: Samuel Colvin; Adrian Garcia Badaracco; David Montague; David Hewitt; Sydney Runkle; Victorien Plot
- 라이선스: MIT
- 원본: https://pypi.org/project/pydantic-core/2.50.4/ https://github.com/pydantic/pydantic/tree/main/pydantic-core
- 경로: `packages/core/pyproject.toml`
- 용도: pydantic 의 추이 의존성(Rust 확장)
- 변경 내역: 없음(수정 없이 사용). packages/core/pyproject.toml 의 pydantic>=2.14,<3 과 uv.lock 에서 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:aead3b74b68396bf0feab5d57e050b730ded7df55853c1e048a87e00aaf033c6`
- 확인자: omp

### dep-pyopengl-3.1.10

- 표기: PyOpenGL, Copyright Mike C. Fletcher and contributors. BSD License.
- 저작자: Mike C. Fletcher
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/pyopengl/3.1.10/ https://github.com/mcfletch/pyopengl https://github.com/mcfletch/pyopengl/blob/master/license.txt
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: mujoco 4.0.0 이 끌고 오는 추이 의존성(X-01a). 저장소 코드는 렌더링하지 않는다
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: mujoco 4.0.0 이(가) 요구하며 uv.lock 에서 3.1.10 으로 고정. 해시는 PyPI sdist. PyPI 분류는 BSD License 이며 SPDX 는 저장소 LICENSE 의 BSD 3조항으로 읽은 값이다 [확인: 리뷰]
- 받은 날짜: 2026-11-12
- 원본 해시: `sha256:c4a02d6866b54eb119c8e9b3fb04fa835a95ab802dd96607ab4cdb0012df8335`
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

### dep-referencing-0.37.0

- 표기: referencing, Copyright (c) 2022 Julian Berman. MIT License.
- 저작자: Julian Berman
- 라이선스: MIT
- 원본: https://pypi.org/project/referencing/0.37.0/ https://github.com/python-jsonschema/referencing
- 경로: `pyproject.toml`
- 용도: jsonschema 의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 루트 pyproject.toml 의 dev 그룹(jsonschema>=4.26)과 uv.lock 에서 0.37.0 로 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:44aefc3142c5b842538163acb373e24cce6632bd54bdb01b21ad5863489f50d8`
- 확인자: omp

### dep-rpds-py-2026.9.1

- 표기: rpds-py, Copyright (c) 2023 Julian Berman. MIT License.
- 저작자: Julian Berman
- 라이선스: MIT
- 원본: https://pypi.org/project/rpds-py/2026.9.1/ https://github.com/crate-py/rpds
- 경로: `pyproject.toml`
- 용도: jsonschema 의 추이 의존성(Rust 확장)
- 변경 내역: 없음(수정 없이 사용). 루트 pyproject.toml 의 dev 그룹(jsonschema>=4.26)과 uv.lock 에서 2026.9.1 로 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:4793ef7f78268b124b73fa933440f01d258bbae01de9fa53e9080c9ab0425a12`
- 확인자: omp

### dep-three-0.187.0

- 표기: three.js, Copyright 2010-2026 three.js authors. MIT License.
- 저작자: three.js authors (mrdoob)
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/three/v/0.187.0 https://github.com/mrdoob/three.js https://github.com/mrdoob/three.js/blob/dev/LICENSE
- 경로: `spikes/webxr/package.json`
- 용도: 실행 의존성: WebXR 스파이크(A0-02b)의 3D 장면과 WebXR 렌더러
- 변경 내역: 없음(수정 없이 사용). npm 배포 tarball 의 sha256. spikes/webxr/package.json 의 dependencies 와 pnpm-lock.yaml 에서 0.187.0 으로 고정. @iwer/devui 와 @iwer/sem 이 추이 의존성으로 three 0.165.0 을 따로 끌어온다(MIT, 번들에는 지연 로딩 조각으로만 들어가고 emulate:false 라 실행되지 않는다)
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:ff540832ded0cfe919764d24a3d88f3e2a05f23303f876423e4f893841e90728`
- 확인자: omp

### dep-three-0.187.0-gltf-check

- 표기: three.js, Copyright (c) 2010-2026 three.js authors. MIT License.
- 저작자: three.js authors
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/three/v/0.187.0 https://github.com/mrdoob/three.js https://github.com/mrdoob/three.js/blob/dev/LICENSE
- 경로: `tools/gltf-check/package.json`
- 용도: 실행 의존성: B-01c 증거 페이지(tools/gltf-check/page)가 GLTFLoader 로 부품 glTF 를 읽어 그린다. 제품 코드가 아님
- 변경 내역: 없음(수정 없이 사용). 해시는 npm 배포 tarball 의 sha256. tools/gltf-check/package.json 의 dependencies 와 pnpm-lock.yaml 에서 0.187.0 으로 고정
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:ff540832ded0cfe919764d24a3d88f3e2a05f23303f876423e4f893841e90728`
- 확인자: omp

### dep-three-0.187.0-web-client

- 표기: three.js, Copyright (c) 2010-2026 three.js authors. MIT License.
- 저작자: three.js authors
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/three/v/0.187.0 https://github.com/mrdoob/three.js https://github.com/mrdoob/three.js/blob/dev/LICENSE
- 경로: `spikes/web-client/package.json`
- 용도: 실행 의존성: A0-02a/A0-02c 측정 페이지의 렌더러(InstancedMesh). 측정용 스파이크이며 제품 코드가 아님
- 변경 내역: 없음(수정 없이 사용). 해시는 `npm pack three@0.187.0` tgz 의 sha256. spikes/web-client/package.json 의 dependencies 와 pnpm-lock.yaml 에서 0.187.0 으로 고정
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:ff540832ded0cfe919764d24a3d88f3e2a05f23303f876423e4f893841e90728`
- 확인자: omp

### dep-tokenizers-0.23.3

- 표기: tokenizers, Copyright Hugging Face Inc. Apache License 2.0.
- 저작자: Hugging Face
- 라이선스: Apache-2.0
- 원본: https://pypi.org/project/tokenizers/0.23.3/ https://github.com/huggingface/tokenizers https://github.com/huggingface/tokenizers/blob/main/LICENSE
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: Whisper 토크나이저(tokenizer.json). 로컬 받아쓰기(I-01a)
- 변경 내역: 없음(수정 없이 사용). faster-whisper 1.2.1 의 의존성(tokenizers<1,>=0.13)이며 uv.lock 에서 고정. 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:cded33237c77caeef62944d32aa9a7ef42bdce2b3497e18d137e072a8c4be438`
- 확인자: omp

### dep-tqdm-4.70.1

- 표기: tqdm, MPL-2.0 AND MIT.
- 저작자: tqdm developers
- 라이선스: MPL-2.0 AND MIT
- 원본: https://pypi.org/project/tqdm/4.70.1/ https://github.com/tqdm/tqdm
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: faster-whisper, huggingface-hub 이(가) 요구하며 uv.lock 에서 4.70.1 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:cefd0eca11b2a37a3aee776544d4f4ae913f02688135b5556b8788dfa474afc4`
- 확인자: omp

### dep-truststore-0.10.5

- 표기: truststore, MIT.
- 저작자: Seth Michael Larson
- 라이선스: MIT
- 원본: https://pypi.org/project/truststore/0.10.5/ https://github.com/sethmlarson/truststore
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 로컬 받아쓰기(I-01a)의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). 추이 의존성: httpcore2, httpx2 이(가) 요구하며 uv.lock 에서 0.10.5 로 고정(루트는 faster-whisper). 해시는 sdist
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:30d36967ccaded5cbb38d602c433f53600036c79d502f4533a49b60a03bbefcd`
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

### dep-typing-extensions-4.16.0

- 표기: typing_extensions, Copyright (c) Python Software Foundation. PSF License 2.0.
- 저작자: Guido van Rossum; Jukka Lehtosalo; Łukasz Langa; Michael Lee
- 라이선스: PSF-2.0
- 원본: https://pypi.org/project/typing-extensions/4.16.0/ https://github.com/python/typing_extensions
- 경로: `packages/core/pyproject.toml`
- 용도: pydantic 의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). packages/core/pyproject.toml 의 pydantic>=2.14,<3 과 uv.lock 에서 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5`
- 확인자: omp

### dep-typing-inspection-0.4.5

- 표기: typing-inspection, Copyright (c) Pydantic Services Inc. 2025 to present. MIT License.
- 저작자: Victorien Plot
- 라이선스: MIT
- 원본: https://pypi.org/project/typing-inspection/0.4.5/ https://github.com/pydantic/typing-inspection
- 경로: `packages/core/pyproject.toml`
- 용도: pydantic 의 추이 의존성
- 변경 내역: 없음(수정 없이 사용). packages/core/pyproject.toml 의 pydantic>=2.14,<3 과 uv.lock 에서 고정. 해시는 PyPI sdist 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:7f16c411e7930dc79596d42ab44672a3fe5f60eb34b781a1647e7872363120c7`
- 확인자: omp

### dep-websockets-17.4

- 표기: websockets, Copyright (c) Aymeric Augustin and contributors. BSD-3-Clause License.
- 저작자: Aymeric Augustin and contributors
- 라이선스: BSD-3-Clause
- 원본: https://pypi.org/project/websockets/17.4/ https://github.com/python-websockets/websockets https://github.com/python-websockets/websockets/blob/main/LICENSE
- 경로: `packages/engine/pyproject.toml`
- 용도: 실행 의존성: 문서 구독과 명령 발행 채널의 WebSocket 전송(C-05a) kinetra_engine.protocol
- 변경 내역: 없음(수정 없이 사용). packages/engine/pyproject.toml 의 dependencies(websockets==17.4)와 uv.lock 에서 고정. 해시는 PyPI sdist. 추이 의존성 없음
- 받은 날짜: 2026-11-12
- 원본 해시: `sha256:09d3939b70df0c8ad2da145ebd50978bccaee1d565e838b0e7921a34d38571eb`
- 확인자: omp

### dep-webxr-input-profiles-assets-1.0.20

- 표기: WebXR Input Profiles, Copyright (c) 2019 Amazon. MIT License.
- 저작자: Amazon (immersive-web community)
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/@webxr-input-profiles/assets/v/1.0.20 https://github.com/immersive-web/webxr-input-profiles https://github.com/immersive-web/webxr-input-profiles/blob/main/LICENSE.md
- 경로: `spikes/webxr/fixtures/profiles`
- 용도: 실행 의존성: WebXR 스파이크(A0-02b)가 컨트롤러 입력 매핑(squeeze = 버튼 1)을 읽는 입력 프로필 JSON. @pmndrs/xr 이 기본으로는 CDN 에서 받는 것을 오프라인 테스트용으로 로컬 서버가 준다
- 변경 내역: 없음(수정 없이 복사). 이 패키지 tarball 의 dist/profiles/profilesList.json (sha256 fe0442d7b206e74d1d3d597ed5a28759e9f0a26d5814dabd179acdf1560b4ad4) 과 dist/profiles/meta-quest-touch-plus/profile.json (sha256 f69041753f555fb91c36d97fd4a58885f3ceb35e2273b179f59cedd464aec688) 두 파일만 spikes/webxr/fixtures/profiles/ 에 넣었다. 컨트롤러 3D 모델(.glb)은 넣지 않았다. 원본 해시는 tarball 의 sha256
- 받은 날짜: 2026-11-11
- 원본 해시: `sha256:30df2a2268220fc0d0e034bed1550aabdd7a2500573c5216f64fc70d59c3d91e`
- 확인자: omp

### dep-ws-8.22.2

- 표기: ws, Copyright (c) 2011 Einar Otto Stangvik; (c) 2013 Arnout Kazemier and contributors; (c) 2016 Luigi Pinca and contributors. MIT License.
- 저작자: Einar Otto Stangvik; Arnout Kazemier; Luigi Pinca
- 라이선스: MIT
- 원본: https://www.npmjs.com/package/ws/v/8.22.2 https://github.com/websockets/ws https://github.com/websockets/ws/blob/master/LICENSE
- 경로: `spikes/web-client/package.json`
- 용도: 실행 의존성: A0-02a 측정용 합성 포즈 스트림 서버(WebSocket). 측정용 스파이크이며 제품 코드가 아님
- 변경 내역: 없음(수정 없이 사용). 해시는 `npm pack ws@8.22.2` tgz 의 sha256. spikes/web-client/package.json 의 dependencies 와 pnpm-lock.yaml 에서 8.22.2 로 고정
- 받은 날짜: 2026-11-10
- 원본 해시: `sha256:de7148fed079cf115faacda8118276839dc9ab377d6b9075cea3424fa1d758f2`
- 확인자: omp
