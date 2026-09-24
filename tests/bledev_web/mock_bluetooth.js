// A stand-in for navigator.bluetooth, loaded when the page has ?mock=1.
//
// It plays nus_gate_server.py's part in JavaScript: one device named
// "bledev-gate" with the Nordic UART service, answering MTU, UP, DOWN, ECHO
// and BYE. It lets the gate page run headless in any browser, so the Python to
// JavaScript plumbing is checked before a radio is involved. Like Android, it
// cuts a write without response to the link's payload (mock_mtu - 3) without
// saying so, which is why webble sizes writes to the MTU it's told.
// ?mockplant=1 flips the bit at offset 5000 of DOWN and ECHO.
(() => {
  const q = new URLSearchParams(location.search);
  if (q.get("mock") !== "1") return;
  const MTU = parseInt(q.get("mock_mtu") || "23", 10);
  const PLANT = q.get("mockplant") === "1";
  const NUS = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
  const RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";
  const TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";
  const later = (f, ms = 0) => setTimeout(f, ms);
  const pattern = (n, seed) => {
    const a = new Uint8Array(n);
    for (let i = 0; i < n; i++) a[i] = (i * 7 + (i >> 8) * 13 + seed) & 255;
    return a;
  };
  const err = (name, message) => Object.assign(new Error(message), { name });

  class Char extends EventTarget {
    constructor(service, uuid, props) {
      super();
      this.service = service;
      this.uuid = uuid;
      this.properties = props;
      this.value = null;
      this.notifying = false;
    }
    async writeValueWithoutResponse(v) {
      if (!device.gatt.connected) throw err("NetworkError", "GATT Server is disconnected.");
      const bytes = new Uint8Array(v.buffer ? v.buffer.slice(v.byteOffset, v.byteOffset + v.byteLength) : v);
      server.receive(bytes.slice(0, MTU - 3)); // silent truncation, as Android does
    }
    async writeValueWithResponse(v) { return this.writeValueWithoutResponse(v); }
    async readValue() { return new DataView(new Uint8Array(0).buffer); }
    async startNotifications() { this.notifying = true; return this; }
    async stopNotifications() { this.notifying = false; return this; }
  }

  // The server side: nus_gate_server.py's protocol.
  const server = {
    buf: [],
    mode: null,
    need: 0,
    got: [],
    sent: 0,
    queue: [],
    sending: false,
    send(bytes) {
      for (let i = 0; i < bytes.length; i += MTU - 3) this.queue.push(bytes.slice(i, i + MTU - 3));
      this.pump();
    },
    pump() {
      if (this.sending) return;
      this.sending = true;
      const step = () => {
        const chunk = this.queue.shift();
        if (!chunk || !device.gatt.connected) { this.sending = false; return; }
        if (tx.notifying) {
          tx.value = new DataView(chunk.buffer, chunk.byteOffset, chunk.byteLength);
          tx.dispatchEvent(new Event("characteristicvaluechanged"));
        }
        later(step);
      };
      later(step);
    },
    line(text) { this.send(new TextEncoder().encode(text + "\n")); },
    flip(chunk, sent) {
      if (PLANT && sent <= 5000 && 5000 < sent + chunk.length) chunk[5000 - sent] ^= 1;
      return chunk;
    },
    receive(bytes) {
      if (this.mode === "UP") {
        this.got.push(...bytes);
        if (this.got.length >= this.need) {
          const want = pattern(this.need, 1);
          let bad = 0, first = -1;
          for (let i = 0; i < this.need; i++) if (this.got[i] !== want[i]) { bad++; if (first < 0) first = i; }
          const ok = bad === 0 && this.got.length === this.need;
          this.line(`UP ${ok ? "OK" : "BAD"} ${Date.now() - this.t0} ${bad} ${first}`);
          this.mode = null;
        }
        return;
      }
      if (this.mode === "ECHO") {
        const chunk = this.flip(Uint8Array.from(bytes), this.sent);
        this.sent += chunk.length;
        this.send(chunk);
        if (this.sent >= this.need) this.mode = null;
        return;
      }
      this.buf.push(...bytes);
      const nl = this.buf.indexOf(10);
      if (nl < 0) return;
      const cmd = new TextDecoder().decode(Uint8Array.from(this.buf.slice(0, nl))).trim();
      const rest = this.buf.slice(nl + 1);
      this.buf = [];
      const [op, n] = cmd.split(" ");
      if (op === "MTU") this.line(`MTU ${MTU}`);
      else if (op === "UP") { this.mode = "UP"; this.need = +n; this.got = []; this.t0 = Date.now(); }
      else if (op === "DOWN") this.send(this.flip(pattern(+n, 2), 0));
      else if (op === "ECHO") { this.mode = "ECHO"; this.need = +n; this.sent = 0; }
      else if (op === "BYE") later(() => device.gatt.disconnect(), 50);
      if (rest.length) this.receive(Uint8Array.from(rest));
    },
  };

  const service = { uuid: NUS, isPrimary: true };
  const rx = new Char(service, RX, { read: false, write: true, writeWithoutResponse: true, notify: false, indicate: false });
  const tx = new Char(service, TX, { read: false, write: false, writeWithoutResponse: false, notify: true, indicate: false });
  service.getCharacteristics = async (uuid) => {
    const all = [rx, tx].filter((c) => !uuid || c.uuid === uuid);
    if (!all.length) throw err("NotFoundError", "No Characteristics matching UUID found in Service.");
    return all;
  };

  const device = new EventTarget();
  device.id = "mock-device-id";
  device.name = "bledev-gate";
  device.gatt = {
    connected: false,
    device,
    async connect() { this.connected = true; return this; },
    disconnect() {
      if (!this.connected) return;
      this.connected = false;
      later(() => device.dispatchEvent(new Event("gattserverdisconnected")));
    },
    async getPrimaryServices(uuid) {
      if (uuid && uuid !== NUS) throw err("NotFoundError", "No Services matching UUID found in Device.");
      return [service];
    },
  };

  const bluetooth = {
    async getAvailability() { return true; },
    async requestDevice(options) {
      if (!navigator.userActivation || !navigator.userActivation.isActive) {
        throw err("SecurityError", "Must be handling a user gesture to show a permission request.");
      }
      const f = (options.filters || [])[0] || {};
      if (f.name && f.name !== device.name) throw err("NotFoundError", "User cancelled the requestDevice() chooser.");
      return device;
    },
  };
  Object.defineProperty(navigator, "bluetooth", { value: bluetooth, configurable: true });
  console.log("mock navigator.bluetooth installed, mtu", MTU, "plant", PLANT);
})();
