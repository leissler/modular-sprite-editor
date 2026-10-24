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

# Release outside Windows links SGDK's library built from SGDK's sources with this GCC (once, into
# out/sgdk-gcc<version>; SGDK_LIB_DIR=... puts it elsewhere, `make sgdk-lib` builds only the library): the
# lib/libmd.a SGDK ships holds GCC 13's link-time code, which other GCCs refuse to link. On Windows SGDK's own
# GCC 13 links lib/libmd.a as it is, and debug links lib/libmd_debug.a, which has no link-time code, everywhere.
ifneq ($(OS),Windows_NT)
ifeq ($(BUILD_TYPE),release)
SGDK_LIB_DIR ?= out/sgdk-gcc$(shell $(CC) -dumpfullversion)
SGDK_LIB := $(abspath $(SGDK_LIB_DIR))
SGDK_TOOLS := $(SGDK_LIB)/tools
HOST_CC ?= cc
HOST_CXX ?= c++
# C17 like GCC 13: from GCC 15 on, C23 makes bool a keyword and snd_pcm.c no longer matches its header.
SGDK_LIB_MAKE = $(MAKE) -C $(SGDK) -f makelib.gen OUT_DIR=$(SGDK_LIB) ASMZ80=$(SGDK_TOOLS)/sjasm \
	BINTOS=$(SGDK_TOOLS)/bintos EXTRA_FLAGS=-std=gnu17
LIBMD := $(SGDK_LIB)/libmd.a

.PHONY: sgdk-lib
sgdk-lib: $(SGDK_LIB)/libmd.a

$(OUT_DIR)/rom.out: $(LIBMD)

# Built from scratch whenever SGDK changes, its resource header first: sys.c and others include it.
$(SGDK_LIB)/libmd.a: $(wildcard $(addprefix $(SGDK)/,makelib.gen common.mk inc/*.h inc/*/*.h inc/*/*/*.h \
		src/*.* src/*/*.* src/*/*/*.* res/*.* res/*/*.*)) | $(SGDK_TOOLS)/sjasm $(SGDK_TOOLS)/bintos
	$(RM) -r -f $(SGDK_LIB)/src $(SGDK_LIB)/res $@
	$(SGDK_LIB_MAKE) $(SGDK_LIB)/res/libres.o
	$(SGDK_LIB_MAKE) $@

# SGDK's Z80 assembler and binary converter (for its sound drivers), from the sources in its tools folder
$(SGDK_TOOLS)/sjasm: $(wildcard $(SGDK)/tools/sjasm/src/*.cpp $(SGDK)/tools/sjasm/src/*.h)
	@$(MKDIR) -p $(dir $@)
	$(HOST_CXX) -O2 -w -DMAX_PATH=MAXPATHLEN -o $@ $(filter %.cpp,$^)

$(SGDK_TOOLS)/bintos: $(SGDK)/tools/bintos/src/bintos.c
	@$(MKDIR) -p $(dir $@)
	$(HOST_CC) -O2 -w -o $@ $<
endif
endif
