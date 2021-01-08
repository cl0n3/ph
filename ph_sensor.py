import csv
import glob
import logging
import math
import os
import signal
import subprocess
import threading
import time
import pigpio


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
        self._on(0.5)

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
    audioDir = os.getcwd() + '/audio'

    def play(self, ph):
        logging.debug(f'finding file {self.audioDir}/{ph}.mp3')
        for filename in glob.glob(self.audioDir + '/*'):
            if filename.lower() == f'{self.audioDir}/{ph}.mp3'.lower():
                subprocess.run(["omxplayer", filename])
                return

        logging.error(f'no audio file for {ph}')


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

        self.daemon = True
        self.name = 'Buttons'

    def __del__(self):
        self._cb_pin_n.cancel()
        self._cb_pin_w.cancel()

        self.pi.set_mode(self.PIN_N, self._mode_pin_n)
        self.pi.set_mode(self.PIN_W, self._mode_pin_w)

    def on_button_pressed(self, gpio, level, tick):
        """
        Invoked on the GPIO threads.
        @param gpio: pin
        @param level: pin level, likely 1.
        @param tick:
        @return: None
        """
        _ticks = tick
        _level = level
        if gpio == self.PIN_N:
            self.narrow_read = True
        elif gpio == self.PIN_W:
            self.wide_read = True

    def request_reading(self):
        """
        Invoked on the Buttons thread, which monitors the flags set on the pigpio thread.
        @return: None
        """
        if self.narrow_read:
            self.narrow_read = False
            self.chime.short_chime()
            self.sensor.request_read('narrow', self.report_reading)
        elif self.wide_read:
            self.wide_read = False
            self.chime.double_short_chime()
            self.sensor.request_read('wide', self.report_reading)

    def report_reading(self, ph):
        """
        Invoked from the Sensor thread to report it's result.
        @param ph: the PH reading found from the sensor.
        @return: None
        """
        self.audio.play(ph)

    def run(self):
        while True:
            self.request_reading()
            time.sleep(0.5)


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

    _reads = []
    _frequency = None
    _filter = 3
    _interval = 1.0  # One reading per second.

    hertz = [0] * 3  # Latest triplet.
    _hertz = [0] * 3  # Current values.
    tally = [1] * 3  # Latest triplet.
    _tally = [1] * 3  # Current values.
    _delay = [0.1] * 3  # Tune delay to get _samples pulses.
    _cycle = 0
    _samples = 20
    _last_tick = 0
    _start_tick = 0

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

        self._cb_OUT = pi.callback(self.PIN_OUT, pigpio.RISING_EDGE, self.gpio_callback)
        self._cb_S2 = pi.callback(self.PIN_S2, pigpio.EITHER_EDGE, self.gpio_callback)
        self._cb_S3 = pi.callback(self.PIN_S3, pigpio.EITHER_EDGE, self.gpio_callback)

        self.set_frequency(2)
        self.set_filter(3)

        pi.write(self.PIN_OUT, 0)  # Disable frequency output.
        pi.write(self.PIN_OE, self.ACTIVE)  # Enable device (active low).

        self.daemon = True
        self.name = 'Sensor'

    def __del__(self):
        self._cb_S3.cancel()
        self._cb_S2.cancel()
        self._cb_OUT.cancel()

        self.set_frequency(0)  # off
        self.set_filter(3)  # Clear

        self._pi.set_mode(self.PIN_OUT, self._mode_OUT)
        self._pi.set_mode(self.PIN_S0, self._mode_S0)
        self._pi.set_mode(self.PIN_S1, self._mode_S1)
        self._pi.set_mode(self.PIN_S2, self._mode_S2)
        self._pi.set_mode(self.PIN_S3, self._mode_S3)
        self._pi.set_mode(self.PIN_OE, self._mode_OE)

        self._pi.write(self.PIN_OE, self.INACTIVE)  # disable device

    def request_read(self, read_type, callback):
        req = {
            'file': f'./{read_type}_data.csv',
            'callback': callback
        }
        self._reads.append(req)
        logging.debug('received read request req(%s)', str(req))

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

    def set_filter(self, f):
        """
            Set the colour to be sampled.

            f  S2  S3  Photo-diode
            0  L   L   Red
            1  H   H   Green
            2  L   H   Blue
            3  H   L   Clear (no filter)
        """
        self._filter = f
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
        return self._filter

    def gpio_callback(self, gpio, level, tick):
        logger = logging.Logger('gpio')
        logger.setLevel(logging.INFO)
        """
            Invoked on the GPIO thread.

            @param gpio 0-31 The GPIO which has changed state
            @param level 0-2     0 = change to low (a falling edge)
                                 1 = change to high (a rising edge)
                                 2 = no level change (a watchdog timeout)
            @param tick 32-bit The number of microseconds since boot
                WARNING: this wraps around from 4294967295 to 0 roughly every 72 minutes
        """
        logger.debug('gpio(%s) level(%s) tick(%s)', gpio, level, tick)
        if gpio == self.PIN_OUT:  # Frequency counter.
            if self._cycle == 0:
                self._start_tick = tick
            else:
                self._last_tick = tick
            self._cycle += 1
            logger.debug('updating frequency counter cycle(%s) start_tick(%s) last_tick(%s)',
                         self._cycle, self._start_tick, self._last_tick)

        else:  # Must be transition between colour samples.
            logger.debug('colour transition')
            if gpio == self.PIN_S2:
                if level == 0:  # Clear -> Red.
                    self._cycle = 0
                    logger.debug('clear->red')
                    return
                else:  # Blue -> Green.
                    colour = 2
                    logger.debug('blue->green')
            else:
                if level == 0:  # Green -> Clear.
                    colour = 1
                    logger.debug('green->clear')
                else:  # Red -> Blue.
                    colour = 0
                    logger.debug('red->blue')

            if self._cycle > 1:
                self._cycle -= 1
                td = pigpio.tickDiff(self._start_tick, self._last_tick)
                self._hertz[colour] = (1000000 * self._cycle) / td
                self._tally[colour] = self._cycle
                logger.debug('updated hertz cycle(%s) td(%s) hertz(%s)(%s) tally(%s)(%s)',
                             self._cycle, td, colour, self._hertz[colour], colour, self._tally[colour])

            else:
                self._hertz[colour] = 0
                self._tally[colour] = 0
                logger.debug('reset hertz and tally')

            self._cycle = 0

            if colour == 1:
                for i in range(3):
                    self.hertz[i] = self._hertz[i]
                    self.tally[i] = self._tally[i]

    def cycle_sensor(self):
        req = self._reads.pop()
        logging.debug(f'servicing request({str(req)}), remaining requests {len(self._reads)}')

        next_time = time.time() + self._interval
        logging.debug('next_time(%s)', next_time)
        self._pi.set_mode(self.PIN_OUT, pigpio.INPUT)  # Enable output gpio.

        # The order Red -> Blue -> Green -> Clear is needed by the
        # callback function so that each S2/S3 transition triggers
        # a state change.  The order was chosen so that a single
        # gpio changes state between each colour to be sampled.

        self.set_filter(0)  # Red
        logging.debug('set_filter(red) sleeping(%s)', self._delay[0])
        time.sleep(self._delay[0])

        self.set_filter(2)  # Blue
        logging.debug('set_filter(blue) sleeping(%s)', self._delay[2])
        time.sleep(self._delay[2])

        self.set_filter(1)  # Green
        logging.debug('set_filter(green) sleeping(%s)', self._delay[1])
        time.sleep(self._delay[1])

        self._pi.write(self.PIN_OUT, 0)  # Disable output gpio.

        self.set_filter(3)  # Clear
        delay = next_time - time.time()
        logging.debug('set_filter(clear) sleeping(%s)', delay)

        if delay > 0.0:
            time.sleep(delay)

        # Tune the next set of delays to get reasonable results
        # as quickly as possible.

        for c in range(3):

            # Calculate dly needed to get _samples pulses.

            if self.hertz[c]:
                dly = self._samples / float(self.hertz[c])
                logging.debug('updating delays hertz(%s)(%s) samples(%s) delay(%s)',
                              c, self.hertz[c], self._samples, dly)
            else:  # Didn't find any edges, increase sample time.
                dly = self._delay[c] + 0.1
                logging.debug('no edges delay(%s)', dly)

            # Constrain dly to reasonable values.

            if dly < 0.001:
                dly = 0.001
                logging.debug('capping delay(%s)', dly)
            elif dly > 0.5:
                dly = 0.5
                logging.debug('capping delay(%s)', dly)

            self._delay[c] = dly

        file = req['file']

        ref_data = {}
        with open(file) as csvFile:
            for row in csv.reader(csvFile):
                ref_data[row[0]] = [int(row[1]), int(row[2]), int(row[3])]
        logging.debug("loaded {} ref data rows from {}".format(len(ref_data), file))

        sample = self.get_hertz()

        if sample is None or not sample or all(v == 0 for v in sample):
            logging.error("no colour samples to analyse")
            return None

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

        logging.info('read PH(%s) using datafile(%s) sample HZ(%s)', str(ph_found), file, str(sample))

        callback = req['callback']
        if callback:
            callback(ph_found)

    def run(self):
        while True:
            if len(self._reads) != 0:
                self.cycle_sensor()
            else:
                time.sleep(1)


class GracefulKiller:
    kill_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        _signum = signum
        _frame = frame
        self.kill_now = True
        logging.info(f'exit signum({signum} frame({frame})')


if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s [%(levelname)s] %(name)s [%(thread)d %(threadName)s]: %(message)s',
                        filename='../logs/ph_sensor.log', level=logging.DEBUG)
    logging.info(f'starting cwd({os.getcwd()})')

    rpi = pigpio.pi()
    sensor = Sensor(rpi)
    chime = Chime(rpi)
    audio = Audio()
    buttons = Buttons(rpi, sensor, chime, audio)

    sensor.start()
    buttons.start()

    chime.long_chime()

    killer = GracefulKiller()

    while not killer.kill_now:
        time.sleep(1)
