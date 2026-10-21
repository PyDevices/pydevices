"""Optional same-interpreter adapter for an earful Connect device.

Importing this module never starts earful and never reads credentials.  A
caller supplies the already-created earful Device instance, or calls
``discover`` to use a module-level ``device``/``current_device`` if an
application has exposed one.
"""


class EarfulAdapter:
    def __init__(self, device):
        self.device = device

    @property
    def device_id(self):
        return getattr(self.device, "device_id", None) or getattr(self.device, "name", None)

    @property
    def name(self):
        return getattr(self.device, "name", None) or self.device_id

    def play(self, context_uri=None, uris=None, position_ms=None):
        # earful.Device.play uses Connect-shaped keyword arguments.  Passing
        # a context as the positional URI would request a single track and
        # silently lose the playlist; position_ms maps to its ``position``
        # argument so a local play has the same seek semantics as Web API.
        position = 0 if position_ms is None else int(position_ms)
        if uris is not None:
            if len(uris) != 1:
                raise ValueError("earful local playback accepts one URI; use context_uri for a queue")
            return self.device.play(uri=uris[0], position=position)
        if context_uri is not None:
            return self.device.play(context=context_uri, position=position)
        return self.device.play(position=position)

    def pause(self):
        return self.device.pause()

    def resume(self):
        method = getattr(self.device, "resume", None)
        return method() if method is not None else self.device.play()

    def next(self):
        return self.device.next()

    def previous(self):
        method = getattr(self.device, "prev", None)
        return method() if method is not None else self.device.previous()

    def seek(self, position_ms):
        return self.device.seek(position_ms)

    def set_volume(self, volume_percent):
        self.device.volume = volume_percent
        return None

    def state(self):
        return {
            "device_id": self.device_id,
            "name": self.name,
            "is_active": bool(getattr(self.device, "active", True)),
            "is_playing": bool(getattr(self.device, "playing", False)),
            "volume_percent": getattr(self.device, "volume", None),
            "track": getattr(self.device, "track", None),
            "position_ms": getattr(self.device, "position", None),
            "duration_ms": getattr(self.device, "duration", None),
            "context": getattr(self.device, "playlist", None),
        }


def discover(module=None):
    """Return an adapter only when an application has exposed an earful device."""
    if module is None:
        try:
            import earful as module
        except ImportError:
            return None
    device = getattr(module, "current_device", None) or getattr(module, "device", None)
    if device is None:
        return None
    return EarfulAdapter(device)
