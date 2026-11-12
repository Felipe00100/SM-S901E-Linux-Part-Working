#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hide the Plasma virtual keyboard when the user taps outside its area.

The compositor exposes the keyboard through org.kde.KWin /VirtualKeyboard.
We read the touchscreen evdev node (without grabbing it), and when a touch
ends above the keyboard region we set the `active` property to false.
KWin re-activates the keyboard normally when a text field is focused again.
"""
import glob
import os
import shutil
import struct
import subprocess
import time

EV_SYN = 0
EV_KEY = 1
EV_ABS = 3
SYN_REPORT = 0
BTN_TOUCH = 0x14A
ABS_Y = 0x01
ABS_MT_POSITION_Y = 0x35
ABS_MT_TRACKING_ID = 0x39
KEYBOARD_TOP_FRACTION = 0.55
DBUS_TIMEOUT = 2.0


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except OSError:
        return ""


def find_touchscreen():
    for event in sorted(glob.glob("/dev/input/event*")):
        name = read_text("/sys/class/input/%s/device/name" % os.path.basename(event))
        if "fts2ba61y" in name.lower() or name.lower().startswith("fts"):
            return event
    return None


def find_session_runtime():
    for runtime in sorted(glob.glob("/run/user/[0-9]*")):
        if os.path.exists(os.path.join(runtime, "bus")) and glob.glob(os.path.join(runtime, "wayland-[0-9]")):
            return runtime
    return None


def session_env(runtime):
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = runtime
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=%s/bus" % runtime
    sockets = sorted(glob.glob(os.path.join(runtime, "wayland-[0-9]")))
    if sockets:
        env["WAYLAND_DISPLAY"] = os.path.basename(sockets[0])
    return env


def kwin_property(env, prop):
    try:
        result = subprocess.run(
            ["qdbus6", "org.kde.KWin", "/VirtualKeyboard",
             "org.freedesktop.DBus.Properties.Get",
             "org.kde.kwin.VirtualKeyboard", prop],
            env=env, capture_output=True, text=True, timeout=DBUS_TIMEOUT)
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return False


def kwin_set_active(env, active):
    try:
        return subprocess.run(
            ["qdbus6", "org.kde.KWin", "/VirtualKeyboard",
             "org.freedesktop.DBus.Properties.Set",
             "org.kde.kwin.VirtualKeyboard", "active",
             "true" if active else "false"],
            env=env, capture_output=True, text=True, timeout=DBUS_TIMEOUT).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def kwin_hide(env):
    # Hide now, then leave the input method enabled so the next text field
    # can show the keyboard again.
    if kwin_set_active(env, False):
        time.sleep(0.15)
        kwin_set_active(env, True)
        print("tap outside keyboard -> hidden", flush=True)


def axis_max(fd, code):
    # struct input_absinfo { s32 value, minimum, maximum, fuzz, flat, resolution; }
    try:
        import fcntl
        buf = bytearray(24)
        fcntl.ioctl(fd, 0x80184540 + code, buf, True)
        _value, _minimum, maximum, _fuzz, _flat, _resolution = struct.unpack("6i", buf)
        return maximum if maximum > 0 else None
    except (OSError, ImportError, struct.error):
        return None


def main():
    if not shutil.which("qdbus6"):
        raise SystemExit("qdbus6 not found")
    event = find_touchscreen()
    if not event:
        raise SystemExit("touchscreen evdev not found")
    runtime = find_session_runtime()
    if not runtime:
        raise SystemExit("Plasma Wayland session not found")

    fd = os.open(event, os.O_RDONLY | os.O_NONBLOCK)
    max_y = axis_max(fd, ABS_MT_POSITION_Y) or axis_max(fd, ABS_Y) or 2340
    threshold = int(max_y * KEYBOARD_TOP_FRACTION)
    env = session_env(runtime)
    print("s22-kbd-autohide: %s max_y=%d threshold=%d runtime=%s" %
          (event, max_y, threshold, runtime), flush=True)

    last_y = None
    os.set_blocking(fd, True)
    while True:
        data = os.read(fd, 24)
        if len(data) < 24:
            time.sleep(0.1)
            continue
        _sec, _usec, etype, code, value = struct.unpack("llHHi", data)
        if etype == EV_ABS:
            if code in (ABS_Y, ABS_MT_POSITION_Y):
                last_y = value
            elif code == ABS_MT_TRACKING_ID and value < 0:
                if last_y is not None and kwin_property(env, "visible"):
                    print("touch release y=%d threshold=%d" % (last_y, threshold), flush=True)
                    if last_y < threshold:
                        kwin_hide(env)
                last_y = None
        elif etype == EV_KEY and code == BTN_TOUCH and value == 0:
            if last_y is not None and kwin_property(env, "visible"):
                print("touch release y=%d threshold=%d" % (last_y, threshold), flush=True)
                if last_y < threshold:
                    kwin_hide(env)
            last_y = None


if __name__ == "__main__":
    main()
