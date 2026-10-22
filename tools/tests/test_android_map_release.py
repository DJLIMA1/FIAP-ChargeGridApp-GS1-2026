import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_mobile_apk import build_then_verify
from verify_android_map_release import verify_factory_code


@pytest.mark.parametrize("exit_code", [None, 0, 1])
def test_cli_success_exit_still_validates_apk_but_failed_build_does_not(exit_code):
    calls = []

    def build():
        if exit_code is not None:
            raise SystemExit(exit_code)

    if exit_code == 1:
        with pytest.raises(SystemExit):
            build_then_verify(build, lambda: calls.append("verified"))
        assert calls == []
    else:
        build_then_verify(build, lambda: calls.append("verified"))
        assert calls == ["verified"]

FACTORY = """.method public create(Landroid/content/Context;ILjava/lang/Object;)Lio/flutter/plugin/platform/PlatformView;
    invoke-interface {p1, p2}, Lcom/github/josxha/maplibre/FlutterApi;->createPlatformView(I)Lio/flutter/plugin/platform/PlatformView;
    .line 16
    {result}
    return-object p1
.end method
"""


def test_release_factory_keeps_native_proxy_result():
    verify_factory_code(FACTORY.replace("{result}", "move-result-object p1"))


def test_rejects_r8_null_return_observed_in_broken_082_apk():
    # This is the instruction emitted by R8 in the failing release APK.
    with pytest.raises(ValueError, match="R8 discarded"):
        verify_factory_code(FACTORY.replace("{result}", "const/4 p1, 0x0"))


def test_rejects_missing_android_factory():
    with pytest.raises(ValueError, match="missing"):
        verify_factory_code("")
