from uxaudit import __version__


def test_version_is_defined():
    assert isinstance(__version__, str)
    assert __version__
