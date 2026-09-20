#!/bin/zsh

# Build a standard macOS installer that places the application in /Applications.
set -euo pipefail

script_dir="${0:A:h}"
project_root="${script_dir:h}"
app_bundle="${project_root}/Dashboard Analytic.app"
output_path="${1:-${project_root}/Dashboard Analytic Installer.pkg}"

if [[ ! -d "$app_bundle" ]]; then
    print -u2 -- "Dashboard Analytic.app was not found at ${app_bundle}."
    exit 1
fi

if [[ "${output_path:e}" != "pkg" ]]; then
    print -u2 -- "The installer output path must use the .pkg extension."
    exit 1
fi

output_directory="${output_path:h}"
if [[ ! -d "$output_directory" ]]; then
    print -u2 -- "The installer output directory does not exist: ${output_directory}"
    exit 1
fi

bundle_version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "${app_bundle}/Contents/Info.plist")"
temporary_directory="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/dashboard-analytic-installer.XXXXXX")"
temporary_package="${temporary_directory}/Dashboard Analytic Installer.pkg"

cleanup() {
    /bin/rm -rf "$temporary_directory"
}
trap cleanup EXIT INT TERM HUP

/usr/bin/pkgbuild \
    --component "$app_bundle" \
    --install-location "/Applications" \
    --identifier "com.jaimetur.dashboardanalytic.installer" \
    --version "$bundle_version" \
    "$temporary_package"

/bin/mv -f "$temporary_package" "$output_path"
print -- "Installer created at ${output_path}"
