# Build and run instructions

Verified with: **QNX SDP 8.0** (non-commercial QNX Everywhere license), `qcc` 12.2.0 (`-Vgcc_ntox86_64`), target **QEMU x86_64
quick-start image** (`QNX qnxqemu 8.0.0 2026/06/05 x86pc x86_64`, kernel `procnto-smp-instr`), on an Apple Silicon Mac
(x86 SDP in an amd64 Docker container, QEMU 11 with software emulation, no KVM). A Linux x86_64 host with KVM works the same way and is faster.

## 0. Prerequisites
* QNX SDP 8.0 installed (QNX Software Center, free licence at https://www.qnx.com/products/everywhere/). SDP 8.0 hosts are x86_64 Linux/Windows only.
* The quick-start QEMU image: install package `com.qnx.qnx800.quickstart.qemu` in the Software Center, then in `~/qnx800/images/qemu`
  run `./unpack_qemu_image.sh`. You get `qemu/output/ifs.bin` and `disk-qemu` (raw, 48 GB sparse). For a small portable copy:
  `qemu-img convert -O qcow2 disk-qemu disk-qemu.qcow2` (5 GB) and put `ifs.bin` + `disk-qemu.qcow2` in one folder (`PF_IMAGE_DIR`).
* `qemu-system-x86_64` (Linux: `apt install qemu-system-x86`; macOS: `brew install qemu`), `python3` >= 3.9 (standard library only).
* Apple Silicon / no native SDP: Docker + an amd64 container with the SDP in a volume. See `scripts/docker-make.sh`
  (variables `PF_QNX_VOLUME`, `PF_QNX_IMAGE`); the Dockerfile used is in `docs/Dockerfile.sdp-env`.

## 1. Build the on-target programs
```
source ~/qnx800/qnxsdp-env.sh
make -C target                     # x86_64 -> target/build/x86_64/{mars,ipc_deadlock,deadline,starve}
make -C target ARCH=aarch64le      # 64-bit ARM targets (Raspberry Pi 4/5 ...), same sources
# without a native SDP:  scripts/docker-make.sh
```

## 2. Boot QNX and record traces
```
export PF_IMAGE_DIR=/path/to/image          # ifs.bin + disk-qemu.qcow2
scripts/qnx-vm.sh start                     # ssh up in ~20 s even without KVM
scripts/pf-run.sh mars none 3               # bug: pthread mutex with PTHREAD_PRIO_NONE
scripts/pf-run.sh mars inherit 3            # fix: PTHREAD_PRIO_INHERIT (QNX default)
```
`pf-run.sh` pushes the binary, runs it under `tracelogger -w` as root on the target, pulls the `.kev` file and converts it with
the SDP's `traceprinter` (found on `PATH`, else through the Docker env).

## 3. Analyze
```
cd host
python3 -m pathfinder analyze ../examples/traces/mars_none.kev --out ../report     # needs traceprinter, or pass the .txt/.txt.gz dump
open ../report/mars_none.html
python3 -m pathfinder compare ../examples/traces/mars_none.txt.gz ../examples/traces/mars_inherit.txt.gz
python3 -m unittest discover tests                                                  # runs on the committed real traces
```
Exit status of `analyze` is 1 when a critical finding exists (usable in CI).

## 4. Everything at once
`scripts/e2e.sh` builds, boots the VM, records bug and fix traces for all four scenarios, analyzes them and asserts the expected
findings. The committed `examples/` is the output of this script.

## 5. Optional LLM narrative
`PF_ENV_FILE=/path/to/file-with-ANTHROPIC_API_KEY python3 -m pathfinder analyze ... --llm`. Off by default; see `host/pathfinder/llm.py`
for the citation-validation contract.
