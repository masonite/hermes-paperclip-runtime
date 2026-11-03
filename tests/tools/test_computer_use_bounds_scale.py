import json

import pytest


class TestBoundsScaleField:
    def test_scale_reported_when_spaces_diverge(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from tools.computer_use.backend import CaptureResult, UIElement
        from tools.computer_use.tool import _capture_response

        # Live repro geometry: 1455x791 screenshot, native bounds to 3799.
        elems = [UIElement(index=0, role="Button", label="Close",
                           bounds=(3730, 0, 69, 60), app="")]
        cap = CaptureResult(mode="som", width=1455, height=791, png_b64=None,
                            elements=elems, app="chrome.exe",
                            window_title="", png_bytes_len=0)
        out = json.loads(_capture_response(cap))
        assert out["bounds_scale"] == pytest.approx(3799 / 1455, abs=0.01)
        assert f"~{out['bounds_scale']}x" in out["summary"]

    def test_no_scale_when_spaces_match(self):
        from tools.computer_use.backend import UIElement
        from tools.computer_use.tool import _bounds_scale

        elems = [UIElement(index=0, role="Button", label="OK",
                           bounds=(10, 10, 50, 20), app="")]
        assert _bounds_scale(elems, 1455, 791) is None
        assert _bounds_scale([], 1455, 791) is None
        assert _bounds_scale(elems, 0, 0) is None
