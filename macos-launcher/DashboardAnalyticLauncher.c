#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main(int argc, char *argv[]) {
    (void)argc;

    char executable_path[PATH_MAX];
    if (realpath(argv[0], executable_path) == NULL) {
        perror("Unable to resolve Dashboard Analytic launcher path");
        return EXIT_FAILURE;
    }

    char *macos_directory = executable_path;
    for (char *cursor = executable_path; *cursor != '\0'; cursor++) {
        if (*cursor == '/') {
            macos_directory = cursor;
        }
    }
    *macos_directory = '\0';

    char launch_script[PATH_MAX];
    if (snprintf(
            launch_script,
            sizeof(launch_script),
            "%s/../Resources/launch-server.zsh",
            executable_path
        ) >= (int)sizeof(launch_script)) {
        fputs("Dashboard Analytic launch path is too long.\n", stderr);
        return EXIT_FAILURE;
    }

    char *arguments[] = {"zsh", launch_script, NULL};
    execv("/bin/zsh", arguments);
    perror("Unable to start Dashboard Analytic");
    return EXIT_FAILURE;
}
