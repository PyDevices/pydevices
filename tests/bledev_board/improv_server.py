# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""The Improv gate, board side: serve Improv as ``bledev-improv`` until provisioned.

It first takes the board off Wi-Fi, so a join it reports afterwards is one the
Improv client caused. It never prints the credentials it receives, only the
state changes and the address it got. Logs to /improv_server.log.
"""
import asyncio

import network

import bledev.improv as improv
import bledev.mpble

LOG = "/improv_server.log"


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


async def main():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        wlan.disconnect()
    except OSError:
        pass
    await asyncio.sleep_ms(500)
    log("wifi before: connected", wlan.isconnected())
    ble = bledev.mpble.get()
    server = improv.Server(ble, "bledev-improv")
    state_names = {1: "authorization required", 2: "authorized", 3: "provisioning", 4: "provisioned"}
    set_state = server._set_state

    async def logged_state(state):
        log("state", state_names.get(state, state))
        await set_state(state)

    set_error = server._set_error

    async def logged_error(error):
        log("error", error)
        await set_error(error)

    server._set_state = logged_state
    server._set_error = logged_error
    log("serving Improv as bledev-improv, capabilities", server.capabilities)
    url = await server.serve()
    log("provisioned: redirect", url, "wifi connected", wlan.isconnected(), "ip", wlan.ifconfig()[0])


open(LOG, "w").close()
asyncio.run(main())
