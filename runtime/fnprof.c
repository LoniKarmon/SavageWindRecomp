// Function-entry profiler. SAVAGEWIND_FNPROF=<from>:<to> counts guest function entries (every generated
// function calls FN_ENTER) between those presented frames, then writes build/fnprof.txt (addr count, most
// called first). Diffing two runs shows which game functions a change brings in; counts also show hot code.
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hle.h"
#include "platform.h"
#include "control_mem.h"

volatile int g_fnprof;

#define NSLOT (1 << 18)
static struct { _Atomic uint64_t addr; _Atomic uint64_t count; } slots[NSLOT];

// SAVAGEWIND_FNPROF_BT=<hex addr>[,...]: also print the host backtrace (guest functions are f_<addr>) the first time
// each listed function is entered inside the window - who calls it
static uint64_t bt_addrs[256];
static int bt_n = -1;
static _Atomic uint8_t bt_done[256];

uint64_t g_bt_first_x0;

static void bt_check(uint64_t a, uint64_t lr, uint64_t x0) {
    if (bt_n < 0) {
        bt_n = 0;
        const char *e = getenv("SAVAGEWIND_FNPROF_BT");
        for (const char *p = e; p && *p && bt_n < 256;) {
            bt_addrs[bt_n++] = strtoull(p, (char **)&p, 16);
            while (*p == ',' || *p == ' ') p++;
        }
    }
    for (int i = 0; i < bt_n; i++)
        if (bt_addrs[i] == a && !atomic_exchange(&bt_done[i], 1)) {
            if (i == 0) g_bt_first_x0 = x0;
            uint64_t vt = x0 >= 0x7000000000ull && x0 < 0x7800000000ull ? *(uint64_t *)(uintptr_t)x0 : 0;
            uint64_t v100 = vt >= 0x7000000000ull && vt < 0x7800000000ull ? *(uint64_t *)(uintptr_t)(vt + 0x100) : 0;
            uint64_t p8 = x0 >= 0x7000000000ull && x0 < 0x7800000000ull ? *(uint64_t *)(uintptr_t)(x0 + 8) : 0;
            fprintf(stderr, "[fnprof-bt] %llx entered from guest lr %llx x0 %llx (vtable %llx, +0x100 %llx, [x0+8] %llx):\n",
                    (unsigned long long)a, (unsigned long long)lr, (unsigned long long)x0, (unsigned long long)vt,
                    (unsigned long long)v100, (unsigned long long)p8);
            plat_print_backtrace();  // (execinfo is macOS / glibc only)
        }
}

// SAVAGEWIND_FNPROF_ARGS=<hex addr>[,...]: log x0-x5 and the caller on each entry of those functions (the first
// SAVAGEWIND_FNPROF_ARGS_MAX entries each, default 64) - what a function is called with, without a debugger - and
// what one register points to: SAVAGEWIND_FNPROF_DEREF=<reg>:<qwords> (default 1:4, x1: often a descriptor or out
// argument).
static uint64_t args_addrs[64];
static int args_n = -1, args_max = 64, deref_reg = 1, deref_n = 4;
static _Atomic int args_count[64];

static void args_check(uint64_t a, uint64_t lr) {
    if (args_n < 0) {
        args_n = 0;
        const char *e = getenv("SAVAGEWIND_FNPROF_ARGS");
        if (getenv("SAVAGEWIND_FNPROF_ARGS_MAX")) args_max = atoi(getenv("SAVAGEWIND_FNPROF_ARGS_MAX"));
        if (getenv("SAVAGEWIND_FNPROF_DEREF")) sscanf(getenv("SAVAGEWIND_FNPROF_DEREF"), "%d:%d", &deref_reg, &deref_n);
        if (deref_reg < 0 || deref_reg > 30) deref_reg = 1;
        if (deref_n < 0 || deref_n > 64) deref_n = 4;
        for (const char *p = e; p && *p && args_n < 64;) {
            args_addrs[args_n++] = strtoull(p, (char **)&p, 16);
            while (*p == ',' || *p == ' ') p++;
        }
    }
    for (int i = 0; i < args_n; i++)
        if (args_addrs[i] == a && atomic_fetch_add(&args_count[i], 1) < args_max) {
            Cpu *c = kernel_current_cpu();
            if (!c) return;
            char line[1600];
            int n = snprintf(line, sizeof line, "[fnprof-args] %llx from %llx: %llx %llx %llx %llx %llx %llx [x%d:",
                             (unsigned long long)a, (unsigned long long)lr, (unsigned long long)c->x[0],
                             (unsigned long long)c->x[1], (unsigned long long)c->x[2], (unsigned long long)c->x[3],
                             (unsigned long long)c->x[4], (unsigned long long)c->x[5], deref_reg);
            uint64_t p = c->x[deref_reg];
            for (int k = 0; k < deref_n && p >= GUEST_LO && p + 8 * (k + 1) <= GUEST_HI; k++) {
                uint64_t v = ((uint64_t *)(uintptr_t)p)[k];
                n += snprintf(line + n, sizeof line - n, " %llx", (unsigned long long)v);
                const char *s = (const char *)(uintptr_t)v;  // a pointer to text (a name): show it
                int len = 0;
                if (v >= GUEST_LO && v + 64 <= GUEST_HI)
                    while (len < 64 && s[len] >= 0x20 && s[len] < 0x7f) len++;
                if (len >= 4 && (len == 64 || !s[len]) && n < (int)sizeof line - 80)
                    n += snprintf(line + n, sizeof line - n, "=\"%.*s\"", len, s);
            }
            fprintf(stderr, "%s]\n", line);
        }
}

// SAVAGEWIND_FNPROF_ARM=<hex>: from the FIRST entry of that function, one line per MAIN-MODULE guest
// function entry afterwards (addr from caller lr; sdk loops of background threads stay out) - the ORDERED
// history of a phase, e.g. nnMain's dead-walk tail after its init ipc answered ok but no frame presented
// (runs 108-111). Capped by SAVAGEWIND_FNPROF_ARM_MAX (default 2M lines) so a hot phase cannot bury the
// log; the cap line marks where tracing stopped.
static uint64_t arm_addr;
static int arm_state = -1;  // -1: env not read, 0: off, 1: waiting for arm_addr, 2: tracing
static long arm_left;
static int arm_all;  // SAVAGEWIND_FNPROF_ARM_ALL=1: log sdk/thunk entries too (everything, not just main)

static void arm_check(uint64_t a, uint64_t lr) {
    if (arm_state < 0) {
        const char *e = getenv("SAVAGEWIND_FNPROF_ARM");
        arm_addr = e ? strtoull(e, NULL, 16) : 0;
        arm_left = getenv("SAVAGEWIND_FNPROF_ARM_MAX") ? atol(getenv("SAVAGEWIND_FNPROF_ARM_MAX")) : 2000000;
        arm_all = getenv("SAVAGEWIND_FNPROF_ARM_ALL") != NULL;
        arm_state = arm_addr ? 1 : 0;
    }
    if (arm_state == 1) {
        if (a != arm_addr) return;
        arm_state = 2;
        LOG("[fnprof-arm] armed at %llx\n", (unsigned long long)a);
    }
    if (arm_state != 2) return;
    if (arm_all ? 0 : (a - GUEST_LO >= 0x1e98000ull)) return;  // main module only unless ARM_ALL
    if (arm_left-- <= 0) {
        arm_state = 0;
        LOG("[fnprof-arm] cap reached, tracing stopped\n");
        return;
    }
    LOG("[fn] %llx from %llx\n", (unsigned long long)a, (unsigned long long)lr);
}

// SAVAGEWIND_FNPROF_TAIL=<a>[,<b>...]: on the FIRST entry of each listed function, print a forensic
// one-liner with the live Cpu registers plus the guest words nnMain's e00/e04/e08/e14 virtual-call tail
// is about to dereference (Application vtable, its slot [0x28], the GOT words behind the 61ddc argument
// load and the e14 exit gate, the RootTask list head). run113 proved that tail never dispatched (no [fn]
// for the slot target f_7000e952b8) - one of these words is the dead one; which, settles the fix.
static uint64_t tail_addrs[8];
static int tail_n = -1, tail_fired[8];

static uint64_t tail_word(uint64_t a) {  // committed guest word, else raw host-heap word, else 0
    if (a < 0x1000) return 0;            // near-NULL: never raw-deref the host's unmapped page-0
    uint64_t v;
    if (control_mem_peek(a, &v, 8)) return v;
    if (a < 0x7fff00000000ull) return *(volatile uint64_t *)(uintptr_t)a;  // host malloc'd node
    return 0;
}

// SAVAGEWIND_FNPROF_TAIL_LR=<hex lr>: fire the same dump the FIRST time any function is entered FROM that
// return address -- for straight-line tails that call no function before the site of interest, the last
// call's entry is the exact moment to snapshot (run115: the e08 guard still skipped even with the slot
// seeded at 61b80, so [x20]'s vptr must change AFTER the f_7000e952b8-entry dump; lr 7000c61d90 is nnMain's
// last TLS thunk call, ~4 instructions before the e00-e08 virtual call reads it). Also runs dispatch_lookup
// on the slot values, splitting "wrong pointer" from "lookup failure" in the same snapshot.
static uint64_t tlr_addr;
static int tlr_state = -1;

static void tlr_dump(uint64_t lr, Cpu *c) {
    uint64_t x20 = c->x[20], x23 = c->x[23], vt = tail_word(x20), sl = tail_word(vt + 0x28);
    // SAVAGEWIND_FNPROF_TAIL_RESEED=<addr>:<value>: re-write a boot slot AT the snapshot instant, after the
    // ctor-drain and early guest stores are done -- run116: a load-time seed of [0x7001d76038] read good at
    // the d90 thunk entry but the e04 guard still answered 0, so the slot's LAST writer sits between them;
    // re-seeding here proves whether the e04/e08 chain then dispatches (the virtual "run" = f_7000e952b8).
    const char *rs = getenv("SAVAGEWIND_FNPROF_TAIL_RESEED");
    if (rs) {
        char *end;
        uint64_t a = strtoull(rs, &end, 16), v = end && *end == ':' ? strtoull(end + 1, &end, 16) : 0;
        if (a >= GUEST_LO && a + 8 <= GUEST_HI) *(volatile uint64_t *)(uintptr_t)a = v;
    }
    x20 = c->x[20], vt = tail_word(x20), sl = tail_word(vt + 0x28);  // re-read post-reseed
    LOG("[tail-lr] lr=%llx x20=%llx x21=%llx x22=%llx x23=%llx [x20]=%llx [[x20]+0x28]=%llx dl=%d\n",
        (unsigned long long)lr, (unsigned long long)x20, (unsigned long long)c->x[21],
        (unsigned long long)c->x[22], (unsigned long long)x23, (unsigned long long)vt,
        (unsigned long long)sl, dispatch_lookup(sl) != NULL);
    LOG("[tail-lr]  [[x20]+0x58]=%llx dl58=%d [x23]=%llx slot_6b8e0=%llx [[slot_6b8e0]]=%llx\n",
        (unsigned long long)tail_word(vt + 0x58), dispatch_lookup(tail_word(vt + 0x58)) != NULL,
        (unsigned long long)tail_word(x23), (unsigned long long)tail_word(0x7001d6b8e0ull),
        (unsigned long long)tail_word(tail_word(0x7001d6b8e0ull)));
}

static void tail_check(uint64_t a, uint64_t lr, Cpu *c) {
    if (tail_n < 0) {
        tail_n = 0;
        const char *e = getenv("SAVAGEWIND_FNPROF_TAIL");
        for (const char *p = e; p && *p && tail_n < 8; tail_n++) {
            tail_addrs[tail_n] = strtoull(p, (char **)&p, 16);
            while (*p == ',') p++;
        }
    }
    for (int i = 0; i < tail_n; i++) {
        if (a != tail_addrs[i] || tail_fired[i]++) continue;
        uint64_t x20 = c->x[20], x23 = c->x[23], vt = tail_word(x20), sl = tail_word(vt + 0x28);
        LOG("[tail] f_%llx x0=%llx x20=%llx x21=%llx x22=%llx x23=%llx x24=%llx\n", (unsigned long long)a,
            (unsigned long long)c->x[0], (unsigned long long)x20, (unsigned long long)c->x[21],
            (unsigned long long)c->x[22], (unsigned long long)x23, (unsigned long long)c->x[24]);
        LOG("[tail]  [x20]=%llx [[x20]+0x28]=%llx [x0]=%llx [[x0]+0x28]=%llx [x23]=%llx\n",
            (unsigned long long)vt, (unsigned long long)sl, (unsigned long long)c->x[0],
            (unsigned long long)tail_word(tail_word(c->x[0]) + 0x28), (unsigned long long)tail_word(x23));
        LOG("[tail]  slot_6b678=%llx slot_6b8e0=%llx [[slot_6b8e0]]=%llx slot_1d78250=%llx slot_1d78358=%llx\n",
            (unsigned long long)tail_word(0x7001d6b678ull), (unsigned long long)tail_word(0x7001d6b8e0ull),
            (unsigned long long)tail_word(tail_word(0x7001d6b8e0ull)),
            (unsigned long long)tail_word(0x7001d78250ull), (unsigned long long)tail_word(0x7001d78358ull));
    }
    if (tlr_state < 0) {
        const char *e = getenv("SAVAGEWIND_FNPROF_TAIL_LR");
        tlr_addr = e ? strtoull(e, NULL, 16) : 0;
        tlr_state = tlr_addr ? 1 : 0;
    }
    if (tlr_state == 1 && lr == tlr_addr) { tlr_state = 0; tlr_dump(lr, c); }
}

void fnprof_hit(uint64_t a, uint64_t lr, uint64_t x0) {
    if (bt_n) bt_check(a, lr, x0);
    if (args_n) args_check(a, lr);
    if (arm_state != 0) arm_check(a, lr);
    if (tail_n != 0 || tlr_state != 0) { Cpu *cc = kernel_current_cpu(); if (cc) tail_check(a, lr, cc); }
    uint32_t h = (uint32_t)((a >> 2) * 0x9E3779B1u) & (NSLOT - 1);
    for (int n = 0; n < NSLOT; n++, h = (h + 1) & (NSLOT - 1)) {
        uint64_t cur = atomic_load_explicit(&slots[h].addr, memory_order_relaxed);
        if (cur == a || (cur == 0 && atomic_compare_exchange_strong(&slots[h].addr, &cur, a)) || cur == a) {
            atomic_fetch_add_explicit(&slots[h].count, 1, memory_order_relaxed);
            return;
        }
    }
}

static int cmp(const void *x, const void *y) {
    uint64_t a = ((const uint64_t *)x)[1], b = ((const uint64_t *)y)[1];
    return a < b ? 1 : a > b ? -1 : 0;
}

void fnprof_frame(uint64_t frame) {
    static long from = -2, to;
    if (from == -2) {
        from = -1;
        const char *e = getenv("SAVAGEWIND_FNPROF");
        if (e && sscanf(e, "%ld:%ld", &from, &to) != 2) from = -1;
    }
    if (from < 0) return;
    if ((long)frame == from) { g_fnprof = 1; LOG("[fnprof] on at frame %llu\n", (unsigned long long)frame); }
    if ((long)frame != to) return;
    g_fnprof = 0;
    uint64_t (*rows)[2] = malloc(sizeof(uint64_t[2]) * NSLOT);
    int n = 0;
    for (int i = 0; i < NSLOT; i++)
        if (slots[i].addr) { rows[n][0] = slots[i].addr; rows[n][1] = slots[i].count; n++; }
    qsort(rows, n, sizeof rows[0], cmp);
    const char *out = getenv("SAVAGEWIND_FNPROF_OUT") ? getenv("SAVAGEWIND_FNPROF_OUT") : "build/fnprof.txt";  // (parallel runs)
    FILE *f = fopen(out, "w");
    for (int i = 0; f && i < n; i++) fprintf(f, "%llx %llu\n", (unsigned long long)rows[i][0], (unsigned long long)rows[i][1]);
    if (f) fclose(f);
    free(rows);
    LOG("[fnprof] %d functions, written %s (frames %ld-%ld)\n", n, out, from, to);
    from = -1;
}

// SAVAGEWIND_FNPROF=0:<to>: profile from process start (threads the game starts before the first frame)
__attribute__((constructor)) static void fnprof_early(void) {
    const char *e = getenv("SAVAGEWIND_FNPROF");
    if (e && e[0] == '0' && e[1] == ':') g_fnprof = 1;
}
