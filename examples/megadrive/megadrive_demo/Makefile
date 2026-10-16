ROM_NAME = modular_sprite_megadrive_demo

ifeq ($(SGDK),)
# Relative: on Windows $(CURDIR) is an MSYS path (/c/...) that SGDK's gcc.exe cannot open.
SGDK := third_party/sgdk
endif

ifeq ($(wildcard $(SGDK)/makefile.gen),)
$(error SGDK not found. Set SGDK=/path/to/sgdk or place SGDK in examples/megadrive/megadrive_demo/third_party/sgdk)
endif

include $(SGDK)/makefile.gen

ifeq ($(shell command -v convsym >/dev/null 2>&1; echo $$?),1)
CONVSYM := true
endif

ifeq ($(BUILD_TYPE),debug)
CFLAGS := $(subst -O1,-O3,$(CFLAGS))
AFLAGS := $(subst -O1,-O3,$(AFLAGS))
endif
