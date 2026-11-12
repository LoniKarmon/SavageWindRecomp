"""Per-instruction replacements applied by gen.py to the main module (address -> function(gen, addr) returning C).

Each entry replaces the single guest instruction at that address with hand-written C, for example
to redirect a hard-coded aspect-ratio load to the runtime. The addresses differ between game versions:
tools/game_sites.py finds them (and the functions and data the C uses) for the version being generated,
and table() maps them to these functions; gen.sites holds them all. Every patch still checks the
instruction word it expects before replacing it (assert on the decoded word) and fails loudly otherwise.
The 1.8.2 addresses in the comments are for reading along in a disassembly.

The Link's Awakening patches this file held in LASRecomp are kept in the archived copy
(reference/LASRecomp/tools/patches.py) as more examples of the pattern.
"""
import struct

from game_sites import adrp_page, sext


def _word(gen, a):
    return struct.unpack_from('<I', gen.nso.image, a - gen.base)[0]


def _fn(gen, site):  # the generated function at a site's address
    return f'f_{gen.sites[site]:x}'


# Savage Wind's own pages in the game's Options screen (runtime/ui/game_options.mm), opened from the title screen menu
# (screen 1, buttons 0x69..0x6f, FUN_7100d4c5e0) or the pause menu's System page (buttons 0x4d..0x53, FUN_7100cbc918).
# The screen builds one row per entry of a static option table every time it opens (the table is read through the
# pointers at opt_table, 1.8.2 0x7001cccd98..0x7001cccdb0), and every row goes through a handful of functions. The
# runtime points the table at a longer copy with its own entries (index >= the game's 14) and these hooks hand its rows
# to the runtime: values, texts and what A does. A page change closes the screen and opens it again with another row
# list, from whichever menu opened it. Quitting asks with the game's own two-button dialog (screen 0x39).

def _sub_sp(n):  # `sub sp, sp, #n`
    return 0xd10003ff | (n << 10)


def _quit_dialog(gen, ret, owner):
    # C: open the game's dialog (screen 0x39) as a two-button question (type 7, vtable +0x4e0) over the screen `owner`
    # (a C expression; its input is off while the question is up); the runtime gives it its texts (_dialog_texts) and
    # reads the answer
    req = _fn(gen, 'screen_open_request')
    return (f'{{ extern void {req}(Cpu *); extern uint64_t rt_quit_dialog_begin(uint64_t); '
            f'uint64_t own = {owner}; c->x[0] = 0x39; c->x[1] = 0; c->x[30] = {ret:#x}ull; {req}(c); '
            'uint64_t dlg = rt_quit_dialog_begin(own); '
            f'if (dlg) {{ c->x[0] = dlg; c->x[1] = 7; c->x[2] = 0; c->x[3] = 0; c->x[30] = {ret:#x}ull; '
            'c->pc = LD64(LD64(dlg) + 0x4e0); rt_dispatch(c); } }')


def _reopen_options(gen, ret):
    # C: open the Options screen as the menus' Options buttons do: open request (screen_open_request, 1.8.2
    # FUN_7100d6fd90, with 0x34), then vtable +0x28 (open: screen_open, FUN_71012d90e0) with 1
    req, op = _fn(gen, 'screen_open_request'), _fn(gen, 'screen_open')
    return (f'{{ extern void {req}(Cpu *); extern void {op}(Cpu *); extern uint64_t rt_opt_screen(void); '
            f'c->x[0] = 0x34; c->x[1] = 0; c->x[30] = {ret:#x}ull; {req}(c); uint64_t scr = rt_opt_screen(); '
            f'if (scr) {{ c->x[0] = scr; c->x[1] = 1; c->x[30] = {ret:#x}ull; {op}(c); }} }}')


def _opt_rows(gen, a):
    # createRows (Options vtable +0x2f0): the runtime installs the row list of the page about to be shown
    assert _word(gen, a) == _sub_sp(0xc0), hex(_word(gen, a))
    return ('{ extern void rt_opt_rows(void); rt_opt_rows(); c->sp -= 0xc0; }'
            f'  /* {a:#x}: sub sp, sp, #0xc0 (Options: build rows) */')


def _opt_flag_type(gen, a):
    # row init: the game data flag type of the entry (x1); 0 bool, 1 s32
    assert _word(gen, a) >> 26 == 0x25, hex(_word(gen, a))  # bl gdt_flag_type
    t, fn = gen.sites['gdt_flag_type'], _fn(gen, 'gdt_flag_type')
    return ('{ extern int rt_opt_flag_type(uint64_t); int t = rt_opt_flag_type(c->x[1]); '
            'if (t >= 0) c->x[0] = (uint32_t)t; '
            f'else {{ extern void {fn}(Cpu *); c->x[30] = {a + 4:#x}ull; {fn}(c); }} }}'
            f'  /* {a:#x}: bl {t:#x} (Options: flag type) */')


def _opt_read(gen, a):
    # row value read (x0 = row): fills +0x54 bool, +0x58 value, +0x5c max, +0x60 min, +0x64 button state
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]!
    return ('{ extern int rt_opt_read(uint64_t); if (rt_opt_read(c->x[0])) return; '
            'uint64_t ea = c->sp - 0x30; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); c->sp = ea; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (Options: read value) */')


def _opt_store(gen, a):
    # row value store (x0 = row)
    assert _word(gen, a) & 0x9f00001f == 0x90000008, hex(_word(gen, a))  # adrp x8, <the option table's page>
    page = adrp_page(_word(gen, a), a)
    return (f'{{ extern int rt_opt_store(uint64_t); if (rt_opt_store(c->x[0])) return; c->x[8] = {page:#x}ull; }}'
            f'  /* {a:#x}: adrp x8, {page:#x} (Options: store value) */')


def _opt_reset(gen, a):
    # row reset to the default (x0 = row), from "reset to defaults" (X)
    assert _word(gen, a) == 0xb9406808, hex(_word(gen, a))  # ldr w8, [x0, #0x68]
    return ('{ extern int rt_opt_reset(uint64_t); if (rt_opt_reset(c->x[0])) return; c->x[8] = LD32(c->x[0] + 0x68); }'
            f'  /* {a:#x}: ldr w8, [x0, #0x68] (Options: reset value) */')


def _opt_msg(gen, a):
    # every option text: message w21 of LayoutMsg/OptionWindow_00 into the {char16_t *, u32 length} at x2
    assert _word(gen, a) >> 26 == 0x25, hex(_word(gen, a))  # bl msg_lookup
    t, fn = gen.sites['msg_lookup'], _fn(gen, 'msg_lookup')
    return ('{ extern int rt_opt_msg(uint32_t, uint64_t); if (rt_opt_msg((uint32_t)c->x[21], c->x[2])) c->x[0] = 0; '
            f'else {{ extern void {fn}(Cpu *); c->x[30] = {a + 4:#x}ull; {fn}(c); }} }}'
            f'  /* {a:#x}: bl {t:#x} (Options: message text) */')


def _opt_decide(gen, a):
    # A on a row (x0 = row). 1: close the screen (a page change; the menu that opened it opens it again), 2: done,
    # 3: ask whether to quit
    assert _word(gen, a) == _sub_sp(0x30), hex(_word(gen, a))
    close = _fn(gen, 'screen_close')
    return ('{ extern int rt_opt_decide(uint64_t); int r = rt_opt_decide(c->x[0]); '
            f'if (r == 1) {{ extern void {close}(Cpu *); c->x[0] = LD64(c->x[0]); c->x[1] = 0xffffffffull; '
            f'c->x[30] = {a + 4:#x}ull; {close}(c); return; }} '
            f'if (r == 3) {_quit_dialog(gen, a + 4, "LD64(c->x[0])")} '
            'if (r) return; c->sp -= 0x30; }'
            f'  /* {a:#x}: sub sp, sp, #0x30 (Options: decide) */')


def _opt_tick(gen, a):
    # Options update (x0 = screen): the runtime may ask for one row to be redrawn (a binding changed); 1: skip the
    # update (the quit question is up: the screen's own dialog handling would take its answer)
    assert _word(gen, a) == _sub_sp(0x40), hex(_word(gen, a))
    redraw = _fn(gen, 'opt_row_redraw')
    return ('{ extern uint64_t rt_opt_tick(uint64_t); uint64_t row = rt_opt_tick(c->x[0]); if (row == 1) return; '
            f'if (row) {{ extern void {redraw}(Cpu *); uint64_t s0 = c->x[0], s30 = c->x[30]; '
            f'c->x[0] = row; c->x[1] = 0; c->x[30] = {a + 4:#x}ull; {redraw}(c); c->x[0] = s0; c->x[30] = s30; }} '
            'c->sp -= 0x40; }'
            f'  /* {a:#x}: sub sp, sp, #0x40 (Options: update) */')


# Dual native binding cells: only emitted when the entire strict optional group matched.
def _opt_two_redraw(gen, a):
    assert _word(gen, a) == _sub_sp(0x40)
    return ('{ extern int rt_opt_two_redraw(uint64_t); if (rt_opt_two_redraw(c->x[0])) return; c->sp -= 0x40; }')


def _opt_two_callback(which):
    def patch(gen, a):
        assert _word(gen, a) == 0xb976b008  # ldr w8, [x0, #0x36b0]
        return ('{ extern int rt_opt_two_callback(uint64_t, uint64_t, int); '
                f'if (rt_opt_two_callback(c->x[0], c->x[1], {which})) return; '
                'c->x[8] = LD32(c->x[0] + 0x36b0); }')
    return patch


def _opt_two_row_state(gen, a):
    assert _word(gen, a) & 0x9f00001f == 0x90000008
    page = adrp_page(_word(gen, a), a)
    return ('{ extern int rt_opt_two_row_state(uint64_t); '
            f'if (rt_opt_two_row_state(c->x[0])) return; c->x[8] = {page:#x}ull; }}')


def _opt_two_control(initial):
    def patch(gen, a):
        assert _word(gen, a) == (0xf9400161 if initial else 0xf9400129)
        # x11 / x9 is the original field address; the row stays x20 on initial focus.
        expr = 'c->x[20]' if initial else 'c->x[9] - 0x28'
        reg, field = (1, 11) if initial else (9, 9)
        return ('{ extern uint64_t rt_opt_two_control(uint64_t); '
                f'uint64_t b = rt_opt_two_control({expr}); c->x[{reg}] = b ? b : LD64(c->x[{field}]); }}')
    return patch


def _opt_two_horizontal(gen, a):
    assert _word(gen, a) == 0xb936c268  # str w8, [x19, #0x36c0]
    return ('{ extern void rt_opt_two_horizontal(uint64_t, unsigned); '
            'ST32(c->x[19] + 0x36c0, c->x[8]); rt_opt_two_horizontal(c->x[19], (unsigned)c->x[8]); }')


def _opt_back(gen, a):
    # B on the screen: it closes (after the save); on one of Savage Wind's pages it opens again on the first page
    assert _word(gen, a) >> 26 == 0x25, hex(_word(gen, a))  # bl screen_back
    t, fn = gen.sites['screen_back'], _fn(gen, 'screen_back')
    return (f'{{ extern void rt_opt_back(void); rt_opt_back(); extern void {fn}(Cpu *); '
            f'c->x[30] = {a + 4:#x}ull; {fn}(c); }}'
            f'  /* {a:#x}: bl {t:#x} (Options: back) */')


def _title_tick(gen, a):
    # The title screen menu's update (screen 1, x0 = menu). While its Options button is active ([title_options_state]
    # == 0x6a; 1.8.2 +0x363c) it waits for the Options screen (id 0x34) to go away; after a page change the runtime
    # opens it again first. The quit question's answer is read here too.
    assert _word(gen, a) == 0xa9bb7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x50]!
    return ('{ extern int rt_opt_title_tick(uint64_t); '
            f'if (rt_opt_title_tick(c->x[0])) {{ uint64_t s0 = c->x[0], s30 = c->x[30]; {_reopen_options(gen, a + 4)} '
            'c->x[0] = s0; c->x[30] = s30; } '
            'uint64_t ea = c->sp - 0x50; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); c->sp = ea; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x50]! (title menu: update) */')


def _title_event(gen, a):
    # The title screen menu's button handler (x0 = menu, x1 = button, its id at +0x44): the amiibo settings button
    # (0x6c; Savage Wind has no amiibo support) is Quit, which asks where to
    assert _word(gen, a) == _sub_sp(0x60), hex(_word(gen, a))
    return ('{ extern int rt_title_event(uint32_t); '
            f'if (rt_title_event(LD32(c->x[1] + 0x44))) {{ {_quit_dialog(gen, a + 4, "c->x[0]")} return; }} '
            'c->sp -= 0x60; }'
            f'  /* {a:#x}: sub sp, sp, #0x60 (title menu: button) */')


def _title_msg(gen, a):
    # Message lookup (x0 = message file, x1 = label, x2 = {char16_t *, u32 length}): the title menu's file
    # (LayoutMsg/Title_00, title_msg_file) gives "0003" (amiibo settings) as Quit
    assert _word(gen, a) == _sub_sp(0x40), hex(_word(gen, a))
    title = gen.sites['title_msg_file']
    return ('{ extern int rt_title_msg(uint64_t, uint64_t); '
            f'if (c->x[0] == {title:#x}ull && rt_title_msg(c->x[1], c->x[2])) {{ c->x[0] = 0; return; }} '
            'c->sp -= 0x40; }'
            f'  /* {a:#x}: sub sp, sp, #0x40 (message lookup) */')


def _pause_option_state(gen, a):
    # The pause menu System page's Options state update (x0 = page): it leaves the state once the screen reports
    # closed. During a page change it waits instead, then opens it again.
    assert _word(gen, a) == 0xa9be7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x20]!
    return ('{ extern int rt_opt_pause_tick(void); int r = rt_opt_pause_tick(); '
            f'if (r == 1) {_reopen_options(gen, a + 4)} '
            'if (r) return; '
            'uint64_t ea = c->sp - 0x20; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); c->sp = ea; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x20]! (pause System page: Options state) */')


def _dialog_texts(gen, a):
    # The dialog's two-button layout (x0 = dialog, x1 = message, x2 / x3 = left / right button, {char16_t *, u32}
    # each): the quit question's texts
    assert _word(gen, a) == _sub_sp(0x50), hex(_word(gen, a))
    return ('{ extern void rt_quit_dialog_texts(uint64_t, uint64_t, uint64_t); '
            'rt_quit_dialog_texts(c->x[1], c->x[2], c->x[3]); c->sp -= 0x50; }'
            f'  /* {a:#x}: sub sp, sp, #0x50 (dialog: two-button texts) */')


def _dialog_back(gen, a):
    # B on the dialog presses its cancel button (one of the two); the quit question just closes instead (no answer)
    w = _word(gen, a)
    assert w & 0xffc003ff == 0xf9400100, hex(w)  # ldr x0, [x8, #off] (1.8.2 0x33b0, 1.9.0 0x33c8: the screen grew)
    off = ((w >> 10) & 0xfff) * 8
    return ('{ extern int rt_quit_dialog_back(void); '
            f'c->x[0] = rt_quit_dialog_back() ? 0 : LD64(c->x[8] + {off:#x}); }}'
            f'  /* {a:#x}: ldr x0, [x8, #{off:#x}] (dialog: B) */')


# Frame rate (runtime/hle/framepace.c): the runtime paces the frames at the present and sets the game's clock. The frame
# loop's vsync wait (sead framework, 1.8.2 0x7000d811fc, x0 = its display object; only the first frames after start-up
# come here) waits for the display's vsync, then for more vsyncs until interval / 60 s have passed: skipped (the game's
# own runs with SAVAGEWIND_FRAMEPACE=0). ksys::VFR::updateInterval (x19 = VFR) has just set the interval ratio the
# game's time step comes from (interval / 2): the runtime puts the frame's real length there, before the time
# multipliers and the deltas are worked out from it.

def _frame_wait(gen, a):
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]!
    return ('{ extern int rt_frame_wait(void); if (rt_frame_wait()) return; '
            'uint64_t ea = c->sp - 0x30; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); c->sp = ea; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (frame wait) */')


def _vfr_ratio(gen, a):
    assert _word(gen, a) == 0xb9407a68, hex(_word(gen, a))  # ldr w8, [x19, #0x78]
    return ('{ extern void rt_vfr_update(uint64_t); rt_vfr_update(c->x[19]); c->x[8] = LD32(c->x[19] + 0x78); }'
            f'  /* {a:#x}: ldr w8, [x19, #0x78] (VFR: interval ratio) */')


# Arrows (#144): once in their fall, an arrow's velocity is its last direction x its speed plus a gravity vector
# (0, ArrowGravity, 0), added once per update with no time step (1.9.0 0x70005ee668; the straight part before it scales
# by the delta frame). Above 30 fps it fell 2 or 4 times as fast per second and landed short. The load of its Y part
# (the only one the game sets) takes the frame's length in console frames as a factor (runtime/hle/framepace.c
# rt_arrow_gravity: 1 at 30 fps, slow motion left out as on the console).

def _arrow_gravity(gen, a):
    assert _word(gen, a) == 0xbd410a81, hex(_word(gen, a))  # ldr s1, [x20, #0x108]
    return ('{ extern float rt_arrow_gravity(uint64_t, float); union { uint32_t u; float f; } g = { .u = (uint32_t)LD32(c->x[20] + 0x108) }; '
            'g.f = rt_arrow_gravity(c->x[20], g.f); c->v[1] = g.u; }'
            f'  /* {a:#x}: ldr s1, [x20, #0x108] (arrow gravity) */')


# Experimental shield-surf takeoff grace (#305), runtime/hle/framepace.c. Preserve the original FP subtraction
# through rt_fsub_s (runtime/cpu.h: fp_op_s on x86-64, a native FSUB on AArch64) when the grace is inactive,
# including the game's FP exception/rounding behavior.
def _surf_contact(gen, a):
    assert _word(gen, a) == 0x3941d2a8  # ldrb w8, [x21, #0x74]
    return ('{ extern void rt_surf_contact(uint64_t, unsigned); '
            'c->x[8] = LD8(c->x[21] + 0x74); rt_surf_contact(c->x[21], (unsigned)c->x[8]); }')


def _surf_boost_remove(gen, a):
    assert _word(gen, a) == 0x1e203820  # fsub s0, s1, s0
    return ('{ extern int rt_surf_takeoff_pending(uint64_t); '
            'if (rt_surf_takeoff_pending(c->x[21])) c->v[0] = (uint32_t)c->v[1]; '
            'else rt_fsub_s(c, 0, 1, 0); }')


# A stale actor (#391, #393): the game's target manager (the Sheikah Slate's magnesis and camera targets) keeps a pointer
# to an actor that is already gone. The helper that asks an actor for its link (1.9.0 0x700120bc40: actor + 0x570, then
# + 0x88) got a freed pointer (#391: a garbage value, a crash in the next load) and one inline copy of it
# (1.9.0 0x7000dea400, the camera target) got an actor whose + 0x570 is null (#393: accessing 0x88). Both now treat
# such an actor as none: the helper answers 0, the inline copy leaves its function by the path of "no target".
def _stale_actor_helper(gen, a):
    w = _word(gen, a)
    assert w & 0xff00001f == 0xb4000000, hex(w)  # cbz x0, <ret>
    target = a + sext((w >> 5) & 0x7ffff, 19) * 4
    return ('{ extern void rt_stale_actor(void); '
            'if (!c->x[0]) goto L_%x; '
            'if (c->x[0] - 0x7000000000ull >= 0x320000000ull || !LD64(c->x[0] + 0x570)) { rt_stale_actor(); c->x[0] = 0; goto L_%x; } }'
            % (target, target))


def _stale_actor_target(gen, a):
    assert _word(gen, a) == 0xf942ba68, hex(_word(gen, a))  # ldr x8, [x19, #0x570]
    # the epilogue of "no target": the function's own early exit (cbz x0 / cbnz x19 above this site)
    exit_at = _stale_target_exit(gen, a)
    return ('{ extern void rt_stale_actor(void); '
            'if (c->x[19] - 0x7000000000ull >= 0x320000000ull || !LD64(c->x[19] + 0x570)) { rt_stale_actor(); goto L_%x; } '
            'c->x[8] = LD64(c->x[19] + 0x570); }' % exit_at)


def _stale_target_exit(gen, a):
    # walk back to the cbnz x19 that jumps to this code: its fall-through (the next word) is the epilogue's first word
    b = a
    while b > a - 0x80:
        b -= 4
        w = _word(gen, b)
        if w & 0xff00001f == 0xb5000013:  # cbnz x19, <this code>
            return b + 4
    raise AssertionError('stale target: no cbnz x19 above %#x' % a)


def _surf_jump_request(gen, a):
    w = _word(gen, a)
    assert w & 0xfff8001f == 0x36000000  # tbz w0, #0, <no jump>
    target = a + sext((w >> 5) & 0x3fff, 14) * 4
    return ('{ extern int rt_surf_jump_request(uint64_t); '
            f'if (!(c->x[0] & 1) || !rt_surf_jump_request(c->x[19])) goto L_{target:x}; }}')


# The physics step's solver microsteps (runtime/hle/framepace.c rt_solver_steps, #161): before each Havok step the game
# gives the solver round(delta frame x 6) microsteps (1.9.0 0x700156f930): 6 at 30 fps, 3 at 60, 2 at 120. With fewer
# the solver gives way more to what is in contact with Link: holding a cucco, its body over his head held his jump
# to a third of its height above 90 fps. The runtime gives 6 / sqrt(delta frame) on shorter steps (12 at 120).

def _solver_steps(gen, a):
    assert _word(gen, a) == 0x1e220822, hex(_word(gen, a))  # fmul s2, s1, s2
    return ('{ extern float rt_solver_steps(float, float); union { uint32_t u; float f; } d = { .u = (uint32_t)c->v[1] }, '
            'k = { .u = (uint32_t)c->v[2] }; k.f = rt_solver_steps(d.f, k.f); c->v[2] = k.u; }'
            f'  /* {a:#x}: fmul s2, s1, s2 (solver microsteps: delta frame x 6) */')


# Keyframed bodies' turn (runtime/hle/framepace.c rt_kf_angle, #209): the platforms and parts the game moves (a Divine
# Beast tilting, lifts, gates) get each physics step the angular velocity that takes them to their target, the angle
# of the turn left over the step (1.9.0 0x70012d5598). That angle is 2 acos(|w|) of the turn's quaternion
# (hkQuaternion::getAngle, 0x70000b06d4): below about a milliradian w rounds to 1 in a float, and a turn that small
# reads as none. At 30 fps a tilting Vah Medoh turns its floor about 1.7 mrad a frame; at 120, 0.43: the floor stood
# still for a few steps and then caught up at once (0.08 x sqrt(1, 2, 3, 4) rad/s for a steady 0.05), and Link on it
# hopped. The runtime gives 2 atan2(|xyz|, |w|), the same angle without the rounding.

def _kf_angle(gen, a):
    assert _word(gen, a) >> 26 == 0x25, hex(_word(gen, a))  # bl (getAngle)
    target = sext(_word(gen, a) & 0x3ffffff, 26) * 4 + a
    return ('{ extern float rt_kf_angle(uint64_t); union { float f; uint32_t u; } r = { rt_kf_angle(c->x[0]) }; '
            f'c->v[0] = r.u; }}  /* {a:#x}: bl {target:#x} (keyframed body: angle of the turn left) */')


# The sound system's frame (runtime/hle/framepace.c rt_snd_frame_floor, #145): once a frame the game hands its sound
# system the delta frame, at least 0.5 (1.9.0 0x7001551004; 1.8.2 0x710143ce64 in the Ghidra project): in console
# frames, with the frame rate (30) it makes the seconds every sound timer and fade steps by. The floor is a 60 fps
# frame, so above 60 fps the sound's clock ran fast: at ~95 fps each field battle music segment started the next one
# when it was 63% through, and the segments played over each other. The floor becomes 0.5 x the frame's length in
# console frames: 0.5 at 30 fps as on the console, and the real frame at any rate (slow motion floored as there).

def _snd_frame_floor(gen, a):
    assert _word(gen, a) == 0x1e2c1001, hex(_word(gen, a))  # fmov s1, #0.5
    return ('{ extern float rt_snd_frame_floor(void); union { uint32_t u; float f; } m = { .f = rt_snd_frame_floor() }; '
            'c->v[1] = m.u; }'
            f'  /* {a:#x}: fmov s1, #0.5 (sound frame: floor of the delta frame) */')


# The menus' speed (runtime/hle/framepace.c rt_gui_speed): once a frame the game stores its integer interval x 0.5 as
# the GUI speed (the float at +0xb20 of a UI object; 1.8.2 0x700116d0e8): 1 at 30 fps, 0.5 at 60 and never lower, so
# the menus' cursor and animations ran faster above 60 fps. The runtime gives the frame's real length instead, as Cemu's
# FPS++ does on the Wii U (v208 0x03415afc).

def _gui_speed(gen, a):
    assert _word(gen, a) == 0xbd0b2100, hex(_word(gen, a))  # str s0, [x8, #0xb20]
    return ('{ extern float rt_gui_speed(float); union { uint32_t u; float f; } s = { .u = (uint32_t)c->v[0] }; '
            's.f = rt_gui_speed(s.f); ST32(c->x[8] + 0xb20, s.u); }'
            f'  /* {a:#x}: str s0, [x8, #0xb20] (GUI speed) */')


# MainShortCut's HoldShortCutBg starts P_Capture_00 transparent and has an alpha jump at frame 1. The screen
# corrects that boundary only at frame == 1 (1.9.0 0x7000e26a38). The wall-time GUI
# clock can present fractional opening frames below 1, or skip the exact value: the backdrop briefly turns black
# (#173). Apply the same alpha correction once the animation has started, leaving frame 0 and stopped animations
# alone. Keep the GUI clock unchanged so both the quick selectors and the other menus retain their normal speed.
def _quick_menu_capture_alpha(gen, a):
    w = _word(gen, a)
    assert w & 0xff00001f == 0x54000001, hex(w)  # b.ne <skip alpha correction>
    assert _word(gen, a - 4) == 0x1e212000 and _word(gen, a - 8) == 0x1e2e1001
    target = a + sext((w >> 5) & 0x7ffff, 19) * 4
    return ('{ union { uint32_t u; float f; } frame = { .u = (uint32_t)c->v[0] }; '
            f'if (!(frame.f > 0.0f)) goto L_{target:x}; }} '
            f'/* {a:#x}: b.ne (quick-menu capture alpha after animation starts) */')


# Perspective projections' matrix (sead's PerspectiveProjection, its vtable +0x58; 1.8.2 0x7000da13f4): it reads
# tan(fovy / 2) at +0xac and the aspect ratio at +0xb0 here. The runtime may change both before the matrix is built:
# a 16:9 view widened to the window's shape (ultrawide: more to the sides, not stretched) and the field of view
# (runtime/nvn/output_scale.c rt_persp).

def _persp_matrix(gen, a):
    assert _word(gen, a) == 0x2d558801, hex(_word(gen, a))  # ldp s1, s2, [x0, #0xac]
    return ('{ extern void rt_persp(uint64_t, uint32_t *, uint32_t *); uint32_t t = LD32(c->x[0] + 0xac), '
            'k = LD32(c->x[0] + 0xb0); rt_persp(c->x[0], &t, &k); c->v[1] = t; c->v[2] = k; }'
            f'  /* {a:#x}: ldp s1, s2, [x0, #0xac] (perspective matrix: tan(fovy / 2), aspect) */')


# Frustum projections' matrix (sead's FrustumProjection, its vtable +0x58; 1.8.2 0x7000da18d4): left / right at
# +0xa8 / +0xac and top / bottom at +0xa0 / +0xa4, each pair loaded twice. Some HUD layers are these (the menus'
# cursor): a 16:9 one is widened as the perspective ones are (runtime/nvn/output_scale.c rt_frustum).

def _frustum_load(word, regs, what):
    def patch(gen, a):
        assert _word(gen, a) == word, hex(_word(gen, a))
        r0, r1 = regs
        k = 0 if what == 'lr' else 2
        return ('{ extern void rt_frustum(uint64_t, float *); float f[4]; rt_frustum(c->x[0], f); '
                f'union {{ float f; uint32_t u; }} p0 = {{ f[{k}] }}, p1 = {{ f[{k + 1}] }}; '
                f'c->v[{r0}] = p0.u; c->v[{r1}] = p1.u; }}'
                f'  /* {a:#x}: ldp s{r0}, s{r1}, [x0, #{0xa8 if what == "lr" else 0xa0:#x}] (frustum matrix) */')
    return patch


# Projections' update (sead's Projection, 1.8.2 0x7000da0e18): every getter of the matrix, the device matrix and a
# point's projection makes the matrix again first when its dirty flag (+8) is set. It is taken as always set, so every
# matrix follows the window's shape and the field of view now (runtime/nvn/output_scale.c rt_persp): one made before
# the first frame, or before a change, stayed as it was (the menus' cursor is drawn by a HUD layer made at startup).

def _proj_update(gen, a):
    assert _word(gen, a) == 0x39402008, hex(_word(gen, a))  # ldrb w8, [x0, #8]
    return f'c->x[8] = 1;  /* {a:#x}: ldrb w8, [x0, #8] (projection update: dirty, always) */'


# ... and its load of the view's offset (+0xb4 x, +0xb8 y: a frustum moved by a fraction of its width and height; the
# inventory's Link is drawn to the right that way), which the widened view takes as a fraction of its 16:9 part
# (runtime/nvn/output_scale.c rt_persp_offset).

def _persp_matrix_offset(gen, a):
    assert _word(gen, a) == 0x2d569404, hex(_word(gen, a))  # ldp s4, s5, [x0, #0xb4]
    return ('{ extern void rt_persp_offset(uint64_t, uint32_t *, uint32_t *); uint32_t x = LD32(c->x[0] + 0xb4), '
            'y = LD32(c->x[0] + 0xb8); rt_persp_offset(c->x[0], &x, &y); c->v[4] = x; c->v[5] = y; }'
            f'  /* {a:#x}: ldp s4, s5, [x0, #0xb4] (perspective matrix: offset) */')


# Perspective projections' screen position to camera position (their vtable +0x68; 1.8.2 0x7000da14c0): the game
# places some things on screen with it (the menus' cursor corners), so it takes the same widened view as the matrix.

def _persp_unproject_y(gen, a):
    assert _word(gen, a) == 0xbd40ac01, hex(_word(gen, a))  # ldr s1, [x0, #0xac]
    return ('{ extern void rt_persp(uint64_t, uint32_t *, uint32_t *); uint32_t t = LD32(c->x[0] + 0xac), '
            'k = LD32(c->x[0] + 0xb0); rt_persp(c->x[0], &t, &k); c->v[1] = t; }'
            f'  /* {a:#x}: ldr s1, [x0, #0xac] (screen to camera: tan(fovy / 2)) */')


def _persp_unproject_x(gen, a):
    assert _word(gen, a) == 0x2d558c02, hex(_word(gen, a))  # ldp s2, s3, [x0, #0xac]
    return ('{ extern void rt_persp(uint64_t, uint32_t *, uint32_t *); uint32_t t = LD32(c->x[0] + 0xac), '
            'k = LD32(c->x[0] + 0xb0); rt_persp(c->x[0], &t, &k); c->v[2] = t; c->v[3] = k; }'
            f'  /* {a:#x}: ldp s2, s3, [x0, #0xac] (screen to camera: tan(fovy / 2), aspect) */')


# The mouse camera (runtime/hle/input.c). Every camera action (CameraChase, CameraAiming, CameraHorse...) reads the
# right stick through one function (1.9.0 0x7000d57fe0), which applies a dead zone, squares the tilt (v |v|) and
# keeps it in the unit circle; the chase-like ones (CameraChase, CameraShieldSurfing, CameraWakeboard) square the
# vertical part once more (y |y|). The camera then turns by that x its speeds x the frame's length (VFR). Fine for a
# stick; from the mouse it crept on slow moves, sped up on fast ones and stopped at the stick's top speed. While the
# mouse has the camera the runtime answers the stick input itself (rt_cam_stick: the frame's mouse motion over the
# frame's length, linear, not clamped) and the vertical part goes through unsquared (rt_cam_pitch), so a frame's turn
# is the mouse's motion in it times the sensitivity, at any frame rate. The cameras turn the horizontal part 1.78
# times as fast as the vertical one for a stick, and the bow's (CameraAiming) and a held item's (CameraAiming2) scale
# them apart again (lngStickScale 0.7 and latStickScale 1; 0.8 and 1.5): the runtime gives the vertical part 1.78
# times the mouse's motion, and those two cameras' vertical part the horizontal part's scale (rt_cam_pitch_scale), so
# the mouse turns both alike. Optional sites (tools/game_sites.py OPTIONAL_GROUPS): without them the mouse moves the
# stick, as before.

def _cam_stick(gen, a):
    assert _word(gen, a) == _sub_sp(0x30), hex(_word(gen, a))
    return ('{ extern int rt_cam_stick(uint64_t, uint64_t); if (rt_cam_stick(c->x[0], c->x[30])) return; '
            'c->sp -= 0x30; }'
            f'  /* {a:#x}: sub sp, sp, #0x30 (camera stick input) */')


def _cam_pitch(gen, a):
    # fmul s1, s0, s0 just above, fnmul s3, s0, s0 here: the vertical part kept its sign squared, s1 or s3 by s0's sign
    assert _word(gen, a) == 0x1e208803 and _word(gen, a - 4) == 0x1e200801, hex(_word(gen, a))
    return ('{ extern int rt_cam_pitch(float *); union { uint32_t u; float f; } y = { .u = (uint32_t)c->v[0] }; '
            'if (rt_cam_pitch(&y.f)) c->v[1] = y.u; else y.f = -(y.f * y.f); c->v[3] = y.u; }'
            f'  /* {a:#x}: fnmul s3, s0, s0 (camera: the vertical stick part squared) */')


def _cam_pitch_aim(gen, a):
    # ldr s1, [x8]: the camera's latStickScale, through the parameter pointer loaded just above (ldr x8, [x19, #off]);
    # its lngStickScale's pointer is the next one (the parameters load in that order)
    assert _word(gen, a) == 0xbd400101, hex(_word(gen, a))
    w = next(_word(gen, a - 4 * i) for i in range(1, 5) if _word(gen, a - 4 * i) & 0xffc003ff == 0xf9400268)
    lng = ((w >> 10) & 0xfff) * 8 + 8
    return ('{ extern uint32_t rt_cam_pitch_scale(uint32_t, uint32_t); '
            f'c->v[1] = rt_cam_pitch_scale(LD32(c->x[8]), LD32(LD64(c->x[19] + {lng:#x}))); }}'
            f'  /* {a:#x}: ldr s1, [x8] (camera: latStickScale) */')


# The game's Camera X-axis / Y-axis options (Inverted) are applied by the cameras' controller (the one the camera
# input reads, id 3 of the controller manager): every frame it reads the flags (CameraRLReverse, CameraUpDownReverse)
# and turns that axis of its right stick around. The mouse's camera input doesn't go through it, so the runtime is
# told the flags here and turns the mouse's motion around the same way (rt_cam_reverse).

def _cam_reverse(axis):
    def patch(gen, a):
        w = _word(gen, a)
        assert w >> 26 == 0x25, hex(w)  # bl <the flag's getter>
        t = a + sext(w & 0x3FFFFFF, 26) * 4
        return (f'{{ extern void f_{t:x}(Cpu *); extern void rt_cam_reverse(int, int); c->x[30] = {a + 4:#x}ull; '
                f'f_{t:x}(c); rt_cam_reverse({axis}, (int)(c->x[0] & 1)); }}'
                f'  /* {a:#x}: bl {t:#x} (camera controller: {"XY"[axis]}-axis inverted) */')
    return patch


def _pc_button_group(gen, a):
    assert _word(gen, a) == _sub_sp(0x60), hex(_word(gen, a))
    return ('{ extern void rt_pc_button_group(Cpu *); rt_pc_button_group(c); c->sp -= 0x60; }'
            f' /* {a:#x}: native mouse pointer arguments */')

def _pc_cursor_manager(gen, a):
    assert _word(gen, a) == _sub_sp(0x50), hex(_word(gen, a))
    return ('{ extern void rt_pc_cursor_manager(Cpu *, uint64_t, uint64_t); '
            f'rt_pc_cursor_manager(c, {gen.sites["pc_cursor_activate"]:#x}ull, {gen.sites["pc_pane_bounds"]:#x}ull); '
            'c->sp -= 0x50; }')

def _pc_map_focus(position):
    def patch(gen, a):
        expected = _sub_sp(0x30) if position else 0xa9be7bfd
        assert _word(gen, a) == expected, hex(_word(gen, a))
        prologue = 'c->sp -= 0x30;' if position else 'c->sp -= 0x20; ST64(c->sp, c->x[29]); ST64(c->sp + 8, c->x[30]);'
        return ('{ extern int rt_pc_map_focus(Cpu *, int); '
                f'if (rt_pc_map_focus(c, {int(position)})) return; {prologue} }}')
    return patch

# Placed actors' traverse distance (1.9.0 0x70010a4640, 1.8.2 0x7000f908b0): how far from the camera an actor placed
# on the map is created (trees and bushes 150 m, rocks and buildings 300-3000 m, the full model of a building with a
# "_Far" version ~500 m, enemies 150 m). It is the actor's traverseDist (ActorInfo; 100 when unset) times a scale: the
# float at +0x310 of the actor debug manager (the object at 1.9.0 0x7001e39348, made only when its "ActorDebug" heap
# exists, which the released game doesn't have), or 1 without it. Every placed actor's distance goes through here.
# Video > Draw distance multiplies that scale, on both paths (runtime/draw_distance.c rt_traverse_scale; Original:
# the game's own).

def _traverse_scale(gen, a):
    assert _word(gen, a) == 0xbd431101, hex(_word(gen, a))  # ldr s1, [x8, #0x310]
    return ('{ extern uint32_t rt_traverse_scale(uint32_t, uint32_t); '
            'c->v[1] = rt_traverse_scale(LD32(c->x[8] + 0x310), (uint32_t)c->v[0]); }'
            f'  /* {a:#x}: ldr s1, [x8, #0x310] (placement: traverse distance scale) */')


def _traverse_scale_default(gen, a):
    assert _word(gen, a) == 0x1e2e1001, hex(_word(gen, a))  # fmov s1, #1.0
    return ('{ extern uint32_t rt_traverse_scale(uint32_t, uint32_t); '
            'c->v[1] = rt_traverse_scale(0x3f800000u, (uint32_t)c->v[0]); }'
            f'  /* {a:#x}: fmov s1, #1.0 (placement: traverse distance scale, no debug manager) */')


# The grass's view context (1.9.0 0x70013ad8b0, 1.8.2 0x70012999d0): both grass layers (blades, and the crossed
# quads) build it every frame from the camera (x2; s3 is the layer's cell size, 3 m or 10 m). s1 and s2 are
# screen-size limits (in 1.9.0's play: blades 0.0858 and 2, crossed quads 0.0162 and 0.186) that give the region the
# layer makes and lists its cells in: about 1 / (max(tan(fovy / 2), s0) * s1), s0 = tan(10 deg), out to at most
# 1 / (s0 * s1) (a narrow view, the scope: 66 m for the blades, inside their +-69 m grid). Video > Draw distance takes
# the blades' region further by dividing both limits by their factor and multiplying s0 by it, which keeps that
# most where it was (runtime/draw_distance.c rt_grass_range; Original: the game's own).

def _grass_range(gen, a):
    assert _word(gen, a) == 0xbd400024, hex(_word(gen, a))  # ldr s4, [x1]
    return ('{ extern int rt_grass_range(uint64_t, uint32_t, uint32_t *, uint32_t *, uint32_t *); '
            'uint32_t s0 = (uint32_t)c->v[0], '
            's1 = (uint32_t)c->v[1], s2 = (uint32_t)c->v[2]; '
            'if (rt_grass_range(c->x[2], (uint32_t)c->v[3], &s0, &s1, &s2)) { c->v[0] = s0; c->v[1] = s1; c->v[2] = s2; } '
            'c->v[4] = LD32(c->x[1]); }'
            f'  /* {a:#x}: ldr s4, [x1] (grass view context: its screen-size limits) */')


# ... and how each grass layer fades out: by cell, from 1 / (k * distance), with k = max(the camera's tan(fovy / 2)
# at +0x170, tan(10 deg)) stored once a frame (blades: +0x373e8 of their manager, 1.9.0 0x70013a85d0; crossed quads:
# +0x4fdb8, 0x70013baa5c). The blades fade from about 8 m to 21.5 m (clamp((1 / (k d) - 0.1) / 0.17), k = 0.466 in
# play), the crossed quads out to about 46 m. Every reader of k is a fade of that kind, so a smaller k fades the same
# grass that many times further out (runtime/draw_distance.c rt_grass_fade; Original: the game's own).

def _grass_fade(base, off):
    def patch(gen, a):
        want = 0xbd000000 | ((off // 4) << 10) | (base << 5)  # str s0, [x<base>, #off]
        assert _word(gen, a) == want, hex(_word(gen, a))
        fn = 'rt_grass_fade_blades' if off == 0x240 else 'rt_grass_fade_quads'
        return (f'{{ extern uint32_t {fn}(uint64_t, uint32_t); '
                f'ST32(c->x[{base}] + {off:#x}, {fn}(c->x[{base}] + {off:#x} - {0x373e8 if off == 0x240 else 0x4fdb8:#x}, (uint32_t)c->v[0])); }}'
                f'  /* {a:#x}: str s0, [x{base}, #{off:#x}] (grass: its fades\' camera scale) */')
    return patch


# The blades' draw slots: their manager makes 256 at boot (1.9.0 0x70013a7230, `mov w1, #0x100` before the array's
# creation; each slot a 2 x 800-byte shader block), its main pass draws its nearest cells into as many as there are,
# and two other passes stop at the 256th cell (0x70013b32e0, 0x7001496c40: `cmp wN, #0xff; b.hi`). A blade region
# 2.5 times the game's needs more: runtime/draw_distance.c rt_grass_blade_slots makes 512 when the game starts at
# High (Original and Medium: the game's 256, and the two passes as the game has them).

def _grass_blade_slots(gen, a):
    assert _word(gen, a) == 0x52802001, hex(_word(gen, a))  # mov w1, #0x100
    return ('{ extern uint32_t rt_grass_blade_slots(uint32_t); c->x[1] = rt_grass_blade_slots(0x100); }'
            f'  /* {a:#x}: mov w1, #0x100 (grass blades: draw slots) */')


def _grass_blade_cap(gen, a, fn='rt_grass_blade_cap'):
    w = _word(gen, a)
    assert w & 0xfffffc1f == 0x7103fc1f, hex(w)  # cmp wN, #0xff
    n = (w >> 5) & 31
    return (f'{{ extern uint32_t {fn}(void); '
            f'(void)(subs32(c, (uint32_t)c->x[{n}], {fn}())); }}'
            f'  /* {a:#x}: cmp w{n}, #0xff (grass blades: the last draw slot) */')


# The per-frame pass that points each draw slot at this frame's half of its double-buffered shader block (1.9.0
# 0x70013ae920: for the drawn cells, at most 256 of them, `cmp w8, #0xff; ...; mov w9, #0xff; csel`) has the same cap.
# With 512 slots and more than 256 cells drawn, the slots past the 256th kept last frame's half: the cells drawn there
# alternated between this frame's grass and the one from two frames before, every frame (round 4: a flicker at
# High only, seen near Link and in the far grass). Its count and its clamp now stop at the last slot.

def _grass_blade_cap_swap(gen, a):
    return _grass_blade_cap(gen, a, 'rt_grass_blade_swap_cap')


def _grass_blade_cap_max(gen, a):
    w = _word(gen, a)
    assert w & 0xffffffe0 == 0x52801fe0, hex(w)  # mov wN, #0xff
    n = w & 31
    return ('{ extern uint32_t rt_grass_blade_swap_cap(void); '
            f'c->x[{n}] = rt_grass_blade_swap_cap(); }}'
            f'  /* {a:#x}: mov w{n}, #0xff (grass blades: the last draw slot) */')


# The blades' region test, per cell of their grid as their update lists them (1.9.0 0x70013a8eec..): the cell's offset
# from the camera (x s9, z s13, squared distance s21), the view direction (a, b at sp+0x204, sp+0x208), its distance
# from the view's axis (s0 = |a z - b x|), then `fcmp s0, s6` (the near part's half width + 1.5 m) and `fcmp s0, s7`
# (the far part's). The parts are slabs as wide as the view is at their end, so a region 2.5 times as deep lists
# about 760 cells at 60 m and the list holds 512. runtime/draw_distance.c rt_grass_blade_lateral narrows them, only
# past the game's own near distance and only at High, to a cone a little wider than the view: the cells the game
# lists itself stay listed, and the region reaches further within the list.

def _grass_blade_lateral(gen, a):
    w = _word(gen, a)
    assert w in (0x1e262000, 0x1e272000), hex(w)  # fcmp s0, s6 / fcmp s0, s7
    n = (w >> 16) & 31
    return ('{ extern float rt_grass_blade_lateral(int, float, float, float, float, uint32_t, uint32_t); '
            f'c->nzcv = cmp_s(c, VSF32(0), rt_grass_blade_lateral({n - 6}, VSF32({n}), VSF32(9), VSF32(13), VSF32(21), '
            'LD32(c->sp + 0x204), LD32(c->sp + 0x208))); }'
            f'  /* {a:#x}: fcmp s0, s{n} (grass blades: a cell inside the region\'s width) */')


# The terrain's distant trees (tera::Core::Tree, 1.9.0 0x70013c94ac, 1.8.2 0x70012b55cc: its per-frame shader setup).
# The trees past the actor trees are drawn by the terrain, from where it fades them in (+0x14cb0, 100 m; +0x14cb4 the
# fade, 100 m) out to +0x14cb8 (4000 m, fading over the last +0x14cbc, 500 m; +0x14cc0, 4000 m, where its blocks
# change detail). The constructor sets them, and the game writes them again as it plays (about twice a frame; the end
# is sometimes 4444.5 m); this setup and the per-frame update (1.9.0 0x70013c8898) read them. Video > Draw distance
# sets them at the setup's entry, from the game's latest values times its factor (runtime/draw_distance.c
# rt_tree_ranges; Original: the game's own).

def _tree_ranges(gen, a):
    w = _word(gen, a)
    assert w & 0x9f00001f == 0x90000008, hex(w)  # adrp x8, <page>
    page = adrp_page(w, a)
    return (f'{{ extern void rt_tree_ranges(uint64_t); rt_tree_ranges(c->x[0]); c->x[8] = {page:#x}ull; }}'
            f'  /* {a:#x}: adrp x8, {page:#x} (distant trees: their ranges) */')


# Accessibility > Infinite arrows (runtime/assists.c rt_infinite_arrows). The pause menu data's arrow removal (1.9.0
# 0x7000d93814; x0 the pause menu data, x1 the arrow's name, w2 how many) returns at once when the actor info doesn't
# tag the item 0x19f6c13a (an arrow), else takes the count off the pouch's arrows of that name (each item's count at
# +0x20; a stack that runs out goes to 0 and the rest comes off the next) and writes the counts to the game data
# (PorchItem_Value1). Two places reach it, both for a bow the player holds: the bow's shot (1.9.0 0x700092ddb4) and a
# weapon function that takes one arrow (its tail call at 0x70007fe9f8, after the weapon's vtable +0x4e8 says the
# player holds it). With the option on it returns before taking any; the shot itself still needs an arrow in the pouch.

def _remove_arrows(gen, a):
    assert _word(gen, a) == _sub_sp(0x70), hex(_word(gen, a))
    return ('{ extern int rt_infinite_arrows(void); if (rt_infinite_arrows()) return; c->sp -= 0x70; }'
            f'  /* {a:#x}: sub sp, sp, #0x70 (remove arrows: none with Infinite arrows) */')


# Accessibility > Unbreakable weapons (runtime/assists.c rt_keep_wear, rt_no_wear; from #296). The pouch's setter for
# an equipped item's value (type w22: 0 weapon, 1 bow, 2 arrows, 3 shield; new value w20; the item x11, value at
# +0x20) is where a hit's wear lands, in hundredths (1700 = 17). The runtime keeps the old value when the new one is
# lower.

def _no_wear(gen, a):
    assert _word(gen, a) == 0xb9002174, hex(_word(gen, a))  # str w20, [x11, #0x20]
    return ('{ extern int rt_keep_wear(uint32_t, int32_t, int32_t); '
            'if (!rt_keep_wear((uint32_t)c->x[22], (int32_t)c->x[20], (int32_t)LD32(c->x[11] + 0x20))) '
            'ST32(c->x[11] + 0x20, c->x[20]); }'
            f'  /* {a:#x}: str w20, [x11, #0x20] (equipped item value: no wear) */')


# Every life goes through one method (1.9.0 0x7000b952b8, 1.8.2 0x7000a81da8; x1 the life, a copy the caller stores):
# every frame, for everything that has one, it takes the cost of the frame's hits (w9) off the life (w8) with
# `sub w8, w8, w9`. The saved return address, at sp + 0x28, tells whose life it is: a weapon's durability, in
# hundredths, when the call comes from the weapon's update (no_wear_ret, from #296: Unbreakable weapons, the actor's
# own copy, which is what breaks); Link's hearts when it comes from his damage handling (the call just before
# link_life_store; his losses are left to _link_life); anything else's otherwise (One-hit kill, the damage dealt).
# runtime/assists.c rt_life_cost. Without Link's sites every call that isn't a weapon's counts as his.

def _no_wear_hit(gen, a):
    assert _word(gen, a) == 0x4b090108, hex(_word(gen, a))  # sub w8, w8, w9
    wret = gen.sites['no_wear_ret']
    if 'link_life_store' in gen.sites:
        s = gen.sites['link_life_store']
        bl = _word(gen, s - 0x20)  # (Link's call of this method: bl, then 6 instructions to the store)
        assert bl >> 26 == 0x25 and 0 <= a - (s - 0x20 + sext(bl & 0x3FFFFFF, 26) * 4) < 0x400, hex(bl)
        whose = f'r == {wret:#x}ull ? 1 : r == {s - 0x1c:#x}ull ? 2 : 0'
    else:
        whose = f'r == {wret:#x}ull ? 1 : 2'
    return ('{ extern uint32_t rt_life_cost(uint32_t, int32_t, int); uint64_t r = LD64(c->sp + 0x28); '
            f'c->x[8] = (uint32_t)((uint32_t)c->x[8] - rt_life_cost((uint32_t)c->x[9], (int32_t)c->x[8], {whose})); }}'
            f'  /* {a:#x}: sub w8, w8, w9 (a life\'s hit: Accessibility) */')


# Link's damage handling (1.9.0 0x7000cc4c3c; x21 his life, in quarter hearts) works on a copy of it (w25, also at
# sp + 0xc): the frame's hits through the method above, a few cases of its own (one quarter, four, the death path,
# which may leave one quarter), and stores the copy at its end (link_life_store, `str w25, [x21]`); another path takes
# one quarter off and stores it at once (link_life_tick, `str w8, [x21]`). God mode keeps the old life, Damage taken
# scales the loss (runtime/assists.c rt_link_life); the copy gets the same value, so what follows sees it.

def _link_life(gen, a):
    w = _word(gen, a)
    if w == 0xb90002b9:  # str w25, [x21]
        return ('{ extern int32_t rt_link_life(int32_t, int32_t); '
                'int32_t v = rt_link_life((int32_t)LD32(c->x[21]), (int32_t)c->x[25]); '
                'c->x[25] = (uint32_t)v; ST32(c->sp + 0xc, (uint32_t)v); ST32(c->x[21], (uint32_t)v); }'
                f'  /* {a:#x}: str w25, [x21] (Link\'s life: Accessibility) */')
    assert w == 0xb90002a8, hex(w)  # str w8, [x21]
    return ('{ extern int32_t rt_link_life(int32_t, int32_t); '
            'c->x[8] = (uint32_t)rt_link_life((int32_t)LD32(c->x[21]), (int32_t)c->x[8]); ST32(c->x[21], c->x[8]); }'
            f'  /* {a:#x}: str w8, [x21] (Link\'s life: Accessibility) */')


# Accessibility > Infinite stamina (runtime/assists.c rt_stamina): the stamina setter (1.9.0 0x7000cc7410; x0
# PlayerInfo, s0 the new stamina, 1000 a wheel) stores it at +0xa4; with the option on a lower value isn't stored.

def _stamina(gen, a):
    assert _word(gen, a) == 0xbd00a668, hex(_word(gen, a))  # str s8, [x19, #0xa4]
    return ('{ extern uint32_t rt_stamina(uint32_t, uint32_t); '
            'ST32(c->x[19] + 0xa4, rt_stamina(LD32(c->x[19] + 0xa4), (uint32_t)c->v[8])); }'
            f'  /* {a:#x}: str s8, [x19, #0xa4] (stamina: Accessibility) */')


# tools/game_sites.py site -> its patch
# BOTW's streaming Yaz0 decoder (1.9.0 0x700131d674; x0 its state, x1/w2 the input chunk): in native code
# (runtime/hle/yaz0.c rt_yaz0, which declines the first call of a stream, the one that reads its header). Its return
# instruction checks the native result against the game's code with SAVAGEWIND_YAZ0=2.
def _yaz0_stream(gen, a):
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]!
    return ('{ extern int rt_yaz0(Cpu *); if (rt_yaz0(c)) return; '
            'uint64_t ea = c->sp - 0x30; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); c->sp = ea; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (Yaz0 stream decoder) */')


def _yaz0_stream_ret(gen, a):
    assert _word(gen, a) == 0xd65f03c0, hex(_word(gen, a))  # ret
    return '{ extern void rt_yaz0_done(Cpu *); rt_yaz0_done(c); return; }' + f'  /* {a:#x}: ret (Yaz0 stream decoder) */'


# A shrine apparatus (DungeonRotateGyro::calc_, 1.9.0): the call that fetches the mechanism's input, then a heartbeat
# with the mechanism (x19) and what the call returned (x0), so runtime/pc_gyro_scene.c knows the player controls one.
def _gyro_scene_actor(gen, a):
    w = _word(gen, a)
    assert w >> 26 == 0x25, hex(w)  # bl
    t = a + sext(w & 0x3ffffff, 26) * 4
    return (f'{{ extern void f_{t:x}(Cpu *); extern void rt_gyro_scene_actor(Cpu *, uint64_t, uint64_t); '
            f'c->x[30] = {a + 4:#x}ull; f_{t:x}(c); rt_gyro_scene_actor(c, c->x[19], c->x[0]); }}'
            f'  /* {a:#x}: bl (shrine apparatus input) */')


# Per-action bindings (runtime/hle/bindings.c, docs/ACTIONS.md). The game reads its pad object through two functions,
# isHold(pad, action) and isTrig(pad, action): each looks the action's pad mask up in a table of 41 (act_masks) and tests
# it against the pad object's held (+0x11c) or pressed (+0x10) word. An action the player gave a binding of its own is
# answered by the runtime from the host key / button instead (rt_act_query); every other answer stays the game's.
def _act_query(kind):
    def patch(gen, a):
        assert _word(gen, a) == 0xa9be7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x20]!
        return ('{ extern int rt_act_query(int, uint64_t, uint64_t, uint64_t, uint64_t); '
                f'int r = rt_act_query({kind}, c->x[0], c->x[1], c->x[30], {gen.sites["act_masks"]:#x}ull); '
                'if (r >= 0) { c->x[0] = (uint64_t)r; return; } '
                'uint64_t ea = c->sp - 0x20; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); c->sp = ea; }'
                f'  /* {a:#x}: stp x29, x30, [sp, #-0x20]! ({"pressed" if kind else "held"} query of an action) */')
    return patch


# The free camera (runtime/hle/freecam.c rt_lookat): sead::LookAtCamera::doUpdateMatrix (1.9.0 0x7000eb2d5c) builds
# a camera's view from its eye (+0x38), at (+0x44) and up (+0x50); the runtime sees each camera there first and may
# put its own eye and at in place before they are read.

def _lookat_update(gen, a):
    assert _word(gen, a) == 0x2d470801, hex(_word(gen, a))  # ldp s1, s2, [x0, #0x38]
    return ('{ extern void rt_lookat(uint64_t); rt_lookat(c->x[0]); c->v[1] = LD32(c->x[0] + 0x38); '
            'c->v[2] = LD32(c->x[0] + 0x3c); }'
            f'  /* {a:#x}: ldp s1, s2, [x0, #0x38] (LookAtCamera view: eye x, y) */')


# Cursour(agl debug)'s setup (game_sites.py debug_cursor_pool_guard): its load of the debug cursor's pool object
# (+0x70, empty on machines where the game never maps the pool it asked the system for: issue #472's crash before
# the first frame). Guard it: with no pool object, hand the game its own null and take the device call's own null
# path — the `cbz x0` twelve words ahead skips to its target, past the cursor's whole setup, and the function
# returns as the game's release build returns it, the debug cursor never made and nothing dereferenced again.
def _debug_cursor_pool_guard(gen, a):
    assert _word(gen, a) == 0xf9403a60, hex(_word(gen, a))  # ldr x0, [x19, #0x70]
    w = _word(gen, a + 0x14)
    assert w & 0xFC00001F == 0xB4000000, hex(w)  # the skip: cbz x0, <the setup's end>
    skip = a + 0x14 + sext((w >> 5) & 0x7FFFF, 19) * 4
    return (f'{{ uint64_t pool = LD64(c->x[19] + 0x70); c->x[0] = pool; '
            f'if (!pool) goto L_{skip:x}; }}'
            f'  /* {a:#x}: ldr x0, [x19, #0x70] (Cursour debug: pool object, guarded) */')


# The same cursor's pane update (game_sites.py debug_cursor_pane_guard), one step past the pool guard: the pool
# guard skips the cursor's whole setup, so the cursor is never made and the pane its boot chain passes as x1 — the
# caller's [param+0x20], a slot its ctor never writes — stays empty; the update's first load through the pane (its
# vtable) faults dereferencing 0. Guard the entry before any stack frame is pushed: with no pane return 0 (nothing
# drawn) straight from the entry, landing in the caller's own pane-less path right after its call, as the guest's
# own `cbz` exit takes it. The pool guard alone would fault again on every such update, not just the boot one.
def _debug_cursor_pane_guard(gen, a):
    assert _word(gen, a) == 0xa9ba7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x60]!
    return ('{ if (!c->x[1]) { c->x[0] = 0; return; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x60]! (Cursour debug: pane update, guarded) */')


# seadDebugMenuSystem's page functions (game_sites.py debug_menu_* guards, tools/patches.py): one step past the
# debug cursor the pool guard skips, the debug menu's page-lookup functions look a page or item up by its key's
# name — the char* at [key+8]. The menu init the boot never completed left the keys it builds with a null name,
# and every one of these dereferences faults on 0 (run32's crash: the page find's own string compare). Each guard
# re-checks the pointer the guest just loaded and takes that function's own empty-name path — the branch its byte
# check would take for a "" name — which is the answer for a name that isn't there at all.


def _debug_menu_key_guard(gen, a):
    # the page find's entry (f_7000f29f4c): its load of the key's name (x19 = the key) for the byte-by-byte hash
    # loop that computes the search hash; with no name the game's cbz skips the loop and the hash comes out 0
    assert _word(gen, a) == 0xf9400669, hex(_word(gen, a))  # ldr x9, [x19, #8]
    w = _word(gen, a + 8)
    assert w & 0xFC000000 in (0xB4000000, 0x34000000), hex(w)  # the empty name's skip: cbz w8, <hash 0>
    skip = a + 8 + sext((w >> 5) & 0x7FFFF, 19) * 4
    return (f'{{ uint64_t nm = LD64(c->x[19] + 8); c->x[9] = nm; if (!nm) goto L_{skip:x}; }}'
            f'  /* {a:#x}: ldr x9, [x19, #8] (Debug menu page find: key name, guarded) */')


def _debug_menu_len_guard(gen, a):
    # the same find, its second key-name load (x21): the key's virtual name getter call and the same-pointer
    # compare after it would take a null as a name, so treat it as the mismatch its compare loop reports for a
    # name different from the page's — advance the search, which lands in the game's not-found answer
    assert _word(gen, a) == 0xf9400675, hex(_word(gen, a))  # ldr x21, [x19, #8]
    assert _word(gen, a + 4) == 0xf9400d08, hex(_word(gen, a + 4))  # ldr x8, [x8, #0x18] (the key's getter)
    return ('{ uint64_t nm = LD64(c->x[19] + 8); c->x[21] = nm; if (!nm) goto L_7000f2a1cc; }'
            f'  /* {a:#x}: ldr x21, [x19, #8] (Debug menu page find: key name, guarded) */')


def _debug_menu_page_guard(gen, a):
    # the same find's byte-by-byte string compare, re-loading the key's name: run32's fault (the compare loop's
    # first byte load dereferences 0); with no name take the compare's not-equal branch — advance the search to
    # the next slot, landing in the game's own not-found answer once the binary search runs out
    assert _word(gen, a) == 0xf9400669, hex(_word(gen, a))  # ldr x9, [x19, #8]
    assert _word(gen, a + 4) == 0xaa1b03ea, hex(_word(gen, a + 4))  # mov x10, x27 (the compare loop's bound)
    return ('{ uint64_t nm = LD64(c->x[19] + 8); c->x[9] = nm; if (!nm) goto L_7000f2a1cc; }'
            f'  /* {a:#x}: ldr x9, [x19, #8] (Debug menu page find: compare, guarded) */')


def _debug_menu_cand_guard(gen, a):
    # the same compare's other side (run33's fault, one step past the key guards): its load of the candidate
    # page's name the page getter just returned into the temp at [sp+8] — the static page table's entries carry
    # unpopulated names too, so that read-back can be 0, and the compare's byte load of it dereferences 0. With
    # no candidate name the key (which the guards above already proved present) cannot equal it: take the
    # compare's not-equal branch, exactly as the loop's first mismatch would. (The key-name guard rules out the
    # both-null same-pointer match this skips; the search ends in its not-found answer either way.)
    assert _word(gen, a) == 0xf94007e8, hex(_word(gen, a))  # ldr x8, [sp, #8]
    assert _word(gen, a + 4) == 0xeb0802bf, hex(_word(gen, a + 4))  # cmp x21, x8 (the same-pointer test)
    return ('{ uint64_t nm = LD64(c->sp + 8); c->x[8] = nm; if (!nm) goto L_7000f2a1cc; }'
            f'  /* {a:#x}: ldr x8, [sp, #8] (Debug menu page find: candidate name, guarded) */')


def _debug_menu_path_guard(gen, a):
    # the page name's '/'-splitting helper (f_7000f2a1f0): its load of the key's name (x2 = the key); its
    # empty-name answer is return true with page 0 written to the out param (x19 = x1, set by the next guest
    # instruction — the guard does it too, since it jumps the byte check that would have)
    assert _word(gen, a) == 0xf9400448, hex(_word(gen, a))  # ldr x8, [x2, #8]
    assert _word(gen, a + 4) == 0xaa0103f3, hex(_word(gen, a + 4))  # mov x19, x1 (the out param)
    return ('{ uint64_t nm = LD64(c->x[2] + 8); c->x[8] = nm; c->x[19] = c->x[1]; '
            'if (!nm) goto L_7000f2a284; }'
            f'  /* {a:#x}: ldr x8, [x2, #8] (Debug menu page split: key name, guarded) */')


def _debug_menu_hash_guard(gen, a):
    # the lookup that hashes the key's name itself (f_7000f2a484): its load of the name (x21 = the key) into the
    # hash loop; the empty-name path is the loop's own answer for nothing to hash (hash 0, L_7000f2a504)
    assert _word(gen, a) == 0xf94006a9, hex(_word(gen, a))  # ldr x9, [x21, #8]
    assert _word(gen, a + 4) == 0x39400128, hex(_word(gen, a + 4))  # ldrb w8, [x9] (the loop's byte load)
    return ('{ uint64_t nm = LD64(c->x[21] + 8); c->x[9] = nm; if (!nm) goto L_7000f2a504; }'
            f'  /* {a:#x}: ldr x9, [x21, #8] (Debug menu page hash: key name, guarded) */')


# The title screen's first shader link (game_sites.py shader_queue_guard, tools/patches.py _shader_queue_guard):
# f_700106ecd4 takes the agl ShaderHolder singleton's queue member ([holder+0x28]) — empty where the boot never
# filled it — and f_7000f9e384's first load through it ([queue+0x2d8], the linked-program count) faults on 0
# (run34's crash: `accessing 0x2d8`). The count-load's own <1 exit is the game's answer for a queue with nothing
# in it; the guard takes it with a null queue, and the function returns as it returns for an empty queue.

def _shader_queue_guard(gen, a):
    assert _word(gen, a) == 0xb942dada, hex(_word(gen, a))  # ldr w26, [x22, #0x2d8]
    assert _word(gen, a + 4) == 0x7100075f, hex(_word(gen, a + 4))  # cmp w26, #1
    w = _word(gen, a + 8)
    assert w & 0xFC000000 == 0x54000000, hex(w)  # the count < 1 exit: b.lt <the epilogue>
    skip = a + 8 + sext((w >> 5) & 0x7FFFF, 19) * 4
    return (f'{{ uint64_t q = c->x[22]; if (!q) {{ c->x[0] = 0; goto L_{skip:x}; }} '
            f'c->x[26] = LD32(q + 0x2d8); }}'
            f'  /* {a:#x}: ldr w26, [x22, #0x2d8] (agl ShaderHolder queue, guarded) */')


# The debug menu's entry registration (game_sites.py debug_menu_reg_* guards, tools/patches.py): run35's crash —
# the title's registration step (f_700125682c) hands the two registration wrappers a null table object: the debug
# menu whose init the boot never completed reports 0 entries ([x21+0x38]), and the caller's csel turns that into
# xzr (the table the menu never built). The wrappers add the table's entry-vector members — +0x288 and +0x2b8 —
# to it and pass the result to their fill twins (f_7000ec8eb8/f_7000ec8f4c), whose first store writes the entry
# count straight through it: str w20,[x19] on 0x2b8 was the fault. The third sibling f_7000ec7708 takes the same
# table directly and loads that +0x2b8 count as its first word. Guard each at the entry, before the frame is
# pushed: with no table there is nothing to register — return, the guest's ret, the wrappers' and the copy
# variant's results ignored by every caller (their 104/105/294 bl sites); the fill twins are only ever called
# from inside the wrappers, so the null table is never dereferenced again. The fall-through replays the pushed-
# frame prologue (the pre-index stp's writeback and x29/x30 stores) so the real tables are untouched.


def _debug_menu_reg_288_guard(gen, a):
    # f_7000ec74d8: entry guard on its first stp, pinned by the table+0x288 add six words in
    assert _word(gen, a) == 0xa9bc7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x40]!
    assert _word(gen, a + 0x18) == 0x910a2000, hex(_word(gen, a + 0x18))  # add x0, x0, #0x288 (the entry vector)
    return ('{ if (!c->x[0]) return; c->sp -= 0x40; ST64(c->sp, c->x[29]); ST64(c->sp + 8, c->x[30]); }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x40]! (Debug menu reg +0x288: table, guarded) */')


def _debug_menu_reg_2b8_guard(gen, a):
    # f_7000ec7690: the same guard one shape over, on the +0x2b8 entry vector — run35's faulting wrapper
    assert _word(gen, a) == 0xa9bc7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x40]!
    assert _word(gen, a + 0x18) == 0x910ae000, hex(_word(gen, a + 0x18))  # add x0, x0, #0x2b8 (the entry vector)
    return ('{ if (!c->x[0]) return; c->sp -= 0x40; ST64(c->sp, c->x[29]); ST64(c->sp + 8, c->x[30]); }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x40]! (Debug menu reg +0x2b8: table, guarded) */')


def _debug_menu_reg_copy_guard(gen, a):
    # f_7000ec7708: the same table's copy variant (bl f_7000ea69cc fills a copy of the entry vector) — its first
    # load is the +0x2b8 count, so a null table faults here too wherever one of its many callers passes it
    assert _word(gen, a) == 0xa9bb7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x50]!
    assert _word(gen, a + 0x18) == 0xb942b808, hex(_word(gen, a + 0x18))  # ldr w8, [x0, #0x2b8] (the entry count)
    return ('{ if (!c->x[0]) return; c->sp -= 0x50; ST64(c->sp, c->x[29]); ST64(c->sp + 8, c->x[30]); }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x50]! (Debug menu reg copy: table, guarded) */')


# The rest of the registration cluster (game_sites.py debug_menu_reg_* guards): the sweep of the title's
# registration function (f_70012567bc) and of the cluster found run36 faulting in the +0x288 vector's copy
# variant (f_7000ec7550, called 55 more times with the same x25) — the same entry shape as f_7000ec7708 one
# vector over — and seven siblings that take the same table the same way: the +0x298 and +0x2c8 vectors' wrappers
# and copy variants, and each vector's free/reset (its data pointer at vec+0x8, then a cbz). All of them fault on
# a null table within the first two instructions; the same entry guard covers every caller, the way it already
# covers the boot's 82 calls through the four guarded entries.


def _debug_menu_reg_guard(frame, pin_off, pin_word, vec):
    # entry guard on the pushed-frame stp (the frame size pins the shape), pinned by the first instruction that
    # touches the table (the vector's count, its data pointer, or the add before the fill call)
    def patch(gen, a):
        assert _word(gen, a) == 0xa9bc7bfd - ((frame - 0x40) << 12), hex(_word(gen, a))  # stp x29, x30, [sp]
        assert _word(gen, a + pin_off) == pin_word, hex(_word(gen, a + pin_off))  # the first touch of the table
        return ('{' + f' if (!c->x[0]) return; c->sp -= {frame:#x}; ST64(c->sp, c->x[29]); '
                f'ST64(c->sp + 8, c->x[30]); ' + '}'
                f'  /* {a:#x}: stp x29, x30, [sp, #{frame:#x}]! (Debug menu reg {vec}: table, guarded) */')
    return patch


# The title's actor creation (game_sites.py uinj_db_guard, tools/patches.py): run38's fault — after the debug-menu
# cluster was cleared the boot reached f_7000fb272c's actor-build step, which asks the thunk at f_7000f9e5ec for the
# uinj actor database: it loads the scene world's +0x28 member, adds a fixed 0x4e0, and tail-branches (b, not bl) to
# f_7000ff3520, whose first load reads the record count through base+0x54158. On this machine the never-completed
# title init never built that member, so it loads null, the add leaves the base at 0x4e0, and the count load faults
# dereferencing 0x4e0+0x54158 = 0x54638. run39's follow-up — fault 0x70, inside libnvn's memcpy — showed the result
# is not just stored: the ctor keeps it as the actor's uinj record at actor+0x138 and the param builder f_7000fb2804
# reads it back, the 0x204-byte actor name at +0x70 (that memcpy), the field at +0x274 and the override flags at
# +0xb28/+0xe88 -- reads only, no writes. So hand out a zeroed default record instead of the null: a zero padding
# run in main's rodata (the assertions below pin its span), read as an empty name, null fields and no overrides --
# exactly the state of an actor the never-built database never learned. The guard refreshes x8 so the add's
# fall-through keeps a real database's base intact.
def _uinj_db_guard(gen, a):
    assert _word(gen, a) == 0xf9401408, hex(_word(gen, a))  # ldr x8, [x0, #0x28] (the actor-db member)
    assert _word(gen, a + 4) == 0x91138100, hex(_word(gen, a + 4))  # add x0, x8, #0x4e0 (the record-array base)
    for off in range(0, 0xe90, 0x10):  # the record's read span, pinned zero in rodata padding
        assert _word(gen, 0x700171a380 + off) == 0, hex(0x700171a380 + off)
    return ('{ x8 = LD64(c->x[0] + 0x28); c->x[8] = x8; if (!x8) { c->x[0] = 0x700171a380ull; return; } }'
            f'  /* {a:#x}: ldr x8, [x0, #0x28] (actor create: uinj db member, guarded) */')


# The actor param builder's entry loop (game_sites.py light_rig_flag_guard, tools/patches.py): run40's fault — with
# the zeroed default record in place, the builder f_7000fb2804 walked its light-rig entry loop (w25 = 0..7) and each
# iteration asked the helper f_7000ff2d24 -- its only call site -- for entry #w25 of the record's parameter set:
# [record+0xf28] + 0x53658 + 0x160 * w25, clamped to the set's 8 entries with a csel. The zeroed record's back-pointer
# reads 0, so the base stayed 0x53658 + 0x160 * w25 -- an offset, not a pointer, unmapped in the guest -- and the
# loop's first read, ldrb w8, [x0, #0x48] (the entry's use flag), faulted at 0x53658 + 0x48 = 0x536a0, lr 0x7000fb313c.
# Guard that read: an entry base below 4 GiB (every real back-pointer is a heap pointer) means "no parameter set" --
# jump to the loop's own continue label, the block the entry's two cbz guards already share (add w25, w25, #1; cmp;
# b.ne -- w8 unused, so the skipped flag is dead there). The sweep of the builder's other record reads found them all
# inside the pinned-zero span or plain stores, so this one guard closes the family. The helper's return value needs no
# write-back: the flag it loads is dead on this path.
def _light_rig_flag_guard(gen, a):
    assert _word(gen, a) == 0x39412008, hex(_word(gen, a))  # ldrb w8, [x0, #0x48] (the entry's use flag)
    nxt = _word(gen, a + 4)  # cbz w8, <continue label>
    assert nxt & 0xFF00001F == 0x34000008, hex(nxt)
    assert (a + 4 + sext((nxt >> 5) & 0x7FFFF, 19) * 4) == 0x7000fb31c8, hex(a + 4 + sext((nxt >> 5) & 0x7FFFF, 19) * 4)
    return ('{ if (!(c->x[0] >> 32)) { x8 = c->x[8]; goto L_7000fb31c8; }'
            ' x8 = LD8(c->x[0] + 0x48); c->x[8] = x8; }'
            f'  /* {a:#x}: ldrb w8, [x0, #0x48] (param builder: light-rig entry flag, guarded) */')


# The param-object constructors' context list (game_sites.py param_ctor_ctx_guard, tools/patches.py): run41's fault —
# with the light-rig loop skipped, the builder f_7000fb2804 reached its param-object tail and faulted at 0x98, lr
# 0x7000ff6798: the three param objects go to their constructors with x3 = the actor context -- the builder's own x3,
# held through as x19 -- and f_7000ff64dc registers its object by reading the context's entry list at [x19+0x98]
# (count/capacity ldp, slot store at +0xa0, count bump): a null context faults dereferencing 0x98. Same root as the
# uinj record above: the title context this machine's init never built. The constructor's own fields are real (x20 =
# x0, the built param block on the builder's stack), and its shared tail f_7000ff6928 -- entered only from
# f_7000ff64dc's own record loop (count 0: never runs here) -- pushes through the same x19 window, so one entry guard
# on x3 covers the family; the sweep of the builder's other calls found no further context derefs. Registration is
# the constructors' whole job (and the builder ignores their returns), so with no list to register in, returning
# without building is exactly what a context-less actor means.
def _param_ctor_ctx_guard(gen, a):
    assert _word(gen, a) == 0xd10183ff, hex(_word(gen, a))  # sub sp, sp, #0x60 (the frame, pins the entry)
    assert _word(gen, a + 0x1c) == 0x29406037, hex(_word(gen, a + 0x1c))  # ldp w23, w24, [x1] (the block words)
    return ('{ if (!c->x[3]) return; }'
            f'  /* {a:#x}: sub sp, sp, #0x60 (param object ctor: context list, guarded) */')


# The actor's parameter-list builder (game_sites.py actor_param_ctx_guard, tools/patches.py): run42's fault ran the
# story of the last three families through one pointer -- the builder's context parameter x3 (held as x20) is the
# never-built title context, null like the uinj record's db (the thunk now hands out a zeroed default record for it)
# and the param-registration list (whose constructors this guard already skips). Past those, the builder's message
# step f_7000fe9210 takes the context as its descriptor and reads the entry count through it at its very first
# instruction (its prologue's str x1, [sp, #0x28]; ldr w1, [x1]: run42's fault pc was one gate later, but any flow
# into it faults on the null descriptor the moment the count path opens), and the copy path gates the message
# catalog -- static 0x7001e36048, the
# version field at +0x28 of the object it points at, needs >= 76 (the guest's own too-old branch nulls the catalog
# and its copy loop then reads through the null) -- which the title's never-completed init left at 0 in bss. A
# sweep of the builder's remaining flows found every other dereference through the zeroed record or the real stack
# block (the entry loop and constructors are guarded one family up), and the actor step after the builder's bl
# ignores its return and only registers the actor through its real factory. So: return from the builder when the
# context is absent -- a context-less actor is exactly an actor with no parameters to build.
def _actor_param_ctx_guard(gen, a):
    assert _word(gen, a) == 0xa9ba7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x60]! (the frame, pins entry)
    assert _word(gen, a + 0x1c) == 0xd10ac3ff, hex(_word(gen, a + 0x1c))  # sub sp, sp, #0x2b0 (the locals frame)
    assert _word(gen, a + 0x20) == 0x528bb008, hex(_word(gen, a + 0x20))  # mov w8, #0x5d80 (the actor field)
    assert _word(gen, a + 0x24) == 0xaa0303f4, hex(_word(gen, a + 0x24))  # mov x20, x3 (the context, held)
    return ('{ if (!c->x[3]) return; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x60]! (param builder: context, guarded) */')


# The param-object transfer (game_sites.py param_list_xfer_guard, tools/patches.py): run45's fault was the consumer
# side of the construction family #10 skipped -- the actor-creation step f_7001263218 (its call at 0x70012632f8)
# hands the actor's param block (x0 + 0x150) to f_7000ffb320, whose whole body is moving the block's param-object
# vector (the +0x9d8 count / +0x9e0 data pair) into the actor's registry: it clamps to record index 0, reads the
# record's entry count at [record+0x258] to pick the object, then the object's own list housekeeping -- its lookup
# x24 feeds f_7000573698(x24 + 0x40, ...), f_7000ffb468, the stores to [x24+0x154] and [x24+0x158], and the push
# onto the record's list at [record+0x98]. The guarded ctor never built the vector, so its data pointer stayed 0
# (an alloc'd block the ctor would have filled): the smaddl base was 0 and the record-0 read, ldr w9, [x8, #0x258],
# faulted at 0x258 exactly -- host pc f_7000ffb320+0x123 is mov eax, [rdi+rdx+0x258] right after imul rdi, rdi,
# 0x5f0, and the run45 dump's fault address is 0x258 = 0 * 0x5f0 + 0x258. With a null vector there is no object to
# transfer and every step of the body would have faulted on it, so return from the entry: the sole caller ignores
# the result (it re-derives x0 from x20 on its very next instruction) and the record's list and index table simply
# stay as they are -- exactly a context-less actor's empty parameter list arriving at its consumer.
def _param_list_xfer_guard(gen, a):
    assert _word(gen, a) == 0xa9bb7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x50]! (frame, pins the entry)
    assert _word(gen, a + 0x18) == 0xb949d808, hex(_word(gen, a + 0x18))  # ldr w8, [x0, #0x9d8] (vector count)
    assert _word(gen, a + 0x24) == 0xf944f019, hex(_word(gen, a + 0x24))  # ldr x25, [x0, #0x9e0] (vector data)
    return ('{ if (!LD64(c->x[0] + 0x9e0ull)) return; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x50]! (param transfer: empty vector, guarded) */')


# The title actor's default-param subsystem (game_sites.py param_subsys_guard, tools/patches.py): run46's fault --
# the actor init step f_7001263218 (guest lr 0x70012633fc) took its count<1 path (the guarded ctor left the param
# vector empty, count 0) and loaded the actor's default-param subsystem through field [x20+0x3680], then wrote
# through it: str wzr, [x23, #0x220] cleared the record count, f_700100fd54 copied the +0x220..+0x225 flag window
# into +0x500..+0x540, two record headers went through the record array at [x23+0x230] (bl f_700100fd70 twice),
# and sibling subsystem stores followed through fields [x20+0x3388] (a flag word), +0x3678 (a float pair at
# +0x6ed0/+0x6ed4) and +0x3900 (a mode byte at +0x38). The never-built title init left the fields 0 -- the first
# store, ldr x23, [x20, #0x3680] then str wzr, [x23, #0x220], faulted at 0x220 exactly, x23 0 in the dump and the
# host disasm reading mov eax,[rdi+rdx+0x258]-style: mov [rdx+0x220], 0 right after mov rdx, [rdx+0x3680]. The
# whole block sits between this load and the count<1 merge label the same path already reaches (the b.lt at
# 0x70012636dc, count still 0, targets 0x7001263758): with no subsystem there is nothing to initialize, so on a
# null field jump to that existing label. The sweep of the merge region found only the real stack block, embedded
# actor fields (x19 + 0x10, 0x78, the param getters f_7000f75e40/f75e5c/f75e84 the builder already calls safely)
# and stores into the actor's own block -- no further dereference of the absent subsystem's fields before the
# merge, so one guard covers the family.
def _param_subsys_guard(gen, a):
    assert _word(gen, a) == 0xf95b4297, hex(_word(gen, a))  # ldr x23, [x20, #0x3680] (the subsystem, null here)
    assert _word(gen, a + 8) == 0xb90222ff, hex(_word(gen, a + 8))  # str wzr, [x23, #0x220] (the fault, count)
    return ('{ c->x[23] = LD64(c->x[20] + 0x3680ull); if (!c->x[23]) goto L_7001263758; }'
            f'  /* {a:#x}: ldr x23, [x20, #0x3680] (actor init: default-param subsystem, guarded) */')


# The gfx::System's actor-list notify (game_sites.py gfx_system_list_guard, tools/patches.py): run47's fault --
# the actor init's tail notify step f_7000f7658c dispatches the gfx::System's notification f_700123b8f8 through
# the actor's vtable (blr x8 at 0x7000fb4d2c, slot +8 of the object at [x20+0x5c90] -- the gfx::System instance,
# its name string "gfx::System" still in the run47 register dump's x6/x7). The notification loads the system's
# actor-list base through field [x0+0x58] into x21 and reads the list's entry count through it -- ldr w9,
# [x21, x9] with x9 the list head offset 0x5610, then the array at [x21+0x5618], its length clamped against the
# static at [0x7001d76bf8] -- and the never-built title init left that base 0, so the count read faulted at
# 0x5610 exactly (x21 0 in the dump; host pc f_700123b8f8+0x100 is the mov esi,[r13+0x5610]-style read
# mov esi,[rbx+r13], r13 = x21's home). The sweep above and below the fault: the mutex step (static
# [0x7001d66468]) gates itself -- its cbz skips the lock when the static's object is absent -- the loop's bl
# f_7001236614 and vtable +0xb8 name step run only for entries of the skipped list, and the guest already has a
# skip-everyone path: the busy-lock branch jumps to the function's own return label L_700123b994, reload block
# restoring the callee-saved frame. One guard on the null base jumps there -- an un-notified actor is exactly
# what a never-built system means -- and the blr's caller ignores the result, re-deriving x0 from x19 on its
# very next instruction (mov x0, x19 at 0x7000fb4d30).
def _gfx_system_list_guard(gen, a):
    assert _word(gen, a) == 0xb8696aa9, hex(_word(gen, a))  # ldr w9, [x21, x9] (the fault, x9 = 0x5610)
    assert _word(gen, a - 4) == 0xf945fd08, hex(_word(gen, a - 4))  # ldr x8, [x8, #0xbf8] (the length static)
    assert _word(gen, a + 4) == 0xf96b0eaa, hex(_word(gen, a + 4))  # ldr x10, [x21, #0x5618] (the array)
    return ('{ x21 = c->x[21]; if (!x21) goto L_700123b994; }'
            '  { uint64_t ea = x21 + c->x[9]; uint64_t v = LD32(ea); c->x[9] = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr w9, [x21, x9] (gfx::System notify: actor list, guarded) */')


# The actor init's subsystem-field tail (game_sites.py's four actor_*_guard sites, tools/patches.py): run48's
# fault -- the title actor init f_7001263218, past the family 13-15 guards, registers its subsystems through the
# fields of its subsystem block x20 (real) and the never-built title init left those fields 0 like the fields
# before them. The fault, 0x100 exactly: the notify step's return path at 0x7001263c9c stores the vtable
# descriptor adr through field [x20+0x5cd8] (str x9, [x8, #0x100], x8 0 in the dump; host pc f_7001263218+0x1b76
# is mov QWORD PTR [rax+0x100],rcx right after the call at 0x7001263c84, rax = [[rbx+0xa0]+0x5cd8]) -- guard it
# as a conditional store, the descriptor simply goes nowhere. The sweep of the rest of the tail found the two
# registry lookups (0x70012641b0/0x70012641f0): both load field [x20+0x55e8] into x21 and hand it to the
# registry lookup f_7000f778dc, which reads the entry count at [x0+0x38] and the array at [x0+0x40] through it
# -- a null field would fault at 0x38 there -- and each lookup's own not-found result (-1) reaches the guest
# label 0x70012642d8/0x70012642e0 storing 0 through [x19+0x10f8]/[x19+0x1100], so a null field jumps to that
# existing label (the entry read at [x21+0x40] after the bl is skipped with the call). The last chain, the
# consumer at 0x7001264228: it loads field [x20+0x55f0] into x0, stores the same value through [x19+0x1108]
# (the same null, and the actor block is a fresh allocation), and calls vtable slot +0xc0 for the flag byte at
# [x19+0x11b8] -- null has no vtable, so jump to the function tail at 0x700126428c: the entry loop it passes
# over is gated on the param count [x20+0x108] the guarded ctor left 0 (its own cbz skips it on this machine
# anyway), and the tail only stores static function tables through the real block x20 before the epilogue.
def _actor_reg_field_guard(gen, a):
    assert _word(gen, a) == 0xf9008109, hex(_word(gen, a))  # str x9, [x8, #0x100] (the fault, x8 = the field)
    assert _word(gen, a - 0x14) == 0xf96e6e88, hex(_word(gen, a - 0x14))  # ldr x8, [x20, #0x5cd8] (the field)
    return ('{ if (x8) { uint64_t ea = x8 + 0x100ull; ST64(ea, x9); } }'
            f'  /* {a:#x}: str x9, [x8, #0x100] (actor init: subsystem vtable store, guarded) */')


def _actor_list_reg_guard_1(gen, a):
    assert _word(gen, a) == 0xf96af695, hex(_word(gen, a))  # ldr x21, [x20, #0x55e8] (the field)
    assert _word(gen, a - 8) == 0xf9451660, hex(_word(gen, a - 8))  # ldr x0, [x19, #0xa28] (the notify link)
    return ('{ c->x[21] = LD64(c->x[20] + 0x55e8ull); if (!c->x[21]) goto L_70012642d8; }'
            f'  /* {a:#x}: ldr x21, [x20, #0x55e8] (actor init: registry field, guarded) */')


def _actor_list_reg_guard_2(gen, a):
    assert _word(gen, a) == 0xf96af695, hex(_word(gen, a))  # ldr x21, [x20, #0x55e8] (the field)
    assert _word(gen, a - 0xc) == 0xf9087e68, hex(_word(gen, a - 0xc))  # str x8, [x19, #0x10f8] (first result)
    return ('{ c->x[21] = LD64(c->x[20] + 0x55e8ull); if (!c->x[21]) goto L_70012642e0; }'
            f'  /* {a:#x}: ldr x21, [x20, #0x55e8] (actor init: registry field again, guarded) */')


def _actor_subsys_ref_guard(gen, a):
    assert _word(gen, a) == 0xf96afa80, hex(_word(gen, a))  # ldr x0, [x20, #0x55f0] (the field)
    assert _word(gen, a - 0xc) == 0x91004368, hex(_word(gen, a - 0xc))  # add x8, x27, #0x10 (the descriptor)
    return ('{ x0 = LD64(c->x[20] + 0x55f0ull); if (!x0) goto L_700126428c; }'
            f'  /* {a:#x}: ldr x0, [x20, #0x55f0] (actor init: subsystem ref field, guarded) */')


# The subsystem consumer's null getter result (game_sites.py subsys_consume_guard, tools/patches.py): run49's
# fault -- the actor init's tail hands the allocator's subsystem block (x24) plus the stack descriptor (x1 = sp
# + 0x58) to the subsystem consumer f_700126daf0 (bl 0x7001263f00). The descriptor's [x1+8] holds the getter
# result: the caller built it with the null-safe getter f_7001016510 (its head is ldr x8,[x0,#0x420]; cmp/csel
# -- and its subject is the field [x20_actor+0x51d8] the never-built title init left 0, so the getter answers
# 0), and the consumer reads the subsystem's flag word through it: ldr w21, [x8, #0x298] faulted at 0x298
# exactly, x8 0 in the dump (host pc f_700126daf0+0xde is the mov esi,[rbp+0x298]-style read right after the
# field copy, mov eax,[rdi+0x8]). The sweep of the consumer's body: the same value's copy at [x20+0x10] is
# read again at ldr w4, [x8, #0x2b4] (the same null, one bl later), every other dereference goes through the
# real allocation (x20 = x0, x22 = the f_7000e8c250 result) or the real descriptor ([x19] = [sp+0x58] = the
# actor's real x28), and the getter value's other home -- the caller's stack slot [sp+0x60] -- is never read
# again. So one entry guard on the null getter returns from the consumer: the sole caller ignores the result
# (mov w0, #0x6c0 on its very next instruction) and the subsystem block stays exactly as the allocator left
# it -- an absent subsystem has nothing to register.
def _subsys_consume_guard(gen, a):
    assert _word(gen, a) == 0xd10383ff, hex(_word(gen, a))  # sub sp, sp, #0xe0 (the frame, pins the entry)
    assert _word(gen, a + 0x1c) == 0xf9400428, hex(_word(gen, a + 0x1c))  # ldr x8, [x1, #8] (the getter result)
    assert _word(gen, a + 0x40) == 0xb9429915, hex(_word(gen, a + 0x40))  # ldr w21, [x8, #0x298] (the fault)
    return ('{ if (!LD64(c->x[1] + 8ull)) return; }'
            f'  /* {a:#x}: sub sp, sp, #0xe0 (subsystem consumer: null getter result, guarded) */')


# The registry lookup's null registry (game_sites.py registry_lookup_guard, tools/patches.py): run50's fault --
# the actor init's subsystem initializer f_7001274db4 (actor init's bl 0x7001264050, its x2 = the real block)
# loads the subsystem registry through field [x2+0x55e8] -- the same never-built field the family-15 guards
# cover -- and makes four registry lookups with it (bl 0x7000f778dc at 0x7001274df8/0xe70/0xee8/0xf60, the first
# one faulting): the lookup's first dereference is the entry count ldrsw x8, [x0, #0x38], then the entry array
# at [x0+0x40] -- 0x38 faulted exactly with the dump's x0 0. The guest's own empty-registry answer is the -1
# its count==0 branch returns at 0x7000f779b0 (mov w19, #-1; mov w0, w19 restores the frame and rets), and
# every caller family gates on it: all four of f_7001274db4's lookups follow with cmn w0, #1 / b.eq and skip
# the found-object stores through [x21+0x40] on -1, and its tail cbz skips the flag step (w20 = 0 in the
# dump) -- so a null registry is exactly an empty one, answered from the lookup's entry. The guard returns
# before the frame (the guest's own sub/add pair nets zero, c->sp untouched) with w0 = -1; the other 18 call
# sites include the actor init's two guarded loads (families 15's goto skips their calls entirely) and the
# title/bootup lookups that already run with a real registry (the guard's c->x[0] test is false for them).
def _registry_lookup_guard(gen, a):
    assert _word(gen, a) == 0xd10183ff, hex(_word(gen, a))  # sub sp, sp, #0x60 (the frame, pins the entry)
    assert _word(gen, a + 0x1c) == 0xb9803808, hex(_word(gen, a + 0x1c))  # ldrsw x8, [x0, #0x38] (the fault)
    return ('{ if (!c->x[0]) { c->x[0] = 0xffffffffull; return; } }'
            f'  /* {a:#x}: sub sp, sp, #0x60 (registry lookup: null registry, guarded) */')


# The record subsystem init's null registry base (game_sites.py record_subsys_init_guard, tools/patches.py):
# run51's fault -- the actor init's tail builds the title actor's record subsystem with f_700124fccc (its sole
# caller, the bl 0x700126407c in the guarded tail; x0 = the freshly allocated 0x31d8 subsystem block, kept
# through [x19+0x3a8], the result ignored). The init stores the registry base into the block's own field
# [x25+0x5d0] -- only when the lookup f_700155ddc4 answers non-null, and it answers null for the never-built
# registry -- and drives it through the param-array thunk f_7000fb1224 (x0 = the field, ldr x8, [x0, #0x40],
# faulting at 0x40 exactly, the dump's x0 0). The sweep of the whole function: both thunk calls fault on the
# null field and the caller dereferences the result (ldr x8, [x0, #0x10] at 0x700124feb8), and every later
# chain dies through it or its unfilled siblings -- the block-1 record's field [x25+0x5d8] the consumer reads
# its vtable through (the ldr x8, [x0] at 0x700124fff0, the next fault waiting), the param loop's vtable call
# through [x27+0x5d8] (0x700125036c), the third field read's [x8+0x38] chain whose guest null-name cbz skips
# only after that deref (0x7001250438), and the tail's record-destroy step f_7000faa8b8 through the block's
# [x0+0x3c] the skipped blocks never built. The guest's own absent paths prove the skip: the alloc-fail cbz
# reaches the return at 0x70012507f8, the null-name cbz at the third read reaches 0x70012507b8 -- and the
# caller ignores the result (mov w0, #0x178, the next subsystem's alloc, on its very next instruction), so
# one entry guard on the null field returns from the whole record init before the frame.
def _record_subsys_init_guard(gen, a):
    assert _word(gen, a) == 0xd10583ff, hex(_word(gen, a))  # sub sp, sp, #0x160 (the frame, pins the entry)
    assert _word(gen, a + 0x2c) == 0xaa0003f9, hex(_word(gen, a + 0x2c))  # mov x25, x0 (the block)
    assert _word(gen, a + 0x1e0) == 0xf942eb20, hex(_word(gen, a + 0x1e0))  # ldr x0, [x25, #0x5d0] (the field)
    return ('{ if (!LD64(c->x[0] + 0x5d0ull)) return; }'
            f'  /* {a:#x}: sub sp, sp, #0x160 (record subsystem init: null registry base, guarded) */')


# The actor-list subsystem's registration steps (game_sites.py's two subsys_list_* sites, tools/patches.py):
# run52's fault -- the actor init's tail registers the actor-list subsystem block at [x19+0xa28] (a real
# allocation, the dump's x0 0x72d523ba70) with its registrar f_70012354dc (bl 0x70012641a4, its sole caller).
# The block's actor-list base field [x0+0x58] -- the field the gfx::System notify also reads its list through
# (gfx_system_list_guard) -- is the null one the never-built title init left: the registrar's first use
# stores its resume-callback adr through it, str x8, [x22, #0x5458], faulting at 0x5458 with the dump's x22 0
# (host f_70012354dc+0xf7: mov QWORD PTR [rcx+0x5458],rax, rcx = [r15+0x58] reloaded from the spilled base).
# The sweep of the registrar's body found every later chain through the same null base -- the record links
# [x22+0x5450]/+0x5460/+0x5448, the manager reads [x22+0x5208] twice -- and after the four stores the reload
# re-reads the base and its consumer faults one deref later (ldr w3, [x8, #0x108] at 0x7001235540, 0x108
# waiting), then the loop's per-entry vtable steps and f_700123f578 calls all run on entries of the base's
# list -- so the guard returns from the entry before the frame. The sibling registration step the tail calls
# right after (bl 0x70012641ac, f_7001237d00, also its sole caller) loads the same field and reads the
# manager's entry through it: ldr x8, [x8, #0x5208] at +0x14 (0x5208 waiting), then locks the found entry,
# calls its vtable slot +8 and registers its resume-record slots -- an absent manager list registers nothing,
# so the same entry return answers it. Both callers ignore the results (the tail reloads ldr x0, [x19,
# #0xa28] on its very next instructions), and the registry lookups the tail reaches next already skip on
# null through the guarded loads (actor_list_reg_guard_1/2's guest -1 branches).
def _subsys_list_init_guard(gen, a):
    assert _word(gen, a) == 0xd10183ff, hex(_word(gen, a))  # sub sp, sp, #0x60 (the frame, pins the entry)
    assert _word(gen, a + 0x1c) == 0xf9402c16, hex(_word(gen, a + 0x1c))  # ldr x22, [x0, #0x58] (the base)
    assert _word(gen, a + 0x30) == 0xf92a2ec8, hex(_word(gen, a + 0x30))  # str x8, [x22, #0x5458] (the fault)
    return ('{ if (!LD64(c->x[0] + 0x58ull)) return; }'
            f'  /* {a:#x}: sub sp, sp, #0x60 (actor-list subsystem registrar: null list base, guarded) */')


def _subsys_list_reg_guard(gen, a):
    assert _word(gen, a) == 0xa9be7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x20]! (pins the entry)
    assert _word(gen, a + 0xc) == 0xf9402c08, hex(_word(gen, a + 0xc))  # ldr x8, [x0, #0x58] (the base)
    assert _word(gen, a + 0x14) == 0xf9690508, hex(_word(gen, a + 0x14))  # ldr x8, [x8, #0x5208] (the next)
    return ('{ if (!LD64(c->x[0] + 0x58ull)) return; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x20]! (actor-list subsystem step 2: null list base, guarded) */')


# The subsystem record's null fields (game_sites.py's two subsys sites, tools/patches.py): run53's fault --
# the boot's first function past the whole guarded actor-init tail, f_70012642e8, looks up the subsystem
# block with the thunk f_7000fb272c (bl 0x700126437c) and drives its record fields: a real block (the dump's
# x0 0x72d5bbd048, kept as x19) whose fields the never-built title init left null. Its first use stores the
# mode flag through the record field -- ldr x8, [x0, #0x3388] and str w24, [x8, #0x18], the fault 0x18 (host
# f_70012642e8+267: mov DWORD PTR [rcx+0x18],edx, rcx = [rax+0x3388] reloaded from the spilled field) -- and
# the guard skips just that store: the block's own later stores go through x0/the real block (host mov
# [rax+0x43c0]), the +0x55f0 consumer self-gates (the guest's own cbz 0x70012643f0 -> 0x7001264588 skips the
# vtable block the null ref answers), and the count-gated loop the guest falls through to reads the param
# array: ldr x21, [x19, #0x3900] into the loop head's ldr w8, [x21, #8] -- the fault 0x8 waiting (the sweep
# found no other unguarded chain: every remaining deref runs on entries of these two fields). A null param
# array means zero entries, exactly what the loop's own count skip answers, so the second guard jumps the
# whole loop to the label its count b.lt/b.eq reach (0x70012645f8: the after-loop record stores, through the
# real x19 block).
def _subsys_record_mode_guard(gen, a):
    assert _word(gen, a) == 0xb9001918, hex(_word(gen, a))  # str w24, [x8, #0x18] (the fault, x8 = the field)
    assert _word(gen, a - 0x10) == 0xf959c408, hex(_word(gen, a - 0x10))  # ldr x8, [x0, #0x3388] (the field)
    return ('{ if (x8) { uint64_t ea = x8 + 0x18ull; ST32(ea, (uint32_t)c->x[24]); } }'
            f'  /* {a:#x}: str w24, [x8, #0x18] (subsystem record: null record field, guarded) */')


def _subsys_param_array_guard(gen, a):
    assert _word(gen, a) == 0xf95c8275, hex(_word(gen, a))  # ldr x21, [x19, #0x3900] (the array base)
    assert _word(gen, a - 0xc) == 0xb9410a68, hex(_word(gen, a - 0xc))  # ldr w8, [x19, #0x108] (the count)
    assert _word(gen, a + 0xc) == 0xb9400aa8, hex(_word(gen, a + 0xc))  # ldr w8, [x21, #8] (the next fault)
    return ('{ x21 = LD64(c->x[19] + 0x3900ull); if (!x21) goto L_70012645f8; }'
            f'  /* {a:#x}: ldr x21, [x19, #0x3900] (subsystem param array: null base, guarded) */')


# The name-entry lookup's null table (game_sites.py subsys_entry_lookup_guard, tools/patches.py): run54's
# fault -- the boot's walk past the guarded subsystem record reaches the name-entry lookup f_7000eceac8 (the
# bl 0x7000ecea90 in its thin wrapper f_7000ecea7c, its sole caller -- the dump's lr 0x7000ecea94; x0 = the
# subsystem block the walk found at 0x72d5242958, a real object with the dump's [x0] vtable) and reads its
# bound pair through the table base the never-built title init left null in the block's field [x0+0x20]:
# ldr x9, [x0, #0x20] and ldrh w9, [x8] -- the fault 0x0 (host f_7000eceac8+d8: movzx eax, WORD PTR
# [r9+rsi*1], rsi = the null base, the index csel'd to 0 since the count [x0+0x18] is <= the asked entry,
# the dump's w1 1). The sweep of the whole lookup: its entry loop reads the entries through the sibling
# field [x0+0x30] (ldr x0, [x25, x8] at 0x7000eceb60, the next fault waiting on the same never-built init),
# the per-entry virtual calls and the compare loop run on found entries (the guest's own cbz x0 skips the
# null ones -- the array's holes), and the not-found walk returns the guest's own -1 (mov w20, #-1). The
# caller only reads the same two fields again on the found path, after its tbnz w0, #0x1f test routes a
# negative answer to its own mov w0, #-1, so the lookup's entry guard answering -1 reaches the whole walk
# with the answer the never-built table already is: nothing to find.
def _subsys_entry_lookup_guard(gen, a):
    assert _word(gen, a) == 0xa9ba7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x60]! (the frame, entry)
    assert _word(gen, a + 0x1c) == 0xb9401808, hex(_word(gen, a + 0x1c))  # ldr w8, [x0, #0x18] (the count)
    assert _word(gen, a + 0x24) == 0xf9401009, hex(_word(gen, a + 0x24))  # ldr x9, [x0, #0x20] (the table)
    assert _word(gen, a + 0x34) == 0x79400109, hex(_word(gen, a + 0x34))  # ldrh w9, [x8] (the fault)
    return ('{ if (!LD64(c->x[0] + 0x20ull)) { c->x[0] = 0xffffffffull; return; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x60]! (name-entry lookup: null table, guarded) */')


# The indexed getEntry lookups' null table (game_sites.py's three subsys_index_get sites, tools/patches.py):
# run55's fault -- the boot's init step f_7001264644 (the frame lr 0x70012646b4, right after the guarded
# subsystem record's next sibling step) looks up subsystem entries by name through the guarded wrapper
# chain, whose cbnz/cbz paths all ran clean in run55, falls back to the indexed getEntry lookups and faults
# in f_7000fb42f8: it clamps the asked entry to a global bound (its ldrsh w9, [x8] -- a real address, the
# dump's x8 0x7000...0x101-clamped 0 index) and reads the bound pair through the table base the never-built
# title init left null in the block's field [x0+0x20] (the dump's x0/x20 0x72d5242958, a real block): ldr
# x8, [x0, #0x20] and ldrh w10, [x10, #2] -- the fault 0x2 (host f_7000fb42f8+8d: movzx ecx, WORD PTR
# [rsi+rcx*4+0x2], rsi = the null base). The sweep of the whole lookup: the entry array comes through the
# sibling field [x0+0x30] (the ldr x19, [x9, x8, lsl #3] -- the next fault waiting on the same never-built
# init), the per-entry virtual call runs only on found entries (the guest's own cbz x19 skips the array's
# holes), and every answer is a pointer the callers test: the not-found paths answer the guest's own mov
# x0, xzr, the init step stores it straight into its subsystem fields ([x19+0x118/0x120/...], its cbnz
# after the name lookup's found check too), the f_7000fb2804 callers test it with cbz/cbnz or cmp #0 +
# csel, and the rest pass it as a to-be-tested pointer deeper. Two shape-identical siblings the same step
# calls right after -- f_7000fb44b4 (bound global +0xf38, its two call sites at 0x7001264778/0x70012647bc)
# and f_7000fb45dc (global +0xb00, the three later name lookups' fallback) -- read the same two fields the
# same way and would fault in turn, so all three get the same entry guard answering the guest's own null
# entry: exactly what a never-built table is, nothing to get.
def _subsys_index_get_guard_1(gen, a):
    assert _word(gen, a) == 0xa9be7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x20]! (the frame, entry)
    assert _word(gen, a + 0x18) == 0xb940180a, hex(_word(gen, a + 0x18))  # ldr w10, [x0, #0x18] (the count)
    assert _word(gen, a + 0x24) == 0xf9401008, hex(_word(gen, a + 0x24))  # ldr x8, [x0, #0x20] (the table)
    assert _word(gen, a + 0x34) == 0x7940054a, hex(_word(gen, a + 0x34))  # ldrh w10, [x10, #2] (the fault)
    return ('{ if (!LD64(c->x[0] + 0x20ull)) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x20]! (indexed getEntry: null table, guarded) */')


def _subsys_index_get_guard_2(gen, a):
    assert _word(gen, a) == 0xa9be7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x20]! (the frame, entry)
    assert _word(gen, a + 0x18) == 0xb940180a, hex(_word(gen, a + 0x18))  # ldr w10, [x0, #0x18] (the count)
    assert _word(gen, a + 0x24) == 0xf9401008, hex(_word(gen, a + 0x24))  # ldr x8, [x0, #0x20] (the table)
    assert _word(gen, a + 0x34) == 0x7940054a, hex(_word(gen, a + 0x34))  # ldrh w10, [x10, #2] (the fault)
    return ('{ if (!LD64(c->x[0] + 0x20ull)) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x20]! (indexed getEntry 2: null table, guarded) */')


def _subsys_index_get_guard_3(gen, a):
    assert _word(gen, a) == 0xa9be7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x20]! (the frame, entry)
    assert _word(gen, a + 0x18) == 0xb940180a, hex(_word(gen, a + 0x18))  # ldr w10, [x0, #0x18] (the count)
    assert _word(gen, a + 0x24) == 0xf9401008, hex(_word(gen, a + 0x24))  # ldr x8, [x0, #0x20] (the table)
    assert _word(gen, a + 0x34) == 0x7940054a, hex(_word(gen, a + 0x34))  # ldrh w10, [x10, #2] (the fault)
    return ('{ if (!LD64(c->x[0] + 0x20ull)) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x20]! (indexed getEntry 3: null table, guarded) */')


# The subsystem list's null base (game_sites.py's two entry-name/pick sites, tools/patches.py): run56's
# fault -- the init step f_7001264644 got past all five indexed fallbacks (run55's family, their null
# answers stored into [x19+0x118..0x140]) and its last lookup f_700126b908 (the bl 0x7001264750 -- the
# dump's lr 0x7001264754; x0 = the real actor block 0x72d523a6e8) reads a subsystem entry through its list
# base three dereferences down: ldr x8, [x0, #0x158] (the dump's x8 0x72d5242958 -- real) and ldr x8, [x8]
# then the list field ldr x8, [x8, #0x5c80] -- the never-built title init left null (the host mov rax,
# [rax+0x5c80] reads it fine) -- and the first use faults: ldr x0, [x8], the fault 0x0 (host
# f_700126b908+65: mov rcx, QWORD PTR [rax]). The sweep of every #0x5c80 dereference in the whole module
# found exactly two consumers, and both already carry their own absent answer: A right after the entry
# get's cbz x0 jumps to its unknown-name string return (0x70015e615b, its label L_700126b95c), B -- the
# per-kind entry picker f_7000ffc3dc, the next fault waiting, its ldr x19, [x8, w2, sxtw #3] through the
# same null base -- answers the same string from its default case (label L_7000ffc44c; its w1==2 path's
# count sibling field 0x5c78 is a load through the same real base, answers 0, and the guest's own b.ls
# then takes its x19-null path). So each guard skips just the load through the null list base to its own
# function's string return -- the answer a never-built list already is: no entry, the unknown name.
def _subsys_entry_name_guard(gen, a):
    assert _word(gen, a) == 0xf9400100, hex(_word(gen, a))  # ldr x0, [x8] (the fault, x8 = the list base)
    assert _word(gen, a - 0x10) == 0xf940ac08, hex(_word(gen, a - 0x10))  # ldr x8, [x0, #0x158] (chain head)
    assert _word(gen, a - 4) == 0xf96e4108, hex(_word(gen, a - 4))  # ldr x8, [x8, #0x5c80] (the field)
    return ('{ if (!x8) goto L_700126b95c; x0 = LD64(x8); }'
            f'  /* {a:#x}: ldr x0, [x8] (subsystem list base: null, guarded to the unknown-name string) */')


def _subsys_entry_pick_guard(gen, a):
    assert _word(gen, a) == 0xf862d913, hex(_word(gen, a))  # ldr x19, [x8, w2, sxtw #3] (the next fault)
    assert _word(gen, a - 4) == 0xf96e4108, hex(_word(gen, a - 4))  # ldr x8, [x8, #0x5c80] (the field)
    assert _word(gen, a - 8) == 0x540000e9, hex(_word(gen, a - 8))  # b.ls #0x7000ffc458 (the count skip)
    return ('{ if (!x8) goto L_7000ffc44c;'
            ' uint64_t ea = x8 + ((uint64_t)(int64_t)(int32_t)x2 << 3);'
            ' uint64_t v = LD64(ea); x19 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr x19, [x8, w2, sxtw #3] (subsystem list base: null, guarded) */')


# The directory iterator's untagged handle (game_sites.py dir_entry_accessor_guard, tools/patches.py):
# run57's fault -- the title step f_700009d950 (a save-dir path: bl 0x700009a7ec opened it, bl 0x700009b77c
# read 0x100 bytes -- a real read the cmp x0, #0x100 passed, the dump's x0/x1/x21 0x72d636a230 the fs
# iterator handle at [object+0x2a0]) reaches through its wrapper f_700007dfdc (the bl 0x700009d9d8 -- the
# dump's lr 0x700009d9dc, its own lr 0x700007dff8 pinning the call site) the leaf accessor f_700007eb78:
# it probes the tag 0x2002 at the handle's +0x14/+0x20/+0x2c (three entry sizes of the fs-iterator's
# header) and its common tail reads the value dword after the tag, ldr w0, [x8, #4] -- the csel leaves x8
# 0 when no probe matches, the fault 0x4 (host f_700007dfdc+bc, the inlined leaf tail: mov edx, DWORD PTR
# [rax+4], rax = 0; on our machine the handle carries no 0x2002 tag, the never-built fs state left it
# raw). The sweep of the leaf: its three probe reads run on the real handle (the fault is the fourth
# dereference -- the tail is the leaf's only other one), so the guard answers the neutral 0 there, exactly
# the offset the answer is used as: the caller wrapper stores it into the step's field [x19+0x298] (an
# entry's offset, 0 = at the buffer head) and the other two call sites (f_700009ed70's two saves-list
# iterations, bl 0x700009edc0/0x700009ee38) add the answer straight onto the entry buffer base --
# entry-at-offset-0, the same shape a fresh read buffer has; the leaf itself keeps x8 0 past the guard,
# which no caller reads.
def _dir_entry_accessor_guard(gen, a):
    assert _word(gen, a) == 0xb9400500, hex(_word(gen, a))  # ldr w0, [x8, #4] (the fault, x8 = the tag)
    assert _word(gen, a - 4) == 0x9a9f0008, hex(_word(gen, a - 4))  # csel x8, x0, xzr, eq (0 when untagged)
    return ('{ if (x8) { uint64_t ea = x8 + 0x4ull; uint64_t v = LD32(ea); x0 = (uint64_t)(v); }'
            ' else { x0 = 0ull; } }'
            f'  /* {a:#x}: ldr w0, [x8, #4] (dir iterator: untagged handle, guarded to offset 0) */')


# The family's four untagged-handle siblings (game_sites.py's accessor guards 2-5): the same leaf shape
# probed through the two other header tags -- 0x2001 (mov w9, #0x2001, tails +4 / +8) and 0x2000 (the
# cmp w9, #2, lsl #12 exact test, tails +4 / +8) -- all with the same csel x8, x0, xzr, eq leaving 0 on
# the untagged handle and the same tail value read as the leaf's only other dereference. run58's fault
# was the 0x2001/+8 leaf (host f_700007ead4+4c: mov edx, DWORD PTR [rax+8], rax = 0); the other three
# would fault in turn on the same handle (the step's own next call f_700009dbf0 starts with the 0x2001
# leaf's +4 sibling bl, and its sibling f_700009ecb4 reads the 0x2000 pair). All four answer the same
# neutral offset 0 the callers add onto the entry buffer base (entry at the buffer head) or compare as a
# size (0 <= requested takes the guest's own nothing-read answer path).
def _dir_entry_accessor_guard_2(gen, a):
    assert _word(gen, a) == 0xb9400900, hex(_word(gen, a))  # ldr w0, [x8, #8] (the fault, run58's)
    assert _word(gen, a - 4) == 0x9a9f0008, hex(_word(gen, a - 4))  # csel x8, x0, xzr, eq (0 when untagged)
    return ('{ if (x8) { uint64_t ea = x8 + 0x8ull; uint64_t v = LD32(ea); x0 = (uint64_t)(v); }'
            ' else { x0 = 0ull; } }'
            f'  /* {a:#x}: ldr w0, [x8, #8] (dir iterator 2: untagged handle, guarded to offset 0) */')


def _dir_entry_accessor_guard_3(gen, a):
    assert _word(gen, a) == 0xb9400500, hex(_word(gen, a))  # ldr w0, [x8, #4] (the next fault)
    assert _word(gen, a - 4) == 0x9a9f0008, hex(_word(gen, a - 4))  # csel x8, x0, xzr, eq (0 when untagged)
    return ('{ if (x8) { uint64_t ea = x8 + 0x4ull; uint64_t v = LD32(ea); x0 = (uint64_t)(v); }'
            ' else { x0 = 0ull; } }'
            f'  /* {a:#x}: ldr w0, [x8, #4] (dir iterator 3: untagged handle, guarded to offset 0) */')


def _dir_entry_accessor_guard_4(gen, a):
    assert _word(gen, a) == 0xb9400900, hex(_word(gen, a))  # ldr w0, [x8, #8] (the third-tag sibling)
    assert _word(gen, a - 4) == 0x9a9f0008, hex(_word(gen, a - 4))  # csel x8, x0, xzr, eq (0 when untagged)
    return ('{ if (x8) { uint64_t ea = x8 + 0x8ull; uint64_t v = LD32(ea); x0 = (uint64_t)(v); }'
            ' else { x0 = 0ull; } }'
            f'  /* {a:#x}: ldr w0, [x8, #8] (dir iterator 4: untagged handle, guarded to offset 0) */')


def _dir_entry_accessor_guard_5(gen, a):
    assert _word(gen, a) == 0xb9400500, hex(_word(gen, a))  # ldr w0, [x8, #4] (the third-tag sibling)
    assert _word(gen, a - 4) == 0x9a9f0008, hex(_word(gen, a - 4))  # csel x8, x0, xzr, eq (0 when untagged)
    return ('{ if (x8) { uint64_t ea = x8 + 0x4ull; uint64_t v = LD32(ea); x0 = (uint64_t)(v); }'
            ' else { x0 = 0ull; } }'
            f'  /* {a:#x}: ldr w0, [x8, #4] (dir iterator 5: untagged handle, guarded to offset 0) */')


# The zero-size read the SDK aborts on (game_sites.py fs_read_zero_guard, tools/patches.py): run60's
# fault -- the accessor guards' answer 0 flows on: the step f_7000f07ee0 took the guarded size answer
# (bl 0x7000f08114 f_700007ead4) into bl f_7000007c20 (x0 = the answer) and allocated 0 bytes -- a null
# pool buffer stored to [x19+0xbf8] -- then its read step f_700009dbf0 seeks 0 (fine) and calls the file
# wrapper f_700009b77c (x1 = the null buffer, x2 = 0 bytes): the wrapper's vtable Read succeeds (bit0
# clear), its success path f_700009a93c calls the SDK import thunk f_70015a1110 -- its GOT jump lands in
# the SDK's ReadFileImpl (the frames f_70025ad4a0 store api string 0x7002e0bb62 "ReadFile", result 0 and
# the message 0x7002e014e7 into the assert context), which R_UNLESS(buffer != nullptr) answered fs
# ResultNullptrArgument -- module 2, description 6063 (the svcBreak info print, 0x2f5e02) -- and sead's
# X macro aborted. The sweep: every file read goes through this wrapper (bl callers f_700009d950 -- the
# real 0x100-byte save-dir listing, f_700009dbf0 -- the aborting one, f_700009dcc8 -- a sibling), the
# wrapper's contract answers the read count in x0, and both callers compare count against requested --
# so the guard answers "read 0 bytes" at the entry when the size is 0: a zero-size read reads nothing,
# the SDK's null-buffer check never runs, and no host file contents were ever at issue (client-side
# abort, before the IPC).
def _fs_read_zero_guard(gen, a):
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]! (the frame, entry)
    assert _word(gen, a + 0x10) == 0xf9400008, hex(_word(gen, a + 0x10))  # ldr x8, [x0] (the vtable)
    return ('{ if (!c->x[2]) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (IFile Read: zero size, guarded to 0 bytes read) */')


# The deeper null-buffer read the SDK aborts on (game_sites.py fs_read_null_buffer_guard, tools/patches.py):
# run61's fault -- the wrapper f_700009b77c's zero-size guard took its request, but the step f_7000f07ee0's
# read went on through the wrapper's success tail (b 0x700009b7ec into the impl f_700009a93c): the impl's
# SDK ReadFile x1 is not the caller's buffer argument but the object's own buffer field (ldr x1, [x20, #8],
# the lift +0x28), run61's request carried a nonzero size (the accessor guards answered 0, the step
# allocated 0, the pool handed out a null buffer -- but the read step's size came from elsewhere), so the
# SDK's R_UNLESS(buffer != nullptr) answered fs ResultNullptrArgument again -- 0x2f5e02, the svcBreak's
# info print at stack slot 0x68, one frame deeper than run60's 0x38 -- and sead aborted. The sweep: the
# impl has no bl callers at all -- its routes are the wrapper's two tail branches and the wrapper's blr
# (its error tail f_700009aeb0 runs after the other callers' bls) -- so the one guard on the impl entry's
# buffer field covers every route, answering 0 bytes read, success: the wrapper's callers (the real
# 0x100-byte save-dir listing f_700009d950, the aborting f_700009dbf0, the sibling f_700009dcc8) all
# compare count against requested and treat 0 as the nothing-read path. A null buffer reads nothing.
def _fs_read_null_buffer_guard(gen, a):
    assert _word(gen, a) == 0xd10103ff, hex(_word(gen, a))  # sub sp, sp, #0x40 (the frame, entry)
    assert _word(gen, a + 0x28) == 0xf9400681, hex(_word(gen, a + 0x28))  # ldr x1, [x20, #8] (the buffer field)
    return ('{ uint64_t buf = LD64(c->x[0] + 8ull); if (!buf || !c->x[1]) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: sub sp, sp, #0x40 (IFile read impl: null buffer field or argument, guarded to 0 bytes read) */')


# The null fs state the sead accessors abort on (game_sites.py fs_state guards, tools/patches.py):
# run63's fault -- the read guards answered and the step f_7000f07ee0 ran on, passing its never-built
# fs state (the dump's x21 = 0, the argument the step's own cbnz at +0x60 treats as "no caller buffer")
# into the accessor thunks: bl 0x7000f0814c f_700008f87c re-aims x0 at its x1 (the state) and hits the
# thunk f_700007e05c ldr x0, [x0, #8] on the null state -- signal 11 accessing 0x8 at the dump's host
# pc f_700007e05c+10, x6/x7 still spelling "DummySound.bfsar". The sweep enumerated every dereference
# of that object in the step: the thunk f_700007e05c (tail b f_700007f704: ldr x0, [x0, #0x40], bl
# f_700007eee0: ldrsw x8, [x0, #0x34], add x0, x0, x8 -- base + signed self-relative offset; its two
# callers f_700008f87c and f_700008f8a0 pack orr x0, x9(=4), x8, lsl #4 -- the tag-4 handle family
# #24/#25 answered neutral 0), its sibling thunk f_700007e044 (the same ldr x0, [x0, #8], tail b
# f_700007f6b0; callers f_7000080440 -- from the step's bl 0x7000f0817c f_700008042c -- and f_70000807f0),
# and the two entry queries f_700007e36c (ldr x0, [x0, #8] at +0x14 then bl f_700007f7ec) and f_700007e3e0
# (the same at +0x14 then bl f_700007f9dc; reached from the step's f_700008042c and the tail accessors
# f_70000805b4/f_70000805bc -> f_7000093644/f_7000093934) -- all four guard at the entry: a null state
# answers 0, the established neutral (tag-4 handle index 0; the query bit the callers already carry on
# a failed probe). The state is only ever null on our machine (families #24-#26's never-built fs state)
# -- on real hardware it is built and every guard passes.
def _fs_state_accessor_guard(gen, a):
    assert _word(gen, a) == 0xf9400400, hex(_word(gen, a))  # ldr x0, [x0, #8] (the state field, entry)
    assert _word(gen, a + 4) == 0x140005a9, hex(_word(gen, a + 4))  # b #0x700007f704 (the tail chain)
    return ('{ if (!c->x[0]) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: ldr x0, [x0, #8] (fs state accessor thunk: null state, guarded to 0) */')


def _fs_state_accessor_guard_2(gen, a):
    assert _word(gen, a) == 0xf9400400, hex(_word(gen, a))  # ldr x0, [x0, #8] (the state field, entry)
    assert _word(gen, a + 4) == 0x1400059a, hex(_word(gen, a + 4))  # b #0x700007f6b0 (the tail chain)
    return ('{ if (!c->x[0]) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: ldr x0, [x0, #8] (fs state accessor thunk 2: null state, guarded to 0) */')


def _fs_state_query_guard(gen, a):
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]! (the frame, entry)
    assert _word(gen, a + 0x14) == 0xf9400400, hex(_word(gen, a + 0x14))  # ldr x0, [x0, #8] (the state field)
    return ('{ if (!c->x[0]) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (fs state query: null state, guarded to 0) */')


def _fs_state_query_guard_2(gen, a):
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]! (the frame, entry)
    assert _word(gen, a + 0x14) == 0xf9400400, hex(_word(gen, a + 0x14))  # ldr x0, [x0, #8] (the state field)
    return ('{ if (!c->x[0]) { c->x[0] = 0ull; return; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (fs state query 2: null state, guarded to 0) */')


# The sead framework swap the physics step runs on its never-built table (game_sites.py
# framework_swap_guard, tools/patches.py): run64's fault -- boot went deeper than ever (past the fs
# families, into physics/system init, the dump's x6/x7 spelling "Physics/System/S") -- and the swap
# helper f_7000ec9990 (21 bl callers: 11 physics-config, 3 in the step f_7000eeaff8, 7 elsewhere; no
# tail branches) converts a word array through the framework's slot table: x9 = [0x7001d6e960] (the
# sead framework global, never constructed here: run64's dump x9 = 0x6e0bebe98, a stale host pointer
# in dirty memory), x21 = [[x9 + 8·bit] + 0x20], then per word ldr w0, [x19] + blr x21 + str w0,
# [x19], #4. The dump's x21 = 0x7af992ff12 (same dirty value, > GUEST_HI, unmapped): the loop's first
# ldr w0, [x19] faults at exactly the dump's accessed 0x7af992ff12, host pc f_7000ec9990+b0. One
# entry guard for every caller: the table or the array off the guest map (the stale_actor guards'
# range idiom) means the framework was never built -- nothing to convert -- so the helper answers by
# its own early return (the b.lt ret, the shape a zero word count takes, which all its callers
# tolerate). The step f_7000eeaff8 needs its own guard too: its three bls pass x1 = x1 + dirty
# field-sums (run64's x27 = x20 + x23 landed on the dirty 0x7af992ff12), and its loop re-reads the
# array itself after every helper return (bl 0x7000eeb0c0 then ldr w8, [x21], cmp w25, w24, b.lo --
# a dirty w24 = [x1+0x2c] count would re-read the junk base forever, faulting again at the same
# address). Its guard replaces the count load: a base off the guest map answers the count 0 and
# jumps to the cbz's existing target L_7000eeb0d8 -- the step's own "nothing to convert" tail (set
# the parsed flag at [x1+8], carry on to the entry list); otherwise the guard re-executes the load.
def _framework_swap_guard(gen, a):
    assert _word(gen, a) == 0xd342fc48, hex(_word(gen, a))  # lsr x8, x2, #2 (the word count, entry)
    assert _word(gen, a + 0x24) == 0xf944b129, hex(_word(gen, a + 0x24))  # ldr x9, [x9, #0x960] (the global)
    return ('{ uint64_t g = LD64(0x7001d6e960ull);'
            ' if (g - 0x7000000000ull >= 0x320000000ull || c->x[1] - 0x7000000000ull >= 0x320000000ull)'
            ' { return; }'
            ' x8 = (uint64_t)(ROR64(c->x[2], 2) & 0x3fffffffffffffffull); }'
            f'  /* {a:#x}: lsr x8, x2, #2 (sead framework swap: table never built, guarded to nothing converted) */')


def _physics_cfg_entry_guard(gen, a):
    assert _word(gen, a - 4) == 0xf9400261, hex(_word(gen, a - 4))  # ldr x1, [x19] (the config struct)
    assert _word(gen, a) == 0xb9402c38, hex(_word(gen, a))  # ldr w24, [x1, #0x2c] (the loop count)
    assert _word(gen, a + 4) == 0x34000198, hex(_word(gen, a + 4))  # cbz w24, #0x7000eeb0d8 (the count-0 tail)
    return ('{ if (c->x[27] - 0x7000000000ull >= 0x320000000ull)'
            ' { c->x[24] = 0ull; goto L_7000eeb0d8; }'
            ' uint64_t ea = x1 + 0x2cull; uint64_t v = LD32(ea); c->x[24] = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr w24, [x1, #0x2c] (physics config step: array base off the guest map,'
            ' guarded to the count-0 tail) */')


# The Ecosystem/LoadBalancer step's never-loaded sub-objects (game_sites.py
# load_balancer_entry_guard / load_balancer_handle_guard, tools/patches.py): run65's fault -- the
# physics-config guards held (family #28 closed, boot now reaches Actor/ActorInfo.product.sbyml) --
# signal 11 accessing 0 with the dump's lr 7001185724 pinning ldr x8, [x23], the vtable load of the
# second sub-object the step looks up through the thunk f_700155dd2c: its ready probe f_700155dd60
# checks the path's flag byte and subsystem pointer and answers 0 when the path was never loaded --
# and on our machine the second path is exactly that. The step derefs the answer unguarded (its
# first two vtable loads and the third block's too; blocks 4 and 5 carry the game's own cbz/csel
# guards but still read the entry's handle at [x23+8] / [x22+8] for the handle setter). The game's
# own no-entry path (cbz x22 -> L_70011857d4 with x23 = 0, and cbz x21 -> L_700118589c -> x22 = 0 ->
# L_7001185830) proves both neutrals: an absent entry skips its handoff block by falling into the
# shared alloc tail (goto L_70011857d4, the existing label -- alloc the handle cell, store the
# handle the next guard supplies, carry on), and an absent entry has no handle to read, so the two
# handle loads answer 0, which the null-tolerant setter f_7000e8aefc (cbz x1 -> store {0,0}) takes
# as its own "no handle" state. Blocks whose entry the ready probe did answer for (the first, which
# run65 proved loaded) re-execute their vtable load untouched.
def _load_balancer_entry_guard(gen, a):
    assert _word(gen, a) == 0xf94002e8, hex(_word(gen, a))  # ldr x8, [x23] (the entry's vtable, block 2)
    assert _word(gen, a + 4) == 0xaa0003e1, hex(_word(gen, a + 4))  # mov x1, x0 (the singleton)
    return ('{ if (!c->x[23]) goto L_70011857d4;'
            ' uint64_t ea = c->x[23] + 0x0ull; uint64_t v = LD64(ea); x8 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr x8, [x23] (LoadBalancer step: sub-object never loaded, guarded to'
            " the step's no-entry tail) */")


def _load_balancer_entry_guard_2(gen, a):
    assert _word(gen, a) == 0xf94002e8, hex(_word(gen, a))  # ldr x8, [x23] (the entry's vtable, block 3)
    assert _word(gen, a + 4) == 0xaa0003e1, hex(_word(gen, a + 4))  # mov x1, x0 (the singleton)
    return ('{ if (!c->x[23]) goto L_70011857d4;'
            ' uint64_t ea = c->x[23] + 0x0ull; uint64_t v = LD64(ea); x8 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr x8, [x23] (LoadBalancer step: same, the third block pre-empted) */')


def _load_balancer_handle_guard(gen, a):
    assert _word(gen, a) == 0xf94006e1, hex(_word(gen, a))  # ldr x1, [x23, #8] (the entry's handle)
    return ('{ c->x[1] = c->x[23] ? LD64(c->x[23] + 0x8ull) : 0ull; }'
            f'  /* {a:#x}: ldr x1, [x23, #8] (LoadBalancer step: an absent entry has no handle,'
            ' the setter stores {0,0}) */')


def _load_balancer_handle_guard_2(gen, a):
    assert _word(gen, a) == 0xf94006c1, hex(_word(gen, a))  # ldr x1, [x22, #8] (the entry's handle)
    return ('{ c->x[1] = c->x[22] ? LD64(c->x[22] + 0x8ull) : 0ull; }'
            f'  /* {a:#x}: ldr x1, [x22, #8] (LoadBalancer step: the game\'s own no-entry path'
            ' leaves x22 0 here, the setter stores {0,0}) */')


# The LoadBalancer step's never-built path entries (game_sites.py physics_path_scan_guard /
# sead_heap_alloc_guard, tools/patches.py): run66 went deepest yet -- the count-0 and
# LoadBalancer guards held and the physics step set its parsed flag -- and died with signal 11
# accessing 0x823a89c29e at the dump's host pc f_7000eeaff8+3a7: objdump pins that to the string
# scan's cmpb $0x0,(%rdx), the guest ldrb w8, [x20, x21] at 0x7000eeb10c (the dump's x19 =
# 0xffffffff is the mov w19, #-1 right before it, x20 = the dump's exact 0x823a89c29e). The step
# walks the never-built config struct's path-entry array [x20, x27) converting every entry with
# the sead heap -- and both the base (the dump's x20) and the end (x27 = 0x82f68b1c1f) are dirty
# field-sums off the guest map, so the scan's first byte read faults; the sweep's second site is
# the heap manager itself: [0x7001d6eab8] of the framework's never-constructed page (the dump's
# dirty crc32-table registers), bare-dereferenced by ldr x8, [x8] at 0x7000eeb154 feeding the
# alloc bl and the registration blrs. The step's own exits prove the neutral for both: a base (or
# heap) off the guest map means nothing to convert -- exactly the entry-count cbz's skip shape --
# so both take the loop's existing done tail (goto L_7000eeb214: reload the config from [sp, #8],
# set the string-parsed flag bit 2, restore the spills and return; the caller's post-step virtual
# call carries on with its valid config struct). With a real loaded config both re-execute.
def _physics_path_scan_guard(gen, a):
    assert _word(gen, a) == 0x38756a88, hex(_word(gen, a))  # ldrb w8, [x20, x21] (the scan byte)
    assert _word(gen, a - 4) == 0xaa1f03f5, hex(_word(gen, a - 4))  # mov x21, xzr (the scan index)
    return ('{ if (c->x[20] - 0x7000000000ull >= 0x320000000ull) goto L_7000eeb214;'
            ' uint64_t ea = c->x[20] + x21; uint64_t v = LD8(ea); x8 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldrb w8, [x20, x21] (path entries: array base off the guest map,'
            " guarded to the step's done tail) */")


def _sead_heap_alloc_guard(gen, a):
    assert _word(gen, a) == 0xf9400108, hex(_word(gen, a))  # ldr x8, [x8] (the heap manager)
    assert _word(gen, a - 0xc) == 0xf9455d08, hex(_word(gen, a - 0xc))  # ldr x8, [x8, #0xab8]
    return ('{ if (x8 - 0x7000000000ull >= 0x320000000ull) goto L_7000eeb214;'
            ' uint64_t ea = x8 + 0x0ull; uint64_t v = LD64(ea); x8 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr x8, [x8] (path entries: sead heap never built,'
            " guarded to the step's done tail) */")


# The never-built resource manager (game_sites.py resource_manager_* guards, tools/patches.py):
# run67 passed the path-entry guards (family #30 closed) and died with signal 11 accessing 0x318;
# the dump's host pc f_70012647e8+8f with guest lr 7001420c7c pins the resource path lookup --
# the leaf f_70012647e8 walks [[x0, #0x158] then [+0x3638] to the entry table and reads its
# count with ldr w9, [x8, #0x318]. On our machine the manager was never built (the dump's x0 is
# a live actor, the +0x3638 field reads 0 out of readable data), so the count read faults at
# exactly 0x318 (x28 carries the "fs::ResultPathNotFound" the not-found shape returns). The
# sweep: the leaf is reached from exactly two functions (caller1's float block -- the one that
# died, which ignores the answer -- and caller2, whose x0 comes from the never-built .bss
# singleton [0x7001e43df0]); the leaf's own "path not found" exit is a bare epilogue ret
# carrying x0 = 0, exactly the shape its cbz x0 takes when the string search fails, so both
# chain derefs answer it for a base off the guest map -- the field read (this run's fault) and
# x0 itself -- and the found-path flag stores and tail call are skipped exactly as on the
# game's own not-found path. The same count field lives on the sibling manager pointer
# [x0, #0xcc0]: the registration leaf f_7000fcded4 (which the lookup tail-calls with x0 = the
# same object on the found path) reads ldr w8, [x21, #0x318] after its virtual probe and hands
# the table to f_7000fd5f94, and the removal sibling f_7000fcdd10 (the other callers' other
# half) reads it twice, before the entry search and after it (where the search's own answer
# would land instead). All three answer their own "nothing registered/removed" exit --
# cmp x20, #0; cset w0, ne; ret, the null search result's 0 -- the removal sites' answer also
# carrying the [x19, #0x168] = -1 index reset the game's own null-result path stores, and the
# later removal site answers 0 straight (its [x19, #0x120] pair load and post-search call
# skipped, the game's own skip shape). With a real built table (run67's x21 is live heap) the
# reads re-execute untouched. Last the never-built rng: caller1's post-lookup float block
# reads [0x7001e34818] (a zeroed .bss singleton) three times into the 11-instruction xorshift
# step f_7000eb6e7c, whose first ldp w8, w9, [x0] faults on address 0; the entry answers the
# step's own returned new state, w0 = 0 -- the deterministic stream caller1 bfxils into its
# actor floats -- skipping the state stores with a null base.
def _resource_manager_chain_guard(gen, a):
    assert _word(gen, a) == 0xf940ac08, hex(_word(gen, a))  # ldr x8, [x0, #0x158] (the manager)
    assert _word(gen, a - 4) == 0x910003fd, hex(_word(gen, a - 4))  # mov x29, sp (the leaf prologue)
    assert _word(gen, a - 8) == 0xa9014ff4, hex(_word(gen, a - 8))  # stp x20, x19, [sp, #0x10]
    return ('{ if (c->x[0] - 0x7000000000ull >= 0x320000000ull)'
            ' { c->x[0] = 0ull; goto L_70012648b4; }'
            ' uint64_t ea = c->x[0] + 0x158ull; uint64_t v = LD64(ea); x8 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr x8, [x0, #0x158] (path lookup: manager base off the guest map,\n'
            "     guarded to the leaf's not-found ret) */")


def _resource_manager_count_guard(gen, a):
    assert _word(gen, a) == 0xb9431909, hex(_word(gen, a))  # ldr w9, [x8, #0x318] (the count)
    assert _word(gen, a - 4) == 0xf95b1d08, hex(_word(gen, a - 4))  # ldr x8, [x8, #0x3638] (the table)
    return ('{ if (x8 - 0x7000000000ull >= 0x320000000ull)'
            ' { c->x[0] = 0ull; goto L_70012648b4; }'
            ' uint64_t ea = x8 + 0x318ull; uint64_t v = LD32(ea); c->x[9] = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr w9, [x8, #0x318] (path lookup: entry table never built,'
            " guarded to the leaf's not-found ret) */")


def _resource_manager_reg_count_guard(gen, a):
    assert _word(gen, a) == 0xb9431aa8, hex(_word(gen, a))  # ldr w8, [x21, #0x318] (the count)
    assert _word(gen, a - 4) == 0xd63f0100, hex(_word(gen, a - 4))  # blr x8 (the virtual probe)
    assert _word(gen, a - 8) == 0xf9405908, hex(_word(gen, a - 8))  # ldr x8, [x8, #0xb0] (the vtable)
    return ('{ if (x21 - 0x7000000000ull >= 0x320000000ull)'
            ' { c->x[20] = 0ull; goto L_7000fcdfe8; }'
            ' uint64_t ea = x21 + 0x318ull; uint64_t v = LD32(ea); x8 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr w8, [x21, #0x318] (registration: sibling manager never built,\n'
            "     guarded to the leaf's nothing-registered ret) */")


def _resource_manager_removal_guard(gen, a):
    assert _word(gen, a) == 0xb9431aa8, hex(_word(gen, a))  # ldr w8, [x21, #0x318] (the count)
    assert _word(gen, a + 4) == 0x12800016, hex(_word(gen, a + 4))  # mov w22, #-1 (the no-index)
    return ('{ if (c->x[21] - 0x7000000000ull >= 0x320000000ull) { c->x[20] = 0ull;\n'
            '     { uint64_t ea2 = x19 + 0x168ull; ST32(ea2, (uint32_t)0xffffffffu); }\n'
            '     goto L_7000fcde30; }'
            ' uint64_t ea = c->x[21] + 0x318ull; uint64_t v = LD32(ea); x8 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr w8, [x21, #0x318] (removal: sibling manager never built, guarded\n'
            "            to the sibling's nothing-removed ret with the own index reset) */")


def _resource_manager_removal_guard_2(gen, a):
    assert _word(gen, a) == 0xb9431aa8, hex(_word(gen, a))  # ldr w8, [x21, #0x318] (the count)
    assert _word(gen, a - 4) == 0xd63f0100, hex(_word(gen, a - 4))  # blr x8 (the virtual probe)
    assert _word(gen, a + 4) == 0x7100051f, hex(_word(gen, a + 4))  # cmp w8, #1 (the count probe)
    assert _word(gen, a + 8) == 0x540001eb, hex(_word(gen, a + 8))  # b.lt #0x7000fcdeac
    return ('{ if (c->x[21] - 0x7000000000ull >= 0x320000000ull) { c->x[20] = 0ull;'
            ' goto L_7000fcde30; }'
            ' uint64_t ea = c->x[21] + 0x318ull; uint64_t v = LD32(ea); x8 = (uint64_t)(v); }'
            f'  /* {a:#x}: ldr w8, [x21, #0x318] (removal post-search: same, guarded to the\n'
            "            sibling's nothing-removed ret -- its x20 reload answers 0) */")


# The never-built param subsystem (game_sites.py param_array_* guards, tools/patches.py):
# run68 cleared the resource-manager family and went deepest yet -- the registrar's param-table
# chain ran through the framework step f_700127d4d0 into the giant builder thunk f_70015959c4 --
# and died with signal 11 accessing 0x40: the dump's host pc f_7000f4b830+de pins the param
# array constructor's str x0, [x20, #0x40] at 0x7000f4b860, the dump's guest lr exactly. The
# alloc thunk f_7000007c20 worked (the dump's x0 is a live heap block) but the object it stores
# into is 0: the builder thunk calls the array wrapper f_7000f4b8ac twice with x0 =
# [[0x7001d6c5e8]] / [[0x7001d6f250]], the never-built subsystems' singleton pointers, and the
# ctor's first store faults. Both steps are void setup whose callers ignore the answer (the
# ctor's only caller is the wrapper, whose bl return feeds only a cbz w22 re-check; the
# wrapper's two callers are the thunk, which clobbers x0 immediately), and the wrapper's own
# [x19, #8] / [x19, #0xc0] / [x19, #0x58] reads on the same null object would fault next, so
# both functions answer at entry with their callers' ignored answer 0 for an object off the
# guest map: with no subsystem object there is nothing to allocate into, the thunk carries on
# with its live heap and data cells. With a real built subsystem both re-execute their spill
# prologues untouched (a skipped prologue is net-neutral: the epilogue restores sp either way).
def _param_array_ctor_guard(gen, a):
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]! (entry)
    return ('{ if (x0 - 0x7000000000ull >= 0x320000000ull) { c->x[0] = 0ull; return; }'
            ' uint64_t ea = sp_ - 48; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); sp_ = ea; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (param array ctor: subsystem object'
            " never built, the step's callers ignore its answer) */")


def _param_array_step_guard(gen, a):
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]! (entry)
    return ('{ if (x0 - 0x7000000000ull >= 0x320000000ull) { c->x[0] = 0ull; return; }'
            ' uint64_t ea = sp_ - 48; ST64(ea, c->x[29]); ST64(ea + 8, x30); sp_ = ea; }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (param array step: subsystem singleton'
            ' never built, the builder thunk ignores both returns) */')


def _resource_manager_rand_guard(gen, a):
    assert _word(gen, a) == 0x29402408, hex(_word(gen, a))  # ldp w8, w9, [x0] (the rng state)
    assert _word(gen, a + 4) == 0x4a082d08, hex(_word(gen, a + 4))  # eor w8, w8, w8, lsl #11
    return ('{ if (x0 - 0x7000000000ull >= 0x320000000ull) { c->x[0] = 0ull; return; }'
            ' uint64_t ea = x0 + 0; uint64_t a = LD32(ea), b = LD32(ea + 4);'
            ' x8 = (uint64_t)(a); x9 = (uint64_t)(b); }'
            f'  /* {a:#x}: ldp w8, w9, [x0] (rng: never-built state singleton off the guest map,'
            ' the step answers its own returned new state 0) */')


# The framework step's dirty x19 (game_sites.py framework_x19_load_guard_1..17, tools/patches.py):
# run69 cleared the param-array family and the whole param-table section ran to completion --
# deepest boot yet -- and died with signal 11 accessing 0: the dump's host pc f_700127d4d0+4484
# objdump-pins the lifted LD64(c->x[19] + 8) of ldr x2, [x19, #8] at 0x700127ec90, right after
# the call the dump's block shows. The dump's x19 = 0x646f727000000001 -- the ParamHolder union
# {int i; char c[4]} cell {1, "prod"} (ActorInfo.product.sbyml, the last RomFS file listed)
# read as an object pointer. The step's x19 is its incoming x0 stack-buffer argument and the
# hash-lookup helper behind the thunk f_7000ea1e14 (body f_7000ea1e18, mov x19, x2 at
# 0x7000ea1e38) reuses the callee-saved x19 without restoring it -- on a real Switch the
# callee leaves its own valid entry pointer there, so a real guest never faults here. The step
# reloads x19 only in its epilogue (ldp x20, x19, [sp, #0x50] at 0x700127ef48), so all sixteen
# [x19] entry reads from the fault to the epilogue see the dirty cell: every load guards as a
# conditional load-skip answering null (the sweep's audit shows each consumer either cbz/cbnz
# the load on its own null branch -- sites 2, 6, 17 -- or passes it as the possibly-null entry
# name/value into callees the resource-manager family already taught to take null), and with a
# real Switch's callee left an on-map pointer here every guard re-executes its load untouched.
def _framework_x19_load_guard(gen, a):
    assert _word(gen, a) == 0xf9400662, hex(_word(gen, a))  # ldr x2, [x19, #8] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) c->x[2] = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x8ull; uint64_t v = LD64(ea); c->x[2] = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x2, [x19, #8] (the fault: dirty x19 param cell, null name to the'
            " query's own cbz x20 path) */")


def _framework_x19_load_guard_2(gen, a):
    assert _word(gen, a) == 0xf9400668, hex(_word(gen, a))  # ldr x8, [x19, #8] (the entry pointer)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x8 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x8ull; uint64_t v = LD64(ea); x8 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x8, [x19, #8] (its own cbz x8 skips on the null answer) */')


def _framework_x19_load_guard_3(gen, a):
    assert _word(gen, a) == 0xf9400660, hex(_word(gen, a))  # ldr x0, [x19, #8] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x8ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19, #8] (null name to the callee, as the manager family'
            ' taught) */')


def _framework_x19_load_guard_4(gen, a):
    assert _word(gen, a) == 0xf9400260, hex(_word(gen, a))  # ldr x0, [x19] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19] (null name to the callee) */')


def _framework_x19_load_guard_5(gen, a):
    assert _word(gen, a) == 0xa9400a61, hex(_word(gen, a))  # ldp x1, x2, [x19] (name and value)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) { c->x[1] = 0ull; c->x[2] = 0ull; }'
            ' else { uint64_t ea = c->x[19] + 0; uint64_t a = LD64(ea), b = LD64(ea + 8);'
            ' c->x[1] = (uint64_t)(a); c->x[2] = (uint64_t)(b); } }'
            f'  /* {a:#x}: ldp x1, x2, [x19] (null name and value to the callee) */')


def _framework_x19_load_guard_6(gen, a):
    assert _word(gen, a) == 0xf9400668, hex(_word(gen, a))  # ldr x8, [x19, #8] (the entry pointer)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x8 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x8ull; uint64_t v = LD64(ea); x8 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x8, [x19, #8] (its own cbz x8 skips on the null answer) */')


def _framework_x19_load_guard_7(gen, a):
    assert _word(gen, a) == 0xf9400660, hex(_word(gen, a))  # ldr x0, [x19, #8] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x8ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19, #8] (null name to the callee) */')


def _framework_x19_load_guard_8(gen, a):
    assert _word(gen, a) == 0xf9400660, hex(_word(gen, a))  # ldr x0, [x19, #8] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x8ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19, #8] (null name to the callee) */')


def _framework_x19_load_guard_9(gen, a):
    assert _word(gen, a) == 0xf9400260, hex(_word(gen, a))  # ldr x0, [x19] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19] (null name to the callee) */')


def _framework_x19_load_guard_10(gen, a):
    assert _word(gen, a) == 0xf9400268, hex(_word(gen, a))  # ldr x8, [x19] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x8 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); x8 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x8, [x19] (spilled to [sp, #8] for the callee, null spills take'
            ' the own check) */')


def _framework_x19_load_guard_11(gen, a):
    assert _word(gen, a) == 0xf9400260, hex(_word(gen, a))  # ldr x0, [x19] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19] (null name to the callee) */')


def _framework_x19_load_guard_12(gen, a):
    assert _word(gen, a) == 0xf9400261, hex(_word(gen, a))  # ldr x1, [x19] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) c->x[1] = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); c->x[1] = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x1, [x19] (null name as the callee\'s x1) */')


def _framework_x19_load_guard_13(gen, a):
    assert _word(gen, a) == 0xf9400262, hex(_word(gen, a))  # ldr x2, [x19] (the entry value)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) c->x[2] = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); c->x[2] = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x2, [x19] (null value as the thunk\'s x2) */')


def _framework_x19_load_guard_14(gen, a):
    assert _word(gen, a) == 0xf9400260, hex(_word(gen, a))  # ldr x0, [x19] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19] (null name to the callee) */')


def _framework_x19_load_guard_15(gen, a):
    assert _word(gen, a) == 0xf9400260, hex(_word(gen, a))  # ldr x0, [x19] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19] (null name to the callee) */')


def _framework_x19_load_guard_16(gen, a):
    assert _word(gen, a) == 0xf9400260, hex(_word(gen, a))  # ldr x0, [x19] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x0ull; uint64_t v = LD64(ea); x0 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x0, [x19] (null name to the callee) */')


def _framework_x19_load_guard_17(gen, a):
    assert _word(gen, a) == 0xf9400661, hex(_word(gen, a))  # ldr x1, [x19, #8] (the entry name)
    return ('{ if (c->x[19] - 0x7000000000ull >= 0x320000000ull) c->x[1] = 0ull;'
            ' else { uint64_t ea = c->x[19] + 0x8ull; uint64_t v = LD64(ea); c->x[1] = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x1, [x19, #8] (its own cbnz takes the null fall-through) */')


# The holder's dirty sub-array (game_sites.py holder_array_init_guard, tools/patches.py):
# run70 cleared the dirty-x19 family -- every guarded load answered null and the param-table
# chain walked one level deeper: the step's callee f_7001550dec read the stack buffer's
# [x0, #0x70] object (valid), whose sibling f_7001551ee4 alloc'd the 0x10 entry, stored it at
# [x19, #0x18], init'd it, then read the holder's old sub-array pointer [x19, #0x10] and
# cbz-branched on it before calling the node init f_700155210c -- which died with signal 11
# accessing 0x6800000014, the dump's host pc f_700155210c+fa objdump-pinning the pre-index
# str wzr, [x21, #0x10]! at 0x700155214c (the dump's x19 = x21 = 0x6800000004 exactly): the
# ParamHolder union cell {4, "h"} read as the sub-array pointer -- the next raw param cell of
# the never-built subsystem where a built one would hold a zeroed head node. Every access in
# the init runs on that cell (the node walk spans [x19, #0x10] through [x19, #0x2c8] and the
# node compares read [x9, #0x18..#0x2c8] tables off it), so the guard returns at entry with
# the answer 0 of the init's own failed singleton alloc (its cbz x0 tail 0x70015524b8 is the
# same done path), the caller ignores x0 after its bl at 0x7001551f2c, and with a real built
# subsystem the on-map pointer re-executes the spill frame untouched.
def _holder_array_init_guard(gen, a):
    assert _word(gen, a) == 0xd10183ff, hex(_word(gen, a))  # sub sp, sp, #0x60 (the frame, entry)
    assert _word(gen, a + 0x18) == 0x910043fd, hex(_word(gen, a + 0x18))  # add x29, sp, #0x10 (fp)
    assert _word(gen, a + 0x1c) == 0xaa0003f3, hex(_word(gen, a + 0x1c))  # mov x19, x0 (the object)
    return ('{ if (x0 - 0x7000000000ull >= 0x320000000ull) { c->x[0] = 0ull; return; }'
            ' sp_ = (uint64_t)(sp_ - 0x60ull); }'
            f'  /* {a:#x}: sub sp, sp, #0x60 (sub-array init: the holder\'s never-built'
            ' sub-array pointer is the {4,"h"} ParamHolder cell off the guest map -- the step'
            ' answers its own null-alloc done 0, the caller ignores x0) */')


# The param-table step's dirty virtual call (game_sites.py param_holder_vcall_guard,
# tools/patches.py): run71 cleared the holder-init family -- the node init answered 0 and the
# chain kept walking: the step f_7001550dec (the callee the dirty-x19 family's site 1 already
# taught to take the null name) alloc'd its node through f_7001551ee4 (now whole), then ran its
# own tail and died at lr 0x7001550e24 on its blr x8 at 0x7001550e20 with FATAL: no function at
# a90657f6f9002bf7 -- the dump's x8 exactly: the step's object field [x19, #0x30] answered
# 0x7001d04098, a raw .rodata cell -- and the never-built subsystem left a code address in its
# first word, so the "vtable" slot [x8, #0x10] read two raw instruction words (0xa90657f6
# f9002bf7). The loads themselves never fault; the lifted c->pc = x8; rt_dispatch(c) dispatch
# found no function there. The guard skips the dispatch when the target is off the guest map
# and answers 0 -- the caller's next lifted line reloads x0 from [x19, #0x40] and ignores the
# answer -- and dispatches untouched on a real built object's on-map vtable slot.
def _param_holder_vcall_guard(gen, a):
    assert _word(gen, a) == 0xd63f0100, hex(_word(gen, a))  # blr x8 (the virtual step)
    assert _word(gen, a - 4) == 0xf9400908, hex(_word(gen, a - 4))  # ldr x8, [x8, #0x10] (the slot)
    assert _word(gen, a - 8) == 0xf9400008, hex(_word(gen, a - 8))  # ldr x8, [x0] (the "vptr")
    return ('{ if (x8 - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { c->pc = x8; x30 = 0x7001550e24ull; c->x[0] = x0; c->x[8] = x8;'
            ' c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x30 = c->x[30]; } }'
            f'  /* {a:#x}: blr x8 (dirty "vtable" slot -- two raw instruction words off the'
            ' guest map -- the dispatch skips to the ignored 0 the caller reloads) */')


# The param step's dirty-field callees (game_sites.py entry_field_lookup_guard/_2,
# entry_config_fill_guard, tools/patches.py): run72 cleared the dirty-"vtable" family -- the
# virtual step skipped to its ignored 0 and the step f_7001550dec ran past it into its tail --
# and died with signal 11 accessing 0xbe912318: the dump's host pc f_7001394864+119 objdump-
# pins the result store str x0, [x20, #0x20] at 0x70013948c0 (the dump's lr exactly) into the
# param table's entry field -- the dump's x20 = 0xbe9122f8, the step's dirty [x19, #0x40]
# object field (another raw cell of the never-built subsystem, this one holding utf8 bytes)
# read as the entry. The virtual [x21, #0x18] step and the string lookup f_70013959a4 inside
# ran fine (the dump's x0 = 0, the answer reused); only the store into the raw cell faulted.
# The sweep of the step's tail shows the same story at its two remaining dirty-field callees:
# f_7001382998 (0x7001550e44, x0 = the [x19, #0x90] field, its only store str x0, [x19, #0x28]
# faults the same way) and f_700138e5b8 (0x7001550e54, x0 = the [x19, #0x60] base + 0x48, a
# huge config fill whose first store str w0, [x19, #0x68] faults and whose ~20 further loads
# and stores all hang off that base); f_700135e048 (0x7001550e38) is a bare ret, no guard.
# All three guard at entry with the answer 0 for an object off the guest map -- every caller
# reloads x0 or x8 from its own table right after the bl (and the cbz x20 branch the step's
# null x2 already takes skips the rest) -- and with a real built subsystem the on-map objects
# re-execute the spill frame untouched.
def _entry_field_lookup_guard(gen, a):
    assert _word(gen, a) == 0xa9bd7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x30]! (the frame, entry)
    assert _word(gen, a + 0x20) == 0xaa0003f4, hex(_word(gen, a + 0x20))  # mov x20, x0 (the entry)
    assert _word(gen, a + 0x5c) == 0xf9001280, hex(_word(gen, a + 0x5c))  # str x0, [x20, #0x20] (the fault)
    return ('{ if (x0 - 0x7000000000ull >= 0x320000000ull) { c->x[0] = 0ull; return; }'
            ' { uint64_t ea = sp_ - 48; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); sp_ = ea; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x30]! (lookup result store: the entry is the'
            ' dirty [x19, #0x40] raw cell -- the step returns the lookup\'s ignored 0, the'
            ' caller reloads x0 from [x19, #0x38] right after) */')


def _entry_field_lookup_guard_2(gen, a):
    assert _word(gen, a) == 0xa9be7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x20]! (the frame, entry)
    assert _word(gen, a + 0xc) == 0xaa0003f3, hex(_word(gen, a + 0xc))  # mov x19, x0 (the entry)
    assert _word(gen, a + 0x28) == 0xf9001660, hex(_word(gen, a + 0x28))  # str x0, [x19, #0x28] (the sibling store)
    return ('{ if (x0 - 0x7000000000ull >= 0x320000000ull) { c->x[0] = 0ull; return; }'
            ' { uint64_t ea = sp_ - 32; ST64(ea, x29); ST64(ea + 8, x30); sp_ = ea; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x20]! (lookup result store sibling: the entry'
            ' is the dirty [x19, #0x90] raw cell, the same ignored-0 entry return) */')


def _entry_config_fill_guard(gen, a):
    assert _word(gen, a) == 0xa9ba7bfd, hex(_word(gen, a))  # stp x29, x30, [sp, #-0x60]! (the frame, entry)
    assert _word(gen, a + 0x24) == 0xaa0003f3, hex(_word(gen, a + 0x24))  # mov x19, x0 (the base)
    assert _word(gen, a + 0x40) == 0xb9006a60, hex(_word(gen, a + 0x40))  # str w0, [x19, #0x68] (the first store)
    return ('{ if (x0 - 0x7000000000ull >= 0x320000000ull) { c->x[0] = 0ull; return; }'
            ' { uint64_t ea = sp_ - 96; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); sp_ = ea; } }'
            f'  /* {a:#x}: stp x29, x30, [sp, #-0x60]! (config fill: the base is the dirty'
            ' [x19, #0x60] raw cell + 0x48 -- every one of its ~20 loads and stores hangs off'
            ' it, the step returns its ignored 0 to the caller\'s own cbz x20 tail) */')


# The step tail's unbound sead delegate (game_sites.py param_delegate_invoke_guard,
# tools/patches.py): run73 cleared the dirty-field callee family -- the step f_7001550dec ran
# its whole tail into its sub-step f_7001550ed0 -- and died on an SDK assertion instead of a
# fault: the log's sead report printed "SDK has been aborted or failed assertion with no
# message." and the FATAL is svcBreak(reason=0) at sdk 0x700267974c; the guest frames
# 7001550ee8 7001550e90 700127ec98 pin the param chain exactly (framework step, guarded tail,
# sub-step). The sub-step's bl #0x70015a19e0 at 0x7001550ee4 is a module import thunk (adrp /
# ldr x17, [x16, #0xdb8] / br x17 on GOT slot 0x7001d78db8) the resolver wired to the sdk's
# delegate invoke f_7002640e30: it ldrb's the delegate's state byte at [x0, #0x28] and
# dispatches state 1 or 2 -- here it fell to its assert tail because the delegate at object +
# 0x240 was never bound (the same never-built registrar -- the byte is raw). The guard answers
# the invoke's own "nothing changed" 0 and skips the call: the next line's tbz w0, #0 takes
# the sub-step's own return and its caller's tail is all cbz-guarded (f_7000f093f0's null
# singleton answer, the [x19, #0x2a0] null check). With a real Switch's built delegate the
# state byte is 1 or 2 and the guarded call dispatches untouched; the state byte is inside the
# step's valid object (its [x19, #0x270]-style loads ran), so the guard's own load is safe.
def _param_delegate_invoke_guard(gen, a):
    assert _word(gen, a) == 0x940142bf, hex(_word(gen, a))  # bl #0x70015a19e0 (the invoke thunk)
    assert _word(gen, a + 4) == 0x360000a0, hex(_word(gen, a + 4))  # tbz w0, #0 (nothing-changed ret)
    return ('{ if (LD8(x0 + 0x28ull) - 1ull > 1ull) x0 = 0ull;'
            ' else { extern void f_70015a19e0(Cpu *);'
            ' x30 = 0x7001550ee8ull; c->x[0] = x0; c->x[19] = x19; c->x[29] = x29;'
            ' c->x[30] = x30; c->sp = sp_; f_70015a19e0(c); x0 = c->x[0]; x8 = c->x[8];'
            ' x30 = c->x[30]; } }'
            f'  /* {a:#x}: bl #0x70015a19e0 (delegate invoke: the state byte at [x0, #0x28] is'
            ' raw -- neither bound 1 nor 2 -- the guard answers the invoke\'s own nothing-'
            ' changed 0 so the tbz takes the step\'s return; a built delegate re-invokes) */')


# The step tail's ready-flag helper on the raw field (game_sites.py entry_ready_flag_guard,
# tools/patches.py): run74 cleared the unbound-delegate family -- the sub-step's invoke skipped
# to its nothing-changed 0, the sub-step returned through its own ret, and the step
# f_7001550dec reached its LAST tail branch for the first time: its epilogue restored the
# framework step's dirty x19 (the {1,"prod"} ParamHolder cell -- the #33 guards load-skip
# reads but never scrub x19 itself), and b #0x7001557a08 at 0x7001550ebc carried x0 = the
# never-written [object, #0x2a0] field, the raw word 1, into the ready-flag helper -- and died
# with signal 11 accessing 0x9 at the entry ldrb w8, [x0, #8] (the dump: x0 = 1,
# x19 = 0x646f727000000001, lr = the framework step's 0x700127ec98, the thunk's return
# address). The helper reads its object's ready-flag byte at +8, returns when already set,
# else probes the (null) settings singleton and its own null answer skips both flag stores.
# The guard returns at entry with the neutral 0 for an object off the guest map -- the
# framework step overwrites x0 and x8 with its next loads (the #33 audit: site 1's consumer
# reassigns both before use), so the tail's ignored answer cannot mislead -- and the real
# Switch's built ready object (or null, whose cbz the never-built world never reaches here)
# re-probes the flag byte untouched.
def _entry_ready_flag_guard(gen, a):
    assert _word(gen, a) == 0x39402008, hex(_word(gen, a))  # ldrb w8, [x0, #8] (the ready flag, entry)
    assert _word(gen, a + 4) == 0x34000048, hex(_word(gen, a + 4))  # cbz w8 (the flag test)
    assert _word(gen, a + 8) == 0xd65f03c0, hex(_word(gen, a + 8))  # ret (the flag-set done path)
    return ('{ if (x0 - 0x7000000000ull >= 0x320000000ull) { c->x[0] = 0ull; return; }'
            ' { uint64_t ea = x0 + 0x8ull; uint64_t v = LD8(ea); x8 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldrb w8, [x0, #8] (ready flag: x0 is the never-written'
            ' [object, #0x2a0] raw word 1 off the guest map -- the helper returns its own'
            ' flag-set done ret with the neutral 0 the framework step overwrites; a built'
            ' ready object re-probes the byte untouched) */')


# The step query object's dirty "vtable" pair (game_sites.py query_object_vtable_guard /
# query_object_vcall_guard, tools/patches.py): run75 cleared the ready-flag family -- the
# whole param chain answered and the framework step ran past bl #0x7001550dec to its virtual
# probe -- and died with signal 11 accessing 0: the dump's host pc f_700127d4d0+4558
# objdump-pins mov 0x28(%rax),%rax, the lifted LD64(x8 + 0x28) of ldr x8, [x8, #0x28] at
# 0x700127eca0 (lr 0x700127ec98 exactly, the param step's return). The pair: ldr x8, [x22]
# at 0x700127ec98 reads the never-built registration slot -- null where a registered
# resource-manager query object belongs -- and the "vtable" slot load faults on it; the
# blr x8 at 0x700127eca4 dispatches off the null slot's answer. The tail at 0x700127ecb0
# reloads x0 from [x23] and only branches on x21, so the dispatch's answer is ignored: the
# load guards as a load-skip answering null (x8 = 0, off-map by the idiom too), the dispatch
# as the #35 dispatch-skip answering 0 -- the same "nothing registered" answer the
# resource-manager family already established -- and with a real Switch's registered object
# (on-map "vptr", on-map slot) both re-execute untouched.
def _query_object_vtable_guard(gen, a):
    assert _word(gen, a) == 0xf9401508, hex(_word(gen, a))  # ldr x8, [x8, #0x28] (the slot)
    assert _word(gen, a + 4) == 0xd63f0100, hex(_word(gen, a + 4))  # blr x8 (the virtual probe)
    assert _word(gen, a + 8) == 0xf10006bf, hex(_word(gen, a + 8))  # cmp x21, #1 (the tail)
    return ('{ if (x8 - 0x7000000000ull >= 0x320000000ull) x8 = 0ull;'
            ' else { uint64_t ea = x8 + 0x28ull; uint64_t v = LD64(ea); x8 = (uint64_t)(v); } }'
            f'  /* {a:#x}: ldr x8, [x8, #0x28] (query object: the registration slot read null --'
            ' the "vtable" slot load skips to 0, off-map for the dispatch below) */')


def _query_object_vcall_guard(gen, a):
    assert _word(gen, a) == 0xd63f0100, hex(_word(gen, a))  # blr x8 (the virtual probe)
    assert _word(gen, a - 4) == 0xf9401508, hex(_word(gen, a - 4))  # ldr x8, [x8, #0x28] (the slot)
    assert _word(gen, a + 4) == 0xf10006bf, hex(_word(gen, a + 4))  # cmp x21, #1 (the tail)
    return ('{ if (x8 - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
            ' else { c->pc = x8; x30 = 0x700127eca8ull; c->x[0] = x0; c->x[8] = x8;'
            ' c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x30 = c->x[30]; } }'
            f'  /* {a:#x}: blr x8 (query virtual: the null slot answers nothing-registered 0,'
            ' the tail reloads x0 from [x23] and branches only on x21) */')


# The framework step's debug-logging tail (game_sites.py log_tail_* guards, tools/patches.py):
# run76 cleared the query-virtual family -- the step ran past its virtual probe into the
# post-chain debug-logging tail (0x700127ece4..0x700127efd4) -- and died with signal 11
# accessing 0x1: the dump's host pc f_7000007c20+130 pins the alloc thunk reading its name
# argument INSIDE the resource-node getter f_70010860b4 (the step's bl at 0x700127ece0 passes
# x0 = x20, the never-built param value's raw word 1, and the getter's cache-miss path allocs
# a 0x430 node keyed on that name; the dump: x0 = 0x430, x1 = 1, guest frames 70010860f8
# 700127ece4). The static sweep of the whole tail shows the same root cause everywhere: the
# never-built registrar left every param/resource singleton slot null in .bss and every key a
# raw word, so the tail's ~20 singleton getters alloc with a dirty key (the alloc thunk derefs
# it) and its publishers store through the null singleton itself. Three loads inside the step
# double-deref those slots (0x700127ecf0 / 0x700127ed50 / 0x700127ee08: [slot] is null, ldr x0,
# [x8] faults) -- they answer x0 = 0 as the null singleton to the guarded callee right after.
# Every one of the 20 call sites ignores the answer (each reloads x0 from [x21]/its own table
# right after the bl, audited one by one), so the entry guards answer the resource family's
# neutral 0 for an off-map x0 (key OR singleton), and with a real Switch's built subsystem the
# keys and singletons are on-map -- every guarded line re-executes its spill/store
# byte-identical. (The _query_object_vcall_guard text above closes the run75 family.)
# The registry-node ctor f_7000008168 and its step caller need three extra guard shapes: an
# STP pair whose two sources differ (incl. the 32-bit width at 0x7000008538), and a pre-index
# store skip that still performs the base write-back (the str xzr, [x25, #8]! at 0x7000008348;
# the literal-8 base it leaves behind feeds the guarded stores at 0x7000008d7c/0x70000086f4).
def _offmap_ldp_load_guard(w, cond, dst1, dst2, ea, note):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))  # ldp (pair load)
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull) {{ {dst1} = 0ull; {dst2} = 0ull; }}'
                f' else {{ uint64_t ea = {ea}; uint64_t a = LD64(ea), b = LD64(ea + 8);'
                f' {dst1} = (uint64_t)(a); {dst2} = (uint64_t)(b); }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_u128_load_guard(w, cond, dst1, dst2, ea, rest, note):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))  # ldp into a v-register pair
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull) {{ {dst1} = 0; {dst2} = 0; }}'
                f' else {{ uint64_t ea = {ea}; {rest} }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_lda_guard(w, cond, dst, note):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))  # lda8 (acquire load)
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull) {dst} = 0ull;'
                f' else {{ {dst} = (uint64_t)(lda8({cond})); }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_pair_store_guard(w, cond, ea, src1, src2, note, st='ST64', gap=8):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))  # STP pair with two different sources
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull);'
                f' else {{ uint64_t ea = {ea}; {st}(ea, {src1}); {st}(ea + {gap}, {src2});'
                f' }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_pre_store_guard(w, cond, add, note, st='ST64', zero='0ull'):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))  # str xzr, [cond, #add]! (pre-index)
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull)'
                f' {cond} = (uint64_t)({cond} + {add});'
                f' else {{ uint64_t ea = {cond} + {add}; {st}(ea, {zero}); {cond} = ea; }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_pre_load_guard(w, cond, add, dst, note):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))  # ldr dst, [cond, #add]! (pre-index)
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull)'
                f' {{ {cond} = (uint64_t)({cond} + {add}); {dst} = 0ull; }}'
                f' else {{ uint64_t ea = {cond} + {add}; uint64_t v = LD64(ea); {cond} = ea;'
                f' {dst} = (uint64_t)(v); }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _tail_guard(spill, w_entry, off, w_pin, note, cond='x0'):
    def guard(gen, a):
        assert _word(gen, a) == w_entry, hex(_word(gen, a))
        assert _word(gen, a + off) == w_pin, hex(_word(gen, a + off))
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull)'
                ' { c->x[0] = 0ull; return; }'
                f' {spill} }}  /* {a:#x}: {note} */')
    return guard


def _tail_load_guard(off, w_pin, note):
    def guard(gen, a):
        assert _word(gen, a) == 0xf9400100, hex(_word(gen, a))  # ldr x0, [x8] (the slot)
        assert _word(gen, a + off) == w_pin, hex(_word(gen, a + off))
        return ('{ if (x8 - 0x7000000000ull >= 0x320000000ull) x0 = 0ull;'
                ' else { uint64_t ea = x8 + 0x0ull; uint64_t v = LD64(ea);'
                ' x0 = (uint64_t)(v); } }'
                f'  /* {a:#x}: {note} */')
    return guard


_STP30 = '{ uint64_t ea = sp_ - 48; ST64(ea, c->x[29]); ST64(ea + 8, c->x[30]); sp_ = ea; }'
_STP30X = '{ uint64_t ea = sp_ - 48; ST64(ea, c->x[29]); ST64(ea + 8, x30); sp_ = ea; }'

# The framework step's node-builder chain (game_sites.py node_build_*/lockmgr_*/pushmgr_*/
# step_node_*/node_init_*/list_clear_* guards, tools/patches.py): run77 cleared the log_tail
# family -- the step ran from its post-chain block to its bl #0x7000003f10 node-builder --
# and died with signal 11 accessing 0: the dump's host pc f_7000003f10+184 objdump-pins the
# 4354 block's second LD64 (ldr x8, [x19] then ldr x8, [x8, #0x80] at 0x7000004354/0x7000004360
# -- the never-built registry hands the builder its object as a raw rodata string, the dump:
# x19 = 0x70015e615b, so its first word is an ASCII cell and the "vtable" slot load faults).
# The static sweep shows the same root cause through the whole chain: the builder's factory/
# lock/push paths double-deref static-link addend words (.data slots at [0x7001d69430]/
# [0x7001d6af80] holding file-relative pointers, off-map to the recompiler), the answered
# 0-node flows into the step's ldr x8, [x21] / ldr x8, [x8, #0x28] / blr x8 probe pair, and
# the node registrar f_700127efe0 and 256-entry list-clear f_700127f150 deref their null/
# addend singletons and store flags through off-map slots. The three factories below skip
# one guest load or store when its base pointer is off the guest map (answering the lifted
# destination with 0) and re-execute it byte-identical otherwise -- the #31 off-map idiom --
# and the blr sites skip their dispatch answering 0 (the #35/#39 form) into code that ignores
# the answer or is itself guarded: off-map OR not a lifted function (run78 cleared the
# ASCII-vtable fault, but its init-time caller's real object's slot held the unrelocated
# addend 0x70016574c2 -- on-map yet odd/tagged, a dispatch FATAL through the range check
# alone -- so the probe now consults dispatch_lookup, NULL for any address that is no
# recompiled function, which a real Switch's relocated slot always is), so a real Switch's
# built chain never differs.
def _offmap_load_guard(w, cond, dst, ea, ld, note):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull) {dst} = 0ull;'
                f' else {{ uint64_t ea = {ea}; uint64_t v = {ld}(ea); {dst} = (uint64_t)(v);'
                f' }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_store_guard(w, cond, ea, st, src, note):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull);'
                f' else {{ uint64_t ea = {ea}; {st}(ea, {src}); }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_blr_guard(disp, note, cond='x8', answer='c->x[0] = 0ull', w=0xd63f0100):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))  # blr x8 / blr x9 (the virtual probe)
        return ('{ extern GuestFn dispatch_lookup(uint64_t);'
                f' if ({cond} - 0x7000000000ull >= 0x320000000ull || !dispatch_lookup({cond}))'
                f' {answer};'
                f' else {{ {disp} }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_stp_guard(w, cond, ea, src, note):
    def guard(gen, a):
        assert _word(gen, a) == w, hex(_word(gen, a))
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull);'
                f' else {{ uint64_t ea = {ea}; ST64(ea, {src}); ST64(ea + 8, {src});'
                f' }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _offmap_call_skip_guard(cond, disp, note, answer='c->x[0] = 0ull', w=None):
    """Skip a thunk call whose pointer argument is off-map (family #49: run101's 0x70 -- the
    always-call flip exposed that the 0x70015a03xx..0x70015a0axx service thunks dispatch into
    GUARD-FREE sdk lifts (f_700264d8fc is a bare `str wzr, [x0]`), so a dead base like x21 = 0x38
    stores through dst = x21 + 0x38 and faults inside the stub. Those stubs (mutex/mem) do their
    work THROUGH the argument, so with a dead argument calling gains nothing: skip, like before
    the flip. The lock/TLS/registrar thunks (0x700159fexx, f_700000151c) keep _always_call --
    their side effects are exactly what the registry needs and their lifts are guarded.
    w= takes the exact word for a TAIL thunk jump (family #52: 0x7000000a44 is `b`, not `bl`,
    and ends the block -- such a site's answer must carry `return` too, else the guard block
    falls through into the block it branched over)."""
    def guard(gen, a):
        if w is not None:
            assert _word(gen, a) == w, hex(_word(gen, a))  # tail jump (b #<target>)
        else:
            assert _word(gen, a) & 0xFC000000 == 0x94000000, hex(_word(gen, a))  # bl #<target>
        return ('{' + f' if ({cond} - 0x7000000000ull >= 0x320000000ull) {{ {answer}; }}'
                f' else {{ {disp} }} }}'
                f'  /* {a:#x}: {note} */')
    return guard


def _always_call(cond, disp, note, answer='c->x[0] = 0ull'):
    def guard(gen, a):
        assert _word(gen, a) & 0xFC000000 == 0x94000000, hex(_word(gen, a))  # bl #<target>
        # run85's gdb snapshot proved every data slot RELOCATED correctly (the registry slot
        # holds its full base-plus-addend pointer); the registry simply stays empty because
        # the guest passes x0 = 0 ("no argument") to these thunks as a LEGITIMATE value -- an
        # off-map skip guard therefore denies side effects the guest needs (the lock-fail
        # block never fills, the init gate reads dead, nnMain returns, and no frame presents).
        # With every callee's lift now fully guarded, calling through a dead x0 is safe: each
        # dead deref inside answers 0 and any genuine object passes through. So always call.
        return ('{' + f' {disp} }}'
                f'  /* {a:#x}: {note} */')
    return guard


PATCHES = {
    'lookat_update': _lookat_update,
    'pc_map_focus': _pc_map_focus(False),
    'pc_map_focus_target': _pc_map_focus(True),
    'pc_map_focus_now': _pc_map_focus(True),
    'pc_button_group': _pc_button_group,
    'pc_cursor_manager': _pc_cursor_manager,
    'gyro_scene_actor': _gyro_scene_actor,
    'pause_options_update': _pause_option_state,
    'opt_two_redraw': _opt_two_redraw,
    'opt_two_select': _opt_two_callback(0),
    'opt_two_state': _opt_two_callback(1),
    'opt_two_decide': _opt_two_callback(2),
    'opt_two_after': _opt_two_callback(3),
    'opt_two_row_state': _opt_two_row_state,
    'opt_two_update_control': _opt_two_control(False),
    'opt_two_initial_control': _opt_two_control(True),
    'opt_two_left': _opt_two_horizontal,
    'opt_two_right': _opt_two_horizontal,
    'opt_create_rows': _opt_rows,
    'opt_row_init_flag_type': _opt_flag_type,
    'opt_read': _opt_read,
    'opt_store': _opt_store,
    'opt_reset': _opt_reset,
    'opt_msg_call': _opt_msg,
    'opt_decide': _opt_decide,
    'opt_update': _opt_tick,
    'opt_back_call': _opt_back,
    'dialog_texts': _dialog_texts,
    'dialog_back': _dialog_back,
    'title_update': _title_tick,
    'title_button': _title_event,
    'msg_lookup': _title_msg,
    'frame_wait': _frame_wait,
    'yaz0_stream': _yaz0_stream,
    'yaz0_stream_ret': _yaz0_stream_ret,
    'vfr_ratio': _vfr_ratio,
    'gui_speed': _gui_speed,
    'quick_menu_capture_alpha': _quick_menu_capture_alpha,
    'arrow_fall_gravity': _arrow_gravity,
    'surf_contact': _surf_contact,
    'surf_boost_remove': _surf_boost_remove,
    'surf_jump_request': _surf_jump_request,
    'stale_actor_helper': _stale_actor_helper,
    'stale_actor_target': _stale_actor_target,
    'phys_solver_steps': _solver_steps,
    'kf_angle': _kf_angle,
    'snd_frame_floor': _snd_frame_floor,
    'persp_matrix': _persp_matrix,
    'persp_matrix_offset': _persp_matrix_offset,
    'persp_unproject_y': _persp_unproject_y,
    'persp_unproject_x': _persp_unproject_x,
    'proj_update': _proj_update,
    'frustum_lr0': _frustum_load(0x2d550001, (1, 0), 'lr'),
    'frustum_lr1': _frustum_load(0x2d550c02, (2, 3), 'lr'),
    'frustum_tb0': _frustum_load(0x2d540800, (0, 2), 'tb'),
    'frustum_tb1': _frustum_load(0x2d540c02, (2, 3), 'tb'),
    'cam_stick': _cam_stick,
    'cam_pitch_chase': _cam_pitch,
    'cam_pitch_surf': _cam_pitch,
    'cam_pitch_wakeboard': _cam_pitch,
    'cam_pitch_aim': _cam_pitch_aim,
    'cam_pitch_item': _cam_pitch_aim,
    'cam_reverse_x': _cam_reverse(0),
    'cam_reverse_y': _cam_reverse(1),
    'traverse_scale': _traverse_scale,
    'traverse_scale_default': _traverse_scale_default,
    'grass_range': _grass_range,
    'grass_fade_blades': _grass_fade(27, 0x240),
    'grass_fade_quads': _grass_fade(24, 0x4),
    'grass_blade_slots': _grass_blade_slots,
    'grass_blade_cap_a': _grass_blade_cap,
    'grass_blade_cap_b': _grass_blade_cap,
    'grass_blade_cap_c': _grass_blade_cap_swap,
    'grass_blade_cap_c_max': _grass_blade_cap_max,
    'grass_blade_lateral_near': _grass_blade_lateral,
    'grass_blade_lateral_far': _grass_blade_lateral,
    'tree_ranges': _tree_ranges,
    'act_hold': _act_query(0),
    'act_trig': _act_query(1),
    'pouch_remove_arrows': _remove_arrows,
    'no_wear_store': _no_wear,
    'no_wear_hit': _no_wear_hit,
    'link_life_store': _link_life,
    'link_life_tick': _link_life,
    'stamina_store': _stamina,
    'debug_cursor_pool_guard': _debug_cursor_pool_guard,
    'debug_cursor_pane_guard': _debug_cursor_pane_guard,
    'debug_menu_key_guard': _debug_menu_key_guard,
    'debug_menu_len_guard': _debug_menu_len_guard,
    'debug_menu_page_guard': _debug_menu_page_guard,
    'debug_menu_cand_guard': _debug_menu_cand_guard,
    'debug_menu_path_guard': _debug_menu_path_guard,
    'debug_menu_hash_guard': _debug_menu_hash_guard,
    'shader_queue_guard': _shader_queue_guard,
    'debug_menu_reg_288_guard': _debug_menu_reg_288_guard,
    'debug_menu_reg_2b8_guard': _debug_menu_reg_2b8_guard,
    'debug_menu_reg_copy_guard': _debug_menu_reg_copy_guard,
    'debug_menu_reg_288c_guard': _debug_menu_reg_guard(0x50, 0x18, 0xb9428808, 'copy +0x288'),
    'debug_menu_reg_288f_guard': _debug_menu_reg_guard(0x40, 0x14, 0xf9414808, 'free +0x290'),
    'debug_menu_reg_2b8f_guard': _debug_menu_reg_guard(0x40, 0x14, 0xf9416008, 'free +0x2c0'),
    'debug_menu_reg_298_guard': _debug_menu_reg_guard(0x40, 0x18, 0x910a6000, '+0x298'),
    'debug_menu_reg_298c_guard': _debug_menu_reg_guard(0x50, 0x18, 0xb9429808, 'copy +0x298'),
    'debug_menu_reg_298f_guard': _debug_menu_reg_guard(0x40, 0x14, 0xf9415008, 'free +0x2a0'),
    'debug_menu_reg_2a8_guard': _debug_menu_reg_guard(0x40, 0x18, 0x910aa000, '+0x2a8'),
    'debug_menu_reg_2a8c_guard': _debug_menu_reg_guard(0x50, 0x18, 0xb942a808, 'copy +0x2a8'),
    'debug_menu_reg_2a8f_guard': _debug_menu_reg_guard(0x40, 0x14, 0xf9415808, 'free +0x2b0'),
    'debug_menu_reg_2c8_guard': _debug_menu_reg_guard(0x40, 0x18, 0x910b2000, '+0x2c8'),
    'debug_menu_reg_2c8c_guard': _debug_menu_reg_guard(0x50, 0x18, 0xb942c808, 'copy +0x2c8'),
    'debug_menu_reg_2c8f_guard': _debug_menu_reg_guard(0x40, 0x14, 0xf9416808, 'free +0x2d0'),
    'debug_menu_reg_278_guard': _debug_menu_reg_guard(0x40, 0x18, 0x9109e000, '+0x278'),
    'debug_menu_reg_278c_guard': _debug_menu_reg_guard(0x50, 0x18, 0xb9427808, 'copy +0x278'),
    'debug_menu_reg_278f_guard': _debug_menu_reg_guard(0x40, 0x14, 0xf9414008, 'free +0x280'),
    'uinj_db_guard': _uinj_db_guard,
    'light_rig_flag_guard': _light_rig_flag_guard,
    'param_ctor_ctx_guard': _param_ctor_ctx_guard,
    'actor_param_ctx_guard': _actor_param_ctx_guard,
    'param_list_xfer_guard': _param_list_xfer_guard,
    'param_subsys_guard': _param_subsys_guard,
    'gfx_system_list_guard': _gfx_system_list_guard,
    'actor_reg_field_guard': _actor_reg_field_guard,
    'actor_list_reg_guard_1': _actor_list_reg_guard_1,
    'actor_list_reg_guard_2': _actor_list_reg_guard_2,
    'actor_subsys_ref_guard': _actor_subsys_ref_guard,
    'subsys_consume_guard': _subsys_consume_guard,
    'registry_lookup_guard': _registry_lookup_guard,
    'record_subsys_init_guard': _record_subsys_init_guard,
    'subsys_list_init_guard': _subsys_list_init_guard,
    'subsys_list_reg_guard': _subsys_list_reg_guard,
    'subsys_record_mode_guard': _subsys_record_mode_guard,
    'subsys_param_array_guard': _subsys_param_array_guard,
    'subsys_entry_lookup_guard': _subsys_entry_lookup_guard,
    'subsys_index_get_guard_1': _subsys_index_get_guard_1,
    'subsys_index_get_guard_2': _subsys_index_get_guard_2,
    'subsys_index_get_guard_3': _subsys_index_get_guard_3,
    'subsys_entry_name_guard': _subsys_entry_name_guard,
    'subsys_entry_pick_guard': _subsys_entry_pick_guard,
    'dir_entry_accessor_guard': _dir_entry_accessor_guard,
    'dir_entry_accessor_guard_2': _dir_entry_accessor_guard_2,
    'dir_entry_accessor_guard_3': _dir_entry_accessor_guard_3,
    'dir_entry_accessor_guard_4': _dir_entry_accessor_guard_4,
    'dir_entry_accessor_guard_5': _dir_entry_accessor_guard_5,
    'fs_read_zero_guard': _fs_read_zero_guard,
    'fs_read_null_buffer_guard': _fs_read_null_buffer_guard,
    'fs_state_accessor_guard': _fs_state_accessor_guard,
    'fs_state_accessor_guard_2': _fs_state_accessor_guard_2,
    'fs_state_query_guard': _fs_state_query_guard,
    'fs_state_query_guard_2': _fs_state_query_guard_2,
    'framework_swap_guard': _framework_swap_guard,
    'physics_cfg_entry_guard': _physics_cfg_entry_guard,
    'load_balancer_entry_guard': _load_balancer_entry_guard,
    'load_balancer_entry_guard_2': _load_balancer_entry_guard_2,
    'load_balancer_handle_guard': _load_balancer_handle_guard,
    'load_balancer_handle_guard_2': _load_balancer_handle_guard_2,
    'physics_path_scan_guard': _physics_path_scan_guard,
    'sead_heap_alloc_guard': _sead_heap_alloc_guard,
    'resource_manager_chain_guard': _resource_manager_chain_guard,
    'resource_manager_count_guard': _resource_manager_count_guard,
    'resource_manager_reg_count_guard': _resource_manager_reg_count_guard,
    'resource_manager_removal_guard': _resource_manager_removal_guard,
    'resource_manager_removal_guard_2': _resource_manager_removal_guard_2,
    'resource_manager_rand_guard': _resource_manager_rand_guard,
    'param_array_ctor_guard': _param_array_ctor_guard,
    'param_array_step_guard': _param_array_step_guard,
    'framework_x19_load_guard': _framework_x19_load_guard,
    'framework_x19_load_guard_2': _framework_x19_load_guard_2,
    'framework_x19_load_guard_3': _framework_x19_load_guard_3,
    'framework_x19_load_guard_4': _framework_x19_load_guard_4,
    'framework_x19_load_guard_5': _framework_x19_load_guard_5,
    'framework_x19_load_guard_6': _framework_x19_load_guard_6,
    'framework_x19_load_guard_7': _framework_x19_load_guard_7,
    'framework_x19_load_guard_8': _framework_x19_load_guard_8,
    'framework_x19_load_guard_9': _framework_x19_load_guard_9,
    'framework_x19_load_guard_10': _framework_x19_load_guard_10,
    'framework_x19_load_guard_11': _framework_x19_load_guard_11,
    'framework_x19_load_guard_12': _framework_x19_load_guard_12,
    'framework_x19_load_guard_13': _framework_x19_load_guard_13,
    'framework_x19_load_guard_14': _framework_x19_load_guard_14,
    'framework_x19_load_guard_15': _framework_x19_load_guard_15,
    'framework_x19_load_guard_16': _framework_x19_load_guard_16,
    'framework_x19_load_guard_17': _framework_x19_load_guard_17,
    'holder_array_init_guard': _holder_array_init_guard,
    'param_holder_vcall_guard': _param_holder_vcall_guard,
    'entry_field_lookup_guard': _entry_field_lookup_guard,
    'entry_field_lookup_guard_2': _entry_field_lookup_guard_2,
    'entry_config_fill_guard': _entry_config_fill_guard,
    'param_delegate_invoke_guard': _param_delegate_invoke_guard,
    'entry_ready_flag_guard': _entry_ready_flag_guard,
    'query_object_vtable_guard': _query_object_vtable_guard,
    'query_object_vcall_guard': _query_object_vcall_guard,
    # The framework step's debug-logging tail (see the _tail_guard comment above): 20 entry
    # guards answering the resource family's neutral 0 for an off-map key/singleton x0, plus
    # 3 in-step slot-double-deref load guards answering 0 for an off-map x8.
    'log_tail_resource_getter_guard':  _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf941a6d3,
                                                   'resource-node getter keyed on the raw word 1'),
    'log_tail_node_publish_guard':     _tail_guard(_STP30X, 0xa9bd7bfd, 0x3c, 0xf901e695,
                                                   'node publisher storing through its this-pointer'),
    'log_tail_flag_accessor_guard':    _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf947fed3,
                                                   'flag accessor on the never-built singleton'),
    'log_tail_flag_accessor_guard_2':  _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf94006d3,
                                                   'flag accessor 2 on the never-built singleton'),
    'log_tail_flag_accessor_guard_3':  _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf9400ed3,
                                                   'flag accessor 3 on the never-built singleton'),
    'log_tail_value_getter_guard':     _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf942c6b3,
                                                   'param-value getter keyed on the raw word 1'),
    'log_tail_value_publish_guard':    _tail_guard('{ uint64_t ea = c->x[0] + 0x20ull; ST64(ea, c->x[1]); }',
                                                   0xf9001001, 4, 0xd65f03c0,
                                                   'param-value publisher storing through the null singleton',
                                                   cond='c->x[0]'),
    'log_tail_tag_getter_guard':       _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf942e6d3,
                                                   'tag getter keyed on the raw word 1'),
    'log_tail_name_getter_guard':      _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf9429ed3,
                                                   'name getter keyed on the raw word 1'),
    'log_tail_name_format_guard':      _tail_guard('sp_ = (uint64_t)(sp_ - 0x40ull);',
                                                   0xd10103ff, 0x60, 0xf9002aa0,
                                                   'name formatter storing through the never-built singleton'),
    'log_tail_flag_node_getter_guard': _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf9432eb3,
                                                   'flag-node getter keyed on the raw word 1'),
    'log_tail_flag_format_guard':      _tail_guard('sp_ = (uint64_t)(sp_ - 0x50ull);',
                                                   0xd10143ff, 0x20, 0xf9413108,
                                                   'flag formatter derefing the never-built singleton'),
    'log_tail_state_getter_guard':     _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf947beb3,
                                                   'state getter keyed on the raw word 1'),
    'log_tail_state_format_guard':     _tail_guard('sp_ = (uint64_t)(sp_ - 0x90ull);',
                                                   0xd10243ff, 0x20, 0x52802b15,
                                                   'state formatter on the never-built singleton'),
    'log_tail_pool_getter_guard':      _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf945b2d3,
                                                   'pool getter keyed on the raw word 1'),
    'log_tail_pool_clear_guard':       _tail_guard('{ uint64_t ea = x0 + 0x28ull; ST32(ea, 0u); }',
                                                   0xb900281f, 4, 0xb900781f,
                                                   'pool clear storing through the null singleton'),
    'log_tail_debug_getter_guard':     _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf94592d3,
                                                   'debug getter keyed on the raw word 1'),
    'log_tail_time_getter_guard':      _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf9426ab3,
                                                   'time getter keyed on the raw word 1'),
    'log_tail_ready_setter_guard':     _tail_guard('sp_ = (uint64_t)(sp_ - 0x20ull);',
                                                   0xd10083ff, 0x14, 0x3900c008,
                                                   'ready setter storing through the never-built singleton'),
    'log_tail_manager_getter_guard':   _tail_guard(_STP30,  0xa9bd7bfd, 0x14, 0xf942bed3,
                                                   'manager getter keyed on the raw word 1'),
    'log_tail_slot_load_guard':        _tail_load_guard(8,  0xaa1503e0,
                                                        'null param singleton slot then ldr x0, [x8] before node publish'),
    'log_tail_slot_load_guard_2':      _tail_load_guard(8,  0xaa1503e0,
                                                        'null param-value singleton slot then ldr x0, [x8] before value publish'),
    'log_tail_slot_load_guard_3':      _tail_load_guard(4,  0xf9400268,
                                                        'null flag singleton slot then ldr x0, [x8] before flag format'),
    # The framework step's node-builder chain (see the _offmap_load_guard comment above):
    # the node-builder thunk f_7000003f10 -- 5 load-skips on its object/"vtable"/factory
    # derefs (the object arrives as the never-built registry's raw string, the factory slot
    # reads a static-link addend) + the 2 dispatch-skips its clone-virtuals answer 0 into
    # (4490 reloads over, 4914 -> 3f48 b.lo 44d4 -> returns the answered 0 node).
    'node_build_obj_load_guard':       _offmap_load_guard(0xf9400268, 'c->x[19]', 'x8', 'c->x[19] + 0x0ull', 'LD64',
                                                          'builder object word: off-map name word answers 0 vtable'),
    'node_build_vtable_load_guard':    _offmap_load_guard(0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
                                                          'builder clone-vtable slot off the ASCII word'),
    'node_build_factory_load_guard':   _offmap_load_guard(0xf940010d, 'x8', 'c->x[13]', 'x8 + 0x0ull', 'LD64',
                                                          'builder factory slot [0x7001d69430] addend then ldr x13, [x8]'),
    'node_build_obj_load_guard_2':     _offmap_load_guard(0xf9400268, 'c->x[19]', 'x8', 'c->x[19] + 0x0ull', 'LD64',
                                                          'builder 4354-block object word answers 0 vtable'),
    'node_build_vtable_load_guard_2':  _offmap_load_guard(0xf9404108, 'x8', 'x8', 'x8 + 0x80ull', 'LD64',
                                                          'builder 4354-block vtable slot off the ASCII word (run77)'),
    'node_build_factory_load_guard_2': _offmap_load_guard(0xf9400100, 'x8', 'c->x[0]', 'x8 + 0x0ull', 'LD64',
                                                          'builder factory slot addend then ldr x0, [x8] for the lock thunk'),
    'node_build_vtable_blr_guard':     _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000004490ull; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10;'
        ' c->x[12] = x12; c->x[21] = x21; c->sp = sp_; rt_dispatch(c); x8 = c->x[8]; x9 = c->x[9];'
        ' x10 = c->x[10]; x12 = c->x[12];',
        'builder clone-virtual on the answered 0 vtable: 4490 reloads x1 and 449c takes x21 = x0'
        ' = 0 -> 40ac cbz x21 -> 4338 returns the 0 node'),
    'node_build_vtable_blr_guard_2':   _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x700000490cull; c->x[8] = x8; c->x[9] = x9; c->x[21] = x21;'
        ' c->sp = sp_; rt_dispatch(c); x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10]; x12 = c->x[12];',
        'builder vtable-slot-miss virtual on the answered 0: 4914 x22 = x0 = 0 -> 3f48 b.lo'
        ' 44d4 -> returns the 0 node'),
    # The two alloc/lock thunks f_7000ea3c44 / f_7000ea3c88: their manager slot
    # [0x7001d6af80] reads a static addend, so the head/key loads, the pop load and the
    # push store skip; the thunks return 0 / leave the list untouched, which the builder's
    # 4470 cbnz and the registrar's guarded loads both handle.
    'lockmgr_head_load_guard':         _offmap_load_guard(0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
                                                          'lock thunk manager slot [0x7001d6af80] addend then ldr x8, [x8]'),
    'lockmgr_key_load_guard':          _offmap_load_guard(0xb9408900, 'x8', 'x0', 'x8 + 0x88ull', 'LD32',
                                                          'lock thunk key load on the answered-0 manager'),
    'lockmgr_pop_load_guard':          _offmap_load_guard(0xf9400100, 'x8', 'x0', 'x8 + 0x0ull', 'LD64',
                                                          'lock thunk list pop answering the empty list 0'),
    'pushmgr_head_load_guard':         _offmap_load_guard(0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
                                                          'push thunk manager slot addend then ldr x8, [x8]'),
    'pushmgr_key_load_guard':          _offmap_load_guard(0xb9408900, 'x8', 'x0', 'x8 + 0x88ull', 'LD32',
                                                          'push thunk key load on the answered-0 manager'),
    'pushmgr_slot_load_guard':         _offmap_load_guard(0xf9405808, 'x0', 'x8', 'x0 + 0xb0ull', 'LD64',
                                                          'push thunk old-head load answering the empty list 0'),
    'pushmgr_slot_store_guard':        _offmap_store_guard(0xf9005813, 'x0', 'x0 + 0xb0ull', 'ST64', 'x19',
                                                          'push thunk list-link store through the answered-0 head'),
    # The step's own probe pair on the builder's answered 0 node: the virtual answer is
    # dead (eea0 reloads x0 from x20), so the pair skips answering 0 into the log tail.
    'step_node_load_guard':            _offmap_load_guard(0xf94002a8, 'x21', 'x8', 'x21 + 0x0ull', 'LD64',
                                                          'step node word on the builder answered 0 node'),
    'step_node_vtable_guard':          _offmap_load_guard(0xf9401508, 'x8', 'x8', 'x8 + 0x28ull', 'LD64',
                                                          'step node vtable slot 0x28 on the answered 0 word'),
    'step_node_vcall_guard':           _offmap_blr_guard(
        'c->pc = x8; x30 = 0x700127eea0ull; c->x[0] = x0; c->x[8] = x8; c->x[30] = x30;'
        ' rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x30 = c->x[30];',
        'step node virtual probe on the answered 0 slot: eea0 reloads x0 from x20, the answer'
        ' is dead', answer='x0 = 0ull'),
    # The node registrar f_700127efe0 on the answered 0 node (its cbz x0 skips to the
    # w19 = 1 tail): its factory/log/gadget/alloc/registry slot double-derefs skip to 0 and
    # its four flag stores to null-slot addends skip, and the tail's cmp x19, #1 branch to
    # the epilogue means f124 only runs in a built chain anyway.
    'node_init_slot_load_guard':       _offmap_load_guard(0xf94002c0, 'c->x[22]', 'x0', 'c->x[22] + 0x0ull', 'LD64',
                                                          'registrar factory slot [0x7001d69430] addend then ldr x0, [x22]'),
    'node_init_log_load_guard':        _offmap_load_guard(0xf9400115, 'x8', 'c->x[21]', 'x8 + 0x0ull', 'LD64',
                                                          'registrar log slot [0x7001d76990] addend then ldr x21, [x8]'),
    'node_init_gadget_load_guard':     _offmap_load_guard(0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
                                                          'registrar gadget slot [0x7001d76c90] addend then ldr x8, [x8]'),
    'node_init_alloc_load_guard':      _offmap_load_guard(0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
                                                          'registrar alloc manager slot addend then ldr x8, [x8]'),
    'node_init_alloc_load_guard_2':    _offmap_load_guard(0xf9404108, 'x8', 'x8', 'x8 + 0x80ull', 'LD64',
                                                          'registrar alloc chain ldr x8, [x8, #0x80] on the answered 0'),
    'node_init_alloc_load_guard_3':    _offmap_load_guard(0xb940d108, 'x8', 'x8', 'x8 + 0xd0ull', 'LD32',
                                                          'registrar alloc flag word on the answered 0'),
    'node_init_registry_load_guard':   _offmap_load_guard(0xf9400100, 'x8', 'x0', 'x8 + 0x0ull', 'LD64',
                                                          'registrar registry slot [0x7001d66dd0] addend then ldr x0, [x8]'),
    'node_init_flag_store_guard':      _offmap_store_guard(0xb900011f, 'x8', 'x8 + 0x0ull', 'ST32', '0u',
                                                          'registrar flag store through the slot addend 0x1e93910'),
    'node_init_flag_store_guard_2':    _offmap_store_guard(0xb9000137, 'x9', 'x9 + 0x0ull', 'ST32', '(uint32_t)c->x[23]',
                                                          'registrar flag store 2 through the slot addend'),
    'node_init_flag_store_guard_3':    _offmap_store_guard(0xb9000158, 'x10', 'x10 + 0x0ull', 'ST32', '(uint32_t)c->x[24]',
                                                          'registrar flag store 3 through the slot addend'),
    'node_init_flag_store_guard_4':    _offmap_store_guard(0xb9000109, 'x8', 'x8 + 0x0ull', 'ST32', '(uint32_t)x9',
                                                          'registrar flag store 4 through the slot addend'),
    'node_init_slot_load_guard_2':     _offmap_load_guard(0xf94002c0, 'c->x[22]', 'x0', 'c->x[22] + 0x0ull', 'LD64',
                                                          'registrar tail factory slot addend then ldr x0, [x22] before push'),
    # The 256-entry list-clear f_700127f150: its singleton [0x7001d66458] reads a static
    # addend and the manager-buffer slot [0x7001e44f00+0xf00] is still null before the
    # step's own alloc, so both loop bodies skip their vtable pair, virtuals (answered 0
    # feeds only guarded code), head/name loads, the name scan, the count load and the
    # strbuf terminator store; a built singleton/allocated buffer re-executes byte-identical.
    'list_clear_buf_load_guard':       _offmap_load_guard(0xf9427754, 'x26', 'c->x[20]', 'x26 + 0x4e8ull', 'LD64',
                                                          'clear loop entry field on the not-yet-allocated manager buffer'),
    'list_clear_vtable_load_guard':    _offmap_load_guard(0xf9400268, 'x19', 'x8', 'x19 + 0x0ull', 'LD64',
                                                          'clear loop singleton [0x7001d66458] addend then ldr x8, [x19]'),
    'list_clear_vtable_load_guard_2':  _offmap_load_guard(0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
                                                          'clear loop vtable slot 0x18 on the answered 0 word'),
    'list_clear_vcall_guard':          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x700127f1a0ull; c->x[8] = x8; c->x[19] = x19; c->x[22] = x22;'
        ' c->x[25] = x25; c->x[26] = x26; c->sp = sp_; rt_dispatch(c); x8 = c->x[8];',
        'clear loop virtual 1 on the answered 0 vtable: the answer is dead (f1a0 reloads)'),
    'list_clear_head_load_guard':      _offmap_load_guard(0xf9400675, 'x19', 'c->x[21]', 'x19 + 0x8ull', 'LD64',
                                                          'clear loop name head on the addend singleton'),
    'list_clear_vtable_load_guard_3':  _offmap_load_guard(0xf9400268, 'x19', 'x8', 'x19 + 0x0ull', 'LD64',
                                                          'clear loop 2nd-body singleton then ldr x8, [x19]'),
    'list_clear_vtable_load_guard_4':  _offmap_load_guard(0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
                                                          'clear loop 2nd-body vtable slot 0x18 on the answered 0'),
    'list_clear_vcall_guard_2':        _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x700127f1c0ull; c->x[8] = x8; c->x[26] = x26;'
        ' rt_dispatch(c); x8 = c->x[8];',
        'clear loop virtual 2 on the answered 0 vtable: the answer is dead (f1c0 reloads)'),
    'list_clear_head_load_guard_2':    _offmap_load_guard(0xf9400669, 'x19', 'c->x[9]', 'x19 + 0x8ull', 'LD64',
                                                          'clear loop 2nd-body name head on the addend singleton'),
    'list_clear_name_load_guard':      _offmap_load_guard(0x3868692a, 'c->x[9]', 'c->x[10]', 'c->x[9] + x8', 'LD8',
                                                          'clear loop name scan on the answered-0 head answers end-of-name'),
    'list_clear_count_load_guard':     _offmap_load_guard(0xb9401349, 'x26', 'c->x[9]', 'x26 + 0x10ull', 'LD32',
                                                          'clear loop count on the not-yet-allocated manager buffer'),
    'list_clear_name_store_guard':     _offmap_store_guard(0x383aca9f, 'c->x[20]',
                                                           'c->x[20] + (uint64_t)(int64_t)(int32_t)x26',
                                                           'ST8', '0u',
                                                          'clear loop terminator store through the answered-0 entry field'),
    # The step's node constructor f_700000690c (run79's fault family; see the ctrl_* group
    # comment in game_sites.py OPTIONAL_GROUPS): the caller passes the builder's answered-0
    # node and the lock thunk answers 0 again through the #41 manager-slot guards, so the
    # constructor's null-arg else-init and the paths it feeds deref and store through literal
    # bases / guest VAs 0x8..0x88. Every guarded else re-runs the original instruction
    # verbatim, and on a real Switch (built registry, relocated slots) those bases are all
    # on-map, so the guards are pass-through there; the dead-on-Switch else paths are exactly
    # the ones whose literal-base stores would fault on a real Switch too.
    'ctrl_arg_load_guard':             _offmap_load_guard(0xf9400109, 'x8', 'x9', 'x8 + 0x0ull', 'LD64',
                                                          'constructor first word of the answered-0 caller object (6944)'),
    'ctrl_vtable_load_guard':          _offmap_load_guard(0xf9401929, 'x9', 'x9', 'x9 + 0x30ull', 'LD64',
                                                          'constructor vtable+0x30 slot on the answered-0 first word (694c)'),
    'ctrl_list_head_store_guard':      _offmap_store_guard(0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
                                                          'chain-head 0x7001d04bc0 store through the sp+0x30 spill holding raw 8 (6b14)'),
    'ctrl_node_flag_store_guard':      _offmap_store_guard(0xb9003a7f, 'c->x[19]', 'c->x[19] + 0x38ull', 'ST32', '0u',
                                                          'node count init on the answered-0 manager slot, x19 = 0 (6b30)'),
    'ctrl_node_link_stp_guard':        _offmap_stp_guard(0xa902a669, 'c->x[19]', 'c->x[19] + 0x28ull', 'x9',
                                                         'node list-link self-pointer pair init on x19 = 0 (6b34)'),
    'ctrl_node_vptr_store_guard':      _offmap_store_guard(0xf9000268, 'c->x[19]', 'c->x[19] + 0x0ull', 'ST64', 'x8',
                                                          'node vtable 0x7001d04d60 store on x19 = 0 (6b3c)'),
    'ctrl_node_push_call_guard':       _always_call(
        'c->x[19]',
        'c->x[30] = 0x7000006b44ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10;'
        ' c->x[12] = x12; c->sp = sp_; f_700000151c(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9];'
        ' x10 = c->x[10]; x12 = c->x[12];',
        'registrar push f_700000151c would write through x0 = x19+0x40 = 0x40; 6b44 recomputes'
        ' x0, so the answer is dead (6b40)'),
    'ctrl_node_tail_store_guard':      _offmap_store_guard(0xf900427f, 'c->x[19]', 'c->x[19] + 0x80ull', 'ST64', '0ull',
                                                          'node tail link clear on x19 = 0 (6b4c)'),
    'ctrl_hle_mutex_call_guard':       _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0ab0(Cpu *c); c->x[30] = 0x7000006b54ull; c->x[0] = x0;'
        ' f_70015a0ab0(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10];'
        ' x12 = c->x[12];',
        'osMutexInit would write through x0 = x19+0x88 = 0x88; the constructor returns x19'
        ' (6b58-6b6c), so the answer is dead (6b50); the patched bl bypasses the generator'
        ' target scan, so the cross-chunk declaration rides in the else block'),
    'ctrl_ctor_resp_store_guard':      _offmap_store_guard(0xf9000100, 'x8', 'x8 + 0x0ull', 'ST64', 'x0',
                                                          'lock-thunk 0 answer through the [x29+0x18] frame slot holding literal 0x10 (6ba4)'),
    'ctrl_init_link_store_guard':      _offmap_store_guard(0xf900012a, 'x9', 'x9 + 0x0ull', 'ST64', 'x10',
                                                          'else-init list link through literal 8, the run79 fault insn str x10, [x9] (6bf4)'),
    'ctrl_init_zero_store_guard':      _offmap_store_guard(0xf900013f, 'x9', 'x9 + 0x0ull', 'ST64', '0ull',
                                                          'else-init null store through literal 0x10 (6c04)'),
    'ctrl_init_zero_store_guard_2':    _offmap_store_guard(0xf900011f, 'x8', 'x8 + 0x0ull', 'ST64', '0ull',
                                                          'else-init null store through literal 0x20 (6c08)'),
    'ctrl_init_zero_store_guard_3':    _offmap_store_guard(0xf900011f, 'x8', 'x8 + 0x0ull', 'ST64', '0ull',
                                                          'else-init null store through literal 0x18 (6c10)'),
    'ctrl_probe_vcall_guard':          _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x7000006c68ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9;'
        ' c->x[10] = x10; c->sp = sp_; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9];'
        ' x10 = c->x[10]; x12 = c->x[12];',
        'constructor probe virtual on the answered-0 vtable slot or an unrelocated addend:'
        ' 6c68-6c70 reload x0 from the frame slot and 6aac ignores the answer (6c64)',
        cond='x9', w=0xd63f0120),
    'ctrl_ctor_vf_vcall_guard':        _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000006dd8ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9;'
        ' c->x[10] = x10; c->x[12] = x12; c->sp = sp_; rt_dispatch(c); x0 = c->x[0];'
        ' x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10]; x12 = c->x[12];',
        'push-region vtable virtual on the double-deref of the answered-0 object, reachable'
        ' once the thunk answers a real object: 6dd8 reloads x0 from the frame (6dd4)'),
    # The registry-node singleton constructor f_7000008168 and its step caller f_7000003304
    # (run80's fault family -- game_sites.py OPTIONAL_GROUPS' rn_* group carries the run80
    # forensics): the answered-0 singleton flows through the ctor key block (run80's fault insn
    # str xzr, [x25, #8]! at 8348), the empty-count path and the join tail, so every load/store
    # below rides c->x[21] = 0 or a literal base it leaves behind (the pre-index write-back hands
    # 8 to the guarded 8d7c store); the alloc node's copy/lock block then rides literal 0x38 and
    # answered-0 mutex handles into the import thunks, and the caller's three post-call vtable-
    # pair probes dispatch on answered-0 or unrelocated-addend slots (the #35/#39 form). Every
    # guarded else re-runs the original instruction verbatim and on a real Switch (built
    # registry, relocated slots) those bases are all on-map, so the guards pass through there.
    # The entry calls whose args ride frames or on-map slots (f_70015a09e0/09d0/fef0 and the
    # alloc wrapper) stay unguarded -- proven null-safe through runtime-resolved import slots in
    # run80 -- and the string-compare loop after this chain is the predicted family #44.
    'rn_08348':                        _offmap_pre_store_guard(
        0xf8008f3f, 'c->x[25]', '0x8ull',
        'run80 fault insn, pre-index lock-owner clear on the answered-0 node; the skip still'
        ' performs the base write-back, leaving the literal 8 that feeds the guarded 8d7c store'
        ' (8348)'),
    'rn_0834c':                        _offmap_stp_guard(
        0xa9017ebf, 'c->x[21]', 'c->x[21] + 16', '0ull',
        'key-block null list-link pair on the answered-0 singleton (834c)'),
    'rn_08354':                        _offmap_store_guard(
        0xf90002a8, 'c->x[21]', 'c->x[21] + 0x0ull', 'ST64', 'x8',
        'key-block vtable store through the answered-0 singleton (8354)'),
    'rn_084f0':                        _offmap_store_guard(
        0xf90042bf, 'c->x[21]', 'c->x[21] + 0x80ull', 'ST64', '0ull',
        'join-tail back-link clear on the answered-0 singleton (84f0)'),
    'rn_084f4':                        _offmap_store_guard(
        0xf90002a8, 'c->x[21]', 'c->x[21] + 0x0ull', 'ST64', 'x8',
        'join-tail vtable 0x7001d04b00 store on the answered-0 singleton (84f4)'),
    'rn_0850c':                        _offmap_pair_store_guard(
        0xa902aaa8, 'c->x[21]', 'c->x[21] + 40', 'x8', 'x10',
        'join-tail string-pair store through the answered-0 singleton (850c)'),
    'rn_0851c':                        _offmap_store_guard(
        0xf90012a9, 'c->x[21]', 'c->x[21] + 0x20ull', 'ST64', 'x9',
        'join-tail slot+0x10 pointer on the answered-0 singleton (851c)'),
    'rn_08524':                        _offmap_load_guard(
        0xf9402c08, 'x0', 'x8', 'x0 + 0x58ull', 'LD64',
        'lock-object word on the frame-slot value that answers null off-map on this path (8524)'),
    'rn_08528':                        _offmap_store_guard(
        0xf90066a9, 'c->x[21]', 'c->x[21] + 0xc8ull', 'ST64', 'x9',
        'join-tail capacity 0x7fffffff on the answered-0 singleton (8528)'),
    'rn_08530':                        _offmap_store_guard(
        0xb900c2a9, 'c->x[21]', 'c->x[21] + 0xc0ull', 'ST32', '(uint32_t)x9',
        'join-tail flag 1 on the answered-0 singleton (8530)'),
    'rn_08534':                        _offmap_stp_guard(
        0xa9097ebf, 'c->x[21]', 'c->x[21] + 144', '0ull',
        'join-tail null pair 0x90 on the answered-0 singleton (8534)'),
    'rn_08538':                        _offmap_pair_store_guard(
        0x291a26aa, 'c->x[21]', 'c->x[21] + 208', '(uint32_t)x10', '(uint32_t)x9',
        'join-tail count pair 0xd0, 32-bit STP width, on the answered-0 singleton (8538)',
        st='ST32', gap=4),
    'rn_0853c':                        _offmap_store_guard(
        0xb9008aa8, 'c->x[21]', 'c->x[21] + 0x88ull', 'ST32', '(uint32_t)x8',
        'join-tail bucket shift on the answered-0 singleton (853c)'),
    'rn_08540':                        _offmap_stp_guard(
        0xa90a7ebf, 'c->x[21]', 'c->x[21] + 160', '0ull',
        'join-tail null pair 0xa0 on the answered-0 singleton (8540)'),
    'rn_08544':                        _offmap_stp_guard(
        0xa90b7ebf, 'c->x[21]', 'c->x[21] + 176', '0ull',
        'join-tail null pair 0xb0 on the answered-0 singleton (8544)'),
    'rn_08550':                        _offmap_pair_store_guard(
        0xa90e7ea0, 'c->x[21]', 'c->x[21] + 224', 'x0', '0ull',
        'join-tail bucket-head link pair through the answered-0 singleton (8550)'),
    'rn_08554':                        _offmap_store_guard(
        0xf9007abf, 'c->x[21]', 'c->x[21] + 0xf0ull', 'ST64', '0ull',
        'join-tail tail clear on the answered-0 singleton (8554)'),
    'rn_08558':                        _offmap_store_guard(
        0xb900daa8, 'c->x[21]', 'c->x[21] + 0xd8ull', 'ST32', '(uint32_t)x8',
        'join-tail shift count on the answered-0 singleton (8558)'),
    'rn_08560':                        _offmap_store_guard(
        0xb900faa0, 'c->x[21]', 'c->x[21] + 0xf8ull', 'ST32', '(uint32_t)x0',
        'f_70015a09d0 thunk answer on the answered-0 singleton (8560)'),
    'rn_08568':                        _offmap_store_guard(
        0xf90052b5, 'c->x[21]', 'c->x[21] + 0xa0ull', 'ST64', 'c->x[21]',
        'join-tail self-link on the answered-0 singleton (8568)'),
    'rn_08570':                        _offmap_load_guard(
        0xf9400100, 'x8', 'x0', 'x8 + 0x0ull', 'LD64',
        'registry-head load on the unrelocated static slot [0x7001d69430]; the null answer'
        ' takes the alloc path (8570)'),
    'rn_086f4':                        _offmap_store_guard(
        0xf90042b4, 'c->x[21]', 'c->x[21] + 0x80ull', 'ST64', 'c->x[20]',
        'node-copy back-link through the answered-0 singleton, src = real alloc node (86f4)'),
    'rn_086fc':                        _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0910(Cpu *c); c->x[30] = 0x7000008700ull; c->x[0] = x0;'
        ' c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->x[23] = x23;'
        ' f_70015a0910(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10];'
        ' x11 = c->x[11];',
        'node-copy memcpy would store 0x20 bytes at dst = x21 + 0x38 = literal 0x38; the answer'
        ' is dead, 8700 recomputes x0 (the patched bl bypasses the generator target scan, so the'
        ' cross-chunk declaration rides in the else block) (86fc)'),
    'rn_08710':                        _offmap_store_guard(
        0xf9007aa8, 'c->x[21]', 'c->x[21] + 0xf0ull', 'ST64', 'x8',
        'mutex-init answer store through the answered-0 singleton (8710)'),
    'rn_08718':                        _offmap_store_guard(
        0xb9008aa8, 'c->x[21]', 'c->x[21] + 0x88ull', 'ST32', '(uint32_t)x8',
        'mutex wait-count store on the answered-0 singleton (8718)'),
    'rn_0871c':                        _offmap_load_guard(
        0xb940dab4, 'c->x[21]', 'c->x[20]', 'c->x[21] + 0xd8ull', 'LD32',
        'wait-count reload on the answered-0 singleton (871c)'),
    'rn_08720':                        _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0a80(Cpu *c); c->x[30] = 0x7000008724ull; c->x[8] = x8;'
        ' f_70015a0a80(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10];'
        ' x11 = c->x[11];',
        'the mutex thunk f_70015a0a80 rides the f_70015a09e0 return, null on this path; 8724'
        ' recomputes x0 (8720)'),
    'rn_08724':                        _offmap_load_guard(
        0xf94072a0, 'c->x[21]', 'x0', 'c->x[21] + 0xe0ull', 'LD64',
        'mutex address load on the answered-0 singleton (8724)'),
    'rn_08730':                        _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0a90(Cpu *c); c->x[30] = 0x7000008734ull; c->x[0] = x0;'
        ' f_70015a0a90(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10];'
        ' x11 = c->x[11];',
        'the wait thunk f_70015a0a90 rides the guarded 8724 answer; its result dies into the'
        ' vtable stores, which re-materialize x8 (8730)'),
    'rn_0873c':                        _offmap_store_guard(
        0xf90002a8, 'c->x[21]', 'c->x[21] + 0x0ull', 'ST64', 'x8',
        'second vtable 0x7001d04be0 store on the answered-0 singleton (873c)'),
    'rn_08748':                        _offmap_store_guard(
        0xf9001aa8, 'c->x[21]', 'c->x[21] + 0x30ull', 'ST64', 'x8',
        'name-link slot store on the answered-0 singleton (8748)'),
    'rn_08750':                        _offmap_load_guard(
        0xb9408900, 'x8', 'x0', 'x8 + 0x88ull', 'LD32',
        'caller-object count on the sp+0x38 slot holding the answered-0 arg (8750)'),
    'rn_08754':                        _offmap_store_guard(
        0xf9004115, 'x8', 'x8 + 0x80ull', 'ST64', 'c->x[21]',
        'caller-object back-link through the same literal-0 base (8754)'),
    'rn_08758':                        _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0a60(Cpu *c); c->x[30] = 0x700000875cull; c->x[0] = x0;'
        ' c->x[8] = x8; f_70015a0a60(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9];'
        ' x10 = c->x[10]; x11 = c->x[11];',
        'the mutex thunk f_70015a0a60 rides the guarded 8750 answer; 8778 recomputes x0 from'
        ' the static slot (8758)'),
    'rn_08778':                        _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0a60(Cpu *c); c->x[30] = 0x700000877cull; c->x[0] = x0;'
        ' c->x[8] = x8; f_70015a0a60(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9];'
        ' x10 = c->x[10]; x11 = c->x[11];',
        'the second f_70015a0a60 rides the never-initialized slot [0x7001e348b0] word, off-map'
        ' here; the epilogue returns x21 = 0 and ignores the answer (8778)'),
    'rn_08d7c':                        _offmap_store_guard(
        0xf900033f, 'c->x[25]', 'c->x[25] + 0x0ull', 'ST64', '0ull',
        'lock-owner clear through the literal 8 written back by 8348 -- run80 fault path'
        ' second half (8d7c)'),
    # The caller side: the answered-0 / addend vtable-pair probe chains after the ctor, the
    # null list-entry from 36d4, and the f_7000003f10 builder's answered-0 result. The three
    # blr skips answer c->x[0] = 0 into code that recomputes x0 or already holds literal 0 in
    # the local (the guards make it so on this path), and their dispatch_lookup backstop lets
    # an unrelocated addend slot skip too.
    'rn_0339c':                        _offmap_load_guard(
        0xf9400288, 'x20', 'x8', 'x20 + 0x0ull', 'LD64',
        'step-object vtable load feeding the NE-path probe chain (339c)'),
    'rn_033a8':                        _offmap_load_guard(
        0xf9401508, 'x8', 'x8', 'x8 + 0x28ull', 'LD64',
        'method slot on the guarded answer or unrelocated addend (33a8)'),
    'rn_036cc':                        _offmap_blr_guard(
        'c->pc = x8; x30 = 0x70000036d0ull; c->x[0] = x0; c->x[8] = x8;'
        ' c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x13 = c->x[13];'
        ' x30 = c->x[30];',
        'NE-path virtual probe on the answered-0 / addend vtable pair; 33bc recomputes x0 from'
        ' x19, so the answer is dead (36cc)'),
    'rn_033d4':                        _offmap_load_guard(
        0xf9400268, 'x19', 'x8', 'x19 + 0x0ull', 'LD64',
        'node vtable on x19 = 0, the null list-entry from 36d4 (33d4)'),
    'rn_033dc':                        _offmap_load_guard(
        0xf9404108, 'x8', 'x8', 'x8 + 0x80ull', 'LD64',
        'method slot on the guarded answer (33dc)'),
    'rn_036e4':                        _offmap_blr_guard(
        'c->pc = x8; x30 = 0x70000036e8ull; c->x[0] = x0; c->x[8] = x8; c->x[19] = x19;'
        ' c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x13 = c->x[13];'
        ' x30 = c->x[30];',
        'NE-path virtual probe on the answered-0 vtable pair; local x0 is already the literal 0'
        ' spilled from x19, so x20 = x0 at 36e8 carries the skip answer into 3450 (36e4)'),
    'rn_0347c':                        _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'builder-result vtable on the answered-0 f_7000003f10 return (347c)'),
    'rn_03484':                        _offmap_load_guard(
        0xf9404108, 'x8', 'x8', 'x8 + 0x80ull', 'LD64',
        'builder-result method slot on the guarded answer (3484)'),
    'rn_03728':                        _offmap_blr_guard(
        'c->pc = x8; x30 = 0x700000372cull; c->x[0] = x0; c->x[8] = x8; c->x[19] = x19;'
        ' c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x13 = c->x[13];'
        ' x30 = c->x[30];',
        'NE-path virtual probe after the builder answered 0; local x0 = literal 0 carries into'
        ' the 34f4 continuation, predicted family #44 (3728)'),
    # The manager-singleton ctor twins and their step caller side (run81, family #44):
    # every site guards one of the two byte-identical twins f_7000005308/f_7000004d9c or
    # the step caller f_7000003304's probe chains around their calls; see game_sites.py
    # mc_* for the full-CFG forensics. The twins' base is the lock thunk f_7000ea3c44's
    # answered-0 singleton, so their vtable chain, init stores and virtual tail probe all
    # hang off literal 0 exactly like run80's node singleton did.
    'mc_05340':                         _offmap_load_guard(
        0xf9400109, 'x8', 'x9', 'x8 + 0x0ull', 'LD64',
        'manager vtable load through the answered-0 lock thunk base -- run81 fault (5340)'),
    'mc_05348':                         _offmap_load_guard(
        0xf9401929, 'x9', 'x9', 'x9 + 0x30ull', 'LD64',
        'second hop of the answered-0 manager vtable chain (5348)'),
    'mc_054b4':                         _offmap_stp_guard(
        0xa9017e7f, 'c->x[19]', 'c->x[19] + 16', '0ull',
        'link-slot zero pair stores on the answered-0 manager (54b4)'),
    'mc_054b8':                         _offmap_pair_store_guard(
        0xa9000268, 'c->x[19]', 'c->x[19] + 0', 'x8', 'x0',
        'vtable and arg pair stores on the answered-0 manager (54b8)'),
    'mc_05504':                         _offmap_store_guard(
        0xf9000268, 'c->x[19]', 'c->x[19] + 0x0ull', 'ST64', 'x8',
        'second vtable store on the answered-0 manager (5504)'),
    'mc_05514':                         _always_call(
        'c->x[19]',
        'extern void f_7000005874(Cpu *c); c->x[30] = 0x7000005518ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[12] = x12; c->sp = sp_; f_7000005874(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10]; x12 = c->x[12];',
        'sub-ctor f_7000005874 skipped on the off-map answered-0 manager; its dead answer lands in the equally guarded 5554 back-link store (5514)'),
    'mc_05554':                         _offmap_store_guard(
        0xf9000660, 'c->x[19]', 'c->x[19] + 0x8ull', 'ST64', 'x0',
        'back-link store through the guarded lock thunk call (5554)'),
    'mc_055c0':                         _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x70000055c4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->sp = sp_; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10]; x12 = c->x[12];',
        'ctor-tail virtual probe on the answered-0 vtable chain; its answer becomes the loop state x19 = 0, which re-runs the guarded init tail byte-identically (55c0)', cond='x9', w=0xd63f0120),
    'mc_04dd4':                         _offmap_load_guard(
        0xf9400109, 'x8', 'x9', 'x8 + 0x0ull', 'LD64',
        'twin manager vtable load through the answered-0 lock thunk base (4dd4)'),
    'mc_04ddc':                         _offmap_load_guard(
        0xf9401929, 'x9', 'x9', 'x9 + 0x30ull', 'LD64',
        'twin second hop of the answered-0 manager vtable chain (4ddc)'),
    'mc_04f48':                         _offmap_stp_guard(
        0xa9017e7f, 'c->x[19]', 'c->x[19] + 16', '0ull',
        'twin link-slot zero pair stores on the answered-0 manager (4f48)'),
    'mc_04f4c':                         _offmap_pair_store_guard(
        0xa9000268, 'c->x[19]', 'c->x[19] + 0', 'x8', 'x0',
        'twin vtable and arg pair stores on the answered-0 manager (4f4c)'),
    'mc_04f98':                         _offmap_store_guard(
        0xf9000268, 'c->x[19]', 'c->x[19] + 0x0ull', 'ST64', 'x8',
        'twin second vtable store on the answered-0 manager (4f98)'),
    'mc_04fa8':                         _always_call(
        'c->x[19]',
        'extern void f_7000005d80(Cpu *c); c->x[30] = 0x7000004facull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[12] = x12; c->sp = sp_; f_7000005d80(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10]; x12 = c->x[12];',
        'twin sub-ctor f_7000005d80 skipped on the off-map answered-0 manager; its dead answer lands in the equally guarded 4fec back-link store (4fa8)'),
    'mc_04fec':                         _offmap_store_guard(
        0xf9000660, 'c->x[19]', 'c->x[19] + 0x8ull', 'ST64', 'x0',
        'twin back-link store through the guarded lock thunk call (4fec)'),
    'mc_05058':                         _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x700000505cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->sp = sp_; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10]; x12 = c->x[12];',
        'twin ctor-tail virtual probe on the answered-0 vtable chain; its answer becomes the loop state x19 = 0, which re-runs the guarded init tail byte-identically (5058)', cond='x9', w=0xd63f0120),
    'mc_03548':                         _offmap_load_guard(
        0xf9400288, 'x20', 'x8', 'x20 + 0x0ull', 'LD64',
        'step-object vtable load feeding the post-ctor NE probe (3548)'),
    'mc_03550':                         _offmap_load_guard(
        0xf9401508, 'x8', 'x8', 'x8 + 0x28ull', 'LD64',
        'method slot on the guarded answer or unrelocated addend (3550)'),
    'mc_03578':                         _offmap_load_guard(
        0xf9400268, 'x19', 'x8', 'x19 + 0x0ull', 'LD64',
        'second base vtable load off the answered-0 manager (3578)'),
    'mc_0357c':                         _offmap_load_guard(
        0xf9404108, 'x8', 'x8', 'x8 + 0x80ull', 'LD64',
        'method slot [vt+0x80] on the guarded answer (357c)'),
    'mc_03764':                         _offmap_blr_guard(
        'c->pc = x8; x30 = 0x7000003768ull; c->x[0] = x0; c->x[8] = x8; c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x13 = c->x[13]; x30 = c->x[30];',
        'NE-path virtual probe on the answered-0 / addend vtable pair; L_3560 re-checks x25, so the answer is dead (3764)'),
    'mc_03774':                         _offmap_blr_guard(
        'c->pc = x8; x30 = 0x7000003778ull; c->x[0] = x0; c->x[8] = x8; c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x13 = c->x[13]; x30 = c->x[30];',
        'second NE-path virtual probe with w1 = 8; x20 = the zero answer feeds the equally guarded f_7000003f10 builder chain (3774)'),
    'mc_03640':                         _offmap_load_guard(
        0xf9400288, 'x20', 'x8', 'x20 + 0x0ull', 'LD64',
        'twin step-object vtable load feeding the post-ctor NE probe (3640)'),
    'mc_03648':                         _offmap_load_guard(
        0xf9401508, 'x8', 'x8', 'x8 + 0x28ull', 'LD64',
        'twin method slot on the guarded answer or unrelocated addend (3648)'),
    'mc_03670':                         _offmap_load_guard(
        0xf9400268, 'x19', 'x8', 'x19 + 0x0ull', 'LD64',
        'twin second base vtable load off the answered-0 manager (3670)'),
    'mc_03678':                         _offmap_load_guard(
        0xf9401508, 'x8', 'x8', 'x8 + 0x28ull', 'LD64',
        'twin method slot [vt+0x28] on the guarded answer (3678)'),
    'mc_037ac':                         _offmap_blr_guard(
        'c->pc = x8; x30 = 0x70000037b0ull; c->x[0] = x0; c->x[8] = x8; c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x13 = c->x[13]; x30 = c->x[30];',
        'NE-path virtual probe on the twin answered-0 / addend vtable pair; L_3658 re-checks x23, so the answer is dead (37ac)'),
    'mc_037b4':                         _offmap_blr_guard(
        'c->pc = x8; x30 = 0x70000037b8ull; c->x[0] = x0; c->x[8] = x8; c->x[30] = x30; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x13 = c->x[13]; x30 = c->x[30];',
        'second twin NE-path virtual probe answered 0 into the sp-based step epilogue (37b4)'),
    'bt_0a784':                          _offmap_load_guard(
        0xf9400109, 'x8', 'x9', 'x8 + 0x0ull', 'LD64',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a784)'),
    'bt_0a78c':                          _offmap_load_guard(
        0xf9401929, 'x9', 'x9', 'x9 + 0x30ull', 'LD64',
        'registry entry-chain insurance load via x9 skipped off-map on the answered-0 walk (a78c)'),
    'bt_0a790':                          _offmap_load_guard(
        0xf9447d6b, 'c->x[11]', 'c->x[11]', 'c->x[11] + 0x8f8ull', 'LD64',
        'registry entry-chain insurance load via c->x[11] skipped off-map on the answered-0 walk (a790)'),
    'bt_0a79c':                          _offmap_load_guard(
        0xf9400151, 'x10', 'c->x[17]', 'x10 + 0x0ull', 'LD64',
        'registry entry-chain insurance load via x10 skipped off-map on the answered-0 walk (a79c)'),
    'bt_0a7a0':                          _offmap_load_guard(
        0x7941b109, 'x8', 'x9', 'x8 + 0xd8ull', 'LD16',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a7a0)'),
    'bt_0a7ac':                          _offmap_load_guard(
        0xb9409109, 'x8', 'x9', 'x8 + 0x90ull', 'LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a7ac)'),
    'bt_0a7c0':                          _offmap_load_guard(
        0xf940750c, 'x8', 'c->x[12]', 'x8 + 0xe8ull', 'LD64',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a7c0)'),
    'bt_0a7d0':                          _offmap_load_guard(
        0xb980f509, 'x8', 'x9', 'x8 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a7d0)'),
    'bt_0a7d8':                          _offmap_load_guard(
        0x39437110, 'x8', 'c->x[16]', 'x8 + 0xdcull', 'LD8',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a7d8)'),
    'bt_0a7e8':                          _offmap_load_guard(
        0xf9400d90, 'c->x[12]', 'c->x[16]', 'c->x[12] + 0x18ull', 'LD64',
        'registry entry-chain insurance load via c->x[12] skipped off-map on the answered-0 walk (a7e8)'),
    'bt_0a7f8':                          _offmap_load_guard(
        0x79402597, 'c->x[12]', 'c->x[23]', 'c->x[12] + 0x12ull', 'LD16',
        'registry entry-chain insurance load via c->x[12] skipped off-map on the answered-0 walk (a7f8)'),
    'bt_0a7fc':                          _offmap_store_guard(
        0xf9000d89, 'c->x[12]', 'c->x[12] + 0x18ull', 'ST64', 'x9',
        'registry entry-chain insurance store via c->x[12] skipped off-map on the answered-0 walk (a7fc)'),
    'bt_0a800':                          _offmap_load_guard(
        0xb980f511, 'x8', 'c->x[17]', 'x8 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a800)'),
    'bt_0a808':                          _offmap_load_guard(
        0xf940052e, 'x9', 'c->x[14]', 'x9 + 0x8ull', 'LD64',
        'registry entry-chain insurance load via x9 skipped off-map on the answered-0 walk (a808)'),
    'bt_0a818':                          _offmap_load_guard(
        0xf9400131, 'x9', 'c->x[17]', 'x9 + 0x0ull', 'LD64',
        'registry entry-chain insurance load via x9 skipped off-map on the answered-0 walk (a818)'),
    'bt_0a820':                          _offmap_store_guard(
        0xf900062e, 'c->x[17]', 'c->x[17] + 0x8ull', 'ST64', 'c->x[14]',
        'registry entry-chain insurance store via c->x[17] skipped off-map on the answered-0 walk (a820)'),
    'bt_0a824':                          _offmap_load_guard(
        0xf940052e, 'x9', 'c->x[14]', 'x9 + 0x8ull', 'LD64',
        'registry entry-chain insurance load via x9 skipped off-map on the answered-0 walk (a824)'),
    'bt_0a82c':                          _offmap_load_guard(
        0xf9400131, 'x9', 'c->x[17]', 'x9 + 0x0ull', 'LD64',
        'registry entry-chain insurance load via x9 skipped off-map on the answered-0 walk (a82c)'),
    'bt_0a830':                          _offmap_store_guard(
        0xf90001d1, 'c->x[14]', 'c->x[14] + 0x0ull', 'ST64', 'c->x[17]',
        'registry entry-chain insurance store via c->x[14] skipped off-map on the answered-0 walk (a830)'),
    'bt_0a834':                          _offmap_pair_store_guard(
        0xa9007d3f, 'x9', 'x9 + 0', '0ull', '0ull',
        'registry entry-chain insurance pair store via x9 skipped off-map on the answered-0 walk (a834)'),
    'bt_0a83c':                          _offmap_load_guard(
        0xb940f10e, 'x8', 'c->x[14]', 'x8 + 0xf0ull', 'LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a83c)'),
    'bt_0a840':                          _offmap_load_guard(
        0xb9409111, 'x8', 'c->x[17]', 'x8 + 0x90ull', 'LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a840)'),
    'bt_0a84c':                          _offmap_store_guard(
        0xb900f10e, 'x8', 'x8 + 0xf0ull', 'ST32', '(uint32_t)c->x[14]',
        'registry entry-chain insurance store via x8 skipped off-map on the answered-0 walk (a84c)'),
    'bt_0a850':                          _offmap_load_guard(
        0xb9810d0e, 'x8', 'c->x[14]', 'x8 + 0x10cull', '(uint64_t)(int64_t)(int32_t)LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a850)'),
    'bt_0a85c':                          _offmap_load_guard(
        0xf940012e, 'x9', 'c->x[14]', 'x9 + 0x0ull', 'LD64',
        'registry entry-chain insurance load via x9 skipped off-map on the answered-0 walk (a85c)'),
    'bt_0a860':                          _offmap_store_guard(
        0xf9000121, 'x9', 'x9 + 0x0ull', 'ST64', 'c->x[1]',
        'registry entry-chain insurance store via x9 skipped off-map on the answered-0 walk (a860)'),
    'bt_0a864':                          _offmap_pair_store_guard(
        0xa900242e, 'c->x[1]', 'c->x[1] + 0', 'c->x[14]', 'x9',
        'registry entry-chain insurance pair store via c->x[1] skipped off-map on the answered-0 walk (a864)'),
    'bt_0a86c':                          _offmap_store_guard(
        0xf90005c1, 'c->x[14]', 'c->x[14] + 0x8ull', 'ST64', 'c->x[1]',
        'registry entry-chain insurance store via c->x[14] skipped off-map on the answered-0 walk (a86c)'),
    'bt_0a870':                          _offmap_load_guard(
        0xb9410909, 'x8', 'x9', 'x8 + 0x108ull', 'LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a870)'),
    'bt_0a878':                          _offmap_store_guard(
        0xb9010909, 'x8', 'x8 + 0x108ull', 'ST32', '(uint32_t)x9',
        'registry entry-chain insurance store via x8 skipped off-map on the answered-0 walk (a878)'),
    'bt_0a890':                          _offmap_store_guard(
        0xb90871bf, 'c->x[13]', 'c->x[13] + 0x870ull', 'ST32', '0u',
        'registry entry-chain insurance store via c->x[13] skipped off-map on the answered-0 walk (a890)'),
    'bt_0a898':                          _offmap_store_guard(
        0xf90435bf, 'c->x[13]', 'c->x[13] + 0x868ull', 'ST64', '0ull',
        'registry entry-chain insurance store via c->x[13] skipped off-map on the answered-0 walk (a898)'),
    'bt_0a8a0':                          _offmap_store_guard(
        0xf90431bf, 'c->x[13]', 'c->x[13] + 0x860ull', 'ST64', '0ull',
        'registry entry-chain insurance store via c->x[13] skipped off-map on the answered-0 walk (a8a0)'),
    'bt_0a8a4':                          _offmap_store_guard(
        0xf9043dae, 'c->x[13]', 'c->x[13] + 0x878ull', 'ST64', 'c->x[14]',
        'registry entry-chain insurance store via c->x[13] skipped off-map on the answered-0 walk (a8a4)'),
    'bt_0a8a8':                          _offmap_store_guard(
        0x7910e1b0, 'c->x[13]', 'c->x[13] + 0x870ull', 'ST16', '(uint32_t)c->x[16]',
        'registry entry-chain insurance store via c->x[13] skipped off-map on the answered-0 walk (a8a8)'),
    'bt_0a8ac':                          _offmap_load_guard(
        0xb980f50d, 'x8', 'c->x[13]', 'x8 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a8ac)'),
    'bt_0a8b8':                          _offmap_load_guard(
        0xf94001ed, 'c->x[15]', 'c->x[13]', 'c->x[15] + 0x0ull', 'LD64',
        'registry entry-chain insurance load via c->x[15] skipped off-map on the answered-0 walk (a8b8)'),
    'bt_0a8bc':                          _offmap_store_guard(
        0xf90001e9, 'c->x[15]', 'c->x[15] + 0x0ull', 'ST64', 'x9',
        'registry entry-chain insurance store via c->x[15] skipped off-map on the answered-0 walk (a8bc)'),
    'bt_0a8c0':                          _offmap_pair_store_guard(
        0xa9003d2d, 'x9', 'x9 + 0', 'c->x[13]', 'c->x[15]',
        'registry entry-chain insurance pair store via x9 skipped off-map on the answered-0 walk (a8c0)'),
    'bt_0a8c8':                          _offmap_store_guard(
        0xf90005a9, 'c->x[13]', 'c->x[13] + 0x8ull', 'ST64', 'x9',
        'registry entry-chain insurance store via c->x[13] skipped off-map on the answered-0 walk (a8c8)'),
    'bt_0a8cc':                          _offmap_load_guard(
        0xb940f109, 'x8', 'x9', 'x8 + 0xf0ull', 'LD32',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a8cc)'),
    'bt_0a8d4':                          _offmap_store_guard(
        0xb900f109, 'x8', 'x8 + 0xf0ull', 'ST32', '(uint32_t)x9',
        'registry entry-chain insurance store via x8 skipped off-map on the answered-0 walk (a8d4)'),
    'bt_0a8d8':                          _offmap_load_guard(
        0x7941b508, 'x8', 'x8', 'x8 + 0xdaull', 'LD16',
        'registry entry-chain insurance load via x8 skipped off-map on the answered-0 walk (a8d8)'),
    'bt_0a8dc':                          _offmap_store_guard(
        0x79002188, 'c->x[12]', 'c->x[12] + 0x10ull', 'ST16', '(uint32_t)x8',
        'registry entry-chain insurance store via c->x[12] skipped off-map on the answered-0 walk (a8dc)'),
    'bt_0a8e0':                          _offmap_load_guard(
        0x79402588, 'c->x[12]', 'x8', 'c->x[12] + 0x12ull', 'LD16',
        'registry entry-chain insurance load via c->x[12] skipped off-map on the answered-0 walk (a8e0)'),
    'bt_0a8f8':                          _offmap_store_guard(
        0xf9035660, 'x19', 'x19 + 0x6a8ull', 'ST64', 'x0',
        'registry entry-chain insurance store via x19 skipped off-map on the answered-0 walk (a8f8)'),
    'bt_0a8fc':                          _offmap_store_guard(
        0xf9035a7f, 'x19', 'x19 + 0x6b0ull', 'ST64', '0ull',
        'registry entry-chain insurance store via x19 skipped off-map on the answered-0 walk (a8fc)'),
    'bt_0a904':                          _offmap_store_guard(
        0xf9035e7f, 'x19', 'x19 + 0x6b8ull', 'ST64', '0ull',
        'registry entry-chain insurance store via x19 skipped off-map on the answered-0 walk (a904)'),
    'bt_0a908':                          _offmap_store_guard(
        0xf9035268, 'x19', 'x19 + 0x6a0ull', 'ST64', 'x8',
        'registry entry-chain insurance store via x19 skipped off-map on the answered-0 walk (a908)'),
    'bt_0a914':                          _offmap_load_guard(
        0x7941b009, 'x0', 'x9', 'x0 + 0xd8ull', 'LD16',
        'registry entry-chain insurance load via x0 skipped off-map on the answered-0 walk (a914)'),
    'bt_0a924':                          _offmap_pre_load_guard(
        0xf8478d69, 'c->x[11]', '120', 'x9',
        'registry entry-chain insurance pre-index load via c->x[11] skipped off-map on the answered-0 walk (a924)'),
    'bt_0a928':                          _offmap_load_guard(
        0xb980156a, 'c->x[11]', 'x10', 'c->x[11] + 0x14ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'registry entry-chain insurance load via c->x[11] skipped off-map on the answered-0 walk (a928)'),
    'bt_0a930':                          _offmap_store_guard(
        0xf900016a, 'c->x[11]', 'c->x[11] + 0x0ull', 'ST64', 'x10',
        'registry entry-chain insurance store via c->x[11] skipped off-map on the answered-0 walk (a930)'),
    'bt_0a934':                          _offmap_pair_store_guard(
        0xa9002d49, 'x10', 'x10 + 0', 'x9', 'c->x[11]',
        'registry entry-chain insurance pair store via x10 skipped off-map on the answered-0 walk (a934)'),
    'bt_0a93c':                          _offmap_store_guard(
        0xf900052a, 'x9', 'x9 + 0x8ull', 'ST64', 'x10',
        'registry entry-chain insurance store via x9 skipped off-map on the answered-0 walk (a93c)'),
    'bt_0a940':                          _offmap_load_guard(
        0xb9408809, 'x0', 'x9', 'x0 + 0x88ull', 'LD32',
        'registry entry-chain insurance load via x0 skipped off-map on the answered-0 walk (a940)'),
    'bt_0a948':                          _offmap_store_guard(
        0xb9008809, 'x0', 'x0 + 0x88ull', 'ST32', '(uint32_t)x9',
        'registry entry-chain insurance store via x0 skipped off-map on the answered-0 walk (a948)'),
    'bt_0a958':                          _offmap_store_guard(
        0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
        'registry init-tail store via x8 skipped off-map on the answered-0 walk (a958)'),
    'bt_0a964':                          _offmap_store_guard(
        0xf9064128, 'x9', 'x9 + 0xc80ull', 'ST64', 'x8',
        'registry init-tail store via x9 skipped off-map on the answered-0 walk (a964)'),
    'bt_0a970':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0330(Cpu *c); c->x[30] = 0x700000a974ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[19] = x19; c->sp = sp_; f_70015a0330(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10];',
        'array-zeroing thunk f_70015a0330 skipped on the raw x0 = x19 + 0x28 of the answered-0 singleton; its dead spill lands in the equally guarded tail (a970)'),
    'bt_0a978':                          _offmap_store_guard(
        0x3906427f, 'x19', 'x19 + 0x190ull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a978)'),
    'bt_0a980':                          _offmap_pre_store_guard(
        0x38014d1f, 'x8', '20',
        'registry init-tail pre-index store via x8 skipped off-map on the answered-0 walk (a980)', 'ST8', '0u'),
    'bt_0a984':                          _offmap_load_guard(
        0xf9438d29, 'x9', 'x9', 'x9 + 0x718ull', 'LD64',
        'registry init-tail load via x9 skipped off-map on the answered-0 walk (a984)'),
    'bt_0a98c':                          _offmap_store_guard(
        0x390aae7f, 'x19', 'x19 + 0x2abull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a98c)'),
    'bt_0a990':                          _offmap_store_guard(
        0xb901aa75, 'x19', 'x19 + 0x1a8ull', 'ST32', '(uint32_t)c->x[21]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a990)'),
    'bt_0a9a8':                          _offmap_store_guard(
        0xf9000269, 'x19', 'x19 + 0x0ull', 'ST64', 'x9',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a9a8)'),
    'bt_0a9b4':                          _offmap_load_guard(
        0xf947d929, 'x9', 'x9', 'x9 + 0xfb0ull', 'LD64',
        'registry init-tail load via x9 skipped off-map on the answered-0 walk (a9b4)'),
    'bt_0a9b8':                          _offmap_pair_store_guard(
        0xa9187e6a, 'x19', 'x19 + 384', 'x10', '0ull',
        'registry init-tail pair store via x19 skipped off-map on the answered-0 walk (a9b8)'),
    'bt_0a9bc':                          _offmap_store_guard(
        0xb902ca75, 'x19', 'x19 + 0x2c8ull', 'ST32', '(uint32_t)c->x[21]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a9bc)'),
    'bt_0a9c0':                          _offmap_store_guard(
        0x390f2e7f, 'x19', 'x19 + 0x3cbull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a9c0)'),
    'bt_0a9c8':                          _offmap_store_guard(
        0x390f427f, 'x19', 'x19 + 0x3d0ull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a9c8)'),
    'bt_0a9d0':                          _offmap_store_guard(
        0xf9015e76, 'x19', 'x19 + 0x2b8ull', 'ST64', 'c->x[22]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a9d0)'),
    'bt_0a9d4':                          _offmap_pair_store_guard(
        0xa919a276, 'x19', 'x19 + 408', 'c->x[22]', 'x8',
        'registry init-tail pair store via x19 skipped off-map on the answered-0 walk (a9d4)'),
    'bt_0a9dc':                          _offmap_store_guard(
        0xf9015a68, 'x19', 'x19 + 0x2b0ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a9dc)'),
    'bt_0a9e4':                          _offmap_pre_store_guard(
        0x38014d1f, 'x8', '20',
        'registry init-tail pre-index store via x8 skipped off-map on the answered-0 walk (a9e4)', 'ST8', '0u'),
    'bt_0a9e8':                          _offmap_store_guard(
        0xf9016268, 'x19', 'x19 + 0x2c0ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a9e8)'),
    'bt_0a9f0':                          _offmap_store_guard(
        0xf9000117, 'x8', 'x8 + 0x0ull', 'ST64', 'c->x[23]',
        'registry init-tail store via x8 skipped off-map on the answered-0 walk (a9f0)'),
    'bt_0a9f8':                          _offmap_store_guard(
        0x7907ba7f, 'x19', 'x19 + 0x3dcull', 'ST16', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (a9f8)'),
    'bt_0a9fc':                          _offmap_pre_store_guard(
        0x38014d1f, 'x8', '20',
        'registry init-tail pre-index store via x8 skipped off-map on the answered-0 walk (a9fc)', 'ST8', '0u'),
    'bt_0aa00':                          _offmap_store_guard(
        0xf901f668, 'x19', 'x19 + 0x3e8ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa00)'),
    'bt_0aa08':                          _offmap_store_guard(
        0xb903f268, 'x19', 'x19 + 0x3f0ull', 'ST32', '(uint32_t)x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa08)'),
    'bt_0aa14':                          _offmap_store_guard(
        0x39104e7f, 'x19', 'x19 + 0x413ull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa14)'),
    'bt_0aa1c':                          _offmap_store_guard(
        0x7908327f, 'x19', 'x19 + 0x418ull', 'ST16', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa1c)'),
    'bt_0aa20':                          _offmap_store_guard(
        0xb9043275, 'x19', 'x19 + 0x430ull', 'ST32', '(uint32_t)c->x[21]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa20)'),
    'bt_0aa24':                          _offmap_pre_store_guard(
        0x38014d3f, 'x9', '20',
        'registry init-tail pre-index store via x9 skipped off-map on the answered-0 walk (aa24)', 'ST8', '0u'),
    'bt_0aa28':                          _offmap_store_guard(
        0xf9021669, 'x19', 'x19 + 0x428ull', 'ST64', 'x9',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa28)'),
    'bt_0aa2c':                          _offmap_store_guard(
        0x3914ce7f, 'x19', 'x19 + 0x533ull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa2c)'),
    'bt_0aa30':                          _offmap_store_guard(
        0xf9021276, 'x19', 'x19 + 0x420ull', 'ST64', 'c->x[22]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa30)'),
    'bt_0aa34':                          _offmap_store_guard(
        0xb9054a75, 'x19', 'x19 + 0x548ull', 'ST32', '(uint32_t)c->x[21]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa34)'),
    'bt_0aa38':                          _offmap_store_guard(
        0x39192e7f, 'x19', 'x19 + 0x64bull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa38)'),
    'bt_0aa3c':                          _offmap_store_guard(
        0xf9029e76, 'x19', 'x19 + 0x538ull', 'ST64', 'c->x[22]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa3c)'),
    'bt_0aa40':                          _offmap_store_guard(
        0x3919ce7f, 'x19', 'x19 + 0x673ull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa40)'),
    'bt_0aa44':                          _offmap_store_guard(
        0xf901f268, 'x19', 'x19 + 0x3e0ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa44)'),
    'bt_0aa4c':                          _offmap_pre_store_guard(
        0x38014d1f, 'x8', '20',
        'registry init-tail pre-index store via x8 skipped off-map on the answered-0 walk (aa4c)', 'ST8', '0u'),
    'bt_0aa50':                          _offmap_store_guard(
        0xf902a268, 'x19', 'x19 + 0x540ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa50)'),
    'bt_0aa5c':                          _offmap_store_guard(
        0x3900511f, 'x8', 'x8 + 0x14ull', 'ST8', '0u',
        'registry init-tail store via x8 skipped off-map on the answered-0 walk (aa5c)'),
    'bt_0aa64':                          _offmap_store_guard(
        0xf9032e69, 'x19', 'x19 + 0x658ull', 'ST64', 'x9',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa64)'),
    'bt_0aa6c':                          _offmap_store_guard(
        0xb9066269, 'x19', 'x19 + 0x660ull', 'ST32', '(uint32_t)x9',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa6c)'),
    'bt_0aa70':                          _offmap_load_guard(
        0xf9422908, 'x8', 'x8', 'x8 + 0x450ull', 'LD64',
        'registry init-tail load via x8 skipped off-map on the answered-0 walk (aa70)'),
    'bt_0aa78':                          _offmap_store_guard(
        0xf9032a68, 'x19', 'x19 + 0x650ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa78)'),
    'bt_0aa84':                          _offmap_store_guard(
        0x790cf27f, 'x19', 'x19 + 0x678ull', 'ST16', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa84)'),
    'bt_0aa88':                          _offmap_store_guard(
        0x390f467f, 'x19', 'x19 + 0x3d1ull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa88)'),
    'bt_0aa8c':                          _offmap_store_guard(
        0xf9000113, 'x8', 'x8 + 0x0ull', 'ST64', 'x19',
        'registry init-tail store via x8 skipped off-map on the answered-0 walk (aa8c)'),
    'bt_0aa94':                          _offmap_store_guard(
        0x390f6668, 'x19', 'x19 + 0x3d9ull', 'ST8', '(uint32_t)x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aa94)'),
    'bt_0aa98':                          _always_call(
        'x0',
        'extern void f_70000008e0(Cpu *c); c->x[30] = 0x700000aa9cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; f_70000008e0(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10];',
        'mutex-style thunk f_70000008e0 skipped on the raw x0 of the answered-0 walk; the dead answer lands nowhere, the guarded 0xaa9c spill continues (aa98)'),
    'bt_0aaa4':                          _offmap_store_guard(
        0xb906c27f, 'x19', 'x19 + 0x6c0ull', 'ST32', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aaa4)'),
    'bt_0aaa8':                          _offmap_store_guard(
        0xf9000268, 'x19', 'x19 + 0x0ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aaa8)'),
    'bt_0aab4':                          _offmap_store_guard(
        0xf9034268, 'x19', 'x19 + 0x680ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aab4)'),
    'bt_0aac0':                          _offmap_pre_store_guard(
        0x38014d1f, 'x8', '20',
        'registry init-tail pre-index store via x8 skipped off-map on the answered-0 walk (aac0)', 'ST8', '0u'),
    'bt_0aac4':                          _offmap_store_guard(
        0xf9036a68, 'x19', 'x19 + 0x6d0ull', 'ST64', 'x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aac4)'),
    'bt_0aacc':                          _offmap_store_guard(
        0xf900013f, 'x9', 'x9 + 0x0ull', 'ST64', '0ull',
        'registry init-tail store via x9 skipped off-map on the answered-0 walk (aacc)'),
    'bt_0aad0':                          _offmap_store_guard(
        0xf900011f, 'x8', 'x8 + 0x0ull', 'ST64', '0ull',
        'registry init-tail store via x8 skipped off-map on the answered-0 walk (aad0)'),
    'bt_0aad4':                          _offmap_store_guard(
        0xf800511f, 'x8', 'x8 + 5', 'ST64', '0ull',
        'registry init-tail store via x8 skipped off-map on the answered-0 walk (aad4)'),
    'bt_0aadc':                          _offmap_store_guard(
        0xf800713f, 'x9', 'x9 + 7', 'ST64', '0ull',
        'registry init-tail store via x9 skipped off-map on the answered-0 walk (aadc)'),
    'bt_0aae4':                          _offmap_store_guard(
        0x79101a68, 'x19', 'x19 + 0x80cull', 'ST16', '(uint32_t)x8',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aae4)'),
    'bt_0aaec':                          _offmap_store_guard(
        0x391b127f, 'x19', 'x19 + 0x6c4ull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aaec)'),
    'bt_0aaf0':                          _offmap_store_guard(
        0xb906da75, 'x19', 'x19 + 0x6d8ull', 'ST32', '(uint32_t)c->x[21]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aaf0)'),
    'bt_0aaf4':                          _offmap_store_guard(
        0x391f6e7f, 'x19', 'x19 + 0x7dbull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aaf4)'),
    'bt_0aaf8':                          _offmap_store_guard(
        0xf9036676, 'x19', 'x19 + 0x6c8ull', 'ST64', 'c->x[22]',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aaf8)'),
    'bt_0aafc':                          _offmap_store_guard(
        0x391f827f, 'x19', 'x19 + 0x7e0ull', 'ST8', '0u',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (aafc)'),
    'bt_0ab00':                          _offmap_store_guard(
        0xf9000157, 'x10', 'x10 + 0x0ull', 'ST64', 'c->x[23]',
        'registry init-tail store via x10 skipped off-map on the answered-0 walk (ab00)'),
    'bt_0ab04':                          _offmap_store_guard(
        0xf9041e7f, 'x19', 'x19 + 0x838ull', 'ST64', '0ull',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (ab04)'),
    'bt_0ab08':                          _offmap_store_guard(
        0xf800711f, 'x8', 'x8 + 7', 'ST64', '0ull',
        'registry init-tail store via x8 skipped off-map on the answered-0 walk (ab08)'),
    'bt_0ab0c':                          _offmap_store_guard(
        0xf900011f, 'x8', 'x8 + 0x0ull', 'ST64', '0ull',
        'registry init-tail store via x8 skipped off-map on the answered-0 walk (ab0c)'),
    'bt_0ab10':                          _offmap_store_guard(
        0xf800f13f, 'x9', 'x9 + 15', 'ST64', '0ull',
        'registry init-tail store via x9 skipped off-map on the answered-0 walk (ab10)'),
    'bt_0ab14':                          _offmap_store_guard(
        0xf904167f, 'x19', 'x19 + 0x828ull', 'ST64', '0ull',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (ab14)'),
    'bt_0ab18':                          _offmap_store_guard(
        0xf904127f, 'x19', 'x19 + 0x820ull', 'ST64', '0ull',
        'registry init-tail store via x19 skipped off-map on the answered-0 walk (ab18)'),
    'bt_0ab1c':                          _offmap_store_guard(
        0xf9064693, 'c->x[20]', 'c->x[20] + 0xc88ull', 'ST64', 'x19',
        'registry init-tail store via c->x[20] skipped off-map on the answered-0 walk (ab1c)'),
    'bt_0ab60':                          _offmap_load_guard(
        0xf94002c0, 'c->x[22]', 'x0', 'c->x[22] + 0x0ull', 'LD64',
        'registry lock-retry load via c->x[22] skipped off-map on the answered-0 walk (ab60)'),
    'bt_0ab70':                          _offmap_store_guard(
        0xf90002e0, 'c->x[23]', 'c->x[23] + 0x0ull', 'ST64', 'x0',
        'registry lock-retry store via c->x[23] skipped off-map on the answered-0 walk (ab70)'),
    'bt_0abb8':                          _offmap_store_guard(
        0xf9000128, 'x9', 'x9 + 0x0ull', 'ST64', 'x8',
        'run82 fault block store via x9 skipped off-map on the answered-0 walk (abb8)'),
    'bt_0abc0':                          _offmap_store_guard(
        0xf90002ff, 'c->x[23]', 'c->x[23] + 0x0ull', 'ST64', '0ull',
        'run82 fault block store via c->x[23] skipped off-map on the answered-0 walk (abc0)'),
    'bt_0abc4':                          _offmap_store_guard(
        0xf900011f, 'x8', 'x8 + 0x0ull', 'ST64', '0ull',
        'run82 fault block store via x8 skipped off-map on the answered-0 walk (abc4)'),
    'bt_0abcc':                          _offmap_store_guard(
        0xf900011f, 'x8', 'x8 + 0x0ull', 'ST64', '0ull',
        'run82 fault block store via x8 skipped off-map on the answered-0 walk (abcc)'),
    'bt_0ac20':                          _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x700000ac24ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[19] = x19; c->sp = sp_; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10];',
        'alloc-chain virtual probe answered 0 through the dispatch_lookup backstop when x9 is a raw addend, the spill-based chain continues (ac20)', cond='x9', w=0xd63f0120),
    'bt_0ad88':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x700000ad8cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[19] = x19; c->sp = sp_; rt_dispatch(c); x0 = c->x[0]; x8 = c->x[8]; x9 = c->x[9]; x10 = c->x[10];',
        'deep virtual probe answered 0 through the dispatch_lookup backstop; the insurance for the dead L_ad4c chain (ad88)'),
    'bu_61570':                          _offmap_load_guard(
        0xf94396f7, 'c->x[23]', 'c->x[23]', 'c->x[23] + 0x728ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1570)'),
    'bu_61574':                          _offmap_load_guard(
        0xb94012e8, 'c->x[23]', 'x8', 'c->x[23] + 0x10ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1574)'),
    'bu_61578':                          _offmap_load_guard(
        0xb9402ae9, 'c->x[23]', 'x9', 'c->x[23] + 0x28ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1578)'),
    'bu_61584':                          _offmap_load_guard(
        0xf9400ef3, 'c->x[23]', 'c->x[19]', 'c->x[23] + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1584)'),
    'bu_6158c':                          _offmap_load_guard(
        0xf9400268, 'c->x[19]', 'x8', 'c->x[19] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[19] skipped off-map (158c)'),
    'bu_61590':                          _offmap_store_guard(
        0xf9000ee8, 'c->x[23]', 'c->x[23] + 0x18ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (1590)'),
    'bu_61594':                          _offmap_pair_store_guard(
        0xa9007e7f, 'c->x[19]', 'c->x[19] + 0', '0ull', '0ull',
        'caller f_7000c61540 answered-0 walk pair store via c->x[19] skipped off-map (1594)'),
    'bu_6159c':                          _offmap_store_guard(
        0xf9000260, 'c->x[19]', 'c->x[19] + 0x0ull', 'ST64', 'x0',
        'caller f_7000c61540 answered-0 walk store via c->x[19] skipped off-map (159c)'),
    'bu_615a4':                          _offmap_load_guard(
        0xf94002e9, 'c->x[23]', 'x9', 'c->x[23] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (15a4)'),
    'bu_615a8':                          _offmap_pre_store_guard(
        0xf8010d1f, 'x8', '16',
        'caller f_7000c61540 answered-0 walk pre-index store via x8 skipped off-map (15a8)'),
    'bu_615ac':                          _offmap_store_guard(
        0xf90002e8, 'c->x[23]', 'c->x[23] + 0x0ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (15ac)'),
    'bu_615b0':                          _offmap_store_guard(
        0xf9000e77, 'c->x[19]', 'c->x[19] + 0x18ull', 'ST64', 'c->x[23]',
        'caller f_7000c61540 answered-0 walk store via c->x[19] skipped off-map (15b0)'),
    'bu_615b4':                          _offmap_store_guard(
        0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (15b4)'),
    'bu_615bc':                          _offmap_store_guard(
        0xf9000528, 'x9', 'x9 + 0x8ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via x9 skipped off-map (15bc)'),
    'bu_615c0':                          _offmap_load_guard(
        0xb94012e8, 'c->x[23]', 'x8', 'c->x[23] + 0x10ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (15c0)'),
    'bu_615c8':                          _offmap_store_guard(
        0xb90012e8, 'c->x[23]', 'c->x[23] + 0x10ull', 'ST32', '(uint32_t)x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (15c8)'),
    'bu_615d8':                          _offmap_pair_store_guard(
        0xa9002260, 'c->x[19]', 'c->x[19] + 0', 'x0', 'x8',
        'caller f_7000c61540 answered-0 walk pair store via c->x[19] skipped off-map (15d8)'),
    'bu_615dc':                          _offmap_load_guard(
        0xb94012e8, 'c->x[23]', 'x8', 'c->x[23] + 0x10ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (15dc)'),
    'bu_615e0':                          _offmap_load_guard(
        0xb9402ae9, 'c->x[23]', 'x9', 'c->x[23] + 0x28ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (15e0)'),
    'bu_615ec':                          _offmap_load_guard(
        0xf9400ef4, 'c->x[23]', 'c->x[20]', 'c->x[23] + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (15ec)'),
    'bu_615f4':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (15f4)'),
    'bu_615f8':                          _offmap_store_guard(
        0xf9000ee8, 'c->x[23]', 'c->x[23] + 0x18ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (15f8)'),
    'bu_615fc':                          _offmap_pair_store_guard(
        0xa9007e9f, 'c->x[20]', 'c->x[20] + 0', '0ull', '0ull',
        'caller f_7000c61540 answered-0 walk pair store via c->x[20] skipped off-map (15fc)'),
    'bu_61604':                          _offmap_store_guard(
        0xf9000280, 'c->x[20]', 'c->x[20] + 0x0ull', 'ST64', 'x0',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1604)'),
    'bu_6160c':                          _offmap_load_guard(
        0xf94002e9, 'c->x[23]', 'x9', 'c->x[23] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (160c)'),
    'bu_61610':                          _offmap_pre_store_guard(
        0xf8010d1f, 'x8', '16',
        'caller f_7000c61540 answered-0 walk pre-index store via x8 skipped off-map (1610)'),
    'bu_61614':                          _offmap_store_guard(
        0xf90002e8, 'c->x[23]', 'c->x[23] + 0x0ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (1614)'),
    'bu_61618':                          _offmap_store_guard(
        0xf9000e97, 'c->x[20]', 'c->x[20] + 0x18ull', 'ST64', 'c->x[23]',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1618)'),
    'bu_6161c':                          _offmap_store_guard(
        0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (161c)'),
    'bu_61624':                          _offmap_store_guard(
        0xf9000528, 'x9', 'x9 + 0x8ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via x9 skipped off-map (1624)'),
    'bu_61628':                          _offmap_load_guard(
        0xb94012e8, 'c->x[23]', 'x8', 'c->x[23] + 0x10ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1628)'),
    'bu_61630':                          _offmap_store_guard(
        0xb90012e8, 'c->x[23]', 'c->x[23] + 0x10ull', 'ST32', '(uint32_t)x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (1630)'),
    'bu_61650':                          _offmap_pair_store_guard(
        0xa9006680, 'c->x[20]', 'c->x[20] + 0', 'x0', 'c->x[25]',
        'caller f_7000c61540 answered-0 walk pair store via c->x[20] skipped off-map (1650)'),
    'bu_61690':                          _offmap_load_guard(
        0xf9438ad6, 'c->x[22]', 'c->x[22]', 'c->x[22] + 0x710ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[22] skipped off-map (1690)'),
    'bu_61698':                          _offmap_store_guard(
        0x790002df, 'c->x[22]', 'c->x[22] + 0x0ull', 'ST16', '0u',
        'caller f_7000c61540 answered-0 walk store via c->x[22] skipped off-map (1698)'),
    'bu_6169c':                          _offmap_store_guard(
        0xf9000edf, 'c->x[22]', 'c->x[22] + 0x18ull', 'ST64', '0ull',
        'caller f_7000c61540 answered-0 walk store via c->x[22] skipped off-map (169c)'),
    'bu_616a0':                          _offmap_pair_store_guard(
        0xa900fedf, 'c->x[22]', 'c->x[22] + 8', '0ull', '0ull',
        'caller f_7000c61540 answered-0 walk pair store via c->x[22] skipped off-map (16a0)'),
    'bu_616a4':                          _offmap_load_guard(
        0xf941335a, 'c->x[26]', 'c->x[26]', 'c->x[26] + 0x260ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[26] skipped off-map (16a4)'),
    'bu_6171c':                          _offmap_load_guard(
        0xf86bd80d, 'x0', 'c->x[13]', 'x0 + ((uint64_t)(int64_t)(int32_t)c->x[11] << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x0 skipped off-map (171c)'),
    'bu_61730':                          _offmap_load_guard(
        0x386e69af, 'c->x[13]', 'c->x[15]', 'c->x[13] + c->x[14]', 'LD8',
        'caller f_7000c61540 answered-0 walk load via c->x[13] skipped off-map (1730)'),
    'bu_61734':                          _offmap_load_guard(
        0x386e6910, 'x8', 'c->x[16]', 'x8 + c->x[14]', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1734)'),
    'bu_6174c':                          _offmap_load_guard(
        0x386e69af, 'c->x[13]', 'c->x[15]', 'c->x[13] + c->x[14]', 'LD8',
        'caller f_7000c61540 answered-0 walk load via c->x[13] skipped off-map (174c)'),
    'bu_61750':                          _offmap_load_guard(
        0x386e6930, 'x9', 'c->x[16]', 'x9 + c->x[14]', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1750)'),
    'bu_617fc':                          _offmap_load_guard(
        0xf9443508, 'x8', 'x8', 'x8 + 0x868ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (17fc)'),
    'bu_61804':                          _offmap_store_guard(
        0xb9000113, 'x8', 'x8 + 0x0ull', 'ST32', '(uint32_t)c->x[19]',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1804)'),
    'bu_61810':                          _offmap_load_guard(
        0xf943e108, 'x8', 'x8', 'x8 + 0x7c0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1810)'),
    'bu_61814':                          _offmap_load_guard(
        0xb9400109, 'x8', 'x9', 'x8 + 0x0ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1814)'),
    'bu_6181c':                          _offmap_load_guard(
        0xf9400508, 'x8', 'x8', 'x8 + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (181c)'),
    'bu_61820':                          _offmap_load_guard(
        0xf9400113, 'x8', 'c->x[19]', 'x8 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1820)'),
    'bu_61858':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1858)'),
    'bu_61864':                          _offmap_load_guard(
        0xf9401508, 'x8', 'x8', 'x8 + 0x28ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1864)'),
    'bu_61868':                          _offmap_load_guard(
        0xf9447929, 'x9', 'x9', 'x9 + 0x8f0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1868)'),
    'bu_61888':                          _offmap_load_guard(
        0xf9445d08, 'x8', 'x8', 'x8 + 0x8b8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1888)'),
    'bu_6188c':                          _offmap_load_guard(
        0xf9445929, 'x9', 'x9', 'x9 + 0x8b0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (188c)'),
    'bu_61898':                          _offmap_store_guard(
        0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1898)'),
    'bu_618a0':                          _offmap_load_guard(
        0xf9446108, 'x8', 'x8', 'x8 + 0x8c0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (18a0)'),
    'bu_618b0':                          _offmap_ldp_load_guard(
        0xa9402109, 'x8', 'x9', 'x8',
        'x8 + 0',
        'caller f_7000c61540 answered-0 walk ldp pair load via x8 skipped off-map (18b0)'),
    'bu_618d4':                          _offmap_lda_guard(
        0x8dffe88, 'c->x[20]', 'x8',
        'caller f_7000c61540 answered-0 walk acquire load via c->x[20] skipped off-map (18d4)'),
    'bu_618e0':                          _offmap_load_guard(
        0xb94dc108, 'x8', 'x8', 'x8 + 0xdc0ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (18e0)'),
    'bu_618e8':                          _offmap_lda_guard(
        0x8dffe88, 'c->x[20]', 'x8',
        'caller f_7000c61540 answered-0 walk acquire load via c->x[20] skipped off-map (18e8)'),
    'bu_618fc':                          _offmap_load_guard(
        0xb94dc508, 'x8', 'x8', 'x8 + 0xdc4ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (18fc)'),
    'bu_6192c':                          _offmap_load_guard(
        0xf9421ab5, 'c->x[21]', 'c->x[21]', 'c->x[21] + 0x430ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (192c)'),
    'bu_6193c':                          _offmap_load_guard(
        0xf94002a0, 'c->x[21]', 'x0', 'c->x[21] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (193c)'),
    'bu_6194c':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (194c)'),
    'bu_61954':                          _offmap_load_guard(
        0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1954)'),
    'bu_61958':                          _offmap_load_guard(
        0xf9447d29, 'x9', 'x9', 'x9 + 0x8f8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1958)'),
    'bu_61964':                          _offmap_load_guard(
        0xf94002ae, 'c->x[21]', 'c->x[14]', 'c->x[21] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (1964)'),
    'bu_61968':                          _offmap_load_guard(
        0x7941b288, 'c->x[20]', 'x8', 'c->x[20] + 0xd8ull', 'LD16',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1968)'),
    'bu_61974':                          _offmap_load_guard(
        0xb9409288, 'c->x[20]', 'x8', 'c->x[20] + 0x90ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1974)'),
    'bu_61988':                          _offmap_load_guard(
        0xf9407688, 'c->x[20]', 'x8', 'c->x[20] + 0xe8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1988)'),
    'bu_61998':                          _offmap_load_guard(
        0xb980f689, 'c->x[20]', 'x9', 'c->x[20] + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1998)'),
    'bu_619a0':                          _offmap_load_guard(
        0x3943728d, 'c->x[20]', 'c->x[13]', 'c->x[20] + 0xdcull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (19a0)'),
    'bu_619b0':                          _offmap_load_guard(
        0xf9400d1c, 'x8', 'c->x[28]', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (19b0)'),
    'bu_619c0':                          _offmap_load_guard(
        0x79402509, 'x8', 'x9', 'x8 + 0x12ull', 'LD16',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (19c0)'),
    'bu_619c4':                          _offmap_store_guard(
        0xf9000d0a, 'x8', 'x8 + 0x18ull', 'ST64', 'x10',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (19c4)'),
    'bu_619c8':                          _offmap_load_guard(
        0xb980f68f, 'c->x[20]', 'c->x[15]', 'c->x[20] + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (19c8)'),
    'bu_619d0':                          _offmap_ldp_load_guard(
        0xa9402d4e, 'x10', 'c->x[14]', 'c->x[11]',
        'x10 + 0',
        'caller f_7000c61540 answered-0 walk ldp pair load via x10 skipped off-map (19d0)'),
    'bu_619e4':                          _offmap_store_guard(
        0xf90005cb, 'c->x[14]', 'c->x[14] + 0x8ull', 'ST64', 'c->x[11]',
        'caller f_7000c61540 answered-0 walk store via c->x[14] skipped off-map (19e4)'),
    'bu_619e8':                          _offmap_load_guard(
        0xf940054b, 'x10', 'c->x[11]', 'x10 + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (19e8)'),
    'bu_619f0':                          _offmap_load_guard(
        0xf940014e, 'x10', 'c->x[14]', 'x10 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (19f0)'),
    'bu_619f4':                          _offmap_store_guard(
        0xf900016e, 'c->x[11]', 'c->x[11] + 0x0ull', 'ST64', 'c->x[14]',
        'caller f_7000c61540 answered-0 walk store via c->x[11] skipped off-map (19f4)'),
    'bu_619f8':                          _offmap_pair_store_guard(
        0xa9007d5f, 'x10', 'x10 + 0', '0ull', '0ull',
        'caller f_7000c61540 answered-0 walk pair store via x10 skipped off-map (19f8)'),
    'bu_61a00':                          _offmap_load_guard(
        0xb940f28a, 'c->x[20]', 'x10', 'c->x[20] + 0xf0ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1a00)'),
    'bu_61a04':                          _offmap_load_guard(
        0xb940928b, 'c->x[20]', 'c->x[11]', 'c->x[20] + 0x90ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1a04)'),
    'bu_61a10':                          _offmap_store_guard(
        0xb900f28a, 'c->x[20]', 'c->x[20] + 0xf0ull', 'ST32', '(uint32_t)x10',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1a10)'),
    'bu_61a14':                          _offmap_load_guard(
        0xb9810e8a, 'c->x[20]', 'x10', 'c->x[20] + 0x10cull', '(uint64_t)(int64_t)(int32_t)LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1a14)'),
    'bu_61a20':                          _offmap_load_guard(
        0xf940000a, 'x0', 'x10', 'x0 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x0 skipped off-map (1a20)'),
    'bu_61a24':                          _offmap_store_guard(
        0xf9000001, 'x0', 'x0 + 0x0ull', 'ST64', 'c->x[1]',
        'caller f_7000c61540 answered-0 walk store via x0 skipped off-map (1a24)'),
    'bu_61a28':                          _offmap_pair_store_guard(
        0xa900002a, 'c->x[1]', 'c->x[1] + 0', 'x10', 'x0',
        'caller f_7000c61540 answered-0 walk pair store via c->x[1] skipped off-map (1a28)'),
    'bu_61a30':                          _offmap_store_guard(
        0xf9000541, 'x10', 'x10 + 0x8ull', 'ST64', 'c->x[1]',
        'caller f_7000c61540 answered-0 walk store via x10 skipped off-map (1a30)'),
    'bu_61a34':                          _offmap_load_guard(
        0xb9410a8a, 'c->x[20]', 'x10', 'c->x[20] + 0x108ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1a34)'),
    'bu_61a3c':                          _offmap_store_guard(
        0xb9010a8a, 'c->x[20]', 'c->x[20] + 0x108ull', 'ST32', '(uint32_t)x10',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1a3c)'),
    'bu_61a54':                          _offmap_store_guard(
        0xf901652a, 'x9', 'x9 + 0x2c8ull', 'ST64', 'x10',
        'caller f_7000c61540 answered-0 walk store via x9 skipped off-map (1a54)'),
    'bu_61a5c':                          _offmap_store_guard(
        0xb902c13f, 'x9', 'x9 + 0x2c0ull', 'ST32', '0u',
        'caller f_7000c61540 answered-0 walk store via x9 skipped off-map (1a5c)'),
    'bu_61a64':                          _offmap_store_guard(
        0xf9015d3f, 'x9', 'x9 + 0x2b8ull', 'ST64', '0ull',
        'caller f_7000c61540 answered-0 walk store via x9 skipped off-map (1a64)'),
    'bu_61a68':                          _offmap_store_guard(
        0xf901593f, 'x9', 'x9 + 0x2b0ull', 'ST64', '0ull',
        'caller f_7000c61540 answered-0 walk store via x9 skipped off-map (1a68)'),
    'bu_61a6c':                          _offmap_store_guard(
        0x7905812a, 'x9', 'x9 + 0x2c0ull', 'ST16', '(uint32_t)x10',
        'caller f_7000c61540 answered-0 walk store via x9 skipped off-map (1a6c)'),
    'bu_61a70':                          _offmap_load_guard(
        0xb980f68a, 'c->x[20]', 'x10', 'c->x[20] + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1a70)'),
    'bu_61a7c':                          _offmap_load_guard(
        0xf940018a, 'c->x[12]', 'x10', 'c->x[12] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[12] skipped off-map (1a7c)'),
    'bu_61a80':                          _offmap_store_guard(
        0xf9000189, 'c->x[12]', 'c->x[12] + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via c->x[12] skipped off-map (1a80)'),
    'bu_61a84':                          _offmap_pair_store_guard(
        0xa900312a, 'x9', 'x9 + 0', 'x10', 'c->x[12]',
        'caller f_7000c61540 answered-0 walk pair store via x9 skipped off-map (1a84)'),
    'bu_61a8c':                          _offmap_store_guard(
        0xf9000549, 'x10', 'x10 + 0x8ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x10 skipped off-map (1a8c)'),
    'bu_61a90':                          _offmap_load_guard(
        0xb940f289, 'c->x[20]', 'x9', 'c->x[20] + 0xf0ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1a90)'),
    'bu_61a98':                          _offmap_store_guard(
        0xb900f289, 'c->x[20]', 'c->x[20] + 0xf0ull', 'ST32', '(uint32_t)x9',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1a98)'),
    'bu_61a9c':                          _offmap_load_guard(
        0x7941b689, 'c->x[20]', 'x9', 'c->x[20] + 0xdaull', 'LD16',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1a9c)'),
    'bu_61aa0':                          _offmap_store_guard(
        0x79002109, 'x8', 'x8 + 0x10ull', 'ST16', '(uint32_t)x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1aa0)'),
    'bu_61aa4':                          _offmap_load_guard(
        0x79402509, 'x8', 'x9', 'x8 + 0x12ull', 'LD16',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1aa4)'),
    'bu_61abc':                          _always_call(
        'x0',
        'extern void f_7000e93868(Cpu *c); c->x[30] = 0x7000c61ac0ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; f_7000e93868(c);',
        'f_7000e93868 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1abc)'),
    'bu_61ac8':                          _offmap_load_guard(
        0xf944c108, 'x8', 'x8', 'x8 + 0x980ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1ac8)'),
    'bu_61acc':                          _offmap_store_guard(
        0xf901129f, 'c->x[20]', 'c->x[20] + 0x220ull', 'ST64', '0ull',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1acc)'),
    'bu_61ad8':                          _offmap_store_guard(
        0xf9000289, 'c->x[20]', 'c->x[20] + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1ad8)'),
    'bu_61adc':                          _offmap_store_guard(
        0xf9010e88, 'c->x[20]', 'c->x[20] + 0x218ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1adc)'),
    'bu_61ae0':                          _always_call(
        'x0',
        'extern void f_7001126c04(Cpu *c); c->x[30] = 0x7000c61ae4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7001126c04(c);',
        'f_7001126c04 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1ae0)'),
    'bu_61ae8':                          _offmap_store_guard(
        0xf9013e9f, 'c->x[20]', 'c->x[20] + 0x278ull', 'ST64', '0ull',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1ae8)'),
    'bu_61aec':                          _offmap_store_guard(
        0xf9013a88, 'c->x[20]', 'c->x[20] + 0x270ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1aec)'),
    'bu_61af4':                          _offmap_store_guard(
        0xb9028280, 'c->x[20]', 'c->x[20] + 0x280ull', 'ST32', '(uint32_t)x0',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1af4)'),
    'bu_61afc':                          _offmap_store_guard(
        0xb9028680, 'c->x[20]', 'c->x[20] + 0x284ull', 'ST32', '(uint32_t)x0',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1afc)'),
    'bu_61b10':                          _offmap_store_guard(
        0x390a229f, 'c->x[20]', 'c->x[20] + 0x288ull', 'ST8', '0u',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1b10)'),
    'bu_61b2c':                          _always_call(
        'x0',
        'extern void f_7000003f10(Cpu *c); c->x[30] = 0x7000c61b30ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000003f10(c);',
        'f_7000003f10 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1b2c)'),
    'bu_61b50':                          _offmap_lda_guard(
        0x8dffd08, 'x8', 'x8',
        'caller f_7000c61540 answered-0 walk acquire load via x8 skipped off-map (1b50)'),
    'bu_61b60':                          _offmap_u128_load_guard(
        0x2d400760, 'c->x[27]', 'c->v[0]', 'c->v[1]', 'c->x[27] + 0',
        'u128 a = LD32(ea), b = LD32(ea + 4); c->v[0] = a; c->v[1] = b;',
        'caller f_7000c61540 answered-0 walk ldp pair load into v-regs via c->x[27] skipped off-map (1b60)'),
    'bu_61b7c':                          _always_call(
        'x0',
        'extern void f_7000e93960(Cpu *c); c->x[30] = 0x7000c61b80ull; c->x[0] = x0; c->x[8] = x8; f_7000e93960(c);',
        'f_7000e93960 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1b7c)'),
    'bu_61b8c':                          _offmap_store_guard(
        0x39085288, 'c->x[20]', 'c->x[20] + 0x214ull', 'ST8', '(uint32_t)x8',
        'caller f_7000c61540 answered-0 walk store via c->x[20] skipped off-map (1b8c)'),
    'bu_61b90':                          _offmap_load_guard(
        0xf94002a8, 'c->x[21]', 'x8', 'c->x[21] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (1b90)'),
    'bu_61b94':                          _offmap_load_guard(
        0xf9401508, 'x8', 'x8', 'x8 + 0x28ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1b94)'),
    'bu_61b98':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c61b9cull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (1b98)'),
    'bu_61b9c':                          _offmap_load_guard(
        0xb94012e8, 'c->x[23]', 'x8', 'c->x[23] + 0x10ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1b9c)'),
    'bu_61ba4':                          _offmap_load_guard(
        0xf94002e9, 'c->x[23]', 'x9', 'c->x[23] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1ba4)'),
    'bu_61bbc':                          _offmap_load_guard(
        0xf9400749, 'c->x[26]', 'x9', 'c->x[26] + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[26] skipped off-map (1bbc)'),
    'bu_61bc8':                          _offmap_load_guard(
        0x3940012a, 'x9', 'x10', 'x9 + 0x0ull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1bc8)'),
    'bu_61bd4':                          _offmap_load_guard(
        0x3940052a, 'x9', 'x10', 'x9 + 0x1ull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1bd4)'),
    'bu_61be0':                          _offmap_load_guard(
        0x3940092a, 'x9', 'x10', 'x9 + 0x2ull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1be0)'),
    'bu_61bec':                          _offmap_load_guard(
        0x39400d2a, 'x9', 'x10', 'x9 + 0x3ull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1bec)'),
    'bu_61bf8':                          _offmap_load_guard(
        0x39401129, 'x9', 'x9', 'x9 + 0x4ull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1bf8)'),
    'bu_61c0c':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x0 skipped off-map (1c0c)'),
    'bu_61c14':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1c14)'),
    'bu_61c18':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c61c1cull; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (1c18)'),
    'bu_61c1c':                          _offmap_load_guard(
        0xf94002a8, 'c->x[21]', 'x8', 'c->x[21] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (1c1c)'),
    'bu_61c24':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1c24)'),
    'bu_61c28':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c61c2cull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (1c28)'),
    'bu_61c2c':                          _offmap_load_guard(
        0xf94006a8, 'c->x[21]', 'x8', 'c->x[21] + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (1c2c)'),
    'bu_61c6c':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x0 skipped off-map (1c6c)'),
    'bu_61c74':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1c74)'),
    'bu_61c78':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c61c7cull; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (1c78)'),
    'bu_61c7c':                          _offmap_load_guard(
        0xf94002a8, 'c->x[21]', 'x8', 'c->x[21] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (1c7c)'),
    'bu_61c84':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1c84)'),
    'bu_61c88':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c61c8cull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (1c88)'),
    'bu_61c8c':                          _offmap_load_guard(
        0xf94006a8, 'c->x[21]', 'x8', 'c->x[21] + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (1c8c)'),
    'bu_61ca8':                          _offmap_load_guard(
        0x386a690c, 'x8', 'c->x[12]', 'x8 + x10', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1ca8)'),
    'bu_61cac':                          _offmap_load_guard(
        0x386a692d, 'x9', 'c->x[13]', 'x9 + x10', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1cac)'),
    'bu_61cdc':                          _offmap_store_guard(
        0xf9000d1c, 'x8', 'x8 + 0x18ull', 'ST64', 'c->x[28]',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1cdc)'),
    'bu_61ce8':                          _always_call(
        'x0',
        'extern void f_7000002140(Cpu *c); c->x[30] = 0x7000c61cecull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000002140(c);',
        'f_7000002140 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1ce8)'),
    'bu_61cf8':                          _offmap_load_guard(
        0xf94002c8, 'c->x[22]', 'x8', 'c->x[22] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[22] skipped off-map (1cf8)'),
    'bu_61d00':                          _offmap_load_guard(
        0xf94006c9, 'c->x[22]', 'x9', 'c->x[22] + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[22] skipped off-map (1d00)'),
    'bu_61d04':                          _offmap_store_guard(
        0xf9000509, 'x8', 'x8 + 0x8ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1d04)'),
    'bu_61d08':                          _offmap_load_guard(
        0xf94006c8, 'c->x[22]', 'x8', 'c->x[22] + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[22] skipped off-map (1d08)'),
    'bu_61d10':                          _offmap_load_guard(
        0xf94002c9, 'c->x[22]', 'x9', 'c->x[22] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[22] skipped off-map (1d10)'),
    'bu_61d14':                          _offmap_store_guard(
        0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1d14)'),
    'bu_61d18':                          _offmap_pair_store_guard(
        0xa9007edf, 'c->x[22]', 'c->x[22] + 0', '0ull', '0ull',
        'caller f_7000c61540 answered-0 walk pair store via c->x[22] skipped off-map (1d18)'),
    'bu_61d1c':                          _offmap_load_guard(
        0xb94012e8, 'c->x[23]', 'x8', 'c->x[23] + 0x10ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1d1c)'),
    'bu_61d24':                          _offmap_store_guard(
        0xb90012e8, 'c->x[23]', 'c->x[23] + 0x10ull', 'ST32', '(uint32_t)x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (1d24)'),
    'bu_61d28':                          _offmap_load_guard(
        0xf9400ee8, 'c->x[23]', 'x8', 'c->x[23] + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1d28)'),
    'bu_61d30':                          _offmap_store_guard(
        0xf9000efa, 'c->x[23]', 'c->x[23] + 0x18ull', 'ST64', 'c->x[26]',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (1d30)'),
    'bu_61d34':                          _offmap_load_guard(
        0xb94012e8, 'c->x[23]', 'x8', 'c->x[23] + 0x10ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1d34)'),
    'bu_61d38':                          _offmap_load_guard(
        0xb9402ae9, 'c->x[23]', 'x9', 'c->x[23] + 0x28ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1d38)'),
    'bu_61d44':                          _offmap_load_guard(
        0xf9400ef5, 'c->x[23]', 'c->x[21]', 'c->x[23] + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1d44)'),
    'bu_61d4c':                          _offmap_load_guard(
        0xf94002a8, 'c->x[21]', 'x8', 'c->x[21] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[21] skipped off-map (1d4c)'),
    'bu_61d50':                          _offmap_store_guard(
        0xf9000ee8, 'c->x[23]', 'c->x[23] + 0x18ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (1d50)'),
    'bu_61d54':                          _offmap_pair_store_guard(
        0xa9007ebf, 'c->x[21]', 'c->x[21] + 0', '0ull', '0ull',
        'caller f_7000c61540 answered-0 walk pair store via c->x[21] skipped off-map (1d54)'),
    'bu_61d5c':                          _offmap_store_guard(
        0xf90002a0, 'c->x[21]', 'c->x[21] + 0x0ull', 'ST64', 'x0',
        'caller f_7000c61540 answered-0 walk store via c->x[21] skipped off-map (1d5c)'),
    'bu_61d64':                          _offmap_load_guard(
        0xf94002e9, 'c->x[23]', 'x9', 'c->x[23] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1d64)'),
    'bu_61d68':                          _offmap_pre_store_guard(
        0xf8010d1f, 'x8', '16',
        'caller f_7000c61540 answered-0 walk pre-index store via x8 skipped off-map (1d68)'),
    'bu_61d6c':                          _offmap_store_guard(
        0xf90002e8, 'c->x[23]', 'c->x[23] + 0x0ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (1d6c)'),
    'bu_61d70':                          _offmap_store_guard(
        0xf9000eb7, 'c->x[21]', 'c->x[21] + 0x18ull', 'ST64', 'c->x[23]',
        'caller f_7000c61540 answered-0 walk store via c->x[21] skipped off-map (1d70)'),
    'bu_61d74':                          _offmap_store_guard(
        0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1d74)'),
    'bu_61d7c':                          _offmap_store_guard(
        0xf9000528, 'x9', 'x9 + 0x8ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via x9 skipped off-map (1d7c)'),
    'bu_61d80':                          _offmap_load_guard(
        0xb94012e8, 'c->x[23]', 'x8', 'c->x[23] + 0x10ull', 'LD32',
        'caller f_7000c61540 answered-0 walk load via c->x[23] skipped off-map (1d80)'),
    'bu_61d88':                          _offmap_store_guard(
        0xb90012e8, 'c->x[23]', 'c->x[23] + 0x10ull', 'ST32', '(uint32_t)x8',
        'caller f_7000c61540 answered-0 walk store via c->x[23] skipped off-map (1d88)'),
    'bu_61d9c':                          _offmap_pair_store_guard(
        0xa90022a0, 'c->x[21]', 'c->x[21] + 0', 'x0', 'x8',
        'caller f_7000c61540 answered-0 walk pair store via c->x[21] skipped off-map (1d9c)'),
    'bu_61df4':                          _offmap_load_guard(
        0xf9433d08, 'x8', 'x8', 'x8 + 0x678ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1df4)'),
    'bu_61e00':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[20] skipped off-map (1e00)'),
    'bu_61e04':                          _offmap_load_guard(
        0xf9401508, 'x8', 'x8', 'x8 + 0x28ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1e04)'),
    'bu_61e08':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c61e0cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (1e08)'),
    'bu_61e10':                          _offmap_load_guard(
        0xf9447108, 'x8', 'x8', 'x8 + 0x8e0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1e10)'),
    'bu_61e14':                          _offmap_load_guard(
        0xf9400100, 'x8', 'x0', 'x8 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1e14)'),
    'bu_61e3c':                          _offmap_load_guard(
        0xf9400755, 'c->x[26]', 'c->x[21]', 'c->x[26] + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[26] skipped off-map (1e3c)'),
    'bu_61e44':                          _offmap_load_guard(
        0xf9400348, 'c->x[26]', 'x8', 'c->x[26] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[26] skipped off-map (1e44)'),
    'bu_61e80':                          _offmap_load_guard(
        0xf941054a, 'x10', 'x10', 'x10 + 0x208ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (1e80)'),
    'bu_61e88':                          _offmap_load_guard(
        0xf9400149, 'x10', 'x9', 'x10 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (1e88)'),
    'bu_61e98':                          _offmap_load_guard(
        0xf9410529, 'x9', 'x9', 'x9 + 0x208ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1e98)'),
    'bu_61e9c':                          _offmap_load_guard(
        0xf9400129, 'x9', 'x9', 'x9 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (1e9c)'),
    'bu_61ed0':                          _always_call(
        'x0',
        'extern void f_70005a37f8(Cpu *c); c->x[30] = 0x7000c61ed4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; f_70005a37f8(c);',
        'f_70005a37f8 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1ed0)'),
    'bu_61ee0':                          _always_call(
        'x0',
        'extern void f_700159feb0(Cpu *c); c->x[30] = 0x7000c61ee4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_700159feb0(c);',
        'f_700159feb0 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1ee0)'),
    'bu_61ef8':                          _offmap_store_guard(
        0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1ef8)'),
    'bu_61f04':                          _always_call(
        'x0',
        'extern void f_700159fec0(Cpu *c); c->x[30] = 0x7000c61f08ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_700159fec0(c);',
        'f_700159fec0 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1f04)'),
    'bu_61f14':                          _always_call(
        'x0',
        'extern void f_700159feb0(Cpu *c); c->x[30] = 0x7000c61f18ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_700159feb0(c);',
        'f_700159feb0 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1f14)'),
    'bu_61f2c':                          _offmap_store_guard(
        0xf9000109, 'x8', 'x8 + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x8 skipped off-map (1f2c)'),
    'bu_61f38':                          _always_call(
        'x0',
        'extern void f_700159fec0(Cpu *c); c->x[30] = 0x7000c61f3cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_700159fec0(c);',
        'f_700159fec0 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1f38)'),
    'bu_61f48':                          _always_call(
        'x0',
        'extern void f_700159feb0(Cpu *c); c->x[30] = 0x7000c61f4cull; c->x[0] = x0; c->x[8] = x8; f_700159feb0(c);',
        'f_700159feb0 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1f48)'),
    'bu_61f60':                          _offmap_store_guard(
        0xf9000368, 'c->x[27]', 'c->x[27] + 0x0ull', 'ST64', 'x8',
        'caller f_7000c61540 answered-0 walk store via c->x[27] skipped off-map (1f60)'),
    'bu_61f64':                          _always_call(
        'x0',
        'extern void f_700159fec0(Cpu *c); c->x[30] = 0x7000c61f68ull; c->x[0] = x0; c->x[8] = x8; f_700159fec0(c);',
        'f_700159fec0 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (1f64)'),
    'bu_61f84':                          _offmap_store_guard(
        0x390006cd, 'c->x[22]', 'c->x[22] + 0x1ull', 'ST8', '(uint32_t)c->x[13]',
        'caller f_7000c61540 answered-0 walk store via c->x[22] skipped off-map (1f84)'),
    'bu_61f88':                          _offmap_load_guard(
        0xf86c780d, 'x0', 'c->x[13]', 'x0 + (c->x[12] << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x0 skipped off-map (1f88)'),
    'bu_61fa8':                          _offmap_store_guard(
        0x390002cd, 'c->x[22]', 'c->x[22] + 0x0ull', 'ST8', '(uint32_t)c->x[13]',
        'caller f_7000c61540 answered-0 walk store via c->x[22] skipped off-map (1fa8)'),
    'bu_61fac':                          _offmap_load_guard(
        0xf86c780d, 'x0', 'c->x[13]', 'x0 + (c->x[12] << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x0 skipped off-map (1fac)'),
    'bu_61fc8':                          _offmap_load_guard(
        0xf86b780c, 'x0', 'c->x[12]', 'x0 + (c->x[11] << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x0 skipped off-map (1fc8)'),
    'bu_61fcc':                          _offmap_store_guard(
        0xf90006cc, 'c->x[22]', 'c->x[22] + 0x8ull', 'ST64', 'c->x[12]',
        'caller f_7000c61540 answered-0 walk store via c->x[22] skipped off-map (1fcc)'),
    'bu_61fe0':                          _offmap_load_guard(
        0xf8697908, 'x8', 'x8', 'x8 + (x9 << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1fe0)'),
    'bu_61fe4':                          _offmap_load_guard(
        0x3875c908, 'x8', 'x8', 'x8 + (uint64_t)(int64_t)(int32_t)c->x[21]', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (1fe4)'),
    'bu_6200c':                          _offmap_load_guard(
        0xf9400101, 'x8', 'c->x[1]', 'x8 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (200c)'),
    'bu_62024':                          _always_call(
        'x0',
        'extern void f_7000e8c830(Cpu *c); c->x[30] = 0x7000c62028ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; f_7000e8c830(c);',
        'f_7000e8c830 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (2024)'),
    'bu_62034':                          _offmap_load_guard(
        0xf869790b, 'x8', 'c->x[11]', 'x8 + (x9 << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2034)'),
    'bu_62040':                          _offmap_load_guard(
        0x3868696a, 'c->x[11]', 'x10', 'c->x[11] + x8', 'LD8',
        'caller f_7000c61540 answered-0 walk load via c->x[11] skipped off-map (2040)'),
    'bu_6206c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c62070ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (206c)'),
    'bu_62078':                          _always_call(
        'x0',
        'extern void f_7000eb4330(Cpu *c); c->x[30] = 0x7000c6207cull; c->x[0] = x0; f_7000eb4330(c);',
        'f_7000eb4330 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (2078)'),
    'bu_62084':                          _offmap_load_guard(
        0xf9446508, 'x8', 'x8', 'x8 + 0x8c8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2084)'),
    'bu_62090':                          _offmap_load_guard(
        0xf9400100, 'x8', 'x0', 'x8 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2090)'),
    'bu_620a0':                          _always_call(
        'x0',
        'extern void f_7000eb4434(Cpu *c); c->x[30] = 0x7000c620a4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000eb4434(c);',
        'f_7000eb4434 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (20a0)'),
    'bu_620a8':                          _always_call(
        'x0',
        'extern void f_7000e99bf0(Cpu *c); c->x[30] = 0x7000c620acull; c->x[0] = x0; f_7000e99bf0(c);',
        'f_7000e99bf0 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (20a8)'),
    'bu_620b8':                          _offmap_load_guard(
        0xf9446908, 'x8', 'x8', 'x8 + 0x8d0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (20b8)'),
    'bu_620cc':                          _offmap_load_guard(
        0xf9400100, 'x8', 'x0', 'x8 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (20cc)'),
    'bu_620d4':                          _always_call(
        'x0',
        'extern void f_7000e99c84(Cpu *c); c->x[30] = 0x7000c620d8ull; c->x[0] = x0; c->x[8] = x8; f_7000e99c84(c);',
        'f_7000e99c84 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (20d4)'),
    'bu_620dc':                          _always_call(
        'x0',
        'extern void f_7000e990e8(Cpu *c); c->x[30] = 0x7000c620e0ull; c->x[0] = x0; f_7000e990e8(c);',
        'f_7000e990e8 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (20dc)'),
    'bu_620ec':                          _offmap_load_guard(
        0xf9446f5a, 'c->x[26]', 'c->x[26]', 'c->x[26] + 0x8d8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[26] skipped off-map (20ec)'),
    'bu_62100':                          _offmap_load_guard(
        0xf9400340, 'c->x[26]', 'x0', 'c->x[26] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[26] skipped off-map (2100)'),
    'bu_6210c':                          _always_call(
        'x0',
        'extern void f_7000e99180(Cpu *c); c->x[30] = 0x7000c62110ull; c->x[0] = x0; f_7000e99180(c);',
        'f_7000e99180 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (210c)'),
    'bu_62110':                          _offmap_load_guard(
        0xf9400340, 'c->x[26]', 'x0', 'c->x[26] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[26] skipped off-map (2110)'),
    'bu_62114':                          _always_call(
        'x0',
        'extern void f_7000eb5c48(Cpu *c); c->x[30] = 0x7000c62118ull; c->x[0] = x0; f_7000eb5c48(c);',
        'f_7000eb5c48 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (2114)'),
    'bu_62124':                          _always_call(
        'x0',
        'extern void f_7000f37048(Cpu *c); c->x[30] = 0x7000c62128ull; c->x[0] = x0; c->x[8] = x8; f_7000f37048(c);',
        'f_7000f37048 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (2124)'),
    'bu_62130':                          _offmap_load_guard(
        0xf8697908, 'x8', 'x8', 'x8 + (x9 << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2130)'),
    'bu_62134':                          _offmap_load_guard(
        0x3940010b, 'x8', 'c->x[11]', 'x8 + 0x0ull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2134)'),
    'bu_62140':                          _offmap_load_guard(
        0x3940050b, 'x8', 'c->x[11]', 'x8 + 0x1ull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2140)'),
    'bu_62160':                          _offmap_load_guard(
        0x386b690c, 'x8', 'c->x[12]', 'x8 + c->x[11]', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2160)'),
    'bu_62164':                          _offmap_load_guard(
        0x386b694d, 'x10', 'c->x[13]', 'x10 + c->x[11]', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (2164)'),
    'bu_621a8':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (21a8)'),
    'bu_621ac':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c621b0ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (21ac)'),
    'bu_621b8':                          _offmap_load_guard(
        0x387b6909, 'x8', 'x9', 'x8 + c->x[27]', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (21b8)'),
    'bu_621d8':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (21d8)'),
    'bu_621dc':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c621e0ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (21dc)'),
    'bu_621e8':                          _offmap_load_guard(
        0x3868692a, 'x9', 'x10', 'x9 + x8', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (21e8)'),
    'bu_62228':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2228)'),
    'bu_6222c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c62230ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (222c)'),
    'bu_62248':                          _offmap_load_guard(
        0x386a690b, 'x8', 'c->x[11]', 'x8 + x10', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2248)'),
    'bu_6224c':                          _offmap_load_guard(
        0x386a692c, 'x9', 'c->x[12]', 'x9 + x10', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (224c)'),
    'bu_62284':                          _always_call(
        'x0',
        'extern void f_7000ea3c44(Cpu *c); c->x[30] = 0x7000c62288ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea3c44(c);',
        'f_7000ea3c44 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (2284)'),
    'bu_622a0':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c622a4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (22a0)'),
    'bu_622b4':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0520(Cpu *c); c->x[30] = 0x7000c622b8ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_70015a0520(c);',
        'f_70015a0520 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (22b4)'),
    'bu_622d8':                          _always_call(
        'x0',
        'extern void f_7000ea064c(Cpu *c); c->x[30] = 0x7000c622dcull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea064c(c);',
        'f_7000ea064c skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (22d8)'),
    'bu_622e4':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0530(Cpu *c); c->x[30] = 0x7000c622e8ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; f_70015a0530(c);',
        'f_70015a0530 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (22e4)'),
    'bu_622fc':                          _always_call(
        'x0',
        'extern void f_7000ea04a0(Cpu *c); c->x[30] = 0x7000c62300ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea04a0(c);',
        'f_7000ea04a0 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (22fc)'),
    'bu_62310':                          _offmap_load_guard(
        0xf9400508, 'x8', 'x8', 'x8 + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2310)'),
    'bu_62330':                          _offmap_load_guard(
        0xf9400900, 'x8', 'x0', 'x8 + 0x10ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2330)'),
    'bu_62354':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x0 skipped off-map (2354)'),
    'bu_62358':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2358)'),
    'bu_6235c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c62360ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (235c)'),
    'bu_62378':                          _offmap_load_guard(
        0xf9400d0e, 'x8', 'c->x[14]', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2378)'),
    'bu_62388':                          _offmap_load_guard(
        0xf9400daf, 'c->x[13]', 'c->x[15]', 'c->x[13] + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[13] skipped off-map (2388)'),
    'bu_6239c':                          _offmap_load_guard(
        0xf9400508, 'x8', 'x8', 'x8 + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (239c)'),
    'bu_623b8':                          _always_call(
        'x0',
        'extern void f_7000e8c944(Cpu *c); c->x[30] = 0x7000c623bcull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; f_7000e8c944(c);',
        'f_7000e8c944 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (23b8)'),
    'bu_623cc':                          _offmap_load_guard(
        0xf940016a, 'c->x[11]', 'x10', 'c->x[11] + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[11] skipped off-map (23cc)'),
    'bu_623d0':                          _offmap_store_guard(
        0xf9000169, 'c->x[11]', 'c->x[11] + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via c->x[11] skipped off-map (23d0)'),
    'bu_623d4':                          _offmap_pair_store_guard(
        0xa9002d2a, 'x9', 'x9 + 0', 'x10', 'c->x[11]',
        'caller f_7000c61540 answered-0 walk pair store via x9 skipped off-map (23d4)'),
    'bu_62404':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (2404)'),
    'bu_62408':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000c6240cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (2408)'),
    'bu_62414':                          _offmap_load_guard(
        0x3868692a, 'x9', 'x10', 'x9 + x8', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x9 skipped off-map (2414)'),
    'bu_62438':                          _offmap_load_guard(
        0xf9410d4a, 'x10', 'x10', 'x10 + 0x218ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (2438)'),
    'bu_6244c':                          _offmap_load_guard(
        0x3940010d, 'x8', 'c->x[13]', 'x8 + 0x0ull', 'LD8',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (244c)'),
    'bu_62454':                          _offmap_load_guard(
        0xf869794b, 'x10', 'c->x[11]', 'x10 + (x9 << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (2454)'),
    'bu_62460':                          _offmap_load_guard(
        0x3868696c, 'c->x[11]', 'c->x[12]', 'c->x[11] + x8', 'LD8',
        'caller f_7000c61540 answered-0 walk load via c->x[11] skipped off-map (2460)'),
    'bu_62470':                          _offmap_load_guard(
        0xf8697949, 'x10', 'x9', 'x10 + (x9 << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (2470)'),
    'bu_62490':                          _always_call(
        'x0',
        'extern void f_7000ea0704(Cpu *c); c->x[30] = 0x7000c62494ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea0704(c);',
        'f_7000ea0704 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (2490)'),
    'bu_624a4':                          _offmap_load_guard(
        0xf9400d0e, 'x8', 'c->x[14]', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (24a4)'),
    'bu_624b4':                          _offmap_load_guard(
        0xf9400daf, 'c->x[13]', 'c->x[15]', 'c->x[13] + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[13] skipped off-map (24b4)'),
    'bu_624c8':                          _offmap_load_guard(
        0xf9400508, 'x8', 'x8', 'x8 + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (24c8)'),
    'bu_624e4':                          _offmap_load_guard(
        0xf9400d0e, 'x8', 'c->x[14]', 'x8 + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (24e4)'),
    'bu_624f0':                          _offmap_load_guard(
        0xf9400508, 'x8', 'x8', 'x8 + 0x8ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x8 skipped off-map (24f0)'),
    'bu_6250c':                          _offmap_load_guard(
        0xf9400dbc, 'c->x[13]', 'c->x[28]', 'c->x[13] + 0x18ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via c->x[13] skipped off-map (250c)'),
    'bu_62520':                          _offmap_load_guard(
        0x3868696a, 'c->x[11]', 'x10', 'c->x[11] + x8', 'LD8',
        'caller f_7000c61540 answered-0 walk load via c->x[11] skipped off-map (2520)'),
    'bu_62580':                          _offmap_load_guard(
        0xf86bd949, 'x10', 'x9', 'x10 + ((uint64_t)(int64_t)(int32_t)c->x[11] << 3)', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (2580)'),
    'bu_62590':                          _offmap_load_guard(
        0xf9400141, 'x10', 'c->x[1]', 'x10 + 0x0ull', 'LD64',
        'caller f_7000c61540 answered-0 walk load via x10 skipped off-map (2590)'),
    'bu_625a8':                          _always_call(
        'x0',
        'extern void f_7000e8c830(Cpu *c); c->x[30] = 0x7000c625acull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; f_7000e8c830(c);',
        'f_7000e8c830 skipped on the off-map x0 of the answered-0 caller walk; the dead 0 answer lands where the guarded chain already expects 0 (25a8)'),
    'bu_625cc':                          _offmap_store_guard(
        0xf9000149, 'x10', 'x10 + 0x0ull', 'ST64', 'x9',
        'caller f_7000c61540 answered-0 walk store via x10 skipped off-map (25cc)'),
    'bv_188b8':                          _offmap_load_guard(
        0xf9475e68, 'c->x[19]', 'x8', 'c->x[19] + 0xeb8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[19] skipped off-map (88b8)'),
    'bv_188c4':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (88c4)'),
    'bv_188c8':                          _offmap_load_guard(
        0xf9400169, 'x11', 'x9', 'x11 + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (88c8)'),
    'bv_188d8':                          _offmap_load_guard(
        0xf9400109, 'x8', 'x9', 'x8 + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (88d8)'),
    'bv_188e0':                          _offmap_load_guard(
        0xf9401929, 'x9', 'x9', 'x9 + 0x30ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x9 skipped off-map (88e0)'),
    'bv_188e4':                          _offmap_load_guard(
        0xf9447d4a, 'x10', 'x10', 'x10 + 0x8f8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x10 skipped off-map (88e4)'),
    'bv_188f0':                          _offmap_load_guard(
        0xf9400171, 'x11', 'c->x[17]', 'x11 + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (88f0)'),
    'bv_188f4':                          _offmap_load_guard(
        0x7941b109, 'x8', 'x9', 'x8 + 0xd8ull', 'LD16',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (88f4)'),
    'bv_18900':                          _offmap_load_guard(
        0xb940910a, 'x8', 'x10', 'x8 + 0x90ull', 'LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8900)'),
    'bv_18914':                          _offmap_load_guard(
        0xf940750c, 'x8', 'c->x[12]', 'x8 + 0xe8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8914)'),
    'bv_18924':                          _offmap_load_guard(
        0xb980f50a, 'x8', 'x10', 'x8 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8924)'),
    'bv_1892c':                          _offmap_load_guard(
        0x39437110, 'x8', 'c->x[16]', 'x8 + 0xdcull', 'LD8',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (892c)'),
    'bv_1893c':                          _offmap_load_guard(
        0xf9400d90, 'c->x[12]', 'c->x[16]', 'c->x[12] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[12] skipped off-map (893c)'),
    'bv_1894c':                          _offmap_load_guard(
        0x7940258e, 'c->x[12]', 'c->x[14]', 'c->x[12] + 0x12ull', 'LD16',
        'f_7000d188a4 answered-0 walk load via c->x[12] skipped off-map (894c)'),
    'bv_18950':                          _offmap_store_guard(
        0xf9000d8a, 'c->x[12]', 'c->x[12] + 0x18ull', 'ST64', 'x10',
        'f_7000d188a4 answered-0 walk store via c->x[12] skipped off-map (8950)'),
    'bv_18954':                          _offmap_load_guard(
        0xb980f50d, 'x8', 'c->x[13]', 'x8 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8954)'),
    'bv_1895c':                          _offmap_load_guard(
        0xf9400551, 'x10', 'c->x[17]', 'x10 + 0x8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x10 skipped off-map (895c)'),
    'bv_1896c':                          _offmap_load_guard(
        0xf9400152, 'x10', 'c->x[18]', 'x10 + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x10 skipped off-map (896c)'),
    'bv_18974':                          _offmap_store_guard(
        0xf9000651, 'c->x[18]', 'c->x[18] + 0x8ull', 'ST64', 'c->x[17]',
        'f_7000d188a4 answered-0 walk store via c->x[18] skipped off-map (8974)'),
    'bv_18978':                          _offmap_load_guard(
        0xf9400551, 'x10', 'c->x[17]', 'x10 + 0x8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x10 skipped off-map (8978)'),
    'bv_18980':                          _offmap_load_guard(
        0xf9400152, 'x10', 'c->x[18]', 'x10 + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x10 skipped off-map (8980)'),
    'bv_18984':                          _offmap_store_guard(
        0xf9000232, 'c->x[17]', 'c->x[17] + 0x0ull', 'ST64', 'c->x[18]',
        'f_7000d188a4 answered-0 walk store via c->x[17] skipped off-map (8984)'),
    'bv_18988':                          _offmap_pair_store_guard(
        0xa9007d5f, 'x10', 'x10 + 0', '0ull', '0ull',
        'f_7000d188a4 answered-0 walk pair store via x10 skipped off-map (8988)'),
    'bv_18990':                          _offmap_load_guard(
        0xb940f111, 'x8', 'c->x[17]', 'x8 + 0xf0ull', 'LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8990)'),
    'bv_18994':                          _offmap_load_guard(
        0xb9409112, 'x8', 'c->x[18]', 'x8 + 0x90ull', 'LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8994)'),
    'bv_189a0':                          _offmap_store_guard(
        0xb900f111, 'x8', 'x8 + 0xf0ull', 'ST32', '(uint32_t)c->x[17]',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (89a0)'),
    'bv_189a4':                          _offmap_load_guard(
        0xb9810d11, 'x8', 'c->x[17]', 'x8 + 0x10cull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (89a4)'),
    'bv_189b0':                          _offmap_load_guard(
        0xf9400151, 'x10', 'c->x[17]', 'x10 + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x10 skipped off-map (89b0)'),
    'bv_189b4':                          _offmap_store_guard(
        0xf9000141, 'x10', 'x10 + 0x0ull', 'ST64', 'c->x[1]',
        'f_7000d188a4 answered-0 walk store via x10 skipped off-map (89b4)'),
    'bv_189b8':                          _offmap_pair_store_guard(
        0xa9002831, 'c->x[1]', 'c->x[1] + 0', 'c->x[17]', 'x10',
        'f_7000d188a4 answered-0 walk pair store via c->x[1] skipped off-map (89b8)'),
    'bv_189c0':                          _offmap_store_guard(
        0xf9000621, 'c->x[17]', 'c->x[17] + 0x8ull', 'ST64', 'c->x[1]',
        'f_7000d188a4 answered-0 walk store via c->x[17] skipped off-map (89c0)'),
    'bv_189c4':                          _offmap_load_guard(
        0xb941090a, 'x8', 'x10', 'x8 + 0x108ull', 'LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (89c4)'),
    'bv_189cc':                          _offmap_store_guard(
        0xb901090a, 'x8', 'x8 + 0x108ull', 'ST32', '(uint32_t)x10',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (89cc)'),
    'bv_189e4':                          _offmap_pre_store_guard(
        0xf8050ddf, 'c->x[14]', '80',
        'f_7000d188a4 answered-0 walk pre-index store via c->x[14] skipped off-map (89e4)'),
    'bv_189e8':                          _offmap_store_guard(
        0xf9000dca, 'c->x[14]', 'c->x[14] + 0x18ull', 'ST64', 'x10',
        'f_7000d188a4 answered-0 walk store via c->x[14] skipped off-map (89e8)'),
    'bv_189f0':                          _offmap_store_guard(
        0xb90011df, 'c->x[14]', 'c->x[14] + 0x10ull', 'ST32', '0u',
        'f_7000d188a4 answered-0 walk store via c->x[14] skipped off-map (89f0)'),
    'bv_189f4':                          _offmap_store_guard(
        0xf90005df, 'c->x[14]', 'c->x[14] + 0x8ull', 'ST64', '0ull',
        'f_7000d188a4 answered-0 walk store via c->x[14] skipped off-map (89f4)'),
    'bv_189f8':                          _offmap_store_guard(
        0x790021ca, 'c->x[14]', 'c->x[14] + 0x10ull', 'ST16', '(uint32_t)x10',
        'f_7000d188a4 answered-0 walk store via c->x[14] skipped off-map (89f8)'),
    'bv_189fc':                          _offmap_load_guard(
        0xb980f510, 'x8', 'c->x[16]', 'x8 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (89fc)'),
    'bv_18a04':                          _offmap_load_guard(
        0xf94001ed, 'c->x[15]', 'c->x[13]', 'c->x[15] + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[15] skipped off-map (8a04)'),
    'bv_18a0c':                          _offmap_store_guard(
        0xf90001ea, 'c->x[15]', 'c->x[15] + 0x0ull', 'ST64', 'x10',
        'f_7000d188a4 answered-0 walk store via c->x[15] skipped off-map (8a0c)'),
    'bv_18a10':                          _offmap_pair_store_guard(
        0xa9003d4d, 'x10', 'x10 + 0', 'c->x[13]', 'c->x[15]',
        'f_7000d188a4 answered-0 walk pair store via x10 skipped off-map (8a10)'),
    'bv_18a18':                          _offmap_store_guard(
        0xf90005aa, 'c->x[13]', 'c->x[13] + 0x8ull', 'ST64', 'x10',
        'f_7000d188a4 answered-0 walk store via c->x[13] skipped off-map (8a18)'),
    'bv_18a1c':                          _offmap_load_guard(
        0xb940f10a, 'x8', 'x10', 'x8 + 0xf0ull', 'LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8a1c)'),
    'bv_18a24':                          _offmap_store_guard(
        0xb900f10a, 'x8', 'x8 + 0xf0ull', 'ST32', '(uint32_t)x10',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (8a24)'),
    'bv_18a28':                          _offmap_load_guard(
        0x7941b508, 'x8', 'x8', 'x8 + 0xdaull', 'LD16',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8a28)'),
    'bv_18a2c':                          _offmap_store_guard(
        0x79002188, 'c->x[12]', 'c->x[12] + 0x10ull', 'ST16', '(uint32_t)x8',
        'f_7000d188a4 answered-0 walk store via c->x[12] skipped off-map (8a2c)'),
    'bv_18a30':                          _offmap_load_guard(
        0x79402588, 'c->x[12]', 'x8', 'c->x[12] + 0x12ull', 'LD16',
        'f_7000d188a4 answered-0 walk load via c->x[12] skipped off-map (8a30)'),
    'bv_18a48':                          _offmap_load_guard(
        0xf9447129, 'x9', 'x9', 'x9 + 0x8e0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x9 skipped off-map (8a48)'),
    'bv_18a50':                          _offmap_pre_store_guard(
        0xf8008d49, 'x10', '8',
        'f_7000d188a4 answered-0 walk pre-index store via x10 skipped off-map (8a50)'),
    'bv_18a58':                          _offmap_pair_store_guard(
        0xa9017d5f, 'x10', 'x10 + 16', '0ull', '0ull',
        'f_7000d188a4 answered-0 walk pair store via x10 skipped off-map (8a58)'),
    'bv_18a5c':                          _offmap_pre_store_guard(
        0xf8008d20, 'x9', '8',
        'f_7000d188a4 answered-0 walk pre-index store via x9 skipped off-map (8a5c)'),
    'bv_18a64':                          _offmap_load_guard(
        0x7941b009, 'c->x[0]', 'x9', 'c->x[0] + 0xd8ull', 'LD16',
        'f_7000d188a4 answered-0 walk load via c->x[0] skipped off-map (8a64)'),
    'bv_18a74':                          _offmap_pre_load_guard(
        0xf8478dab, 'c->x[13]', '120', 'x11',
        'f_7000d188a4 answered-0 walk pre-index load via c->x[13] skipped off-map (8a74)'),
    'bv_18a78':                          _offmap_load_guard(
        0xb98015ac, 'c->x[13]', 'c->x[12]', 'c->x[13] + 0x14ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000d188a4 answered-0 walk load via c->x[13] skipped off-map (8a78)'),
    'bv_18a80':                          _offmap_store_guard(
        0xf90001ac, 'c->x[13]', 'c->x[13] + 0x0ull', 'ST64', 'c->x[12]',
        'f_7000d188a4 answered-0 walk store via c->x[13] skipped off-map (8a80)'),
    'bv_18a84':                          _offmap_pair_store_guard(
        0xa900358b, 'c->x[12]', 'c->x[12] + 0', 'x11', 'c->x[13]',
        'f_7000d188a4 answered-0 walk pair store via c->x[12] skipped off-map (8a84)'),
    'bv_18a8c':                          _offmap_store_guard(
        0xf900056c, 'x11', 'x11 + 0x8ull', 'ST64', 'c->x[12]',
        'f_7000d188a4 answered-0 walk store via x11 skipped off-map (8a8c)'),
    'bv_18a90':                          _offmap_load_guard(
        0xb940880b, 'c->x[0]', 'x11', 'c->x[0] + 0x88ull', 'LD32',
        'f_7000d188a4 answered-0 walk load via c->x[0] skipped off-map (8a90)'),
    'bv_18a98':                          _offmap_store_guard(
        0xb900880b, 'c->x[0]', 'c->x[0] + 0x88ull', 'ST32', '(uint32_t)x11',
        'f_7000d188a4 answered-0 walk store via c->x[0] skipped off-map (8a98)'),
    'bv_18aa8':                          _offmap_store_guard(
        0xf9000149, 'x10', 'x10 + 0x0ull', 'ST64', 'x9',
        'f_7000d188a4 answered-0 walk store via x10 skipped off-map (8aa8)'),
    'bv_18ab8':                          _offmap_store_guard(
        0xf907592a, 'x9', 'x9 + 0xeb0ull', 'ST64', 'x10',
        'f_7000d188a4 answered-0 walk store via x9 skipped off-map (8ab8)'),
    'bv_18ac0':                          _offmap_store_guard(
        0xf900010b, 'x8', 'x8 + 0x0ull', 'ST64', 'x11',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (8ac0)'),
    'bv_18ac4':                          _offmap_store_guard(
        0xb9002909, 'x8', 'x8 + 0x28ull', 'ST32', '(uint32_t)x9',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (8ac4)'),
    'bv_18ac8':                          _offmap_store_guard(
        0x3900b11f, 'x8', 'x8 + 0x2cull', 'ST8', '0u',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (8ac8)'),
    'bv_18acc':                          _offmap_store_guard(
        0xf9075e68, 'c->x[19]', 'c->x[19] + 0xeb8ull', 'ST64', 'x8',
        'f_7000d188a4 answered-0 walk store via c->x[19] skipped off-map (8acc)'),
    'bv_18ae4':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8ae4)'),
    'bv_18af4':                          _offmap_store_guard(
        0xf9000fa9, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'x9',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8af4)'),
    'bv_18b00':                          _offmap_load_guard(
        0xf9400120, 'x9', 'c->x[0]', 'x9 + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x9 skipped off-map (8b00)'),
    'bv_18b08':                          _always_call(
        'c->x[0]',
        'extern void f_7000ea3c44(Cpu *c); c->x[30] = 0x7000d18b0cull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000ea3c44(c);',
        'f_7000ea3c44 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8b08)'),
    'bv_18b0c':                          _offmap_load_guard(
        0xf9400fa8, 'c->x[29]', 'x8', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8b0c)'),
    'bv_18b10':                          _offmap_store_guard(
        0xf9000100, 'x8', 'x8 + 0x0ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (8b10)'),
    'bv_18b20':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8b20)'),
    'bv_18b28':                          _always_call(
        'c->x[0]',
        'extern void f_7000ea3c44(Cpu *c); c->x[30] = 0x7000d18b2cull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[11] = x11; c->sp = sp_; f_7000ea3c44(c);',
        'f_7000ea3c44 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8b28)'),
    'bv_18b34':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (8b34)'),
    'bv_18b38':                          _offmap_load_guard(
        0xf9400fa0, 'c->x[29]', 'c->x[0]', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8b38)'),
    'bv_18b4c':                          _offmap_load_guard(
        0xf9447108, 'x8', 'x8', 'x8 + 0x8e0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8b4c)'),
    'bv_18b64':                          _offmap_store_guard(
        0xf900014b, 'x10', 'x10 + 0x0ull', 'ST64', 'x11',
        'f_7000d188a4 answered-0 walk store via x10 skipped off-map (8b64)'),
    'bv_18b6c':                          _offmap_store_guard(
        0xf9000fa8, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'x8',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8b6c)'),
    'bv_18b74':                          _offmap_store_guard(
        0xf900015f, 'x10', 'x10 + 0x0ull', 'ST64', '0ull',
        'f_7000d188a4 answered-0 walk store via x10 skipped off-map (8b74)'),
    'bv_18b78':                          _offmap_store_guard(
        0xf900011f, 'x8', 'x8 + 0x0ull', 'ST64', '0ull',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (8b78)'),
    'bv_18b80':                          _offmap_store_guard(
        0xf900011f, 'x8', 'x8 + 0x0ull', 'ST64', '0ull',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (8b80)'),
    'bv_18b8c':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8b8c)'),
    'bv_18b98':                          _always_call(
        'c->x[0]',
        'extern void f_7000eaff08(Cpu *c); c->x[30] = 0x7000d18b9cull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000eaff08(c);',
        'f_7000eaff08 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8b98)'),
    'bv_18ba4':                          _offmap_load_guard(
        0xf9400fa0, 'c->x[29]', 'c->x[0]', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8ba4)'),
    'bv_18bb8':                          _always_call(
        'c->x[0]',
        'extern void f_7000eaff18(Cpu *c); c->x[30] = 0x7000d18bbcull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000eaff18(c);',
        'f_7000eaff18 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8bb8)'),
    'bv_18bc4':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8bc4)'),
    'bv_18bd4':                          _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x7000d18bd8ull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x9 is off-map or unmapped (8bd4)', cond='x9', w=0xd63f0120),
    'bv_18be0':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (8be0)'),
    'bv_18be4':                          _offmap_load_guard(
        0xf9400fa0, 'c->x[29]', 'c->x[0]', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8be4)'),
    'bv_18bf0':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8bf0)'),
    'bv_18c00':                          _always_call(
        'c->x[0]',
        'extern void f_7000eaff08(Cpu *c); c->x[30] = 0x7000d18c04ull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000eaff08(c);',
        'f_7000eaff08 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8c00)'),
    'bv_18c18':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (8c18)'),
    'bv_18c1c':                          _offmap_load_guard(
        0xf9400fa0, 'c->x[29]', 'c->x[0]', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8c1c)'),
    'bv_18c34':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8c34)'),
    'bv_18c48':                          _always_call(
        'c->x[0]',
        'extern void f_7000ea064c(Cpu *c); c->x[30] = 0x7000d18c4cull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000ea064c(c);',
        'f_7000ea064c skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8c48)'),
    'bv_18c50':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8c50)'),
    'bv_18c5c':                          _always_call(
        'c->x[0]',
        'extern void f_7000eaff18(Cpu *c); c->x[30] = 0x7000d18c60ull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000eaff18(c);',
        'f_7000eaff18 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8c5c)'),
    'bv_18c64':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (8c64)'),
    'bv_18c70':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8c70)'),
    'bv_18c88':                          _always_call(
        'c->x[0]',
        'extern void f_7000ea04a0(Cpu *c); c->x[30] = 0x7000d18c8cull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000ea04a0(c);',
        'f_7000ea04a0 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8c88)'),
    'bv_18c98':                          _offmap_load_guard(
        0xf9400fa0, 'c->x[29]', 'c->x[0]', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8c98)'),
    'bv_18ca4':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (8ca4)'),
    'bv_18cbc':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8cbc)'),
    'bv_18cc8':                          _offmap_load_guard(
        0xf9400d89, 'c->x[12]', 'x9', 'c->x[12] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[12] skipped off-map (8cc8)'),
    'bv_18cd8':                          _offmap_load_guard(
        0xf9400d0b, 'x8', 'x11', 'x8 + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8cd8)'),
    'bv_18cec':                          _offmap_load_guard(
        0xf9400529, 'x9', 'x9', 'x9 + 0x8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x9 skipped off-map (8cec)'),
    'bv_18d04':                          _offmap_load_guard(
        0xf940058c, 'c->x[12]', 'c->x[12]', 'c->x[12] + 0x8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[12] skipped off-map (8d04)'),
    'bv_18d20':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8d20)'),
    'bv_18d30':                          _offmap_load_guard(
        0xf9400900, 'x8', 'c->x[0]', 'x8 + 0x10ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8d30)'),
    'bv_18d5c':                          _offmap_load_guard(
        0xf9400008, 'c->x[0]', 'x8', 'c->x[0] + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[0] skipped off-map (8d5c)'),
    'bv_18d60':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8d60)'),
    'bv_18d64':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000d18d68ull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (8d64)'),
    'bv_18d70':                          _offmap_load_guard(
        0xf9400fa0, 'c->x[29]', 'c->x[0]', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8d70)'),
    'bv_18d78':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (8d78)'),
    'bv_18d88':                          _offmap_store_guard(
        0xf9000fa0, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'c->x[0]',
        'f_7000d188a4 answered-0 walk store via c->x[29] skipped off-map (8d88)'),
    'bv_18da0':                          _always_call(
        'c->x[0]',
        'extern void f_7000e8c944(Cpu *c); c->x[30] = 0x7000d18da4ull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000e8c944(c);',
        'f_7000e8c944 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8da0)'),
    'bv_18db0':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (8db0)'),
    'bv_18dbc':                          _offmap_load_guard(
        0xf9400fa0, 'c->x[29]', 'c->x[0]', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8dbc)'),
    'bv_18dd4':                          _offmap_store_guard(
        0xf9000d90, 'c->x[12]', 'c->x[12] + 0x18ull', 'ST64', 'c->x[16]',
        'f_7000d188a4 answered-0 walk store via c->x[12] skipped off-map (8dd4)'),
    'bv_18de4':                          _offmap_load_guard(
        0xf94001ed, 'c->x[15]', 'c->x[13]', 'c->x[15] + 0x0ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[15] skipped off-map (8de4)'),
    'bv_18dec':                          _offmap_store_guard(
        0xf90001eb, 'c->x[15]', 'c->x[15] + 0x0ull', 'ST64', 'x11',
        'f_7000d188a4 answered-0 walk store via c->x[15] skipped off-map (8dec)'),
    'bv_18df0':                          _offmap_pair_store_guard(
        0xa9003d6d, 'x11', 'x11 + 0', 'c->x[13]', 'c->x[15]',
        'f_7000d188a4 answered-0 walk pair store via x11 skipped off-map (8df0)'),
    'bv_18df8':                          _offmap_store_guard(
        0xf90005ab, 'c->x[13]', 'c->x[13] + 0x8ull', 'ST64', 'x11',
        'f_7000d188a4 answered-0 walk store via c->x[13] skipped off-map (8df8)'),
    'bv_18dfc':                          _offmap_load_guard(
        0xb940f10b, 'x8', 'x11', 'x8 + 0xf0ull', 'LD32',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8dfc)'),
    'bv_18e04':                          _offmap_store_guard(
        0xb900f10b, 'x8', 'x8 + 0xf0ull', 'ST32', '(uint32_t)x11',
        'f_7000d188a4 answered-0 walk store via x8 skipped off-map (8e04)'),
    'bv_18e1c':                          _always_call(
        'c->x[0]',
        'extern void f_7000ea0704(Cpu *c); c->x[30] = 0x7000d18e20ull; c->x[0] = c->x[0]; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[11] = x11; c->sp = sp_; f_7000ea0704(c);',
        'f_7000ea0704 skipped on the off-map c->x[0] of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (8e1c)'),
    'bv_18e30':                          _offmap_load_guard(
        0xf9400d89, 'c->x[12]', 'x9', 'c->x[12] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[12] skipped off-map (8e30)'),
    'bv_18e40':                          _offmap_load_guard(
        0xf9400d0b, 'x8', 'x11', 'x8 + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8e40)'),
    'bv_18e54':                          _offmap_load_guard(
        0xf9400529, 'x9', 'x9', 'x9 + 0x8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x9 skipped off-map (8e54)'),
    'bv_18e6c':                          _offmap_load_guard(
        0xf9400d89, 'c->x[12]', 'x9', 'c->x[12] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[12] skipped off-map (8e6c)'),
    'bv_18e80':                          _offmap_load_guard(
        0xf9400529, 'x9', 'x9', 'x9 + 0x8ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x9 skipped off-map (8e80)'),
    'bv_18ea0':                          _offmap_load_guard(
        0xf9400d10, 'x8', 'c->x[16]', 'x8 + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x8 skipped off-map (8ea0)'),
    'bv_18ea4':                          _offmap_load_guard(
        0xf9400fa0, 'c->x[29]', 'c->x[0]', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via c->x[29] skipped off-map (8ea4)'),
    'bv_18eac':                          _offmap_load_guard(
        0xf942196b, 'x11', 'x11', 'x11 + 0x430ull', 'LD64',
        'f_7000d188a4 answered-0 walk load via x11 skipped off-map (8eac)'),
    'bw_05894':                          _offmap_store_guard(
        0xb900301f, 'x0', 'x0 + 0x30ull', 'ST32', '0u',
        'f_7000005874 answered-0 node-init store via x0 skipped off-map (5894)'),
    'bw_05898':                          _offmap_pair_store_guard(
        0xa9025816, 'x0', 'x0 + 32', 'c->x[22]', 'c->x[22]',
        'f_7000005874 answered-0 node-init pair store via x0 skipped off-map (5898)'),
    'bw_058a4':                          _offmap_store_guard(
        0xb900481f, 'x0', 'x0 + 0x48ull', 'ST32', '0u',
        'f_7000005874 answered-0 node-init store via x0 skipped off-map (58a4)'),
    'bw_058a8':                          _offmap_pair_store_guard(
        0xa903a008, 'x0', 'x0 + 56', 'x8', 'x8',
        'f_7000005874 answered-0 node-init pair store via x0 skipped off-map (58a8)'),
    'bw_058ac':                          _offmap_load_guard(
        0xf9421a94, 'c->x[20]', 'c->x[20]', 'c->x[20] + 0x430ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (58ac)'),
    'bw_058b0':                          _offmap_load_guard(
        0xf9400280, 'c->x[20]', 'x0', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (58b0)'),
    'bw_058b4':                          _offmap_pair_store_guard(
        0xa9057e7f, 'c->x[19]', 'c->x[19] + 80', '0ull', '0ull',
        'f_7000005874 answered-0 node-init pair store via c->x[19] skipped off-map (58b4)'),
    'bw_058c0':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000006ef0(Cpu *c); c->x[30] = 0x70000058c4ull; c->x[0] = x0; c->x[8] = x8; c->x[20] = c->x[20]; c->sp = sp_; f_7000006ef0(c);',
        'f_7000006ef0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (58c0)'),
    'bw_058c4':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (58c4)'),
    'bw_058d0':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (58d0)'),
    'bw_058d8':                          _offmap_load_guard(
        0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x8 skipped off-map (58d8)'),
    'bw_058dc':                          _offmap_load_guard(
        0xf9447d29, 'x9', 'x9', 'x9 + 0x8f8ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x9 skipped off-map (58dc)'),
    'bw_058e8':                          _offmap_load_guard(
        0xf940028d, 'c->x[20]', 'c->x[13]', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (58e8)'),
    'bw_058ec':                          _offmap_load_guard(
        0x7941b008, 'x0', 'x8', 'x0 + 0xd8ull', 'LD16',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (58ec)'),
    'bw_058f8':                          _offmap_load_guard(
        0xb9409008, 'x0', 'x8', 'x0 + 0x90ull', 'LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (58f8)'),
    'bw_0590c':                          _offmap_load_guard(
        0xf940740b, 'x0', 'x11', 'x0 + 0xe8ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (590c)'),
    'bw_0591c':                          _offmap_load_guard(
        0xb980f408, 'x0', 'x8', 'x0 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (591c)'),
    'bw_05924':                          _offmap_load_guard(
        0x3943700c, 'x0', 'c->x[12]', 'x0 + 0xdcull', 'LD8',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (5924)'),
    'bw_05934':                          _offmap_load_guard(
        0xf9400d6c, 'x11', 'c->x[12]', 'x11 + 0x18ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5934)'),
    'bw_05944':                          _offmap_load_guard(
        0x79402569, 'x11', 'x9', 'x11 + 0x12ull', 'LD16',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5944)'),
    'bw_05948':                          _offmap_store_guard(
        0xf9000d68, 'x11', 'x11 + 0x18ull', 'ST64', 'x8',
        'f_7000005874 answered-0 node-init store via x11 skipped off-map (5948)'),
    'bw_0594c':                          _offmap_load_guard(
        0xb980f40e, 'x0', 'c->x[14]', 'x0 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (594c)'),
    'bw_05954':                          _offmap_ldp_load_guard(
        0xa940290d, 'x8', 'c->x[13]', 'c->x[10]',
        'x8 + 0',
        'f_7000005874 answered-0 node-init ldp pair load via x8 skipped off-map (5954)'),
    'bw_05968':                          _offmap_store_guard(
        0xf90005aa, 'c->x[13]', 'c->x[13] + 0x8ull', 'ST64', 'c->x[10]',
        'f_7000005874 answered-0 node-init store via c->x[13] skipped off-map (5968)'),
    'bw_0596c':                          _offmap_load_guard(
        0xf940050a, 'x8', 'c->x[10]', 'x8 + 0x8ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x8 skipped off-map (596c)'),
    'bw_05974':                          _offmap_load_guard(
        0xf940010d, 'x8', 'c->x[13]', 'x8 + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x8 skipped off-map (5974)'),
    'bw_05978':                          _offmap_store_guard(
        0xf900014d, 'c->x[10]', 'c->x[10] + 0x0ull', 'ST64', 'c->x[13]',
        'f_7000005874 answered-0 node-init store via c->x[10] skipped off-map (5978)'),
    'bw_0597c':                          _offmap_pair_store_guard(
        0xa9007d1f, 'x8', 'x8 + 0', '0ull', '0ull',
        'f_7000005874 answered-0 node-init pair store via x8 skipped off-map (597c)'),
    'bw_05984':                          _offmap_load_guard(
        0xb940f00a, 'x0', 'c->x[10]', 'x0 + 0xf0ull', 'LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (5984)'),
    'bw_05988':                          _offmap_load_guard(
        0xb940900d, 'x0', 'c->x[13]', 'x0 + 0x90ull', 'LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (5988)'),
    'bw_05994':                          _offmap_store_guard(
        0xb900f00a, 'x0', 'x0 + 0xf0ull', 'ST32', '(uint32_t)c->x[10]',
        'f_7000005874 answered-0 node-init store via x0 skipped off-map (5994)'),
    'bw_05998':                          _offmap_load_guard(
        0xb9810c0a, 'x0', 'c->x[10]', 'x0 + 0x10cull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (5998)'),
    'bw_059a4':                          _offmap_load_guard(
        0xf940010a, 'x8', 'c->x[10]', 'x8 + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x8 skipped off-map (59a4)'),
    'bw_059a8':                          _offmap_store_guard(
        0xf9000101, 'x8', 'x8 + 0x0ull', 'ST64', 'c->x[1]',
        'f_7000005874 answered-0 node-init store via x8 skipped off-map (59a8)'),
    'bw_059ac':                          _offmap_pair_store_guard(
        0xa900202a, 'c->x[1]', 'c->x[1] + 0', 'c->x[10]', 'x8',
        'f_7000005874 answered-0 node-init pair store via c->x[1] skipped off-map (59ac)'),
    'bw_059b4':                          _offmap_store_guard(
        0xf9000541, 'c->x[10]', 'c->x[10] + 0x8ull', 'ST64', 'c->x[1]',
        'f_7000005874 answered-0 node-init store via c->x[10] skipped off-map (59b4)'),
    'bw_059b8':                          _offmap_load_guard(
        0xb9410808, 'x0', 'x8', 'x0 + 0x108ull', 'LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (59b8)'),
    'bw_059c0':                          _offmap_store_guard(
        0xb9010808, 'x0', 'x0 + 0x108ull', 'ST32', '(uint32_t)x8',
        'f_7000005874 answered-0 node-init store via x0 skipped off-map (59c0)'),
    'bw_059d8':                          _offmap_pre_store_guard(
        0xf8098d1f, 'x8', '152',
        'f_7000005874 answered-0 node-init pre-index store via x8 skipped off-map (59d8)'),
    'bw_059dc':                          _offmap_store_guard(
        0xf9000d09, 'x8', 'x8 + 0x18ull', 'ST64', 'x9',
        'f_7000005874 answered-0 node-init store via x8 skipped off-map (59dc)'),
    'bw_059e4':                          _offmap_store_guard(
        0xb900111f, 'x8', 'x8 + 0x10ull', 'ST32', '0u',
        'f_7000005874 answered-0 node-init store via x8 skipped off-map (59e4)'),
    'bw_059e8':                          _offmap_store_guard(
        0xf900051f, 'x8', 'x8 + 0x8ull', 'ST64', '0ull',
        'f_7000005874 answered-0 node-init store via x8 skipped off-map (59e8)'),
    'bw_059ec':                          _offmap_store_guard(
        0x79002109, 'x8', 'x8 + 0x10ull', 'ST16', '(uint32_t)x9',
        'f_7000005874 answered-0 node-init store via x8 skipped off-map (59ec)'),
    'bw_059f0':                          _offmap_load_guard(
        0xb980f409, 'x0', 'x9', 'x0 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (59f0)'),
    'bw_059fc':                          _offmap_load_guard(
        0xf9400289, 'c->x[20]', 'x9', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (59fc)'),
    'bw_05a00':                          _offmap_store_guard(
        0xf9000288, 'c->x[20]', 'c->x[20] + 0x0ull', 'ST64', 'x8',
        'f_7000005874 answered-0 node-init store via c->x[20] skipped off-map (5a00)'),
    'bw_05a04':                          _offmap_pair_store_guard(
        0xa9005109, 'x8', 'x8 + 0', 'x9', 'c->x[20]',
        'f_7000005874 answered-0 node-init pair store via x8 skipped off-map (5a04)'),
    'bw_05a0c':                          _offmap_store_guard(
        0xf9000528, 'x9', 'x9 + 0x8ull', 'ST64', 'x8',
        'f_7000005874 answered-0 node-init store via x9 skipped off-map (5a0c)'),
    'bw_05a10':                          _offmap_load_guard(
        0xb940f008, 'x0', 'x8', 'x0 + 0xf0ull', 'LD32',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (5a10)'),
    'bw_05a18':                          _offmap_store_guard(
        0xb900f008, 'x0', 'x0 + 0xf0ull', 'ST32', '(uint32_t)x8',
        'f_7000005874 answered-0 node-init store via x0 skipped off-map (5a18)'),
    'bw_05a1c':                          _offmap_load_guard(
        0x7941b408, 'x0', 'x8', 'x0 + 0xdaull', 'LD16',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (5a1c)'),
    'bw_05a20':                          _offmap_store_guard(
        0x79002168, 'x11', 'x11 + 0x10ull', 'ST16', '(uint32_t)x8',
        'f_7000005874 answered-0 node-init store via x11 skipped off-map (5a20)'),
    'bw_05a24':                          _offmap_load_guard(
        0x79402568, 'x11', 'x8', 'x11 + 0x12ull', 'LD16',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5a24)'),
    'bw_05a40':                          _offmap_pre_store_guard(
        0xf8020eff, 'c->x[23]', '32',
        'f_7000005874 answered-0 node-init pre-index store via c->x[23] skipped off-map (5a40)'),
    'bw_05a44':                          _offmap_load_guard(
        0xf9458908, 'x8', 'x8', 'x8 + 0xb10ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x8 skipped off-map (5a44)'),
    'bw_05a48':                          _offmap_pair_store_guard(
        0xa902d29f, 'c->x[20]', 'c->x[20] + 40', '0ull', 'c->x[20]',
        'f_7000005874 answered-0 node-init pair store via c->x[20] skipped off-map (5a48)'),
    'bw_05a4c':                          _offmap_store_guard(
        0xf9001e9f, 'c->x[20]', 'c->x[20] + 0x38ull', 'ST64', '0ull',
        'f_7000005874 answered-0 node-init store via c->x[20] skipped off-map (5a4c)'),
    'bw_05a54':                          _offmap_store_guard(
        0xf9000288, 'c->x[20]', 'c->x[20] + 0x0ull', 'ST64', 'x8',
        'f_7000005874 answered-0 node-init store via c->x[20] skipped off-map (5a54)'),
    'bw_05a58':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70000008e0(Cpu *c); c->x[30] = 0x7000005a5cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[11] = x11; c->x[20] = c->x[20]; f_70000008e0(c);',
        'f_70000008e0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5a58)'),
    'bw_05a64':                          _offmap_store_guard(
        0x3901ce9f, 'c->x[20]', 'c->x[20] + 0x73ull', 'ST8', '0u',
        'f_7000005874 answered-0 node-init store via c->x[20] skipped off-map (5a64)'),
    'bw_05a68':                          _offmap_pre_store_guard(
        0x38054d1f, 'x8', '84',
        'f_7000005874 answered-0 node-init pre-index store via x8 skipped off-map (5a68)', 'ST8', '0u'),
    'bw_05a6c':                          _offmap_store_guard(
        0xb9005289, 'c->x[20]', 'c->x[20] + 0x50ull', 'ST32', '(uint32_t)x9',
        'f_7000005874 answered-0 node-init store via c->x[20] skipped off-map (5a6c)'),
    'bw_05a7c':                          _offmap_pair_store_guard(
        0xa9042289, 'c->x[20]', 'c->x[20] + 64', 'x9', 'x8',
        'f_7000005874 answered-0 node-init pair store via c->x[20] skipped off-map (5a7c)'),
    'bw_05a88':                          _offmap_store_guard(
        0xf9000288, 'c->x[20]', 'c->x[20] + 0x0ull', 'ST64', 'x8',
        'f_7000005874 answered-0 node-init store via c->x[20] skipped off-map (5a88)'),
    'bw_05a8c':                          _offmap_pair_store_guard(
        0xa9055274, 'c->x[19]', 'c->x[19] + 80', 'c->x[20]', 'c->x[20]',
        'f_7000005874 answered-0 node-init pair store via c->x[19] skipped off-map (5a8c)'),
    'bw_05a98':                          _offmap_load_guard(
        0xf9402695, 'c->x[20]', 'c->x[21]', 'c->x[20] + 0x48ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (5a98)'),
    'bw_05aa4':                          _offmap_load_guard(
        0xb9405288, 'c->x[20]', 'x8', 'c->x[20] + 0x50ull', 'LD32',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (5aa4)'),
    'bw_05ac0':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0330(Cpu *c); c->x[30] = 0x7000005ac4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_70015a0330(c);',
        'f_70015a0330 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5ac0)'),
    'bw_05ac4':                          _offmap_store_guard(
        0x3838cabf, 'c->x[21]', 'c->x[21] + (uint64_t)(int64_t)(int32_t)c->x[24]', 'ST8', '0u',
        'f_7000005874 answered-0 node-init store via c->x[21] skipped off-map (5ac4)'),
    'bw_05ac8':                          _offmap_load_guard(
        0xf9401e88, 'c->x[20]', 'x8', 'c->x[20] + 0x38ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (5ac8)'),
    'bw_05ad0':                          _offmap_store_guard(
        0xf9001e96, 'c->x[20]', 'c->x[20] + 0x38ull', 'ST64', 'c->x[22]',
        'f_7000005874 answered-0 node-init store via c->x[20] skipped off-map (5ad0)'),
    'bw_05ad4':                          _offmap_load_guard(
        0xf94002c8, 'c->x[22]', 'x8', 'c->x[22] + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[22] skipped off-map (5ad4)'),
    'bw_05ad8':                          _offmap_store_guard(
        0xf90002d7, 'c->x[22]', 'c->x[22] + 0x0ull', 'ST64', 'c->x[23]',
        'f_7000005874 answered-0 node-init store via c->x[22] skipped off-map (5ad8)'),
    'bw_05adc':                          _offmap_pair_store_guard(
        0xa9025a88, 'c->x[20]', 'c->x[20] + 32', 'x8', 'c->x[22]',
        'f_7000005874 answered-0 node-init pair store via c->x[20] skipped off-map (5adc)'),
    'bw_05ae4':                          _offmap_store_guard(
        0xf9000517, 'x8', 'x8 + 0x8ull', 'ST64', 'c->x[23]',
        'f_7000005874 answered-0 node-init store via x8 skipped off-map (5ae4)'),
    'bw_05ae8':                          _offmap_load_guard(
        0xb9403268, 'c->x[19]', 'x8', 'c->x[19] + 0x30ull', 'LD32',
        'f_7000005874 answered-0 node-init load via c->x[19] skipped off-map (5ae8)'),
    'bw_05af0':                          _offmap_store_guard(
        0xb9003268, 'c->x[19]', 'c->x[19] + 0x30ull', 'ST32', '(uint32_t)x8',
        'f_7000005874 answered-0 node-init store via c->x[19] skipped off-map (5af0)'),
    'bw_05b10':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000002140(Cpu *c); c->x[30] = 0x7000005b14ull; c->x[0] = x0; c->x[8] = x8; f_7000002140(c);',
        'f_7000002140 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5b10)'),
    'bw_05b18':                          _offmap_load_guard(
        0xf9401289, 'c->x[20]', 'x9', 'c->x[20] + 0x20ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (5b18)'),
    'bw_05b1c':                          _offmap_store_guard(
        0xf9001e9f, 'c->x[20]', 'c->x[20] + 0x38ull', 'ST64', '0ull',
        'f_7000005874 answered-0 node-init store via c->x[20] skipped off-map (5b1c)'),
    'bw_05b24':                          _offmap_load_guard(
        0xf940168a, 'c->x[20]', 'c->x[10]', 'c->x[20] + 0x28ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (5b24)'),
    'bw_05b28':                          _offmap_store_guard(
        0xf900052a, 'x9', 'x9 + 0x8ull', 'ST64', 'c->x[10]',
        'f_7000005874 answered-0 node-init store via x9 skipped off-map (5b28)'),
    'bw_05b2c':                          _offmap_load_guard(
        0xf9401689, 'c->x[20]', 'x9', 'c->x[20] + 0x28ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[20] skipped off-map (5b2c)'),
    'bw_05b34':                          _offmap_load_guard(
        0xf94002ea, 'c->x[23]', 'c->x[10]', 'c->x[23] + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[23] skipped off-map (5b34)'),
    'bw_05b38':                          _offmap_store_guard(
        0xf900012a, 'x9', 'x9 + 0x0ull', 'ST64', 'c->x[10]',
        'f_7000005874 answered-0 node-init store via x9 skipped off-map (5b38)'),
    'bw_05b3c':                          _offmap_pair_store_guard(
        0xa9007eff, 'c->x[23]', 'c->x[23] + 0', '0ull', '0ull',
        'f_7000005874 answered-0 node-init pair store via c->x[23] skipped off-map (5b3c)'),
    'bw_05b40':                          _offmap_load_guard(
        0xb9401109, 'x8', 'x9', 'x8 + 0x10ull', 'LD32',
        'f_7000005874 answered-0 node-init load via x8 skipped off-map (5b40)'),
    'bw_05b48':                          _offmap_store_guard(
        0xb9001109, 'x8', 'x8 + 0x10ull', 'ST32', '(uint32_t)x9',
        'f_7000005874 answered-0 node-init store via x8 skipped off-map (5b48)'),
    'bw_05b54':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea3c44(Cpu *c); c->x[30] = 0x7000005b58ull; c->x[0] = x0; c->x[8] = x8; f_7000ea3c44(c);',
        'f_7000ea3c44 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5b54)'),
    'bw_05b64':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000005b68ull; c->x[8] = x8; c->x[9] = x9; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (5b64)'),
    'bw_05b84':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0520(Cpu *c); c->x[30] = 0x7000005b88ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[20] = c->x[20]; f_70015a0520(c);',
        'f_70015a0520 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5b84)'),
    'bw_05bb0':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea064c(Cpu *c); c->x[30] = 0x7000005bb4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea064c(c);',
        'f_7000ea064c skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5bb0)'),
    'bw_05bbc':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0530(Cpu *c); c->x[30] = 0x7000005bc0ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[11] = x11; c->x[20] = c->x[20]; f_70015a0530(c);',
        'f_70015a0530 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5bbc)'),
    'bw_05bd0':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea04a0(Cpu *c); c->x[30] = 0x7000005bd4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea04a0(c);',
        'f_7000ea04a0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5bd0)'),
    'bw_05bfc':                          _offmap_load_guard(
        0xf9400d6d, 'x11', 'c->x[13]', 'x11 + 0x18ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5bfc)'),
    'bw_05c0c':                          _offmap_load_guard(
        0xf9400d8e, 'c->x[12]', 'c->x[14]', 'c->x[12] + 0x18ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[12] skipped off-map (5c0c)'),
    'bw_05c20':                          _offmap_load_guard(
        0xf940056b, 'x11', 'x11', 'x11 + 0x8ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5c20)'),
    'bw_05c38':                          _offmap_load_guard(
        0xf940056b, 'x11', 'x11', 'x11 + 0x8ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5c38)'),
    'bw_05c5c':                          _offmap_load_guard(
        0xf9400900, 'x8', 'x0', 'x8 + 0x10ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x8 skipped off-map (5c5c)'),
    'bw_05c88':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x0 skipped off-map (5c88)'),
    'bw_05c8c':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x8 skipped off-map (5c8c)'),
    'bw_05c90':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000005c94ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[11] = x11; c->x[20] = c->x[20]; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (5c90)'),
    'bw_05ca8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c944(Cpu *c); c->x[30] = 0x7000005cacull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[11] = x11; c->x[20] = c->x[20]; f_7000e8c944(c);',
        'f_7000e8c944 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5ca8)'),
    'bw_05cc4':                          _offmap_store_guard(
        0xf9000d6c, 'x11', 'x11 + 0x18ull', 'ST64', 'c->x[12]',
        'f_7000005874 answered-0 node-init store via x11 skipped off-map (5cc4)'),
    'bw_05cd4':                          _offmap_load_guard(
        0xf9400149, 'c->x[10]', 'x9', 'c->x[10] + 0x0ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[10] skipped off-map (5cd4)'),
    'bw_05cd8':                          _offmap_store_guard(
        0xf9000148, 'c->x[10]', 'c->x[10] + 0x0ull', 'ST64', 'x8',
        'f_7000005874 answered-0 node-init store via c->x[10] skipped off-map (5cd8)'),
    'bw_05cdc':                          _offmap_pair_store_guard(
        0xa9002909, 'x8', 'x8 + 0', 'x9', 'c->x[10]',
        'f_7000005874 answered-0 node-init pair store via x8 skipped off-map (5cdc)'),
    'bw_05cf4':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea0704(Cpu *c); c->x[30] = 0x7000005cf8ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea0704(c);',
        'f_7000ea0704 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5cf4)'),
    'bw_05d08':                          _offmap_load_guard(
        0xf9400d6d, 'x11', 'c->x[13]', 'x11 + 0x18ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5d08)'),
    'bw_05d18':                          _offmap_load_guard(
        0xf9400d8e, 'c->x[12]', 'c->x[14]', 'c->x[12] + 0x18ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[12] skipped off-map (5d18)'),
    'bw_05d2c':                          _offmap_load_guard(
        0xf940056b, 'x11', 'x11', 'x11 + 0x8ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5d2c)'),
    'bw_05d48':                          _offmap_load_guard(
        0xf9400d6d, 'x11', 'c->x[13]', 'x11 + 0x18ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5d48)'),
    'bw_05d54':                          _offmap_load_guard(
        0xf940056b, 'x11', 'x11', 'x11 + 0x8ull', 'LD64',
        'f_7000005874 answered-0 node-init load via x11 skipped off-map (5d54)'),
    'bw_05d74':                          _offmap_load_guard(
        0xf9400d8c, 'c->x[12]', 'c->x[12]', 'c->x[12] + 0x18ull', 'LD64',
        'f_7000005874 answered-0 node-init load via c->x[12] skipped off-map (5d74)'),
    'bx_05d9c':                          _offmap_store_guard(
        0xb900301f, 'x0', 'x0 + 0x30ull', 'ST32', '0u',
        'f_7000005d80 answered-0 node-init store via x0 skipped off-map (5d9c)'),
    'bx_05da4':                          _offmap_pair_store_guard(
        0xa9025816, 'x0', 'x0 + 32', 'c->x[22]', 'c->x[22]',
        'f_7000005d80 answered-0 node-init pair store via x0 skipped off-map (5da4)'),
    'bx_05dac':                          _offmap_pair_store_guard(
        0xa903fc1f, 'x0', 'x0 + 56', '0ull', '0ull',
        'f_7000005d80 answered-0 node-init pair store via x0 skipped off-map (5dac)'),
    'bx_05db0':                          _offmap_load_guard(
        0xf9421ab5, 'c->x[21]', 'c->x[21]', 'c->x[21] + 0x430ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (5db0)'),
    'bx_05db4':                          _offmap_store_guard(
        0xf900241f, 'x0', 'x0 + 0x48ull', 'ST64', '0ull',
        'f_7000005d80 answered-0 node-init store via x0 skipped off-map (5db4)'),
    'bx_05db8':                          _offmap_load_guard(
        0xf94002a0, 'c->x[21]', 'x0', 'c->x[21] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (5db8)'),
    'bx_05dbc':                          _offmap_store_guard(
        0x7900a27f, 'c->x[19]', 'c->x[19] + 0x50ull', 'ST16', '0u',
        'f_7000005d80 answered-0 node-init store via c->x[19] skipped off-map (5dbc)'),
    'bx_05dc8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000006ef0(Cpu *c); c->x[30] = 0x7000005dccull; c->x[0] = x0; c->sp = sp_; f_7000006ef0(c);',
        'f_7000006ef0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5dc8)'),
    'bx_05dd8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a07c0(Cpu *c); c->x[30] = 0x7000005ddcull; c->x[0] = x0; f_70015a07c0(c);',
        'f_70015a07c0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5dd8)'),
    'bx_05de8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000007c20(Cpu *c); c->x[30] = 0x7000005decull; c->x[0] = x0; f_7000007c20(c);',
        'f_7000007c20 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5de8)'),
    'bx_05df4':                          _offmap_store_guard(
        0xf9002660, 'c->x[19]', 'c->x[19] + 0x48ull', 'ST64', 'x0',
        'f_7000005d80 answered-0 node-init store via c->x[19] skipped off-map (5df4)'),
    'bx_05e00':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a07d0(Cpu *c); c->x[30] = 0x7000005e04ull; c->x[0] = x0; f_70015a07d0(c);',
        'f_70015a07d0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5e00)'),
    'bx_05e04':                          _offmap_load_guard(
        0xf94002a8, 'c->x[21]', 'x8', 'c->x[21] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (5e04)'),
    'bx_05e14':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5e14)'),
    'bx_05e1c':                          _offmap_load_guard(
        0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (5e1c)'),
    'bx_05e20':                          _offmap_load_guard(
        0xf9447d29, 'x9', 'x9', 'x9 + 0x8f8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (5e20)'),
    'bx_05e2c':                          _offmap_load_guard(
        0xf94002ae, 'c->x[21]', 'c->x[14]', 'c->x[21] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (5e2c)'),
    'bx_05e30':                          _offmap_load_guard(
        0x7941b008, 'x0', 'x8', 'x0 + 0xd8ull', 'LD16',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5e30)'),
    'bx_05e3c':                          _offmap_load_guard(
        0xb9409008, 'x0', 'x8', 'x0 + 0x90ull', 'LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5e3c)'),
    'bx_05e50':                          _offmap_load_guard(
        0xf940740c, 'x0', 'x12', 'x0 + 0xe8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5e50)'),
    'bx_05e60':                          _offmap_load_guard(
        0xb980f408, 'x0', 'x8', 'x0 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5e60)'),
    'bx_05e68':                          _offmap_load_guard(
        0x3943700d, 'x0', 'c->x[13]', 'x0 + 0xdcull', 'LD8',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5e68)'),
    'bx_05e78':                          _offmap_load_guard(
        0xf9400d8d, 'x12', 'c->x[13]', 'x12 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (5e78)'),
    'bx_05e88':                          _offmap_load_guard(
        0x7940258b, 'x12', 'c->x[11]', 'x12 + 0x12ull', 'LD16',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (5e88)'),
    'bx_05e8c':                          _offmap_store_guard(
        0xf9000d88, 'x12', 'x12 + 0x18ull', 'ST64', 'x8',
        'f_7000005d80 answered-0 node-init store via x12 skipped off-map (5e8c)'),
    'bx_05e90':                          _offmap_load_guard(
        0xb980f40a, 'x0', 'x10', 'x0 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5e90)'),
    'bx_05e98':                          _offmap_ldp_load_guard(
        0xa940390f, 'x8', 'c->x[15]', 'c->x[14]',
        'x8 + 0',
        'f_7000005d80 answered-0 node-init ldp pair load via x8 skipped off-map (5e98)'),
    'bx_05eac':                          _offmap_store_guard(
        0xf90005ee, 'c->x[15]', 'c->x[15] + 0x8ull', 'ST64', 'c->x[14]',
        'f_7000005d80 answered-0 node-init store via c->x[15] skipped off-map (5eac)'),
    'bx_05eb0':                          _offmap_load_guard(
        0xf940050e, 'x8', 'c->x[14]', 'x8 + 0x8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (5eb0)'),
    'bx_05eb8':                          _offmap_load_guard(
        0xf940010f, 'x8', 'c->x[15]', 'x8 + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (5eb8)'),
    'bx_05ebc':                          _offmap_store_guard(
        0xf90001cf, 'c->x[14]', 'c->x[14] + 0x0ull', 'ST64', 'c->x[15]',
        'f_7000005d80 answered-0 node-init store via c->x[14] skipped off-map (5ebc)'),
    'bx_05ec0':                          _offmap_pair_store_guard(
        0xa9007d1f, 'x8', 'x8 + 0', '0ull', '0ull',
        'f_7000005d80 answered-0 node-init pair store via x8 skipped off-map (5ec0)'),
    'bx_05ec8':                          _offmap_load_guard(
        0xb940f00e, 'x0', 'c->x[14]', 'x0 + 0xf0ull', 'LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5ec8)'),
    'bx_05ecc':                          _offmap_load_guard(
        0xb940900f, 'x0', 'c->x[15]', 'x0 + 0x90ull', 'LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5ecc)'),
    'bx_05ed8':                          _offmap_store_guard(
        0xb900f00e, 'x0', 'x0 + 0xf0ull', 'ST32', '(uint32_t)c->x[14]',
        'f_7000005d80 answered-0 node-init store via x0 skipped off-map (5ed8)'),
    'bx_05edc':                          _offmap_load_guard(
        0xb9810c0e, 'x0', 'c->x[14]', 'x0 + 0x10cull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5edc)'),
    'bx_05ee8':                          _offmap_load_guard(
        0xf940010e, 'x8', 'c->x[14]', 'x8 + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (5ee8)'),
    'bx_05eec':                          _offmap_store_guard(
        0xf9000101, 'x8', 'x8 + 0x0ull', 'ST64', 'c->x[1]',
        'f_7000005d80 answered-0 node-init store via x8 skipped off-map (5eec)'),
    'bx_05ef0':                          _offmap_pair_store_guard(
        0xa900202e, 'c->x[1]', 'c->x[1] + 0', 'c->x[14]', 'x8',
        'f_7000005d80 answered-0 node-init pair store via c->x[1] skipped off-map (5ef0)'),
    'bx_05ef8':                          _offmap_store_guard(
        0xf90005c1, 'c->x[14]', 'c->x[14] + 0x8ull', 'ST64', 'c->x[1]',
        'f_7000005d80 answered-0 node-init store via c->x[14] skipped off-map (5ef8)'),
    'bx_05efc':                          _offmap_load_guard(
        0xb9410808, 'x0', 'x8', 'x0 + 0x108ull', 'LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5efc)'),
    'bx_05f04':                          _offmap_store_guard(
        0xb9010808, 'x0', 'x0 + 0x108ull', 'ST32', '(uint32_t)x8',
        'f_7000005d80 answered-0 node-init store via x0 skipped off-map (5f04)'),
    'bx_05f1c':                          _offmap_pre_store_guard(
        0xf80a8d1f, 'x8', '168',
        'f_7000005d80 answered-0 node-init pre-index store via x8 skipped off-map (5f1c)'),
    'bx_05f20':                          _offmap_store_guard(
        0xf9000d0b, 'x8', 'x8 + 0x18ull', 'ST64', 'c->x[11]',
        'f_7000005d80 answered-0 node-init store via x8 skipped off-map (5f20)'),
    'bx_05f28':                          _offmap_store_guard(
        0xb900111f, 'x8', 'x8 + 0x10ull', 'ST32', '0u',
        'f_7000005d80 answered-0 node-init store via x8 skipped off-map (5f28)'),
    'bx_05f2c':                          _offmap_store_guard(
        0xf900051f, 'x8', 'x8 + 0x8ull', 'ST64', '0ull',
        'f_7000005d80 answered-0 node-init store via x8 skipped off-map (5f2c)'),
    'bx_05f30':                          _offmap_store_guard(
        0x7900210b, 'x8', 'x8 + 0x10ull', 'ST16', '(uint32_t)c->x[11]',
        'f_7000005d80 answered-0 node-init store via x8 skipped off-map (5f30)'),
    'bx_05f34':                          _offmap_load_guard(
        0xb980f40b, 'x0', 'c->x[11]', 'x0 + 0xf4ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5f34)'),
    'bx_05f3c':                          _offmap_load_guard(
        0xf94002aa, 'c->x[21]', 'x10', 'c->x[21] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (5f3c)'),
    'bx_05f44':                          _offmap_store_guard(
        0xf90002a8, 'c->x[21]', 'c->x[21] + 0x0ull', 'ST64', 'x8',
        'f_7000005d80 answered-0 node-init store via c->x[21] skipped off-map (5f44)'),
    'bx_05f48':                          _offmap_pair_store_guard(
        0xa900550a, 'x8', 'x8 + 0', 'x10', 'c->x[21]',
        'f_7000005d80 answered-0 node-init pair store via x8 skipped off-map (5f48)'),
    'bx_05f50':                          _offmap_store_guard(
        0xf9000548, 'x10', 'x10 + 0x8ull', 'ST64', 'x8',
        'f_7000005d80 answered-0 node-init store via x10 skipped off-map (5f50)'),
    'bx_05f54':                          _offmap_load_guard(
        0xb940f008, 'x0', 'x8', 'x0 + 0xf0ull', 'LD32',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5f54)'),
    'bx_05f5c':                          _offmap_store_guard(
        0xb900f008, 'x0', 'x0 + 0xf0ull', 'ST32', '(uint32_t)x8',
        'f_7000005d80 answered-0 node-init store via x0 skipped off-map (5f5c)'),
    'bx_05f60':                          _offmap_load_guard(
        0x7941b408, 'x0', 'x8', 'x0 + 0xdaull', 'LD16',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (5f60)'),
    'bx_05f64':                          _offmap_store_guard(
        0x79002188, 'x12', 'x12 + 0x10ull', 'ST16', '(uint32_t)x8',
        'f_7000005d80 answered-0 node-init store via x12 skipped off-map (5f64)'),
    'bx_05f68':                          _offmap_load_guard(
        0x79402588, 'x12', 'x8', 'x12 + 0x12ull', 'LD16',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (5f68)'),
    'bx_05f80':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70000075f4(Cpu *c); c->x[30] = 0x7000005f84ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[12] = x12; f_70000075f4(c);',
        'f_70000075f4 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5f80)'),
    'bx_05f8c':                          _offmap_load_guard(
        0xf9422e94, 'c->x[20]', 'c->x[20]', 'c->x[20] + 0x458ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[20] skipped off-map (5f8c)'),
    'bx_05f90':                          _offmap_store_guard(
        0xf9002275, 'c->x[19]', 'c->x[19] + 0x40ull', 'ST64', 'c->x[21]',
        'f_7000005d80 answered-0 node-init store via c->x[19] skipped off-map (5f90)'),
    'bx_05f94':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[20] skipped off-map (5f94)'),
    'bx_05f98':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (5f98)'),
    'bx_05f9c':                          _offmap_load_guard(
        0xf9412929, 'x9', 'x9', 'x9 + 0x250ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (5f9c)'),
    'bx_05fa8':                          _offmap_load_guard(
        0xf9401ea9, 'c->x[21]', 'x9', 'c->x[21] + 0x38ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (5fa8)'),
    'bx_05fb4':                          _offmap_store_guard(
        0xf9001eb6, 'c->x[21]', 'c->x[21] + 0x38ull', 'ST64', 'c->x[22]',
        'f_7000005d80 answered-0 node-init store via c->x[21] skipped off-map (5fb4)'),
    'bx_05fb8':                          _offmap_load_guard(
        0xf94002c9, 'c->x[22]', 'x9', 'c->x[22] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[22] skipped off-map (5fb8)'),
    'bx_05fbc':                          _offmap_store_guard(
        0xf90002c8, 'c->x[22]', 'c->x[22] + 0x0ull', 'ST64', 'x8',
        'f_7000005d80 answered-0 node-init store via c->x[22] skipped off-map (5fbc)'),
    'bx_05fc0':                          _offmap_pair_store_guard(
        0xa9025aa9, 'c->x[21]', 'c->x[21] + 32', 'x9', 'c->x[22]',
        'f_7000005d80 answered-0 node-init pair store via c->x[21] skipped off-map (5fc0)'),
    'bx_05fc8':                          _offmap_store_guard(
        0xf9000528, 'x9', 'x9 + 0x8ull', 'ST64', 'x8',
        'f_7000005d80 answered-0 node-init store via x9 skipped off-map (5fc8)'),
    'bx_05fcc':                          _offmap_load_guard(
        0xb9403268, 'c->x[19]', 'x8', 'c->x[19] + 0x30ull', 'LD32',
        'f_7000005d80 answered-0 node-init load via c->x[19] skipped off-map (5fcc)'),
    'bx_05fd4':                          _offmap_store_guard(
        0xb9003268, 'c->x[19]', 'c->x[19] + 0x30ull', 'ST32', '(uint32_t)x8',
        'f_7000005d80 answered-0 node-init store via c->x[19] skipped off-map (5fd4)'),
    'bx_05fd8':                          _offmap_load_guard(
        0xf9402268, 'c->x[19]', 'x8', 'c->x[19] + 0x40ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[19] skipped off-map (5fd8)'),
    'bx_05fdc':                          _offmap_store_guard(
        0xf9001e68, 'c->x[19]', 'c->x[19] + 0x38ull', 'ST64', 'x8',
        'f_7000005d80 answered-0 node-init store via c->x[19] skipped off-map (5fdc)'),
    'bx_05ffc':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000002140(Cpu *c); c->x[30] = 0x7000006000ull; c->x[0] = x0; c->x[8] = x8; f_7000002140(c);',
        'f_7000002140 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (5ffc)'),
    'bx_06008':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x700000600cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (6008)'),
    'bx_06010':                          _offmap_load_guard(
        0xf9412908, 'x8', 'x8', 'x8 + 0x250ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (6010)'),
    'bx_06014':                          _offmap_load_guard(
        0xf9400289, 'c->x[20]', 'x9', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[20] skipped off-map (6014)'),
    'bx_06018':                          _offmap_load_guard(
        0xf9400d29, 'x9', 'x9', 'x9 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (6018)'),
    'bx_0602c':                          _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x7000006030ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x9 is off-map or unmapped (602c)', cond='x9', w=0xd63f0120),
    'bx_06030':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[20] skipped off-map (6030)'),
    'bx_06034':                          _offmap_load_guard(
        0xf9400d08, 'x8', 'x8', 'x8 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (6034)'),
    'bx_06040':                          _offmap_load_guard(
        0xf9400697, 'c->x[20]', 'c->x[23]', 'c->x[20] + 0x8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[20] skipped off-map (6040)'),
    'bx_06048':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x700000604cull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (6048)'),
    'bx_0604c':                          _offmap_load_guard(
        0xf9400689, 'c->x[20]', 'x9', 'c->x[20] + 0x8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[20] skipped off-map (604c)'),
    'bx_06058':                          _offmap_load_guard(
        0x39400128, 'x9', 'x8', 'x9 + 0x0ull', 'LD8',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (6058)'),
    'bx_06070':                          _offmap_load_guard(
        0x3868692a, 'x9', 'x10', 'x9 + x8', 'LD8',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (6070)'),
    'bx_06080':                          _offmap_load_guard(
        0xf94012aa, 'c->x[21]', 'x10', 'c->x[21] + 0x20ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (6080)'),
    'bx_06084':                          _offmap_store_guard(
        0xf9001ebf, 'c->x[21]', 'c->x[21] + 0x38ull', 'ST64', '0ull',
        'f_7000005d80 answered-0 node-init store via c->x[21] skipped off-map (6084)'),
    'bx_0608c':                          _offmap_load_guard(
        0xf94016ab, 'c->x[21]', 'c->x[11]', 'c->x[21] + 0x28ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (608c)'),
    'bx_06090':                          _offmap_store_guard(
        0xf900054b, 'x10', 'x10 + 0x8ull', 'ST64', 'c->x[11]',
        'f_7000005d80 answered-0 node-init store via x10 skipped off-map (6090)'),
    'bx_06094':                          _offmap_load_guard(
        0xf94016aa, 'c->x[21]', 'x10', 'c->x[21] + 0x28ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[21] skipped off-map (6094)'),
    'bx_0609c':                          _offmap_load_guard(
        0xf940010b, 'x8', 'c->x[11]', 'x8 + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (609c)'),
    'bx_060a0':                          _offmap_store_guard(
        0xf900014b, 'x10', 'x10 + 0x0ull', 'ST64', 'c->x[11]',
        'f_7000005d80 answered-0 node-init store via x10 skipped off-map (60a0)'),
    'bx_060a4':                          _offmap_pair_store_guard(
        0xa9007d1f, 'x8', 'x8 + 0', '0ull', '0ull',
        'f_7000005d80 answered-0 node-init pair store via x8 skipped off-map (60a4)'),
    'bx_060a8':                          _offmap_load_guard(
        0xb940112a, 'x9', 'x10', 'x9 + 0x10ull', 'LD32',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (60a8)'),
    'bx_060b0':                          _offmap_store_guard(
        0xb900112a, 'x9', 'x9 + 0x10ull', 'ST32', '(uint32_t)x10',
        'f_7000005d80 answered-0 node-init store via x9 skipped off-map (60b0)'),
    'bx_060bc':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea3c44(Cpu *c); c->x[30] = 0x70000060c0ull; c->x[0] = x0; c->x[8] = x8; f_7000ea3c44(c);',
        'f_7000ea3c44 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (60bc)'),
    'bx_060cc':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x70000060d0ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (60cc)'),
    'bx_060ec':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0520(Cpu *c); c->x[30] = 0x70000060f0ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_70015a0520(c);',
        'f_70015a0520 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (60ec)'),
    'bx_06110':                          _offmap_store_guard(
        0xf9000fa9, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'x9',
        'f_7000005d80 answered-0 node-init store via c->x[29] skipped off-map (6110)'),
    'bx_06124':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea064c(Cpu *c); c->x[30] = 0x7000006128ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea064c(c);',
        'f_7000ea064c skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (6124)'),
    'bx_06130':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0530(Cpu *c); c->x[30] = 0x7000006134ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[12] = x12; f_70015a0530(c);',
        'f_70015a0530 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (6130)'),
    'bx_06140':                          _offmap_store_guard(
        0xf9000fa9, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'x9',
        'f_7000005d80 answered-0 node-init store via c->x[29] skipped off-map (6140)'),
    'bx_0614c':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea04a0(Cpu *c); c->x[30] = 0x7000006150ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea04a0(c);',
        'f_7000ea04a0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (614c)'),
    'bx_06160':                          _offmap_load_guard(
        0xf9400fa9, 'c->x[29]', 'x9', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[29] skipped off-map (6160)'),
    'bx_06170':                          _offmap_store_guard(
        0xf9000fa9, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'x9',
        'f_7000005d80 answered-0 node-init store via c->x[29] skipped off-map (6170)'),
    'bx_06184':                          _offmap_load_guard(
        0xf9400d8d, 'x12', 'c->x[13]', 'x12 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (6184)'),
    'bx_06194':                          _offmap_load_guard(
        0xf9400d2e, 'x9', 'c->x[14]', 'x9 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (6194)'),
    'bx_061a8':                          _offmap_load_guard(
        0xf940058c, 'x12', 'x12', 'x12 + 0x8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (61a8)'),
    'bx_061c0':                          _offmap_load_guard(
        0xf940058c, 'x12', 'x12', 'x12 + 0x8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (61c0)'),
    'bx_061d4':                          _offmap_store_guard(
        0xf9000fa9, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'x9',
        'f_7000005d80 answered-0 node-init store via c->x[29] skipped off-map (61d4)'),
    'bx_061ec':                          _offmap_load_guard(
        0xf9400900, 'x8', 'x0', 'x8 + 0x10ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (61ec)'),
    'bx_06218':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x0 skipped off-map (6218)'),
    'bx_0621c':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x8 skipped off-map (621c)'),
    'bx_06220':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000006224ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[12] = x12; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (6220)'),
    'bx_06224':                          _offmap_load_guard(
        0xf9400fa9, 'c->x[29]', 'x9', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[29] skipped off-map (6224)'),
    'bx_06238':                          _offmap_store_guard(
        0xf9000fa9, 'c->x[29]', 'c->x[29] + 0x18ull', 'ST64', 'x9',
        'f_7000005d80 answered-0 node-init store via c->x[29] skipped off-map (6238)'),
    'bx_06244':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c944(Cpu *c); c->x[30] = 0x7000006248ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[12] = x12; f_7000e8c944(c);',
        'f_7000e8c944 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (6244)'),
    'bx_0624c':                          _offmap_load_guard(
        0xf9400fa9, 'c->x[29]', 'x9', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[29] skipped off-map (624c)'),
    'bx_06268':                          _offmap_store_guard(
        0xf9000d8d, 'x12', 'x12 + 0x18ull', 'ST64', 'c->x[13]',
        'f_7000005d80 answered-0 node-init store via x12 skipped off-map (6268)'),
    'bx_06278':                          _offmap_load_guard(
        0xf94001aa, 'c->x[13]', 'x10', 'c->x[13] + 0x0ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[13] skipped off-map (6278)'),
    'bx_0627c':                          _offmap_store_guard(
        0xf90001a8, 'c->x[13]', 'c->x[13] + 0x0ull', 'ST64', 'x8',
        'f_7000005d80 answered-0 node-init store via c->x[13] skipped off-map (627c)'),
    'bx_06280':                          _offmap_pair_store_guard(
        0xa900350a, 'x8', 'x8 + 0', 'x10', 'c->x[13]',
        'f_7000005d80 answered-0 node-init pair store via x8 skipped off-map (6280)'),
    'bx_06294':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea0704(Cpu *c); c->x[30] = 0x7000006298ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; f_7000ea0704(c);',
        'f_7000ea0704 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (6294)'),
    'bx_062a8':                          _offmap_load_guard(
        0xf9400d8d, 'x12', 'c->x[13]', 'x12 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (62a8)'),
    'bx_062b8':                          _offmap_load_guard(
        0xf9400d2e, 'x9', 'c->x[14]', 'x9 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (62b8)'),
    'bx_062cc':                          _offmap_load_guard(
        0xf940058c, 'x12', 'x12', 'x12 + 0x8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (62cc)'),
    'bx_062e8':                          _offmap_load_guard(
        0xf9400d8d, 'x12', 'c->x[13]', 'x12 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (62e8)'),
    'bx_062f4':                          _offmap_load_guard(
        0xf940058c, 'x12', 'x12', 'x12 + 0x8ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x12 skipped off-map (62f4)'),
    'bx_06314':                          _offmap_load_guard(
        0xf9400d2d, 'x9', 'c->x[13]', 'x9 + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via x9 skipped off-map (6314)'),
    'bx_0631c':                          _offmap_load_guard(
        0xf9400fa9, 'c->x[29]', 'x9', 'c->x[29] + 0x18ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[29] skipped off-map (631c)'),
    'bx_0632c':                          _offmap_load_guard(
        0xf9422c21, 'c->x[1]', 'c->x[1]', 'c->x[1] + 0x458ull', 'LD64',
        'f_7000005d80 answered-0 node-init load via c->x[1] skipped off-map (632c)'),
    'bx_06330':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e92140(Cpu *c); c->x[30] = 0x7000006334ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; f_7000e92140(c);',
        'f_7000e92140 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (6330)'),
    'by_00908':                          _offmap_store_guard(
        0xf9000008, 'x0', 'x0 + 0x0ull', 'ST64', 'x8',
        'f_70000008e0 answered-0 registry-tail store via x0 skipped off-map (908)'),
    'by_00910':                          _offmap_pair_store_guard(
        0xa9017c1f, 'x0', 'x0 + 16', '0ull', '0ull',
        'f_70000008e0 answered-0 registry-tail pair store via x0 skipped off-map (910)'),
    'by_00918':                          _offmap_pre_store_guard(
        0xf8008eff, 'c->x[23]', '8',
        'f_70000008e0 answered-0 registry-tail pre-index store via c->x[23] skipped off-map (918)'),
    'by_0091c':                          _offmap_load_guard(
        0xf9421908, 'x8', 'x8', 'x8 + 0x430ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (91c)'),
    'by_00920':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (920)'),
    'by_00950':                          _offmap_load_guard(
        0xf947c108, 'x8', 'x8', 'x8 + 0xf80ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (950)'),
    'by_00954':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (954)'),
    'by_0095c':                          _offmap_load_guard(
        0xb9408900, 'x8', 'x0', 'x8 + 0x88ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (95c)'),
    'by_00960':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_700159fee0(Cpu *c); c->x[30] = 0x7000000964ull; c->x[0] = x0; c->x[8] = x8; f_700159fee0(c);',
        'f_700159fee0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (960)'),
    'by_00968':                          _offmap_load_guard(
        0xf9405808, 'x0', 'x8', 'x0 + 0xb0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x0 skipped off-map (968)'),
    'by_00984':                          _offmap_load_guard(
        0xb9406289, 'x20', 'x9', 'x20 + 0x60ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (984)'),
    'by_0098c':                          _offmap_load_guard(
        0xf9400289, 'x20', 'x9', 'x20 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (98c)'),
    'by_00994':                          _offmap_load_guard(
        0xf9404529, 'x9', 'x9', 'x9 + 0x88ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (994)'),
    'by_00998':                          _offmap_load_guard(
        0xf944754a, 'x10', 'x10', 'x10 + 0x8e8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x10 skipped off-map (998)'),
    'by_009a4':                          _offmap_load_guard(
        0xb9409289, 'x20', 'x9', 'x20 + 0x90ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (9a4)'),
    'by_009ac':                          _offmap_load_guard(
        0xf9401e8b, 'x20', 'c->x[11]', 'x20 + 0x38ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (9ac)'),
    'by_009b4':                          _offmap_load_guard(
        0xf9402289, 'x20', 'x9', 'x20 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (9b4)'),
    'by_009e4':                          _offmap_store_guard(
        0xf90002f5, 'c->x[23]', 'c->x[23] + 0x0ull', 'ST64', 'c->x[21]',
        'f_70000008e0 answered-0 registry-tail store via c->x[23] skipped off-map (9e4)'),
    'by_009e8':                          _offmap_load_guard(
        0x7941b2a8, 'c->x[21]', 'x8', 'c->x[21] + 0xd8ull', 'LD16',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (9e8)'),
    'by_009f8':                          _offmap_pre_load_guard(
        0xf8478d48, 'x10', '120', 'x8',
        'f_70000008e0 answered-0 registry-tail pre-index load via x10 skipped off-map (9f8)'),
    'by_009fc':                          _offmap_load_guard(
        0xb9801549, 'x10', 'x9', 'x10 + 0x14ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_70000008e0 answered-0 registry-tail load via x10 skipped off-map (9fc)'),
    'by_00a04':                          _offmap_store_guard(
        0xf9000149, 'x10', 'x10 + 0x0ull', 'ST64', 'x9',
        'f_70000008e0 answered-0 registry-tail store via x10 skipped off-map (a04)'),
    'by_00a08':                          _offmap_pair_store_guard(
        0xa9002928, 'x9', 'x9 + 0', 'x8', 'x10',
        'f_70000008e0 answered-0 registry-tail pair store via x9 skipped off-map (a08)'),
    'by_00a10':                          _offmap_store_guard(
        0xf9000509, 'x8', 'x8 + 0x8ull', 'ST64', 'x9',
        'f_70000008e0 answered-0 registry-tail store via x8 skipped off-map (a10)'),
    'by_00a14':                          _offmap_load_guard(
        0xb9408aa8, 'c->x[21]', 'x8', 'c->x[21] + 0x88ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (a14)'),
    'by_00a1c':                          _offmap_store_guard(
        0xb9008aa8, 'c->x[21]', 'c->x[21] + 0x88ull', 'ST32', '(uint32_t)x8',
        'f_70000008e0 answered-0 registry-tail store via c->x[21] skipped off-map (a1c)'),
    'by_00a44':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0530(Cpu *c); c->nzcv = fnz_nz(&F); c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; __attribute__((musttail)) return f_70015a0530(c);',
        'TAIL thunk jump b #0x70015a0530 after the epilogue on the answered-0 walk; the dead 0 answer must carry return -- the block it ends has no fall-through (the b skips the 0xa48 block), the guard block returning 0 is exactly where the guarded caller (bt_0aa9c spill, mc_04fa8 twin chain) expects the answered-0 (a44)',
        answer='c->x[0] = 0ull; return', w=0x14567ebb),
    'by_00a54':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0520(Cpu *c); c->x[30] = 0x7000000a58ull; c->x[0] = x0; c->x[8] = x8; f_70015a0520(c);',
        'f_70015a0520 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (a54)'),
    'by_00a60':                          _offmap_load_guard(
        0xb9800128, 'x9', 'x8', 'x9 + 0x0ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (a60)'),
    'by_00a68':                          _offmap_load_guard(
        0xf9400534, 'x9', 'x20', 'x9 + 0x8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (a68)'),
    'by_00a78':                          _offmap_load_guard(
        0xf9447718, 'c->x[24]', 'c->x[24]', 'c->x[24] + 0x8e8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[24] skipped off-map (a78)'),
    'by_00a7c':                          _offmap_load_guard(
        0xf9400288, 'x20', 'x8', 'x20 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (a7c)'),
    'by_00a84':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (a84)'),
    'by_00a88':                          _offmap_load_guard(
        0xf9404508, 'x8', 'x8', 'x8 + 0x88ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (a88)'),
    'by_00a98':                          _offmap_load_guard(
        0xb9409109, 'x8', 'x9', 'x8 + 0x90ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (a98)'),
    'by_00a9c':                          _offmap_load_guard(
        0xf9401d08, 'x8', 'x8', 'x8 + 0x38ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (a9c)'),
    'by_00ab0':                          _offmap_load_guard(
        0xf940214a, 'x10', 'x10', 'x10 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x10 skipped off-map (ab0)'),
    'by_00ac8':                          _offmap_pre_load_guard(
        0xb8864f3c, 'c->x[25]', '100', 'c->x[28]',
        'f_70000008e0 answered-0 registry-tail pre-index load via c->x[25] skipped off-map (ac8)'),
    'by_00af4':                          _offmap_load_guard(
        0xf9400129, 'x9', 'x9', 'x9 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (af4)'),
    'by_00af8':                          _offmap_load_guard(
        0xf9404529, 'x9', 'x9', 'x9 + 0x88ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (af8)'),
    'by_00b08':                          _offmap_load_guard(
        0xb940912a, 'x9', 'x10', 'x9 + 0x90ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (b08)'),
    'by_00b0c':                          _offmap_load_guard(
        0xf9401d29, 'x9', 'x9', 'x9 + 0x38ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (b0c)'),
    'by_00b20':                          _offmap_load_guard(
        0xf940216b, 'c->x[11]', 'c->x[11]', 'c->x[11] + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[11] skipped off-map (b20)'),
    'by_00b3c':                          _offmap_load_guard(
        0xf9400529, 'x9', 'x9', 'x9 + 0x8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (b3c)'),
    'by_00b68':                          _offmap_load_guard(
        0xf9402108, 'x8', 'x8', 'x8 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (b68)'),
    'by_00b88':                          _offmap_pre_load_guard(
        0xb8864f3c, 'c->x[25]', '100', 'c->x[28]',
        'f_70000008e0 answered-0 registry-tail pre-index load via c->x[25] skipped off-map (b88)'),
    'by_00bb0':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0530(Cpu *c); c->x[30] = 0x7000000bb4ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; f_70015a0530(c);',
        'f_70015a0530 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (bb0)'),
    'by_00bc4':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0520(Cpu *c); c->x[30] = 0x7000000bc8ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; f_70015a0520(c);',
        'f_70015a0520 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (bc4)'),
    'by_00bf4':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0520(Cpu *c); c->x[30] = 0x7000000bf8ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; f_70015a0520(c);',
        'f_70015a0520 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (bf4)'),
    'by_00bf8':                          _offmap_load_guard(
        0xf9400315, 'c->x[24]', 'c->x[21]', 'c->x[24] + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[24] skipped off-map (bf8)'),
    'by_00c1c':                          _offmap_load_guard(
        0xb9800128, 'x9', 'x8', 'x9 + 0x0ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (c1c)'),
    'by_00c24':                          _offmap_load_guard(
        0xf9400535, 'x9', 'c->x[21]', 'x9 + 0x8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (c24)'),
    'by_00c34':                          _offmap_load_guard(
        0xf94002b4, 'c->x[21]', 'x20', 'c->x[21] + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (c34)'),
    'by_00c38':                          _offmap_load_guard(
        0xf9400289, 'x20', 'x9', 'x20 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (c38)'),
    'by_00c3c':                          _offmap_load_guard(
        0xf9404529, 'x9', 'x9', 'x9 + 0x88ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (c3c)'),
    'by_00c48':                          _offmap_load_guard(
        0xb940928a, 'x20', 'x10', 'x20 + 0x90ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (c48)'),
    'by_00c50':                          _offmap_load_guard(
        0xf9401e89, 'x20', 'x9', 'x20 + 0x38ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (c50)'),
    'by_00c58':                          _offmap_load_guard(
        0xf940228b, 'x20', 'c->x[11]', 'x20 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (c58)'),
    'by_00c74':                          _offmap_pre_load_guard(
        0xb8864f29, 'c->x[25]', '100', 'x9',
        'f_70000008e0 answered-0 registry-tail pre-index load via c->x[25] skipped off-map (c74)'),
    'by_00ca0':                          _offmap_load_guard(
        0xf940028a, 'x20', 'x10', 'x20 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (ca0)'),
    'by_00ca4':                          _offmap_load_guard(
        0xf940454a, 'x10', 'x10', 'x10 + 0x88ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x10 skipped off-map (ca4)'),
    'by_00cb0':                          _offmap_load_guard(
        0xb940928b, 'x20', 'c->x[11]', 'x20 + 0x90ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (cb0)'),
    'by_00cb8':                          _offmap_load_guard(
        0xf9401e8a, 'x20', 'x10', 'x20 + 0x38ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (cb8)'),
    'by_00cc0':                          _offmap_load_guard(
        0xf940228c, 'x20', 'c->x[12]', 'x20 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (cc0)'),
    'by_00ce0':                          _offmap_load_guard(
        0xf940054a, 'x10', 'x10', 'x10 + 0x8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x10 skipped off-map (ce0)'),
    'by_00d08':                          _offmap_load_guard(
        0xf9402289, 'x20', 'x9', 'x20 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (d08)'),
    'by_00d28':                          _offmap_pre_load_guard(
        0xb8864f29, 'c->x[25]', '100', 'x9',
        'f_70000008e0 answered-0 registry-tail pre-index load via c->x[25] skipped off-map (d28)'),
    'by_00d48':                          _offmap_store_guard(
        0xf9000314, 'c->x[24]', 'c->x[24] + 0x0ull', 'ST64', 'x20',
        'f_70000008e0 answered-0 registry-tail store via c->x[24] skipped off-map (d48)'),
    'by_00d58':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0530(Cpu *c); c->x[30] = 0x7000000d5cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; f_70015a0530(c);',
        'f_70015a0530 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (d58)'),
    'by_00d5c':                          _offmap_store_guard(
        0xf90002f5, 'c->x[23]', 'c->x[23] + 0x0ull', 'ST64', 'c->x[21]',
        'f_70000008e0 answered-0 registry-tail store via c->x[23] skipped off-map (d5c)'),
    'by_00d74':                          _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x7000000d78ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x9 is off-map or unmapped (d74)', cond='x9', w=0xd63f0120),
    'by_00d84':                          _offmap_load_guard(
        0xf9402289, 'x20', 'x9', 'x20 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (d84)'),
    'by_00da8':                          _offmap_blr_guard(
        'c->pc = x10; c->x[30] = 0x7000000dacull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x10 is off-map or unmapped (da8)', cond='x10', w=0xd63f0140),
    'by_00db8':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (db8)'),
    'by_00dbc':                          _offmap_load_guard(
        0xf9404508, 'x8', 'x8', 'x8 + 0x88ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (dbc)'),
    'by_00dc0':                          _offmap_load_guard(
        0xf9447529, 'x9', 'x9', 'x9 + 0x8e8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (dc0)'),
    'by_00dd4':                          _offmap_load_guard(
        0xb940928b, 'x20', 'c->x[11]', 'x20 + 0x90ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (dd4)'),
    'by_00dd8':                          _offmap_load_guard(
        0xf9401e8a, 'x20', 'x10', 'x20 + 0x38ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (dd8)'),
    'by_00ddc':                          _offmap_load_guard(
        0xf9447508, 'x8', 'x8', 'x8 + 0x8e8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (ddc)'),
    'by_00de8':                          _offmap_load_guard(
        0xf940228c, 'x20', 'c->x[12]', 'x20 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (de8)'),
    'by_00e00':                          _offmap_load_guard(
        0xb9400329, 'c->x[25]', 'x9', 'c->x[25] + 0x0ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via c->x[25] skipped off-map (e00)'),
    'by_00e04':                          _offmap_load_guard(
        0xf9447508, 'x8', 'x8', 'x8 + 0x8e8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (e04)'),
    'by_00e1c':                          _offmap_load_guard(
        0xb94062a8, 'c->x[21]', 'x8', 'c->x[21] + 0x60ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (e1c)'),
    'by_00e24':                          _offmap_load_guard(
        0xf94002a8, 'c->x[21]', 'x8', 'c->x[21] + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (e24)'),
    'by_00e2c':                          _offmap_load_guard(
        0xf9404508, 'x8', 'x8', 'x8 + 0x88ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (e2c)'),
    'by_00e30':                          _offmap_load_guard(
        0xf9447529, 'x9', 'x9', 'x9 + 0x8e8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (e30)'),
    'by_00e3c':                          _offmap_load_guard(
        0xb94092a9, 'c->x[21]', 'x9', 'c->x[21] + 0x90ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (e3c)'),
    'by_00e48':                          _offmap_load_guard(
        0xf9401eaa, 'c->x[21]', 'x10', 'c->x[21] + 0x38ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (e48)'),
    'by_00e50':                          _offmap_load_guard(
        0xf94022a8, 'c->x[21]', 'x8', 'c->x[21] + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (e50)'),
    'by_00e70':                          _offmap_store_guard(
        0xf9000315, 'c->x[24]', 'c->x[24] + 0x0ull', 'ST64', 'c->x[21]',
        'f_70000008e0 answered-0 registry-tail store via c->x[24] skipped off-map (e70)'),
    'by_00e88':                          _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x7000000e8cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x9 is off-map or unmapped (e88)', cond='x9', w=0xd63f0120),
    'by_00e9c':                          _offmap_load_guard(
        0xf940228a, 'x20', 'x10', 'x20 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (e9c)'),
    'by_00eb0':                          _offmap_load_guard(
        0xf9402289, 'x20', 'x9', 'x20 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x20 skipped off-map (eb0)'),
    'by_00ec8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea2fe4(Cpu *c); c->x[30] = 0x7000000eccull; c->x[0] = x0; c->x[21] = c->x[21]; f_7000ea2fe4(c);',
        'f_7000ea2fe4 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (ec8)'),
    'by_00ee8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea2fe4(Cpu *c); c->x[30] = 0x7000000eecull; c->x[0] = x0; c->x[20] = x20; c->x[21] = c->x[21]; f_7000ea2fe4(c);',
        'f_7000ea2fe4 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (ee8)'),
    'by_00f08':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000000f0cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (f08)'),
    'by_00f18':                          _offmap_load_guard(
        0xf9402129, 'x9', 'x9', 'x9 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (f18)'),
    'by_00f34':                          _offmap_blr_guard(
        'c->pc = x9; c->x[30] = 0x7000000f38ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x9 is off-map or unmapped (f34)', cond='x9', w=0xd63f0120),
    'by_00f40':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (f40)'),
    'by_00f44':                          _offmap_load_guard(
        0xf9404508, 'x8', 'x8', 'x8 + 0x88ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (f44)'),
    'by_00f54':                          _offmap_load_guard(
        0xb940910a, 'x8', 'x10', 'x8 + 0x90ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (f54)'),
    'by_00f58':                          _offmap_load_guard(
        0xf9401d09, 'x8', 'x9', 'x8 + 0x38ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (f58)'),
    'by_00f68':                          _offmap_load_guard(
        0xf940216b, 'c->x[11]', 'c->x[11]', 'c->x[11] + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[11] skipped off-map (f68)'),
    'by_00f7c':                          _offmap_load_guard(
        0xf9402108, 'x8', 'x8', 'x8 + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x8 skipped off-map (f7c)'),
    'by_00f98':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000000f9cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[20] = x20; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (f98)'),
    'by_00fc4':                          _offmap_load_guard(
        0xb9800128, 'x9', 'x8', 'x9 + 0x0ull', '(uint64_t)(int64_t)(int32_t)LD32',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (fc4)'),
    'by_00fcc':                          _offmap_load_guard(
        0xf9400535, 'x9', 'c->x[21]', 'x9 + 0x8ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via x9 skipped off-map (fcc)'),
    'by_00fd4':                          _offmap_load_guard(
        0xf94002a0, 'c->x[21]', 'x0', 'c->x[21] + 0x0ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (fd4)'),
    'by_00fdc':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000ea2fe4(Cpu *c); c->x[30] = 0x7000000fe0ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; f_7000ea2fe4(c);',
        'f_7000ea2fe4 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (fdc)'),
    'by_01014':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0530(Cpu *c); c->x[30] = 0x7000001018ull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; f_70015a0530(c);',
        'f_70015a0530 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (1014)'),
    'by_01018':                          _offmap_store_guard(
        0xf90002ff, 'c->x[23]', 'c->x[23] + 0x0ull', 'ST64', '0ull',
        'f_70000008e0 answered-0 registry-tail store via c->x[23] skipped off-map (1018)'),
    'by_01038':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x700000103cull; c->x[0] = x0; c->x[8] = x8; c->x[9] = x9; c->x[10] = x10; c->x[20] = x20; c->x[21] = c->x[21]; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (1038)'),
    'by_01044':                          _offmap_load_guard(
        0xf94022a8, 'c->x[21]', 'x8', 'c->x[21] + 0x40ull', 'LD64',
        'f_70000008e0 answered-0 registry-tail load via c->x[21] skipped off-map (1044)'),
    'by_01058':                          _offmap_load_guard(
        0xb9400328, 'c->x[25]', 'x8', 'c->x[25] + 0x0ull', 'LD32',
        'f_70000008e0 answered-0 registry-tail load via c->x[25] skipped off-map (1058)'),
    'by_01068':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x700000106cull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (1068)'),
    'bz_939ac':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[20] skipped off-map (39ac)'),
    'bz_939b8':                          _offmap_load_guard(
        0xb940ce61, 'c->x[19]', 'x1', 'c->x[19] + 0xccull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (39b8)'),
    'bz_939bc':                          _offmap_load_guard(
        0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (39bc)'),
    'bz_939c0':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e939c4ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (39c0)'),
    'bz_939c4':                          _offmap_load_guard(
        0xb940ce61, 'c->x[19]', 'x1', 'c->x[19] + 0xccull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (39c4)'),
    'bz_939cc':                          _offmap_load_guard(
        0xb940d261, 'c->x[19]', 'x1', 'c->x[19] + 0xd0ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (39cc)'),
    'bz_939d4':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[20] skipped off-map (39d4)'),
    'bz_939e0':                          _offmap_load_guard(
        0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (39e0)'),
    'bz_939e4':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e939e8ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (39e4)'),
    'bz_939fc':                          _offmap_load_guard(
        0xb940d262, 'c->x[19]', 'c->x[2]', 'c->x[19] + 0xd0ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (39fc)'),
    'bz_93a14':                          _offmap_store_guard(
        0xf900c277, 'c->x[19]', 'c->x[19] + 0x180ull', 'ST64', 'c->x[23]',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3a14)'),
    'bz_93a3c':                          _offmap_load_guard(
        0xf940d661, 'c->x[19]', 'x1', 'c->x[19] + 0x1a8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3a3c)'),
    'bz_93a48':                          _offmap_load_guard(
        0xf940d661, 'c->x[19]', 'x1', 'c->x[19] + 0x1a8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3a48)'),
    'bz_93a54':                          _offmap_u128_load_guard(
        0x2d568660, 'c->x[19]', 'c->v[0]', 'c->v[1]', 'c->x[19] + 180',
        'u128 a = LD32(ea), b = LD32(ea + 4); c->v[0] = a; c->v[1] = b;',
        'f_7000e93960 answered-0 manager-method ldp pair load into v-regs via c->x[19] skipped off-map (3a54)'),
    'bz_93a60':                          _offmap_load_guard(
        0xbd4002a2, 'c->x[21]', 'c->v[2]', 'c->x[21] + 0x0ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[21] skipped off-map (3a60)'),
    'bz_93a64':                          _offmap_store_guard(
        0xbd011262, 'c->x[19]', 'c->x[19] + 0x110ull', 'ST32', 'VS32(2)',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3a64)'),
    'bz_93a6c':                          _offmap_load_guard(
        0xbd4006a2, 'c->x[21]', 'c->v[2]', 'c->x[21] + 0x4ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[21] skipped off-map (3a6c)'),
    'bz_93a70':                          _offmap_store_guard(
        0xf9008e7f, 'c->x[19]', 'c->x[19] + 0x118ull', 'ST64', '0ull',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3a70)'),
    'bz_93a74':                          _offmap_store_guard(
        0xbd011662, 'c->x[19]', 'c->x[19] + 0x114ull', 'ST32', 'VS32(2)',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3a74)'),
    'bz_93a78':                          _offmap_store_guard(
        0xbd012260, 'c->x[19]', 'c->x[19] + 0x120ull', 'ST32', 'VS32(0)',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3a78)'),
    'bz_93a80':                          _offmap_store_guard(
        0xbd012660, 'c->x[19]', 'c->x[19] + 0x124ull', 'ST32', 'VS32(0)',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3a80)'),
    'bz_93ab8':                          _offmap_load_guard(
        0xf9466508, 'x8', 'x8', 'x8 + 0xcc8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3ab8)'),
    'bz_93abc':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3abc)'),
    'bz_93ac0':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93ac4ull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3ac0)'),
    'bz_93ac4':                          _offmap_load_guard(
        0x3942fa68, 'c->x[19]', 'x8', 'c->x[19] + 0xbeull', 'LD8',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3ac4)'),
    'bz_93acc':                          _offmap_load_guard(
        0xb940e260, 'c->x[19]', 'x0', 'c->x[19] + 0xe0ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3acc)'),
    'bz_93ad0':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e9bba8(Cpu *c); c->x[30] = 0x7000e93ad4ull; c->x[0] = x0; c->x[8] = x8; f_7000e9bba8(c);',
        'f_7000e9bba8 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3ad0)'),
    'bz_93ae0':                          _offmap_load_guard(
        0xf9466908, 'x8', 'x8', 'x8 + 0xcd0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3ae0)'),
    'bz_93ae4':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3ae4)'),
    'bz_93ae8':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93aecull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3ae8)'),
    'bz_93af8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e93afcull; c->x[0] = x0; c->x[1] = x1; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3af8)'),
    'bz_93b04':                          _offmap_blr_guard(
        'c->pc = c->x[24]; c->x[30] = 0x7000e93b08ull; c->x[1] = x1; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch c->x[24] is off-map or unmapped (3b04)', cond='c->x[24]', w=0xd63f0300),
    'bz_93b18':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_700000ecb0(Cpu *c); c->x[30] = 0x7000e93b1cull; c->x[0] = x0; c->x[1] = x1; f_700000ecb0(c);',
        'f_700000ecb0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3b18)'),
    'bz_93b24':                          _offmap_load_guard(
        0xf9468318, 'c->x[24]', 'c->x[24]', 'c->x[24] + 0xd00ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3b24)'),
    'bz_93b30':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3b30)'),
    'bz_93b34':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93b38ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3b34)'),
    'bz_93b38':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3b38)'),
    'bz_93b48':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93b4cull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3b48)'),
    'bz_93b64':                          _offmap_load_guard(
        0x3942fa68, 'c->x[19]', 'x8', 'c->x[19] + 0xbeull', 'LD8',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3b64)'),
    'bz_93b68':                          _offmap_load_guard(
        0x3942fe69, 'c->x[19]', 'c->x[9]', 'c->x[19] + 0xbfull', 'LD8',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3b68)'),
    'bz_93b8c':                          _offmap_load_guard(
        0xf9469908, 'x8', 'x8', 'x8 + 0xd30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3b8c)'),
    'bz_93b98':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3b98)'),
    'bz_93b9c':                          _offmap_load_guard(
        0xf9442c21, 'x1', 'x1', 'x1 + 0x858ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x1 skipped off-map (3b9c)'),
    'bz_93ba4':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93ba8ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3ba4)'),
    'bz_93ba8':                          _offmap_load_guard(
        0x3942fe68, 'c->x[19]', 'x8', 'c->x[19] + 0xbfull', 'LD8',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3ba8)'),
    'bz_93bac':                          _offmap_load_guard(
        0x3942fa69, 'c->x[19]', 'c->x[9]', 'c->x[19] + 0xbeull', 'LD8',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3bac)'),
    'bz_93bb0':                          _offmap_load_guard(
        0xb940e66a, 'c->x[19]', 'c->x[10]', 'c->x[19] + 0xe4ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3bb0)'),
    'bz_93bd4':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e93bd8ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3bd4)'),
    'bz_93bec':                          _offmap_load_guard(
        0xf941e35a, 'c->x[26]', 'c->x[26]', 'c->x[26] + 0x3c0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[26] skipped off-map (3bec)'),
    'bz_93bf4':                          _offmap_store_guard(
        0xf9000357, 'c->x[26]', 'c->x[26] + 0x0ull', 'ST64', 'c->x[23]',
        'f_7000e93960 answered-0 manager-method store via c->x[26] skipped off-map (3bf4)'),
    'bz_93bf8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000eb37f8(Cpu *c); c->x[30] = 0x7000e93bfcull; c->x[0] = x0; c->x[1] = x1; f_7000eb37f8(c);',
        'f_7000eb37f8 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3bf8)'),
    'bz_93c04':                          _offmap_load_guard(
        0xf946f108, 'x8', 'x8', 'x8 + 0xde0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c04)'),
    'bz_93c08':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c08)'),
    'bz_93c0c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93c10ull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3c0c)'),
    'bz_93c18':                          _offmap_load_guard(
        0xf946f508, 'x8', 'x8', 'x8 + 0xde8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c18)'),
    'bz_93c20':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c20)'),
    'bz_93c24':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93c28ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3c24)'),
    'bz_93c28':                          _offmap_load_guard(
        0xf9400348, 'c->x[26]', 'x8', 'c->x[26] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[26] skipped off-map (3c28)'),
    'bz_93c30':                          _offmap_load_guard(
        0xf9401901, 'x8', 'x1', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c30)'),
    'bz_93c38':                          _offmap_load_guard(
        0xf946ed08, 'x8', 'x8', 'x8 + 0xdd8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c38)'),
    'bz_93c3c':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c3c)'),
    'bz_93c40':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93c44ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3c40)'),
    'bz_93c44':                          _offmap_load_guard(
        0xb940d668, 'c->x[19]', 'x8', 'c->x[19] + 0xd4ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3c44)'),
    'bz_93c54':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3c54)'),
    'bz_93c64':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93c68ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3c64)'),
    'bz_93c74':                          _offmap_load_guard(
        0xf946fd08, 'x8', 'x8', 'x8 + 0xdf8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c74)'),
    'bz_93c7c':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3c7c)'),
    'bz_93c80':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93c84ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3c80)'),
    'bz_93c84':                          _offmap_load_guard(
        0xb940da68, 'c->x[19]', 'x8', 'c->x[19] + 0xd8ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3c84)'),
    'bz_93c94':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3c94)'),
    'bz_93ca4':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93ca8ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3ca4)'),
    'bz_93cb4':                          _offmap_load_guard(
        0xf946f908, 'x8', 'x8', 'x8 + 0xdf0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3cb4)'),
    'bz_93cbc':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3cbc)'),
    'bz_93cc0':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93cc4ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3cc0)'),
    'bz_93cc4':                          _offmap_load_guard(
        0xb940de68, 'c->x[19]', 'x8', 'c->x[19] + 0xdcull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3cc4)'),
    'bz_93cd4':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3cd4)'),
    'bz_93ce4':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93ce8ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3ce4)'),
    'bz_93cf4':                          _offmap_load_guard(
        0xf9470108, 'x8', 'x8', 'x8 + 0xe00ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3cf4)'),
    'bz_93cfc':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3cfc)'),
    'bz_93d00':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93d04ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3d00)'),
    'bz_93d0c':                          _offmap_load_guard(
        0xf9470508, 'x8', 'x8', 'x8 + 0xe08ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3d0c)'),
    'bz_93d10':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3d10)'),
    'bz_93d14':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93d18ull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3d14)'),
    'bz_93d18':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[20] skipped off-map (3d18)'),
    'bz_93d2c':                          _offmap_load_guard(
        0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3d2c)'),
    'bz_93d30':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93d34ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3d30)'),
    'bz_93d3c':                          _offmap_load_guard(
        0xf9470908, 'x8', 'x8', 'x8 + 0xe10ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3d3c)'),
    'bz_93d48':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3d48)'),
    'bz_93d4c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93d50ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3d4c)'),
    'bz_93d5c':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e93d60ull; c->x[0] = x0; c->x[1] = x1; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3d5c)'),
    'bz_93d60':                          _offmap_store_guard(
        0xf900ce60, 'c->x[19]', 'c->x[19] + 0x198ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3d60)'),
    'bz_93d6c':                          _offmap_load_guard(
        0xf9473908, 'x8', 'x8', 'x8 + 0xe70ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3d6c)'),
    'bz_93d70':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3d70)'),
    'bz_93d74':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93d78ull; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3d74)'),
    'bz_93d78':                          _offmap_load_guard(
        0xf9400340, 'c->x[26]', 'x0', 'c->x[26] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[26] skipped off-map (3d78)'),
    'bz_93d7c':                          _offmap_load_guard(
        0xf940ce61, 'c->x[19]', 'x1', 'c->x[19] + 0x198ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3d7c)'),
    'bz_93d80':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e9bb0c(Cpu *c); c->x[30] = 0x7000e93d84ull; c->x[0] = x0; c->x[1] = x1; f_7000e9bb0c(c);',
        'f_7000e9bb0c skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3d80)'),
    'bz_93d90':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e93d94ull; c->x[0] = x0; c->x[1] = x1; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3d90)'),
    'bz_93d9c':                          _offmap_load_guard(
        0xf940da61, 'c->x[19]', 'x1', 'c->x[19] + 0x1b0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3d9c)'),
    'bz_93da4':                          _offmap_store_guard(
        0xf9009a77, 'c->x[19]', 'c->x[19] + 0x130ull', 'ST64', 'c->x[23]',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3da4)'),
    'bz_93da8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_70015a0880(Cpu *c); c->x[30] = 0x7000e93dacull; c->x[0] = x0; c->x[1] = x1; f_70015a0880(c);',
        'f_70015a0880 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3da8)'),
    'bz_93dac':                          _offmap_load_guard(
        0xf9409a68, 'c->x[19]', 'x8', 'c->x[19] + 0x130ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3dac)'),
    'bz_93db4':                          _offmap_store_guard(
        0xf9004d09, 'x8', 'x8 + 0x98ull', 'ST64', 'c->x[9]',
        'f_7000e93960 answered-0 manager-method store via x8 skipped off-map (3db4)'),
    'bz_93db8':                          _offmap_load_guard(
        0xf9409a60, 'c->x[19]', 'x0', 'c->x[19] + 0x130ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3db8)'),
    'bz_93dbc':                          _offmap_load_guard(
        0xb940a261, 'c->x[19]', 'x1', 'c->x[19] + 0xa0ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3dbc)'),
    'bz_93dc0':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e9af20(Cpu *c); c->x[30] = 0x7000e93dc4ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000e9af20(c);',
        'f_7000e9af20 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3dc0)'),
    'bz_93dc4':                          _offmap_load_guard(
        0xf9409a60, 'c->x[19]', 'x0', 'c->x[19] + 0x130ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3dc4)'),
    'bz_93dc8':                          _offmap_load_guard(
        0x3942f661, 'c->x[19]', 'x1', 'c->x[19] + 0xbdull', 'LD8',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3dc8)'),
    'bz_93dcc':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e9af44(Cpu *c); c->x[30] = 0x7000e93dd0ull; c->x[0] = x0; c->x[1] = x1; f_7000e9af44(c);',
        'f_7000e9af44 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3dcc)'),
    'bz_93dd0':                          _offmap_u128_load_guard(
        0x2d568660, 'c->x[19]', 'c->v[0]', 'c->v[1]', 'c->x[19] + 180',
        'u128 a = LD32(ea), b = LD32(ea + 4); c->v[0] = a; c->v[1] = b;',
        'f_7000e93960 answered-0 manager-method ldp pair load into v-regs via c->x[19] skipped off-map (3dd0)'),
    'bz_93dd8':                          _offmap_load_guard(
        0xf9409a60, 'c->x[19]', 'x0', 'c->x[19] + 0x130ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3dd8)'),
    'bz_93de0':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x0 skipped off-map (3de0)'),
    'bz_93de8':                          _offmap_pair_store_guard(
        0x2d010400, 'x0', 'x0 + 8', 'VS32(0)', 'VS32(1)',
        'f_7000e93960 answered-0 manager-method pair store via x0 skipped off-map (3de8)'),
    'bz_93dec':                          _offmap_load_guard(
        0xf9400908, 'x8', 'x8', 'x8 + 0x10ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3dec)'),
    'bz_93df0':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93df4ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3df0)'),
    'bz_93df4':                          _offmap_load_guard(
        0xb940a268, 'c->x[19]', 'x8', 'c->x[19] + 0xa0ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3df4)'),
    'bz_93e04':                          _offmap_load_guard(
        0xbd46f501, 'x8', 'c->v[1]', 'x8 + 0x6f4ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3e04)'),
    'bz_93e18':                          _offmap_load_guard(
        0xf9410508, 'x8', 'x8', 'x8 + 0x208ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3e18)'),
    'bz_93e20':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3e20)'),
    'bz_93e30':                          _offmap_store_guard(
        0xf9009668, 'c->x[19]', 'c->x[19] + 0x128ull', 'ST64', 'x8',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3e30)'),
    'bz_93e34':                          _offmap_load_guard(
        0xf9400340, 'c->x[26]', 'x0', 'c->x[26] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[26] skipped off-map (3e34)'),
    'bz_93e38':                          _offmap_load_guard(
        0xf9409a61, 'c->x[19]', 'x1', 'c->x[19] + 0x130ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3e38)'),
    'bz_93e3c':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e9bb1c(Cpu *c); c->x[30] = 0x7000e93e40ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000e9bb1c(c);',
        'f_7000e9bb1c skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3e3c)'),
    'bz_93e48':                          _offmap_lda_guard(
        0x8dffd08, 'x8', 'x8',
        'f_7000e93960 answered-0 manager-method acquire load via x8 skipped off-map (3e48)'),
    'bz_93e54':                          _offmap_load_guard(
        0xf9400348, 'c->x[26]', 'x8', 'c->x[26] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[26] skipped off-map (3e54)'),
    'bz_93e64':                          _offmap_load_guard(
        0xf9401917, 'x8', 'c->x[23]', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3e64)'),
    'bz_93e68':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e93e6cull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3e68)'),
    'bz_93e6c':                          _offmap_store_guard(
        0xf900ae60, 'c->x[19]', 'c->x[19] + 0x158ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3e6c)'),
    'bz_93e78':                          _offmap_load_guard(
        0xf943d508, 'x8', 'x8', 'x8 + 0x7a8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3e78)'),
    'bz_93e7c':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3e7c)'),
    'bz_93e80':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93e84ull; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3e80)'),
    'bz_93e90':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e93e94ull; c->x[0] = x0; c->x[1] = x1; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3e90)'),
    'bz_93e94':                          _offmap_store_guard(
        0xf900a660, 'c->x[19]', 'c->x[19] + 0x148ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3e94)'),
    'bz_93ea0':                          _offmap_load_guard(
        0xf947d77b, 'c->x[27]', 'c->x[27]', 'c->x[27] + 0xfa8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[27] skipped off-map (3ea0)'),
    'bz_93ea4':                          _offmap_load_guard(
        0xf9400368, 'c->x[27]', 'x8', 'c->x[27] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[27] skipped off-map (3ea4)'),
    'bz_93ea8':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93eacull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3ea8)'),
    'bz_93eb4':                          _offmap_load_guard(
        0xf947d108, 'x8', 'x8', 'x8 + 0xfa0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3eb4)'),
    'bz_93ebc':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3ebc)'),
    'bz_93ec0':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93ec4ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3ec0)'),
    'bz_93ecc':                          _offmap_load_guard(
        0xf947df9c, 'c->x[28]', 'c->x[28]', 'c->x[28] + 0xfb8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[28] skipped off-map (3ecc)'),
    'bz_93ed4':                          _offmap_load_guard(
        0xf9400388, 'c->x[28]', 'x8', 'c->x[28] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[28] skipped off-map (3ed4)'),
    'bz_93ed8':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93edcull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3ed8)'),
    'bz_93edc':                          _offmap_load_guard(
        0xf9460b20, 'c->x[25]', 'x0', 'c->x[25] + 0xc10ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[25] skipped off-map (3edc)'),
    'bz_93ee8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000007c20(Cpu *c); c->x[30] = 0x7000e93eecull; c->x[0] = x0; c->x[1] = x1; f_7000007c20(c);',
        'f_7000007c20 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3ee8)'),
    'bz_93ef0':                          _offmap_load_guard(
        0xf9460b22, 'c->x[25]', 'c->x[2]', 'c->x[25] + 0xc10ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[25] skipped off-map (3ef0)'),
    'bz_93ef8':                          _offmap_load_guard(
        0xf947d908, 'x8', 'x8', 'x8 + 0xfb0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3ef8)'),
    'bz_93f00':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3f00)'),
    'bz_93f04':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93f08ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3f04)'),
    'bz_93f0c':                          _offmap_load_guard(
        0xf940a660, 'c->x[19]', 'x0', 'c->x[19] + 0x148ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3f0c)'),
    'bz_93f14':                          _offmap_load_guard(
        0xf947f339, 'c->x[25]', 'c->x[25]', 'c->x[25] + 0xfe0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[25] skipped off-map (3f14)'),
    'bz_93f18':                          _offmap_load_guard(
        0xf9400328, 'c->x[25]', 'x8', 'c->x[25] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[25] skipped off-map (3f18)'),
    'bz_93f1c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93f20ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3f1c)'),
    'bz_93f20':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3f20)'),
    'bz_93f34':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93f38ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3f34)'),
    'bz_93f38':                          _offmap_load_guard(
        0xf9400288, 'c->x[20]', 'x8', 'c->x[20] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[20] skipped off-map (3f38)'),
    'bz_93f40':                          _offmap_load_guard(
        0xb940c661, 'c->x[19]', 'x1', 'c->x[19] + 0xc4ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3f40)'),
    'bz_93f48':                          _offmap_load_guard(
        0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3f48)'),
    'bz_93f4c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93f50ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3f4c)'),
    'bz_93f50':                          _offmap_store_guard(
        0xf900aa60, 'c->x[19]', 'c->x[19] + 0x150ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (3f50)'),
    'bz_93f58':                          _offmap_load_guard(
        0xf940ae60, 'c->x[19]', 'x0', 'c->x[19] + 0x158ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3f58)'),
    'bz_93f5c':                          _offmap_load_guard(
        0xf943e108, 'x8', 'x8', 'x8 + 0x7c0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3f5c)'),
    'bz_93f68':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3f68)'),
    'bz_93f6c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93f70ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3f6c)'),
    'bz_93f74':                          _offmap_load_guard(
        0xf940ae60, 'c->x[19]', 'x0', 'c->x[19] + 0x158ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3f74)'),
    'bz_93f7c':                          _offmap_load_guard(
        0xf943e508, 'x8', 'x8', 'x8 + 0x7c8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3f7c)'),
    'bz_93f80':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (3f80)'),
    'bz_93f84':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93f88ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3f84)'),
    'bz_93f88':                          _offmap_load_guard(
        0xf9400340, 'c->x[26]', 'x0', 'c->x[26] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[26] skipped off-map (3f88)'),
    'bz_93f8c':                          _offmap_load_guard(
        0xf940ae61, 'c->x[19]', 'x1', 'c->x[19] + 0x158ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3f8c)'),
    'bz_93f90':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e9bb14(Cpu *c); c->x[30] = 0x7000e93f94ull; c->x[0] = x0; c->x[1] = x1; f_7000e9bb14(c);',
        'f_7000e9bb14 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (3f90)'),
    'bz_93f94':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3f94)'),
    'bz_93fa4':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93fa8ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3fa4)'),
    'bz_93fa8':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3fa8)'),
    'bz_93fb8':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93fbcull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3fb8)'),
    'bz_93fbc':                          _offmap_load_guard(
        0xf9400308, 'c->x[24]', 'x8', 'c->x[24] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[24] skipped off-map (3fbc)'),
    'bz_93fcc':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e93fd0ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (3fcc)'),
    'bz_93fd0':                          _offmap_load_guard(
        0xb940ca68, 'c->x[19]', 'x8', 'c->x[19] + 0xc8ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (3fd0)'),
    'bz_94018':                          _offmap_store_guard(
        0xb9017a68, 'c->x[19]', 'c->x[19] + 0x178ull', 'ST32', '(uint32_t)x8',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (4018)'),
    'bz_9401c':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e94020ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (401c)'),
    'bz_94020':                          _offmap_load_guard(
        0xf9400368, 'c->x[27]', 'x8', 'c->x[27] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[27] skipped off-map (4020)'),
    'bz_94024':                          _offmap_store_guard(
        0xf900ba60, 'c->x[19]', 'c->x[19] + 0x170ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (4024)'),
    'bz_9402c':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e94030ull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (402c)'),
    'bz_94030':                          _offmap_load_guard(
        0xf9400348, 'c->x[26]', 'x8', 'c->x[26] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[26] skipped off-map (4030)'),
    'bz_94038':                          _offmap_load_guard(
        0xf9401901, 'x8', 'x1', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4038)'),
    'bz_94040':                          _offmap_load_guard(
        0xf947d108, 'x8', 'x8', 'x8 + 0xfa0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4040)'),
    'bz_94044':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4044)'),
    'bz_94048':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e9404cull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (4048)'),
    'bz_9404c':                          _offmap_load_guard(
        0xf9400388, 'c->x[28]', 'x8', 'c->x[28] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[28] skipped off-map (404c)'),
    'bz_94058':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e9405cull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (4058)'),
    'bz_9405c':                          _offmap_load_guard(
        0xb9417a60, 'c->x[19]', 'x0', 'c->x[19] + 0x178ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (405c)'),
    'bz_94068':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000007c20(Cpu *c); c->x[30] = 0x7000e9406cull; c->x[0] = x0; c->x[1] = x1; f_7000007c20(c);',
        'f_7000007c20 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (4068)'),
    'bz_94070':                          _offmap_load_guard(
        0xb9417a62, 'c->x[19]', 'c->x[2]', 'c->x[19] + 0x178ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (4070)'),
    'bz_94078':                          _offmap_load_guard(
        0xf947d908, 'x8', 'x8', 'x8 + 0xfb0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4078)'),
    'bz_94080':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4080)'),
    'bz_94084':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e94088ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (4084)'),
    'bz_94088':                          _offmap_load_guard(
        0xf940ba60, 'c->x[19]', 'x0', 'c->x[19] + 0x170ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (4088)'),
    'bz_94090':                          _offmap_load_guard(
        0xf9400328, 'c->x[25]', 'x8', 'c->x[25] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[25] skipped off-map (4090)'),
    'bz_94094':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e94098ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (4094)'),
    'bz_94098':                          _offmap_load_guard(
        0xf9400348, 'c->x[26]', 'x8', 'c->x[26] + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[26] skipped off-map (4098)'),
    'bz_940a0':                          _offmap_load_guard(
        0xf9401901, 'x8', 'x1', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (40a0)'),
    'bz_940a8':                          _offmap_load_guard(
        0xf9405508, 'x8', 'x8', 'x8 + 0xa8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (40a8)'),
    'bz_940ac':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (40ac)'),
    'bz_940b0':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e940b4ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (40b0)'),
    'bz_940bc':                          _offmap_load_guard(
        0xf9405908, 'x8', 'x8', 'x8 + 0xb0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (40bc)'),
    'bz_940c0':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (40c0)'),
    'bz_940c4':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e940c8ull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (40c4)'),
    'bz_940cc':                          _offmap_load_guard(
        0xf940a661, 'c->x[19]', 'x1', 'c->x[19] + 0x148ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (40cc)'),
    'bz_940d4':                          _offmap_load_guard(
        0xb940c262, 'c->x[19]', 'c->x[2]', 'c->x[19] + 0xc0ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (40d4)'),
    'bz_940e0':                          _offmap_load_guard(
        0xf9405d08, 'x8', 'x8', 'x8 + 0xb8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (40e0)'),
    'bz_940e4':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (40e4)'),
    'bz_940e8':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e940ecull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (40e8)'),
    'bz_940f8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e940fcull; c->x[0] = x0; c->x[1] = x1; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (40f8)'),
    'bz_940fc':                          _offmap_store_guard(
        0xf900b260, 'c->x[19]', 'c->x[19] + 0x160ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (40fc)'),
    'bz_94108':                          _offmap_load_guard(
        0xf9407108, 'x8', 'x8', 'x8 + 0xe0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4108)'),
    'bz_9410c':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (410c)'),
    'bz_94110':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e94114ull; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (4110)'),
    'bz_94118':                          _offmap_load_guard(
        0xf940b260, 'c->x[19]', 'x0', 'c->x[19] + 0x160ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (4118)'),
    'bz_9411c':                          _offmap_load_guard(
        0xf9407d08, 'x8', 'x8', 'x8 + 0xf8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (411c)'),
    'bz_94120':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4120)'),
    'bz_94124':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e94128ull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (4124)'),
    'bz_94128':                          _offmap_store_guard(
        0xf900b660, 'c->x[19]', 'c->x[19] + 0x168ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (4128)'),
    'bz_94138':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e9413cull; c->x[0] = x0; c->x[1] = x1; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (4138)'),
    'bz_9413c':                          _offmap_store_guard(
        0xf900e260, 'c->x[19]', 'c->x[19] + 0x1c0ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (413c)'),
    'bz_94148':                          _offmap_load_guard(
        0xf9462108, 'x8', 'x8', 'x8 + 0xc40ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4148)'),
    'bz_9414c':                          _offmap_load_guard(
        0xf9400108, 'x8', 'x8', 'x8 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (414c)'),
    'bz_94150':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e94154ull; c->x[1] = x1; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (4150)'),
    'bz_94154':                          _offmap_load_guard(
        0x3942f268, 'c->x[19]', 'x8', 'c->x[19] + 0xbcull', 'LD8',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (4154)'),
    'bz_9415c':                          _offmap_u128_load_guard(
        0x29568e62, 'c->x[19]', 'c->x[2]', 'c->x[3]', 'c->x[19] + 180',
        'uint64_t a = LD32(ea), b = LD32(ea + 4); c->x[2] = (uint64_t)(a); c->x[3] = (uint64_t)(b);',
        'f_7000e93960 answered-0 manager-method ldp pair load via c->x[19] skipped off-map (415c)'),
    'bz_94168':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e9a6b8(Cpu *c); c->x[30] = 0x7000e9416cull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000e9a6b8(c);',
        'f_7000e9a6b8 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (4168)'),
    'bz_9416c':                          _offmap_store_guard(
        0xf9008260, 'c->x[19]', 'c->x[19] + 0x100ull', 'ST64', 'x0',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (416c)'),
    'bz_9417c':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e94180ull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (417c)'),
    'bz_94188':                          _offmap_load_guard(
        0xf9413108, 'x8', 'x8', 'x8 + 0x260ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4188)'),
    'bz_941a8':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000e8c250(Cpu *c); c->x[30] = 0x7000e941acull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000e8c250(c);',
        'f_7000e8c250 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (41a8)'),
    'bz_941b8':                          _offmap_pair_store_guard(
        0xa9017c08, 'x0', 'x0 + 16', 'x8', '0ull',
        'f_7000e93960 answered-0 manager-method pair store via x0 skipped off-map (41b8)'),
    'bz_941c4':                          _offmap_pair_store_guard(
        0xa9004c08, 'x0', 'x0 + 0', 'x8', 'c->x[19]',
        'f_7000e93960 answered-0 manager-method pair store via x0 skipped off-map (41c4)'),
    'bz_941c8':                          _offmap_load_guard(
        0xb940ea60, 'c->x[19]', 'x0', 'c->x[19] + 0xe8ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (41c8)'),
    'bz_941cc':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000eb0ae0(Cpu *c); c->x[30] = 0x7000e941d0ull; c->x[0] = x0; c->x[8] = x8; f_7000eb0ae0(c);',
        'f_7000eb0ae0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (41cc)'),
    'bz_941f4':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000eb06f0(Cpu *c); c->x[30] = 0x7000e941f8ull; c->x[0] = x0; c->x[1] = x1; f_7000eb06f0(c);',
        'f_7000eb06f0 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (41f4)'),
    'bz_941fc':                          _offmap_store_guard(
        0xf900de75, 'c->x[19]', 'c->x[19] + 0x1b8ull', 'ST64', 'c->x[21]',
        'f_7000e93960 answered-0 manager-method store via c->x[19] skipped off-map (41fc)'),
    'bz_94218':                          _offmap_call_skip_guard(
        'x0',
        'extern void f_7000eb0218(Cpu *c); c->x[30] = 0x7000e9421cull; c->x[0] = x0; c->x[1] = x1; c->x[8] = x8; f_7000eb0218(c);',
        'f_7000eb0218 skipped on the off-map x0 of the answered-0 walk; the dead 0 answer lands where the guarded chain already expects 0 (4218)'),
    'bz_9421c':                          _offmap_load_guard(
        0xf940de60, 'c->x[19]', 'x0', 'c->x[19] + 0x1b8ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (421c)'),
    'bz_94220':                          _offmap_load_guard(
        0xf9400008, 'x0', 'x8', 'x0 + 0x0ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x0 skipped off-map (4220)'),
    'bz_94224':                          _offmap_load_guard(
        0xf9401908, 'x8', 'x8', 'x8 + 0x30ull', 'LD64',
        'f_7000e93960 answered-0 manager-method load via x8 skipped off-map (4224)'),
    'bz_94228':                          _offmap_blr_guard(
        'c->pc = x8; c->x[30] = 0x7000e9422cull; c->x[0] = x0; c->x[8] = x8; rt_dispatch(c);',
        'caller-walk virtual probe answered 0 through the dispatch_lookup backstop when the dispatch x8 is off-map or unmapped (4228)'),
    'bz_94254':                          _always_call(
        'x0',
        'extern void f_700159feb0(Cpu *c); c->x[30] = 0x7000e94258ull; c->x[0] = x0; c->x[8] = x8; f_700159feb0(c);',
        'lock/TLS thunk f_700159feb0 kept ALWAYS-CALL per the #49 rule -- the dead x0 is a legitimate value, the guarded lift answers it 0, and the thunk side effect is exactly what the registry needs (4254)'),
    'bz_9425c':                          _offmap_load_guard(
        0xb940c268, 'c->x[19]', 'x8', 'c->x[19] + 0xc0ull', 'LD32',
        'f_7000e93960 answered-0 manager-method load via c->x[19] skipped off-map (425c)'),
    'bz_94274':                          _offmap_store_guard(
        0xf9060b28, 'c->x[25]', 'c->x[25] + 0xc10ull', 'ST64', 'x8',
        'f_7000e93960 answered-0 manager-method store via c->x[25] skipped off-map (4274)'),
    'bz_94278':                          _always_call(
        'x0',
        'extern void f_700159fec0(Cpu *c); c->x[30] = 0x7000e9427cull; c->x[0] = x0; c->x[8] = x8; f_700159fec0(c);',
        'lock/TLS thunk f_700159fec0 kept ALWAYS-CALL per the #49 rule -- same legitimacy, and its guarded lift answers the dead x0 0 (4278)'),
    'bz_939c8':                          _offmap_call_skip_guard(
        'c->x[0]',
        'extern void f_70015a0800(Cpu *c); c->x[30] = 0x7000e939ccull; c->x[1] = x1; f_70015a0800(c);',
        'implicit-x0 bl (no spill, x0 rides c->x[0]) skipped when the dead answered-0 x0 would enter the GUARD-FREE sdk slot stub of thunk f_70015a0800 per the #49 rule (939c8)'),
    'bz_93a08':                          _offmap_call_skip_guard(
        'c->x[0]',
        'extern void f_70015a0810(Cpu *c); c->x[30] = 0x7000e93a0cull; c->x[1] = x1; f_70015a0810(c);',
        "run107 fault site: thunk f_70015a0810 slot-dispatched into the guard-free sdk stub f_700263b598 where str xzr, [x0] with the dead implicit x0 = 0 died (signal 11 accessing 0x0, guest lr 7000e93a0c, host pc f_700263b598+10); skipped per the #49 rule, the answered-0 continuation is exactly where the guarded chain already expects the dead thunk (93a08)"),
    'bz_93a30':                          _offmap_call_skip_guard(
        'c->x[0]',
        'extern void f_70015a0830(Cpu *c); c->x[30] = 0x7000e93a34ull; c->x[1] = x1; f_70015a0830(c);',
        'implicit-x0 bl skipped when the dead x0 would enter guard-free sdk stub f_70015a0830 per the #49 rule (93a30)'),
    'bz_93be0':                          _offmap_call_skip_guard(
        'c->x[0]',
        'extern void f_7000e9b794(Cpu *c); c->x[30] = 0x7000e93be4ull; c->x[1] = x1; f_7000e9b794(c);',
        'implicit-x0 bl skipped on the dead x0; the guarded main callee answers 0 itself but skipping keeps the same answered-0 shape (93be0)'),
    'bz_93d98':                          _offmap_call_skip_guard(
        'c->x[0]',
        'extern void f_7000e9aa74(Cpu *c); c->x[30] = 0x7000e93d9cull; f_7000e9aa74(c);',
        'implicit-x0 bl skipped on the dead x0; guarded main callee answered-0 either way (93d98)'),
}


def table(sites):
    """address -> patch, for the main module whose sites these are (tools/game_sites.py; an optional site it lacks
    has no patch)"""
    return {sites[name]: fn for name, fn in PATCHES.items() if name in sites}
