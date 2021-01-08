import unittest
import time

import pigpio

from ph_sensor import Sensor, Chime, Buttons


class FakePi:

    def __init__(self):
        self.pins = {}
        self.init_pin(Sensor.PIN_S0)
        self.init_pin(Sensor.PIN_S1)
        self.init_pin(Sensor.PIN_S2)
        self.init_pin(Sensor.PIN_S3)
        self.init_pin(Sensor.PIN_OE)
        self.init_pin(Sensor.PIN_OUT)
        self.init_pin(Chime.PIN)
        self.init_pin(Buttons.PIN_W)
        self.init_pin(Buttons.PIN_N)

    def init_pin(self, pin):
        self.pins[pin] = {
            'callback': None,
            'upDown': None,
            'mode': 0,
            'noise_filter': {
                'stable': 0,
                'active': 0
            },
            'hilo': []
        }

    @staticmethod
    def now():
        return int(round(time.time() * 1000))

    def set_mode(self, pin, mode):
        self.pins[pin]['mode'] = mode

    def set_pull_up_down(self, pin, up_down):
        self.pins[pin]['upDown'] = up_down

    def callback(self, pin, edge, cbf):
        class Wrapper:
            def __init__(self):
                self.cbf = cbf
                self.pin = pin
                self.edge = edge
                self.cancelled = False

            def cancel(self):
                self.cancelled = True

            def is_cancelled(self):
                return self.cancelled

            def invoke(self, level, ticks):
                self.cbf(self.pin, level, ticks)

        w = Wrapper()
        self.pins[pin]['callback'] = w
        return w

    def get_mode(self, pin):
        return self.pins[pin]['mode']

    def write(self, pin, hilo):
        self.pins[pin]['hilo'].append([hilo, self.now()])

    def set_noise_filter(self, pin, stable, active):
        f = self.pins[pin]['noise_filter']
        f['stable'] = stable
        f['active'] = active

    def had_pulse(self, pin, hilo, duration_ms):
        signals = self.pins[pin]['hilo']
        for i in range(1, len(signals)):
            start = signals[i - 1]
            end = signals[i]

            delta = end[1] - start[1]
            if start[0] == hilo and end[0] != hilo and abs(delta - duration_ms) < 10:
                return True

        return False

    def had_pulses(self, pin, pulses):
        signals = self.pins[pin]['hilo']

        for i in range(1, len(signals)):
            start = signals[i - 1]
            end = signals[i]
            delta = end[1] - start[1]

            hilo = pulses[0][0]
            duration_ms = pulses[0][1]

            if start[0] == hilo and end[0] != hilo and abs(delta - duration_ms) < 10:
                pulses.pop(0)

            if len(pulses) == 0:
                return True

        return False

    def had_write(self, pin, hilo):
        signals = self.pins[pin]['hilo']
        for s in signals:
            if s[0] == hilo:
                return True

        return False

    def assert_mode(self, pin, mode):
        return self.get_mode(pin) == mode

    def assert_pull_up_down(self, pin, up_down):
        return self.pins[pin]['upDown'] == up_down

    def assert_noise_filter(self, pin, stable, active):
        f = self.pins[pin]['noise_filter']
        if f['stable'] != stable:
            return False

        if f['active'] != active:
            return False

        return True

    def assert_callback(self, pin, edge):
        c = self.pins[pin]['callback']
        if c is None:
            return False

        return c.edge == edge

    def assert_callback_cancelled(self, pin):
        c = self.pins[pin]['callback']
        return c.is_cancelled()

class FakeAudio:

    plays = []

    def play(self, ph):
        self.plays.append(ph)

    def has_played(self, ph):
        return ph in self.plays


class SensorTest(unittest.TestCase):

    def setUp(self) -> None:
        self.pi = FakePi()
        self.sensor = Sensor(self.pi)

    def testSetFrequency(self) -> None:
        self.assertFrequency(0, 0, 0)
        self.assertFrequency(1, 0, 1)
        self.assertFrequency(2, 1, 0)
        self.assertFrequency(3, 1, 1)

        # cap at 100%
        self.assertFrequency(100, 1, 1)

    def assertFrequency(self, freq, s0, s1):
        self.sensor.set_frequency(freq)
        self.assertTrue(self.pi.had_write(Sensor.PIN_S0, s0))
        self.assertTrue(self.pi.had_write(Sensor.PIN_S1, s1))
        self.assertEqual(self.sensor.get_frequency(), freq)

    def testSetFilter(self) -> None:
        self.assertFilter(0, 0, 0)
        self.assertFilter(1, 1, 1)
        self.assertFilter(2, 0, 1)
        self.assertFilter(3, 1, 0)

    def assertFilter(self, fil, s2, s3) -> None:
        self.sensor._set_filter(fil)
        self.assertTrue(self.pi.had_write(Sensor.PIN_S2, s2))
        self.assertTrue(self.pi.had_write(Sensor.PIN_S3, s3))
        self.assertEqual(self.sensor.get_filter(), fil)


class ChimeTest(unittest.TestCase):

    def setUp(self) -> None:
        self.pi = FakePi()
        self.chime = Chime(self.pi)

    def testLongChime(self):
        self.chime.long_chime()
        self.assertTrue(self.pi.had_pulse(Chime.PIN, Chime.ON, 1000))

    def testShortChime(self):
        self.chime.short_chime()
        self.assertTrue(self.pi.had_pulse(Chime.PIN, Chime.ON, 200))

    def testDoubleShortChime(self):
        self.chime.double_short_chime()
        self.assertTrue(self.pi.had_pulses(Chime.PIN, [
            [Chime.ON, 200],
            [Chime.ON, 200]
        ]))


class ButtonsTest(unittest.TestCase):

    def setUp(self) -> None:
        self.pi = FakePi()
        self.buttons = Buttons(self.pi, None, None, None)

    def testInit(self):
        self.assertTrue(self.pi.assert_mode(Buttons.PIN_W, pigpio.INPUT))
        self.assertTrue(self.pi.assert_mode(Buttons.PIN_N, pigpio.INPUT))
        self.assertTrue(self.pi.assert_pull_up_down(Buttons.PIN_W, pigpio.PUD_UP))
        self.assertTrue(self.pi.assert_pull_up_down(Buttons.PIN_N, pigpio.PUD_UP))
        self.assertTrue(self.pi.assert_noise_filter(Buttons.PIN_W, 300000, 100000))
        self.assertTrue(self.pi.assert_noise_filter(Buttons.PIN_N, 300000, 100000))
        self.assertTrue(self.pi.assert_callback(Buttons.PIN_W, pigpio.RISING_EDGE))

    def testDel(self):
        self.buttons.__del__()

        self.assertTrue(self.pi.assert_callback_cancelled(Buttons.PIN_W))
        self.assertTrue(self.pi.assert_callback_cancelled(Buttons.PIN_N))


class IntegrationTest(unittest.TestCase):

    def setUp(self):
        self.pi = FakePi()
        self.chime = Chime(self.pi)
        self.sensor = Sensor(self.pi)
        self.audio = FakeAudio()

        self.buttons = Buttons(self.pi, self.sensor, self.chime, self.audio)

    def testInit(self):
        pass

    def testSensorReadOnButton(self):
        self.buttons.on_button_pressed(Buttons.PIN_W, 0, 1)
        self.buttons.request_reading()

