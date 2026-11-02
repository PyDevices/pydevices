# Roadmap

- **Scripts on CircuitPython boards.** Run a plain script from the home
  screen there too, through CircuitPython's own way to start a file next.
- **Publishing.** appkit in the mip index with the other packages here, and
  later a pip package.
- **A model for a front panel.** An app can expose a model (describe, apply,
  telemetry, command) and the launcher exposes one too (the app list, which
  app is up, switch), so hmilink can serve them to a phone, a browser or a
  second screen. Apps without a model pay nothing. Model-first becomes the
  recommended way to write an app in these docs, not a requirement.
