# imagick content snap for the nextcloud snap

> [!IMPORTANT]
> **This snap exists only to provide the PHP `imagick` extension to the
> [nextcloud snap](https://github.com/nextcloud-snap/nextcloud-snap).** It
> is not a general-purpose PHP extension or ImageMagick snap. It is built
> for exactly the PHP the nextcloud snap ships (same version, PHP API and
> base), has no apps or commands of its own, and does nothing by itself.
>
> Other snaps or setups might happen to work with it, but they are **not
> supported**: please don't open issues for them. Issues with Nextcloud
> itself belong with [nextcloud-snap](https://github.com/nextcloud-snap/nextcloud-snap/issues)
> or [Nextcloud](https://github.com/nextcloud/server/issues).

It ships `imagick.so` together with a full-featured **ImageMagick 7** and
what Nextcloud's image handling needs: librsvg for SVG, libheif for
HEIC/HEIF, libtiff, webp, jpeg, png, lcms2, freetype/fontconfig, and
ghostscript for PDF/PS/AI. The admin connects the plug, and the warning
*"The PHP module imagick is not enabled although the theming app is"*
goes away.

This snap never runs PHP itself. It only hands files to the nextcloud snap
through a [content interface](https://snapcraft.io/docs/content-interface).

## Install and enable

```sh
snap install imagick          # or: snap install --dangerous ./imagick_*.snap
snap connect nextcloud:imagick imagick:php-extensions
```

To turn it back off:

```sh
snap disconnect nextcloud:imagick imagick:php-extensions
```

Connecting requires a nextcloud snap with the `imagick` plug (proposed
upstream; not in the published nextcloud snap yet). It restarts php-fpm
on connect and disconnect, and when this snap refreshes (for example, to
an ImageMagick security release) its php-fpm notices within a minute and
reloads gracefully, so the new ImageMagick is actually used.

## What the nextcloud snap gets

Everything is mounted under the nextcloud snap's plug target,
`$SNAP/extensions`:

```
extensions/php/extensions/no-debug-non-zts-20240924/imagick.so
extensions/usr/lib/                       ImageMagick 7 + dependency libs
extensions/usr/lib/<arch-triplet>/        dependency libs (e.g. x86_64-linux-gnu)
extensions/usr/etc/ImageMagick-7/         policy.xml (stock), delegates.xml, ...
extensions/usr/etc/ImageMagick-7-limited/ same, with ImageMagick's "limited" policy
extensions/usr/bin/gs                     ghostscript
extensions/usr/share/ghostscript/...      gs Resource tree
```

The nextcloud snap's PHP wrappers point PHP at the extension and give
ImageMagick/ghostscript their paths, roughly:

```sh
# Append, don't prepend: nextcloud's own copies of shared libraries
# (libxml2, ICU, freetype, ...) should keep winning.
LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$SNAP/extensions/usr/lib:$SNAP/extensions/usr/lib/<arch-triplet>"
PATH="$PATH:$SNAP/extensions/usr/bin"
MAGICK_CONFIGURE_PATH="$SNAP/extensions/usr/etc/ImageMagick-7"
GS_LIB="$SNAP/extensions/usr/share/ghostscript/<ver>/Resource/Init"
php -d extension="$SNAP/extensions/php/extensions/no-debug-non-zts-20240924/imagick.so" ...
```

(The nextcloud snap cannot edit its own `php.ini`, so its `php` wrapper and
`php-fpm` launcher add the `-d extension=...` flag when the plugin is
connected.)

## ABI

`imagick.so` is built against **PHP 8.4.27** headers — PHP API
**20240924**, **non-ZTS**. It uses the exact same PHP source tarball (and
checksum) the nextcloud snap builds its PHP from. PHP on any other API
will not load it; that's deliberate, since this snap is matched to the
nextcloud snap and nothing else.

Versions in this build: **imagick 3.8.1**, **ImageMagick 7.1.2-34**
(Q16-HDRI), **ghostscript 9.55.0** (from core22/jammy). The snap version
spells out all three pins: `3.8.1+im7.1.2-34+php8.4.27`.

The libraries are built on **core22**, so the nextcloud snap must be on
core22 too. That means nextcloud **track 34 and later**: the `33`
track also runs PHP 8.4, but on core20, so `imagick.so` would fail to load
there (PHP prints a warning and carries on without it).

The extension sits in a directory named after the PHP API it was built
for (`no-debug-non-zts-<API>`, the same name PHP uses for its own
extension dir), so the nextcloud snap can look up the build matching
*its* PHP and simply skip loading when there is none.

## Security

This is a manual opt-in. ImageMagick parses many complex, untrusted
image formats and has a long CVE history. `imagick.so` runs inside
Nextcloud's PHP with the nextcloud snap's privileges, so this snap's own
confinement does not isolate it. Connecting the plug is a deliberate risk
decision by the Nextcloud admin:

- ImageMagick ships its **stock** `policy.xml` by default.
- A stricter config dir, `usr/etc/ImageMagick-7-limited`, carries
  ImageMagick's own "limited" policy (resource limits; no reading of
  MSL/MVG/PDF/PS/SVG/TXT/URL/XPS, `@file`s, pipes or `/etc`). Nothing uses
  it by default; the nextcloud snap could point `MAGICK_CONFIGURE_PATH`
  at it. Note
  that it also blocks SVG, so Nextcloud's theming favicons stop working.
- ImageMagick is built **without OpenMP**, which does not mix well with
  php-fpm's forked workers.
- Disconnecting the plug or removing this snap stops *future* exposure.
  It does **not** undo a compromise that happened while it was connected.
- Nextcloud keeps most preview providers off until the admin lists them in
  `enabledPreviewProviders`, which is a second, independent opt-in.

## Build

```sh
snapcraft pack            # or: snapcraft --use-lxd pack
```

## CI and releases

All in `.github/workflows/`. Store releases are off until the repository
variable `IMAGICK_STORE_PUBLISH` is `true`, and need the
`SNAPCRAFT_STORE_CREDENTIALS` secret. There is no candidate or testing step:
this snap is locked to the PHP that nextcloud ships on stable, so releases go
straight to **stable** once the smoke test against that nextcloud passes.

- **Snap Builds** (`snap-builds.yml`): every push/PR to `main` builds
  amd64 and arm64, runs the store's review-tools, and runs
  `.github/tests/smoke-test.sh` in a jammy LXD container against the nextcloud
  snap **as published on `latest/stable`**: it checks that our extension
  dir matches nextcloud's PHP API and that PNG/WebP/TIFF/SVG/HEIC/PDF
  work through nextcloud's own PHP. When the published nextcloud snap has
  the `imagick` plug, it tests through a real `snap connect` instead.
- **Publish** (`publish.yml`): after a green Snap Builds run on `main`,
  releases *those exact* snaps (the run's artifacts, not a rebuild) to
  `stable`.
- **Security Rebuild** (`security-rebuild.yml`): daily
  `review-tools.snap-check-notices` on the stable snap (Ubuntu USNs for
  the bundled jammy packages: librsvg, libheif, libtiff, ghostscript...).
  On a hit, it rebuilds the release commit through Snap Builds and releases
  it to `stable`, but only if the rebuild actually clears notices.
- **Track Upstream** (`track-upstream.yml`): daily, compares our pins
  with the PHP the nextcloud snap builds on `master` (what feeds
  `latest/stable`), its base, and the latest ImageMagick and imagick
  releases. ImageMagick and imagick releases, and PHP patch releases,
  are committed straight to `main` with new checksums; Snap Builds runs
  on that, and a green run releases to stable. A PHP *minor* bump (new
  PHP API), a base change, or nextcloud-snap's `develop` moving ahead of
  `master` becomes an issue instead, because this snap and nextcloud must
  switch together. ImageMagick is self-built, so the store's notice check
  doesn't cover it; this tracker is what picks up its security releases.

`snap/snapcraft.yaml` builds ImageMagick, ghostscript's runtime and the
`imagick` extension from pinned upstream tarballs (PHP is a build-time
tool only and is not primed). See the no-top-level-`CMakeLists.txt`,
`PKG_CONFIG_PATH`, `-L/usr/lib` and `png16malpha`/ghostscript comments in
the yaml for the non-obvious bits.

## Licensing

- imagick: PHP License 3.01.
- ImageMagick: ImageMagick License.
- Bundled runtime libraries (librsvg, libheif, libtiff, libwebp, lcms2,
  freetype, fontconfig, ...) keep their own licenses (mostly LGPL/BSD/zlib).
- ghostscript is AGPL-3.0; it is included as a separate program, invoked
  by ImageMagick's `gs` delegate.
