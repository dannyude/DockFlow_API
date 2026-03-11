import pytest

from api.src.services.extractor import extract_text


def test_extract_text_unsupported_type_raises() -> None:
    with pytest.raises(ValueError):
        extract_text(b"abc", "application/octet-stream")
