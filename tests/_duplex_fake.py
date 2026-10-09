"""A stand-in for ``_audioif`` on firmware that records while it plays.

The real one is C: the output and the capture reader are two holders of one
I2S channel pair, and the RX half's interrupt copies every DMA block into a
ring that ``rx_read()`` empties. What ``audiodev`` depends on is the contract,
and that is what this models: who holds the channel, at what rate, whether a
join with a different wire is refused, and a ring the test fills by hand.
"""


class FakeDuplexDriver:
    def __init__(self):
        self.holds = 0           # 1 the output, 2 the capture reader
        self.live = None         # (port, bclk, ws, dout, din, rate)
        self.ring = bytearray()  # what the interrupt would have copied
        self.dropped = 0
        self.captured = 0
        self.calls = []          # every rx_open/rx_close, in order
        self.opened_with = None
        self.reads = 0

    # --- what a board asks ------------------------------------------------

    def i2s_state(self):
        if self.live is None:
            return None
        return (self.live[5], 2, True, self.holds)

    # --- the capture reader -----------------------------------------------

    def rx_open(self, port, bclk, ws, dout, din, rate, *, mclk=-1,
                mclk_fs=256, ring=20000, take=2):
        if self.holds & 2:
            raise ValueError("capture already open")
        want = (port, bclk, ws, dout, din, rate)
        if self.live is not None and self.live[:5] != want[:5]:
            raise RuntimeError("Peripheral in use")
        if self.live is not None and self.live[5] != rate:
            raise ValueError("the I2S channel is clocked at %d Hz and this "
                             "asks for %d Hz" % (self.live[5], rate))
        self.live = want
        self.holds |= 2
        self.opened_with = dict(port=port, bclk=bclk, ws=ws, dout=dout,
                                din=din, rate=rate, mclk=mclk,
                                mclk_fs=mclk_fs, ring=ring, take=take)
        self.calls.append("rx_open")
        return ring

    def rx_read(self, buf):
        if not self.holds & 2:
            raise OSError(19)
        self.reads += 1
        n = min(len(buf), len(self.ring))
        n -= n % 2
        buf[:n] = self.ring[:n]
        del self.ring[:n]
        return n

    def rx_close(self):
        self.calls.append("rx_close")
        if not self.holds & 2:
            return
        self.holds &= ~2
        if not self.holds:
            self.live = None

    def rx_stats(self):
        return (self.captured, self.dropped, len(self.ring))

    # --- the output, as audiobusio.I2SOut(data_in=) would hold it ----------

    def output_opens(self, port=0, bclk=12, ws=10, dout=9, din=11, rate=24000):
        want = (port, bclk, ws, dout, din, rate)
        if self.live is not None and self.live != want:
            raise ValueError("another wire")
        self.live = want
        self.holds |= 1

    def output_closes(self):
        self.holds &= ~1
        if not self.holds:
            self.live = None

    # --- the interrupt ------------------------------------------------------

    def deliver(self, data):
        self.ring += data
        self.captured += len(data) // 2
