# dbus-psi-genset

A Venus OS D-Bus driver that presents an **Offgridtec PSI** inverter as a
generator (`com.victronenergy.genset`). It is intended for a PSI wired to the
**AC-in of a MultiPlus-II**, where it acts as a 230 VAC generator that you
start and stop **manually**.

The driver talks **Modbus RTU** to the PSI (over a USB-RS485 adapter) and:

- publishes the AC output and 12 V DC input measurements, temperatures and
  status under a genset service so the PSI appears in the GX **Device list →
  Generator**;
- exposes a writable `/Start` path (with `/RemoteStartModeEnabled = 1`) that
  toggles the PSI's remote-control coil `0x000F`, so you can switch it on/off
  from the GX generator screen or any D-Bus / Modbus-TCP client;
- optionally manages the PSI's DC cutoff thresholds (LVD/LVDR/HVDR/HVD).

GX **auto** start/stop (SOC-based `dbus_generator`) is intentionally *not*
enabled — control is manual.

## Dependencies

This driver reuses the libraries vendored in the sibling **dbus-serialbattery**
project (`ext/minimalmodbus.py` and `ext/velib_python/`). On Venus OS install
dbus-serialbattery at `/data/apps/dbus-serialbattery` first. For development the
two folders just need to sit side by side in this repo.

## Bench check first

Confirm wiring, baudrate and scaling against the real inverter before touching
D-Bus:

```
python3 tools/psi_dump.py /dev/ttyUSB0            # try 9600 baud, slave 1
python3 tools/psi_dump.py /dev/ttyUSB0 19200 1    # other baud / address
python3 tools/psi_dump.py /dev/ttyUSB0 --start    # turn the inverter on
python3 tools/psi_dump.py /dev/ttyUSB0 --stop     # turn it off
```

Run the offline decode tests with:

```
python3 -m pytest test/
```

## Install on Venus OS

```
cp config.sample.ini config.ini   # then edit baudrate / address / thresholds
./install.sh ttyUSB0              # bind the service to your serial port
```

Logs: `tail -f /var/log/dbus-psi-genset/current | tai64nlocal`

## D-Bus paths published

| Path | Meaning |
|---|---|
| `/Ac/L1/Voltage`, `/Ac/L1/Current`, `/Ac/L1/Power`, `/Ac/Power` | AC output |
| `/Ac/Frequency`, `/NrOfPhases` | fixed 50 Hz, single phase |
| `/Dc/0/Voltage`, `/Dc/0/Current`, `/Dc/0/Power`, `/StarterVoltage` | 12 V DC input |
| `/StatusCode` | 0 = standby, 8 = running, 10 = error |
| `/Error/0/Id` | decoded fault / over-temperature text |
| `/Engine/WindingTemperature`, `/Engine/CoolantTemperature` | inverter / MOSFET temp |
| `/Start` (writable) | 1 = start, 0 = stop → coil `0x000F` |
| `/RemoteStartModeEnabled` | 1 (enables manual `/Start`) |
| `/Settings/{LVD,LVDR,HVDR,HVD}` | DC cutoffs (only when `MANAGE_THRESHOLDS = true`) |
