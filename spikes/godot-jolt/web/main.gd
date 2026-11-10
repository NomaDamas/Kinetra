extends Node
# 200 free cubes on a floor via PhysicsServer3D (same API as ../scale.gd), 1000 physics steps at 500 Hz, then report.
var space: RID
var bodies: Array[RID] = []
var steps := 0
var t_first := 0
var t_ready := 0

func _ready() -> void:
	t_ready = Time.get_ticks_msec()
	var w := World3D.new()
	space = w.space
	PhysicsServer3D.space_set_active(space, true)
	var floor_shape := PhysicsServer3D.box_shape_create()
	PhysicsServer3D.shape_set_data(floor_shape, Vector3(50, 50, 1))
	var fl := PhysicsServer3D.body_create()
	PhysicsServer3D.body_set_space(fl, space)
	PhysicsServer3D.body_set_mode(fl, PhysicsServer3D.BODY_MODE_STATIC)
	PhysicsServer3D.body_add_shape(fl, floor_shape)
	PhysicsServer3D.body_set_state(fl, PhysicsServer3D.BODY_STATE_TRANSFORM, Transform3D(Basis(), Vector3(0, 0, -1)))
	var box := PhysicsServer3D.box_shape_create()
	PhysicsServer3D.shape_set_data(box, Vector3(0.05, 0.05, 0.05))
	for i in 200:
		var b := PhysicsServer3D.body_create()
		PhysicsServer3D.body_set_space(b, space)
		PhysicsServer3D.body_set_mode(b, PhysicsServer3D.BODY_MODE_RIGID)
		PhysicsServer3D.body_add_shape(b, box)
		PhysicsServer3D.body_set_param(b, PhysicsServer3D.BODY_PARAM_MASS, 1.0)
		PhysicsServer3D.body_set_state(b, PhysicsServer3D.BODY_STATE_TRANSFORM,
				Transform3D(Basis(), Vector3((i % 10) * 0.13, ((i / 10) % 10) * 0.13, 0.1 + (i / 100) * 0.13)))
		bodies.append(b)
	print("KINETRA ready physics_engine=", ProjectSettings.get_setting("physics/3d/physics_engine"),
			" version=", Engine.get_version_info()["string"], " ready_ms=", t_ready)

func _physics_process(_d: float) -> void:
	if steps == 0:
		t_first = Time.get_ticks_msec()
	steps += 1
	if steps == 1000:
		var z := 0.0
		for b in bodies:
			z += PhysicsServer3D.body_get_state(b, PhysicsServer3D.BODY_STATE_TRANSFORM).origin.z
		var msg := "KINETRA done steps=%d wall_ms=%d mean_z=%.4f" % [steps, Time.get_ticks_msec() - t_first, z / bodies.size()]
		print(msg)
		if OS.has_feature("web"):
			JavaScriptBridge.eval("window.__godot_result = %s" % JSON.stringify(msg))
