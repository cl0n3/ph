# PH Sensor
The PH Sensor can read litmus paper samples and match the colours against a trained dataset. It allows for two data sets to cover different litmus paper scales

##Architecture
The system uses these components: 
1. Raspberry PI with GPIO
2. A TCS3200 Colour sensor
3. Two push buttons
4. A speaker
5. A python driver
6. pigpiod

### Threading Model
The driver contains four threads
1. The main thread which servers only to keep the process alive and capture operating system signals such as SIGTERM
2. A Sensor thread, which drives the TCS3200 control lines to toggle the colour sampling
3. A Button thread, which handles the toggling of the two switches. It provides a basic debounce mechanism.
4. The pigpio library spawn a thread to handle callbacks from the TCS3200. Both the buttons and the sensors signals (S2/S3/OUT) receive callbacks on this thread.

### Switch debouncing
The button callbacks have a [noise filter](http://abyz.me.uk/rpi/pigpio/python.html#set_noise_filter) which provides a first attempt to ignore the noise switch signal. 
The second layer is the two-threaded scheme. The callback thread will toggle the read flag when the GPIO detects the button rising edge, the button thread loops waiting for the flag and will notify the sensor thread to take a reading. The button thread will sleep to ignore subsequent toggles from the buttons. 

## Production environment
The library is installed under the standard *pi* user under a directory */home/pi/ph*.

All the required python libraries are installed in the global python instance located at */usr/bin/python3.7*

The *pigpiod* service must be running to allow communication with the GPIO.

Systemd manages pigpiod: 

```console
/lib/systemd/system/pigpiod.service
```

The unit file is installed by default on this system.

### Stop, Start, Restart with Systemd

The service runs using the native Systemd subsystem. One can control the PH Sensor service with these commands: 

```console
sudo systemctl reload-daemon

sudo systemctl restart ph_sensor

sudo systemctl stop ph_sensor

sudo systemctl status ph_sensor
```

The Systemd unit file is symlinked to the */home/pi/ph/ph_sensor.service* file. 

The symlink is stored at */lib/systemd/system/*

There are some utility scripts
 
 ```console
/home/pi/bin/phstatus

/home/pi/bin/phstop

/home/pi/bin/phstart
```
which allow for convenient status/stop/start. 

### Running in place 

Stop the installed service with: 
```console
sudo systemctl stop ph_sensor
```

Navigate to: 
```console
/home/pi/ph
```

Run:
```console
phython3.7 ./ph_sensor.py
```

Kill the process with *Control-C* as needed


### Logs

The logs will appear in */home/pi/logs/ph_sensor.log* in all cases. So running with systemd or inplace will append to this log file. The file is a plain-text file.

The Systemd logs are found at : 

```console
/var/log/syslog
```

Information about stopping and starting the sensor will appear there, but the application logs will direct to the local logs dir.

## Git

The code lives at https://github.com/cl0n3/ph.git, including this document.

```console
git commit -a -m "<comment>" -- to save changes

git push -- to load them to the remote server 

git pull -- to get remote changes from the server.
```


