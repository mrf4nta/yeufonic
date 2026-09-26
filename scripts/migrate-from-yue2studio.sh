#!/usr/bin/env sh
# Move a YuE2 Studio setup into this Yeufonic clone.
#
# Yeufonic is YuE2 Studio renamed.  A Docker setup keeps everything that is yours in
# folders beside compose.yml, so moving over is moving those folders:
#
#   data/                  the library: takes, sources, stems, corpora, settings
#   models/                the models, LoRAs included
#   engine-state/          ComfyUI's input, output and user folders
#   compose.override.yml   your own settings, if you made one
#
# Inside the containers the library is always /data, so nothing in it needs changing.
# The engine image (about 15 GB, the same engine) is tagged with its new name, so the
# first start does not rebuild it; --rebuild leaves that out.  The app image is small
# and carries the version shown in the header, so it is built afresh.
#
#   docker compose -p yue2studio down        (in the old folder: stop YuE2 Studio first)
#   sh scripts/migrate-from-yue2studio.sh ~/YuE2gen-studio
#   docker compose up
set -eu

usage() { echo "usage: sh scripts/migrate-from-yue2studio.sh <YuE2 Studio folder> [--rebuild]" >&2; exit 2; }
[ $# -ge 1 ] || usage
OLD=$(CDPATH= cd -- "$1" 2>/dev/null && pwd) || { echo "No folder at $1." >&2; exit 1; }
REBUILD=0
[ "${2:-}" = "--rebuild" ] && REBUILD=1
NEW=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

[ "$OLD" != "$NEW" ] || { echo "That is this folder. Give the YuE2 Studio one." >&2; exit 1; }
[ -f "$OLD/compose.yml" ] && grep -q "yue2studio" "$OLD/compose.yml" \
    || { echo "$OLD does not look like YuE2 Studio: its compose.yml does not name yue2studio." >&2; exit 1; }

# A library in use must not be moved: SQLite may be halfway through a write.
if command -v docker >/dev/null 2>&1 \
    && [ -n "$(docker ps -q --filter "label=com.docker.compose.project.working_dir=$OLD")" ]; then
    echo "YuE2 Studio is running. Stop it first:  (cd $OLD && docker compose down)" >&2
    exit 1
fi

# Moved, not merged: a library already here would be half of two.
for d in data models engine-state; do
    if [ -d "$NEW/$d" ] && [ -n "$(ls -A "$NEW/$d" 2>/dev/null)" ]; then
        echo "$NEW/$d already has something in it. Move it aside first, so nothing is mixed." >&2
        exit 1
    fi
done
if [ -f "$NEW/compose.override.yml" ] && [ -f "$OLD/compose.override.yml" ]; then
    echo "$NEW/compose.override.yml already exists. Move it aside first." >&2
    exit 1
fi

moved=""
for d in data models engine-state; do
    if [ -d "$OLD/$d" ]; then
        rmdir "$NEW/$d" 2>/dev/null || true
        mv "$OLD/$d" "$NEW/$d"
        moved="$moved $d/"
    fi
done
if [ -f "$OLD/compose.override.yml" ]; then
    mv "$OLD/compose.override.yml" "$NEW/compose.override.yml"
    moved="$moved compose.override.yml"
fi
echo "Moved from $OLD:$moved"

if [ "$REBUILD" = 0 ] && command -v docker >/dev/null 2>&1 \
    && docker image inspect yue2studio-engine:latest >/dev/null 2>&1 \
    && ! docker image inspect yeufonic-engine:latest >/dev/null 2>&1; then
    docker tag yue2studio-engine:latest yeufonic-engine:latest
    echo "The engine image is reused, as yeufonic-engine."
fi

echo
echo "Now start Yeufonic here:  cd $NEW && docker compose up"
echo "The YuE2 Studio folder can go once Yeufonic has started with your library."
