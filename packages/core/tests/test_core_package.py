import kinetra_core


def test_core_package_is_importable_from_workspace():
    assert kinetra_core.__doc__ and "Project model" in kinetra_core.__doc__
