#!/bin/sh
ROOT=/home/root/car_ov5640_v1
ADDRESS=169.254.72.156
FIRMWARE=ov5640_bench.bin
EXPECTED=f7fd3b81ad03260d49487ec4c8224e9f5c9dfc5ff5a8437e1b2bb7883bad416d
MANAGER=/sys/class/fpga_manager/fpga0
PIDFILE=/var/run/car_ov5640.pid
LOCK=/var/run/car_ov5640.lock
PREPARED=/var/run/car_ov5640.prepared
LOG=/var/log/car_ov5640.log
prepare_hardware() {
    actual=$(sha256sum "/lib/firmware/$FIRMWARE") || return 1
    [ "${actual%% *}" = "$EXPECTED" ] || return 1
    if [ -r "$PREPARED" ]; then
        [ "$(cat "$PREPARED")" = "$EXPECTED" ] || return 1
        [ "$(cat "$MANAGER/state")" = operating ] || return 1
        return 0
    fi
    for device in amba_pl:vcap_dvp 41600000.i2c 43c40000.v_frmbuf_wr 41220000.gpio; do
        [ -L "/sys/bus/platform/devices/$device/driver" ] || return 1
    done
    for app in psplash QMainApp; do
        pids=$(pidof "$app" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            kill $pids || return 1
            count=0
            while pidof "$app" >/dev/null 2>&1; do
                [ "$count" -lt 10 ] || return 1
                sleep 1
                count=$((count + 1))
            done
        fi
    done
    for device in leds xlnx-drm.0 xlnx-drm.1 amba_pl:drm_pl_disp_hdmi \
        amba_pl:drm_pl_disp_lcd amba_pl:atk_hdmi_drm amba_pl:atk_lcd_drm \
        43c10000.v_tc 43c60000.v_tc 43c20000.v_frmbuf_rd 43c70000.v_frmbuf_rd \
        43c30000.clk_wiz 43c50000.clk_wiz 43c00000.PWM 41200000.gpio 41210000.gpio; do
        driver="/sys/bus/platform/devices/$device/driver"
        if [ -L "$driver" ]; then
            printf '%s' "$device" > "$driver/unbind" || return 1
            [ ! -L "$driver" ] || return 1
        fi
    done
    printf '%s' "$FIRMWARE" > "$MANAGER/firmware" || return 1
    [ "$(cat "$MANAGER/state")" = operating ] || return 1
    devmem 0x41220000 32 7 || return 1
    devmem 0x41600040 32 10 || return 1
    devmem 0x41600120 32 15 || return 1
    devmem 0x41600100 32 2 || return 1
    devmem 0x41600100 32 1 || return 1
    devmem 0x41600028 32 11 || return 1
    devmem 0x4160001c 32 0x80000000 || return 1
    printf '%s\n' "$EXPECTED" > "$PREPARED"
}
supervise() {
    child=
    cleanup() {
        trap - TERM INT EXIT
        if [ -n "$child" ]; then
            kill "$child" 2>/dev/null || true
            wait "$child" 2>/dev/null || true
        fi
        rm -f "$PIDFILE"
        rmdir "$LOCK" 2>/dev/null || true
    }
    trap 'exit 0' TERM INT
    trap cleanup EXIT
    echo "OV5640_START $(date)"
    cd "$ROOT" || return 1
    prepare_hardware || { echo OV5640_HARDWARE_FAILED; return 1; }
    python3 -m software.board.ov5640_ready || { echo OV5640_CAPTURE_FAILED; return 1; }
    ip -4 addr show dev eth0 | grep -q "$ADDRESS/16" || \
        ip addr add "$ADDRESS/16" dev eth0 || return 1
    ip route show 192.168.2.0/24 | grep -q 'dev eth0' || \
        ip route add 192.168.2.0/24 dev eth0 || return 1
    echo "OV5640_SERVICE_READY $ADDRESS:8767"
    while :; do
        python3 -m software.board.blue_tcp_server --bind "$ADDRESS" \
            --camera /dev/video0 --camera-backend ov5640 >/dev/null &
        child=$!
        wait "$child"
        result=$?
        child=
        echo "OV5640_SESSION_END rc=$result $(date)"
        sleep 2
    done
}
case "$1" in
    start)
        [ -d "$ROOT/software/board" ] || exit 1
        if [ -r "$PIDFILE" ]; then
            read -r existing < "$PIDFILE"
            kill -0 "$existing" 2>/dev/null && exit 0
        fi
        mkdir "$LOCK" 2>/dev/null || exit 1
        "$0" supervise </dev/null >>"$LOG" 2>&1 &
        printf '%s\n' "$!" > "$PIDFILE"
        ;;
    supervise) supervise ;;
    stop)
        if [ -r "$PIDFILE" ]; then
            read -r existing < "$PIDFILE"
            kill "$existing" 2>/dev/null || true
        fi
        ;;
    status)
        [ -r "$PIDFILE" ] || exit 1
        read -r existing < "$PIDFILE"
        kill -0 "$existing" 2>/dev/null
        ;;
    *) exit 2 ;;
esac
