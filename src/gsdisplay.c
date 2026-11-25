/* SPDX-License-Identifier: GPL-3.0-only */
/*
 * gsdisplay.so: LD_PRELOAD helper that gsfix.so hands to the game when it lies next to it (the
 * lutris.net scripts put it there). One job: point DISPLAY back to Gamescope's X server.
 *
 * In Lutris' Flatpak, Proton runs through umu in the Steam Runtime, which pressure-vessel starts in
 * a Flatpak sub-sandbox. Flatpak sets DISPLAY (and WAYLAND_DISPLAY) there to the desktop's, so Wine
 * opened its windows on the desktop beside an empty Gamescope window. STEAM_GAME_DISPLAY_0, which
 * Gamescope sets for the game to its own X server, reaches the sub-sandbox unchanged; this copies it
 * back to DISPLAY when a process starts, before Wine connects to X. The X server is reachable there
 * through its abstract socket (the sub-sandbox shares the network namespace).
 *
 * Without STEAM_GAME_DISPLAY_0, or where DISPLAY already matches it, nothing changes. 32-bit
 * processes cannot load it (the loader says "wrong ELF class" and goes on); they inherit DISPLAY from
 * the 64-bit Wine process that starts them.
 *
 * Build: gcc -O2 -Wall -shared -fPIC -o gsdisplay.so gsdisplay.c
 */
#include <stdlib.h>
#include <string.h>

__attribute__((constructor)) static void init(void) {
    const char *game = getenv("STEAM_GAME_DISPLAY_0"), *cur = getenv("DISPLAY");
    if (game && *game && (!cur || strcmp(cur, game) != 0)) setenv("DISPLAY", game, 1);
}
