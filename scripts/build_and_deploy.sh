#!/bin/bash
# SPDX-FileCopyrightText: 2026 Greg Pfountz
# SPDX-License-Identifier: GPL-3.0-only
# See LICENSE for license terms and the warranty disclaimer.

# Build, verify, and install Sudoku using this checkout's virtual environment.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
release_dir="${SUDOKU_RELEASE_DIR:-}"
applications_dir="${SUDOKU_APPLICATIONS_DIR:-$HOME/Applications}"
installed_bundle="$applications_dir/Sudoku.app"
extraction_dir=""
installation_dir=""
replacement_started=0

cleanup() {
    # Restore the prior bundle on failure and discard temporary staging directories.
    local cleanup_status=$?
    trap - EXIT
    if [[ "$cleanup_status" -ne 0 ]]; then
        if [[ -n "$installation_dir" && -e "$installation_dir/previous.app" ]]; then
            if ! rm -rf "$installed_bundle" ||
                ! mv "$installation_dir/previous.app" "$installed_bundle"; then
                printf 'Could not restore Sudoku. Previous app retained at: %s\n' \
                    "$installation_dir/previous.app" >&2
                exit 1
            fi
        elif [[ "$replacement_started" -eq 1 ]]; then
            rm -rf "$installed_bundle"
        fi
    fi
    if [[ -n "$installation_dir" ]]; then
        rm -rf "$installation_dir"
    fi
    if [[ -n "$extraction_dir" ]]; then
        rm -rf "$extraction_dir"
    fi
    exit "$cleanup_status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cd "$project_dir"
if [[ ! -x .venv/bin/python ]]; then
    printf 'Create the project .venv and install requirements-dev.txt before building.\n' >&2
    exit 1
fi

if [[ -z "$release_dir" ]]; then
    release_dir="$(mktemp -d /private/tmp/sudoku-release.XXXXXX)"
fi
release_dir="$(.venv/bin/python -m sudoku.build_paths "$release_dir")"
applications_dir="$(.venv/bin/python -m sudoku.build_paths "$applications_dir")"
installed_bundle="$applications_dir/Sudoku.app"

.venv/bin/python scripts/build_app.py --output-dir "$release_dir"
extraction_dir="$(mktemp -d /private/tmp/sudoku-extracted.XXXXXX)"
ditto -x -k "$release_dir/Sudoku.zip" "$extraction_dir"
codesign --verify --deep --strict "$extraction_dir/Sudoku.app"

# Stage on the destination filesystem so installation uses a directory rename.
mkdir -p "$applications_dir"
installation_dir="$(mktemp -d "$applications_dir/.sudoku-install.XXXXXX")"
ditto --norsrc "$extraction_dir/Sudoku.app" "$installation_dir/Sudoku.app"
codesign --verify --deep --strict "$installation_dir/Sudoku.app"

if [[ -e "$installed_bundle" ]]; then
    # Resolve the installed path at runtime and let the app flush its progress.
    # Stop if quitting is cancelled or stalls; first installs need no quit request.
    osascript - "$installed_bundle" <<'APPLESCRIPT'
on run arguments
    set sudoku_app_path to item 1 of arguments
    if application sudoku_app_path is running then
        tell application sudoku_app_path to quit
        repeat 100 times
            if not (application sudoku_app_path is running) then exit repeat
            delay 0.1
        end repeat
        if application sudoku_app_path is running then
            error "Sudoku is still running. Quit it before deploying."
        end if
    end if
end run
APPLESCRIPT
    mv "$installed_bundle" "$installation_dir/previous.app"
fi
replacement_started=1
mv "$installation_dir/Sudoku.app" "$installed_bundle"
codesign --verify --deep --strict "$installed_bundle"

printf 'Installed: %s\nBuild archive: %s\n' "$installed_bundle" "$release_dir/Sudoku.zip"
