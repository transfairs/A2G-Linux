/* SPDX-License-Identifier: GPL-3.0-only */
/*
 * gsfix.so: LD_PRELOAD add-on for Gamescope (Wayland backend, GNOME). Three jobs:
 *
 * 1. Keep clicks on the window frame away from the game (always active).
 * 2. GSFIX_WMNAME: Gamescope registers with X as window manager "steamcompmgr". Proton detects
 *    that name and removes all window frames (a Steam Deck hack), so the game's dialogs have no
 *    title bar. With a different name the hack does not apply.
 * 3. GSFIX_TITLE / GSFIX_APPID: title and app ID of the Gamescope window (instead of the game's
 *    title or "gamescope"). The app ID links the window to its .desktop file in GNOME (name, icon).
 *    GSFIX_APPID may be a pattern such as "net.lutris.anstoss-2-gold-[0-9]*": it is matched against
 *    the .desktop files in the applications folders and replaced by the first match, since the
 *    Lutris game ID in the file name is not known in advance. Without a match, nothing changes.
 *    Title and app ID are sent again whenever Gamescope commits its window surface without a
 *    buffer: GNOME (Mutter) then replaces the window by a new one without title and app ID, and
 *    the dock showed a generic icon instead of the one from the .desktop file.
 *
 * About 1: Gamescope forwards every mouse click to the game, including clicks on the window
 * frame or title bar (libdecor). When the frame is dragged, GNOME takes over the mouse and the
 * button release never reaches Gamescope. For the game the left button then stays pressed
 * and all further clicks are lost.
 *
 * Fix: Gamescope's pointer events are intercepted. Buttons are passed on only while the
 * pointer is over the game surface (the surface with the Gamescope tag "gamescope-toplevel").
 * Everything else is left unchanged.
 *
 * Only takes effect in the Gamescope process itself and removes itself from LD_PRELOAD there,
 * so that Xwayland, Wine and the game do not inherit it.
 *
 * Build: gcc -O2 -Wall -shared -fPIC -o gsfix.so gsfix.c -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <glob.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client-core.h>
#include <wayland-client-protocol.h>

static int active;
static const char *opt_title, *opt_appid, *opt_wmname;

/* Desktop file ID for an app ID pattern (see 3.), or NULL. */
static char *resolve_appid(const char *pat) {
    if (!pat || !*pat) return NULL;
    if (!strpbrk(pat, "*?[")) return strdup(pat);
    const char *home = getenv("HOME"), *dh = getenv("XDG_DATA_HOME"), *dd = getenv("XDG_DATA_DIRS");
    char dirs[4096];
    if (dh && *dh) snprintf(dirs, sizeof dirs, "%s:%s", dh, dd && *dd ? dd : "/usr/local/share:/usr/share");
    else snprintf(dirs, sizeof dirs, "%s/.local/share:%s", home ? home : "", dd && *dd ? dd : "/usr/local/share:/usr/share");
    char *res = NULL;
    for (char *save, *d = strtok_r(dirs, ":", &save); d && !res; d = strtok_r(NULL, ":", &save)) {
        char full[4352];
        snprintf(full, sizeof full, "%s/applications/%s.desktop", d, pat);
        glob_t g;
        if (glob(full, 0, NULL, &g) == 0 && g.gl_pathc > 0) {
            const char *base = strrchr(g.gl_pathv[0], '/') + 1;
            res = strndup(base, strlen(base) - strlen(".desktop"));
        }
        globfree(&g);
    }
    return res;
}

__attribute__((constructor)) static void init(void) {
    char exe[512];
    ssize_t n = readlink("/proc/self/exe", exe, sizeof exe - 1);
    if (n <= 0) return;
    exe[n] = 0;
    const char *base = strrchr(exe, '/');
    base = base ? base + 1 : exe;
    if (strcmp(base, "gamescope") != 0) return;
    active = 1;
    opt_title = getenv("GSFIX_TITLE");
    opt_appid = resolve_appid(getenv("GSFIX_APPID"));
    opt_wmname = getenv("GSFIX_WMNAME");
    unsetenv("LD_PRELOAD");
}

/* Gamescope binds wl_seat at version 8: events enter .. axis_value120 (10 of them). */
#define NCB 10
typedef void (*cb_t)(void);

/* wl_pointer_listener as of wl_pointer version 9 (libwayland 1.22). Own copy, since older headers
 * (e.g. 1.20 of Ubuntu 22.04, where the release build runs) lack the last two members; the order
 * of the members is that of the protocol's events and does not change. */
struct pointer_listener {
    void (*enter)(void *, struct wl_pointer *, uint32_t, struct wl_surface *, wl_fixed_t, wl_fixed_t);
    void (*leave)(void *, struct wl_pointer *, uint32_t, struct wl_surface *);
    void (*motion)(void *, struct wl_pointer *, uint32_t, wl_fixed_t, wl_fixed_t);
    void (*button)(void *, struct wl_pointer *, uint32_t, uint32_t, uint32_t, uint32_t);
    void (*axis)(void *, struct wl_pointer *, uint32_t, uint32_t, wl_fixed_t);
    void (*frame)(void *, struct wl_pointer *);
    void (*axis_source)(void *, struct wl_pointer *, uint32_t);
    void (*axis_stop)(void *, struct wl_pointer *, uint32_t, uint32_t);
    void (*axis_discrete)(void *, struct wl_pointer *, uint32_t, int32_t);
    void (*axis_value120)(void *, struct wl_pointer *, uint32_t, int32_t);
    void (*axis_relative_direction)(void *, struct wl_pointer *, uint32_t, uint32_t);
};

struct ctx {
    const struct pointer_listener *orig;
    void *data;
    int on_game;     /* pointer is over the game surface */
};

static int is_game_surface(struct wl_surface *s) {
    if (!s) return 0;
    const char *const *tag = wl_proxy_get_tag((struct wl_proxy *)s);
    return tag && *tag && strcmp(*tag, "gamescope-toplevel") == 0;
}

static void p_enter(void *d, struct wl_pointer *p, uint32_t serial, struct wl_surface *s, wl_fixed_t x, wl_fixed_t y) {
    struct ctx *c = d;
    c->on_game = is_game_surface(s);
    if (c->orig->enter) c->orig->enter(c->data, p, serial, s, x, y);
}
static void p_leave(void *d, struct wl_pointer *p, uint32_t serial, struct wl_surface *s) {
    struct ctx *c = d;
    if (is_game_surface(s)) c->on_game = 0;
    if (c->orig->leave) c->orig->leave(c->data, p, serial, s);
}
static void p_motion(void *d, struct wl_pointer *p, uint32_t t, wl_fixed_t x, wl_fixed_t y) {
    struct ctx *c = d;
    if (c->orig->motion) c->orig->motion(c->data, p, t, x, y);
}
static void p_button(void *d, struct wl_pointer *p, uint32_t serial, uint32_t t, uint32_t b, uint32_t st) {
    struct ctx *c = d;
    if (!c->on_game) return;   /* click on frame/title bar: not for the game */
    if (c->orig->button) c->orig->button(c->data, p, serial, t, b, st);
}
static void p_axis(void *d, struct wl_pointer *p, uint32_t t, uint32_t a, wl_fixed_t v) {
    struct ctx *c = d;
    if (c->orig->axis) c->orig->axis(c->data, p, t, a, v);
}
static void p_frame(void *d, struct wl_pointer *p) {
    struct ctx *c = d;
    if (c->orig->frame) c->orig->frame(c->data, p);
}
static void p_axis_source(void *d, struct wl_pointer *p, uint32_t s) {
    struct ctx *c = d;
    if (c->orig->axis_source) c->orig->axis_source(c->data, p, s);
}
static void p_axis_stop(void *d, struct wl_pointer *p, uint32_t t, uint32_t a) {
    struct ctx *c = d;
    if (c->orig->axis_stop) c->orig->axis_stop(c->data, p, t, a);
}
static void p_axis_discrete(void *d, struct wl_pointer *p, uint32_t a, int32_t v) {
    struct ctx *c = d;
    if (c->orig->axis_discrete) c->orig->axis_discrete(c->data, p, a, v);
}
static void p_axis_value120(void *d, struct wl_pointer *p, uint32_t a, int32_t v) {
    struct ctx *c = d;
    if (c->orig->axis_value120) c->orig->axis_value120(c->data, p, a, v);
}
static void p_axis_rel_dir(void *d, struct wl_pointer *p, uint32_t a, uint32_t dir) {
    (void)d; (void)p; (void)a; (void)dir;
}

static const struct pointer_listener wrap = {
    .enter = p_enter, .leave = p_leave, .motion = p_motion, .button = p_button,
    .axis = p_axis, .frame = p_frame, .axis_source = p_axis_source,
    .axis_stop = p_axis_stop, .axis_discrete = p_axis_discrete,
    .axis_value120 = p_axis_value120, .axis_relative_direction = p_axis_rel_dir,
};

/* Only redirect listeners from the Gamescope binary itself, not those of libdecor/GTK. */
static int from_gamescope(const void *impl) {
    Dl_info di;
    if (!dladdr(impl, &di) || !di.dli_fname) return 0;
    const char *base = strrchr(di.dli_fname, '/');
    base = base ? base + 1 : di.dli_fname;
    return strcmp(base, "gamescope") == 0;
}

int wl_proxy_add_listener(struct wl_proxy *proxy, void (**impl)(void), void *data) {
    static int (*real)(struct wl_proxy *, void (**)(void), void *);
    if (!real) real = (int (*)(struct wl_proxy *, void (**)(void), void *))dlsym(RTLD_NEXT, "wl_proxy_add_listener");

    if (active && strcmp(wl_proxy_get_class(proxy), "wl_pointer") == 0 && from_gamescope(impl)) {
        struct ctx *c = calloc(1, sizeof *c);
        if (c) {
            c->orig = (const struct pointer_listener *)impl;
            c->data = data;
            return real(proxy, (void (**)(void))&wrap, c);
        }
    }
    return real(proxy, impl, data);
}

/* --- 2. Window manager name ------------------------------------------------------------- */
void Xutf8SetWMProperties(void *dpy, unsigned long w, const char *window_name, const char *icon_name,
                          char **argv, int argc, void *normal_hints, void *wm_hints, void *class_hints) {
    static void (*real)(void *, unsigned long, const char *, const char *, char **, int, void *, void *, void *);
    if (!real) real = (void (*)(void *, unsigned long, const char *, const char *, char **, int, void *, void *, void *))
        dlsym(RTLD_NEXT, "Xutf8SetWMProperties");
    if (active && opt_wmname && *opt_wmname) {
        if (window_name && strcmp(window_name, "steamcompmgr") == 0) window_name = opt_wmname;
        if (icon_name && strcmp(icon_name, "steamcompmgr") == 0) icon_name = opt_wmname;
    }
    real(dpy, w, window_name, icon_name, argv, argc, normal_hints, wm_hints, class_hints);
}

/* --- 3. Window title and app ID -------------------------------------------------------- */
static void *main_frame;               /* libdecor frame of the Gamescope window */
static struct wl_surface *main_surface;
static char *cur_title, *cur_appid;    /* as last sent */
static int null_attached;              /* buffer removed, not committed yet */

static void remember(char **slot, const char *v) {
    if (*slot && v && strcmp(*slot, v) == 0) return;
    free(*slot);
    *slot = v ? strdup(v) : NULL;
}

void *libdecor_decorate(void *context, struct wl_surface *surface, void *iface, void *user_data) {
    static void *(*real)(void *, struct wl_surface *, void *, void *);
    if (!real) real = (void *(*)(void *, struct wl_surface *, void *, void *))dlsym(RTLD_NEXT, "libdecor_decorate");
    void *frame = real(context, surface, iface, user_data);
    if (active && !main_frame) { main_frame = frame; main_surface = surface; }
    return frame;
}

void libdecor_frame_set_title(void *frame, const char *title) {
    static void (*real)(void *, const char *);
    if (!real) real = (void (*)(void *, const char *))dlsym(RTLD_NEXT, "libdecor_frame_set_title");
    if (active && opt_title && *opt_title) title = opt_title;
    if (active && frame == main_frame) remember(&cur_title, title);
    real(frame, title);
}

void libdecor_frame_set_app_id(void *frame, const char *app_id) {
    static void (*real)(void *, const char *);
    if (!real) real = (void (*)(void *, const char *))dlsym(RTLD_NEXT, "libdecor_frame_set_app_id");
    if (active && opt_appid && *opt_appid) app_id = opt_appid;
    if (active && frame == main_frame) remember(&cur_appid, app_id);
    real(frame, app_id);
}

/* All requests pass through here (wl_surface_attach() etc. are inline wrappers around it).
 * The variable arguments are converted following the request's signature, as libwayland does. */
#define MAX_ARGS 20   /* WL_CLOSURE_MAX_ARGS in libwayland */
typedef struct wl_proxy *(*marshal_array_t)(struct wl_proxy *, uint32_t, const struct wl_interface *,
                                            uint32_t, uint32_t, union wl_argument *);
struct wl_proxy *wl_proxy_marshal_flags(struct wl_proxy *proxy, uint32_t opcode,
                                        const struct wl_interface *interface, uint32_t version,
                                        uint32_t flags, ...) {
    static marshal_array_t real;
    if (!real) real = (marshal_array_t)dlsym(RTLD_NEXT, "wl_proxy_marshal_array_flags");

    const struct wl_interface *pif = *(const struct wl_interface *const *)proxy;  /* wl_proxy starts with its wl_object */
    const char *sig = pif->methods[opcode].signature;
    union wl_argument args[MAX_ARGS];
    int n = 0;
    va_list ap;
    va_start(ap, flags);
    for (; *sig && n < MAX_ARGS; sig++) {
        switch (*sig) {
        case 'i': case 'h': args[n++].i = va_arg(ap, int32_t); break;
        case 'u':           args[n++].u = va_arg(ap, uint32_t); break;
        case 'f':           args[n++].f = va_arg(ap, wl_fixed_t); break;
        case 's':           args[n++].s = va_arg(ap, const char *); break;
        case 'o': case 'n': args[n++].o = va_arg(ap, struct wl_object *); break;
        case 'a':           args[n++].a = va_arg(ap, struct wl_array *); break;
        default: break;     /* version digits, '?' */
        }
    }
    va_end(ap);

    int is_main = active && main_surface && proxy == (struct wl_proxy *)main_surface;
    if (is_main && opcode == WL_SURFACE_ATTACH) null_attached = args[0].o == NULL;
    struct wl_proxy *ret = real(proxy, opcode, interface, version, flags, args);

    if (is_main && opcode == WL_SURFACE_COMMIT && null_attached) {
        null_attached = 0;
        struct wl_proxy *(*get_tl)(void *) = (struct wl_proxy *(*)(void *))dlsym(RTLD_DEFAULT, "libdecor_frame_get_xdg_toplevel");
        struct wl_proxy *tl = get_tl ? get_tl(main_frame) : NULL;
        if (tl) {
            union wl_argument a[1];
            uint32_t v = wl_proxy_get_version(tl);
            if (cur_title) { a[0].s = cur_title; real(tl, 2 /* set_title */, NULL, v, 0, a); }
            if (cur_appid) { a[0].s = cur_appid; real(tl, 3 /* set_app_id */, NULL, v, 0, a); }
        }
    }
    return ret;
}
