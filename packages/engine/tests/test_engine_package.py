import kinetra_engine


def test_engine_package_is_importable_from_workspace():
    assert kinetra_engine.__doc__ and "engine adapters" in kinetra_engine.__doc__
