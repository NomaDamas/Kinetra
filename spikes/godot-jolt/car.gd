# A0-03b: the 4-wheel car of car_scene.json in Godot 4.7 + Jolt (headless). Writes the chassis trajectory as CSV.
#
#   godot --headless --fixed-fps 500 --path spikes/godot-jolt --script car.gd -- \
#     --scene slope --params spikes/godot-jolt/car_scene.json --out /tmp/slope.csv [--dz 1e-6]
#   (spikes/godot-jolt/car.py runs this and the MuJoCo side and prints the differences.)
#
# Row k of the CSV is the chassis after k physics steps (row 0 = the initial state): step,x,y,z,qw,qx,qy,qz.
# Chassis = box, wheels = cylinders (axis = chassis y) on hinge joints. The wheel drive is a torque on the wheel with the
# opposite torque on the chassis (what a MuJoCo <motor> on the hinge does), not a Godot velocity motor.
extends SceneTree

var params := {}
var scene_name := "slope"
var out_path := ""
var dz := 0.0

var space: RID
var world: World3D
var chassis: RID
var wheels: Array[RID] = []
var drive_wheels: Array[RID] = []
var rids: Array[RID] = []
var torque := 0.0
var steps := 0
var n := 0
var rows := PackedStringArray()


func _initialize() -> void:
	_parse(OS.get_cmdline_user_args())
	if Engine.physics_ticks_per_second != 500:
		printerr("car.gd: expected 500 physics ticks per second (project.godot)")
		quit(3)
		return
	var f := FileAccess.open(_params_path, FileAccess.READ)
	if f == null:
		printerr("car.gd: cannot read the params file")
		quit(2)
		return
	params = JSON.parse_string(f.get_as_text())
	_build()


var _params_path := ""


func _parse(a: PackedStringArray) -> void:
	var i := 0
	while i < a.size():
		match a[i]:
			"--scene": scene_name = a[i + 1]; i += 1
			"--params": _params_path = a[i + 1]; i += 1
			"--out": out_path = a[i + 1]; i += 1
			"--dz": dz = float(a[i + 1]); i += 1
			_: printerr("car.gd: unknown argument %s" % a[i])
		i += 1


func _vec(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])


func _quat(a: Array) -> Quaternion:  # params are wxyz
	return Quaternion(a[1], a[2], a[3], a[0])


func _set_body(b: RID, mass: float, shape: RID, xf: Transform3D, linvel: Vector3) -> void:
	PhysicsServer3D.body_set_space(b, space)
	PhysicsServer3D.body_set_mode(b, PhysicsServer3D.BODY_MODE_RIGID)
	PhysicsServer3D.body_add_shape(b, shape)
	PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_MASS, mass)
	PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_FRICTION, params["friction"])
	PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_BOUNCE, params["restitution"])
	PhysicsServer3D.body_set_state(b, PhysicsServer3D.BODY_STATE_CAN_SLEEP, false)
	PhysicsServer3D.body_set_state(b, PhysicsServer3D.BODY_STATE_TRANSFORM, xf)
	PhysicsServer3D.body_set_state(b, PhysicsServer3D.BODY_STATE_LINEAR_VELOCITY, linvel)
	rids.append(b)


func _build() -> void:
	var sc: Dictionary = params["scenes"][scene_name]
	steps = int(sc["steps"])
	torque = float(sc["drive_torque_per_wheel"])
	world = World3D.new()
	space = world.space
	PhysicsServer3D.space_set_active(space, true)

	# ground: a big box whose top face is the tilted plane through the origin
	var gq := _quat(sc["ground_quat_wxyz"])
	var gshape := PhysicsServer3D.box_shape_create()
	PhysicsServer3D.shape_set_data(gshape, Vector3(100, 100, 1))
	var ground := PhysicsServer3D.body_create()
	PhysicsServer3D.body_set_space(ground, space)
	PhysicsServer3D.body_set_mode(ground, PhysicsServer3D.BODY_MODE_STATIC)
	PhysicsServer3D.body_add_shape(ground, gshape)
	PhysicsServer3D.body_set_param(ground, PhysicsServer3D.BODY_PARAM_FRICTION, params["friction"])
	PhysicsServer3D.body_set_param(ground, PhysicsServer3D.BODY_PARAM_BOUNCE, params["restitution"])
	PhysicsServer3D.body_set_state(ground, PhysicsServer3D.BODY_STATE_TRANSFORM,
			Transform3D(Basis(gq), Basis(gq) * Vector3(0, 0, -1)))
	rids.append(ground); rids.append(gshape)

	var cpos := _vec(sc["chassis_pos"]) + Vector3(0, 0, dz)
	var cq := _quat(sc["chassis_quat_wxyz"])
	var cb := Basis(cq)
	var linvel := _vec(sc["chassis_linvel"])
	var ch: Dictionary = params["chassis"]
	var cshape := PhysicsServer3D.box_shape_create()
	PhysicsServer3D.shape_set_data(cshape, _vec(ch["half_extents"]))
	rids.append(cshape)
	chassis = PhysicsServer3D.body_create()
	_set_body(chassis, ch["mass"], cshape, Transform3D(cb, cpos), linvel)

	var wp: Dictionary = params["wheel"]
	var wshape := PhysicsServer3D.cylinder_shape_create()
	PhysicsServer3D.shape_set_data(wshape, {"radius": wp["radius"], "height": 2.0 * wp["half_width"]})  # axis = local y
	rids.append(wshape)
	# hinge frame: local z = hinge axis = chassis y (wheel body frame = chassis frame at the start)
	var frame := Basis(Vector3(1, 0, 0), Vector3(0, 0, -1), Vector3(0, 1, 0))
	for name in wp["positions"]:
		var lp := _vec(wp["positions"][name])
		var w := PhysicsServer3D.body_create()
		_set_body(w, wp["mass"], wshape, Transform3D(cb, cpos + cb * lp), linvel)
		var j := PhysicsServer3D.joint_create()
		PhysicsServer3D.joint_make_hinge(j, chassis, Transform3D(frame, lp), w, Transform3D(frame, Vector3.ZERO))
		PhysicsServer3D.joint_disable_collisions_between_bodies(j, true)
		rids.append(j)
		wheels.append(w)
		if name in wp["drive_wheels"]:
			drive_wheels.append(w)
	rows.append("step,x,y,z,qw,qx,qy,qz")


func _row(k: int) -> String:
	var t: Transform3D = PhysicsServer3D.body_get_state(chassis, PhysicsServer3D.BODY_STATE_TRANSFORM)
	var q := t.basis.get_rotation_quaternion()
	return "%d,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f" % [k, t.origin.x, t.origin.y, t.origin.z, q.w, q.x, q.y, q.z]


func _physics_process(_delta: float) -> bool:
	# Called before the step: callback n shows the state after n-1 steps.
	rows.append(_row(n))
	if n >= steps:
		var f := FileAccess.open(out_path, FileAccess.WRITE)
		f.store_string("\n".join(rows) + "\n")
		f.close()
		for r in rids:
			PhysicsServer3D.free_rid(r)
		quit(0)
		return true
	if torque != 0.0:
		var t: Transform3D = PhysicsServer3D.body_get_state(chassis, PhysicsServer3D.BODY_STATE_TRANSFORM)
		var axis := t.basis * Vector3(0, 1, 0)
		for w in drive_wheels:
			PhysicsServer3D.body_apply_torque(w, axis * torque)
			PhysicsServer3D.body_apply_torque(chassis, -axis * torque)
	n += 1
	return false
