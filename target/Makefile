# Build the on-target programs with the QNX SDP 8.0 toolchain.
#   source ~/qnx800/qnxsdp-env.sh && make            # x86_64 (QEMU quick-start image)
#   make ARCH=aarch64le                               # 64-bit ARM targets (Raspberry Pi 4/5 ...)
ARCH ?= x86_64
CC    = qcc -Vgcc_nto$(ARCH)
CFLAGS = -O1 -g -Wall -Wextra -Wno-unused-parameter
OUT   = build/$(ARCH)
PROGS = mars ipc_deadlock deadline starve

all: $(addprefix $(OUT)/,$(PROGS))

$(OUT)/%: %.c pf_mark.h
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -rf build
