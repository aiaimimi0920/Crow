from __future__ import annotations

import logging
import math
import os
import random
import time

from src.project_environment import getenv as project_getenv

from .captcha_budget import SolveStopped
from .captcha_os_target import OSPointerTarget
from .captcha_pointer_backend import (
    OSPointerBackend,
    PyAutoGUIPointerBackend,
    UInputPointerBackend,
    Win32PointerBackend,
)
from .captcha_x11_pointer import recover_xwayland_left_button

logger = logging.getLogger(__name__)


class CaptchaOSInputMixin:
    def _os_drag_profiles(self):
        # Keep the historically successful fast profile first. NC has a short
        # interaction window, so preserve movement timing while holding the
        # final endpoint for a random 1.5-2.5 seconds before release.
        profiles = (
            {
                "name": "fast_exact_v3",
                "pre_pause": (0.05, 0.15),
                "press_hold": (0.04, 0.08),
                "total_time": (0.4, 0.65),
                "steps": (24, 32),
                "tremor_x": 0.2,
                "tremor_y": 0.4,
                "micro_pause_prob": 0.05,
                "micro_pause": (0.015, 0.05),
                "overshoot": (0.0, 1.2),
                "release_overshoot": (0.0, 0.0),
                "settle_steps": (2, 3),
                "hold_before_release": (1.5, 2.5),
                "release_mode": "exact_release",
                "warmup_px": (1.0, 3.0),
                "warmup_steps": (1, 2),
                "approach_duration": (0.05, 0.15),
                "start_duration": (0.05, 0.15),
            },
            {
                "name": "legacy_exact_release",
                "pre_pause": (0.35, 0.7),
                "press_hold": (0.12, 0.24),
                "total_time": (1.8, 2.6),
                "steps": (48, 68),
                "tremor_x": 0.5,
                "tremor_y": 0.9,
                "micro_pause_prob": 0.08,
                "micro_pause": (0.02, 0.06),
                "overshoot": (4.0, 8.0),
                "release_overshoot": (0.0, 0.0),
                "settle_steps": (3, 5),
                "hold_before_release": (1.5, 2.5),
                "release_mode": "exact_release",
                "warmup_px": (2.0, 5.0),
                "warmup_steps": (2, 3),
                "approach_duration": (0.25, 0.5),
                "start_duration": (0.2, 0.4),
            },
            {
                "name": "dense_exact_release",
                "pre_pause": (0.4, 0.8),
                "press_hold": (0.14, 0.28),
                "total_time": (2.4, 3.4),
                "steps": (72, 96),
                "tremor_x": 0.6,
                "tremor_y": 1.1,
                "micro_pause_prob": 0.1,
                "micro_pause": (0.025, 0.07),
                "overshoot": (5.0, 9.0),
                "release_overshoot": (0.0, 0.0),
                "settle_steps": (4, 6),
                "hold_before_release": (1.5, 2.5),
                "release_mode": "exact_release",
                "warmup_px": (2.0, 6.0),
                "warmup_steps": (2, 4),
                "approach_duration": (0.3, 0.6),
                "start_duration": (0.25, 0.5),
            },
        )
        if os.name != "nt":
            # Physical Linux desktop: visible, bounded motion rather than the
            # sub-second Windows profile. Endpoint hold remains a separate phase.
            for index, profile in enumerate(profiles):
                profile.update(
                    name=("slow_exact_v4", "slow_settle_v4", "slow_dense_v4")[index],
                    total_time=(2.6 + index * 0.4, 3.6 + index * 0.4),
                    steps=(72 + index * 8, 88 + index * 8),
                    pre_pause=(0.3, 0.6), press_hold=(0.18, 0.3),
                    approach_duration=(0.35, 0.6), start_duration=(0.25, 0.4),
                    tremor_x=0.7, pixel_tremor=True, normalize_duration=True,
                    overshoot=(0.0, 1.2), settle_steps=(3, 5),
                )
        return profiles

    def _os_drag_profile(self, variant_index=0):
        profiles = self._os_drag_profiles()
        if not profiles:
            raise RuntimeError("OS drag profiles are unavailable")
        normalized_index = int(variant_index or 0) % len(profiles)
        return dict(profiles[normalized_index])

    def _os_drag_track(self, distance, profile):
        steps = max(int(random.uniform(*profile["steps"])), 1)
        total = random.uniform(*profile["total_time"])
        fracs = []
        dwells = []
        phase = random.uniform(1.5, 2.5) * math.pi
        previous = 0.0
        for index in range(1, steps + 1):
            ratio = index / steps
            eased = ratio * ratio * (3.0 - 2.0 * ratio)
            if index < steps:
                eased += math.sin(ratio * phase) * 0.002
                eased += random.gauss(0.0, 0.0008)
                eased = max(previous + 0.0005, min(eased, 0.998))
            else:
                eased = 1.0
            fracs.append(eased)
            previous = eased
            step_dwell = (total / steps) * random.uniform(0.75, 1.25)
            dwells.append(max(0.006, min(step_dwell, 0.06)))
        if profile.get("normalize_duration"):
            duration_scale = total / sum(dwells)
            dwells = [value * duration_scale for value in dwells]
        return fracs, dwells

    def _os_drag_y_track(self, count, profile):
        if not profile.get("pixel_tremor"):
            return []
        offsets, drift, target, remaining = [], 0.0, 0.0, 0
        for _ in range(count):
            if remaining <= 0:
                target = random.choice((-1, 1)) * random.uniform(1.25, 2.4)
                remaining = random.randint(4, 8)
            drift += (target - drift) * 0.5
            offsets.append(drift)
            remaining -= 1
        return offsets

    def _os_drag_release_plan(self, sx, phys_distance, profile):
        release_mode = str(profile.get("release_mode") or "overshoot_release").strip().lower()
        if release_mode == "exact_release":
            peak_overshoot = max(random.uniform(*profile["overshoot"]), 0.0)
            peak_x = sx + phys_distance + peak_overshoot
            release_x = sx + phys_distance
            settle_steps = max(int(random.uniform(*profile["settle_steps"])), 1)
            settle_xs = []
            for step in range(settle_steps):
                ratio = (step + 1) / settle_steps
                settle_xs.append(peak_x + (release_x - peak_x) * ratio)
            return peak_x, settle_xs, release_x

        release_overshoot = random.uniform(*profile["release_overshoot"])
        peak_overshoot = max(random.uniform(*profile["overshoot"]), release_overshoot)
        peak_x = sx + phys_distance + peak_overshoot
        release_x = sx + phys_distance + release_overshoot
        settle_steps = max(int(random.uniform(*profile["settle_steps"])), 1)
        settle_xs = []
        for step in range(settle_steps):
            ratio = (step + 1) / settle_steps
            settle_xs.append(peak_x + (release_x - peak_x) * ratio)
        return peak_x, settle_xs, release_x

    def _os_drag_warmup_points(self, sx, sy, profile):
        warmup_steps = max(int(random.uniform(*profile.get("warmup_steps", (0, 0)))), 0)
        if warmup_steps <= 0:
            return []
        warmup_px = random.uniform(*profile.get("warmup_px", (0.0, 0.0)))
        points = []
        for step in range(1, warmup_steps + 1):
            ratio = step / warmup_steps
            points.append((
                sx + warmup_px * ratio,
                sy + random.gauss(0, min(profile["tremor_y"], 0.8)),
            ))
        return points

    def _native_os_input_enabled(self):
        # PyAutoGUI is the production-proven input path for Aliyun NC. Keep the
        # lower-level Win32 injector as an explicit fallback instead of silently
        # changing the mouse event stream on every Windows deployment.
        backend = str(project_getenv("CROW_SOLVER_OS_INPUT_BACKEND", "pyautogui")).strip().lower()
        return os.name == "nt" and backend in {"native", "win32"}

    def _uinput_os_input_enabled(self):
        backend = str(project_getenv("CROW_SOLVER_OS_INPUT_BACKEND", "pyautogui")).strip().lower()
        return os.name != "nt" and backend == "uinput"

    def _get_uinput_handle(self):
        if not self._uinput_os_input_enabled():
            return None
        if self._uinput_handle is not None:
            return self._uinput_handle
        if not os.path.exists("/dev/uinput"):
            raise RuntimeError("/dev/uinput is unavailable")
        try:
            from evdev import UInput, ecodes
        except ImportError as error:
            raise RuntimeError("python-evdev is unavailable") from error
        capabilities = {
            ecodes.EV_KEY: [ecodes.BTN_LEFT],
            ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y],
        }
        self._uinput_handle = UInput(
            capabilities,
            name="fapaifang-virtual-mouse",
            vendor=0x046D,
            product=0xC077,
            version=1,
        )
        self._uinput_ecodes = ecodes
        # Allow the host compositor to register the new input device before
        # the first relative move.
        self._wait_interruptibly(0.35)
        return self._uinput_handle

    def _move_uinput_cursor_to(self, pyautogui, target_x, target_y):
        handle = self._get_uinput_handle()
        ecodes = self._uinput_ecodes
        if handle is None or ecodes is None:
            raise RuntimeError("uinput mouse is not initialized")
        for _ in range(36):
            current_x, current_y = self._get_os_cursor_position(pyautogui)
            error_x = float(target_x) - float(current_x)
            error_y = float(target_y) - float(current_y)
            if math.hypot(error_x, error_y) <= 1.25:
                return

            def bounded_step(value):
                if abs(value) < 0.5:
                    return 0
                magnitude = max(1, min(int(round(abs(value))), 64))
                return magnitude if value > 0 else -magnitude

            relative_x = bounded_step(error_x)
            relative_y = bounded_step(error_y)
            if relative_x:
                handle.write(ecodes.EV_REL, ecodes.REL_X, relative_x)
            if relative_y:
                handle.write(ecodes.EV_REL, ecodes.REL_Y, relative_y)
            handle.syn()
            self._wait_interruptibly(0.01)
        final_x, final_y = self._get_os_cursor_position(pyautogui)
        final_error = math.hypot(float(target_x) - float(final_x), float(target_y) - float(final_y))
        self.last_failure_reason = "os_cursor_position_unverified"
        raise RuntimeError(f"uinput cursor did not converge (delta={final_error:.1f}px)")

    def _get_os_cursor_position(self, pyautogui):
        return self._os_pointer_backend(pyautogui).position()

    def _uinput_button_device(self):
        handle = self._get_uinput_handle()
        ecodes = self._uinput_ecodes
        if handle is None or ecodes is None:
            raise RuntimeError("uinput mouse is not initialized")
        return handle, ecodes.EV_KEY, ecodes.BTN_LEFT

    def _os_pointer_backend(self, pyautogui) -> OSPointerBackend:
        override = getattr(self, "_pointer_backend_override", None)
        if override is not None:
            return override
        if self._uinput_os_input_enabled():
            return UInputPointerBackend(
                pyautogui.position,
                lambda x, y: self._move_uinput_cursor_to(pyautogui, x, y),
                self._uinput_button_device,
            )
        if self._native_os_input_enabled():
            return Win32PointerBackend()
        return PyAutoGUIPointerBackend(pyautogui)

    def _set_os_cursor_position(self, pyautogui, x, y):
        self._os_pointer_backend(pyautogui).move(x, y)

    def _set_os_left_button(self, pyautogui, *, down):
        self._os_pointer_backend(pyautogui).left_button(down=down)

    def _move_os_cursor_bounded(self, pyautogui, target_x, target_y, duration):
        """Move in a small fixed number of steps so Windows timer granularity cannot amplify duration."""
        duration = max(float(duration or 0), 0.0)
        try:
            start_x, start_y = self._get_os_cursor_position(pyautogui)
        except SolveStopped:
            raise
        except Exception:
            self._set_os_cursor_position(pyautogui, target_x, target_y)
            if duration:
                self._wait_interruptibly(duration)
            return
        steps = max(3, min(12, int(math.ceil(duration * 30))))
        dwell = duration / steps if steps else 0.0
        for step in range(1, steps + 1):
            ratio = step / steps
            eased = ratio * ratio * (3.0 - 2.0 * ratio)
            x = float(start_x) + (float(target_x) - float(start_x)) * eased
            y = float(start_y) + (float(target_y) - float(start_y)) * eased
            self._set_os_cursor_position(pyautogui, x, y)
            if dwell:
                self._wait_interruptibly(dwell)

    def _move_os_cursor_timed(self, pyautogui, target_x, target_y, duration):
        """Keep PyAutoGUI's proven timing; bound only the opt-in native backend."""
        backend = self._os_pointer_backend(pyautogui)
        if backend.supports_duration:
            backend.move(target_x, target_y, duration=max(float(duration or 0), 0.0))
            return
        self._move_os_cursor_bounded(pyautogui, target_x, target_y, duration)

    def _ensure_os_left_button_released(self, mapped):
        if os.name == "nt" or mapped.get("source") != "x11_window_geometry":
            return True
        result = recover_xwayland_left_button()
        if result.get("released"):
            logger.info("[SOLVER] Released stale Xwayland left button devices=%s", result["released"])
        if not result.get("verified"):
            self.last_failure_reason = "os_button_state_unverified"
            logger.warning("[SOLVER] OS left-button release not verified: %s", result.get("reason"))
            return False
        return True

    def _do_drag_os(self, start_x, start_y, distance, slider_info=None, profile_variant_index=0):
        probe = OSPointerTarget(self, slider_info, start_x, start_y)
        try:
            return self._do_drag_os_target(
                start_x, start_y, distance, slider_info, profile_variant_index, probe
            )
        finally:
            probe.close()

    def _do_drag_os_target(self, start_x, start_y, distance, slider_info, profile_variant_index, probe):
        """OS-level mouse drag. CDP Input events are rejected by Aliyun NC (error:TJiA4d/Vx6urd)."""
        self.last_failure_reason = None
        pyautogui = None
        if self._pointer_backend_override is None:
            try:
                import pyautogui
            except ImportError:
                logger.warning("[SOLVER] pyautogui not installed; skipping OS mouse drag.")
                return None
            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0
        self._enable_process_dpi_awareness()
        if self._pointer_backend_override is None and self._uinput_os_input_enabled():
            try:
                self._get_uinput_handle()
            except SolveStopped:
                raise
            except Exception as error:
                self.last_failure_reason = "uinput_unavailable"
                logger.warning("[SOLVER] uinput mouse unavailable: %s", error)
                return None
        try:
            focused = self._focus_os_window()
        except SolveStopped:
            raise
        except Exception as error:
            self.last_failure_reason = "window_focus_failed"
            logger.warning("[SOLVER] OS window focus failed: %s", error)
            return None
        if not focused:
            self.last_failure_reason = "window_focus_failed"
            logger.warning("[SOLVER] OS window focus failed; skipping OS mouse drag.")
            return None
        self._wait_interruptibly(0.45)
        if probe.enabled:
            if not probe.open():
                return None
            start_x, start_y = probe.point
            slider_info = {**slider_info, **probe.rect}
            track_width = self._get_track_width()
            slider_info["track_width"] = track_width
            distance = self._remaining_drag_distance(slider_info, self._get_track_rect(), track_width)
        mapped = None
        mapping_attempts = 3 if isinstance(slider_info, dict) else 1
        for mapping_attempt in range(1, mapping_attempts + 1):
            try:
                mapped = self._map_css_to_screen(start_x, start_y, distance, slider_info=slider_info)
            except SolveStopped:
                raise
            except Exception as error:
                self.last_failure_reason = "screen_mapping_exception"
                logger.warning("[SOLVER] Screen mapping failed: %s", error)
                return None
            if mapped and (not isinstance(slider_info, dict) or mapped.get("located")):
                break
            if mapping_attempt < mapping_attempts:
                logger.info(
                    f"[SOLVER] Waiting for verified slider screen mapping "
                    f"({mapping_attempt}/{mapping_attempts})..."
                )
                self._wait_interruptibly(0.3)
        if not mapped:
            if not self.last_failure_reason:
                self.last_failure_reason = "screen_mapping_unavailable"
            return None
        if isinstance(slider_info, dict) and not mapped.get("located"):
            self.last_failure_reason = "screen_mapping_unverified"
            logger.warning("[SOLVER] Slider screenshot mapping could not be verified; skipping OS drag.")
            return None
        sx = mapped["x"]
        sy = mapped["y"]
        phys_distance = mapped["distance"]
        if not self._ensure_os_left_button_released(mapped):
            return None
        profile = self._os_drag_profile(profile_variant_index)
        logger.info(
            f"[SOLVER] OS mouse drag from ({sx:.0f},{sy:.0f}) +{phys_distance:.0f}px "
            f"source={mapped.get('source')} located={mapped.get('located')} "
            f"clipped={mapped.get('clipped')} profile={profile.get('name')} "
            f"input={'uinput' if self._uinput_os_input_enabled() else ('win32' if self._native_os_input_enabled() else 'pyautogui')}"
        )
        mouse_is_down = False
        drag_completed = False
        try:
            # 1. 移动到滑块起点附近的随机位置（更像人眼/鼠标先找位置）
            self._move_os_cursor_timed(
                pyautogui,
                sx - random.uniform(18, 36),
                sy + random.uniform(-10, 10),
                random.uniform(*profile.get("approach_duration", (0.25, 0.5))),
            )
            self._wait_interruptibly(random.uniform(*profile["pre_pause"]))
            self._move_os_cursor_timed(
                pyautogui,
                sx,
                sy,
                random.uniform(*profile.get("start_duration", (0.25, 0.6))),
            )
            if os.name != "nt" and mapped.get("source") == "x11_window_geometry":
                try:
                    cursor_x, cursor_y = self._get_os_cursor_position(pyautogui)
                    cursor_delta = math.hypot(float(cursor_x) - sx, float(cursor_y) - sy)
                except SolveStopped:
                    raise
                except Exception as error:
                    self.last_failure_reason = "os_cursor_position_unverified"
                    logger.warning("[SOLVER] OS cursor position check failed: %s", error)
                    return None
                logger.info(
                    f"[SOLVER] OS cursor position expected=({sx:.0f},{sy:.0f}) "
                    f"actual=({float(cursor_x):.0f},{float(cursor_y):.0f}) "
                    f"delta={cursor_delta:.1f}px"
                )
                if cursor_delta > 5.0:
                    self.last_failure_reason = "os_cursor_position_unverified"
                    logger.warning("[SOLVER] OS cursor did not reach the verified slider point.")
                    return None
            self._wait_interruptibly(random.uniform(*profile["press_hold"]))
            if probe.enabled:
                corrected = probe.verify(pyautogui, mapped)
                if corrected is None:
                    return None
                sx, sy = corrected
                phys_distance = distance * probe.scale
            mouse_is_down = True
            self._set_os_left_button(pyautogui, down=True)
            pressed_at = time.monotonic()
            self._wait_interruptibly(random.uniform(*profile["press_hold"]))
            for warmup_x, warmup_y in self._os_drag_warmup_points(sx, sy, profile):
                if self._stop_if_cancelled():
                    self.last_failure_reason = self.last_failure_reason or "cancelled"
                    return None
                self._set_os_cursor_position(pyautogui, warmup_x, warmup_y)
                self._wait_interruptibly(random.uniform(0.04, 0.09))
            fracs, dwells = self._os_drag_track(phys_distance, profile)
            y_offsets = self._os_drag_y_track(len(fracs), profile)
            prev_x = sx
            target_x = sx + phys_distance
            for index, (eased, dwell) in enumerate(zip(fracs, dwells, strict=True)):
                if self._stop_if_cancelled():
                    self.last_failure_reason = self.last_failure_reason or "cancelled"
                    return None
                x = sx + phys_distance * eased
                # 极小幅度回拉（0.5-1.5px），避免严格单调递增
                if random.random() < 0.04:
                    x -= random.uniform(0.5, 1.5)
                x += random.gauss(0, profile["tremor_x"])
                if profile.get("monotonic_x"):
                    # Preserve the monotonic profile after random perturbations.
                    # The final sample remains exactly on the target endpoint.
                    minimum_x = min(prev_x + 0.01, target_x)
                    x = max(minimum_x, min(x, target_x))
                # Y 轴：主体使用 tremor 抖动，末尾 20% 加大 Y 漂移模拟"快到终点时手抖"
                y = sy + (y_offsets[index] if y_offsets else random.gauss(0, profile["tremor_y"]))
                if not y_offsets and eased > 0.8 and random.random() < 0.25:
                    y += random.uniform(-1.5, 1.5)
                self._set_os_cursor_position(pyautogui, x, y)
                prev_x = x
                self._wait_interruptibly(dwell)
                if random.random() < profile["micro_pause_prob"]:
                    self._wait_interruptibly(random.uniform(*profile["micro_pause"]))
            peak_x, settle_xs, release_x = self._os_drag_release_plan(sx, phys_distance, profile)
            self._set_os_cursor_position(pyautogui, peak_x, sy)
            self._wait_interruptibly(random.uniform(0.06, 0.16))
            for settle_x in settle_xs:
                self._set_os_cursor_position(pyautogui, settle_x, sy + random.gauss(0, 1.2))
                self._wait_interruptibly(random.uniform(0.03, 0.07))
            # 释放前最后一次下压/微调
            self._move_os_cursor_timed(
                pyautogui,
                release_x,
                sy if y_offsets else sy + random.gauss(0, 0.8),
                random.uniform(0.05, 0.15),
            )
            arrived_at = time.monotonic()
            self._wait_interruptibly(random.uniform(*profile["hold_before_release"]))
            held_seconds = time.monotonic() - arrived_at
            self._set_os_left_button(pyautogui, down=False)
            mouse_is_down = False
            logger.info(
                "[SOLVER] OS drag timing movement=%.3fs hold=%.3fs",
                arrived_at - pressed_at, held_seconds,
            )
            if not self._ensure_os_left_button_released(mapped):
                return None
            self._wait_interruptibly(random.uniform(0.4, 0.7))
            drag_completed = True
        except SolveStopped:
            raise
        except Exception as error:
            if not self.last_failure_reason:
                self.last_failure_reason = "mouse_drag_exception"
            logger.exception("[SOLVER] OS mouse drag failed")
        finally:
            if mouse_is_down:
                try:
                    self._set_os_left_button(pyautogui, down=False)
                    logger.info("[SOLVER] Released OS mouse button after interrupted drag.")
                except Exception as release_error:
                    logger.warning("[SOLVER] OS mouse release failed: %s", release_error)
        if not drag_completed:
            return None
        return start_x + distance


__all__ = ["CaptchaOSInputMixin"]
