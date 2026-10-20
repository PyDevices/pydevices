# What the CircuitPython interpreter attached to a release adds to
# CircuitPython's unix coverage variant beyond the PyDevices modules, as a user
# C module so CircuitPython's own tree is never edited. release_interpreters.sh
# passes this directory to build_mp.py --modules.
#
# audiospeed: CircuitPython's own Resampler and SpeedChanger. The coverage
# variant hand-lists its sources and leaves this module out. Its rate validator
# passes fractional bounds through mp_int_t parameters, which the unix port's
# -Werror=float-conversion refuses, so that warning is downgraded for these
# objects only.

ifeq ($(findstring /ports/unix,$(abspath $(CURDIR))),)
$(error unix-extras is for CircuitPython's unix port only)
endif

CP_UNIX_EXTRAS_AUDIOSPEED := \
	shared-bindings/audiospeed/__init__.c \
	shared-bindings/audiospeed/Resampler.c \
	shared-bindings/audiospeed/SpeedChanger.c \
	shared-module/audiospeed/__init__.c \
	shared-module/audiospeed/Resampler.c \
	shared-module/audiospeed/SpeedChanger.c

SRC_C += $(CP_UNIX_EXTRAS_AUDIOSPEED)
CFLAGS_USERMOD += -DCIRCUITPY_AUDIOSPEED=1
$(foreach _s,$(CP_UNIX_EXTRAS_AUDIOSPEED),$(eval $(BUILD)/$(_s:.c=.o): CFLAGS += -Wno-error=float-conversion))
