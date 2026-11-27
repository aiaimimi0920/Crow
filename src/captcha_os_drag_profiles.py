from __future__ import annotations

import math
import os
import random


class CaptchaOSDragProfilesMixin:
    def _os_is_windows(self) -> bool:
        return os.name == "nt"

    def _os_drag_profiles(self):
        # Keep the historically successful fast profile first. NC has a short
        # interaction window, so preserve movement timing while holding the
        # final endpoint before release.
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
                "hold_before_release": (0.08, 0.28),
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
                "hold_before_release": (0.08, 0.28),
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
                "hold_before_release": (0.08, 0.28),
                "release_mode": "exact_release",
                "warmup_px": (2.0, 6.0),
                "warmup_steps": (2, 4),
                "approach_duration": (0.3, 0.6),
                "start_duration": (0.25, 0.5),
            },
        )
        if not self._os_is_windows():
            # Physical Linux desktop: human-scale motion (~0.5-1.5s for 256px).
            for index, profile in enumerate(profiles):
                profile.update(
                    name=("slow_exact_v4", "slow_settle_v4", "slow_dense_v4")[index],
                    total_time=(0.55 + index * 0.12, 1.05 + index * 0.18),
                    steps=(30 + index * 4, 42 + index * 6),
                    pre_pause=(0.08, 0.25),
                    press_hold=(0.05, 0.15),
                    approach_duration=(0.06, 0.16),
                    start_duration=(0.05, 0.14),
                    tremor_x=0.7,
                    pixel_tremor=True,
                    normalize_duration=True,
                    overshoot=(2.0, 5.0),
                    settle_steps=(2, 3),
                )
        return profiles

    def _os_drag_profile(self, variant_index=0):
        profiles = self._os_drag_profiles()
        if not profiles:
            raise RuntimeError("OS drag profiles are unavailable")
        normalized_index = int(variant_index or 0) % len(profiles)
        return dict(profiles[normalized_index])

    def _os_drag_track(self, distance, profile):
        _ = distance
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
        release_mode = (
            str(profile.get("release_mode") or "overshoot_release").strip().lower()
        )
        if release_mode == "exact_release":
            peak_overshoot = max(random.uniform(*profile["overshoot"]), 0.0)
            peak_x = sx + phys_distance + peak_overshoot
            release_x = sx + phys_distance
            settle_steps = max(int(random.uniform(*profile["settle_steps"])), 1)
            settle_xs = [
                peak_x + (release_x - peak_x) * ((step + 1) / settle_steps)
                for step in range(settle_steps)
            ]
            return peak_x, settle_xs, release_x

        release_overshoot = random.uniform(*profile["release_overshoot"])
        peak_overshoot = max(random.uniform(*profile["overshoot"]), release_overshoot)
        peak_x = sx + phys_distance + peak_overshoot
        release_x = sx + phys_distance + release_overshoot
        settle_steps = max(int(random.uniform(*profile["settle_steps"])), 1)
        settle_xs = [
            peak_x + (release_x - peak_x) * ((step + 1) / settle_steps)
            for step in range(settle_steps)
        ]
        return peak_x, settle_xs, release_x

    def _os_drag_warmup_points(self, sx, sy, profile):
        warmup_steps = max(int(random.uniform(*profile.get("warmup_steps", (0, 0)))), 0)
        if warmup_steps <= 0:
            return []
        warmup_px = random.uniform(*profile.get("warmup_px", (0.0, 0.0)))
        return [
            (
                sx + warmup_px * (step / warmup_steps),
                sy + random.gauss(0, min(profile["tremor_y"], 0.8)),
            )
            for step in range(1, warmup_steps + 1)
        ]


__all__ = ["CaptchaOSDragProfilesMixin"]
