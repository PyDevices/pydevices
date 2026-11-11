# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""Give the computer a network link to the board over USB (CDC-NCM).

Choose it from code, like any other USB function::

    import usb.device
    from usb.device.net import NCMInterface

    net = NCMInterface()
    usb.device.get().init(net, builtin_driver=True)

The computer sees a USB Ethernet adapter and gets an address from the board's
DHCP server, on a link-local network of its own. ``net.nic`` is the board's end,
a ``network.USBD_NCM``: ``net.nic.ipconfig("addr4")`` gives its address, and
sockets, WebREPL and web servers work over it as over Wi-Fi.

The firmware moves the frames: this class only describes the function, so the
link costs nothing until code chooses it. Windows 10 and later, Linux and macOS
have NCM drivers built in.
"""

from micropython import const
import network

from .core import Interface

_CLASS_CDC = const(0x02)
_CLASS_CDC_DATA = const(0x0A)
_SUBCLASS_NCM = const(0x0D)
_PROTOCOL_NCM_DATA = const(0x01)

_DESC_INTERFACE = const(0x04)
_DESC_CS_INTERFACE = const(0x24)
_FUNC_HEADER = const(0x00)
_FUNC_UNION = const(0x06)
_FUNC_ETHERNET = const(0x0F)
_FUNC_NCM = const(0x1A)

_EP_IN_FLAG = const(1 << 7)
_MAX_SEGMENT = const(1514)


class NCMInterface(Interface):
    """A USB Ethernet function, CDC-NCM.

    Args:
        interface_str: a name for the adapter, shown by some computers.
        bulk_len: the data endpoints' packet size at full speed. A high-speed
            board moves to 512 by itself.

    Attributes:
        nic: the board's end of the link, a ``network.USBD_NCM``.
    """

    def __init__(self, *, interface_str="Board network", bulk_len=64):
        super().__init__()
        self.interface_str = interface_str
        self.bulk_len = bulk_len
        self.nic = network.USBD_NCM()

    def desc_cfg(self, desc, itf_num, ep_num, strs):
        strs.append(self.interface_str)
        istr = len(strs) - 1
        # The computer's MAC, which the board's end of the link is built from.
        strs.append("".join("%02X" % b for b in self.nic.config("mac")))
        imac = len(strs) - 1
        data_itf = itf_num + 1

        desc.interface_assoc(itf_num, 2, _CLASS_CDC, _SUBCLASS_NCM, 0, istr)
        desc.interface(itf_num, 1, _CLASS_CDC, _SUBCLASS_NCM, 0, istr)
        desc.pack("<BBBH", 5, _DESC_CS_INTERFACE, _FUNC_HEADER, 0x0110)
        desc.pack("<BBBBB", 5, _DESC_CS_INTERFACE, _FUNC_UNION, itf_num, data_itf)
        desc.pack("<BBBBIHHB", 13, _DESC_CS_INTERFACE, _FUNC_ETHERNET, imac, 0, _MAX_SEGMENT, 0, 0)
        desc.pack("<BBBHB", 6, _DESC_CS_INTERFACE, _FUNC_NCM, 0x0100, 0)
        desc.endpoint(ep_num | _EP_IN_FLAG, "interrupt", 64, 50)
        # The data interface twice: alternate setting 0 has no endpoints and 1
        # has both, which is how the computer switches the link on and off.
        # Descriptor.interface() has no alternate setting, so these are packed.
        desc.pack("<BBBBBBBBB", 9, _DESC_INTERFACE, data_itf, 0, 0, _CLASS_CDC_DATA, 0, _PROTOCOL_NCM_DATA, 0)
        desc.pack("<BBBBBBBBB", 9, _DESC_INTERFACE, data_itf, 1, 2, _CLASS_CDC_DATA, 0, _PROTOCOL_NCM_DATA, 0)
        desc.endpoint(ep_num + 1, "bulk", self.bulk_len, 0)
        desc.endpoint((ep_num + 1) | _EP_IN_FLAG, "bulk", self.bulk_len, 0)

    def num_itfs(self):
        return 2

    def num_eps(self):
        return 2  # the notification IN, and the data OUT and IN on the next number
