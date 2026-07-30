"""PoB 빌드코드 ↔ XML — 공유용 문자열 코덱.

headless PoB의 Deflate/Inflate는 빈 스텁이라 압축은 Python이 담당한다.
포맷 근거: PoB Modules/Main.lua 실측 —
  `Inflate(common.base64.decode(data:gsub("-","+"):gsub("_","/")))`
즉 빌드코드 = base64(zlib(xml)) 에 URL-safe 치환(+→-, /→_)을 얹은 것.
"""

from __future__ import annotations

import base64
import binascii
import zlib


def decode(build_code: str) -> str:
    """빌드코드 → XML 텍스트. 손상된 코드는 ValueError."""
    normalized = build_code.strip().replace("-", "+").replace("_", "/")
    # base64 패딩 복원 (공유 코드는 패딩이 잘려 다니는 경우가 있다)
    normalized += "=" * (-len(normalized) % 4)
    try:
        raw = base64.b64decode(normalized, validate=True)
        xml = zlib.decompress(raw)
    except (binascii.Error, zlib.error, ValueError) as e:  # 비-ASCII는 ValueError로 온다
        raise ValueError(f"빌드코드 해석 실패: {e}") from e
    return xml.decode("utf-8")


def encode(xml_text: str) -> str:
    """XML 텍스트 → 빌드코드 (PoB '불러오기'에 그대로 붙여넣기 가능)."""
    compressed = zlib.compress(xml_text.encode("utf-8"), 9)
    return base64.b64encode(compressed).decode("ascii").replace("+", "-").replace("/", "_")
