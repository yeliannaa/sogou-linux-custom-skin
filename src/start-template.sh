#!/usr/bin/env bash
# sogou-custom-skin-portable-autostart-v1
set -u
umask 077
TASK_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATCH="$TASK_DIR/patches/status-screen-fix.so"
SOGOU_LIB=/opt/sogoupinyin/files/lib/libSogouIme.so
EXPECTED_LIB=@@NATIVE_SHA256@@
EXPECTED_PATCH=@@STATUS_SHA256@@
V_PATCH="$TASK_DIR/patches/v-mode-fix.so"
EXPECTED_V_PATCH=@@VMODE_SHA256@@
V_PRELOAD=""
LOG="$TASK_DIR/startup.log"
if [[ -f "$LOG" ]] && (( $(stat -c %s "$LOG") > 1048576 )); then
    mv -- "$LOG" "$LOG.previous"
fi
log() { printf '%(%Y-%m-%d %H:%M:%S)T %s\n' -1 "$*" >> "$LOG"; }
if [[ -z ${DISPLAY:-} || -z ${XDG_RUNTIME_DIR:-} ]]; then
    log 'No desktop display/runtime directory; skipped.'
    exit 0
fi
exec 9>"$XDG_RUNTIME_DIR/sogou-custom-skin-status-position.lock"
flock -n 9 || exit 0
hash_is() {
    [[ -r "$1" ]] || return 1
    local actual
    actual=$(sha256sum -- "$1") || return 1
    [[ ${actual%% *} == "$2" ]]
}
same_display() {
    [[ -r /proc/$1/environ ]] || return 1
    tr '\0' '\n' < "/proc/$1/environ" | grep -Fxq -- "DISPLAY=$DISPLAY"
}
patch_loaded() {
    local pid parent_ready=0
    while read -r pid; do
        same_display "$pid" || continue
        if grep -Fq -- "$PATCH" "/proc/$pid/maps" 2>/dev/null; then
            if [[ -n "$V_PRELOAD" ]]; then
                grep -Fq -- "$V_PATCH" "/proc/$pid/maps" 2>/dev/null || return 1
            fi
            parent_ready=1
        fi
    done < <(pgrep -u "$(id -u)" -x fcitx || true)
    (( parent_ready )) || return 1
    # With a keyboard IM selected, Sogou is legitimately started on demand.
    # Its later process inherits the already verified parent's preload setting.
    while read -r pid; do
        same_display "$pid" || continue
        grep -Fq -- "$PATCH" "/proc/$pid/maps" 2>/dev/null || return 1
        if [[ -n "$V_PRELOAD" ]]; then
            grep -Fq -- "$V_PATCH" "/proc/$pid/maps" 2>/dev/null || return 1
        fi
    done < <(pgrep -u "$(id -u)" -f '^/opt/sogoupinyin/files/bin/sogoupinyin-service( |$)' || true)
    return 0
}
launch_native() {
    nohup env -u LD_PRELOAD LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu /usr/bin/fcitx "$@" </dev/null >>"$LOG" 2>&1 9>&- &
}
if [[ "$EXPECTED_PATCH" == disabled ]]; then
    launch_native
    exit 0
fi
if ! hash_is "$SOGOU_LIB" "$EXPECTED_LIB" || ! hash_is "$PATCH" "$EXPECTED_PATCH"; then
    log 'Version or patch changed; starting ordinary Fcitx without this patch.'
    launch_native
    exit 0
fi
if hash_is "$V_PATCH" "$EXPECTED_V_PATCH"; then
    V_PRELOAD=":$V_PATCH"
else
    log "V-mode patch unavailable; retaining status-position patch only."
fi
if patch_loaded; then
    log 'Verified patch already loaded; no restart needed.'
    exit 0
fi
# im-config may have started plain Fcitx before this desktop entry runs.
# Replace that instance once; this script is not a background watchdog.
log 'Loading verified skin compatibility patches.'
timeout 3 /usr/bin/fcitx-remote -e >/dev/null 2>&1 || true
sleep 1
nohup env LD_PRELOAD="$PATCH$V_PRELOAD${LD_PRELOAD:+:$LD_PRELOAD}" LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu /usr/bin/fcitx -r </dev/null >>"$LOG" 2>&1 9>&- &
for (( attempt=0; attempt<30; attempt++ )); do
    sleep .5
    if patch_loaded; then
        state=$(timeout 3 /usr/bin/fcitx-remote 2>/dev/null || true)
        if [[ "$state" =~ ^[012]$ ]]; then
            log 'Patch loaded in Fcitx; any active Sogou service verified. Startup complete.'
            exit 0
        fi
    fi
done
log 'Patched startup did not become ready; restoring ordinary Fcitx.'
timeout 3 /usr/bin/fcitx-remote -e >/dev/null 2>&1 || true
sleep 1
launch_native -r
exit 1
