# Draft: machine.I2S silently deinits a live instance when an id is re-constructed

**Target:** micropython/micropython, an issue (not a PR — the fix is a design
choice between raising and reference-counting, and that is theirs to make).
**Status:** ready to file, awaiting Brad's word. Post only what is below the `---`.

Our second report upstream; the first is
[#19667](https://github.com/micropython/micropython/issues/19667). House posture
is case-by-case per bug and promise nothing, so this is filed on its own merits
and carries no roadmap.

Keep it short. The whole bug is four lines of `mp_machine_i2s_make_new_instance`
and one observed consequence. The duplex limitation found alongside it is a
separate, larger conversation and is deliberately **not** in this report — it
would turn a plain bug report into a feature argument. If they ask what we were
doing when we hit it, that is the moment to raise it.

Verified on ESP32-P4 (Waveshare panel, ES8311 out / ES7210 in on one I2S bus),
MicroPython v1.28.0, 2026-09-04. Tone audibility confirmed by a person.

---

### `machine.I2S`: re-constructing an id silently deinitialises the instance still using it

On the esp32 port, constructing an `I2S` id that is already in use does not
raise. `mp_machine_i2s_make_new_instance` (`ports/esp32/machine_i2s.c:402`)
finds the occupied slot, deinitialises it, and hands back the same object:

```c
if (MP_STATE_PORT(machine_i2s_obj)[i2s_id] == NULL) {
    self = mp_obj_malloc_with_finaliser(machine_i2s_obj_t, &machine_i2s_type);
    MP_STATE_PORT(machine_i2s_obj)[i2s_id] = self;
    self->i2s_id = i2s_id;
} else {
    self = MP_STATE_PORT(machine_i2s_obj)[i2s_id];
    machine_i2s_deinit(self);
}
```

Because both Python handles are the same object, the first user's handle is
reinitialised underneath it, in the other direction, with no error anywhere.

Observed on an ESP32-P4 with a codec on I2S0, playing a 440 Hz tone and then
opening a capture instance three seconds in:

```
mic opened, read 8000 bytes, 3003 non-zero samples
playing flag says: True
(no exception)
```

The tone stopped audibly at the three-second mark. The capture returned real
samples, so it is a live reassignment rather than a stale buffer, and the
playback object went on reporting `playing == True` after losing its hardware.

Reversing the order does raise, so the only ordering that produces a
diagnostic is the one code is less likely to take.

Suggested behaviour, in preference order: raise on constructing an id whose
instance has not been deinitialised; or, if reuse is deliberate, mark the
displaced object closed so its `playing` no longer answers `True`. Either way
the current behaviour loses data with no signal.
