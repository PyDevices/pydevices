# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""``mdns``: the DNS messages it writes and reads, and what ``find()`` makes
of a network's answers.

The network is a fake socket that answers each query with prepared DNS
messages, built here the way responders build them (with name compression),
so nothing here touches a network. Real responders differ in how much they
put in one answer: a Roku sends the port, the address and the TXT with its
PTR; others send only the PTR and wait to be asked for the rest.
"""

import struct
import unittest

import _env  # noqa: F401
import mdns

SVC = "_display._tcp.local"


def _name(name):
    out = b""
    for label in name.split("."):
        out += bytes((len(label),)) + label.encode()
    return out + b"\x00"


def _rr(name, rtype, rdata, ttl=120):
    # *name* is bytes already encoded (a full name or a compression pointer)
    return name + struct.pack(">HHIH", rtype, 1, ttl, len(rdata)) + rdata


def _message(records, ident=0):
    return struct.pack(">HHHHHH", ident, 0x8400, 0, len(records), 0, 0) + b"".join(records)


def _txt(*items):
    return b"".join(bytes((len(i),)) + i.encode() for i in items)


def roku_answer(ident):
    """Everything in one message, the instance name compressed against the
    service name the way responders write it."""
    svc = _name(SVC)
    inst = _name("Living Room")[:-1] + b"\xc0\x0c"  # "Living Room" + pointer to the service at offset 12
    srv = struct.pack(">HHH", 0, 0, 7250) + _name("X0120.local")
    return _message([
        _rr(svc, mdns.PTR, inst),
        _rr(b"\x0bLiving Room\xc0\x0c", mdns.SRV, srv),
        _rr(b"\x0bLiving Room\xc0\x0c", mdns.TXT, _txt("container_id={119A}", "flag")),
        _rr(_name("X0120.local"), mdns.A, bytes((192, 168, 1, 140))),
    ], ident)


class FakeSocket:
    """Answers each sent query with ``responder(questions)``'s messages."""

    def __init__(self, responder):
        self.responder = responder
        self.queue = []
        self.sent = []
        self.closed = False

    def sendto(self, pkt, addr):
        self.sent.append(pkt)
        self.queue.extend(self.responder(_questions(pkt), struct.unpack(">H", pkt[:2])[0]))

    def settimeout(self, t):
        pass

    def recvfrom(self, n):
        if not self.queue:
            raise OSError(110)
        return self.queue.pop(0), ("192.168.1.2", 5353)

    def close(self):
        self.closed = True


def _questions(pkt):
    qd = struct.unpack(">H", pkt[4:6])[0]
    at = 12
    out = []
    for _ in range(qd):
        name, at = mdns._read_name(pkt, at)
        out.append((name, struct.unpack(">H", pkt[at : at + 2])[0]))
        at += 4
    return out


class WithFakeNetwork(unittest.TestCase):
    def use(self, responder):
        sock = FakeSocket(responder)
        real = mdns._socket
        mdns._socket = lambda interface: sock
        self.addCleanup(setattr, mdns, "_socket", real)
        return sock


class Wire(unittest.TestCase):
    def test_query_asks_one_ptr_question(self):
        pkt = mdns.query([(SVC, mdns.PTR)], 7)
        self.assertEqual(struct.unpack(">HHHHHH", pkt[:12]), (7, 0, 1, 0, 0, 0))
        self.assertEqual(_questions(pkt), [(SVC, mdns.PTR)])

    def test_records_follow_compression(self):
        recs = mdns.records(roku_answer(1))
        self.assertIn((SVC, mdns.PTR, "Living Room." + SVC), recs)
        self.assertIn(("Living Room." + SVC, mdns.SRV, (7250, "X0120.local")), recs)
        self.assertIn(("X0120.local", mdns.A, "192.168.1.140"), recs)
        txt = [v for n, t, v in recs if t == mdns.TXT][0]
        self.assertEqual(txt, {"container_id": "{119A}", "flag": ""})

    def test_a_pointer_loop_is_an_error_not_a_hang(self):
        loop = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0) + b"\xc0\x0c"
        with self.assertRaises(ValueError):
            mdns.records(loop)


class Find(WithFakeNetwork):
    def test_everything_in_one_answer(self):
        sock = self.use(lambda qs, ident: [roku_answer(ident)] if (SVC, mdns.PTR) in qs else [])
        found = mdns.Server(None).find("_display", "_tcp", timeout=0.2)
        self.assertEqual(len(found), 1)
        s = found[0]
        self.assertEqual((s.instance_name, s.hostname, s.ipv4_address, s.port), ("Living Room", "X0120", "192.168.1.140", 7250))
        self.assertEqual((s.service_type, s.protocol), ("_display", "_tcp"))
        self.assertEqual(s.txt["container_id"], "{119A}")
        self.assertIsInstance(found, tuple)
        self.assertTrue(sock.closed)

    def test_asks_again_for_what_the_first_answer_left_out(self):
        inst = "Desk." + SVC

        def responder(qs, ident):
            out = []
            for name, qtype in qs:
                if (name, qtype) == (SVC, mdns.PTR):
                    out.append(_message([_rr(_name(SVC), mdns.PTR, _name(inst))], ident))
                elif (name, qtype) == (inst, mdns.SRV):
                    out.append(_message([_rr(_name(inst), mdns.SRV, struct.pack(">HHH", 0, 0, 8080) + _name("desk.local"))], ident))
                elif (name, qtype) == ("desk.local", mdns.A):
                    out.append(_message([_rr(_name("desk.local"), mdns.A, bytes((10, 0, 0, 5)))], ident))
            return out

        self.use(responder)
        (s,) = mdns.Server(None).find("_display", "_tcp", timeout=0.2)
        self.assertEqual((s.instance_name, s.ipv4_address, s.port), ("Desk", "10.0.0.5", 8080))

    def test_names_keep_their_spelling_and_match_without_case(self):
        msg = roku_answer(1).replace(b"Living Room", b"LIVING room")
        self.use(lambda qs, ident: [msg] if qs[0][1] == mdns.PTR else [])
        (s,) = mdns.Server(None).find("_DISPLAY", "_tcp", timeout=0.2)
        self.assertEqual(s.instance_name, "LIVING room")
        self.assertEqual(s.ipv4_address, "192.168.1.140")

    def test_a_malformed_answer_costs_only_itself(self):
        self.use(lambda qs, ident: [b"\x00\x01garbage", roku_answer(ident)] if qs[0][1] == mdns.PTR else [])
        found = mdns.Server(None).find("_display", "_tcp", timeout=0.2)
        self.assertEqual([s.instance_name for s in found], ["Living Room"])

    def test_nothing_answers(self):
        self.use(lambda qs, ident: [])
        self.assertEqual(mdns.Server(None).find("_display", "_tcp", timeout=0.1), ())

    def test_resolve(self):
        def responder(qs, ident):
            if qs == [("p4-devkit.local", mdns.A)]:
                return [_message([_rr(_name("p4-devkit.local"), mdns.A, bytes((192, 168, 1, 155)))], ident)]
            return []

        self.use(responder)
        self.assertEqual(mdns.resolve("p4-devkit", timeout=0.1), "192.168.1.155")
        self.assertIsNone(mdns.resolve("nobody", timeout=0.1))

    def test_advertising_needs_a_responder(self):
        with self.assertRaises(NotImplementedError):
            mdns.Server(None).advertise_service(service_type="_http", protocol="_tcp", port=80)


if __name__ == "__main__":
    unittest.main()
