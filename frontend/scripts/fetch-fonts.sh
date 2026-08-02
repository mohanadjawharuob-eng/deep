#!/usr/bin/env bash
#
# Refresh the self-hosted fonts in public/fonts.
#
#     cd frontend && bash scripts/fetch-fonts.sh
#
# You should not need to run this. The files are committed, because a build
# that reaches the internet is a build that fails on a machine that cannot.
# Run it only to pick up a new version of a face, or to change which weights
# and subsets are carried.
#
# All three faces are under the SIL Open Font Licence, which permits hosting
# them yourself. See public/fonts/OFL.txt.

set -euo pipefail
cd "$(dirname "$0")/.."

OUT="public/fonts"
URL="https://fonts.googleapis.com/css2?family=Source+Sans+3:ital,wght@0,300..800;1,400&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Mono:wght@400;500;600&display=swap"

# A modern user agent, or Google serves the legacy formats instead of woff2 —
# roughly three times the bytes for the same glyphs.
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

command -v python3 >/dev/null || { echo "python3 is needed for this script."; exit 1; }

mkdir -p "$OUT"
rm -f "$OUT"/*.woff2 "$OUT/fonts.css"

curl -sS -A "$UA" "$URL" -o "$OUT/.remote.css"

python3 - "$OUT" <<'PY'
import pathlib, re, subprocess, sys, urllib.parse

out = pathlib.Path(sys.argv[1])
css = (out / ".remote.css").read_text()

for url in sorted(set(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", css))):
    name = urllib.parse.urlparse(url).path.strip("/").replace("/", "-")
    subprocess.run(["curl", "-sS", "-o", str(out / name), url], check=True)
    css = css.replace(url, f"/fonts/{name}")

# Google labels each @font-face with the subset it covers. Latin and latin-ext
# carry the diacritics in transliterated site names; greek is worth keeping for
# classical material. Cyrillic and Vietnamese are weight this platform will
# never render, and every byte is one a phone on a site WiFi has to pull down.
KEEP = {"latin", "latin-ext", "greek", "greek-ext"}
kept = []
for block, subset in re.findall(r"(/\* ([a-z-]+) \*/\s*@font-face \{.*?\})", css, re.S):
    if subset in KEEP:
        kept.append(block)
    else:
        for name in re.findall(r"url\(/fonts/([^)]+)\)", block):
            (out / name).unlink(missing_ok=True)

header = """/* Self-hosted so the platform works with no internet.
 *
 * Loading these from Google blocks first paint on a request that, on a
 * site-house WiFi with no upstream, does not fail for tens of seconds —
 * during which the screen is blank and nothing says why. It is also a
 * request to a third party on every page view, which an institution
 * hosting its own records should not have to make.
 *
 * Subsets: latin, latin-ext and greek. Cyrillic and Vietnamese are
 * dropped — weight this platform will never render.
 *
 * Regenerate with scripts/fetch-fonts.sh.
 */

"""
(out / "fonts.css").write_text(header + "\n\n".join(kept) + "\n")
(out / ".remote.css").unlink()
print(f"{len(kept)} faces, {sum(f.stat().st_size for f in out.iterdir()) // 1024} KiB")
PY
