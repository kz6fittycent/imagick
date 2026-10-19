#!/usr/bin/env python3
"""Compare this snap's pins with upstream, and bump them when they move.

Run by track-upstream.yml from the repository root. Upstream is:

- the nextcloud snap's PHP tarball (URL + checksum) and base, on the
  nextcloud-snap branch that feeds latest/stable (master). imagick.so has to
  be built against exactly that PHP;
- the latest ImageMagick and imagick (PHP extension) releases on GitHub.

On a change, it rewrites snap/snapcraft.yaml and README.md in place
(sources, checksums, version strings, the `craftctl set version=` line) and
writes a PR title and body. Things that need a person - nextcloud changing
its base, or nextcloud-snap's develop branch running ahead of master on PHP
minor version or base - become issues instead (issues.json), because the
build and the consumer have to move together there.

Outputs (in $GITHUB_OUTPUT): changed=true|false, title=..., and the files
pr-body.md and issues.json. Standard library only.
"""

import hashlib
import json
import os
import re
import sys
import urllib.request

SNAPCRAFT = "snap/snapcraft.yaml"
README = "README.md"
NC_YAML = "https://raw.githubusercontent.com/nextcloud-snap/nextcloud-snap/{branch}/snap/snapcraft.yaml"

PHP_RE = re.compile(
    r"(?P<url>https://www\.php\.net/distributions/php-(?P<version>[0-9.]+)\.tar\.bz2)\s*\n"
    r"\s*source-checksum: sha256/(?P<sha>[0-9a-f]{64})"
)
IM_RE = re.compile(
    r"(?P<url>https://github\.com/ImageMagick/ImageMagick/archive/refs/tags/(?P<version>[0-9][0-9.-]*)\.tar\.gz)\s*\n"
    r"\s*source-checksum: sha256/(?P<sha>[0-9a-f]{64})"
)
EXT_RE = re.compile(
    r"(?P<url>https://github\.com/Imagick/imagick/archive/refs/tags/(?P<version>[0-9][0-9.]*)\.tar\.gz)\s*\n"
    r"\s*source-checksum: sha256/(?P<sha>[0-9a-f]{64})"
)
BASE_RE = re.compile(r"^base:\s*(\S+)", re.M)
VERSION_LINE_RE = re.compile(r'craftctl set version="[^"]*"')


def fetch(url, accept=None):
    headers = {"User-Agent": "imagick-snap-track-upstream"}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
        return r.read()


def sha256_of(url):
    return hashlib.sha256(fetch(url)).hexdigest()


def latest_release(repo):
    data = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest", "application/vnd.github+json"))
    return data["tag_name"]


def must_match(regex, text, what):
    m = regex.search(text)
    if not m:
        sys.exit(f"Can't find the {what} pin")
    return m


def minor(version):
    return ".".join(version.split(".")[:2])


def replace_version(text, old, new):
    """Replace a version string, but not as part of a longer version."""
    return re.sub(rf"(?<![0-9.]){re.escape(old)}(?![0-9])", new, text)


def main():
    yaml = open(SNAPCRAFT).read()
    readme = open(README).read()

    ours = {
        "php": must_match(PHP_RE, yaml, "PHP"),
        "im": must_match(IM_RE, yaml, "ImageMagick"),
        "ext": must_match(EXT_RE, yaml, "imagick"),
    }
    our_base = must_match(BASE_RE, yaml, "base").group(1)

    nc = {}
    for branch in ("master", "develop"):
        text = fetch(NC_YAML.format(branch=branch)).decode()
        php = must_match(PHP_RE, text, f"nextcloud-snap {branch} PHP")
        nc[branch] = {
            "php": php.group("version"),
            "php_url": php.group("url"),
            "php_sha": php.group("sha"),
            "base": must_match(BASE_RE, text, f"nextcloud-snap {branch} base").group(1),
        }

    print(f"ours:    PHP {ours['php']['version']}, ImageMagick {ours['im']['version']}, "
          f"imagick {ours['ext']['version']}, {our_base}")
    for branch, info in nc.items():
        print(f"{branch}: PHP {info['php']}, {info['base']} (nextcloud-snap)")

    issues = []
    master = nc["master"]
    develop = nc["develop"]

    if master["base"] != our_base:
        issues.append({
            "title": f"nextcloud snap moved to {master['base']}",
            "body": (
                f"nextcloud-snap `master` (which feeds `latest/stable`) is now on **{master['base']}**; "
                f"this snap is built on **{our_base}**. Its libraries won't load in a different base, "
                "so the build has to move to the same base (build-packages, stage-packages, and the "
                "ghostscript version all change with it). This needs a person; the daily tracker "
                "won't open a pin-bump PR until the bases match again.\n\n"
                "_Opened automatically by `track-upstream.yml`._"
            ),
        })

    if develop["base"] != master["base"] or minor(develop["php"]) != minor(master["php"]):
        issues.append({
            "title": f"Heads-up: nextcloud-snap develop is on PHP {develop['php']} / {develop['base']}",
            "body": (
                f"nextcloud-snap `develop` is on PHP **{develop['php']}** / **{develop['base']}**, "
                f"while `master` (what `latest/stable` is built from) is on PHP **{master['php']}** / "
                f"**{master['base']}**.\n\n"
                "When that reaches master, this snap needs a build for the new PHP API (and/or base) "
                "released at the same time as nextcloud's, or imagick will stop loading for its users "
                "until it catches up (it fails safe: the admin warning just comes back). Plan the "
                "switch now.\n\n"
                "_Opened automatically by `track-upstream.yml`._"
            ),
        })

    changes = []
    if master["base"] == our_base:
        new = {
            "php": (master["php"], master["php_url"], master["php_sha"]),
        }
        im_tag = latest_release("ImageMagick/ImageMagick")
        ext_tag = latest_release("Imagick/imagick")
        new["im"] = (im_tag, f"https://github.com/ImageMagick/ImageMagick/archive/refs/tags/{im_tag}.tar.gz", None)
        new["ext"] = (ext_tag, f"https://github.com/Imagick/imagick/archive/refs/tags/{ext_tag}.tar.gz", None)

        names = {"php": "PHP", "im": "ImageMagick", "ext": "imagick"}
        for key, (version, url, sha) in new.items():
            old = ours[key]
            if version == old.group("version"):
                continue
            sha = sha or sha256_of(url)
            changes.append((key, names[key], old.group("version"), version))
            yaml = yaml.replace(old.group("url"), url).replace(old.group("sha"), sha)
            # The same version string is used throughout (comments, the
            # store description, the README), so replace it everywhere.
            yaml = replace_version(yaml, old.group("version"), version)
            readme = replace_version(readme, old.group("version"), version)

    if changes:
        php = must_match(PHP_RE, yaml, "PHP").group("version")
        im = must_match(IM_RE, yaml, "ImageMagick").group("version")
        ext = must_match(EXT_RE, yaml, "imagick").group("version")
        snap_version = f"{ext}+im{im}+php{php}"
        if len(snap_version) > 32:
            sys.exit(f"Snap version {snap_version!r} is longer than the store's 32 characters")
        yaml = VERSION_LINE_RE.sub(f'craftctl set version="{snap_version}"', yaml)
        open(SNAPCRAFT, "w").write(yaml)
        open(README, "w").write(readme)

    summary = ", ".join(f"{name} {old} → {new}" for _, name, old, new in changes)
    title = f"Track upstream: {summary}" if changes else ""

    body = []
    if changes:
        body.append("Daily `track-upstream.yml` found new upstream versions:\n")
        for key, name, old, new in changes:
            body.append(f"- **{name}**: {old} → {new}")
        body.append("")
        body.append("Sources, checksums, docs and the snap version are updated. "
                    "Snap Builds runs on this branch (build, review-tools, smoke test against "
                    "nextcloud `latest/stable`); merging releases it to stable.")
        php_change = next((c for c in changes if c[0] == "php"), None)
        if php_change and minor(php_change[2]) != minor(php_change[3]):
            body.append("")
            body.append(
                f"> [!WARNING]\n> PHP **minor** version change ({php_change[2]} → {php_change[3]}): that's a new "
                "PHP API, so `imagick.so` moves to a new `no-debug-non-zts-<API>` dir and the README's API "
                "number needs a manual update. Don't merge this (merging releases it) until nextcloud's `latest/stable` ships "
                "the same PHP; until then the smoke test fails on purpose (API mismatch), and releasing "
                "would drop imagick for everyone still on the old PHP."
            )
        if any(c[0] == "im" for c in changes):
            body.append("")
            body.append("ImageMagick is self-built, so its security fixes only reach users through bumps "
                        "like this one; check its [changelog](https://github.com/ImageMagick/ImageMagick/releases) "
                        "for CVEs and release promptly if there are any.")
        body.append("\n---\n_Opened automatically by `track-upstream.yml`._")
    open("pr-body.md", "w").write("\n".join(body) + "\n")
    json.dump(issues, open("issues.json", "w"), indent=2)

    out = os.environ.get("GITHUB_OUTPUT")
    lines = [f"changed={'true' if changes else 'false'}", f"title={title}"]
    if out:
        with open(out, "a") as f:
            f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"{len(issues)} issue(s) to raise")


if __name__ == "__main__":
    main()
