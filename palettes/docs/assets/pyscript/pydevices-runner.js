/** Load the first-party direct MicroPython documentation host. */
import("https://PyDevices.github.io/assets/chrome/docs-runtime.js").catch((error) => {
  console.error("Unable to load the PyDevices documentation runtime:", error);
});
