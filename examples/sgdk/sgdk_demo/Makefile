ROM_NAME = modular_sprite_sgdk_demo

ifeq ($(SGDK),)
SGDK := $(CURDIR)/third_party/sgdk
endif

ifeq ($(wildcard $(SGDK)/makefile.gen),)
$(error SGDK not found. Set SGDK=/path/to/sgdk or place SGDK in examples/sgdk/sgdk_demo/third_party/sgdk)
endif

include $(SGDK)/makefile.gen

ifeq ($(shell command -v convsym >/dev/null 2>&1; echo $$?),1)
CONVSYM := true
endif

ifeq ($(BUILD_TYPE),debug)
CFLAGS := $(subst -O1,-O3,$(CFLAGS))
AFLAGS := $(subst -O1,-O3,$(AFLAGS))
endif
