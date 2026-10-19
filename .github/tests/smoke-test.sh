#!/bin/bash
# Smoke test for the imagick content snap against the *published* nextcloud
# snap. Runs as root inside a throwaway Ubuntu 22.04 (jammy = core22) LXD
# container; snap-builds.yml sets that up.
#
#   smoke-test.sh <imagick.snap> [<smoke.php>]
#
# NEXTCLOUD_CHANNEL picks the nextcloud snap to test against (default
# latest/stable, i.e. what admins actually run).
#
# If that nextcloud snap has the `imagick` content plug, this tests the real
# thing: snap connect, then nextcloud's own (confined) PHP wrapper. Until
# the plug lands upstream it falls back to running nextcloud's php.bin
# directly with the environment the plug would set up, which still checks
# the part that can drift: our extension against nextcloud's PHP build.
set -euo pipefail

snap_file="$1"
smoke_php="${2:-$(dirname "$0")/smoke.php}"
channel="${NEXTCLOUD_CHANNEL:-latest/stable}"

fail() { echo "::error::$*"; exit 1; }

snap wait system seed.loaded
snap install --dangerous "$snap_file"
if ! snap list nextcloud >/dev/null 2>&1; then
	# Retried: the Snap Store's CDN has had transient failures.
	for attempt in 1 2 3; do
		snap install nextcloud --channel="$channel" && break
		[[ "$attempt" == 3 ]] && fail "snap install nextcloud failed"
		sleep 30
	done
fi

nc=/snap/nextcloud/current
ext=/snap/imagick/current/extensions
version="$(sed -n 's/^version: *//p' /snap/imagick/current/meta/snap.yaml | tr -d "'\"")"
echo "imagick snap ${version}; nextcloud $(snap list nextcloud | awk 'NR==2 {print $2, "rev", $3}') from ${channel}"

# The versions smoke.php should report, from <imagick>+im<IM>+php<PHP>.
export EXPECT_IMAGICK_VERSION="${version%%+*}"
im_version="${version#*+im}"
export EXPECT_IM_VERSION="${im_version%%+*}"

# Lockstep checks: same base, and a build for nextcloud's PHP API.
nc_base="$(sed -n 's/^base: *//p' "$nc/meta/snap.yaml")"
our_base="$(sed -n 's/^base: *//p' /snap/imagick/current/meta/snap.yaml)"
[[ "$nc_base" == "$our_base" ]] || fail "nextcloud is on ${nc_base}, this snap is built on ${our_base}"

api_dir=""
for dir in "$nc"/lib/php/extensions/no-debug-non-zts-*; do
	api_dir="$(basename "$dir")"
done
[[ -n "$api_dir" ]] || fail "can't find nextcloud's PHP extension dir"
extension="$ext/php/extensions/$api_dir/imagick.so"
[[ -f "$extension" ]] || fail "nextcloud's PHP wants ${api_dir}, this snap ships: $(ls "$ext/php/extensions")"

nc_libs="$nc/lib:$nc/usr/lib:$nc/usr/lib/$(uname -m)-linux-gnu"
nc_php="$(LD_LIBRARY_PATH="$nc_libs" "$nc/bin/php.bin" -n -r 'echo PHP_VERSION;' 2>/dev/null || true)"
our_php="${version##*+php}"
echo "PHP: nextcloud ${nc_php:-?}, built against ${our_php}, API dir ${api_dir}"
if [[ -n "$nc_php" && "$nc_php" != "$our_php" ]]; then
	echo "::warning::nextcloud runs PHP ${nc_php} but this snap was built against ${our_php} (same API, so it loads)"
fi

has_plug="$(python3 -c 'import sys, yaml; print("imagick" in (yaml.safe_load(open(sys.argv[1])).get("plugs") or {}))' "$nc/meta/snap.yaml")"

if [[ "$has_plug" == "True" ]]; then
	echo "=== nextcloud has the imagick plug: testing through snap connect"
	snap connect nextcloud:imagick imagick:php-extensions
	cp "$smoke_php" /var/snap/nextcloud/common/smoke.php
	snap run --shell nextcloud.occ -c \
		"\$SNAP/bin/php -m | grep -qx imagick && EXPECT_IMAGICK_VERSION='${EXPECT_IMAGICK_VERSION}' EXPECT_IM_VERSION='${EXPECT_IM_VERSION}' \$SNAP/bin/php \$SNAP_COMMON/smoke.php"
else
	echo "=== nextcloud has no imagick plug yet: testing nextcloud's php.bin directly"
	# Same environment the nextcloud snap's imagick-utilities sets up when
	# the plug is connected (nextcloud's own libraries first).
	ld_path="$nc_libs:$ext/usr/lib"
	for libdir in "$ext"/usr/lib/*-linux-gnu; do
		ld_path="$ld_path:$libdir"
	done
	gs_lib=""
	for resource in "$ext"/usr/share/ghostscript/*/Resource/Init; do
		gs_lib="$resource"
	done
	env SNAP="$nc" \
		PHP_MEMORY_LIMIT=512M PHP_EXPOSE_PHP=Off PHP_APC_SHM_SIZE=32M \
		LD_LIBRARY_PATH="$ld_path" \
		PATH="$PATH:$ext/usr/bin" \
		MAGICK_CONFIGURE_PATH="$ext/usr/etc/ImageMagick-7" \
		MAGICK_THREAD_LIMIT=1 \
		GS_LIB="$gs_lib" \
		"$nc/bin/php.bin" -c "$nc/config/php" \
		-d extension="$extension" -d imagick.shutdown_sleep_count=0 \
		"$smoke_php"
fi
echo "=== smoke test passed"
