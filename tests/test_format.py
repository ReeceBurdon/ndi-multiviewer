from fractions import Fraction

import pytest

pytest.importorskip("cyndilib")
from ndi_multiviewer.ndi_backend import VideoFormat  # noqa: E402


@pytest.mark.parametrize(
    "w,h,rate,progressive,expected",
    [
        (1920, 1080, Fraction(60000, 1001), True, "1920×1080p59.94"),
        (1920, 1080, Fraction(25), False, "1920×1080i50"),
        (3840, 2160, Fraction(24000, 1001), True, "3840×2160p23.98"),
        (1280, 720, Fraction(50), True, "1280×720p50"),
    ],
)
def test_label(w, h, rate, progressive, expected):
    assert VideoFormat(w, h, rate, progressive).label() == expected
