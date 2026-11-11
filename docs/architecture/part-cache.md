# 부품 컴파일 캐시 (B-01d)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/parts/cache.py`(`PartCache`, `part_key`, `material_key`), 테스트는 `packages/engine/tests/test_part_cache.py`. `uv run pytest packages/engine -q -k cache`.
- 근거: 이슈 #95, `docs/architecture/part-mass.md`("모든 필드가 튜플·불변이라 해시된다"), `client-adapter.md` D4(파생값은 코어가 계산한다), A2(값으로 가리키면 바뀌지 않는다).
- 범위 밖: 파일에 쓰는 캐시(디스크, 프로세스 사이 공유), 프로젝트 저장 형식과 정의 해시(C-03, #506의 `kinetra_core.definition_hash`), 카탈로그와 해시 비교(C-06), 부품 종류(B-02, B-03).
- 부품을 넣는 절차: `docs/process/add-part.md`.

## 쓰는 법

```python
from kinetra_engine.parts import PartCache
cache = PartCache(max_entries=256)               # 크기는 부르는 쪽이 정한다(기본값 없음)
cache.mass_properties(part, material, params)    # MassProperties, 같은 입력이면 같은 객체
cache.collision_proxy(part, params)              # CollisionProxy
cache.part_glb(part, material, params, pbr=None) # bytes
cache.stats()                                    # CacheStats(hits, misses, evictions, entries, max_entries)
cache.clear()
```

세 함수는 `mass_properties`, `collision_proxy`, `part_glb`와 인자와 예외가 같고 값도 같다(`test_cache_returns_the_same_results_as_compiling_directly`). 결과 객체는 불변이라 적중이면 처음 계산한 그 객체를 돌려준다.

## 키에 들어가는 것

| 결과 | 키 |
|---|---|
| 질량·관성 | 정의, 재료, 풀어낸 파라미터 값 |
| 충돌 프록시 | 정의, 풀어낸 파라미터 값(**재료 없음**: 프록시는 재료를 읽지 않으므로 어느 재료든 한 항목) |
| glb | 정의, 재료, 풀어낸 파라미터 값, 외형(`pbr=` 없으면 "카탈로그", 있으면 그 값의 해시) |

- **정의 해시** `part_key(part)`는 `PartDef.model_dump_json()`의 SHA-256이다. 필드 순서는 모델이 정하고 파일의 키 순서와 무관하다(`test_cache_hits_for_an_equal_definition_built_separately`). 파이썬 `hash()`가 아니라 프로세스와 `PYTHONHASHSEED`에 무관하다(`test_cache_is_identical_across_processes_and_hash_seeds`).
- **재료 해시**: 같은 id에 밀도만 다른 재료는 다른 키다(`test_cache_material_with_the_same_id_but_another_density_is_a_miss`).
- **풀어낸 파라미터**는 `_shape._resolve_parameters`의 결과다. 덮어쓰지 않은 파라미터는 부품의 기본값이라 "덮어쓰기 없음"과 "기본값을 그대로 덮어씀"은 같은 키다. 같은 숫자라도 배지나 출처가 다르면 다른 키다. 결과가 그 배지를 싣기 때문이다. 알 수 없는 이름, 단위 오류, 범위 밖은 키를 만들다가 `ShapeError`로 거절되고 컴파일할 때와 같은 사유다.
- 키가 빠뜨리는 입력이 있으면 낡은 결과가 나간다. 그래서 시험이 정의 JSON의 **잎을 하나씩 모두** 바꿔 해시가 달라지는지 본다(`test_cache_definition_hash_changes_with_every_leaf_of_the_definition`). `PartDef`에 새 절이 생겨도 해시가 무시하면 이 시험이 아니라 키 코드를 고쳐야 한다. 키 코드를 고의로 틀리게 한 변이(재료 빼기, 파라미터 빼기, 외형 빼기, 스냅 포인트 빼기, LRU 갱신 빼기)가 시험을 실패시키는 것을 확인했다.

## C-03의 `definition_hash`를 쓰지 않는 이유

C-03(#506)의 `kinetra_core.definition_hash`는 컬렉션을 id로 정렬한 정규 형식의 해시라서 요소나 파라미터의 순서가 다른 파일도 같은 정의로 본다. 저장·열기·"카탈로그와 다름" 비교에는 그게 맞다. 컴파일러는 순서에 무관하지 않다. 요소 순서가 부동소수점 합의 끝자리와 glb의 노드 순서를 바꾼다(`test_cache_definition_hash_sees_order`는 요소 둘을 바꾸면 glb 바이트가 달라지는 것을 보인다). 정규 해시를 키로 쓰면 순서가 다른 정의에 상대의 결과를 돌려주게 된다. 그래서 이 캐시의 키는 순서까지 포함하는 엄격한 해시이고, 값이 같은데 순서만 다른 정의는 한 번 더 컴파일하는 비용만 든다. 두 해시는 다른 질문에 답한다.

## 한계

- 프로세스 안의 메모리 캐시다. 디스크에 쓰지 않고 프로세스 사이로 공유하지 않는다.
- 크기는 항목 수다. 바이트가 아니다(glb는 질량 결과보다 훨씬 크다). 알맞은 크기를 재지 않았다 [확인 필요: 클라이언트가 쓰는 쪽(B-05, L-01)이 정한다].
- 성공한 결과만 담는다. 거절되는 부품은 매번 같은 비용으로 거절된다(`test_cache_rejects_what_the_compiler_rejects_and_stores_nothing`).
- 두 스레드가 같은 키를 동시에 놓치면 둘 다 계산하고 하나만 남는다(둘 다 `misses`로 센다). 결과는 같다. 잠금 밖에서 계산하므로 다른 스레드의 조회를 막지 않는다.
- `material.id`로 찾는 카탈로그 외형은 같은 프로세스 안에서 바뀌지 않는다고 본다(카탈로그는 파일에서 한 번 읽는다). 카탈로그를 다시 읽는 코드가 생기면 `clear()`를 부르거나 외형을 `pbr=`로 넘긴다.

## 측정 (이 머신, 일회성 관찰이고 기준값이 아니다)

`mounting-plate`(요소 3개)와 상자 N개짜리 부품을 `time.perf_counter()`로 수백 번 평균. 적중 시간은 해시를 만드는 시간이다.

| 부품 | 질량 계산 | 적중 | glb 만들기 | 적중 |
|---|---|---|---|---|
| 요소 3개 | 약 0.14 ms | 약 0.05 ms | 약 0.33 ms | 약 0.05 ms |
| 상자 20개 | 약 5.2 ms | 약 0.08 ms | 약 6.3 ms | 약 0.10 ms |
| 상자 40개 | 약 9.8 ms | 약 0.16 ms | 약 10.5 ms | 약 0.16 ms |

작은 부품에서는 이득이 거의 없고(해시 비용이 계산과 비슷하다) 요소가 늘수록 커진다(겹침 검사가 요소 쌍마다 돈다). 이 숫자는 개발 머신 한 대의 한 번 측정이다.
