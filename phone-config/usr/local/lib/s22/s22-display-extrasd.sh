#!/bin/sh
# SPDX-License-Identifier: MIT
# Background manager for Samsung Galaxy S22 (S6E3FAC) Display Extras:
#  1. Restores VRR, mDNIe colour calibration, white balance, ACL, and AOD settings at boot
#  2. Drives automatic High Brightness Mode (HBM) in sunlight from STK33915 illuminance
#  3. Suppresses AOD HLPM when STK33915 proximity sensor detects pocket / face-down

set -u

CONF="/etc/s22-display.conf"
PANEL=""
for _ in $(seq 1 30); do
	for d in /sys/bus/mipi-dsi/devices/*; do
		if [ -f "$d/vrr_mode" ]; then
			PANEL="$d"
			break 2
		fi
	done
	sleep 1
done

[ -n "$PANEL" ] || exit 1

load_conf() {
	VRR_MODE="adaptive"
	COLOUR_MODE="vivid"
	WHITE_BALANCE_RGB="255 255 255"
	NIGHT_KELVIN="4300"
	ACL_MODE="1"
	HBM_AUTO="1"
	HBM_BOOST_LUX="15000"
	HBM_SUNLIGHT_LUX="40000"
	HBM_EXIT_LUX="8000"
	AOD_ENABLED="1"
	AOD_NITS="10"
	AOD_POCKET_GUARD="1"
	# shellcheck disable=SC1090
	[ -f "$CONF" ] && . "$CONF"
}

load_conf
echo "$VRR_MODE" > "$PANEL/vrr_mode" 2>/dev/null || true
echo "$COLOUR_MODE" > "$PANEL/colour_mode" 2>/dev/null || true
echo "$WHITE_BALANCE_RGB" > "$PANEL/white_balance_rgb" 2>/dev/null || true
echo "$NIGHT_KELVIN" > "$PANEL/night_kelvin" 2>/dev/null || true
echo "$ACL_MODE" > "$PANEL/acl_mode" 2>/dev/null || true
echo "$AOD_NITS" > "$PANEL/aod_brightness" 2>/dev/null || true
echo "$AOD_ENABLED" > "$PANEL/aod_mode" 2>/dev/null || true

find_iio_file() {
	pattern="$1"
	for f in /sys/bus/iio/devices/iio:device*/$pattern; do
		if [ -r "$f" ]; then
			echo "$f"
			return 0
		fi
	done
	return 1
}

ALS_FILE=""
PROX_FILE=""

while true; do
	load_conf

	[ -n "$ALS_FILE" ] || ALS_FILE="$(find_iio_file 'in_illuminance_input' || find_iio_file 'in_illuminance_raw' || true)"
	[ -n "$PROX_FILE" ] || PROX_FILE="$(find_iio_file 'in_proximity_raw' || true)"

	# Auto-HBM in sunlight
	if [ "$HBM_AUTO" = "1" ] && [ -n "$ALS_FILE" ] && [ -r "$ALS_FILE" ]; then
		lux="$(cat "$ALS_FILE" 2>/dev/null | cut -d. -f1 || echo 0)"
		cur_hbm="$(cat "$PANEL/hbm_mode" 2>/dev/null || echo 0)"
		if [ "${lux:-0}" -ge "$HBM_SUNLIGHT_LUX" ] && [ "$cur_hbm" != "2" ]; then
			echo 4095 > "$PANEL/hbm_dbv" 2>/dev/null || true
			echo 2 > "$PANEL/hbm_mode" 2>/dev/null || true
		elif [ "${lux:-0}" -ge "$HBM_BOOST_LUX" ] && [ "${lux:-0}" -lt "$HBM_SUNLIGHT_LUX" ] && [ "$cur_hbm" = "0" ]; then
			echo 1 > "$PANEL/hbm_mode" 2>/dev/null || true
		elif [ "${lux:-0}" -le "$HBM_EXIT_LUX" ] && [ "$cur_hbm" != "0" ]; then
			echo 0 > "$PANEL/hbm_mode" 2>/dev/null || true
		fi
	fi

	# Pocket / face-down guard for Always-On Display
	if [ "$AOD_ENABLED" = "1" ]; then
		if [ "$AOD_POCKET_GUARD" = "1" ] && [ -n "$PROX_FILE" ] && [ -r "$PROX_FILE" ]; then
			prox="$(cat "$PROX_FILE" 2>/dev/null | cut -d. -f1 || echo 0)"
			if [ "${prox:-0}" -gt 50 ]; then
				echo 0 > "$PANEL/aod_mode" 2>/dev/null || true
			else
				echo 1 > "$PANEL/aod_mode" 2>/dev/null || true
			fi
		else
			echo 1 > "$PANEL/aod_mode" 2>/dev/null || true
		fi
	fi

	sleep 3
done
