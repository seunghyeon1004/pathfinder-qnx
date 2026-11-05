#!/bin/bash
# Helper for the QNX 8.0 QEMU quick-start image (software emulation, no KVM needed).
#   qnx-vm.sh start      boot in background, wait until ssh answers
#   qnx-vm.sh stop
#   qnx-vm.sh ssh <cmd>  run a command as qnxuser (stdin is forwarded)
#   qnx-vm.sh sudo <cmd> run a command as root on the target
#   qnx-vm.sh push <local> <remote-path>
#   qnx-vm.sh pull <remote-path> <local>
# Env: PF_IMAGE_DIR = folder with ifs.bin + disk-qemu.qcow2 (see docs/RUN.md), default ../../image
# Default quick-start credentials: qnxuser / qnxuser, ssh forwarded to localhost:2222.
export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH
D=$(cd "$(dirname "$0")" && pwd)
IMG=${PF_IMAGE_DIR:-$D/../../image}
export SSH_ASKPASS="$D/askpass.sh" SSH_ASKPASS_REQUIRE=force DISPLAY=:0
SSH="ssh -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o PubkeyAuthentication=no -o PreferredAuthentications=password -o ConnectTimeout=5 qnxuser@127.0.0.1"
case "$1" in
start)
  pgrep -f qemu-system-x86_64 >/dev/null && { echo "VM already running"; exit 0; }
  nohup qemu-system-x86_64 -nographic -m "${RAM:-4096}" -smp "${CPUS:-4}" -cpu max -accel tcg,thread=multi,tb-size=1024 \
    -kernel "$IMG/ifs.bin" -drive file="$IMG/disk-qemu.qcow2",format=qcow2,if=ide,id=drv0 \
    -netdev user,id=net0,hostfwd=tcp::2222-:22 -device virtio-net-pci,netdev=net0 \
    -object rng-random,filename=/dev/urandom,id=rng0 -device virtio-rng-pci,rng=rng0 \
    -serial file:/tmp/qnx-vm-console.log -monitor none >/dev/null 2>&1 &
  T0=$(date +%s)
  until $SSH 'echo QNXUP' 2>/dev/null </dev/null | grep -q QNXUP; do
    sleep 3; [ $(( $(date +%s) - T0 )) -gt 300 ] && { echo "boot timeout"; exit 1; }
  done
  echo "QNX VM up after $(( $(date +%s) - T0 ))s: $($SSH uname -a </dev/null)" ;;
stop) pkill -f qemu-system-x86_64 ;;
ssh)  shift; exec $SSH "$@" ;;
sudo) shift; exec $SSH "echo qnxuser | sudo -S -p '' $*" ;;
push) $SSH "cat > '$3' && chmod +x '$3'" < "$2" ;;
pull) $SSH "cat '$2'" > "$3" ;;
*) sed -n 2,12p "$0"; exit 1 ;;
esac
