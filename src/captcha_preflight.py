from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

from src.project_environment import getenv as project_getenv

from .captcha_budget import SolveStopped
from .captcha_context import LOCAL_MOCK_VERIFY_MODES
from .captcha_dom import eval_in_all_frames
from .captcha_verification import finalize_page_summary

logger = logging.getLogger(__name__)


class CaptchaPreflightMixin:
    def _close_page(self):
        """Close the dedicated solver page."""
        try:
            self._send_cdp("Page.close")
            self._wait_interruptibly(1)
        except Exception:
            pass

    def _reload_page(self):
        """Reload the page via CDP."""
        try:
            self._send_cdp("Page.reload", {"ignoreCache": False})
            self._wait_interruptibly(3)  # Wait for page to reload
        except Exception:
            pass

    def _page_challenge_summary(self):
        js_script = """
        (function() {
            function scan(doc) {
                var body = doc.body || null;
                var className = body && body.className ? String(body.className) : '';
                var bodyText = body && body.innerText ? String(body.innerText) : '';
                var title = doc.title || '';
                var href = (doc.location && doc.location.href) ? String(doc.location.href) : '';
                var readyState = doc.readyState || '';
                var hasSlider = hasVisibleMatch(doc, __PREFLIGHT_SLIDER_SELECTOR__);
                var hasChallengeWidget = hasVisibleMatch(doc, __VERIFY_CHALLENGE_SELECTOR__);
                var lowerHref = href.toLowerCase();
                var urlHost = '', urlPath = '';
                try {
                    var parsedUrl = new URL(href);
                    urlPath = parsedUrl.pathname.toLowerCase();
                    if ((parsedUrl.protocol === 'http:' || parsedUrl.protocol === 'https:') &&
                        !parsedUrl.username && !parsedUrl.password) {
                        urlHost = parsedUrl.hostname.toLowerCase();
                    }
                } catch (e) {}
                var combined = (className + '\\n' + bodyText + '\\n' + title + '\\n' + href).toLowerCase();
                var listRoute = urlHost === 'sf.taobao.com' && /^\\/list\\/[\\w-]+\\.htm$/.test(urlPath);
                var detailRoute = (urlHost === 'sf-item.taobao.com' && /^\\/sf_item\\/\\d+\\.htm$/.test(urlPath)) ||
                    (urlHost === 'susong-item.taobao.com' && /^\\/auction\\/\\d+\\.htm$/.test(urlPath));
                var challengeRedirect = lowerHref.indexOf('/_____tmd_____/') !== -1 || lowerHref.indexOf('/login_jump') !== -1;
                var auctionItemCount = 0;
                try {
                    auctionItemCount = doc.querySelectorAll('a[href*="sf_item/"], [data-itemid], [data-auction-id]').length;
                } catch (e) {}
                var supportedAuctionPage = (listRoute || detailRoute) && !challengeRedirect;
                var hardBlock = combined.indexOf('baxia') !== -1 || combined.indexOf('punish') !== -1 || combined.indexOf('denyfromx5') !== -1 || challengeRedirect;
                var errorMatch = combined.match(/error\\s*:\\s*[a-z0-9/_-]{1,64}/i);
                var errorWidget = doc.querySelector(__NC_ERROR_SELECTOR__);
                var explicitFailure = combined.indexOf('验证失败') !== -1 ||
                    combined.indexOf('点击框体重试') !== -1 ||
                    combined.indexOf("oops... something's wrong") !== -1 ||
                    combined.indexOf('please refresh page and try again') !== -1 ||
                    hasVisibleMatch(doc, __NC_ERROR_SELECTOR__) ||
                    !!errorMatch;
                var challengeMarker = combined.indexOf('验证码拦截') !== -1 || combined.indexOf('请按住滑块') !== -1 || combined.indexOf('安全验证') !== -1;
                var loginUrl = urlHost === 'login.taobao.com' || urlHost === 'login.tmall.com' || urlPath.indexOf('third-party-cookie') !== -1 || urlPath.indexOf('/passport/') !== -1 || urlPath.indexOf('/login') !== -1;
                var loginText = title.trim().toLowerCase() === '登录' || combined.indexOf('请登录') !== -1 || combined.indexOf('请先登录') !== -1;
                var loginRequired = (!supportedAuctionPage || challengeRedirect) && (loginUrl || loginText);
                var challengePresent = hasSlider || hasChallengeWidget || explicitFailure || hardBlock || challengeMarker;
                return {
                    hardBlock: hardBlock,
                    explicitFailure: explicitFailure,
                    retryableFailure: !!(explicitFailure && !loginRequired && errorWidget && errorWidget.offsetParent !== null),
                    hasSlider: hasSlider,
                    hasChallengeWidget: hasChallengeWidget,
                    auctionItemCount: auctionItemCount,
                    validAuctionPayload: false,
                    loginRequired: loginRequired,
                    challengeMarker: challengeMarker,
                    challengePresent: challengePresent,
                    authenticatedPage: false,
                    href: href,
                    readyState: readyState,
                    title: title,
                    className: className,
                    errorCode: errorMatch ? errorMatch[0].replace(/\\s+/g, '').toLowerCase() : '',
                    bodyText: bodyText.slice(0, 1000)
                };
            }
            var summary = null;
            visitAccessibleDocuments(function(doc) {
                    if (summary === null) { summary = scan(doc); return null; }
                    var frameSummary = scan(doc);
                    summary.hardBlock = summary.hardBlock || frameSummary.hardBlock;
                    summary.explicitFailure = summary.explicitFailure || frameSummary.explicitFailure;
                    summary.retryableFailure = summary.retryableFailure || frameSummary.retryableFailure;
                    summary.hasSlider = summary.hasSlider || frameSummary.hasSlider;
                    summary.hasChallengeWidget = summary.hasChallengeWidget || frameSummary.hasChallengeWidget;
                    summary.frameChallengePresent = summary.frameChallengePresent || frameSummary.challengePresent;
                    summary.challengeMarker = summary.challengeMarker || frameSummary.challengeMarker;
                    summary.loginRequired = summary.loginRequired || frameSummary.loginRequired;
                    summary.auctionItemCount = Math.max(summary.auctionItemCount || 0, frameSummary.auctionItemCount || 0);
                    if (!summary.title && frameSummary.title) summary.title = frameSummary.title;
                    if (!summary.className && frameSummary.className) summary.className = frameSummary.className;
                    if (!summary.errorCode && frameSummary.errorCode) summary.errorCode = frameSummary.errorCode;
                    if (!summary.bodyText && frameSummary.bodyText) summary.bodyText = frameSummary.bodyText;
                    return null;
            }, true);
            // Private, transient evidence from the main document only; Python consumes it.
            summary._verificationHtml = '';
            if (summary.readyState !== 'loading' && !summary.hasSlider &&
                !summary.hasChallengeWidget && !summary.explicitFailure && !summary.frameChallengePresent) {
                summary._verificationHtml = document.documentElement ? document.documentElement.outerHTML : '';
            }
            summary.retryableFailure = !!(summary.retryableFailure && !summary.loginRequired);
            return summary;
        })()
        """
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": eval_in_all_frames(js_script),
            "returnByValue": True
        })
        if ret and "result" in ret and ret["result"].get("value"):
            return finalize_page_summary(ret["result"]["value"], getattr(self, "target_url", None))
        return {
            "probeFailed": True,
            "hardBlock": False,
            "explicitFailure": False,
            "retryableFailure": False,
            "hasSlider": False,
            "validAuctionPayload": False,
            "loginRequired": False,
            "challengeMarker": False,
            "challengePresent": False,
            "authenticatedPage": False,
            "href": "",
            "readyState": "",
            "title": "",
            "className": "",
            "errorCode": "",
            "bodyText": "",
        }

    def _close_solver_ws(self):
        if not self.ws:
            return
        self._release_cdp_mouse()
        try:
            self.ws.close()
        except Exception:
            pass
        self.ws = None

    def _refresh_challenge_summary(self, fallback):
        try:
            refreshed = self._page_challenge_summary()
        except Exception as error:
            logger.warning("[SOLVER] Challenge summary refresh failed: %s", error)
            return {**(fallback if isinstance(fallback, dict) else {}), "probeFailed": True}
        if not isinstance(refreshed, dict) or not refreshed:
            return {**(fallback if isinstance(fallback, dict) else {}), "probeFailed": True}
        return refreshed

    def _challenge_failure_diagnostic(self, summary):
        """Return bounded, query-free NC failure context for runtime logs."""
        payload = summary if isinstance(summary, dict) else {}
        title = re.sub(r"\s+", " ", str(payload.get("title") or "")).strip()[:100]
        class_name = re.sub(r"\s+", " ", str(payload.get("className") or "")).strip()[:120]
        error_code = re.sub(r"[^a-zA-Z0-9_:/-]", "", str(payload.get("errorCode") or ""))[:80]
        href = str(payload.get("href") or "").strip()
        try:
            parsed = urlsplit(href)
            safe_href = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))[:220]
        except ValueError:
            safe_href = ""
        return (
            f"code={error_code or 'none'} title={title or 'none'} "
            f"class={class_name or 'none'} path={safe_href or 'none'} "
            f"retryable={bool(payload.get('retryableFailure'))}"
        )

    def _preflight_already_authenticated(self):
        logger.info("[SOLVER] Auction page is already accessible; no captcha solve is required.")
        self.last_failure_reason = None
        self._close_solver_ws()
        return {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": True,
        }

    def _preflight_manual_required(self):
        self.last_failure_reason = "manual_required"
        self._close_solver_ws()
        return {
            "connected": False,
            "manual_required": True,
            "has_slider": False,
            "already_authenticated": False,
        }

    def _preflight_retryable_failure(self, reason="cdp_unavailable"):
        if not self._stop_if_cancelled():
            self.last_failure_reason = reason
        self._close_solver_ws()
        return {
            "connected": False,
            "manual_required": False,
            "has_slider": False,
            "already_authenticated": False,
        }

    def _wait_for_loading_document(self, summary):
        """Give an existing loading document a short window within the solve budget."""
        deadline = time.monotonic() + 8.0
        for _ in range(32):
            if (
                summary.get("probeFailed")
                or summary.get("readyState") != "loading"
                or summary.get("hasSlider")
            ):
                break
            if self._stop_if_cancelled():
                raise SolveStopped(self.last_failure_reason or "cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._wait_interruptibly(min(0.25, remaining))
            summary = self._refresh_challenge_summary(summary)
        return summary

    def _preflight_current_challenge(self):
        """Inspect the current CDP tab before slower solver fallbacks."""
        if not self.connect_tab():
            return {
                "connected": False,
                "manual_required": self.last_failure_reason == "manual_required",
                "has_slider": False,
                "already_authenticated": False,
            }

        try:
            challenge_summary = self._page_challenge_summary()
        except Exception as error:
            logger.warning("[SOLVER] Challenge preflight failed: %s", error)
            challenge_summary = {"probeFailed": True}

        challenge_summary = self._wait_for_loading_document(challenge_summary)
        has_slider = bool(challenge_summary.get("hasSlider"))
        if challenge_summary.get("probeFailed"):
            return self._preflight_retryable_failure()
        if challenge_summary.get("readyState") == "loading" and not has_slider:
            return self._preflight_retryable_failure("challenge_loading")
        if challenge_summary.get("authenticatedPage"):
            return self._preflight_already_authenticated()
        if challenge_summary.get("loginRequired") and not has_slider:
            logger.info("[SOLVER] Login page detected; waiting for QR/manual login to complete.")
            if self._poll_until_authenticated():
                return self._preflight_already_authenticated()
            challenge_summary = self._refresh_challenge_summary(challenge_summary)
            if challenge_summary.get("probeFailed"):
                return self._preflight_retryable_failure()
            has_slider = bool(challenge_summary.get("hasSlider"))
            if challenge_summary.get("authenticatedPage"):
                return self._preflight_already_authenticated()
            if not has_slider and challenge_summary.get("readyState") == "loading":
                return self._preflight_retryable_failure("challenge_loading")
            if has_slider:
                logger.info("[SOLVER] Slider appeared after login wait; continuing with drag solver.")
            elif challenge_summary.get("loginRequired") or challenge_summary.get("hardBlock"):
                logger.warning("[SOLVER] Login page detected; manual login is required.")
                return self._preflight_manual_required()
        if challenge_summary.get("hardBlock") and not has_slider:
            # A failed NC widget is actionable immediately. Waiting for the full
            # login-recovery window first only delays the retry by two minutes.
            if challenge_summary.get("explicitFailure"):
                logger.info("[SOLVER] Failed NC widget detected; trying retry-click immediately.")
                if self._reset_failed_nc_challenge():
                    challenge_summary = self._refresh_challenge_summary(challenge_summary)
                    if challenge_summary.get("probeFailed"):
                        return self._preflight_retryable_failure()
                    has_slider = bool(challenge_summary.get("hasSlider"))
                    if challenge_summary.get("authenticatedPage"):
                        return self._preflight_already_authenticated()
                    if has_slider:
                        logger.info("[SOLVER] Slider restored after immediate NC retry-click.")

            if not has_slider:
                logger.warning("[SOLVER] Unsupported hard block detected; waiting to see if the session recovers.")
                if self._poll_until_authenticated():
                    return self._preflight_already_authenticated()
                challenge_summary = self._refresh_challenge_summary(challenge_summary)
                if challenge_summary.get("probeFailed"):
                    return self._preflight_retryable_failure()
                has_slider = bool(challenge_summary.get("hasSlider"))
                if challenge_summary.get("authenticatedPage"):
                    return self._preflight_already_authenticated()
                if has_slider:
                    logger.info("[SOLVER] Slider appeared after hard-block wait; continuing with drag solver.")

            if not has_slider:
                logger.info("[SOLVER] Hard block without slider; trying NC retry-click to restore slider.")
                if self._reset_failed_nc_challenge():
                    challenge_summary = self._refresh_challenge_summary(challenge_summary)
                    if challenge_summary.get("probeFailed"):
                        return self._preflight_retryable_failure()
                    has_slider = bool(challenge_summary.get("hasSlider"))
                    if challenge_summary.get("authenticatedPage"):
                        return self._preflight_already_authenticated()
                    if has_slider:
                        logger.info("[SOLVER] Slider restored after NC retry-click; continuing with drag solver.")

            if not has_slider:
                # A failed retry widget probe is not proof of a terminal block.
                challenge_summary = self._refresh_challenge_summary(challenge_summary)
                if challenge_summary.get("probeFailed"):
                    return self._preflight_retryable_failure()
                if challenge_summary.get("authenticatedPage"):
                    return self._preflight_already_authenticated()
                has_slider = bool(challenge_summary.get("hasSlider"))
                if not has_slider and challenge_summary.get("readyState") == "loading":
                    return self._preflight_retryable_failure("challenge_loading")
            if not has_slider and (challenge_summary.get("hardBlock") or challenge_summary.get("loginRequired")):
                logger.warning("[SOLVER] Unsupported hard block detected; manual verification required.")
                return self._preflight_manual_required()

        return {
            "connected": bool(self.ws) or has_slider,
            "manual_required": False,
            "has_slider": has_slider,
            "already_authenticated": False,
        }

    def _headed_playwright_enabled(self):
        raw = project_getenv("CROW_SOLVER_ENABLE_HEADED_PLAYWRIGHT")
        if raw is not None:
            return raw.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False

    def _is_local_mock_slider_target(self):
        target_url = self._normalize_target_url(self.target_url)
        if not target_url:
            return False
        lowered = target_url.lower()
        if "mock_slider.html" in lowered or "test_slider_simple.html" in lowered:
            return True
        try:
            parsed = urlsplit(target_url)
        except ValueError:
            return False
        if parsed.scheme != "file":
            return False
        filename = Path(parsed.path or "").name.lower()
        return filename in {"mock_slider.html", "test_slider_simple.html"}

    def _local_mock_verification_mode(self):
        if not self._is_local_mock_slider_target():
            return None
        target_url = self._normalize_target_url(self.target_url)
        if not target_url:
            return "strict_success_text"
        try:
            parsed = urlsplit(target_url)
        except ValueError:
            return "strict_success_text"
        raw_mode = parse_qs(parsed.query or "").get("verifyMode", ["strict_success_text"])[0]
        mode = str(raw_mode or "").strip().lower()
        if mode in LOCAL_MOCK_VERIFY_MODES:
            return mode
        return "strict_success_text"


__all__ = ["CaptchaPreflightMixin"]
