import signal
import traceback
import csv
import time
import threading
import math
import pigpio
import sys
import subprocess

class sensor(threading.Thread):
    """
   This class reads RGB values from a TCS3200 colour sensor.

   GND   Ground.
   VDD   Supply Voltage (2.7-5.5V)
   /OE   Output enable, active low. When OE is high OUT is disabled
         allowing multiple sensors to share the same OUT line.
   OUT   Output frequency square wave.
   S0/S1 Output frequency scale selection.
   S2/S3 Colour filter selection.

   OUT is a square wave whose frequency is proprtional to the
   intensity of the selected filter colour.

   S2/S3 selects between red, green, blue, and no filter.

   S0/S1 scales the frequency at 100%, 20%, 2% or off.

   To take a reading the colour filters are selected in turn for a
   fraction of a second and the frequency is read and converted to
   Hz.
   
   pi, 24, 22, 23, 4, 17, 18)
   """
    def __init__(self, pi, datfile, OUT=24, S2=22, S3=23, S0=4, S1=17, OE=18):
        """
      The gpios connected to the sensor OUT, S2, and S3 pins must
      be specified.  The S0, S1 (frequency) and OE (output enable)
      gpios are optional.
      """
        threading.Thread.__init__(self)
        self._pi = pi
        self.ref_data = {}
        with open(datfile) as csvfile:
            for row in csv.reader(csvfile):
                self.ref_data[row[0]] = [int(row[1]), int(row[2]), int(row[3])]
        print("loaded {} refdata rows from {}".format(len(self.ref_data), datfile))
    
        self._OUT = OUT
        self._S2 = S2
        self._S3 = S3
        
        But1 = 5
        pi.set_mode(But1,pigpio.INPUT)
        pi.set_pull_up_down(But1, pigpio.PUD_UP)

        self._mode_OUT = pi.get_mode(OUT)
        self._mode_S2 = pi.get_mode(S2)
        self._mode_S3 = pi.get_mode(S3)

        pi.write(OUT, 0) # Disable frequency output.
        pi.set_mode(S2, pigpio.OUTPUT)
        pi.set_mode(S3, pigpio.OUTPUT)

        self._S0 = S0
        self._S1 = S1
        self._OE = OE

        # configure the chime pin for output.
        pi.set_mode(21,pigpio.OUTPUT)

        if (S0 is not None) and (S1 is not None):
            
            self._mode_S0 = pi.get_mode(S0)
            self._mode_S1 = pi.get_mode(S1)
            pi.set_mode(S0, pigpio.OUTPUT)
            pi.set_mode(S1, pigpio.OUTPUT)

        if OE is not None:
            self._mode_OE = pi.get_mode(OE)
            pi.set_mode(OE, pigpio.OUTPUT)
            pi.write(OE, 0) # Enable device (active low).

        self.set_sample_size(20)

        self.set_update_interval(1.0) # One reading per second.

        self.set_frequency(2) # 1 2%, 2 20%

        self._set_filter(3) # Clear.

        self._rgb_black = [0]*3
        self._rgb_white = [10000]*3

        self.hertz=[0]*3 # Latest triplet.
        self._hertz=[0]*3 # Current values.

        self.tally=[1]*3 # Latest triplet.
        self._tally=[1]*3 # Current values.

        self._delay=[0.1]*3 # Tune delay to get _samples pulses.

        self._cycle = 0

        self._cb_OUT = pi.callback(OUT, pigpio.RISING_EDGE, self._cbf)
        self._cb_S2 = pi.callback(S2, pigpio.EITHER_EDGE, self._cbf)
        self._cb_S3 = pi.callback(S3, pigpio.EITHER_EDGE, self._cbf)

        self.daemon = True

        self.start()

    def cancel(self):
        """
      Cancel the sensor and release resources.
      """
        self._cb_S3.cancel()
        self._cb_S2.cancel()
        self._cb_OUT.cancel()

        self.set_frequency(0) # off

        self._set_filter(3) # Clear

        self._pi.set_mode(self._OUT, self._mode_OUT)
        self._pi.set_mode(self._S2, self._mode_S2)
        self._pi.set_mode(self._S3, self._mode_S3)

        if (self._S0 is not None) and (self._S1 is not None):
            self._pi.set_mode(self._S0, self._mode_S0)
            self._pi.set_mode(self._S1, self._mode_S1)

        if self._OE is not None:
            self._pi.write(self._OE, 1) # disable device
            self._pi.set_mode(self._OE, self._mode_OE)
            
        self._running = False
        
    def get_pH(self):
        s = self.get_hertz()
        
        if s is None or not s or all(v == 0 for v in s):
            return 0
        
        min_angle = 360
        pH_found = None
        for pH, v in self.ref_data.items():
            #print (f"PH{pH}, v{v}")
            dotproduct = v[0] * s[0] + v[1] *s[1] + v[2] * s[2]
            v_length = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
            s_length = math.sqrt(s[0]**2 + s[1]**2 + s[2]**2)
            cos_theta = dotproduct / (v_length * s_length)
#            print (f"dot({dotproduct}) vLen({v_length}) sLen({s_length})")
            
            theta = math.acos(cos_theta)
            
            if (theta < min_angle):
                min_angle = theta
                pH_found = pH
                
        return pH_found
        

    def get_rgb(self, top=255):
        """
      Get the latest RGB reading.

      The raw colour hertz readings are converted to RGB values
      as follows.

      RGB = 255 * (Fv - Fb) / (Fw - Fb)

      Where Fv is the sampled hertz, Fw is the calibrated
      white hertz, and Fb is the calibrated black hertz.

      By default the RGB values are constrained to be between
      0 and 255.  A different upper limit can be set by using
      the top parameter.
      """
        rgb = [0]*3
        for c in range(3):
            v = self.hertz[c] - self._rgb_black[c]
            s = self._rgb_white[c] - self._rgb_black[c]
            p = top * v / s
            if p < 0:            
                p = 0
            elif p > top:
                p = top
                rgb[c] = p
        return rgb[:]

    def get_hertz(self):
        """
      Get the latest hertz reading.
      """
        return self.hertz[:]

    def set_black_level(self, rgb):
        """
      Set the black level calibration.
      """
        for i in range(3):
            self._rgb_black[i] = rgb[i]

    def get_black_level(self):
        """
      Get the black level calibration.
      """
        return self._rgb_black[:]

    def set_white_level(self, rgb):
        """
      Set the white level calibration.
      """
        for i in range(3):
            self._rgb_white[i] = rgb[i]

    def get_white_level(self):
      """
      Get the white level calibration.
      """
      return self._rgb_white[:]

    def set_frequency(self, f):
        """
      Set the frequency scaling.

      f  S0  S1  Frequency scaling
      0  L   L   Off
      1  L   H   2%
      2  H   L   20%
      3  H   H   100%
      """
        if f == 0: # off
            S0 = 0; S1 = 0
        elif f == 1: # 2%
            S0 = 0; S1 = 1
        elif f == 2: # 20%
            S0 = 1; S1 = 0
        else: # 100%
            S0 = 1; S1 = 1

        if (self._S0 is not None) and (self._S1 is not None):
            self._frequency = f
            self._pi.write(self._S0, S0)
            self._pi.write(self._S1, S1)
        else:
            self._frequency = None

    def get_frequency(self):
        """
      Get the current frequency scaling.
      """
        return self._frequency

    def set_update_interval(self, t):
        """
      Set the interval between RGB updates.
      """
        if (t >= 0.1) and (t < 2.0):
            self._interval = t

    def get_update_interval(self):
        """
      Get the interval between RGB updates.
      """
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
        """
      Get the sample size.
      """
        return self._samples

    def pause(self):
        """
      Pause reading (until a call to resume).
      """
        self._read = False

    def resume(self):
        """
      Resume reading (after a call to pause).
      """
        self._read = True

    def long_chime(self):
        self._pi.write(21,1)
        time.sleep(2)
        self._pi.write(21,0)

    def short_chime(self):
        self._pi.write(21,1)
        time.sleep(0.5)
        self._pi.write(21,0)

    def _set_filter(self, f):
        """
      Set the colour to be sampled.

      f  S2  S3  Photodiode
      0  L   L   Red
      1  H   H   Green
      2  L   H   Blue
      3  H   L   Clear (no filter)
      """
        if f == 0: # Red
            S2 = 0; S3 = 0
        elif f == 1: # Green
            S2 = 1; S3 = 1
        elif f == 2: # Blue
            S2 = 0; S3 = 1
        else: # Clear
            S2 = 1; S3 = 0

        self._pi.write(self._S2, S2); self._pi.write(self._S3, S3)

    def _cbf(self, g, l, t):

        if g == self._OUT: # Frequency counter.
            if self._cycle == 0:
                self._start_tick = t
            else:
                self._last_tick = t
            self._cycle += 1

        else: # Must be transition between colour samples.
            if g == self._S2:
                if l == 0: # Clear -> Red.
                    self._cycle = 0
                    return
                else:      # Blue -> Green.
                    colour = 2
            else:
                if l == 0: # Green -> Clear.
                    colour = 1
                else:      # Red -> Blue.
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

                self._pi.set_mode(self._OUT, pigpio.INPUT) # Enable output gpio.

            # The order Red -> Blue -> Green -> Clear is needed by the
            # callback function so that each S2/S3 transition triggers
            # a state change.  The order was chosen so that a single
            # gpio changes state between each colour to be sampled.

                self._set_filter(0) # Red
                time.sleep(self._delay[0])

                self._set_filter(2) # Blue
                time.sleep(self._delay[2])

                self._set_filter(1) # Green
                time.sleep(self._delay[1])

                self._pi.write(self._OUT, 0) # Disable output gpio.

                self._set_filter(3) # Clear

                delay = next_time - time.time()

                if delay > 0.0:
                    time.sleep(delay)

            # Tune the next set of delays to get reasonable results
            # as quickly as possible.

                for c in range(3):

               # Calculate dly needed to get _samples pulses.

                    if self.hertz[c]:
                        dly = self._samples / float(self.hertz[c])
                    else: # Didn't find any edges, increase sample time.
                        dly = self._delay[c] + 0.1

               # Constrain dly to reasonable values.

                    if dly < 0.001:
                        dly = 0.001
                    elif dly > 0.5:
                        dly = 0.5

                    self._delay[c] = dly

            else:
                time.sleep(0.1)

    def wait_for_button(self):
        return pi.wait_for_edge(5, pigpio.FALLING_EDGE, 2.0)

class GracefulKiller:
    kill_now = False
    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        self.kill_now = True

if __name__ == "__main__":

    pi = pigpio.pi()
    # get data file
    filename =  sys.argv[1] if len(sys.argv) == 2 else "data.csv"
    
    s = sensor(pi, filename)
    s.long_chime()

    killer = GracefulKiller()
    
    try: 
        while not killer.kill_now:
            
            if s.wait_for_button():
                s.short_chime()
                
                ph = s.get_pH()
                print(ph)
                print(s.get_hertz())
                subprocess.run(["omxplayer", f"/home/pi/Projects/audio/{ph}.MP3"]) 
            
    except Exception as e:

        print("cancelling", e)
        traceback.print_exception(*sys.exc_info())
        s.cancel()
