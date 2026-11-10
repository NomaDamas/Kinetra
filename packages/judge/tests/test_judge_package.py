import kinetra_judge


def test_judge_package_is_importable_from_workspace():
    assert kinetra_judge.__doc__ and "Monte-Carlo" in kinetra_judge.__doc__
