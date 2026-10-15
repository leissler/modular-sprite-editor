# The SNES demo of the Modular Sprite Editor (PVSnesLib). PVSNESLIB_HOME may point at an installed PVSnesLib;
# otherwise third_party/pvsneslib is used (see ../README.md).
ifeq ($(strip $(PVSNESLIB_HOME)),)
PVSNESLIB_HOME := $(CURDIR)/third_party/pvsneslib
endif
export PVSNESLIB_HOME

ifeq ($(wildcard $(PVSNESLIB_HOME)/devkitsnes/snes_rules),)
$(error PVSnesLib not found. Set PVSNESLIB_HOME or put PVSnesLib into examples/snes/snes_demo/third_party/pvsneslib)
endif

export ROMNAME := modular_sprite_snes_demo
export ROMTITLE := MODULAR SPRITE DEMO
# FastROM: the CPU runs 3.58 MHz from the cartridge instead of 2.68 MHz.
export FASTROM := 1
SRC := src
CFLAGS += -I$(CURDIR)/inc

# The ROM size the exported data needs (written by the exporter).
-include modsprite_rom.mk

include $(PVSNESLIB_HOME)/devkitsnes/snes_rules

.PHONY: all
all: $(ROMNAME).sfc

clean: cleanBuildRes cleanRom cleanGfx
