from __future__ import annotations

import logging

import pytest

from brick_panel import room as R
from brick_panel.metrics import Metrics


def word(value):
    data = value.to_bytes(2, "big")
    return data + bytes([R.crc8(data)])


def reading(celsius, humidity):
    t = round((celsius + 45) * 65535 / 175)
    rh = round(humidity * 65535 / 100)
    return word(t) + word(rh)


class FakeSHT:
    def __init__(self, raw=None, fail=None):
        self.raw, self.fail, self.commands = raw, fail, []

    def transfer(self, command, length, wait):
        self.commands.append((command, length))
        if self.fail:
            raise self.fail
        return self.raw


def test_crc_matches_the_datasheet_example():
    assert R.crc8(bytes([0xBE, 0xEF])) == 0x92


def test_decode():
    f, rh = R.decode(reading(25.0, 50.0))
    assert f == pytest.approx(77.0, abs=0.01)
    assert rh == pytest.approx(50.0, abs=0.01)


def test_bad_crc_and_length_are_refused():
    raw = bytearray(reading(25.0, 50.0))
    raw[1] ^= 0x01
    with pytest.raises(ValueError):
        R.decode(bytes(raw))
    with pytest.raises(ValueError):
        R.decode(b"\x00\x01")


def test_poll_reads_with_offset_and_metrics():
    m = Metrics()
    dev = FakeSHT(reading(22.0, 45.0))
    room = R.Room(offset=-2.5, metrics=m, device=dev)
    assert room.poll()
    assert dev.commands == [(R.MEASURE, 6)]
    assert room.temperature == pytest.approx(71.6 - 2.5, abs=0.01)
    assert room.humidity == pytest.approx(45.0, abs=0.01)
    assert room.fresh()
    assert m.get("panel_room_sensor_up") == 1
    assert m.get("panel_room_temperature_fahrenheit") == pytest.approx(69.1, abs=0.01)


def test_unplugged_warns_once_and_keeps_going(caplog):
    m = Metrics()
    room = R.Room(metrics=m, device=FakeSHT(fail=OSError(121, "Remote I/O error")))
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert not room.poll()
    assert room.error == "NO SENSOR" and not room.fresh()
    assert len([r for r in caplog.records if "room sensor" in r.message]) == 1
    assert m.get("panel_room_sensor_up") == 0
    assert m.get("panel_room_reads_total", result="error") == 3


def test_a_bad_reading_keeps_the_last_good_one():
    dev = FakeSHT(reading(22.0, 45.0))
    room = R.Room(device=dev)
    room.poll()
    dev.raw = b"\xff" * 6
    assert not room.poll()
    assert room.error == "BAD READING"
    assert room.temperature == pytest.approx(71.6, abs=0.01)


def test_document_for_home_assistant():
    room = R.Room(device=FakeSHT(reading(22.0, 45.0)))
    assert room.document() == {"up": False, "temperature_f": None, "humidity": None, "pressure_hpa": None}
    room.poll()
    assert room.document() == {"up": True, "temperature_f": 71.6, "humidity": 45.0, "pressure_hpa": None}
    room.updated -= 600
    assert room.document()["up"] is False


# The BME280 on brick1982's Multi-Sensor Stick, read 2026-11-23: its
# calibration and one forced measurement.
STICK_TP = bytes.fromhex("eb6f4f6832003891cfd6d00b64137d00f9ffac260ad8bd10004b")
STICK_H = bytes.fromhex("730100122a031e")
STICK_DATA = bytes.fromhex("59ad00848f00662d")


class FakeBME:
    """A BME280's registers: a read is a one-byte register pointer, then bytes."""

    def __init__(self, chip_id=0x60, data=STICK_DATA, fail=None):
        self.regs = {R.BME_ID: bytes([chip_id]), R.BME_CALIB_TP: STICK_TP, R.BME_CALIB_H: STICK_H, R.BME_DATA: data}
        self.fail, self.reads, self.writes = fail, [], []

    def transfer(self, command, length, wait):
        if self.fail:
            raise self.fail
        self.reads.append(command[0])
        return self.regs[command[0]][:length]

    def write(self, data):
        if self.fail:
            raise self.fail
        self.writes.append(bytes(data))


def bmp280_datasheet_calibration():
    """The BMP280 datasheet's worked example (section 3.12): the BME280 has
    the same temperature and pressure compensation."""
    tp = b"".join(
        v.to_bytes(2, "little", signed=i not in (0, 3))  # T1 and P1 are unsigned
        for i, v in enumerate([27504, 26435, -1000, 36477, -10685, 3024, 2855, 140, -7, 15500, -14600, 6000])
    )
    return R.BME280Calibration(tp + b"\0\0", bytes(7))


def data(adc_p, adc_t, adc_h=0):
    return bytes(
        [adc_p >> 12, (adc_p >> 4) & 0xFF, (adc_p & 0xF) << 4, adc_t >> 12, (adc_t >> 4) & 0xFF, (adc_t & 0xF) << 4]
    ) + adc_h.to_bytes(2, "big")


def test_bme280_matches_the_datasheet_example():
    celsius, _, hpa = R.bme280_compensate(bmp280_datasheet_calibration(), data(415148, 519888))
    assert celsius == pytest.approx(25.08, abs=0.005)
    assert hpa * 100 == pytest.approx(100653.27, abs=0.01)


def test_bme280_reads_the_stick():
    celsius, humidity, hpa = R.bme280_compensate(R.BME280Calibration(STICK_TP, STICK_H), STICK_DATA)
    assert celsius == pytest.approx(26.92, abs=0.01)
    assert humidity == pytest.approx(39.9, abs=0.1)
    assert hpa == pytest.approx(1014.0, abs=0.1)


def test_bme280_calibration_signs():
    cal = R.BME280Calibration(STICK_TP, STICK_H)
    assert (cal.t1, cal.t2, cal.t3) == (28651, 26703, 50)
    assert (cal.p1, cal.p2, cal.p9) == (37176, -10545, 4285)
    assert (cal.h1, cal.h2, cal.h3, cal.h4, cal.h5, cal.h6) == (75, 371, 0, 298, 50, 30)


def test_bme280_skipped_measurement_is_refused():
    with pytest.raises(ValueError):
        R.bme280_compensate(R.BME280Calibration(STICK_TP, STICK_H), data(0x80000, 0x80000))


def test_room_on_a_bme280():
    m = Metrics()
    dev = FakeBME()
    room = R.Room(chip="bme280", offset=-3.0, metrics=m, device=dev)
    assert room.poll()
    assert dev.writes == [bytes([R.BME_CTRL_HUM, 0x01]), bytes([R.BME_CTRL_MEAS, 0x25])]
    assert room.temperature == pytest.approx(80.46 - 3.0, abs=0.02)
    assert room.pressure == pytest.approx(1014.0, abs=0.1)
    assert m.get("panel_room_sensor_up") == 1
    assert m.get("panel_room_pressure_hpa") == pytest.approx(1014.0, abs=0.1)
    assert room.document()["pressure_hpa"] == pytest.approx(1014.0, abs=0.1)
    # The calibration is read once, not every poll.
    room.poll()
    assert dev.reads.count(R.BME_CALIB_TP) == 1


def test_bme280_rereads_its_calibration_after_a_failure():
    dev = FakeBME()
    room = R.Room(chip="bme280", device=dev)
    assert room.poll()
    dev.fail = OSError(121, "Remote I/O error")
    assert not room.poll() and room.error == "NO SENSOR"
    dev.fail = None
    assert room.poll()
    assert dev.reads.count(R.BME_CALIB_TP) == 2


def test_something_else_at_the_address_is_a_bad_reading():
    room = R.Room(chip="bme280", device=FakeBME(chip_id=0x58))  # a BMP280
    assert not room.poll()
    assert room.error == "BAD READING"


def test_chip_picks_its_usual_address():
    assert R.Room(chip="bme280").device.address == 0x76
    assert R.Room().device.address == 0x44
    assert R.Room(chip="bme280", address=0x77).device.address == 0x77
    with pytest.raises(ValueError):
        R.Room(chip="dht22")
