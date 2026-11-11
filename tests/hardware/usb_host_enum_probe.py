# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
# List what is on the host port, with the interface classes.
import time
import usb.core

usb.core.start()
time.sleep_ms(3000)
for dev in usb.core.find(find_all=True):
    cfg = dev.configuration_descriptor()
    print(dev, "bcd %04x" % dev.bcdDevice)
    i = cfg[0]
    while i + 2 <= len(cfg) and cfg[i] >= 2:
        if cfg[i + 1] == 4:
            print("  interface", cfg[i + 2], "alt", cfg[i + 3], "class %02x/%02x/%02x" % (cfg[i + 5], cfg[i + 6], cfg[i + 7]))
        i += cfg[i]
print("done")
