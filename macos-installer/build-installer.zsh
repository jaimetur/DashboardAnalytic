#!/bin/zsh

# Build the native macOS launcher and its installer package.
set -euo pipefail

script_dir="${0:A:h}"
project_root="${script_dir:h}"
launcher_dir="${project_root}/macos-launcher"
app_bundle="${launcher_dir}/Dashboard Analytic.app"
app_contents="${app_bundle}/Contents"
launcher_source="${launcher_dir}/DashboardAnalyticLauncher.m"
info_plist_source="${app_contents}/Info.plist"
icon_source="${app_contents}/Resources/DashboardAnalytic.icns"
launch_script_source="${app_contents}/Resources/launch-server.zsh"
app_executable="${app_contents}/MacOS/DashboardAnalyticLauncher"
output_path="${1:-${script_dir}/Dashboard Analytic Installer.pkg}"

for source_file in \
    "$launcher_source" \
    "$info_plist_source" \
    "$icon_source" \
    "$launch_script_source"; do
    if [[ ! -f "$source_file" ]]; then
        print -u2 -- "Required launcher source was not found: ${source_file}"
        exit 1
    fi
done

if [[ "${output_path:e}" != "pkg" ]]; then
    print -u2 -- "The installer output path must use the .pkg extension."
    exit 1
fi

output_directory="${output_path:h}"
if [[ ! -d "$output_directory" ]]; then
    print -u2 -- "The installer output directory does not exist: ${output_directory}"
    exit 1
fi

/usr/bin/plutil -lint "$info_plist_source" >/dev/null
bundle_version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$info_plist_source")"
temporary_directory="$(/usr/bin/mktemp -d "${TMPDIR:-/tmp}/dashboard-analytic-installer.XXXXXX")"
temporary_executable="${temporary_directory}/DashboardAnalyticLauncher"
temporary_package="${temporary_directory}/Dashboard Analytic Installer.pkg"

cleanup() {
    /bin/rm -rf -- "$temporary_directory"
}
trap cleanup EXIT INT TERM HUP

/bin/mkdir -p "${app_contents}/MacOS"

/usr/bin/clang \
    -fobjc-arc \
    -Wall \
    -Wextra \
    -Werror \
    -mmacosx-version-min=12.0 \
    -arch arm64 \
    -arch x86_64 \
    -framework Cocoa \
    "$launcher_source" \
    -o "$temporary_executable"

/bin/mv -f "$temporary_executable" "$app_executable"
/bin/chmod 755 "$app_executable" "${app_contents}/Resources/launch-server.zsh"
/usr/bin/codesign --force --sign - "$app_bundle"
/usr/bin/xattr -cr "$app_bundle"

COPYFILE_DISABLE=1 /usr/bin/pkgbuild \
    --component "$app_bundle" \
    --install-location "/Applications" \
    --identifier "com.jaimetur.dashboardanalytic.installer" \
    --version "$bundle_version" \
    "$temporary_package"

/bin/mv -f "$temporary_package" "$output_path"
print -- "Installer created at ${output_path}"
