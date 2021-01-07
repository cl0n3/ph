import math
import signal
import subprocess
import csv
import sys
import threading
import time
import traceback
import pigpio

HOME = '.'


class Chime:
    PIN = 21
    ON = 1
    OFF = 0

    def __init__(self, pi):
        self._pi = pi
        self._mode_PIN = pi.get_mode(self.PIN)
        pi.set_mode(self.PIN, pigpio.OUTPUT)

    def __del__(self):
        self._pi.set_mode(self.PIN, self._mode_PIN)

    def long_chime(self):
        self._on(self.ON)

    def short_chime(self):
        self._on()

    def double_short_chime(self):
        self._on()
        time.sleep(0.4)
        self._on()

    def _on(self, duration=0.2):
        self._pi.write(self.PIN, self.ON)
        time.sleep(duration)
        self._pi.write(self.PIN, self.OFF)


class Audio:

    def __init__(self):
        self.audioDir = HOME + '/audio'

    def play(self, filename):
        subprocess.run(["omxplayer", f"{self.audioDir}/{filename}.MP3"])


class Buttons(threading.Thread):
    PIN_N = 5
    PIN_W = 6

    def __init__(self, _pi, _sensor, _chime, _audio):
        threading.Thread.__init__(self)
        self.pi = _pi
        self.sensor = _sensor
        self.chime = _chime
        self.audio = _audio

        self.narrow_read = False
        self.wide_read = False

        self._mode_pin_n = _pi.get_mode(self.PIN_N)
        self._mode_pin_w = _pi.get_mode(self.PIN_W)

        _pi.set_mode(self.PIN_N, pigpio.INPUT)
        _pi.set_pull_up_down(self.PIN_N, pigpio.PUD_UP)
        _pi.set_noise_filter(self.PIN_N, 300000, 100000)
        self._cb_pin_n = _pi.callback(self.PIN_N, pigpio.RISING_EDGE, self.on_button_pressed)

        _pi.set_mode(self.PIN_W, pigpio.INPUT)
        _pi.set_pull_up_down(self.PIN_W, pigpio.PUD_UP)
        _pi.set_noise_filter(self.PIN_W, 300000, 100000)
        self._cb_pin_w = _pi.callback(self.PIN_W, pigpio.RISING_EDGE, self.on_button_pressed)

    def __del__(self):
        self._cb_pin_n.cancel()
        self._cb_pin_w.cancel()

        self.pi.set_mode(self.PIN_N, self._mode_pin_n)
        self.pi.set_mode(self.PIN_W, self._mode_pin_w)

    def on_button_pressed(self, gpio, level, tick):
        _ticks = tick
        _level = level
        if gpio == self.PIN_N:
            self.narrow_read = True
        elif gpio == self.PIN_W:
            self.wide_read = True

    def request_reading(self):
        if self.narrow_read:
            self.chime.short_chime()
            self.audio.play(self.sensor.narrow_read())
            self.narrow_read = False

        elif self.wide_read:
            self.chime.double_short_chime()
            self.audio.play(self.sensor.wide_read())
            self.wide_read = False

    def run(self):
        while True:
            self.request_reading()
            time.sleep(5)


class Sensor(threading.Thread):
    """
        This class reads RGB values from a TCS3200 colour sensor.

        GND   Ground.
        VDD   Supply Voltage (2.7-5.5V)
        /OE   Output enable, active low. When OE is high OUT is disabled
             allowing multiple sensors to share the same OUT line.
        OUT   Output frequency square wave.
        S0/S1 Output frequency scale selection.
        S2/S3 Colour filter selection.

        OUT is a square wave whose frequency is proportional to the
        intensity of the selected filter colour.

        S2/S3 selects between red, green, blue, and no filter.

        S0/S1 scales the frequency at 100%, 20%, 2% or off.

        To take a reading the colour filters are selected in turn for a
        fraction of a second and the frequency is read and converted to
        Hz.
    """

    ACTIVE = 0
    INACTIVE = 1

    PIN_OUT = 24
    PIN_S3 = 23
    PIN_S2 = 22
    PIN_S1 = 17
    PIN_S0 = 4
    PIN_OE = 18

    _frequency = None
    reading = False
    _read = False
    _interval = 1.0  # One reading per second.

    hertz = [0] * 3  # Latest triplet.
    _hertz = [0] * 3  # Current values.
    tally = [1] * 3  # Latest triplet.
    _tally = [1] * 3  # Current values.
    _delay = [0.1] * 3  # Tune delay to get _samples pulses.
    _cycle = 0
    _samples = 0

    def __init__(self, pi):
        threading.Thread.__init__(self)

        self._pi = pi

        self._mode_OUT = pi.get_mode(self.PIN_OUT)
        self._mode_S0 = pi.get_mode(self.PIN_S0)
        self._mode_S1 = pi.get_mode(self.PIN_S1)
        self._mode_S2 = pi.get_mode(self.PIN_S2)
        self._mode_S3 = pi.get_mode(self.PIN_S3)
        self._mode_OE = pi.get_mode(self.PIN_OE)

        pi.set_mode(self.PIN_S0, pigpio.OUTPUT)
        pi.set_mode(self.PIN_S1, pigpio.OUTPUT)
        pi.set_mode(self.PIN_S2, pigpio.OUTPUT)
        pi.set_mode(self.PIN_S3, pigpio.OUTPUT)
        pi.set_mode(self.PIN_OE, pigpio.OUTPUT)

        self._cb_OUT = pi.callback(self.PIN_OUT, pigpio.RISING_EDGE, self._cbf)
        self._cb_S2 = pi.callback(self.PIN_S2, pigpio.EITHER_EDGE, self._cbf)
        self._cb_S3 = pi.callback(self.PIN_S3, pigpio.EITHER_EDGE, self._cbf)

        self.set_sample_size(20)
        self.set_update_interval(1.0)
        self.set_frequency(2)  # 1 2%, 2 20%
        self._set_filter(3)  # Clear

        pi.write(self.PIN_OUT, 0)  # Disable frequency output.
        pi.write(self.PIN_OE, self.ACTIVE)  # Enable device (active low).

        self.daemon = True

    def __del__(self):
        self._cb_S3.cancel()
        self._cb_S2.cancel()
        self._cb_OUT.cancel()

        self.set_frequency(0)  # off
        self._set_filter(3)  # Clear

        self._pi.set_mode(self.PIN_OUT, self._mode_OUT)
        self._pi.set_mode(self.PIN_S0, self._mode_S0)
        self._pi.set_mode(self.PIN_S1, self._mode_S1)
        self._pi.set_mode(self.PIN_S2, self._mode_S2)
        self._pi.set_mode(self.PIN_S3, self._mode_S3)
        self._pi.set_mode(self.PIN_OE, self._mode_OE)

        self._pi.write(self.PIN_OE, self.INACTIVE)  # disable device

    def narrow_read(self):
        print("narrow read button press, reading={}".format(self.reading))
        return self.get_ph(HOME + "/narrow_data.csv")

    def wide_read(self):
        print("wide read button press, reading={}".format(self.reading))
        return self.get_ph(HOME + "/wide_data.csv")

    def get_ph(self, file):
        self.resume()
        ref_data = {}
        with open(file) as csvFile:
            for row in csv.reader(csvFile):
                ref_data[row[0]] = [int(row[1]), int(row[2]), int(row[3])]
        print(f"loaded {len(ref_data)} ref data rows from {file}")

        sample = self.get_hertz()

        if sample is None or not sample or all(v == 0 for v in sample):
            return 0

        min_angle = 360
        ph_found = None
        for pH, v in ref_data.items():
            dotproduct = v[0] * sample[0] + v[1] * sample[1] + v[2] * sample[2]
            v_length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
            s_length = math.sqrt(sample[0] ** 2 + sample[1] ** 2 + sample[2] ** 2)
            cos_theta = dotproduct / (v_length * s_length)
            theta = math.acos(cos_theta)

            if theta < min_angle:
                min_angle = theta
                ph_found = pH

        print(ph_found)
        print(sample)
        self.pause()
        return ph_found

    def get_hertz(self):
        return self.hertz[:]

    def set_frequency(self, f):
        """
            Set the frequency scaling.

            f  S0  S1  Frequency scaling
            0  L   L   Off
            1  L   H   2%
            2  H   L   20%
            3  H   H   100%
        """
        if f == 0:  # off
            s0 = 0
            s1 = 0
        elif f == 1:  # 2%
            s0 = 0
            s1 = 1
        elif f == 2:  # 20%
            s0 = 1
            s1 = 0
        else:  # 100%
            s0 = 1
            s1 = 1

        self._frequency = f
        self._pi.write(self.PIN_S0, s0)
        self._pi.write(self.PIN_S1, s1)

    def get_frequency(self):
        return self._frequency

    def set_update_interval(self, t):
        if (t >= 0.1) and (t < 2.0):
            self._interval = t

    def get_update_interval(self):
        return self._interval

    def set_sample_size(self, samples):
        """
            Set the sample size (number of frequency cycles to accumulate).
        """
        if samples < 10:
            samples = 10
        elif samples > 100:
            samples = 100

        self._samples = samples

    def get_sample_size(self):
        return self._samples

    def pause(self):
        self._read = False

    def resume(self):
        self._read = True

    def _set_filter(self, f):
        """
            Set the colour to be sampled.

            f  S2  S3  Photo-diode
            0  L   L   Red
            1  H   H   Green
            2  L   H   Blue
            3  H   L   Clear (no filter)
        """
        self.filter = f
        if f == 0:  # Red
            s2 = 0
            s3 = 0
        elif f == 1:  # Green
            s2 = 1
            s3 = 1
        elif f == 2:  # Blue
            s2 = 0
            s3 = 1
        else:  # Clear
            s2 = 1
            s3 = 0

        self._pi.write(self.PIN_S2, s2)
        self._pi.write(self.PIN_S3, s3)

    def get_filter(self):
        return self.filter

    def _cbf(self, gpio, level, tick):
        """
            @param gpio 0-31 The GPIO which has changed state
            @param level 0-2     0 = change to low (a falling edge)
                                 1 = change to high (a rising edge)
                                 2 = no level change (a watchdog timeout)
            @param tick 32-bit The number of microseconds since boot
                WARNING: this wraps around from 4294967295 to 0 roughly every 72 minutes
        """
        if gpio == self.PIN_OUT:  # Frequency counter.
            if self._cycle == 0:
                self._start_tick = tick
            else:
                self._last_tick = tick
            self._cycle += 1

        else:  # Must be transition between colour samples.
            if gpio == self.PIN_S2:
                if level == 0:  # Clear -> Red.
                    self._cycle = 0
                    return
                else:  # Blue -> Green.
                    colour = 2
            else:
                if level == 0:  # Green -> Clear.
                    colour = 1
                else:  # Red -> Blue.
                    colour = 0

            if self._cycle > 1:
                self._cycle -= 1
                td = pigpio.tickDiff(self._start_tick, self._last_tick)
                self._hertz[colour] = (1000000 * self._cycle) / td
                self._tally[colour] = self._cycle
            else:
                self._hertz[colour] = 0
                self._tally[colour] = 0

            self._cycle = 0

            # Have we a new set of RGB?
            if colour == 1:
                for i in range(3):
                    self.hertz[i] = self._hertz[i]
                    self.tally[i] = self._tally[i]

    def run(self):
        self._read = True
        while True:
            if self._read:

                next_time = time.time() + self._interval

                self._pi.set_mode(self.PIN_OUT, pigpio.INPUT)  # Enable output gpio.

                # The order Red -> Blue -> Green -> Clear is needed by the
                # callback function so that each S2/S3 transition triggers
                # a state change.  The order was chosen so that a single
                # gpio changes state between each colour to be sampled.

                self._set_filter(0)  # Red
                time.sleep(self._delay[0])

                self._set_filter(2)  # Blue
                time.sleep(self._delay[2])

                self._set_filter(1)  # Green
                time.sleep(self._delay[1])

                self._pi.write(self.PIN_OUT, 0)  # Disable output gpio.

                self._set_filter(3)  # Clear

                delay = next_time - time.time()

                if delay > 0.0:
                    time.sleep(delay)

                # Tune the next set of delays to get reasonable results
                # as quickly as possible.

                for c in range(3):

                    # Calculate dly needed to get _samples pulses.

                    if self.hertz[c]:
                        dly = self._samples / float(self.hertz[c])
                    else:  # Didn't find any edges, increase sample time.
                        dly = self._delay[c] + 0.1

                    # Constrain dly to reasonable values.

                    if dly < 0.001:
                        dly = 0.001
                    elif dly > 0.5:
                        dly = 0.5

                    self._delay[c] = dly

            else:
                time.sleep(0.1)


class GracefulKiller:
    kill_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        _signum = signum
        _frame = frame
        self.kill_now = True


if __name__ == "__main__":
    rpi = pigpio.pi()

    sensor = Sensor(rpi)
    chime = Chime(rpi)
    buttons = Buttons(rpi, sensor, chime)

    sensor.start()
    buttons.start()

    chime.long_chime()

    killer = GracefulKiller()

    try:
        while not killer.kill_now:
            time.sleep(1)

    except Exception as e:
        traceback.print_exception(*sys.exc_info())
