# A0-03a: Godot 4.7 + Jolt multi-body, joint-release and determinism measurement. Measurement only (no tuning).
#
#   uv run python tools/dev/resource_guard.py --profile heavy -- \
#     GODOT --headless --fixed-fps 500 --path spikes/godot-jolt --script scale.gd -- --scene pile --n 200
#   (spikes/godot-jolt/scale.py runs the whole matrix, repeats it per process and compares the hashes.)
#
# Scenes (same recipe as spikes/mujoco-limits/scale.py, Z up, SI, 500 Hz = MuJoCo timestep 0.002; the random
# stream is Godot's, so positions are the same recipe, not the same numbers):
#   pile    N free 0.1 m cubes (1 kg) in a walled bin on a floor, 5 layers, jittered pose, random xy speed +-0.3 m/s.
#   break   100 cubes in 10 columns of 10; each cube is welded to the one below it, the lowest to the world
#           (100 fully locked 6DOF joints). The joints are freed one by one in seeded order between 0.2 s and 1.2 s.
#           With --pile M the M free cubes of the pile scene share the same world (break-1000 = --n 0 --pile 1000).
#
# One process = one run. Output: a `RESULT {json}` line on stdout (and --out FILE).
# rtf = sim seconds / wall seconds spent between physics callbacks, i.e. engine sync + Jolt step only; the time spent in
# this script (state reads, hashing) is not counted. Hash: sha256 chain over the 12 float32 of every body transform
# (origin + 3 basis columns, as Godot reports them) every --hash-every steps.
extends SceneTree

const BOX_HALF := 0.05
const LAYERS := 5
const PITCH_XY := 0.18
const PITCH_Z := 0.15
const WALL_H := 1.0
const GAP := 0.002
const HEAVY_BODIES := 1000

var scene := "pile"
var n_pile := 200
var n_break := 0
var seed_ := 0
var sim_seconds := 2.0
var wall_cap := 60.0
var hash_every := 10
var allow_sleep := false
var count_contacts := false
var out_path := ""

var world: World3D
var space: RID
var box_shape: RID
var rids: Array[RID] = []          # everything to free at the end
var bodies: Array[RID] = []        # dynamic cubes, hashed
var joints: Array[RID] = []        # the 100 welds
var break_bodies: Array[RID] = []
var break_start: PackedVector3Array = PackedVector3Array()
var release_plan: Array = []       # [[step, joint_index], ...] sorted by step
var released := 0
var joint_freed: Array[bool] = []
var ri := 0
var z0: PackedFloat32Array = PackedFloat32Array()

var target_steps := 0
var steps_done := 0
var step_wall_us := 0
var t_exit := -1
var started := false
var ctx := HashingContext.new()
var chain := PackedByteArray()
var checkpoints: PackedStringArray = PackedStringArray()
var compile_us := 0
var pre_release_max_disp := -1.0
var capped := false
var t_process_start := 0


func _initialize() -> void:
	_parse_args(OS.get_cmdline_user_args())
	if max(n_pile, n_break) + 0 >= HEAVY_BODIES and OS.get_environment("KINETRA_GUARD_PASSED") != "1":
		printerr("scale.gd: >= %d bodies is a heavy run (docs/process/dev-resources.md). Start it through tools/dev/resource_guard.py --profile heavy -- <cmd>." % HEAVY_BODIES)
		quit(2)
		return
	if Engine.physics_ticks_per_second != 500:
		printerr("scale.gd: expected 500 physics ticks per second (project.godot), got %d" % Engine.physics_ticks_per_second)
		quit(3)
		return
	t_process_start = Time.get_ticks_usec()


func _parse_args(a: PackedStringArray) -> void:
	var i := 0
	while i < a.size():
		match a[i]:
			"--scene": scene = a[i + 1]; i += 1
			"--n": n_pile = int(a[i + 1]); i += 1
			"--pile": n_pile = int(a[i + 1]); i += 1
			"--seed": seed_ = int(a[i + 1]); i += 1
			"--sim-seconds": sim_seconds = float(a[i + 1]); i += 1
			"--wall-cap": wall_cap = float(a[i + 1]); i += 1
			"--hash-every": hash_every = int(a[i + 1]); i += 1
			"--out": out_path = a[i + 1]; i += 1
			"--sleep": allow_sleep = true
			"--count-contacts": count_contacts = true
			_: printerr("scale.gd: unknown argument %s" % a[i])
		i += 1
	if scene == "break":
		n_break = 100


func _euler_quat(rng: RandomNumberGenerator) -> Quaternion:
	var yaw := rng.randf_range(0.0, TAU)
	var roll := rng.randf_range(-0.15, 0.15)
	var pitch := rng.randf_range(-0.15, 0.15)
	var cr := cos(roll / 2.0); var sr := sin(roll / 2.0)
	var cp := cos(pitch / 2.0); var sp := sin(pitch / 2.0)
	var cy := cos(yaw / 2.0); var sy := sin(yaw / 2.0)
	var w := cr * cp * cy + sr * sp * sy
	var x := sr * cp * cy - cr * sp * sy
	var y := cr * sp * cy + sr * cp * sy
	var z := cr * cp * sy - sr * sp * cy
	return Quaternion(x, y, z, w).normalized()


func _static_box(center: Vector3, half: Vector3) -> void:
	var sh := PhysicsServer3D.box_shape_create()
	PhysicsServer3D.shape_set_data(sh, half)
	var b := PhysicsServer3D.body_create()
	PhysicsServer3D.body_set_space(b, space)
	PhysicsServer3D.body_set_mode(b, PhysicsServer3D.BODY_MODE_STATIC)
	PhysicsServer3D.body_add_shape(b, sh)
	PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_FRICTION, 1.0)
	PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_BOUNCE, 0.0)
	PhysicsServer3D.body_set_state(b, PhysicsServer3D.BODY_STATE_TRANSFORM, Transform3D(Basis(), center))
	rids.append(b); rids.append(sh)


func _cube(pos: Vector3, q: Quaternion) -> RID:
	var b := PhysicsServer3D.body_create()
	PhysicsServer3D.body_set_space(b, space)
	PhysicsServer3D.body_set_mode(b, PhysicsServer3D.BODY_MODE_RIGID)
	PhysicsServer3D.body_add_shape(b, box_shape)
	PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_MASS, 1.0)  # 1000 kg/m^3 * 0.001 m^3
	PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_FRICTION, 1.0)
	PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_BOUNCE, 0.0)
	PhysicsServer3D.body_set_state(b, PhysicsServer3D.BODY_STATE_CAN_SLEEP, allow_sleep)
	PhysicsServer3D.body_set_state(b, PhysicsServer3D.BODY_STATE_TRANSFORM, Transform3D(Basis(q), pos))
	if count_contacts:
		PhysicsServer3D.body_set_max_contacts_reported(b, 16)
	bodies.append(b)
	rids.append(b)
	return b


func _weld(a: RID, ref_a: Transform3D, b: RID, ref_b: Transform3D) -> RID:
	var j := PhysicsServer3D.joint_create()
	PhysicsServer3D.joint_make_generic_6dof(j, a, ref_a, b, ref_b)
	for ax in 3:
		PhysicsServer3D.generic_6dof_joint_set_flag(j, ax, PhysicsServer3D.G6DOF_JOINT_FLAG_ENABLE_LINEAR_LIMIT, true)
		PhysicsServer3D.generic_6dof_joint_set_flag(j, ax, PhysicsServer3D.G6DOF_JOINT_FLAG_ENABLE_ANGULAR_LIMIT, true)
		for p in [PhysicsServer3D.G6DOF_JOINT_LINEAR_LOWER_LIMIT, PhysicsServer3D.G6DOF_JOINT_LINEAR_UPPER_LIMIT,
				PhysicsServer3D.G6DOF_JOINT_ANGULAR_LOWER_LIMIT, PhysicsServer3D.G6DOF_JOINT_ANGULAR_UPPER_LIMIT]:
			PhysicsServer3D.generic_6dof_joint_set_param(j, ax, p, 0.0)
	return j


func _build() -> void:
	world = World3D.new()
	space = world.space
	PhysicsServer3D.space_set_active(space, true)
	box_shape = PhysicsServer3D.box_shape_create()
	PhysicsServer3D.shape_set_data(box_shape, Vector3(BOX_HALF, BOX_HALF, BOX_HALF))
	rids.append(box_shape)
	_static_box(Vector3(0, 0, -1.0), Vector3(200, 200, 1.0))  # floor, top face at z = 0

	var rng := RandomNumberGenerator.new()
	rng.seed = seed_
	var half_x := 0.0
	if n_pile > 0:
		var nx := int(ceil(sqrt(float(n_pile) / LAYERS)))
		var ny := int(ceil(float(n_pile) / (LAYERS * nx)))
		half_x = nx * PITCH_XY / 2.0 + 0.1
		var half_y := ny * PITCH_XY / 2.0 + 0.1
		var vrng := RandomNumberGenerator.new()
		vrng.seed = seed_ + 1
		for i in n_pile:
			var layer := i / (nx * ny)
			var rem := i % (nx * ny)
			var row := rem / nx
			var col := rem % nx
			var x := (col - (nx - 1) / 2.0) * PITCH_XY + rng.randf_range(-0.01, 0.01)
			var y := (row - (ny - 1) / 2.0) * PITCH_XY + rng.randf_range(-0.01, 0.01)
			var z := BOX_HALF + 0.02 + layer * PITCH_Z
			var b := _cube(Vector3(x, y, z), _euler_quat(rng))
			PhysicsServer3D.body_set_state(b, PhysicsServer3D.BODY_STATE_LINEAR_VELOCITY,
					Vector3(vrng.randf_range(-0.3, 0.3), vrng.randf_range(-0.3, 0.3), 0.0))
		var t := 0.05
		_static_box(Vector3(half_x + t, 0, WALL_H / 2), Vector3(t, half_y + 2 * t, WALL_H / 2))
		_static_box(Vector3(-half_x - t, 0, WALL_H / 2), Vector3(t, half_y + 2 * t, WALL_H / 2))
		_static_box(Vector3(0, half_y + t, WALL_H / 2), Vector3(half_x + 2 * t, t, WALL_H / 2))
		_static_box(Vector3(0, -half_y - t, WALL_H / 2), Vector3(half_x + 2 * t, t, WALL_H / 2))

	if n_break > 0:
		var x_off := half_x + 1.0 if n_pile > 0 else 0.0
		var pitch := 2 * BOX_HALF + GAP
		for c in 10:
			var x := x_off + c * 0.3
			var below := RID()
			for r in 10:
				var pos := Vector3(x, 0, 0.5 + BOX_HALF + r * pitch)
				var b := _cube(pos, Quaternion())
				break_bodies.append(b)
				break_start.append(pos)
				if r == 0:
					joints.append(_weld(b, Transform3D(), RID(), Transform3D(Basis(), pos)))
				else:
					joints.append(_weld(b, Transform3D(), below, Transform3D(Basis(), Vector3(0, 0, pitch))))
				below = b
		joint_freed.resize(joints.size())
		joint_freed.fill(false)
		var order: Array = range(joints.size())
		var orng := RandomNumberGenerator.new()
		orng.seed = seed_ + 2
		for i in range(order.size() - 1, 0, -1):
			var k := orng.randi_range(0, i)
			var tmp = order[i]; order[i] = order[k]; order[k] = tmp
		var first := int(round(0.2 / 0.002))
		var span := int(round((1.2 - 0.2) / 0.002))
		for k in order.size():
			release_plan.append([first + int(k * span / order.size()), order[k]])
		release_plan.sort()
	for b in bodies:
		z0.append(PhysicsServer3D.body_get_state(b, PhysicsServer3D.BODY_STATE_TRANSFORM).origin.z)
	target_steps = int(round(sim_seconds / 0.002))
	chain.resize(32)  # all-zero start of the hash chain


func _state_bytes() -> PackedByteArray:
	var f := PackedFloat32Array()
	f.resize(bodies.size() * 12)
	var k := 0
	for b in bodies:
		var t: Transform3D = PhysicsServer3D.body_get_state(b, PhysicsServer3D.BODY_STATE_TRANSFORM)
		f[k] = t.origin.x; f[k + 1] = t.origin.y; f[k + 2] = t.origin.z
		f[k + 3] = t.basis.x.x; f[k + 4] = t.basis.x.y; f[k + 5] = t.basis.x.z
		f[k + 6] = t.basis.y.x; f[k + 7] = t.basis.y.y; f[k + 8] = t.basis.y.z
		f[k + 9] = t.basis.z.x; f[k + 10] = t.basis.z.y; f[k + 11] = t.basis.z.z
		k += 12
	return f.to_byte_array()


func _checkpoint() -> void:
	ctx.start(HashingContext.HASH_SHA256)
	ctx.update(chain)
	ctx.update(_state_bytes())
	chain = ctx.finish()
	checkpoints.append(chain.hex_encode())


func _max_break_disp() -> float:
	var m := 0.0
	for i in break_bodies.size():
		var p: Vector3 = PhysicsServer3D.body_get_state(break_bodies[i], PhysicsServer3D.BODY_STATE_TRANSFORM).origin
		m = max(m, p.distance_to(break_start[i]))
	return m


func _physics_process(_delta: float) -> bool:
	var t_enter := Time.get_ticks_usec()
	if not started:
		var t0 := Time.get_ticks_usec()
		_build()
		compile_us = Time.get_ticks_usec() - t0
		started = true
		t_exit = Time.get_ticks_usec()
		return false
	# The interval since the previous callback is one engine step (Jolt) plus loop overhead.
	step_wall_us += t_enter - t_exit
	steps_done += 1
	if steps_done % hash_every == 0 or steps_done == target_steps:
		_checkpoint()
	while ri < release_plan.size() and release_plan[ri][0] <= steps_done:
		if released == 0:
			pre_release_max_disp = _max_break_disp()
		PhysicsServer3D.free_rid(joints[release_plan[ri][1]])
		joint_freed[release_plan[ri][1]] = true
		ri += 1
		released += 1
	if steps_done >= target_steps or step_wall_us > wall_cap * 1e6:
		capped = steps_done < target_steps
		_finish()
		return true
	t_exit = Time.get_ticks_usec()
	return false


func _finish() -> void:
	var finite := true
	var zmin := INF
	var zmax := -INF
	var moved := 0
	var contacts := -1
	if count_contacts:
		contacts = 0
		for b in bodies:
			var ds := PhysicsServer3D.body_get_direct_state(b)
			contacts += ds.get_contact_count()
	for i in bodies.size():
		var o: Vector3 = PhysicsServer3D.body_get_state(bodies[i], PhysicsServer3D.BODY_STATE_TRANSFORM).origin
		if not (is_finite(o.x) and is_finite(o.y) and is_finite(o.z)):
			finite = false
		zmin = min(zmin, o.z)
		zmax = max(zmax, o.z)
		if z0[i] - o.z > 0.1:
			moved += 1
	var sim_s := steps_done * 0.002
	var wall_s := step_wall_us / 1e6
	var v := Engine.get_version_info()
	var res := {
		"scene": ("break-%d" % n_pile) if n_break > 0 else ("pile-%d" % n_pile),
		"n_pile": n_pile, "n_break_cubes": n_break, "n_bodies": bodies.size(),
		"n_joints_total": joints.size(), "n_joints_released": released,
		"joints_alive": _alive_joints(),
		"seed": seed_, "allow_sleep": allow_sleep,
		"steps": steps_done, "steps_target": target_steps, "capped_by_wall": capped,
		"sim_s": snappedf(sim_s, 1e-6), "wall_s": snappedf(wall_s, 1e-4),
		"rtf": snappedf(sim_s / wall_s, 1e-4) if wall_s > 0 else null,
		"build_s": snappedf(compile_us / 1e6, 1e-3),
		"hash_every": hash_every, "final_hash": checkpoints[checkpoints.size() - 1] if checkpoints.size() > 0 else "",
		"checkpoints": Array(checkpoints),
		"finite": finite, "z_min": snappedf(zmin, 1e-4), "z_max": snappedf(zmax, 1e-4),
		"n_dropped_over_0p1m": moved, "pre_release_max_disp_m": snappedf(pre_release_max_disp, 1e-5),
		"contacts_sampled_last_step": contacts,
		"godot": v["string"], "godot_hash": v["hash"], "physics_engine": ProjectSettings.get_setting("physics/3d/physics_engine"),
		"ticks": Engine.physics_ticks_per_second, "worker_threads": int(ProjectSettings.get_setting("threading/worker_pool/max_threads", -1)),
		"arch": Engine.get_architecture_name(), "process_s": snappedf((Time.get_ticks_usec() - t_process_start) / 1e6, 1e-3),
	}
	for k in joints.size():
		if not joint_freed[k]:
			PhysicsServer3D.free_rid(joints[k])
	for r in rids:
		PhysicsServer3D.free_rid(r)
	var line := JSON.stringify(res)
	print("RESULT " + line)
	if out_path != "":
		var f := FileAccess.open(out_path, FileAccess.WRITE)
		if f != null:
			f.store_string(line)
			f.close()
	quit(0)


func _alive_joints() -> int:
	var n := 0
	for k in joints.size():
		if not joint_freed[k] and PhysicsServer3D.joint_get_type(joints[k]) == PhysicsServer3D.JOINT_TYPE_6DOF:
			n += 1
	return n
