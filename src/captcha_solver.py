from __future__ import annotations

from . import captcha_dom
from .captcha_cdp import CaptchaCDPMixin
from .captcha_context import DEFAULT_CDP_PAGE_TARGET_LIMIT, LOCAL_MOCK_VERIFY_MODES
from .captcha_fallbacks import CaptchaFallbacksMixin
from .captcha_nc_retry import CaptchaNCRetryMixin
from .captcha_orchestration import CaptchaOrchestrationMixin
from .captcha_os_input import CaptchaOSInputMixin
from .captcha_os_mapping import CaptchaOSMappingMixin
from .captcha_os_windows import CaptchaOSWindowsMixin
from .captcha_preflight import CaptchaPreflightMixin
from .captcha_slider import CaptchaSliderMixin
from .captcha_target import CaptchaTargetMixin


class CaptchaSolver(
    CaptchaTargetMixin,
    CaptchaCDPMixin,
    CaptchaSliderMixin,
    CaptchaOSWindowsMixin,
    CaptchaOSMappingMixin,
    CaptchaOSInputMixin,
    CaptchaNCRetryMixin,
    CaptchaPreflightMixin,
    CaptchaOrchestrationMixin,
    CaptchaFallbacksMixin,
):
    # Multiple selectors for different captcha variants
    SLIDER_SELECTORS = list(captcha_dom.SLIDER_SELECTORS)
    TRACK_SELECTORS = list(captcha_dom.TRACK_SELECTORS)


__all__ = ["CaptchaSolver", "DEFAULT_CDP_PAGE_TARGET_LIMIT", "LOCAL_MOCK_VERIFY_MODES"]

if __name__ == "__main__":
    s = CaptchaSolver()
    if s.solve():
        print("Done.")
    else:
        print("Failed.")
