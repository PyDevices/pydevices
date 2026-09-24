// The part of the gate page every runtime shares: the query parameters, the
// log (on the page and POSTed to serve.py), and the button.
const q = new URLSearchParams(location.search);
window.gateParams = {
  runtime: document.documentElement.dataset.runtime,
  plant: q.get("plant") === "1" ? 1 : 0,
  mtu: parseInt(q.get("mtu") || "23", 10),
  name: q.get("name") || "bledev-web",
  mock: q.get("mock") === "1" ? 1 : 0,
};

const out = () => document.getElementById("log");

window.gateLog = (line) => {
  line = String(line);
  out().textContent += line + "\n";
  fetch("/log", { method: "POST", body: `[${window.gateParams.runtime}] ${line}` }).catch(() => {});
  if (line.startsWith("RESULT ")) {
    const go = document.getElementById("go");
    go.textContent = line;
    go.className = line.endsWith("PASS") ? "pass" : "fail";
  }
};

window.gateReady = () => {
  const go = document.getElementById("go");
  go.disabled = false;
  go.textContent = "Connect and run the gate";
  window.gateLog("READY " + navigator.userAgent);
};

window.addEventListener("error", (e) => window.gateLog("PAGE ERROR " + e.message));
window.addEventListener("unhandledrejection", (e) => window.gateLog("PAGE REJECTION " + (e.reason && e.reason.stack || e.reason)));
