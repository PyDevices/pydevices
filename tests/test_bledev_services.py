# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The SIG services in ``bledev`` (battery, device information, ...) over the fake radio.

Each test serves one service on a fake board and reads it from a fake central,
the way a phone would: by UUID, through discovery.
"""

from pathlib import Path
import asyncio
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import bledev  # noqa: E402
from bledev import hid  # noqa: E402
from bledev.battery import Battery  # noqa: E402
from bledev.cyclingpower import CyclingPower  # noqa: E402
from bledev.cyclingpower import encode_measurement as power_bytes  # noqa: E402
from bledev.cyclingspeed import CyclingSpeedCadence  # noqa: E402
from bledev.cyclingspeed import encode_measurement as csc_bytes  # noqa: E402
from bledev.deviceinfo import DeviceInformation  # noqa: E402
from bledev.environmental import EnvironmentalSensing  # noqa: E402
from bledev.heartrate import CHEST, HeartRate  # noqa: E402
from bledev.heartrate import encode_measurement as hr_bytes  # noqa: E402
from bledev.runningspeed import RunningSpeedCadence  # noqa: E402
from bledev.runningspeed import encode_measurement as rsc_bytes  # noqa: E402
from bledev.fake import Air, FakeBLE  # noqa: E402


async def serve(*services, uuids=()):
    """A board serving ``services`` and a central connected to it."""
    air = Air()
    board = FakeBLE(air=air, mtu=247)
    central = FakeBLE(air=air, mtu=247)
    board.register_services(*services)
    advertising = asyncio.create_task(board.advertise(name="svc", services=list(uuids)))
    device = await central.find(name="svc", timeout_ms=2000)
    connection = await device.connect()
    await advertising
    return board, central, connection


async def characteristic(connection, service_uuid, char_uuid):
    service = await connection.service(service_uuid)
    return await service.characteristic(char_uuid)


def run(coroutine):
    return asyncio.run(asyncio.wait_for(coroutine, 10))


class BatteryTests(unittest.TestCase):
    def test_level_is_read_and_notified(self):
        async def go():
            battery = Battery(level=87)
            _, _, connection = await serve(battery.service, uuids=[battery.SERVICE])
            level = await characteristic(connection, 0x180F, 0x2A19)
            self.assertEqual(await level.read(), b"\x57")
            await level.subscribe()
            battery.set_level(41)
            self.assertEqual(await level.notified(), b"\x29")
            self.assertEqual(await level.read(), b"\x29")
            self.assertEqual(battery.level, 41)

        run(go())

    def test_level_range(self):
        self.assertRaises(ValueError, Battery, 101)
        self.assertRaises(ValueError, Battery(5).set_level, -1)


class DeviceInformationTests(unittest.TestCase):
    def test_fields_are_served_by_their_sig_uuids(self):
        async def go():
            info = DeviceInformation(
                manufacturer="PyDevices", model="rack-1", serial="0042", hardware="B", firmware="0.3.0",
                software="9", system_id=bytes(range(8)), pnp_id=(1, 0xFFFF, 0x0123, 0x0100),
            )
            _, _, connection = await serve(info.service, uuids=[info.SERVICE])
            want = {
                0x2A29: b"PyDevices", 0x2A24: b"rack-1", 0x2A25: b"0042", 0x2A27: b"B",
                0x2A26: b"0.3.0", 0x2A28: b"9", 0x2A23: bytes(range(8)),
                0x2A50: struct.pack("<BHHH", 1, 0xFFFF, 0x0123, 0x0100),
            }
            for uuid, value in want.items():
                c = await characteristic(connection, 0x180A, uuid)
                self.assertEqual(await c.read(), value, hex(uuid))

        run(go())

    def test_only_given_fields_are_served(self):
        info = DeviceInformation(model="x")
        self.assertEqual(list(info.characteristics), ["model"])
        self.assertEqual(len(info.service.characteristics), 1)

    def test_system_id_length(self):
        self.assertRaises(ValueError, DeviceInformation, system_id=b"123")


class HeartRateTests(unittest.TestCase):
    def test_flags_and_fields(self):
        self.assertEqual(hr_bytes(72), b"\x00\x48")
        self.assertEqual(hr_bytes(300), b"\x01\x2c\x01")
        # contact supported and detected (0x06), energy (0x08), RR (0x10)
        self.assertEqual(hr_bytes(72, rr_ms=(1000,), energy_kj=1000, contact=True), b"\x1e\x48\xe8\x03\x00\x04")
        # contact supported, not detected: only bit 2
        self.assertEqual(hr_bytes(72, contact=False), b"\x04\x48")
        # 830 ms is 849.92 units of 1/1024 s
        self.assertEqual(hr_bytes(60, rr_ms=(830,)), b"\x10\x3c\x52\x03")

    def test_limits(self):
        self.assertRaises(ValueError, hr_bytes, 70000)
        self.assertEqual(len(hr_bytes(60, rr_ms=(900,) * 9)), 20)
        self.assertRaises(ValueError, hr_bytes, 60, (900,) * 10)

    def test_notified_and_location_read(self):
        async def go():
            monitor = HeartRate(location=CHEST)
            _, _, connection = await serve(monitor.service, uuids=[monitor.SERVICE])
            service = await connection.service(0x180D)
            self.assertEqual(await (await service.characteristic(0x2A38)).read(), b"\x01")
            measurement = await service.characteristic(0x2A37)
            await measurement.subscribe()
            monitor.update(88, rr_ms=(700,))
            self.assertEqual(await measurement.notified(), hr_bytes(88, rr_ms=(700,)))

        run(go())

    def test_energy_reset(self):
        async def go():
            monitor = HeartRate(energy_expended=True)
            _, _, connection = await serve(monitor.service)
            control = await characteristic(connection, 0x180D, 0x2A39)
            waiting = asyncio.create_task(monitor.reset_requested())
            await control.write(b"\x02")  # not the reset opcode
            await asyncio.sleep(0.05)
            self.assertFalse(waiting.done())
            await control.write(b"\x01")
            await asyncio.wait_for(waiting, 2)

        run(go())
        self.assertRaises(ValueError, lambda: asyncio.run(HeartRate().reset_requested()))


class CyclingTests(unittest.TestCase):
    def test_speed_cadence_bytes(self):
        self.assertEqual(csc_bytes(100, 2.0, 50, 1.0), b"\x03\x64\x00\x00\x00\x00\x08\x32\x00\x00\x04")
        self.assertEqual(csc_bytes(100, 2.0), b"\x01\x64\x00\x00\x00\x00\x08")
        self.assertEqual(csc_bytes(crank_revolutions=50, crank_time_s=1.0), b"\x02\x32\x00\x00\x04")
        # the event time wraps at 64 s, the crank count at 2**16
        self.assertEqual(csc_bytes(crank_revolutions=65537, crank_time_s=65.0), b"\x02\x01\x00\x00\x04")

    def test_speed_cadence_refuses_what_it_was_not_made_for(self):
        sensor = CyclingSpeedCadence(wheel=True, crank=False)
        self.assertRaises(ValueError, sensor.update, crank_revolutions=1, crank_time_s=1)
        self.assertRaises(ValueError, sensor.update, wheel_revolutions=1)
        self.assertRaises(ValueError, sensor.update)
        self.assertRaises(ValueError, CyclingSpeedCadence, wheel=False, crank=False)

    def test_speed_cadence_feature(self):
        async def go():
            sensor = CyclingSpeedCadence(wheel=True, crank=True, location=5, locations=(5, 6))
            _, _, connection = await serve(sensor.service)
            feature = await characteristic(connection, 0x1816, 0x2A5C)
            self.assertEqual(await feature.read(), b"\x07\x00")
            self.assertEqual(await (await characteristic(connection, 0x1816, 0x2A5D)).read(), b"\x05")

        run(go())

    def test_control_point_answers_by_indication(self):
        async def go():
            seen = []
            sensor = CyclingSpeedCadence(locations=(5, 6), on_set_cumulative=seen.append)
            _, _, connection = await serve(sensor.service)
            control = await characteristic(connection, 0x1816, 0x2A55)
            task = asyncio.create_task(sensor.run())
            await control.subscribe(notify=False, indicate=True)
            await control.write(b"\x04")
            self.assertEqual(await control.indicated(), b"\x10\x04\x01\x05\x06")
            await control.write(b"\x01\x10\x27\x00\x00")
            self.assertEqual(await control.indicated(), b"\x10\x01\x01")
            self.assertEqual(seen, [10000])
            await control.write(b"\x01\x01")  # short parameter
            self.assertEqual(await control.indicated(), b"\x10\x01\x03")
            await control.write(b"\x02")  # calibration: not supported
            self.assertEqual(await control.indicated(), b"\x10\x02\x02")
            task.cancel()

        run(go())

    def test_power_bytes(self):
        self.assertEqual(power_bytes(200), b"\x00\x00\xc8\x00")
        self.assertEqual(power_bytes(-5), b"\x00\x00\xfb\xff")
        self.assertEqual(power_bytes(200, pedal_balance=50), b"\x01\x00\xc8\x00\x64")
        self.assertEqual(power_bytes(200, accumulated_torque=10), b"\x04\x00\xc8\x00\x40\x01")
        self.assertEqual(power_bytes(200, accumulated_torque=10, crank_torque=True), b"\x0c\x00\xc8\x00\x40\x01")
        self.assertEqual(
            power_bytes(200, wheel_revolutions=3, wheel_time_s=1.0), b"\x10\x00\xc8\x00\x03\x00\x00\x00\x00\x08"
        )
        self.assertEqual(power_bytes(200, crank_revolutions=3, crank_time_s=1.0), b"\x20\x00\xc8\x00\x03\x00\x00\x04")
        self.assertEqual(power_bytes(200, energy_kj=7), b"\x00\x08\xc8\x00\x07\x00")
        # all of it, in the specification's field order
        self.assertEqual(
            power_bytes(200, 50, 10, False, 3, 1.0, 4, 1.0, 7),
            struct.pack("<H", 0x0835) + b"\xc8\x00\x64\x40\x01" + b"\x03\x00\x00\x00\x00\x08" + b"\x04\x00\x00\x04" + b"\x07\x00",
        )

    def test_power_service(self):
        async def go():
            moved = []
            meter = CyclingPower(pedal_balance=True, crank=True, location=6, locations=(5, 6))
            _, _, connection = await serve(meter.service)
            service = await connection.service(0x1818)
            self.assertEqual(await (await service.characteristic(0x2A65)).read(), struct.pack("<I", 0x809))
            measurement = await service.characteristic(0x2A63)
            await measurement.subscribe()
            meter.update(210, pedal_balance=48, crank_revolutions=9, crank_time_s=3.0)
            self.assertEqual(await measurement.notified(), power_bytes(210, 48, None, False, None, None, 9, 3.0))
            self.assertRaises(ValueError, meter.update, 210, energy_kj=1)
            control = await service.characteristic(0x2A66)
            task = asyncio.create_task(meter.run())
            await control.subscribe(notify=False, indicate=True)
            await control.write(b"\x03")
            self.assertEqual(await control.indicated(), b"\x20\x03\x01\x05\x06")
            await control.write(b"\x02\x05")
            self.assertEqual(await control.indicated(), b"\x20\x02\x01")
            self.assertEqual(await (await service.characteristic(0x2A5D)).read(), b"\x05")
            await control.write(b"\x02\x09")
            self.assertEqual(await control.indicated(), b"\x20\x02\x03")
            task.cancel()

        run(go())


class RunningTests(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(rsc_bytes(2.5, 90), b"\x00\x80\x02\x5a")
        self.assertEqual(rsc_bytes(2.5, 90, stride_m=1.0), b"\x01\x80\x02\x5a\x64\x00")
        self.assertEqual(rsc_bytes(2.5, 90, distance_m=12.5), b"\x02\x80\x02\x5a\x7d\x00\x00\x00")
        self.assertEqual(rsc_bytes(2.5, 90, running=True), b"\x04\x80\x02\x5a")
        self.assertEqual(rsc_bytes(2.5, 90, running=False), b"\x00\x80\x02\x5a")
        self.assertRaises(ValueError, rsc_bytes, 2.5, 300)

    def test_service(self):
        async def go():
            seen = []
            pod = RunningSpeedCadence(stride_length=True, total_distance=True, running_status=True,
                                      location=2, locations=(1, 2), on_set_cumulative=seen.append)
            _, _, connection = await serve(pod.service)
            service = await connection.service(0x1814)
            self.assertEqual(await (await service.characteristic(0x2A54)).read(), b"\x17\x00")
            measurement = await service.characteristic(0x2A53)
            await measurement.subscribe()
            pod.update(3.0, 170, stride_m=1.1, distance_m=500, running=True)
            self.assertEqual(await measurement.notified(), rsc_bytes(3.0, 170, 1.1, 500, True))
            control = await service.characteristic(0x2A55)
            task = asyncio.create_task(pod.run())
            await control.subscribe(notify=False, indicate=True)
            await control.write(b"\x01\x64\x00\x00\x00")  # 100 tenths of a metre
            self.assertEqual(await control.indicated(), b"\x10\x01\x01")
            self.assertEqual(seen, [10.0])
            task.cancel()

        run(go())

    def test_refuses_what_it_was_not_made_for(self):
        pod = RunningSpeedCadence()
        self.assertRaises(ValueError, pod.update, 3.0, 170, stride_m=1.1)
        self.assertRaises(ValueError, pod.update, 3.0, 170, running=True)


class EnvironmentalTests(unittest.TestCase):
    def test_encodings(self):
        from bledev.environmental import encode_humidity, encode_pressure, encode_temperature, encode_uv_index

        self.assertEqual(encode_temperature(21.5), struct.pack("<h", 2150))
        self.assertEqual(encode_temperature(-5.25), struct.pack("<h", -525))
        self.assertEqual(encode_humidity(40.2), struct.pack("<H", 4020))
        self.assertEqual(encode_pressure(101325.0), struct.pack("<I", 1013250))
        self.assertEqual(encode_uv_index(7), b"\x07")
        self.assertRaises(ValueError, encode_temperature, 400)
        self.assertRaises(ValueError, encode_humidity, 101)

    def test_service(self):
        async def go():
            weather = EnvironmentalSensing(temperature=True, humidity=True, pressure=True)
            _, _, connection = await serve(weather.service)
            service = await connection.service(0x181A)
            temperature = await service.characteristic(0x2A6E)
            self.assertEqual(await temperature.read(), b"\x00\x80")  # not known yet
            await temperature.subscribe()
            weather.update(temperature=19.0, humidity=55.5, pressure=100500.0)
            self.assertEqual(await temperature.notified(), struct.pack("<h", 1900))
            self.assertEqual(await (await service.characteristic(0x2A6F)).read(), struct.pack("<H", 5550))
            self.assertEqual(await (await service.characteristic(0x2A6D)).read(), struct.pack("<I", 1005000))
            self.assertRaises(ValueError, weather.update, uv_index=3)
            self.assertRaises(ValueError, EnvironmentalSensing)

        run(go())


class HidReusesThem(unittest.TestCase):
    def test_peripheral_serves_the_standalone_services(self):
        async def go():
            air = Air()
            board = FakeBLE(air=air, mtu=247)
            central = FakeBLE(air=air, mtu=247)
            per = hid.Peripheral(board, battery=64, manufacturer="Acme")
            serving = asyncio.create_task(per.serve())
            device = await central.find(name=per.name, timeout_ms=2000)
            connection = await device.connect()
            await serving
            level = await characteristic(connection, 0x180F, 0x2A19)
            self.assertEqual(await level.read(), b"\x40")
            self.assertEqual(await (await characteristic(connection, 0x180A, 0x2A29)).read(), b"Acme")
            pnp = await (await characteristic(connection, 0x180A, 0x2A50)).read()
            self.assertEqual(pnp[:5], struct.pack("<BHH", 1, 0xFFFF, struct.unpack("<H", pnp[3:5])[0]))

        run(go())


if __name__ == "__main__":
    unittest.main()
