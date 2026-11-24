"""The room's own temperature and humidity (and air pressure, from a BME280),
read in a background thread from a sensor on the Pi's I2C bus. Talks to
/dev/i2c-N directly (no packages). Two chips, chosen by room.chip:

- sht3x: a Sensirion SHT3x (SHT30/31/35) at 0x44. A single-shot,
  high-repeatability measurement, checked with the chip's CRC.
- bme280: a Bosch BME280 at 0x76 (the Pimoroni Multi-Sensor Stick's). A
  forced measurement, compensated with the chip's own calibration.

The Pi warms the air around it, so room.offset (the settings) corrects the
temperature (measure against a thermometer once)."""

from __future__ import annotations

import fcntl
import logging
import os
import threading
import time
from typing import Protocol
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metrics import Metrics

log = logging.getLogger(__name__)

I2C_SLAVE = 0x0703
MEASURE = bytes([0x24, 0x00])  # SHT3x: single shot, high repeatability, no clock stretching
MEASURE_SECONDS = 0.02  # 15 ms at most for high repeatability


class Device(Protocol):
    """An I2C device: I2C below, or a stand-in in tests."""

    def transfer(self, command: bytes, length: int, wait: float) -> bytes:
        """Write command, wait, read length bytes."""

    def write(self, data: bytes) -> None:
        """Write data."""


def crc8(data: bytes) -> int:
    """Sensirion's CRC-8: polynomial 0x31, initial 0xFF."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def celsius_to_fahrenheit(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def decode(raw: bytes) -> tuple[float, float]:
    """SHT3x: six bytes (temp MSB, LSB, CRC, humidity MSB, LSB, CRC) -> (°F, %RH)."""
    if len(raw) != 6:
        raise ValueError(f"expected 6 bytes, got {len(raw)}")
    for word, crc in ((raw[0:2], raw[2]), (raw[3:5], raw[5])):
        if crc8(word) != crc:
            raise ValueError("CRC mismatch")
    t = int.from_bytes(raw[0:2], "big")
    rh = int.from_bytes(raw[3:5], "big")
    return celsius_to_fahrenheit(-45 + 175 * t / 65535), 100 * rh / 65535


class SHT3x:
    address = 0x44

    def read(self, device: Device) -> tuple[float, float, float | None]:
        """(°F, %RH, no pressure)."""
        fahrenheit, humidity = decode(device.transfer(MEASURE, 6, MEASURE_SECONDS))
        return fahrenheit, humidity, None


# BME280 registers (Bosch's datasheet, BST-BME280-DS002).
BME_ID, BME_CHIP_ID = 0xD0, 0x60
BME_CALIB_TP, BME_CALIB_H = 0x88, 0xE1  # 26 and 7 bytes
BME_CTRL_HUM, BME_CTRL_MEAS, BME_DATA = 0xF2, 0xF4, 0xF7
BME_HUMIDITY_X1 = 0x01
BME_FORCED_X1 = 0x25  # temperature x1, pressure x1, forced mode
BME_MEASURE_SECONDS = 0.02  # 9.3 ms at most at x1 oversampling
BME_SKIPPED = 0x80000  # what a skipped temperature or pressure reads


def _s16(data: bytes, at: int) -> int:
    return int.from_bytes(data[at : at + 2], "little", signed=True)


def _u16(data: bytes, at: int) -> int:
    return int.from_bytes(data[at : at + 2], "little")


def _s8(byte: int) -> int:
    return byte - 256 if byte > 127 else byte


class BME280Calibration:
    """The chip's trimming values, from its 26 + 7 calibration bytes."""

    def __init__(self, tp: bytes, h: bytes) -> None:
        if len(tp) != 26 or len(h) != 7:
            raise ValueError(f"expected 26 + 7 calibration bytes, got {len(tp)} + {len(h)}")
        self.t1, self.t2, self.t3 = _u16(tp, 0), _s16(tp, 2), _s16(tp, 4)
        self.p1 = _u16(tp, 6)
        self.p2, self.p3, self.p4, self.p5, self.p6, self.p7, self.p8, self.p9 = (
            _s16(tp, at) for at in range(8, 24, 2)
        )
        self.h1 = tp[25]
        self.h2, self.h3 = _s16(h, 0), h[2]
        self.h4 = (_s8(h[3]) << 4) | (h[4] & 0x0F)
        self.h5 = (_s8(h[5]) << 4) | (h[4] >> 4)
        self.h6 = _s8(h[6])


def bme280_compensate(cal: BME280Calibration, raw: bytes) -> tuple[float, float, float]:
    """Eight data bytes (pressure, temperature, humidity) -> (°C, %RH, hPa),
    with the datasheet's floating-point formulas."""
    if len(raw) != 8:
        raise ValueError(f"expected 8 bytes, got {len(raw)}")
    adc_p = (raw[0] << 12) | (raw[1] << 4) | (raw[2] >> 4)
    adc_t = (raw[3] << 12) | (raw[4] << 4) | (raw[5] >> 4)
    adc_h = (raw[6] << 8) | raw[7]
    if BME_SKIPPED in (adc_t, adc_p):
        raise ValueError("measurement skipped")

    var1 = (adc_t / 16384 - cal.t1 / 1024) * cal.t2
    var2 = (adc_t / 131072 - cal.t1 / 8192) ** 2 * cal.t3
    t_fine = var1 + var2
    celsius = t_fine / 5120

    var1 = t_fine / 2 - 64000
    var2 = var1 * var1 * cal.p6 / 32768 + var1 * cal.p5 * 2
    var2 = var2 / 4 + cal.p4 * 65536
    var1 = (cal.p3 * var1 * var1 / 524288 + cal.p2 * var1) / 524288
    var1 = (1 + var1 / 32768) * cal.p1
    if var1 == 0:
        raise ValueError("bad pressure calibration")
    pa = (1048576 - adc_p - var2 / 4096) * 6250 / var1
    pa += (cal.p9 * pa * pa / 2147483648 + pa * cal.p8 / 32768 + cal.p7) / 16

    h = t_fine - 76800
    h = (adc_h - (cal.h4 * 64 + cal.h5 / 16384 * h)) * (
        cal.h2 / 65536 * (1 + cal.h6 / 67108864 * h * (1 + cal.h3 / 67108864 * h))
    )
    h *= 1 - cal.h1 * h / 524288
    return celsius, min(max(h, 0.0), 100.0), pa / 100


class BME280:
    address = 0x76

    def __init__(self) -> None:
        self.calibration: BME280Calibration | None = None

    def read(self, device: Device) -> tuple[float, float, float]:
        """(°F, %RH, hPa). Reads the calibration on first use, and again
        after a failure (the stick may have been replugged)."""
        try:
            if self.calibration is None:
                if device.transfer(bytes([BME_ID]), 1, 0) != bytes([BME_CHIP_ID]):
                    raise ValueError("not a BME280")
                self.calibration = BME280Calibration(
                    device.transfer(bytes([BME_CALIB_TP]), 26, 0),
                    device.transfer(bytes([BME_CALIB_H]), 7, 0),
                )
            # ctrl_hum only takes effect with the ctrl_meas write after it.
            device.write(bytes([BME_CTRL_HUM, BME_HUMIDITY_X1]))
            device.write(bytes([BME_CTRL_MEAS, BME_FORCED_X1]))
            time.sleep(BME_MEASURE_SECONDS)
            celsius, humidity, hpa = bme280_compensate(self.calibration, device.transfer(bytes([BME_DATA]), 8, 0))
        except (OSError, ValueError):
            self.calibration = None
            raise
        return celsius_to_fahrenheit(celsius), humidity, hpa


CHIPS = {"sht3x": SHT3x, "bme280": BME280}


class I2C:
    """One device on /dev/i2c-<bus>."""

    def __init__(self, bus: int, address: int) -> None:
        self.path, self.address = f"/dev/i2c-{bus}", address

    def _open(self) -> int:
        fd = os.open(self.path, os.O_RDWR)
        try:
            fcntl.ioctl(fd, I2C_SLAVE, self.address)
        except OSError:
            os.close(fd)
            raise
        return fd

    def transfer(self, command: bytes, length: int, wait: float) -> bytes:
        fd = self._open()
        try:
            os.write(fd, command)
            if wait:
                time.sleep(wait)
            return os.read(fd, length)
        finally:
            os.close(fd)

    def write(self, data: bytes) -> None:
        fd = self._open()
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


class Room(threading.Thread):
    """Reads the sensor every poll_seconds: temperature in °F with offset
    added, humidity in %, pressure in hPa (BME280 only). address None means
    the chip's usual one. device stands in for the I2C bus in tests."""

    def __init__(
        self,
        bus: int = 1,
        address: int | None = None,
        offset: float = 0.0,
        poll_seconds: float = 30,
        metrics: Metrics | None = None,
        device: Device | None = None,
        chip: str = "sht3x",
    ) -> None:
        super().__init__(name="room", daemon=True)
        if chip not in CHIPS:
            raise ValueError(f"room.chip: expected one of {', '.join(CHIPS)}, got {chip!r}")
        self.chip = CHIPS[chip]()
        self.device = device or I2C(bus, self.chip.address if address is None else address)
        self.offset, self.poll_seconds, self.metrics = offset, poll_seconds, metrics
        self._stopping = threading.Event()
        self.temperature: float | None = None
        self.humidity: float | None = None
        self.pressure: float | None = None
        self.updated: float | None = None
        self.error = ""
        self._warned = False
        if metrics:
            metrics.set("panel_room_sensor_up", 0)

    def poll(self) -> bool:
        try:
            fahrenheit, humidity, pressure = self.chip.read(self.device)
        except (OSError, ValueError) as e:
            self.error = "NO SENSOR" if isinstance(e, OSError) else "BAD READING"
            if not self._warned:  # once, not every 30 s while it's unplugged
                log.warning("room sensor: %s", e)
                self._warned = True
            if self.metrics:
                self.metrics.set("panel_room_sensor_up", 0)
                self.metrics.inc("panel_room_reads_total", result="error")
            return False
        self.temperature, self.humidity, self.pressure = fahrenheit + self.offset, humidity, pressure
        self.updated, self.error, self._warned = time.time(), "", False
        if self.metrics:
            self.metrics.set("panel_room_sensor_up", 1)
            self.metrics.inc("panel_room_reads_total", result="ok")
            self.metrics.set("panel_room_temperature_fahrenheit", round(self.temperature, 2))
            self.metrics.set("panel_room_humidity_percent", round(humidity, 1))
            if pressure is not None:
                self.metrics.set("panel_room_pressure_hpa", round(pressure, 1))
        return True

    def fresh(self, max_age: float = 300) -> bool:
        return self.updated is not None and time.time() - self.updated < max_age

    def document(self) -> dict:
        """The latest reading for Home Assistant (/room.json): null and
        "up": false while the sensor is offline. pressure_hpa is null on an
        SHT3x."""
        up = self.fresh()
        return {
            "up": up,
            "temperature_f": round(self.temperature, 1) if up else None,
            "humidity": round(self.humidity, 1) if up else None,
            "pressure_hpa": round(self.pressure, 1) if up and self.pressure is not None else None,
        }

    def run(self) -> None:
        while not self._stopping.is_set():
            self.poll()
            self._stopping.wait(self.poll_seconds)

    def stop(self) -> None:
        self._stopping.set()
