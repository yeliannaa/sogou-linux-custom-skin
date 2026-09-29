#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Only enlarge the erroneous outer clamp in Sogou MoveStatus.
 * Its inner MoveWnd still applies the real monitor's available geometry.
 * All candidate-related callers retain the original implementation. */
void status_screen_size(int*, int*) __asm__("_ZN6n_sgxx13GetScreenSizeEPiS0_");
void status_screen_size(int* width, int* height) {
    typedef void (*native_fn)(int*, int*);
    native_fn original = (native_fn)dlsym(RTLD_NEXT, "_ZN6n_sgxx13GetScreenSizeEPiS0_");
    Dl_info caller = {0};
    int known = dladdr(__builtin_return_address(0), &caller);
    void* module = NULL;
    if (!original && known && caller.dli_fname) {
        module = dlopen(caller.dli_fname, RTLD_LAZY | RTLD_NOLOAD);
        if (module) original = (native_fn)dlsym(module, "_ZN6n_sgxx13GetScreenSizeEPiS0_");
    }
    if (!original || original == status_screen_size) abort();
    original(width, height);
    if (module) dlclose(module);
    if (!known || !caller.dli_sname ||
        strcmp(caller.dli_sname, "_ZN11t_uiWrapper10MoveStatusEii") != 0) return;
    static Display* display = NULL;
    if (!display) display = XOpenDisplay(NULL);
    if (!display) return;
    XWindowAttributes root;
    if (!XGetWindowAttributes(display, DefaultRootWindow(display), &root)) return;
    if (root.width > 0 && root.height > 0) {
        if (getenv("SOGOU_STATUS_FIX_TRACE"))
            fprintf(stderr, "status-screen-fix: MoveStatus bounds %dx%d -> %dx%d\n", *width, *height, root.width, root.height);
        *width = root.width;
        *height = root.height;
    }
}
