"""프로젝트 구조 스모크 테스트."""


def test_import_src():
    import src  # noqa: F401


def test_import_submodules():
    import src.api  # noqa: F401
    import src.downloader  # noqa: F401
    import src.extractor  # noqa: F401
    import src.reconstruction  # noqa: F401
    import src.viewer  # noqa: F401
