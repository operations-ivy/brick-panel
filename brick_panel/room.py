"""The room's own temperature and humidity, from a Sensirion SHT3x (SHT30/31/35)
on the Pi's I2C bus, read in a background thread. Talks to /dev/i2c-N directly
(no packages): a single-shot, high-repeatability measurement, checked with the
chip's CRC. The Pi warms the air around it, so room.offset (the settings) corrects the
temperature (measure against a thermometer once)."""

from __future__ import annotations

import fcntl
import logging
import os
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metrics import Metrics

log = logging.getLogger(__name__)

I2C_SLAVE = 0x0703
MEASURE = bytes([0x24, 0x00])  # single shot, high repeatability, no clock stretching
MEASURE_SECONDS = 0.02  # 15 ms at most for high repeatability


def crc8(data: bytes) -> int:
    """Sensirion's CRC-8: polynomial 0x31, initial 0xFF."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def decode(raw: bytes) -> tuple[float, float]:
    """Six bytes (temp MSB, LSB, CRC, humidity MSB, LSB, CRC) -> (°F, %RH)."""
    if len(raw) != 6:
        raise ValueError(f"expected 6 bytes, got {len(raw)}")
    for word, crc in ((raw[0:2], raw[2]), (raw[3:5], raw[5])):
        if crc8(word) != crc:
            raise ValueError("CRC mismatch")
    t = int.from_bytes(raw[0:2], "big")
    rh = int.from_bytes(raw[3:5], "big")
    celsius = -45 + 175 * t / 65535
    return celsius * 9 / 5 + 32, 100 * rh / 65535


class I2C:
    """One device on /dev/i2c-<bus>."""

    def __init__(self, bus: int, address: int) -> None:
        self.path, self.address = f"/dev/i2c-{bus}", address

    def transfer(self, command: bytes, length: int, wait: float) -> bytes:
        fd = os.open(self.path, os.O_RDWR)
        try:
            fcntl.ioctl(fd, I2C_SLAVE, self.address)
            os.write(fd, command)
            time.sleep(wait)
            return os.read(fd, length)
        finally:
            os.close(fd)


class Room(threading.Thread):
    """Reads the sensor every poll_seconds: temperature in °F with offset
    added, humidity in %. device stands in for the I2C bus in tests."""

    def __init__(
        self,
        bus: int = 1,
        address: int = 0x44,
        offset: float = 0.0,
        poll_seconds: float = 30,
        metrics: Metrics | None = None,
        device: I2C | None = None,
    ) -> None:
        super().__init__(name="room", daemon=True)
        self.device = device or I2C(bus, address)
        self.offset, self.poll_seconds, self.metrics = offset, poll_seconds, metrics
        self._stopping = threading.Event()
        self.temperature: float | None = None
        self.humidity: float | None = None
        self.updated: float | None = None
        self.error = ""
        self._warned = False
        if metrics:
            metrics.set("panel_room_sensor_up", 0)

    def poll(self) -> bool:
        try:
            fahrenheit, humidity = decode(self.device.transfer(MEASURE, 6, MEASURE_SECONDS))
        except (OSError, ValueError) as e:
            self.error = "NO SENSOR" if isinstance(e, OSError) else "BAD READING"
            if not self._warned:  # once, not every 30 s while it's unplugged
                log.warning("room sensor: %s", e)
                self._warned = True
            if self.metrics:
                self.metrics.set("panel_room_sensor_up", 0)
                self.metrics.inc("panel_room_reads_total", result="error")
            return False
        self.temperature, self.humidity = fahrenheit + self.offset, humidity
        self.updated, self.error, self._warned = time.time(), "", False
        if self.metrics:
            self.metrics.set("panel_room_sensor_up", 1)
            self.metrics.inc("panel_room_reads_total", result="ok")
            self.metrics.set("panel_room_temperature_fahrenheit", round(self.temperature, 2))
            self.metrics.set("panel_room_humidity_percent", round(humidity, 1))
        return True

    def fresh(self, max_age: float = 300) -> bool:
        return self.updated is not None and time.time() - self.updated < max_age

    def document(self) -> dict:
        """The latest reading for Home Assistant (/room.json): null and
        "up": false while the sensor is offline."""
        up = self.fresh()
        return {
            "up": up,
            "temperature_f": round(self.temperature, 1) if up else None,
            "humidity": round(self.humidity, 1) if up else None,
        }

    def run(self) -> None:
        while not self._stopping.is_set():
            self.poll()
            self._stopping.wait(self.poll_seconds)

    def stop(self) -> None:
        self._stopping.set()
