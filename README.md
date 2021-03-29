# zigate-flasher
Python tool to flash your Zigate (Jennic JN5168)

## Requirements
- Python 3.5 or higher
- pyserial
- pyusb
- RPi.GPIO

## Usage
```
usage: zigate-flasher.py [-h] -p PORT [-w WRITE] [-s SAVE] [-e] [--pdm-only]

optional arguments:
  -h, --help            show this help message and exit
  -p PORT, --serialport PORT
                        Serial port, e.g. /dev/ttyUSB0
  -w WRITE, --write WRITE
                        Firmware bin to flash onto the chip
  -s SAVE, --save SAVE  File to save the currently loaded firmware to
  -e, --erase           Erase EEPROM
  --pdm-only            Erase PDM only, use it with --erase

```
