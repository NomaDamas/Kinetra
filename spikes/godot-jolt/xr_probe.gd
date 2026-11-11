# A0-03b: OpenXR / WebXR support status of the Godot binary on this machine. Prints `XR {json}`.
#   godot --headless --path spikes/godot-jolt --script xr_probe.gd
extends SceneTree

func _initialize() -> void:
	var res := {"godot": Engine.get_version_info()["string"], "os": OS.get_name(), "arch": Engine.get_architecture_name()}
	res["classes"] = {}
	for c in ["OpenXRInterface", "OpenXRAPIExtension", "WebXRInterface", "XRServer", "XRCamera3D", "XRController3D", "XROrigin3D"]:
		res["classes"][c] = ClassDB.class_exists(c)
	res["interfaces_registered"] = []
	for i in XRServer.get_interfaces():
		res["interfaces_registered"].append(i["name"])
	res["project_setting_xr/openxr/enabled"] = ProjectSettings.get_setting("xr/openxr/enabled")
	var oxr := XRServer.find_interface("OpenXR")
	res["openxr_interface_found"] = oxr != null
	if oxr != null:
		res["openxr_initialize_ok"] = oxr.initialize()
		res["openxr_is_initialized"] = oxr.is_initialized()
	print("XR " + JSON.stringify(res))
	quit(0)
