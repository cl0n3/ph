## Stop, Start, Restart with Systemd

The service runs using the native Systemd tool. 

```console
sudo systemctl reload-daemon

sudo systemctl restart ph_sensor

sudo systemctl stop ph_sensor

sudo systemctl status ph_sensor
```

The Systemd unit file is symlinked to the /home/pi/ph/ph_sensor.service file. 

The symlink is stored at /lib/systemd/system/

There is a script in /home/pi/bin/restartph which allows for convenient restarting. 

## Running in place 

Stop the installed service with: 

sudo systemctl stop ph_sensor

Navigate to: 

/home/pi/ph


Run
```console
phython3.7 ./ph_sensor.py
```


kill the process with Control-C as needed


## Logs

The logs will appear in /home/pi/logs/ph_sensor.loy in all cases. So running with systemd or inplace will append to this log file.

The systemd logs are found at : 


/var/log/syslog

Information about stoping and starting the sensor will appear there, but the application logs will direct to the local logs dir.

## Git

The code lives at https://github.com/cl0n3/ph.git

run git commit -a -m "<comment>" to save changes

run git push to load them to the remote server 

run git pull to get remote changes from the server.


