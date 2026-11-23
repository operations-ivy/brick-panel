"""CLIMATE and LIGHTS: what their screens show, and the commands they send.

The page is never trusted with the rules. Every command comes here (from this
Pi only, web.py checks that), and is refused unless the panel lock allows a
change and the panel isn't read-only. A setpoint must be one the thermostat's
mode has, inside Home Assistant's guardrails, with auto's heat and cool at
least the gap apart. A light must be one of the panel's lights. Home
Assistant enforces the guardrails too. The lock is LCARS' (lock.py), and
Home Assistant's input_select.lcars_panel_lock overrides it on both panels."""

from __future__ import annotations

from dataclasses import dataclass

from . import lock as L
from .metrics import Metrics
from .setpoints import ACTION_LABELS
from .setpoints import MODE_LABELS
from .setpoints import MODES
from .setpoints import targets

SETPOINT_KEYS = ("temperature", "target_temp_low", "target_temp_high")


def brightness_pct(attrs: dict) -> int | None:
    """Home Assistant's 0-255 as a percent; None when it has none (off, or an
    on/off-only light)."""
    b = attrs.get("brightness")
    return None if b is None else round(b * 100 / 255)


def light_name(entity: str, attrs: dict, names: dict[str, str]) -> str:
    """The name the settings give it, else Home Assistant's, else the entity's."""
    fallback = attrs.get("friendly_name") or entity.split(".", 1)[-1].replace("_", " ")
    return (names.get(entity) or fallback).upper()


def available_modes(attrs: dict) -> list[str]:
    """The modes the thermostat has, in the screen's order."""
    return [m for m in MODES if m in (attrs.get("hvac_modes") or MODES)]


def check_setpoints(attrs: dict, data: object, lo: float, hi: float, gap: float) -> dict | None:
    """data, if it's a setpoint change the thermostat's current mode allows
    (only its keys, numbers inside lo-hi, auto's pair at least gap apart);
    else None."""
    keys = targets(attrs)
    if not isinstance(data, dict) or not data or not set(data) <= set(keys):
        return None
    out = {}
    for key, value in data.items():
        if isinstance(value, bool) or not isinstance(value, int | float) or not lo <= value <= hi:
            return None
        out[key] = value
    if len(keys) == 2:
        low = out.get("target_temp_low", attrs.get("target_temp_low"))
        high = out.get("target_temp_high", attrs.get("target_temp_high"))
        if low is None or high is None or high - low < gap:
            return None
        out = {"target_temp_low": low, "target_temp_high": high}  # set_temperature wants both in auto
    return out


@dataclass
class Controls:
    settings: dict
    ha: object  # HomeAssistant or DemoHomeAssistant
    lock: L.PanelLock
    metrics: Metrics
    room: object = None  # room.Room, when the panel has the sensor

    @classmethod
    def from_settings(cls, settings: dict, ha, metrics: Metrics, room=None) -> Controls:
        c = settings["climate"]
        lock = L.PanelLock(
            c["pin"],
            c["idle_relock_seconds"],
            c["misses_before_lockout"],
            c["lockout_seconds"],
            c["max_lockout_seconds"],
        )
        return cls(settings, ha, lock, metrics, room)

    @staticmethod
    def entities(settings: dict) -> list[str]:
        """Every Home Assistant entity the two screens read."""
        c = settings["climate"]
        return [
            c["thermostat"],
            c["lock_entity"],
            c["setpoint_min_entity"],
            c["setpoint_max_entity"],
            *settings["lights"]["entities"],
        ]

    # Reading.

    @property
    def read_only(self) -> bool:
        return bool(self.settings["climate"]["read_only"])

    @property
    def can_change(self) -> bool:
        return not self.read_only and self.lock.can_change

    def guardrails(self) -> tuple[float, float]:
        c = self.settings["climate"]
        lo, hi = c["default_guardrails"]
        return self.ha.number(c["setpoint_min_entity"], lo), self.ha.number(c["setpoint_max_entity"], hi)

    def link(self) -> str:
        """ "" while Home Assistant answers, else why not."""
        if self.ha.error:
            return self.ha.error
        return "" if self.ha.connected else "CONNECTING"

    def house(self) -> dict:
        """The upstairs room sensor, downstairs the ecobee, and their average
        (none from one floor alone), in Home Assistant's unit."""
        up = None
        if self.room is not None and self.room.fresh():
            up = self.room.temperature
            if self.ha.unit == "°C":
                up = (up - 32) * 5 / 9
        down = self.ha.attrs(self.settings["climate"]["thermostat"]).get("current_temperature")
        if up is None:
            note = "NO UPSTAIRS SENSOR" if self.room is None else "UPSTAIRS SENSOR OFFLINE"
        else:
            note = "" if down is not None else "NO THERMOSTAT READING"
        average = None if up is None or down is None else (up + down) / 2
        humidity = self.room.humidity if self.room is not None and self.room.fresh() else None
        return {"up": up, "down": down, "average": average, "humidity": humidity, "note": note}

    def lock_view(self) -> dict:
        self.lock.set_remote(self.ha.value(self.settings["climate"]["lock_entity"]))
        if self.lock.relock_if_idle():
            self.metrics.inc("panel_relocks_total", reason="idle")
        lock = self.lock
        return {
            "can_change": self.can_change,
            "unlocked": lock.unlocked,
            "remote": lock.remote,
            "read_only": self.read_only,
            "has_pin": bool(lock.pin),
            "lockout": round(lock.lockout_remaining()),
            "misses_left": lock.misses_before_lockout - lock.misses,
        }

    def climate_view(self) -> dict:
        c = self.settings["climate"]
        attrs = self.ha.attrs(c["thermostat"])
        mode = self.ha.value(c["thermostat"])
        lo, hi = self.guardrails()
        action = attrs.get("hvac_action")
        return {
            "available": bool(attrs),
            "mode": mode,
            "mode_label": MODE_LABELS.get(mode, (mode or "--").upper()),
            "modes": available_modes(attrs),
            "action": action,
            "action_label": ACTION_LABELS.get(action, (action or "--").upper()),
            "targets": targets(attrs),
            "setpoints": {k: attrs.get(k) for k in SETPOINT_KEYS},
            "guardrails": [lo, hi],
            "gap": c["heat_cool_gap"],
            "unit": self.ha.unit,
            "house": self.house(),
        }

    def lights_view(self) -> list[dict]:
        light_names = self.settings["lights"]["entities"]  # entity -> the name to show
        out = []
        for entity in light_names:
            state = self.ha.state(entity)
            attrs = (state or {}).get("attributes") or {}
            value = (state or {}).get("state")
            out.append(
                {
                    "entity": entity,
                    "name": light_name(entity, attrs, light_names),
                    "known": state is not None,
                    "available": value in ("on", "off"),
                    "on": value == "on",
                    "pct": brightness_pct(attrs),
                }
            )
        return out

    def view(self) -> dict:
        s = self.settings
        return {
            "link": self.link(),
            "lock": self.lock_view(),
            "climate": self.climate_view(),
            "lights": self.lights_view(),
            "send_after_ms": round(s["climate"]["send_after_seconds"] * 1000),
            "step_pct": s["lights"]["step_pct"],
        }

    # Commands: (ok, why not).

    def _allowed(self) -> str:
        if self.read_only:
            return "read only"
        self.lock_view()  # Home Assistant's override and the idle relock, as of now
        if not self.lock.can_change:
            return "locked"
        if self.link():
            return "no home assistant"
        return ""

    def _send(self, domain: str, service: str, action: str, **data: object) -> tuple[bool, str]:
        self.ha.call(domain, service, **data)
        self.lock.touch()
        self.metrics.inc("panel_commands_total", action=action)
        return True, ""

    def unlock(self, code: object) -> dict:
        self.lock_view()  # Home Assistant's override as of now: hard_locked refuses even the right code
        result = self.lock.try_code(str(code)[:16]) if isinstance(code, str | int) else L.DENIED
        self.metrics.inc("panel_unlock_attempts_total", result=result)
        return {"result": result, **self.lock_view()}

    def secure(self) -> dict:
        if self.lock.unlocked:
            self.metrics.inc("panel_relocks_total", reason="button")
        self.lock.lock()
        return self.lock_view()

    def touch(self) -> None:
        self.lock.touch()

    def set_setpoints(self, data: object) -> tuple[bool, str]:
        if why := self._allowed():
            return False, why
        c = self.settings["climate"]
        lo, hi = self.guardrails()
        checked = check_setpoints(self.ha.attrs(c["thermostat"]), data, lo, hi, c["heat_cool_gap"])
        if checked is None:
            return False, "not a setpoint this mode allows"
        return self._send("climate", "set_temperature", "set_temperature", entity_id=c["thermostat"], **checked)

    def set_mode(self, mode: object) -> tuple[bool, str]:
        if why := self._allowed():
            return False, why
        c = self.settings["climate"]
        if mode not in available_modes(self.ha.attrs(c["thermostat"])):
            return False, "not a mode this thermostat has"
        return self._send("climate", "set_hvac_mode", "set_hvac_mode", entity_id=c["thermostat"], hvac_mode=mode)

    def set_light(self, entity: object, on: object, pct: object = None) -> tuple[bool, str]:
        if why := self._allowed():
            return False, why
        if entity not in self.settings["lights"]["entities"]:
            return False, "not one of the panel's lights"
        if not isinstance(on, bool):
            return False, "on must be true or false"
        if not on:
            return self._send("light", "turn_off", "light_off", entity_id=entity)
        if pct is None:
            return self._send("light", "turn_on", "light_on", entity_id=entity)
        if isinstance(pct, bool) or not isinstance(pct, int) or not 1 <= pct <= 100:
            return False, "brightness is 1-100"
        return self._send("light", "turn_on", "light_brightness", entity_id=entity, brightness_pct=pct)
