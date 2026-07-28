"""P0 스모크: 패키지가 설치·임포트되고 버전이 있다."""

import pok


def test_package_imports() -> None:
    assert pok.__version__
