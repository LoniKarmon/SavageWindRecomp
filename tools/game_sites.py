"""Places in the game's main module that Savage Wind patches or reads, found by pattern for each game version.

    game_sites.py find <exefs/main>      every site in that main module: what its pattern finds, against the
                                         addresses known for that build (a new version: the table to add)
    game_sites.py pattern <exefs/main> <address> [code|call|ref|got|imm]
                                         a pattern that finds that one instruction (for a new site)
    game_sites.py common <main A> <address in A> <main B> <address in B> [kind]
                                         a pattern that finds the same instruction in two versions (for a site whose
                                         pattern no longer finds it: the bits both versions share)

tools/patches.py replaces single instructions at some of these sites while gen.py generates the code. The runtime
reads or writes game data at the others (runtime/game_sites.h): gen.py puts every site into the game library (the
generated layout.c), so the runtime takes the addresses of the version it runs.

A site is found by a short pattern of instruction words, so a later build of the game (other addresses, the same
code) needs no new numbers. Patterns mask the fields that change when code or data moves: branch and call offsets,
ADRP pages, and the low 12 bits an ADD / LDR / STR adds to an ADRP page in the pattern. `at` picks the instruction
(in words from the pattern's start), and the site is
    code  that instruction's own address
    call  the function a BL / B there goes to
    ref   the address an ADD / LDR / STR there forms with its ADRP (the ADRP itself: its page)
    got   the pointer stored at that `ref` address (a GOT entry; the module's relocations make it absolute)
    imm   the instruction's immediate (an LDR / STR offset, an ADD / CMP / MOVZ value): a field offset in a game
          object that a version moved (1.9.0's UI screens are 0x18 bytes bigger from about +0x290 on)
and two have no pattern: data (where the module's .data starts) and end (where its image ends, .bss included).
One pattern serves every version while the code around a site stays the same. Where a version changed it, the site
takes a list of (pattern, at) instead: the first that finds exactly one place wins (each must find one place, or
none, in every version).

The versions Savage Wind can set up are VERSIONS (the same list as runtime/game_versions.h, which the configuration
screen checks: tools/test_game_sites.py compares them). The builds in KNOWN also list every site's address: there a
pattern has to find exactly that place (the self-check), and a pattern that no longer finds exactly one place falls
back to the listed address with a warning. A build not in KNOWN needs every pattern to find exactly one place.
docs/SAVAGE-WIND.md ("Versiones del juego") has the steps for a new version.
"""
import re
import struct
import sys
from collections import namedtuple

MAIN_BASE = 0x7000000000  # (tools/layout.py: main is the first module)

# name, version, main module build id (the first 8 bytes; tools/sw_probe.py prints it), supported. One that isn't
# supported yet is known but refused by the setup until its sites are checked.
Version = namedtuple('Version', 'name build_id supported')
VERSIONS = [
    Version('1.8.2', 'de0b6ac4efc1dda7', True),
    Version('1.9.0', 'cd57b23fa4bbad65', True),  # (2026-02-17: Thai text on Switch 2; SDK 21.4.1)
]

Site = namedtuple('Site', 'name kind pattern at')
BLADE_BUFFERS = '910e0135 b85fc3a9 7103fd1f 52800f18 12001d36 52801fe9 1a893108'
BLADE_LATERAL = ('bd4207e0 bd420be1 1e298821 1f0d0402 1f2d0400 1e202048 1e20cc40 bd000720 1e262000 bd4213e1 1e35d428 '
                 '54000005/ff00001f bd4217e1 1e272000')
TRAVERSE = ('b9400028 2f00e400 36600008/fff8001f d65f03c0 a9bf7bfd 910003fd 12000042 12000083 94000000/fc000000 '
            '90000008/9f00001f 91000108/ffc003ff f9400108 b4000008/ff00001f bd431101 52a85908 1e202008 1e270102 1e22cc00 '
            '1e210800 a8c17bfd 14000000/fc000000 1e2e1001')
# The game's input queries: isHold(pad, action) / isTrig(pad, action). Both load the action's pad mask from a table of 41
# (cmp w1, #0x29) and test it against the pad object's held word (+0x11c) or pressed word (+0x10)
PAD_QUERY = ('a9be7bfd a9014ff4 910003fd 7100a43f 90000008/9f00001f 91000108/ffc003ff 1a9f3029 aa0003f3 b8695914 '
             '7100229f 7a421a84 54000001/ff00001f 2a1f03e0 94000000/fc000000 71000a9f 52800048 52800109 1a880128 '
             '7200001f 1a941114')
OPT_TWO_SITES = ('opt_two_redraw', 'opt_two_select', 'opt_two_state', 'opt_two_decide', 'opt_two_after', 'opt_two_row_state', 'opt_two_update_control', 'opt_two_initial_control', 'opt_two_left', 'opt_two_right', 'opt_two_text', 'opt_two_help', 'opt_two_pane_calc')

SITES = [
    # Experimental dual binding cells. Every pattern must match; no KNOWN fallback.
    Site('opt_two_redraw', 'code', 'd10103ff a9017bfd a90257f6 a9034ff4 910043fd 90000009/9f00001f 91000129/ffc003ff b9405008', 0),
    Site('opt_two_select', 'code', 'b976b008 7100051f 5400000b/ff00001f a9be7bfd a9014ff4 910003fd 9000000b/9f00001f 9100016b/ffc003ff', 0),
    Site('opt_two_state', 'code', 'b976b008 7100051f 5400000b/ff00001f 9000000b/9f00001f 9100016b/ffc003ff f95b5c09 b940016a 5280060c f940056b f940012d b400000d/ff00001f b94051ae 6b0e015f 1a9f81ce 9b2c2dce b94011ce 710009df 54000000/ff00001f 710005df 54000000/ff00001f 3500000e/ff00001f 910061ad 14000000/fc000000 9100a1ad 14000000/fc000000 910081ad f94001ad eb0101bf 54000000/ff00001f 91002129 f1000508 54000001/ff00001f 14000000/fc000000 aa1f03ed 14000000/fc000000 d65f03c0 f9400120 17ffff20', 0),
    Site('opt_two_decide', 'code', 'b976b008 7100051f 5400000b/ff00001f 9000000b/9f00001f 9100016b/ffc003ff f95b5c09 b940016a 5280060c f940056b f940012d b400000d/ff00001f b94051ae 6b0e015f 1a9f81ce 9b2c2dce b94011ce 710009df 54000000/ff00001f 710005df 54000000/ff00001f 3500000e/ff00001f 910061ad 14000000/fc000000 9100a1ad 14000000/fc000000 910081ad f94001ad eb0101bf 54000000/ff00001f 91002129 f1000508 54000001/ff00001f 14000000/fc000000 aa1f03ed 14000000/fc000000 d65f03c0 f9400120 14000001', 0),
    Site('opt_two_after', 'code', 'b976b008 7100051f 5400000b/ff00001f 90000009/9f00001f 91000129/ffc003ff f95b5c0a b940012b 5280060c', 0),
    Site('opt_two_row_state', 'code', '90000008/9f00001f 91000108/ffc003ff b9405009 b940010a 6b09015f f9400508 5280060a 1a9f8129 9b2a2128', 0),
    Site('opt_two_update_control', 'code', 'f9400129 eb09011f 54000000/ff00001f b976c268 71000d1f 54000001/ff00001f f9401e68 3940e108', 0),
    Site('opt_two_initial_control', 'code', 'f9400161 b4000001/ff00001f aa1303e0 94000000/fc000000 aa0003e1 aa1303e0 94000000/fc000000 b9405288', 0),
    Site('opt_two_left', 'code', 'b936c268 f95b6668 f940068b b9405109 6b09015f 5280060a 1a9f8129 9b2a2d29 b9401129 34000009/ff00001f 7100053f 54000001/ff00001f b9405909', 0),
    Site('opt_two_right', 'code', 'b936c268 f95b6668 f940068b b9405109 6b09015f 5280060a 1a9f8129 9b2a2d29 b9401129 34000009/ff00001f 7100053f 54000001/ff00001f 294b250a', 0),
    Site('opt_two_text', 'code', 'b4000000/ff00001f d10583ff a9137bfd a91457fc a9154ff4 9104c3fd 90000009/9f00001f 910063e8', 0),
    Site('opt_two_help', 'code', 'd100c3ff a9017bfd f90013f3 910043fd aa0003f3 94000000/fc000000 90000009/9f00001f 91000129/ffc003ff', 0),
    Site('opt_two_pane_calc', 'code', 'd10243ff fd0023e8 f9002ff9 a904fbfd a9065ff8 a90757f6 a9084ff4 910123fd 39416008', 0),
    # The Options screen (tools/patches.py; runtime/ui/game_options.mm)
    Site('opt_create_rows', 'code', 'd10303ff a9067bfd a9076ffc a90867fa a9095ff8 a90a57f6 a90b4ff4 910183fd '
         '90000008/9f00001f b9400118/ffc003ff', 0),
    Site('opt_row_init_flag_type', 'code', '94000000/fc000000 b9006a60 aa1303e0 94000000/fc000000 aa1303e0 '
         '52800021 94000000/fc000000 a9424ff4', 0),
    Site('gdt_flag_type', 'call', '94000000/fc000000 b9006a60 aa1303e0 94000000/fc000000 aa1303e0 52800021 '
         '94000000/fc000000 a9424ff4', 0),
    Site('opt_row_redraw', 'call', 'aa1303e0 52800021 94000000/fc000000 a9424ff4 a9417bfd 9100c3ff d65f03c0', 2),
    Site('opt_read', 'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd 90000008/9f00001f 91000108/ffc003ff b9405009 '
         'b940010a', 0),
    Site('opt_store', 'code', '90000008/9f00001f 91000108/ffc003ff b9405009 b940010a 6b09015f f9400508 5280060a '
         '1a9f8129 9b2a2121', 0),
    Site('opt_table', 'ref', '90000008/9f00001f 91000108/ffc003ff b9405009 b940010a 6b09015f f9400508 5280060a '
         '1a9f8129 9b2a2121', 1),
    Site('opt_reset', 'code', 'b9406808 7100051f 54000000/ff00001f 35000008/ff00001f 90000008/9f00001f '
         '90000009/9f00001f 91000129/ffc003ff f9400108/ffc003ff', 0),
    Site('opt_msg_call', 'code', '94000000/fc000000 910023e2 aa1403e0 aa1303e1 94000000/fc000000 a9554ff4 a95457fc '
         'a9537bfd', 0),
    Site('msg_lookup', 'call', '94000000/fc000000 910023e2 aa1403e0 aa1303e1 94000000/fc000000 a9554ff4 a95457fc '
         'a9537bfd', 0),
    Site('opt_decide', 'code', 'd100c3ff a9017bfd a9024ff4 910043fd 90000009/9f00001f 91000129/ffc003ff b9405008 '
         'b940012a 5280060b', 0),
    Site('opt_update', 'code', 'd10103ff a9017bfd a90257f6 a9034ff4 910043fd 5286d288/fffff2ff aa0003f3 8b080015', 0),
    Site('opt_back_call', 'code', '94000000/fc000000 f9401e68 b9403909 121e7929 b9003909 90000008/9f00001f '
         '91000108/ffc003ff f9400108', 0),
    Site('screen_back', 'call', '94000000/fc000000 f9401e68 b9403909 121e7929 b9003909 90000008/9f00001f '
         '91000108/ffc003ff f9400108', 0),
    Site('screen_open_request', 'call', '94000000/fc000000 90000008/9f00001f f9400108/ffc003ff f9400108 b9402909 '
         'f9401908 7100d53f 52803509', 0),
    Site('screen_open', 'code', 'a9be7bfd a9014ff4 910003fd aa0003f4 390a001f/ffff1fff b940c000 2a0103f3 '
         '94000000/fc000000', 0),
    Site('screen_close', 'call', '94000000/fc000000 52800028 0a330100 a9414ff4 a8c27bfd d65f03c0', 0),
    Site('screen_mgr', 'ref', '90000008/9f00001f 91000108/ffc003ff f9400108 b9402909 f9401908 7100913f 52802409 '
         '9a9f8129', 1),
    Site('pause_options_update', 'code', 'a9be7bfd a9014ff4 910003fd 90000008/9f00001f aa0003f3 f9400108/ffc003ff '
         'f9400108 b9402909 f9401908 7100d13f 52803409 9a9f8129 f8696914 94000000/fc000000 b4000014/ff00001f '
         'f9400288 aa0003e1 aa1403e0 f9400908 d63f0100 36000000/fff8001f 394a0688/ffff1fff', 0),
    Site('opt_screen_rows', 'imm', 'b9400008/ffc003ff 7100051f 5400000b/ff00001f f95b5009/fffff3ff f9400120 '
         'b940500a 6b01015f 54000000/ff00001f 91002129 f1000508 54000001/ff00001f d65f03c0 52800021', 0),
    # the game's two-button dialog (Quit asks with it)
    Site('dialog_texts', 'code', 'd10143ff a9017bfd f90013f7 a90357f6 a9044ff4 910043fd d2800b49 5286d888/fffffcff', 0),
    Site('dialog_back', 'code', 'f959c100/ffffc3ff b4000000/ff00001f a9414ff4 2a1f03e1 a8c27bfd 14000000/fc000000 '
         'f9400268 aa1303e0', 0),
    Site('dialog_answer', 'ref', '90000008/9f00001f 528001a9 aa0003f3 b9000109/ffc003ff 94000000/fc000000 aa0003e1 '
         'aa1303e0 94000000/fc000000', 3),
    # the title screen menu
    Site('title_update', 'code', 'a9bb7bfd a90167fc 910003fd a9025ff8 a90357f6 a9044ff4 d107c3ff 5286c208/fffff2ff', 0),
    Site('title_button', 'code', 'd10183ff a9037bfd f90023f5 a9054ff4 9100c3fd b9404434 aa0003f3 94000000/fc000000', 0),
    Site('title_options_state', 'imm', 'b9400268/ffc003ff 5101a508 7100191f 54000008/ff00001f 90000009/9f00001f '
         '91000129/ffc003ff 1000000a/9f00001f 3868692b', 0),
    Site('title_msg_file', 'ref', 'f9000549 90000009/9f00001f 91000129/ffc003ff 9000000a/9f00001f '
         'f900015f/ffc003ff a9002d28 a8c17bfd d65f03c0', 2),
    Site('title_version_format', 'ref', '90000001/9f00001f 91000021/ffc003ff d103c3a0 94000000/fc000000 '
         'f9400294/ffffffdf b940da88 35000008/ff00001f 90000001/9f00001f', 1),
    # BOTW's streaming Yaz0 decoder: its entry and its return (tools/patches.py; runtime/hle/yaz0.c)
    Site('yaz0_stream', 'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd 39406808 2a0203f4 aa0103f5 aa0003f3', 0),
    Site('yaz0_stream_ret', 'code', 'd65f03c0 7100869f 54000003/ff00001f b9400e68 35000008/ff00001f 12800000 '
         '14000000/fc000000 12800020', 0),
    # frame rate (runtime/hle/framepace.c, runtime/nvn/objects.c)
    Site('frame_wait', 'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd 91078014 aa0003f3 aa1403e0 94000000/fc000000', 0),
    Site('frame_loop_interval_ret', 'code', 'f9400268 aa1303e0 f9409908 d63f0100 14000000/fc000000 1100052a '
         '14000000/fc000000 2a0903e1', 4),
    Site('vfr_ratio', 'code', 'b9407a68 7100051f 5400000b/ff00001f 2a1f03f4 f9404269 6b14011f 1a9f8288 bd403e60', 0),
    # the menus' speed (tools/patches.py _gui_speed): the frame interval x 0.5 stored as the GUI speed
    # perspective projections' matrix (tools/patches.py _persp_matrix): the load of tan(fovy / 2) and the aspect ratio
    Site('persp_matrix', 'code', 'bd409800 1e2c1003 52b7f008 2d558801 1e202800 2d569404', 3),
    Site('persp_matrix_offset', 'code', 'bd409800 1e2c1003 52b7f008 2d558801 1e202800 2d569404', 5),
    # frustum projections' matrix (tools/patches.py _frustum_matrix): its four loads of left / right and top / bottom
    Site('frustum_lr0', 'code', '2d550001 52b7f008 bd409802 b900043f 1e213800 1e2e1001 1e222842 1e201820', 0),
    Site('frustum_lr1', 'code', '2d550001 52b7f008 bd409802 b900043f 1e213800 1e2e1001 1e222842 1e201820', 10),
    Site('frustum_tb0', 'code', '2d550001 52b7f008 bd409802 b900043f 1e213800 1e2e1001 1e222842 1e201820', 15),
    Site('frustum_tb1', 'code', '2d550001 52b7f008 bd409802 b900043f 1e213800 1e2e1001 1e222842 1e201820', 23),
    # projections' update (tools/patches.py _proj_update): the load of the matrix's dirty flag
    Site('proj_update', 'code', '39402008 aa0003f3 34000268 f9400268 91003261 aa1303e0 f9402d08 d63f0100', 0),
    # perspective projections' screen position to camera position (tools/patches.py _persp_unproject): the loads of
    # tan(fovy / 2) (y) and of it with the aspect ratio (x)
    Site('persp_unproject_y', 'code', 'bd409800 f900003f 1e201004 1e214000 bd000820 bd409800 bd40ac01 bd400442', 6),
    Site('persp_unproject_x', 'code', 'bd409800 f900003f 1e201004 1e214000 bd000820 bd409800 bd40ac01 bd400442', 18),
    # arrows' fall (tools/patches.py _arrow_gravity): the load of the gravity added to an arrow's velocity per update
    Site('arrow_fall_gravity', 'code', 'bd410a81 1e212849 bd410e81 1e21280a 94000000/fc000000 36000000/fff8001f f9404288 2d400500', 0),
    # Experimental shield-surf takeoff grace (#305): contact update, boost removal and launch request.
    Site('surf_contact', 'code', '3941d2a8 36080008/fff8001f bd4066a0 1e202008 5400000d/ff00001f bd403261 1e202028 5400000d/ff00001f', 0),
    Site('surf_boost_remove', 'code', '1e203820 2f00e401 aa1403e1 1e216800 bd003260 0f016680 f94006a0 94000000/fc000000', 0),
    Site('surf_jump_request', 'code', '36000000/fff8001f 52a82608 b9006668 b9008288 52800028 3900a288 2d488680 52800141', 0),
    # a stale actor in the target manager (tools/patches.py _stale_actor_helper, _stale_actor_target; #391, #393): the
    # helper that asks an actor for its link, and the camera target's inline copy of it
    Site('stale_actor_helper', 'code', 'b4000000/ff00001f f942b808 f9404500 14000000/fc000000 d65f03c0', 0),
    Site('stale_actor_target', 'code', 'f942ba68 f9404500 94000000/fc000000 12000008 390006e8 37000000/fff8001f 394002e8 35000008/ff00001f', 0),
    # the physics step's solver microsteps (tools/patches.py _solver_steps): the delta frame times 6
    Site('phys_solver_steps', 'code', '1e231002 1e3c1004 f9401a68 1e2c1009 1e220822 f9400108 1e202048 f9400514', 4),
    # a keyframed body's angular velocity toward its target (tools/patches.py _kf_angle): the call that takes the angle
    # of the turn left (hkQuaternion::getAngle, 2 acos(|w|))
    Site('kf_angle', 'code', '0e612800 0e0e3c08 0e040d00 0f3f5400 0ea0a800 6e180400 4e221c00 6e211c00 3c9983a0 '
         '94000000/fc000000 3cd883a6 1e2008c0', 9),
    # the sound system's frame (tools/patches.py _snd_frame_floor): the delta frame, at least 0.5, its timers' step
    Site('snd_frame_floor', 'code', '1e2c1001 1e212000 1e204c28 94000000/fc000000 b4000000/ff00001f bd415660 '
         'aa0003f4 7e21d800', 0),
    Site('gui_speed', 'code', 'bd0b2100 94000000/fc000000 f9400260 94000000/fc000000 52800020 94000000/fc000000 '
         'a9414ff4 a8c27bfd', 0),
    # MainShortCut's HoldShortCutBg: repair P_Capture_00's alpha after a fractional opening frame (#173).
    Site('quick_menu_capture_alpha', 'code', 'f9400268/ffc003ff bd405100 1e202008 54000000/ff00001f '
         'bd402100 1e2e1001 1e212000 54000001/ff00001f 90000001/9f00001f 91000021/ffc003ff '
         'aa1303e0 94000000/fc000000 52801fe8 39016408', 7),
    Site('pause_state', 'ref', '90000013/9f00001f b9400268/ffc003ff 35000008/ff00001f 90000008/9f00001f '
         'b9400108/ffc003ff 35000008/ff00001f b9400268/ffc003ff 34000008/ff00001f', 1),
    Site('event_mgr', 'ref', '9000000d/9f00001f 910001ad/ffc003ff f94001a0 aa1703e1 94000000/fc000000 aa1703e0 '
         '2a1f03e1 94000000/fc000000', 1),
    Site('controller_step', 'got', '90000008/9f00001f aa1f03f5 f9400108/ffc003ff 52800036 bd400108 b9411668 '
         '1ad522d8 8b150a77', 2),
    # (test tools only: the clock probe)
    Site('player_info', 'ref', '90000008/9f00001f 91000108/ffc003ff f9400100 b4000000/ff00001f 94000000/fc000000 '
         '7100001f 5400000c/ff00001f 91314260', 1),
    Site('world_mgr', 'ref', '90000008/9f00001f 91000108/ffc003ff f9400108 b4000008/ff00001f b946b908 7100051f '
         '54000001/ff00001f a9bf7bfd', 1),
    # the mouse camera (tools/patches.py _cam_stick, _cam_pitch, _cam_pitch_aim; runtime/hle/input.c): the camera's
    # stick input, which every camera action reads, and the square that the chase-like cameras apply to its vertical
    # part
    Site('cam_stick', 'code', 'd100c3ff fd000be8 f90017f3 a901fbfd 910063fd aa0003f3 f900001f 52800060', 0),
    Site('cam_pitch_chase', 'code', '1e208803 1e202008 bd41ce80 1e23cc2b bd41d281 1e212000 54000001/ff00001f '
         '52800039', 0),
    Site('cam_pitch_surf', 'code', '1e208803 1e202008 bd430260 1e23cc2d bd430661 1e212000 54000001/ff00001f '
         '2f00e400', 0),
    Site('cam_pitch_wakeboard', 'code', '1e208803 1e202008 bd433260 1e23cc2f bd433661 1e212000 54000001/ff00001f '
         '2f00e400', 0),
    # CameraAiming (the bow, its zoom, the scope): the load of its latStickScale for the vertical part
    Site('cam_pitch_aim', 'code', 'f9400268/ffc003ff 1e200923 910083e0 910063a1 bd400101 1e210860 bd4057e1 1e210809',
         4),
    # ... and CameraAiming2's (the camera for a held item)
    Site('cam_pitch_item', 'code', '94000000/fc000000 1e20400b 94000000/fc000000 f9400268/ffc003ff 1e200960 bd400101 '
         '90000008/9f00001f 1e210800', 5),
    # the cameras' controller turning its right stick around for the game's Camera X-axis / Y-axis options (Inverted:
    # the flags CameraRLReverse, CameraUpDownReverse): the calls that read them
    Site('cam_reverse_x', 'code', '94000000/fc000000 36000000/fff8001f bd413260 1e214000 bd013260 2a1f03e0 '
         '94000000/fc000000 36000000/fff8001f', 0),
    Site('cam_reverse_y', 'code', '94000000/fc000000 36000000/fff8001f bd413660 1e214000 bd013660 a9424ff4 a9417bfd '
         '9100c3ff', 0),
    Site('pc_button_group', 'code', 'd10183ff a9017bfd a90267fa a9035ff8 a90457f6 a9054ff4 910043fd '
         'aa0003f3 f90003e0 f9401800 2a0403f8 2a0303f5 2a0203f6 aa0103f4 b9000bff', 0),
    Site('pc_cursor_manager', 'code', 'd10143ff a9017bfd a9025ff8 a90357f6 a9044ff4 910043fd b9000be1 91006008', 0),
    Site('pc_cursor_activate', 'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd f9402415 aa0103f3 aa0003f4 f9002401', 0),
    Site('pc_pane_bounds', 'code', 'bd407020 2d4a0821 1e200824 bd408423 1e208825 1e230841 1e238842 1e2c1003', 0),
    # Map focus helpers: retain marker targeting without controller-style recentering on hover.
    Site('pc_map_focus', 'code', 'a9be7bfd f9000bf3 910003fd bd786800 aa0003f3 910063a1 bd786c01 91214000', 0),
    Site('pc_map_focus_target', 'code', 'd100c3ff a9017bfd a9024ff4 910043fd aa0103f3 aa0003f4 97ffffdc aa1403e0', 0),
    Site('pc_map_focus_now', 'code', 'd100c3ff a9017bfd a9024ff4 910043fd aa0103f3 aa0003f4 97ffffb3 aa1403e0', 0),
    # placed actors' traverse distance (tools/patches.py _traverse_scale): the scale the game multiplies every one by,
    # loaded from the actor debug manager, or 1 without it (Video > Draw distance)
    Site('traverse_scale', 'code', TRAVERSE, 13),
    Site('traverse_scale_default', 'code', TRAVERSE, 21),
    # the grass's view context (tools/patches.py _grass_range): its entry, with the two screen-size limits in s1, s2
    Site('grass_range', 'code', 'bd400024 bd000004 bd400425 bd000405 bd400825 2d011005 bd001005', 0),
    # ... and each layer's store of the camera scale its distance fades are measured with (_grass_fade)
    Site('grass_fade_blades', 'code', 'bd417349 aa1a03e0 94000000/fc000000 1e202120 a91ceffa 90000008/9f00001f '
         '1e20cd20 bd024360', 7),
    Site('grass_fade_quads', 'code', 'bd4172e9 aa1703e0 94000000/fc000000 1e202120 90000008/9f00001f 1e20cd20 '
         'bd000700', 6),
    # the blades' draw slots (tools/patches.py _grass_blade_slots): how many their manager makes, and the two passes
    # that stop at the 256th cell
    Site('grass_blade_slots', 'code', 'a9416ffc 52802001 52800103 aa1c03e0 aa1b03e2 94000000/fc000000', 1),
    Site('grass_blade_cap_a', 'code', '7100013f 7a401940 54000000/ff00001f 7103fe7f 54000008/ff00001f 71001d9f', 3),
    Site('grass_blade_cap_b', 'code', '79402509 34000009/ff00001f 79402908 34000008/ff00001f 7103ff7f 54000008/ff00001f '
         '7d4032c0', 4),
    # ... and the per-frame pass that points each slot at this frame's half of its shader block (count clamped to 256)
    Site('grass_blade_cap_c', 'code', BLADE_BUFFERS, 2),
    Site('grass_blade_cap_c_max', 'code', BLADE_BUFFERS, 5),
    # the blades' region test for each cell, near and far parts (tools/patches.py _grass_blade_lateral)
    Site('grass_blade_lateral_near', 'code', BLADE_LATERAL, 8),
    Site('grass_blade_lateral_far', 'code', BLADE_LATERAL, 13),
    # the terrain's distant trees (tools/patches.py _tree_ranges): the entry of their per-frame shader setup
    Site('tree_ranges', 'code', '90000008/9f00001f 91000108/ffc003ff f9400108 b4000008/ff00001f f9452908 '
         'b4000008/ff00001f 39406108 37280008/fff8001f 39402008 36000008/fff8001f d10143ff', 0),
    # a shrine apparatus fetching its input (tools/patches.py _gyro_scene_actor; runtime/pc_gyro_scene.c)
    Site('gyro_scene_actor', 'code', '2d59b28f 2d5ab689 94000000/fc000000 b5000000/ff00001f 9101d280 9101a281', 2),
    # per-action bindings (tools/patches.py _act_query; runtime/hle/bindings.c): the two queries and the mask table
    Site('act_hold', 'code', PAD_QUERY + ' b9411e68', 0),
    Site('act_trig', 'code', PAD_QUERY + ' b9401268', 0),
    Site('act_masks', 'ref', PAD_QUERY + ' b9401268', 5),
    # the store of an equipped weapon's, bow's or shield's durability, x100 (tools/patches.py _no_wear; from #296: the
    # setter 1.8.2 0x7000c809e8 finds the equipped item of a type w22 in the pouch and stores the new value w20)
    Site('no_wear_store', 'code', 'b9002174 5288fb08 72a00088 38686aa8 35000008/ff00001f 2a1403e0 2a1f03e2 '
         '94000000/fc000000', 0),
    # the weapon actor's own durability, x100 (tools/patches.py _no_wear_hit): a hit takes its cost w9 off the value w8
    Site('no_wear_hit', 'code', '4b090108 0aa87d08 1e220101 b9000268 1e212000 1a9f07e0 14000000/fc000000 f9400288', 0),
    # where the weapon's update calls that (no_wear_hit's function, a virtual method that every damage goes through):
    # the instruction after the call, the return address that tells a weapon's wear from damage to Link or an enemy
    Site('no_wear_ret', 'code', 'f9400288 2a0003f5 aa1403e0 f9415d08 d63f0100 b5000000/ff00001f 52800036 '
         '14000000/fc000000', 0),
    # Link's damage handling storing his new life, in quarter hearts (tools/patches.py _link_life): at its end, and on
    # the path that takes one quarter off
    Site('link_life_store', 'code', 'b90002b9 f9400300 94000000/fc000000 6b00033f 5400000d/ff00001f f9400300 b9400ff5 '
         '94000000/fc000000', 0),
    Site('link_life_tick', 'code', 'b90002a8 1e212000 1a9f07e0 14000000/fc000000 2a1f03fa 39715288 36080008/fff8001f '
         'bd42e660', 0),
    # the stamina setter's store, PlayerInfo +0xa4 (tools/patches.py _stamina)
    Site('stamina_store', 'code', '1e204008 94000000/fc000000 bd00a668 f9400ff3 a940fbfd fc4207e8 d65f03c0', 2),
    # the pouch taking arrows off for the player's bow (tools/patches.py _remove_arrows; Accessibility > Infinite arrows)
    Site('pouch_remove_arrows', 'code', 'd101c3ff a9017bfd a9026ffc a90367fa a9045ff8 a90557f6 a9064ff4 910043fd '
         '90000008/9f00001f aa0003f3 f9400108/ffc003ff aa0103e0', 0),
    # sead::LookAtCamera::doUpdateMatrix (tools/patches.py _lookat_update): its first load of the eye (+0x38); eye,
    # at (+0x44) and up (+0x50) make the view matrix written to x1 (free camera, runtime/hle/freecam.c)
    Site('lookat_update', 'code', '2d470801 2d480c00 1e232020 2d491404 1e240440 1e250400 54000000/ff00001f 1e233823', 0),
    # Cursour(agl debug)'s setup (its load of the debug cursor's pool object at +0x70, tools/patches.py
    # _debug_cursor_pool_guard): the game never maps the debug pool here, so that slot stays empty and the very
    # next load (the pool object's vtable) dereferences 0 — the crash before the first frame of issue #472.
    Site('debug_cursor_pool_guard', 'code', 'f9403a60 a904a3f5 f9400008 f9401908 d63f0100 b4000000/ff00001f '
         'aa0003f4 910123e0', 0),
    # Cursour(agl debug)'s pane update (its first instruction, tools/patches.py _debug_cursor_pane_guard), one step
    # past the pool guard: with the cursor's setup skipped the cursor is never made, so the pane the boot chain
    # hands this update as x1 — the caller's [param+0x20], a slot its ctor never writes — stays empty, and the
    # update's first load through the pane (its vtable) dereferences 0. Guard its entry, not each load: all of
    # them go through the same pane.
    Site('debug_cursor_pane_guard', 'code', 'a9ba7bfd a9016ffc 910003fd a90267fa a9035ff8 a90457f6 a9054ff4 '
         'd110c3ff f9400048', 0),
    # seadDebugMenuSystem's page lookup's entry (its load of the key's name for the byte-by-byte hash loop,
    # tools/patches.py _debug_menu_key_guard): with the key's name empty it hashes 0 through its own cbz's skip,
    # which is the answer for a name that isn't there (the search still ends in the game's not-found path).
    Site('debug_menu_key_guard', 'code', 'f9400669 39400128 34000008/ff00001f 2a1f03f7 91000529 1b157eea '
         '0b288157 38401528', 0),
    # the same lookup's second name load, feeding the key's virtual name getter and the same-pointer compare
    # (its load at +0x8, tools/patches.py _debug_menu_len_guard): a null name is treated as the compare loop's
    # mismatch (advance the search), never as a name the search could mistake for a page's.
    Site('debug_menu_len_guard', 'code', 'f9400675 f9400d08 d63f0100 f94007e8 eb0802bf 54000000/ff00001f '
         'f9400669 aa1b03ea', 0),
    # the same lookup's string compare, re-loading the key's name (tools/patches.py _debug_menu_page_guard):
    # a page named without a name faults this byte-by-byte compare on 0 — run32's crash.
    Site('debug_menu_page_guard', 'code', 'f9400669 aa1b03ea 3840152b 3840150c 6b0c017f 54000001/ff00001f '
         '3400000b/ff00001f f100054a 54000001/ff00001f 91000739', 0),
    # the same compare's other side (its load of the candidate page's name the page getter just returned,
    # tools/patches.py _debug_menu_cand_guard): the static page table's names are unpopulated too, and the
    # compare's byte load of that null faulted one step past the key guards (run33's crash) — again the
    # compare's not-equal answer is the right one for a name that isn't there (advance the search).
    Site('debug_menu_cand_guard', 'code', 'f94007e8 eb0802bf 54000000/ff00001f f9400669 aa1b03ea 3840152b '
         '3840150c 6b0c017f', 0),
    # the page name's '/'-splitting step (its load of the name at +0x8, tools/patches.py _debug_menu_path_guard):
    # the empty-name path it already takes (return true, page 0) is the right answer for a name that isn't there.
    Site('debug_menu_path_guard', 'code', 'f9400448 aa0103f3 39400108 34000008/ff00001f f9400048 aa0203e0 '
         'aa0203f4 f9400d08', 0),
    # the page lookup by hash (its load of the key's name at +0x8, tools/patches.py _debug_menu_hash_guard):
    # the empty-name path (hash 0) is the one it takes for a name of nothing.
    Site('debug_menu_hash_guard', 'code', 'f94006a9 39400128 34000008/ff00001f 2a1f03f5 91000529 1b147eaa '
         '0b288155 38401528', 0),
    # agl's ShaderHolder queue (the title screen's first shader link, f_7000f9e384's first load through the
    # holder's queue member — its [holder+0x28], empty on machines whose boot never filled it, tools/patches.py
    # _shader_queue_guard): with no queue nothing is linked yet, and the count-load's own <1 exit returns as the
    # game's own answer for an empty queue (its out params were already zeroed; its single caller ignores the
    # result). The queue is dereferenced nowhere else — this one load guards the whole member.
    Site('shader_queue_guard', 'code', 'b942dada 7100075f 5400000b/ff00001f 914152c8 2a1f03fb '
         '9000001c/9f00001f 9100039c/ffc003ff 91348108', 0),
    # run35's debug-menu registration crash (tools/patches.py _debug_menu_reg_*): the title's registration calls
    # f_7000ec74d8 and f_7000ec7690 with a null table object — the debug menu whose init never completed reports
    # 0 entries and the caller's csel hands the wrappers xzr — and the count store through table+0x288/0x2b8
    # faults (0x2b8). Entry guards; plus the same table's copy variant f_7000ec7708, whose first load is that
    # +0x2b8 count. With no table there is nothing to register: return, the guest's ret at the entry.
    Site('debug_menu_reg_288_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd aa0003f5 '
         '910a2000 aa0203f3', 0),
    Site('debug_menu_reg_2b8_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd aa0003f5 '
         '910ae000 aa0203f3', 0),
    Site('debug_menu_reg_copy_guard', 'code', 'a9bb7bfd f9000bf9 a9025ff8 a90357f6 a9044ff4 910003fd '
         'b942b808 52800316', 0),
    # the whole registration cluster past those four (the sweep of the title's registration function f_70012567bc
    # and of the f_7000ec74d8..f_7000ec7cd8 range, tools/patches.py _debug_menu_reg_guard): the +0x288 copy
    # variant faults at run36 (its 55 calls take the same csel'd x25 table), and the cluster carries the rest of
    # the table's vectors -- the +0x298/+0x2a8/+0x2c8 vectors' wrappers, copy variants, and each vector's
    # free/reset (its data pointer at vec+8 then a cbz) -- all taking this table, all faulting inside their first
    # two instructions with a null one. Same entry guard, so no later boot step relearns this the hard way.
    Site('debug_menu_reg_288c_guard', 'code', 'a9bb7bfd f9000bf9 a9025ff8 a90357f6 a9044ff4 910003fd '
         'b9428808 52800316', 0),
    Site('debug_menu_reg_288f_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd f9414808 '
         'aa0003f3 b4000008/ff00001f', 0),
    Site('debug_menu_reg_2b8f_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd f9416008 '
         'aa0003f3 b4000008/ff00001f', 0),
    Site('debug_menu_reg_298_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd aa0003f5 '
         '910a6000 aa0203f3', 0),
    Site('debug_menu_reg_298c_guard', 'code', 'a9bb7bfd f9000bf9 a9025ff8 a90357f6 a9044ff4 910003fd '
         'b9429808 52800316', 0),
    Site('debug_menu_reg_298f_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd f9415008 '
         'aa0003f3 b4000008/ff00001f', 0),
    Site('debug_menu_reg_2a8_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd aa0003f5 '
         '910aa000 aa0203f3', 0),
    Site('debug_menu_reg_2a8c_guard', 'code', 'a9bb7bfd f9000bf9 a9025ff8 a90357f6 a9044ff4 910003fd '
         'b942a808 52800316', 0),
    Site('debug_menu_reg_2a8f_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd f9415808 '
         'aa0003f3 b4000008/ff00001f', 0),
    Site('debug_menu_reg_2c8_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd aa0003f5 '
         '910b2000 aa0203f3', 0),
    Site('debug_menu_reg_2c8c_guard', 'code', 'a9bb7bfd f9000bf9 a9025ff8 a90357f6 a9044ff4 910003fd '
         'b942c808 52800316', 0),
    Site('debug_menu_reg_2c8f_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd f9416808 '
         'aa0003f3 b4000008/ff00001f', 0),
    # and the +0x278/0x280 vector's trio just below the range above -- run37's fault: the title's other
    # registration step (f_700127add8) walks this vector through the same csel'd x25 null (its fill twin's count
    # store through table+0x278 was the fault), with the same shape one slot earlier than the range above.
    Site('debug_menu_reg_278_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd aa0003f5 '
         '9109e000 aa0203f3', 0),
    Site('debug_menu_reg_278c_guard', 'code', 'a9bb7bfd f9000bf9 a9025ff8 a90357f6 a9044ff4 910003fd '
         'b9427808 52800316', 0),
    Site('debug_menu_reg_278f_guard', 'code', 'a9bc7bfd a9015ff8 a90257f6 a9034ff4 910003fd f9414008 '
         'aa0003f3 b4000008/ff00001f', 0),
    # run38/run39's actor-create crash (tools/patches.py uinj_db_guard): the title's actor creation asks the thunk at
    # f_7000f9e5ec for the uinj actor database -- the scene world's +0x28 member plus a fixed 0x4e0 offset -- and that
    # member is empty (its build never ran, the same half-initialized title as the debug menu above); the target
    # f_7000ff3520's first load, the record count at [db+0x54158], faults dereferencing 0x4e0+0x54158 = 0x54638.
    # Guard the member load: with no database return a zeroed default record (see patches.py) -- the caller keeps it
    # as the actor's uinj record, which its param builder then reads: an empty name at +0x70, null fields and all
    # override flags clear, exactly what a record for an actor the database never learned should read as.
    Site('uinj_db_guard', 'code', 'f9401408 91138100 14000000/fc000000', 0),
    # run40's param-builder crash (tools/patches.py light_rig_flag_guard): with the zeroed default record installed,
    # the builder's entry loop asks the helper f_7000ff2d24 for entry #w25 of the record's light-rig parameter set
    # -- [record+0xf28] + 0x53658 + 0x160 * w25 (8 entries, csel'd) -- but the zeroed record's back-pointer reads 0,
    # leaving the entry base at 0x53658, unmapped: the loop's first read, ldrb w8, [x0, #0x48], faults at 0x536a0.
    # Guard the read on that: a base below 4 GiB (any real back-pointer is a heap pointer) skips the entry, which
    # is exactly what a record whose set was never built means. The helper's only call site; at: 1 pins the ldrb.
    Site('light_rig_flag_guard', 'code', '9400fefb 39412008 34000008/ff00001f', 1),
    # run41's param-object crash (tools/patches.py param_ctor_ctx_guard): the builder's tail hands its three param
    # objects to their constructors with x3 = the actor context (the builder's own x3, null here -- the same
    # never-built title context that emptied the uinj record above, its list head at +0x98 living on the context
    # object). f_7000ff64dc -- the run41 fault's home, lr 0x7000ff6798 -- keeps x3 as x19 and reads its entry array
    # to register the object: ldp w8, w9, [x19, #0x98] (count/capacity, then the slot store and the count bump)
    # faults dereferencing 0x98. Its own fields (x20 = x0, the built param block) are real, and f_7000ff6928 -- the
    # two sibling constructors' shared tail, called from f_7000ff64dc's own record loop (and nothing else) --
    # pushes through the same x19+0x98..0xa0 window: one entry guard on x3 covers the family. A sweep of the other
    # builder calls found no further context derefs (f_7000fe32a8's x20 reads the real stack block; f_70010133f4
    # stores). With no context there is no list to register in: the constructors' whole job is that registration,
    # so returning without building is exactly what a context-less actor means.
    Site('param_ctor_ctx_guard', 'code', 'd10183ff a9017bfd f90013f9 a9035ff8 a90457f6 a9054ff4 910043fd '
         '29406037', 0),
    # run42's param-list crash (tools/patches.py actor_param_ctx_guard): past the guarded constructors the builder
    # f_7000fb2804 reached its message-parameter step -- f_7000fe9210 reads the descriptor count through x1 at its
    # entry (the builder's context, x20 = its x3, straight through) and gates the catalog it copies entries from on
    # [*catalog_static+0x28] >= 0x4c (76: the message table's version) -- and with the context null, [0+4] faulted
    # at 0x4; with the gate open, its copy loop faults on the never-built catalog (static 0x7001e36048, still 0 in
    # bss: the title init that loads the message files never ran, the same init behind the uinj record and the
    # param-registration list). One entry guard on the context skips the whole builder: its sweeps under run41/42
    # showed every other deref through the record or the real stack block, and its caller ignores its return.
    Site('actor_param_ctx_guard', 'code', 'a9ba7bfd a9016ffc 910003fd a90267fa a9035ff8 a90457f6 a9054ff4 '
         'd10ac3ff 528bb008 aa0303f4', 0),
    # run45's param-transfer crash (tools/patches.py param_list_xfer_guard): the consumer of the construction the
    # param_ctor guard skipped. The actor-creation step f_7001263218 hands the actor's param block (x0 + 0x150) to
    # the transfer f_7000ffb320 -- read the vector head ([x0+0x9d8] count, [x0+0x9e0] data), clamp to record index
    # 0, read [record+0x258] -- and the guarded ctor left the vector never built, data 0: the record-0 read
    # (smaddl of 0 * 0x5f0, then ldr w9, [x8, #0x258]) faulted at 0x258 exactly. The whole body is the transfer of
    # record 0's param object (its lookup x24 feeds f_7000573698(x24+0x40), f_7000ffb468, the stores to +0x154/
    # +0x158, the push onto the record's +0x98 list), so a null vector means nothing to transfer -- return; the
    # sole caller ignores the result (it re-derives x0 from x20 right after the bl at 0x70012632f8).
    Site('param_list_xfer_guard', 'code', 'a9bb7bfd a90167fa a9025ff8 a90357f6 a9044ff4 910003fd b949d808 '
         '5280be09', 0),
    # run46's default-param block crash (tools/patches.py param_subsys_guard): the title actor's init step
    # f_7001263218 (its fault lr 0x70012633fc, count<1 path) loads the actor's default-param subsystem through
    # field [x20+0x3680] and initializes it: str wzr, [x23, #0x220] clears the record count, f_700100fd54 copies
    # the +0x220..+0x225 flag window into +0x500..+0x540, two record headers go through the array at [x23+0x230]
    # (bl f_700100fd70 twice), and sibling subsystem stores follow through fields [x20+0x3388]/+0x3678/+0x3900.
    # The never-built title init left the field 0 -- the first store faulted at 0x220 exactly (x23 0 in the dump).
    # The whole block sits between the entry label and the count<1 merge label (the b.lt at 0x70012636dc reaches
    # 0x7001263758 anyway): with no subsystem there is nothing to initialize, so jump to that existing label --
    # its flow reads only the real stack block and embedded actor fields (x19 + 0x10/0x78) and the guarded-safe
    # param getters f_7000f75e40/f75e5c/f75e84.
    Site('param_subsys_guard', 'code', 'f95b4297 aa1703e0 b90222ff 94000000/fc000000', 0),
    # run47's gfx::System notify crash (tools/patches.py gfx_system_list_guard): the actor init's tail notify step
    # f_7000f7658c dispatches the gfx::System's notification f_700123b8f8 through the actor's vtable (blr x8 at
    # 0x7000fb4d2c, slot +8 of the object at [x20+0x5c90]). It loads the system's actor-list base through field
    # [x0+0x58] -- x21 -- and reads the list's entry count through it: ldr w9, [x21, x9] with x9 the list head
    # offset 0x5610, faulting at 0x5610 exactly (x21 0 in the dump) -- the never-built title init left the base
    # null. The sweep: the mutex step above the fault gates itself (its cbz skips the lock when the static's
    # object is absent), the count's compare reads through the [0x7001d76bf8] static, off the guarded path, and
    # the notify loop below (bl f_7001236614 per entry, vtable +0xb8 name) runs only for entries of the skipped
    # list. The busy-lock branch above already skips everyone through the function's own return label, so jump
    # there: the blr's caller ignores the result (mov x0, x19 on its very next instruction).
    Site('gfx_system_list_guard', 'code', 'f945fd08 b8696aa9 f96b0eaa', 1),
    # run48's actor-init tail crash family (tools/patches.py actor_subsys_tail_guards, four sites): the actor's
    # subsystem fields carry the tail of the title actor init f_7001263218, and the never-built title init left
    # them 0 like the vector, the context, the subsystem and the gfx list before them. (1) 0x7001263c9c is the
    # fault: the notify step's return path registers the vtable through field [x20+0x5cd8] -- str x9, [x8, #0x100]
    # -- faulting at 0x100 with x8 0 (host f_7001263218+0x1b76: mov [rax+0x100],rcx right after the
    # f_7000f7658c call, rax = [rax+0x5cd8]). (2)+(3) the two registry lookups load through field [x20+0x55e8]
    # into x21 and hand it to f_7000f778dc, which reads [x0+0x38]/[x0+0x40] through it -- a null field would
    # fault there; the guest's own not-found branches (result -1) reach 0x70012642d8/0x70012642e0 and store 0
    # through [x19+0x10f8]/[x19+0x1100], so skip there on null. (4) the consumer loads field [x20+0x55f0] into
    # x0, stores it through [x19+0x1108] (the same null), and calls vtable slot +0xc0 for a flag byte: null has
    # no vtable, so skip to the function tail the guest's own count==0 branch (the param vector the guarded ctor
    # left empty) already reaches.
    Site('actor_reg_field_guard', 'code', 'f96e6e88 d503201f 10006209 52801400 aa1c03e1 f9008109', 5),
    Site('actor_list_reg_guard_1', 'code', 'f9451660 97ff4ed5/94000000 f96af695', 2),
    Site('actor_list_reg_guard_2', 'code', 'f9087e68 f0001d08/9f00001f 910da108/ffc003ff f96af695', 3),
    Site('actor_subsys_ref_guard', 'code', '91004368 90001fa9/9f00001f 910ca129/ffc003ff f96afa80', 3),
    # run49's subsystem-consumer crash (tools/patches.py subsys_consume_guard): the actor init's tail hands the
    # allocator's subsystem block plus the stack descriptor (sp + 0x58) to the subsystem consumer f_700126daf0
    # (bl 0x7001263f00); the descriptor's getter result at [x1+8] is f_7001016510's null-guarded answer for the
    # field [x20+0x51d8] the never-built title init left 0 -- the getter returns 0 (its cmp/csel is null-safe),
    # and the consumer reads the flag word through it: ldr w21, [x8, #0x298] faulted at 0x298 exactly (x8 0 in
    # the dump; host pc f_700126daf0+0xde). The sweep of the consumer's body: the same value's copy at
    # [x20+0x10] is read again at [x8+0x2b4] (same null), every other dereference goes through the real
    # allocation (x20 = x0) or the real descriptor ([x19] = [sp+0x58] = x28), and the getter value's other home
    # -- the stack slot [sp+0x60] -- is never read again. So return from the entry: the sole caller ignores the
    # result (mov w0, #0x6c0 on its very next instruction) and the subsystem simply registers nothing.
    Site('subsys_consume_guard', 'code', 'd10383ff a9097bfd a90a67fa a90b5ff8 a90c57f6 a90d4ff4 '
         '910243fd f9400428', 0),
    # run50's registry-lookup crash (tools/patches.py registry_lookup_guard): the actor init's tail hands the
    # never-built subsystem registry (field [x2+#0x55e8] of the real block, null like the fields the family-15
    # guards cover) to the actor init's subsystem initializer f_7001274db4 (bl 0x7001264050), whose four
    # registry lookups (bl 0x7000f778dc at 0x7001274df8/0xe70/0xee8/0xf60) fault at [x0+0x38] on the null
    # registry -- the lookup's first instruction is ldrsw x8, [x0, #0x38] (the entry count), then the array at
    # [x0+0x40]. The guest's own empty-registry answer is -1: its count==0 branch reaches the return at
    # 0x7000f779b0 with w0 = #-1, and all four of this family's callers gate on it (cmn w0,#1 b.eq skips the
    # entry read [x21,#0x40] with the found object's stores). So one guard at the lookup's entry returns -1 on
    # a null registry -- a null registry is exactly an empty one -- and covers all 18 of the lookup's call
    # sites (the other families' guarded loads jump past the call before it runs).
    Site('registry_lookup_guard', 'code', 'd10183ff a9017bfd f90013f9 a9035ff8 a90457f6 a9054ff4 '
         '910043fd b9803808', 0),
    # run51's record-subsystem init crash (tools/patches.py record_subsys_init_guard): the actor init's tail
    # builds the title actor's record subsystem with f_700124fccc (bl 0x700126407c, the sole caller, x0 = the
    # freshly allocated 0x31d8 subsystem block, kept through [x19+0x3a8] and ignored after the call). The init
    # loads the registry base it stored into the block's own field [x25+0x5d0] (only stored when the lookup
    # f_700155ddc4 answers non-null -- it answers null here) and drives it through the param-array thunk
    # f_7000fb1224 (ldr x8, [x0, #0x40] -- x0 0, fault 0x40 exactly, host f_7000fb1224+0x14). The sweep of the
    # whole function: both thunk calls (0x700124feb4/0x700124ffb0) fault on the null field, and so does every
    # later chain through it -- the record store's sibling field [x25+0x5d8] (block 1's allocation x23, the
    # consumer's own ldr x8, [x0] at 0x700124fff0 right after the second thunk call), the param loop's vtable
    # call through [x27+0x5d8] (0x700125036c), the third field read's [x8+0x38] chain (0x7001250438, the guest's
    # own null-name skip cbz comes one deref too late), and the tail's f_7000faa8b8 record-destroy step through
    # [x19+0x3c] the skipped blocks would have built. Every dereference of the null field and its unfilled
    # siblings dies inside this one function, and the sole caller ignores the result (mov w0, #0x178 on its very
    # next instruction, the next subsystem's alloc) -- so one entry guard on the null field returns from the
    # whole record init, exactly what a never-built registry means.
    Site('record_subsys_init_guard', 'code', 'd10583ff a9107bfd a9116ffc a91267fa a9135ff8 a91457f6 '
         'a9154ff4 910403fd 52821f08 aa0203f8 aa0103f6 aa0003f9 8b080000 2a1f03e1 52840002/7f800000', 0),
    # run52's subsystem-list registration crash family (tools/patches.py subsys_list_guards, two sites): the
    # actor init's tail registers the actor-list subsystem block at [x19+0xa28] (a real allocation) with its
    # registrar f_70012354dc (bl 0x70012641a4, its sole caller) -- the block's actor-list base field
    # [x0+0x58], the same field the gfx::System notify reads through (gfx_system_list_guard), is the null one
    # the never-built title init left: the registrar's first use stores its resume-callback adr through it,
    # str x8, [x22, #0x5458] -- the fault 0x5458 (host f_70012354dc+0xf7: mov [rcx+0x5458],rax, rcx =
    # [r15+0x58]) -- and the sweep of its body found every later chain through the same null base: the
    # record links [x22+0x5450]/+0x5460/+0x5448, the manager reads [x22+0x5208] twice, and after the four
    # stores the reload re-reads the base and its consumer faults one step later (ldr w3, [x8, #0x108] at
    # 0x7001235540, 0x108 waiting), so the guard returns from the entry. The sibling registration step the
    # tail calls right after (bl 0x70012641ac, f_7001237d00, also its sole caller) loads the same field and
    # reads the manager's entry through it: ldr x8, [x8, #0x5208] (0x5208 waiting) -- same entry return.
    # Both callees' results the tail ignores (ldr x0, [x19, #0xa28] on their very next instructions), the
    # loop's per-entry vtable steps and the after-tail consumers run only through the null base, and the
    # guarded registry lookups the tail reaches next (actor_list_reg_guard_1/2) already skip on null.
    Site('subsys_list_init_guard', 'code', 'd10183ff a9017bfd a90267fa a9035ff8 a90457f6 a9054ff4 '
         '910043fd f9402c16', 0),
    Site('subsys_list_reg_guard', 'code', 'a9be7bfd a9014ff4 910003fd f9402c08 aa0003f3 f9690508', 0),
    # run53's subsystem record family (tools/patches.py subsystem param guards, two sites): the boot's first
    # function past the whole guarded actor-init tail, f_70012642e8, looks up the subsystem block with the
    # thunk f_7000fb272c (bl 0x700126437c) -- a real block (the dump's x0 0x72d5bbd048) whose record fields
    # the never-built title init left null. Its first use stores the mode flag through the record field,
    # ldr x8, [x0, #0x3388] (the guard's pattern anchor) and str w24, [x8, #0x18] -- the fault 0x18 (host
    # f_70012642e8+267: mov DWORD PTR [rcx+0x18],edx, rcx = [rax+0x3388]); the guard skips just the store,
    # the block's own fields the later stores write through x0 (host mov [rax+0x43c0]) stay. The block's
    # +0x55f0 consumer self-gates (cbz 0x70012643f0), the first loop is count-gated, and the sweep's one
    # other unguarded chain is the param array: ldr x21, [x19, #0x3900] into the loop head's ldr w8, [x21,
    # #8] (the fault 0x8 waiting) -- the guard jumps the whole loop to its own count skip, the label the
    # count's b.lt/b.eq reach (a null array means zero entries, exactly what the skip answers).
    Site('subsys_record_mode_guard', 'code', 'f959c408 52800049/7f800000 52a8100a/7f800000 aa0003f3 '
         'b9001918 52887808/7f800000 8b080008 f96af814 b9000109 528000c9/7f800000 b900610a '
         '529ae14a/7f800000 72a7a46a/ff80001f', 4),
    Site('subsys_param_array_guard', 'code', 'b9410a68 7100051f 5400034b/ff00001f f95c8275 2a1f03f4 '
         '5285bc16/7f800000 b9400aa8', 3),
    # run54's entry-table lookup crash (tools/patches.py subsys_entry_lookup_guard): the boot's walk past the
    # guarded subsystem record reaches the name-entry lookup f_7000eceac8 (the bl 0x7000ecea90 in its thin
    # wrapper f_7000ecea7c, its sole caller -- the dump's lr 0x7000ecea94; x0 = the subsystem block found at
    # 0x72d5242958, a real object) and reads its bound pair through the table base the never-built title init
    # left null in the block's field [x0+0x20] -- ldr x9, [x0, #0x20] and ldrh w9, [x8] -- the fault 0x0 (host
    # f_7000eceac8+d8: movzx eax, WORD PTR [r9+rsi*1], rsi = the null base, the index csel'd to 0 since the
    # count [x0+0x18] <= 1). The sweep of the whole lookup: its entry loop reads the entries through the
    # sibling field [x0+0x30] (ldr x0, [x25, x8] at 0x7000eceb60, also null -- the next fault waiting), and
    # every later deref runs on found entries (the guest's own cbz x0 skips null ones) or the vtable/string
    # work; the wrapper re-reads the same two fields only on the found path, after its tbnz w0, #0x1f test
    # routes a negative answer to its own mov w0, #-1 -- the not-found answer the never-built table already
    # is, so the guard returns it from the lookup's entry, and the found path the -1 answers is exactly the
    # boot's state today: nothing to find.
    Site('subsys_entry_lookup_guard', 'code', 'a9ba7bfd f9000bfb a90267fa a9035ff8 a90457f6 a9054ff4 '
         '910003fd b9401808 6b01011f f9401009 b940280a 1a9f8028 8b28c928 79400109 79400508', 0),
    # run55's indexed subsystem-entry crash family (tools/patches.py index-get guards, three sites): the
    # boot's next init step f_7001264644 (the frame lr 0x70012646b4) looks up five subsystem entries by
    # name through the guarded wrapper chain (its cbnz/cbz paths all ran clean in run55), falls back to
    # the indexed getEntry lookups, and faults in f_7000fb42f8: it clamps the asked entry to the bound
    # it reads from a global (its first use, the ldrsh w9,[x8] -- a real address), then reads its bound
    # pair through the table base the never-built title init left null in the block's field [x0+0x20]
    # (the dump's x0/x20 0x72d5242958, a real block) -- ldr x8, [x0, #0x20] and ldrh w10, [x10, #2] --
    # the fault 0x2 (host f_7000fb42f8+8d: movzx ecx, WORD PTR [rsi+rcx*4+0x2], rsi = the null base).
    # The sweep of the whole lookup: its entry array comes through the sibling field [x0+0x30] (the ldr
    # x19, [x9, x8, lsl #3], the next fault waiting on the same never-built init), the per-entry virtual
    # call runs on found entries (its cbz x19 skips the array's holes), and the not-found answers are
    # the guest's own mov x0, xzr -- a null entry, which every caller tests (cbnz/cbz, or the csel after
    # cmp x0, #0, or passing it as a found-entry pointer to be tested deeper) and the init step stores
    # straight into its subsystem fields. Two shape-identical siblings the same step calls right after
    # -- f_7000fb44b4 (bound global 0xf38, two call sites) and f_7000fb45dc (global 0xb00, three call
    # sites, the later name lookups' fallback) -- read the same two fields the same way and would fault
    # in turn, so each of the three gets the same entry guard answering the guest's own null entry:
    # exactly what a never-built table is, nothing to get. (Their clones f_7000fb9438/f_7001068190 read
    # the same fields too but are not on this boot path; they will bring their own family if reached.)
    Site('subsys_index_get_guard_1', 'code', 'a9be7bfd f9000bf3 910003fd 37f803a1/fff8001f f0007408 '
         '913d0108 b940180a f9400108 79c00109 f9401008 6b09015f 1a9f8129 8b29c90a 7940054a', 0),
    Site('subsys_index_get_guard_2', 'code', 'a9be7bfd f9000bf3 910003fd 37f803a1/fff8001f f0007408 '
         '913ce108 b940180a f9400108 79c00109 f9401008 6b09015f 1a9f8129 8b29c90a 7940054a', 0),
    Site('subsys_index_get_guard_3', 'code', 'a9be7bfd f9000bf3 910003fd 37f803a1/fff8001f 90007428 '
         '912c0108 b940180a f9400108 79c00109 f9401008 6b09015f 1a9f8129 8b29c90a 7940054a', 0),
    # run56's subsystem list family (tools/patches.py entry-name/pick guards, two sites): the init step's
    # last lookups f_700126b908 (the frame lr 0x7001264754; x0 = the real actor block at 0x72d523a6e8) read
    # a subsystem entry through its list base, three dereferences down: ldr x8, [x0, #0x158] (the dump's x0
    # -> real) and ldr x8, [x8] then the list field ldr x8, [x8, #0x5c80] -- the never-built title init left
    # it null -- and its first use faults: ldr x0, [x8], the fault 0x0 (host f_700126b908+65: mov rcx, QWORD
    # PTR [rax]). Both consumers' own absent paths return the module's unknown-name string (0x70015e615b) --
    # A right after the entry get's cbz x0 (its label L_700126b95c), B as its default case (L_7000ffc44c) --
    # so a null list base answers through each function's own string return: A's guard skips the load and
    # the whole found-entry virtual chain to that label, B's the entry-array indexed load. The sweep of all
    # 0x5c80 dereferences in the module found exactly these two consumers (plus B's count field 0x5c78 read,
    # a sibling load through the same real base -- it answers 0 and the guest's own cbz paths follow).
    Site('subsys_entry_name_guard', 'code', 'f940ac08 2a1f03e1 f9400108 f96e4108 f9400100', 4),
    Site('subsys_entry_pick_guard', 'code', '6b02013f 540000e9/ff00001f f96e4108 f862d913', 3),
    # run57's directory-iterator family (tools/patches.py dir_entry_accessor_guard): the title step
    # f_700009d950 (the frame's caller, a save-dir path read: bl 0x700009a7ec opened it, bl 0x700009b77c
    # read 0x100 bytes -- a real read, the dump's x0/x1 0x72d636a230 the handle at [object+0x2a0]) reaches
    # through its wrapper f_700007dfdc (the bl 0x700009d9d8, the dump's lr 0x700009d9dc) the leaf accessor
    # f_700007eb78: it probes the tag 0x2002 at the handle's +0x14/+0x20/+0x2c (three entry sizes of the
    # fs-iterator's header) and its common tail reads the value dword after the tag, ldr w0, [x8, #4] --
    # x8 the csel leaves 0 when no probe matches, the fault 0x4 (host f_700007dfdc+bc, the inlined leaf
    # tail: mov edx, DWORD PTR [rax+4], rax = 0; on our machine the handle carries no 0x2002 tag, the
    # never-built fs state left it raw). The sweep of the leaf: its three probe reads run on the real
    # handle -- the tail is its only dereference, so the guard answers the neutral 0 there, exactly the
    # offset the value is used as: the caller wrapper stores it into the step's field [x19+0x298] (used
    # as an entry's offset, 0 = at the buffer head), and the other two call sites (f_700009ed70's two
    # saves-list iterations) add the answer straight onto the entry buffer base -- entry-at-offset-0, the
    # same shape a fresh read buffer has.
    Site('dir_entry_accessor_guard', 'code', 'aa0003e8 52840049 78414d0a 6b09015f 54000100/ff00001f '
         'aa0003e8 78420d0a 6b09015f 54000080/ff00001f 7842cc08 6b09011f 9a9f0008 b9400500 d65f03c0', 12),
    # run58's tag-0x2001 sibling family (tools/patches.py accessor guards 2/3): the same path's next step
    # f_7000f07ee0 (the BFSAR open -- the dump's x6/x7 spell "DummySound.bfsar", the newest RomFS read)
    # bl f_700007ead4 (the bl 0x7000f08114 -- the dump's lr 0x7000f08118; x0 = the handle at [x19+0x560],
    # the dump's x0 0x72d636a230 -- the same raw handle reached through the step's own object field, its
    # x19 0x72d6369cd0 a fresh object for this step): it probes the tag 0x2001 at
    # the same three offsets (csel x8, x0, xzr, eq), its tail reads the value dword at +8 (the two data
    # offsets of the fs-iterator header's three entry sizes), ldr w0, [x8, #8] -- the fault 0x8 (host
    # f_700007ead4+4c: mov edx, DWORD PTR [rax+8], rax = 0). The sweep: its sibling leaf f_700007eb40 (tag
    # 0x2001, tail ldr w0, [x8, #4]) is the next fault waiting -- f_700009dbf0, the very next call of the
    # same step (bl 0x7000f0813c), starts with bl 0x700009dc18 f_700007eb40 on x20 = [object+0x2a0] = the
    # same handle 0x72d636a230. And the callers consume the answer as an offset or size, so both guards
    # answer the neutral 0 (last run's tag-0x2002 leaf did): f_7000f07ee0 aligns the allocation to 0x1000
    # (size 0 answers 0x1000 bytes), f_700009dbf0's cmp answer, requested; b.ls skip answers its own mov
    # w0, wzr (nothing read), and f_700009ecb4's add x1, x19, w0, sxtw gets the entry at offset 0 -- the
    # shape the raw handle already is. (The six inline tag-0x2001 probe sites in the module are other
    # functions on other objects; they will bring their own family if reached.)
    Site('dir_entry_accessor_guard_2', 'code', 'aa0003e8 52840029 78414d0a 6b09015f 54000100/ff00001f '
         'aa0003e8 78420d0a 6b09015f 54000080/ff00001f 7842cc08 6b09011f 9a9f0008 b9400900 d65f03c0', 12),
    Site('dir_entry_accessor_guard_3', 'code', 'aa0003e8 52840029 78414d0a 6b09015f 54000100/ff00001f '
         'aa0003e8 78420d0a 6b09015f 54000080/ff00001f 7842cc08 6b09011f 9a9f0008 b9400500 d65f03c0', 12),
    # run58's other half: the family's two leaves that probe the third tag 0x2000 (cmp w9, #2, lsl #12 is
    # the exact-equality test for it) -- f_700007eaa0 (tail ldr w0, [x8, #8], the bl 0x7000f359a0 in the
    # step's sibling f_7000f35930 right behind f_700009dbf0) and f_700007eb0c (tail ldr w0, [x8, #4], the
    # bl 0x700009dcf0/0x700009ecfc with its tag-0x2000 sibling f_700007eaa0) -- both would fault in turn
    # on the same untagged handle, both get the same guard answering offset 0.
    Site('dir_entry_accessor_guard_4', 'code', 'aa0003e8 78414d09 7140093f 54000100/ff00001f aa0003e8 '
         '78420d09 7140093f 54000080/ff00001f 7842cc08 7140091f 9a9f0008 b9400900 d65f03c0', 11),
    Site('dir_entry_accessor_guard_5', 'code', 'aa0003e8 78414d09 7140093f 54000100/ff00001f aa0003e8 '
         '78420d09 7140093f 54000080/ff00001f 7842cc08 7140091f 9a9f0008 b9400500 d65f03c0', 11),
    # run60's zero-size-read family (tools/patches.py fs_read_zero_guard): the accessor guards' answer 0
    # flows on -- the step f_7000f07ee0 takes the guarded size answer (bl 0x7000f08114 f_700007ead4, the
    # dump's lr 0x7000f08118) into bl f_7000007c20 (x0 = that answer) and allocates 0 bytes (a null pool
    # buffer stored to [x19+0xbf8]), then calls bl f_7000f0813c f_700009dbf0 -- its read step: blr a
    # vtable, bl f_700009b860 seek(offset 0 -- the SDK takes it fine), bl f_700009b77c read(x0 = the file
    # at [x21+0x2f0], x1 = the null buffer, x2 = 0): the wrapper's success tail (bl 0x700009a97c the SDK
    # import thunk f_70015a1110 through its GOT slot -- its lift f_700009a93c +0x40, the dump's frame
    # 700009a980) reaches the SDK's ReadFile, which R_UNLESS(buffer != nullptr) answers 0x2f5e02 --
    # fs ResultNullptrArgument (module 2, description 6063 -- the run60 svcBreak info print, its api
    # string 0x7002e0bb62 "ReadFile" in the StoreContext) -- and sead's X macro aborts: "SDK has been
    # aborted or failed assertion with no message." The sweep: every file read in the step goes through
    # the wrapper f_700009b77c (its three bl callers: the step f_700009d950 reads its real 0x100 bytes,
    # f_700009dbf0 is this one, f_700009dcc8 its sibling) and every caller consumes the answer x0 as the
    # read count with cmp answered, requested -- so the guard answers 0 bytes read, success, when the
    # request is 0 (a zero-byte read reads nothing; the SDK's null check never runs, and on our machine
    # the host file's real contents were never at issue -- the assert is client-side, before the IPC).
    Site('fs_read_zero_guard', 'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd f9400008 aa0303f3 aa0203f4 '
         'aa0103f5 aa0003f6 f9404108 d63f0100 36000140/ff00001f 9100a2c0', 0),
    # run61's deeper null-buffer read (tools/patches.py fs_read_null_buffer_guard): the wrapper's entry
    # guard took the zero-size request, but the step's read went on -- run61's abort is the same fs
    # ResultNullptrArgument (0x2f5e02, svcBreak info 723ffff068) at the same frame 700009a980: the
    # wrapper's success tail branches into its impl f_700009a93c (bl 0x700009a97c the SDK import thunk
    # f_70015a1110), whose x1 is not the caller's buffer argument but the object's own buffer field,
    # ldr x1, [x20, #8] -- run61's request carried a nonzero size, so the real invariant is the null
    # buffer field itself, not a zero size. The sweep: the impl has no bl callers at all -- every route
    # to it is the wrapper's two tail branches (the error tail f_700009aeb0 sits after the wrapper's
    # other callers' bl 0x700009b7cc/0x700009dd78) and the wrapper's own blr -- so one guard on the
    # impl entry's [x0+8] covers every route: it answers 0 bytes read, success, and the wrapper's
    # callers already treat count 0 as the nothing-read path (their cmp answered, requested).
    Site('fs_read_null_buffer_guard', 'code', 'd10103ff a9017bfd a90257f6 a9034ff4 910043fd aa0303f3 '
         'aa0203f5 aa0103f6 aa0003f4 94000408 f9400681 910023e0 aa1603e3', 0),
    # run63's null fs-state family (tools/patches.py fs_state guards): the read guards answered, the
    # step f_7000f07ee0 ran on -- and passed its never-built fs state (the dump's x21 = 0: its own
    # cbnz at +0x60 took the no-caller-buffer branch, so the argument stays 0) into the accessor
    # thunks: bl f_7000f0814c f_700008f87c -- which re-aims x0 at its x1 (the state) -- hits the
    # thunk f_700007e05c ldr x0, [x0, #8] on the null state: the run63 signal 11 accessing 0x8 at
    # the dump's host pc f_700007e05c+10, x6/x7 still spelling "DummySound.bfsar". The sweep of
    # every dereference of that object in the step: the thunk f_700007e05c (tail b f_700007f704 ->
    # bl f_700007eee0, base + signed offset at +0x34; callers f_700008f87c and f_700008f8a0 pack
    # orr x0, x9(=4), x8, lsl #4 -- the tag-4 handle family #24/#25 answered neutral), its sibling
    # thunk f_700007e044 (same ldr x0, [x0, #8], tail b f_700007f6b0; callers f_7000080440 from the
    # step's bl f_7000f0817c f_700008042c and f_70000807f0), and the two entry queries f_700007e36c
    # and f_700007e3e0 (both ldr x0, [x0, #8] at +4, the same state; reached from the step's
    # f_700008042c and from the tail accessors f_70000805b4/f_70000805bc -> f_7000093644/f_7000093934)
    # -- all four answer 0 at the entry, the established neutral: tag-4 handle index 0, query flag
    # 0 ("miss") the callers already carry on a failed bl f_700007f7ec/f_700007f9dc.
    Site('fs_state_accessor_guard', 'code', 'f9400400 140005a9', 0),
    Site('fs_state_accessor_guard_2', 'code', 'f9400400 1400059a', 0),
    Site('fs_state_query_guard', 'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd aa0003f6 f9400400 '
         'aa0103f4 2a0203f5 2a0203e1 aa1403e2 94000516', 0),
    Site('fs_state_query_guard_2', 'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd aa0003f5 f9400400 '
         'aa0103f4 94000578', 0),
    # run64's never-built sead framework family (tools/patches.py framework_swap_guard and
    # physics_cfg_entry_guard): the deepest boot yet -- past the fs families, into physics/system init
    # (the dump's x6/x7 spell "Physics/System/S", the frames 7001572xxx are the config step) -- and
    # signal 11 accessing 0x7af992ff12 at the dump's host pc f_7000ec9990+b0: that helper converts a
    # word array through the framework's slot table -- x9 = [0x7001d6e960] (the sead framework's
    # global, never constructed on our machine: run64's dump x9 = 0x6e0bebe98, a stale host pointer,
    # dirty memory), x21 = [[x9 + 8·bit] + 0x20], then for every word: ldr w0, [x19] + blr x21 +
    # str w0, [x19], #4 -- the dump's x21 = 0x7af992ff12 (the same dirty value, > GUEST_HI,
    # unmapped): the loop's first ldr w0, [x19] faults at exactly the dump address, x19 = the array
    # x1 = 0x7af992ff12. The sweep: the helper has 21 bl callers (11 in the physics-config region
    # 0x7000ec93xx-0x7000ec98xx, 3 in the step f_7000eeaff8, 7 elsewhere) and no tail branches --
    # one entry guard covers them all: the framework global or the array pointer off the guest map
    # (the stale_actor guards' range idiom) means the table was never built, so there is nothing to
    # convert and the helper answers by its own early return (its b.lt ret answers without touching
    # the array for a zero word count -- the same "nothing converted" shape its callers tolerate).
    # The guard alone is not enough for the step: its three bls pass x1 = x1 + dirty field-sums --
    # x27 = x20 + x23 lands on the dirty 0x7af992ff12 too -- and its own loop re-reads the array
    # after the helper returns (bl 0x7000eeb0c0 then ldr w8, [x21], cmp w25, w24, b.lo -- a dirty
    # w24 = [x1+0x2c] count re-reads the junk base forever, and the first re-read faults again at
    # 0x7af992ff12). Guard the step's loop at its count load: a base off the guest map answers the
    # count 0 its own cbz path already takes (goto L_7000eeb0d8, the existing label -- the step's
    # "no words to convert" tail: set the parsed flag at [x1+8] and carry on to its entry list).
    Site('framework_swap_guard', 'code', 'd342fc48 7100051f 540002ab/ff00001f a9bd7bfd f9000bf5 '
         'a9024ff4 910003fd b0007529 2a2003e8 f944b129', 0),
    Site('physics_cfg_entry_guard', 'code', 'f9400261 b9402c38 34000018/ff00001f', 1),
    # run65's never-loaded sub-object family (tools/patches.py load_balancer_entry_guard and
    # load_balancer_handle_guard): boot passed the physics-config guards (family #28 closed -- the
    # dump's last RomFS read is now Actor/ActorInfo.product.sbyml) and died on signal 11 accessing 0
    # at the dump's host pc f_70011855b0+42e: the Ecosystem/LoadBalancer init step (its registers
    # carry the path string "Ecosystem/LoadBalancer.beco"), called from the framework step
    # f_700127d4d0 (the dump's lr 7001185724 pins the exact instruction: ldr x8, [x23] -- the vtable
    # load of a looked-up sub-object, dump x23 = 0). The step asks the thunk f_700155dd2c five times
    # through its life for five sub-objects -- the ready probe f_700155dd60 checks the path's flag
    # byte [x0+8] bit 1 and its subsystem pointer [x0+0x10], answers [[x0+0x10]+0x38] or 0 when the
    # path was never loaded -- and on our machine the second path answers 0 (its package was never
    # read). The sweep enumerated every dereference of those answers in the step: sites 1-3 (loads
    # at 0x70011856e0, 0x7001185724 -- the fault -- 0x7001185768) deref the entry unconditionally
    # (vtable + slot-0 blr + [csel+8] handle read + three field stores); sites 4 and 5 carry the
    # game's own null guards (cbz x22 -> L_70011857d4 and cbz x21 -> L_700118589c -> x22 = 0) but
    # still read [x23+8] / [x22+8] before the handle setter f_7000e8aefc, which is null-tolerant
    # itself (cbz x1 -> store {0,0}) -- those two loads fault next at 0x8 and 0x8 if left alone.
    # The game's own null paths prove the right neutral answers: an absent entry SKIPS the handoff
    # block (goto L_70011857d4, the existing "no entry" tail: alloc the handle cell, store {0,0},
    # run the later init) -- the same shape a real hardware "not found" would take -- and an absent
    # handle answers 0 into the setter (a null entry has no handle at +8). Site 3's pattern needs
    # the stp [x20,#0x208] tail (the bare 8-word shape also matches f_70012cf130).
    Site('load_balancer_entry_guard', 'code', 'f94002e8 aa0003e1 aa1703e0 f9400108 d63f0100 7200001f '
         'aa1903e0 9a9f12e8', 0),
    Site('load_balancer_entry_guard_2', 'code', 'f94002e8 aa0003e1 aa1703e0 f9400108 d63f0100 '
         '7200001f aa1603e0 9a9f12e8 f9400508 91004109 f9010688', 0),
    Site('load_balancer_handle_guard', 'code', '97f41a9c f94006e1', 1),
    Site('load_balancer_handle_guard_2', 'code', '97f41a85 f94006c1', 1),
    # run66's never-built config path entries (tools/patches.py physics_path_scan_guard and
    # sead_heap_alloc_guard): boot passed the LoadBalancer guards (family #29 closed -- run66's
    # x6/x7 carry "Ecosyste" + "m/LoadBa" again, the deepest route yet: the registrar
    # f_70014d97f0's ~80 param registrations ran and reached the physics step's tail) -- and died
    # on signal 11 accessing 0x823a89c29e at the dump's host pc f_7000eeaff8+3a7, which objdump
    # pins to the step's string scan cmpb $0x0,(%rdx) with %rdx = 0xa0(%rbx): the guest
    # ldrb w8, [x20, x21] at 0x7000eeb10c (the dump's x19 = 0xffffffff is the mov w19, #-1 right
    # before it at 0x7000eeb104, x20 = the dump's 0x823a89c29e exactly). The family #28 count-0
    # guard held -- the step set its parsed flag and moved on -- but the step then walks the same
    # never-built config struct's path-entry array [x20, x27) converting every entry through the
    # sead heap: x20 = the dirty field-sum base and x27 = its end are both off the guest map (the
    # dump's 0x823a89c29e and 0x82f68b1c1f), so the scan's first byte read faults. The sweep's
    # neutrals are the step's own exits: a base off the guest map means there are no entries at
    # all -- exactly the shape the entry-count cbz (cbz w9, #0x7000eeb228) takes and the loop's
    # own "array exhausted" done tail (goto L_7000eeb214: reload the config from [sp, #8], set the
    # string-parsed flag bit 2, restore the spills and return, the caller's post-step virtual call
    # carrying on); and inside the loop the heap manager -- [0x7001d6eab8] of the framework's
    # never-constructed page (the dump's x13/x12/x10/x11 are its crc32 tables, dirty) -- feeds the
    # alloc bl and the two registration blrs through a bare ldr x8, [x8]: a global off the guest
    # map means there is no heap to allocate from, so the step answers the same done tail (the
    # entries converted up to there are still marked parsed).
    Site('physics_path_scan_guard', 'code', 'aa1f03f5 38756a88', 1),
    Site('sead_heap_alloc_guard', 'code', 'f9455d08 531f7afa 52800102 f9400108', 3),
    # run67's never-built resource manager (tools/patches.py resource_manager_*): boot passed the
    # path-entry guards (family #30 closed -- run67's x28 carries "fs::ResultPathNotFound", the
    # deepest route yet: the Physics/System param step and the LoadBalancer step tails ran) and
    # died on signal 11 accessing 0x318. The dump's host pc f_70012647e8+8f with guest lr
    # 7001420c7c pins the resource path lookup: the leaf walks [[x0, #0x158] then [+0x3638] to
    # the entry table and reads its count with ldr w9, [x8, #0x318] -- on our machine the
    # manager was never built, the +0x3638 field reads 0 from readable data, so the count read
    # faults at exactly 0x318. The leaf's own "path not found" exit is a bare epilogue ret
    # carrying x0 = 0 (the shape its cbz x0 takes when the string search fails, which the
    # caller1 float block right after the bl already tolerates) -- both chain derefs guard to it
    # for a base off the guest map: the table field (this run's fault) and x0 itself (the second
    # caller loads it from the never-built .bss singleton [0x7001e43df0]). The same count field
    # on the sibling manager pointer [x0, #0xcc0]: the registration leaf f_7000fcded4 (which the
    # lookup tail-calls with x0 = the same object on the found path) reads ldr w8, [x21, #0x318]
    # after its virtual probe and hands the table to f_7000fd5f94, and the removal sibling
    # f_7000fcdd10 (the other callers' other half) reads it twice; all three guard to their own
    # "nothing registered/removed" exits (cmp x20, #0; cset w0, ne -- the null search result's
    # 0 answer, the removal sites' shape also carrying the [x19, #0x168] = -1 index reset).
    # Last the never-built rng: caller1's post-lookup float block reads [0x7001e34818] (a zeroed
    # .bss singleton) three times into the xorshift step f_7000eb6e7c, whose first ldp w8, w9,
    # [x0] faults on address 0 -- the entry answers the step's own returned new state w0 = 0
    # (the deterministic stream caller1 bfxils into its actor floats), state stores skipped.
    Site('resource_manager_chain_guard', 'code', 'a9014ff4 910003fd f940ac08', 2),
    Site('resource_manager_count_guard', 'code', 'f95b1d08 b9431909', 1),
    Site('resource_manager_reg_count_guard', 'code', 'f9405908 d63f0100 b9431aa8 7100051f', 2),
    Site('resource_manager_removal_guard', 'code', 'b9431aa8 12800016', 0),
    Site('resource_manager_removal_guard_2', 'code', 'd63f0100 b9431aa8 7100051f 5400000b/ff00001f', 1),
    Site('resource_manager_rand_guard', 'code', '29402408 4a082d08 29412c0a 29002809 53087d09', 0),
    # run68's never-built param subsystem (tools/patches.py param_array_*): boot passed the
    # resource-manager family (run68 died deeper, deepest route yet: the registrar's whole
    # param-table chain ran through the framework step f_700127d4d0's thunk) and died on signal
    # 11 accessing 0x40: the dump's host pc f_7000f4b830+de pins the param array constructor's
    # str x0, [x20, #0x40] at 0x7000f4b860 (the dump's lr exactly) -- the alloc thunk
    # f_7000007c20 worked (the dump's x0 = a live block) but the object it stores into is 0
    # (the dump's x20/x0 story): the giant builder thunk f_70015959c4 calls the array wrapper
    # f_7000f4b8ac twice (0x7001595cb8/0x7001595cd4, its x0 = [[0x7001d6c5e8]]/[[0x7001d6f250]]
    # -- the never-built subsystems' singleton pointers) with x19 = 0, and the ctor's first
    # store faults. Both functions are void setup steps whose callers ignore the answer (the
    # wrapper's bl return feeds only cbz w22, the thunk's returns are immediately clobbered),
    # and the wrapper's own [x19, #8]/[x19, #0xc0]/[x19, #0x58] reads on the same null object
    # would fault right after -- so both guard return at entry with x0 = 0 for an object off
    # the guest map: with no subsystem object there is nothing to allocate into, the thunk
    # carries on with its live heap and data cells, and with a real built subsystem both
    # re-execute their spills untouched.
    Site('param_array_ctor_guard', 'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd 2a0103f3 aa0203f5 aa0003f4 2a0103f6', 0),
    Site('param_array_step_guard', 'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd aa0203f4 aa0303e2 2a0103f6 aa0003f3', 0),
    # The framework step's dirty x19 (tools/patches.py framework_x19_load_guard_1..17): run69
    # cleared the param-array family and went deepest yet -- the whole param-table section ran
    # to completion -- and died with signal 11 accessing 0 at host pc f_700127d4d0+4484, which
    # objdump pins to the lifted LD64(c->x[19] + 8) of ldr x2, [x19, #8] at 0x700127ec90, the
    # dump's guest window exactly. The dump's x19 = 0x646f727000000001 -- the sead ParamHolder
    # union {int i; char c[4]} cell {1, "prod"} of ActorInfo.product.sbyml (the last RomFS
    # file) read as an object pointer: the step's x19 is its incoming stack-buffer argument,
    # and the hash-lookup helper behind the thunk f_7000ea1e14 (real body f_7000ea1e18, mov
    # x19, x2 at 0x7000ea1e38) reuses the callee-saved x19 as scratch without restoring it --
    # on a real Switch the callee leaves a valid entry pointer there, here the never-built
    # subsystem left the param cell. The step restores x19 only in its epilogue (ldp x20, x19,
    # [sp, #0x50] at 0x700127ef48), so every [x19] read from 0x700127ec90 to the epilogue is
    # the dirty cell: all seventeen loads guard as conditional load-skips answering null, the
    # consumers all cbz/cbnz the load or pass it as a possibly-null name/value to callees the
    # resource-manager family already taught to take null.
    Site('framework_x19_load_guard',    'code', 'f9400662 94000000/fc000000 f94002c8 aa1603e0 f9401508 d63f0100 f10006bf 54000000/ff00001f', 0),
    Site('framework_x19_load_guard_2',  'code', 'f9400668 b4000008/ff00001f 90000015/9f00001f 910002b5/ffc003ff aa1503e0 94000000/fc000000 f9400660 94000000/fc000000 aa1503e0 94000000/fc000000 b4000014/ff00001f 90000015/9f00001f 910002b5/ffc003ff aa1503e0 94000000/fc000000 aa1403e0', 0),
    Site('framework_x19_load_guard_3',  'code', 'f9400660 940016f9', 0),
    Site('framework_x19_load_guard_4',  'code', 'f9400260 97fe25bb', 0),
    Site('framework_x19_load_guard_5',  'code', 'a9400a61 97fe25eb', 0),
    Site('framework_x19_load_guard_6',  'code', 'f9400668 b4000008/ff00001f 90000014/9f00001f 91000294/ffc003ff aa1403e0 94000000/fc000000 f9400660 94000000/fc000000 f9400660', 0),
    Site('framework_x19_load_guard_7',  'code', 'f9400660 94001739', 0),
    Site('framework_x19_load_guard_8',  'code', 'f9400660 94001776', 0),
    Site('framework_x19_load_guard_9',  'code', 'f9400260 97fbe789', 0),
    Site('framework_x19_load_guard_10', 'code', 'f9400268 f90007e8 97fbe88c', 0),
    Site('framework_x19_load_guard_11', 'code', 'f9400260 97faad3e', 0),
    Site('framework_x19_load_guard_12', 'code', 'f9400261 f9400100 97faad7f', 0),
    Site('framework_x19_load_guard_13', 'code', 'f9400262 91004308 910023e1 aa1f03e0 52800103 52800024 2a1f03e5 a900d3e8', 0),
    Site('framework_x19_load_guard_14', 'code', 'f9400260 97f9567a', 0),
    Site('framework_x19_load_guard_15', 'code', 'f9400260 9406030d', 0),
    Site('framework_x19_load_guard_16', 'code', 'f9400260 9405dfd0', 0),
    Site('framework_x19_load_guard_17', 'code', 'f9400661 b5000241', 0),
    # The holder's dirty sub-array (tools/patches.py holder_array_init_guard): run70 cleared the
    # dirty-x19 family and the param-table chain walked one level deeper -- the step's callee
    # f_7001550dec read the stack buffer's [x0, #0x70] object (valid), whose ctor sibling
    # f_7001551ee4 alloc'd its 0x10 entry, stored it at [x19, #0x18], init'd it and then read the
    # holder's old sub-array pointer [x19, #0x10], cbz-branched on it (non-zero here) and called
    # the node init f_700155210c on it -- and died with signal 11 accessing 0x6800000014: the
    # dump's host pc f_700155210c+fa objdump-pins the pre-index str wzr, [x21, #0x10]! at
    # 0x700155214c (the dump's x19 = x21 exactly). The dump's x0 = 0x6800000004 -- the ParamHolder
    # union {int i; char c[4]} cell {4, "h"} read as the sub-array pointer (the next raw param
    # cell of the never-built subsystem). Every read in the init runs on that cell (its node walk
    # spans [x19, #0x10] through [x19, #0x2c8]), so the guard returns at entry with the answer 0
    # of its own failed singleton alloc (its cbz x0 tail): the caller ignores x0 after the bl, and
    # with a real built subsystem the on-map pointer re-executes the frame untouched.
    Site('holder_array_init_guard', 'code', 'd10183ff a9017bfd a90267fa a9035ff8 a90457f6 a9054ff4 910043fd aa0003f3 94000000/fc000000 b4000000/ff00001f aa1303f5', 0),
    # The param-table step's dirty virtual call (tools/patches.py param_holder_vcall_guard):
    # run71 cleared the holder-init family and died at lr 0x7001550e24 on the step f_7001550dec's
    # blr x8 at 0x7001550e20 -- FATAL: no function at a90657f6f9002bf7, the dump's x8 exactly:
    # the object field [x19, #0x30] answered 0x7001d04098, a raw .rodata cell, not a built
    # object -- its vptr [x0] is a code address and the slot [x8, #0x10] is two raw instruction
    # words, so the lifted c->pc = x8; rt_dispatch(c) dispatch found no function there (the
    # loads themselves never fault). The guard skips the dispatch when the target is off the
    # guest map and answers 0 -- the caller's next line reloads x0 from [x19, #0x40], so the
    # answer is ignored -- and dispatches untouched on a real built object's on-map slot.
    Site('param_holder_vcall_guard', 'code', 'd63f0100 f9402260 aa1503e1 94000000/fc000000 f9401e60 aa1503e1 94000000/fc000000 f9404a60', 0),
    # The param step's dirty-field callees (tools/patches.py entry_field_lookup_guard/_2,
    # entry_config_fill_guard): run72 cleared the dirty-"vtable" family -- the virtual step
    # skipped to its ignored 0 and the step f_7001550dec ran past it -- and died with signal 11
    # accessing 0xbe912318: the dump's host pc f_7001394864+119 objdump-pins the result store
    # str x0, [x20, #0x20] at 0x70013948c0 (the dump's lr exactly) into the param table's entry
    # field -- the dump's x20 = 0xbe9122f8, the step's dirty [x19, #0x40] object field (another
    # raw cell, this one holding utf8 bytes) read as the entry. The string lookup answered the
    # dump's x0 = 0 (fine), only the store into the raw cell faulted. The sweep of the step's
    # tail shows the same story at its two remaining dirty-field callees: f_7001382998 (called
    # at 0x7001550e44 with x0 = the [x19, #0x90] field, its only store str x0, [x19, #0x28]
    # faults on a raw cell) and f_700138e5b8 (called at 0x7001550e54 with x0 = the
    # [x19, #0x60] base + 0x48, a huge config fill whose first str w0, [x19, #0x68] faults);
    # f_700135e048 (0x7001550e38) is a bare ret. All three guard at entry with the answer 0
    # for an object off the guest map -- every caller reloads x0 or x8 right after the bl and
    # the cbz x20 branch the never-built step's null x2 already takes skips the rest -- and
    # with a real built subsystem the on-map objects re-execute the spill frame untouched.
    Site('entry_field_lookup_guard',    'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd 90000008/9f00001f 90000015/9f00001f 910002b5/ffc003ff f9400108/ffc003ff', 0),
    Site('entry_field_lookup_guard_2',  'code', 'a9be7bfd f9000bf3 910003fd aa0003f3 90000000/9f00001f 91000000/ffc003ff aa1f03e2 aa1f03e3', 0),
    Site('entry_config_fill_guard',     'code', 'a9ba7bfd a9016ffc 910003fd a90267fa a9035ff8 a90457f6 a9054ff4 d11903ff', 0),
    # The step tail's unbound sead delegate (tools/patches.py param_delegate_invoke_guard):
    # run73 cleared the dirty-field callee family -- the step ran its whole tail into its
    # sub-step f_7001550ed0 -- and died on an SDK assertion instead of a fault: the guest
    # frames 7001550ee8 7001550e90 700127ec98 pin the param chain (framework step, guarded
    # tail, sub-step), and the sub-step's bl #0x70015a19e0 at 0x7001550ee4 -- a module import
    # thunk (adrp/ldr/br on GOT slot 0x7001d78db8) the resolver wired to the sdk's delegate
    # invoke f_7002640e30, which ldrb's the delegate's state byte at [x0, #0x28] and dispatches
    # state 1 or 2 -- fell through to its assert tail (the sead report f_700259fee0 printing
    # "SDK has been aborted or failed assertion with no message." into the log, then
    # svcBreak(reason=0) at 0x700267974c, the run's FATAL). The delegate at object + 0x240 was
    # never bound (the registrar that binds it never ran -- the same story as the raw cells) so
    # the state byte is neither 1 nor 2. The guard answers the invoke's own "nothing changed"
    # 0 and skips the call: the next line's tbz w0, #0 takes the sub-step's own return, and its
    # caller's tail runs cbz-guarded (f_7000f093f0's null answer, the [x19, #0x2a0] null check).
    # With a real Switch's built delegate (state byte 1 or 2) the guarded call dispatches
    # untouched; the byte itself is inside the step's valid object, so the guard's load is safe.
    Site('param_delegate_invoke_guard', 'code', '94000000/fc000000 36000000/fff8001f 94000000/fc000000 b9427268 6b08001f 54000001/ff00001f f9400bf3 a8c27bfd', 0),
    # The step tail's ready-flag helper on the raw field (tools/patches.py
    # entry_ready_flag_guard): run74 cleared the unbound-delegate family -- the sub-step's
    # invoke skipped to its nothing-changed 0, the sub-step returned, and the step f_7001550dec
    # reached its LAST tail for the first time: after its epilogue restored the framework
    # step's dirty x19 (the {1,"prod"} ParamHolder cell -- the #33 guards load-skip reads but
    # never scrub x19 itself) it tail-branches b #0x7001557a08 at 0x7001550ebc carrying
    # x0 = the never-written [object, #0x2a0] field, the raw word 1 -- and died with signal 11
    # accessing 0x9 at the helper's entry ldrb w8, [x0, #8] (the dump: x0 = 1, x19 =
    # 0x646f727000000001, lr = the framework step's 0x700127ec98, the thunk's return exactly).
    # On a real Switch that field is the built ready object (or null, whose cbz branch the
    # never-built world already took its way through) and the helper returns through its
    # flag-set early ret when already ready -- the guard returns that same ret with the
    # neutral 0 the framework step overwrites with its next load (the #33 audit: site 1's
    # consumer reassigns x0 before use), and dispatches the flag probe untouched when x0 is
    # on the guest map.
    Site('entry_ready_flag_guard',      'code', '39402008 34000008/ff00001f d65f03c0 a9be7bfd f9000bf3 910003fd aa0003f3 94000000/fc000000', 0),
    # The step query object's dirty "vtable" pair (tools/patches.py query_object_vtable_guard,
    # query_object_vcall_guard): run75 cleared the ready-flag family -- the whole param chain
    # answered and the framework step ran past bl #0x7001550dec -- and died with signal 11
    # accessing 0: the dump's host pc f_700127d4d0+4558 objdump-pins mov 0x28(%rax),%rax, the
    # lifted LD64(x8 + 0x28) of ldr x8, [x8, #0x28] at 0x700127eca0 (lr 0x700127ec98 exactly,
    # the param step's return), the step's virtual probe of the query object: the ldr x8,
    # [x22] at 0x700127ec98 read the never-built registration slot as the object -- a raw
    # word -- and the "vtable" slot load faults on it. The ecb0 tail reloads x0 from [x23]
    # and only branches on x21, so the blr x8's answer at 0x700127eca4 is ignored: the pair
    # guards as a load-skip answering null plus the #35 dispatch-skip answering 0, and with a
    # real Switch's registered object both re-execute untouched (on-map "vptr", on-map slot).
    Site('query_object_vtable_guard',   'code', 'f9401508 d63f0100 f10006bf 54000000/ff00001f f94002e0 aa1503e1 94000000/fc000000 90000000/9f00001f', 0),
    Site('query_object_vcall_guard',    'code', 'd63f0100 f10006bf 54000000/ff00001f f94002e0 aa1503e1 94000000/fc000000 90000000/9f00001f 91000000/ffc003ff', 0),
    # The step tail's never-built logging subsystem (tools/patches.py log_tail_* guards):
    # run76 cleared the query-virtual family -- the step ran past its virtual probe into the
    # debug-logging tail of its post-chain block (0x700127ece4..0x700127efd4) -- and died with
    # signal 11 accessing 0x1: the dump's host pc f_7000007c20+130 pins the alloc thunk reading
    # its NAME argument inside the resource-node getter f_70010860b4 -- the step's bl at
    # 0x700127ece0 passes x0 = x20, the never-built param value's raw word 1, and the getter's
    # cache-miss path allocs a 0x430 node keyed on that name (the dump: x0 = 0x430, x1 = 1,
    # guest frames 70010860f8 700127ece4). The static sweep of the whole tail shows the same
    # root cause everywhere it goes: the never-built registrar left every param/resource
    # singleton slot null in .bss and every key a raw cell, so its ~20 singleton getters alloc
    # with a dirty name (thunk fault) and its publishers store through the null singleton
    # (store fault), plus three double-deref loads INSIDE the step itself -- 0x700127ecf0,
    # 0x700127ed50, 0x700127ee08 read [slot] (null) then ldr x0, [x8] straight off it (those
    # answer the null singleton as x0 = 0 to the guarded callees right after). Every answer is
    # ignored: all 20 call sites reload x0 from [x21]/their own table right after the bl
    # (0x700127ece8 mov x1, x20 overwrites... and the ecf8/ed58/ee18-style reloads; audited
    # one by one), and with a real Switch's built subsystem the keys and singletons are on-map
    # so every guarded line re-executes its spill/store byte-identical. The entry guards answer
    # the resource family's neutral 0 (tools/patches.py _tail_guard_entry), the three loads
    # answer 0 with the off-map x8 idiom of the #39 pair.
    Site('log_tail_resource_getter_guard',  'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd 90000016/9f00001f f941a6d3', 0),
    Site('log_tail_node_publish_guard',     'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd aa0003f4 52800a00 52800102 aa0103f3', 0),
    Site('log_tail_flag_accessor_guard',    'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd 90000016/9f00001f f947fed3', 0),
    Site('log_tail_flag_accessor_guard_2',  'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd b0005e16 f94006d3 b5000293 aa0003f4 52800500', 0),
    Site('log_tail_flag_accessor_guard_3',  'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd b0005e16 f9400ed3 b5000293 aa0003f4 52800500', 0),
    Site('log_tail_value_getter_guard',     'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd 90000015/9f00001f f94002b3/ffc003ff b5000013/ff00001f aa0003f4 52801800 52800102 aa1403e1 94000000/fc000000 aa1403e1 52800062 aa0003f3 94000000/fc000000 92b01008', 0),
    Site('log_tail_value_publish_guard',    'code', 'f9001001 d65f03c0 fc170fec 6d012beb', 0),
    Site('log_tail_tag_getter_guard',       'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd 90000016/9f00001f f94002d3/ffc003ff b4000013/ff00001f aa1303e0 a9424ff4 a94157f6 a8c37bfd d65f03c0 aa0003f4 52804c00', 0),
    Site('log_tail_name_getter_guard',      'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd 90000016/9f00001f f94002d3/ffc003ff b5000013/ff00001f aa0003f4 52801900', 0),
    Site('log_tail_name_format_guard',      'code', 'd10103ff a9017bfd a90257f6 a9034ff4 910043fd 90000008/9f00001f aa0203f3 f9400108/ffc003ff aa0103f4 aa0003f5', 0),
    Site('log_tail_flag_node_getter_guard', 'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd 90000015/9f00001f f94002b3/ffc003ff b4000013/ff00001f aa1303e0 a9424ff4 f9400bf5 a8c37bfd d65f03c0 aa0003f4 52803000', 0),
    Site('log_tail_flag_format_guard',      'code', 'd10143ff a9017bfd a9025ff8 a90357f6 a9044ff4 910043fd 90000008/9f00001f aa0103f5 f9400108/ffc003ff aa0003f3 aa1f03f6', 0),
    Site('log_tail_state_getter_guard',     'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd 90000015/9f00001f f94002b3/ffc003ff b4000013/ff00001f aa1303e0 a9424ff4 f9400bf5 a8c37bfd d65f03c0 aa0003f4 52802300', 0),
    Site('log_tail_state_format_guard',     'code', 'd10243ff a9037bfd a9046ffc a90567fa a9065ff8 a90757f6 a9084ff4 9100c3fd 52802b15', 0),
    Site('log_tail_pool_getter_guard',      'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd 90000016/9f00001f f94002d3/ffc003ff b4000013/ff00001f aa1303e0 a9424ff4 a94157f6 a8c37bfd d65f03c0 aa0003f4 5281c500', 0),
    Site('log_tail_pool_clear_guard',       'code', 'b900281f b900781f b900c81f b901181f b901681f b901b81f b902081f b902581f', 0),
    Site('log_tail_debug_getter_guard',     'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd 90000016/9f00001f f94002d3/ffc003ff b4000013/ff00001f aa1303e0 a9424ff4 a94157f6 a8c37bfd d65f03c0 aa0003f4 52811800', 0),
    Site('log_tail_time_getter_guard',      'code', 'a9bd7bfd f9000bf5 a9024ff4 910003fd 90000015/9f00001f f94002b3/ffc003ff b5000013/ff00001f aa0003f4 52800d00 52800102 aa1403e1 94000000/fc000000 aa1403e1 52800062 aa0003f3 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff f9000268 90000008/9f00001f 9100a260 f9000113/ffc003ff 52800028', 0),
    Site('log_tail_ready_setter_guard',     'code', 'd10083ff a9017bfd 910043fd 52800028 d10013a1 3900c008 f9401400 381fc3a8', 0),
    Site('log_tail_manager_getter_guard',   'code', 'a9bd7bfd a90157f6 a9024ff4 910003fd b00052f6 f942bed3 b5000293 aa0003f4 52800500', 0),
    Site('log_tail_slot_load_guard',        'code', 'f9400100 94000000/fc000000 aa1503e0 94000000/fc000000 f9400668 b4000128 b0001df5', 0),
    Site('log_tail_slot_load_guard_2',      'code', 'f9400100 94000000/fc000000 aa1503e0 94000000/fc000000 d0001cd5 912106b5 aa1503e0', 0),
    Site('log_tail_slot_load_guard_3',      'code', 'f9400100 f9400268 f90007e8 94000000/fc000000 aa1403e0 94000000/fc000000 90001e54', 0),
    # The framework step's node-builder chain (tools/patches.py node_build_*/lockmgr_*/
    # pushmgr_*/step_node_*/node_init_*/list_clear_* guards): run77 cleared the whole
    # log_tail family -- the step ran from its post-chain block to its bl #0x7000003f10
    # node-builder -- and died with signal 11 accessing 0: the dump's host pc
    # f_7000003f10+184 objdump-pins the second LD64 of the 4354 block (ldr x8, [x19] then
    # ldr x8, [x8, #0x80] at 0x7000004354/0x7000004360): the never-built registry hands the
    # step's node-builder call its object as a raw rodata string (the dump: x19 =
    # 0x70015e615b), so its first word is an ASCII cell and the "vtable" slot load faults.
    # The static sweep of the chain shows the same never-built-registry root cause
    # everywhere: the builder's factory/lock/push paths double-deref static-link addend
    # words ([0x7001d69430], [0x7001d6af80]: .data slots holding file-relative pointers,
    # off-map to the recompiler) and its answered 0-node flows into the step's own
    # ldr x8, [x21] / ldr x8, [x8, #0x28] / blr x8 probe pair at 0x700127ee90-0x700127ee9c,
    # into the node registrar f_700127efe0's slot double-derefs and its null-slot flag
    # stores, and into the 256-entry list-clear f_700127f150's null-singleton loop (its
    # manager-buffer slot [0x7001e44f00] still null before the step's own alloc). The 42
    # guards answer 0/skip-store exactly when the base pointer is off the guest map, so a
    # real Switch's built chain (on-map object, relocated slot, built loop singleton)
    # re-executes every guarded line byte-identical, and the answers are all consumed by
    # guarded-off-map code or ignored (the builder returns x21 = 0, the step pair's
    # virtual answer is dead, the clear loop's virtual/strbuf answers feed only its own
    # guarded loads).
    Site('node_build_obj_load_guard',       'code', 'f9400268 1b157ca2 d503201f 10000009/9f00001f f9401908 eb09011f 54000001/ff00001f 90000008/9f00001f', 0),
    Site('node_build_vtable_load_guard',    'code', 'f9401908 eb09011f 54000001/ff00001f 90000008/9f00001f 7100005f f9400108/ffc003ff f940010d 5a825448', 0),
    Site('node_build_factory_load_guard',   'code', 'f940010d 5a825448 51000509 6a09011f 54000001/ff00001f 7941b268 37000008/fff8001f aa1f03e9', 0),
    Site('node_build_obj_load_guard_2',     'code', 'f9400268 90000009/9f00001f 91000129/ffc003ff f9404108 eb09011f 54000001/ff00001f 710002bf 5a9556b6', 0),
    Site('node_build_vtable_load_guard_2',  'code', 'f9404108 eb09011f 54000001/ff00001f 710002bf 5a9556b6 510006c9 6a0902df 54000001/ff00001f', 0),
    Site('node_build_factory_load_guard_2', 'code', 'f9400100 94000000/fc000000 f9400fa1 2a1303e5 aa0003f3 b5000000/ff00001f 14000000/fc000000 aa1303e0', 0),
    Site('node_build_vtable_blr_guard',     'code', 'd63f0100 f9400fa1 aa1503e4 2a1603e5 aa0003f5 14000000/fc000000 b400000d/ff00001f f94009a0', 0),
    Site('node_build_vtable_blr_guard_2',   'code', 'd63f0100 f9400fa1 2a1603e5 aa0003f6 14000000/fc000000 9102e260 91026277 f9000fa1', 0),
    Site('lockmgr_head_load_guard',         'code', 'f9400108 b9408900 94000000/fc000000 9102c008 91002269 f9400bf3 f100001f 9a880128', 0),
    Site('lockmgr_key_load_guard',          'code', 'b9408900 94000000/fc000000 9102c008 91002269 f9400bf3 f100001f 9a880128 f9400100', 0),
    Site('lockmgr_pop_load_guard',          'code', '9a880128 f9400100 a8c27bfd d65f03c0', 1),
    Site('pushmgr_head_load_guard',         'code', 'f9400108 b9408900 94000000/fc000000 f9405808 f9005813 aa0803e0 f9400bf3 a8c27bfd', 0),
    Site('pushmgr_key_load_guard',          'code', 'b9408900 94000000/fc000000 f9405808 f9005813 aa0803e0 f9400bf3 a8c27bfd d65f03c0', 0),
    Site('pushmgr_slot_load_guard',         'code', 'f9405808 f9005813 aa0803e0 f9400bf3 a8c27bfd d65f03c0', 0),
    Site('pushmgr_slot_store_guard',        'code', 'f9005813 aa0803e0 f9400bf3 a8c27bfd d65f03c0', 0),
    Site('step_node_load_guard',            'code', 'f94002a8 aa1503e0 f9401508 d63f0100 aa1403e0 94000000/fc000000 90000014/9f00001f 91000294/ffc003ff', 0),
    Site('step_node_vtable_guard',          'code', 'f9401508 d63f0100 aa1403e0 94000000/fc000000 90000014/9f00001f 91000294/ffc003ff aa1403e0 94000000/fc000000', 0),
    Site('step_node_vcall_guard',           'code', 'd63f0100 aa1403e0 94000000/fc000000 90000014/9f00001f 91000294/ffc003ff aa1403e0 94000000/fc000000 f9400260', 0),
    Site('node_init_slot_load_guard',       'code', 'f94002c0 aa1403e1 94000000/fc000000 aa0003f3 aa1403e0 94000000/fc000000 aa1403e0 94000000/fc000000', 0),
    Site('node_init_log_load_guard',        'code', 'f9400115 910043e8 91004129 91002100 f9000fe9 a9002be9 94000000/fc000000 90000008/9f00001f', 0),
    Site('node_init_gadget_load_guard',     'code', 'f9400108 91008108 f90017e8 90000008/9f00001f f9400108/ffc003ff f9400108 f9404108 b940d108', 0),
    Site('node_init_alloc_load_guard',      'code', 'f9400108 f9404108 b940d108 b90003e8 94000000/fc000000 b90007e0 aa1503e0 52800041', 0),
    Site('node_init_alloc_load_guard_2',    'code', 'f9404108 b940d108 b90003e8 94000000/fc000000 b90007e0 aa1503e0 52800041 52800058', 0),
    Site('node_init_alloc_load_guard_3',    'code', 'b940d108 b90003e8 94000000/fc000000 b90007e0 aa1503e0 52800041 52800058 94000000/fc000000', 0),
    Site('node_init_registry_load_guard',   'code', 'f9400100 94000000/fc000000 90000008/9f00001f 90000009/9f00001f f9400108/ffc003ff f9400129/ffc003ff 9000000a/9f00001f f100067f', 0),
    Site('node_init_flag_store_guard',      'code', 'b900011f b9000137 90000008/9f00001f 52800089 f9400108/ffc003ff b9000158 b9000109 54000000/ff00001f', 0),
    Site('node_init_flag_store_guard_2',    'code', 'b9000137 90000008/9f00001f 52800089 f9400108/ffc003ff b9000158 b9000109 54000000/ff00001f f94002c0', 0),
    Site('node_init_flag_store_guard_3',    'code', 'b9000158 b9000109 54000000/ff00001f f94002c0 aa1303e1 94000000/fc000000 a9464ff4 a94557f6', 0),
    Site('node_init_flag_store_guard_4',    'code', 'b9000109 54000000/ff00001f f94002c0 aa1303e1 94000000/fc000000 a9464ff4 a94557f6 a9445ff8', 0),
    Site('node_init_slot_load_guard_2',     'code', 'f94002c0 aa1303e1 94000000/fc000000 a9464ff4 a94557f6 a9445ff8 a9437bfd 9101c3ff', 0),
    Site('list_clear_buf_load_guard',       'code', 'f9427754 d63f0100 f9400675 eb15029f 54000000/ff00001f f9400268 aa1303e0 9113835a', 0),
    Site('list_clear_vtable_load_guard',    'code', 'f9400268 f9400d08 f9427754 d63f0100 f9400675 eb15029f 54000000/ff00001f f9400268', 0),
    Site('list_clear_vtable_load_guard_2',  'code', 'f9400d08 f9427754 d63f0100 f9400675 eb15029f 54000000/ff00001f f9400268 aa1303e0', 0),
    Site('list_clear_vcall_guard',          'code', 'd63f0100 f9400675 eb15029f 54000000/ff00001f f9400268 aa1303e0 9113835a f9400d08', 0),
    Site('list_clear_head_load_guard',      'code', 'f9400675 eb15029f 54000000/ff00001f f9400268 aa1303e0 9113835a f9400d08 d63f0100', 0),
    Site('list_clear_vtable_load_guard_3',  'code', 'f9400268 aa1303e0 9113835a f9400d08 d63f0100 f9400669 aa1f03e8 3868692a', 0),
    Site('list_clear_vtable_load_guard_4',  'code', 'f9400d08 d63f0100 f9400669 aa1f03e8 3868692a 3400000a/ff00001f 91000508 eb19011f', 0),
    Site('list_clear_vcall_guard_2',        'code', 'd63f0100 f9400669 aa1f03e8 3868692a 3400000a/ff00001f 91000508 eb19011f 54000001/ff00001f', 0),
    Site('list_clear_head_load_guard_2',    'code', 'f9400669 aa1f03e8 3868692a 3400000a/ff00001f 91000508 eb19011f 54000001/ff00001f 2a1f03e8', 0),
    Site('list_clear_name_load_guard',      'code', '3868692a 3400000a/ff00001f 91000508 eb19011f 54000001/ff00001f 2a1f03e8 b9401349 aa1403e0', 0),
    Site('list_clear_count_load_guard',     'code', 'b9401349 aa1403e0 aa1503e1 5100052a 6b09011f 1a8ab11a 93407f42 94000000/fc000000', 0),
    Site('list_clear_name_store_guard',     'code', '383aca9f 910006d6 f10402df 54000001/ff00001f a9444ff4 a94357f6 a9425ff8 a94167fa', 0),
    Site('ctrl_arg_load_guard',            'code', 'f9400109 9000000b/9f00001f f9401929 f940016b/ffc003ff eb0b013f 54000001/ff00001f f9400150 7941b109 37000009/fff8001f aa1f03eb b9409109 531d7122 37f80009/fff8001f 7100205f 54000008/ff00001f f940750a', 0),  # -> 0x7000006944
    Site('ctrl_vtable_load_guard',         'code', 'f9401929 f9447d6b eb0b013f 54000001/ff00001f f9400150 7941b109 37000009/fff8001f aa1f03eb b9409109 531d7122 37f80009/fff8001f 7100205f 54000008/ff00001f f940750a', 0),  # -> 0x700000694c
    Site('ctrl_list_head_store_guard',     'code', 'f9000109 9000000a/9f00001f f9000148/ffc003ff 90000008/9f00001f 91000108/ffc003ff 9100a269 91010260 b9003a7f', 0),  # -> 0x7000006b14
    Site('ctrl_node_flag_store_guard',     'code', 'b9003a7f a902a669 91004108 f9000268 94000000/fc000000 91022260 aa1f03e1 f900427f', 0),  # -> 0x7000006b30
    Site('ctrl_node_link_stp_guard',       'code', 'a902a669 91004108 f9000268 94000000/fc000000 91022260 aa1f03e1 f900427f 94000000/fc000000', 0),  # -> 0x7000006b34
    Site('ctrl_node_vptr_store_guard',     'code', 'f9000268 94000000/fc000000 91022260 aa1f03e1 f900427f 94000000/fc000000 f9036a93 aa1303e0', 0),  # -> 0x7000006b3c
    Site('ctrl_node_push_call_guard',      'code', '94000000/fc000000 91022260 aa1f03e1 f900427f 94000000/fc000000 f9036a93 aa1303e0 a9484ff4', 0),  # -> 0x7000006b40
    Site('ctrl_node_tail_store_guard',     'code', 'f900427f 94000000/fc000000 f9036a93 aa1303e0 a9484ff4 f9403bf5 a9467bfd 910243ff', 0),  # -> 0x7000006b4c
    Site('ctrl_hle_mutex_call_guard',      'code', '94000000/fc000000 f9036a93 aa1303e0 a9484ff4 f9403bf5 a9467bfd 910243ff d65f03c0', 0),  # -> 0x7000006b50
    Site('ctrl_ctor_resp_store_guard',     'code', 'f9000100 f9401be8 b5000000/ff00001f 14000000/fc000000 aa0003f3 aa0903e0 94000000/fc000000 9000000a/9f00001f', 0),  # -> 0x7000006ba4
    Site('ctrl_init_link_store_guard',     'code', 'f900012a 52800209 f9000fa8 52800408 f900013f f900011f 52800308 f900011f', 0),  # -> 0x7000006bf4
    Site('ctrl_init_zero_store_guard',     'code', 'f900013f f900011f 52800308 f900011f 14000000/fc000000 f9001be8 9102e008 91026015', 0),  # -> 0x7000006c04
    Site('ctrl_init_zero_store_guard_2',   'code', 'f900011f 52800308 f900011f 14000000/fc000000 f9001be8 9102e008 91026015 f9000fa0', 0),  # -> 0x7000006c08
    Site('ctrl_init_zero_store_guard_3',   'code', 'f900011f 14000000/fc000000 f9001be8 9102e008 91026015 f9000fa0 aa0803e0 94000000/fc000000', 0),  # -> 0x7000006c10
    Site('ctrl_probe_vcall_guard',         'code', 'd63f0120 aa0003f3 f9400fa0 14000000/fc000000 9102e109 f9000fa0 91026115 aa0903e0', 0),  # -> 0x7000006c64
    Site('ctrl_ctor_vf_vcall_guard',       'code', 'd63f0100 f9400fa0 aa1f03f3 f9401beb 14000000/fc000000 cb0d014d 14000000/fc000000 f9000fa0', 0),  # -> 0x7000006dd4
    Site('rn_08348',                   'code', 'f8008f3f a9017ebf 91004108 f90002a8 90000008/9f00001f 91000108/ffc003ff f9400108 b4000008/ff00001f', 0),  # -> 0x7000008348
    Site('rn_0834c',                   'code', 'a9017ebf 91004108 f90002a8 90000008/9f00001f 91000108/ffc003ff f9400108 b4000008/ff00001f 90000008/9f00001f', 0),  # -> 0x700000834c
    Site('rn_08354',                   'code', 'f90002a8 90000008/9f00001f 91000108/ffc003ff f9400108 b4000008/ff00001f 90000008/9f00001f f9400108/ffc003ff b4000008/ff00001f', 0),  # -> 0x7000008354
    Site('rn_084f0',                   'code', 'f90042bf f90002a8 90000009/9f00001f 9102a10a f9400129/ffc003ff 90000008/9f00001f 91000108/ffc003ff a902aaa8', 0),  # -> 0x70000084f0
    Site('rn_084f4',                   'code', 'f90002a8 90000009/9f00001f 9102a10a f9400129/ffc003ff 90000008/9f00001f 91000108/ffc003ff a902aaa8 91004129', 0),  # -> 0x70000084f4
    Site('rn_0850c',                   'code', 'a902aaa8 91004129 a94283ea b81d83bf f90012a9 12b00009 f9402c08 f90066a9', 0),  # -> 0x700000850c
    Site('rn_0851c',                   'code', 'f90012a9 12b00009 f9402c08 f90066a9 52800029 b900c2a9 a9097ebf 291a26aa', 0),  # -> 0x700000851c
    Site('rn_08524',                   'code', 'f9402c08 f90066a9 52800029 b900c2a9 a9097ebf 291a26aa b9008aa8 a90a7ebf', 0),  # -> 0x7000008524
    Site('rn_08528',                   'code', 'f90066a9 52800029 b900c2a9 a9097ebf 291a26aa b9008aa8 a90a7ebf a90b7ebf', 0),  # -> 0x7000008528
    Site('rn_08530',                   'code', 'b900c2a9 a9097ebf 291a26aa b9008aa8 a90a7ebf a90b7ebf b85d83a8 1ac82128', 0),  # -> 0x7000008530
    Site('rn_08534',                   'code', 'a9097ebf 291a26aa b9008aa8 a90a7ebf a90b7ebf b85d83a8 1ac82128 a90e7ea0', 0),  # -> 0x7000008534
    Site('rn_08538',                   'code', '291a26aa b9008aa8 a90a7ebf a90b7ebf b85d83a8 1ac82128 a90e7ea0 f9007abf', 0),  # -> 0x7000008538
    Site('rn_0853c',                   'code', 'b9008aa8 a90a7ebf a90b7ebf b85d83a8 1ac82128 a90e7ea0 f9007abf b900daa8', 0),  # -> 0x700000853c
    Site('rn_08540',                   'code', 'a90a7ebf a90b7ebf b85d83a8 1ac82128 a90e7ea0 f9007abf b900daa8 94000000/fc000000', 0),  # -> 0x7000008540
    Site('rn_08544',                   'code', 'a90b7ebf b85d83a8 1ac82128 a90e7ea0 f9007abf b900daa8 94000000/fc000000 b900faa0', 0),  # -> 0x7000008544
    Site('rn_08550',                   'code', 'a90e7ea0 f9007abf b900daa8 94000000/fc000000 b900faa0 90000008/9f00001f f90052b5 f9400108/ffc003ff', 0),  # -> 0x7000008550
    Site('rn_08554',                   'code', 'f9007abf b900daa8 94000000/fc000000 b900faa0 90000008/9f00001f f90052b5 f9400108/ffc003ff f9400100', 0),  # -> 0x7000008554
    Site('rn_08558',                   'code', 'b900daa8 94000000/fc000000 b900faa0 90000008/9f00001f f90052b5 f9400108/ffc003ff f9400100 b4000000/ff00001f', 0),  # -> 0x7000008558
    Site('rn_08560',                   'code', 'b900faa0 90000008/9f00001f f90052b5 f9400108/ffc003ff f9400100 b4000000/ff00001f b4000014/ff00001f f9400288', 0),  # -> 0x7000008560
    Site('rn_08568',                   'code', 'f90052b5 f9421908 f9400100 b4000000/ff00001f b4000014/ff00001f f9400288 90000009/9f00001f f9401908', 0),  # -> 0x7000008568
    Site('rn_08570',                   'code', 'f9400100 b4000000/ff00001f b4000014/ff00001f f9400288 90000009/9f00001f f9401908 f9400129/ffc003ff eb09011f', 0),  # -> 0x7000008570
    Site('rn_086f4',                   'code', 'f90042b4 52800402 94000000/fc000000 d100a3a0 d100c3a1 94000000/fc000000 f85d83a8 f9007aa8', 0),  # -> 0x70000086f4
    Site('rn_086fc',                   'code', '94000000/fc000000 d100a3a0 d100c3a1 94000000/fc000000 f85d83a8 f9007aa8 f85d03a8 b9008aa8', 0),  # -> 0x70000086fc
    Site('rn_08710',                   'code', 'f9007aa8 f85d03a8 b9008aa8 b940dab4 94000000/fc000000 f94072a0 12800001 aa1403e2', 0),  # -> 0x7000008710
    Site('rn_08718',                   'code', 'b9008aa8 b940dab4 94000000/fc000000 f94072a0 12800001 aa1403e2 94000000/fc000000 90000008/9f00001f', 0),  # -> 0x7000008718
    Site('rn_0871c',                   'code', 'b940dab4 94000000/fc000000 f94072a0 12800001 aa1403e2 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff', 0),  # -> 0x700000871c
    Site('rn_08720',                   'code', '94000000/fc000000 f94072a0 12800001 aa1403e2 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff f90002a8', 0),  # -> 0x7000008720
    Site('rn_08724',                   'code', 'f94072a0 12800001 aa1403e2 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff f90002a8 9102a108', 0),  # -> 0x7000008724
    Site('rn_08730',                   'code', '94000000/fc000000 90000008/9f00001f 91000108/ffc003ff f90002a8 9102a108 aa1503e1 f9001aa8 f9401fe8', 0),  # -> 0x7000008730
    Site('rn_0873c',                   'code', 'f90002a8 9102a108 aa1503e1 f9001aa8 f9401fe8 b9408900 f9004115 94000000/fc000000', 0),  # -> 0x700000873c
    Site('rn_08748',                   'code', 'f9001aa8 f9401fe8 b9408900 f9004115 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff b9400113', 0),  # -> 0x7000008748
    Site('rn_08750',                   'code', 'b9408900 f9004115 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff b9400113 94000000/fc000000 11000408', 0),  # -> 0x7000008750
    Site('rn_08754',                   'code', 'f9004115 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff b9400113 94000000/fc000000 11000408 aa1303e0', 0),  # -> 0x7000008754
    Site('rn_08758',                   'code', '94000000/fc000000 90000008/9f00001f 91000108/ffc003ff b9400113 94000000/fc000000 11000408 aa1303e0 93407d01', 0),  # -> 0x7000008758
    Site('rn_08768',                   'code', '94000000/fc000000 11000408 aa1303e0 93407d01 94000000/fc000000 a94c4ff4 a94b57f6 a94a5ff8', 0),  # -> 0x7000008768
    Site('rn_08778',                   'code', '94000000/fc000000 a94c4ff4 a94b57f6 a94a5ff8 a94967fa a9486ffc a9477bfd 910343ff d65f03c0 aa1703e0', 0),  # -> 0x7000008778
    Site('rn_08d7c',                   'code', 'f900033f 14000000/fc000000 aa1f03f7 c85f7f88 927ff908 c8097f88 35000009/ff00001f b4000013/ff00001f', 0),  # -> 0x7000008d7c
    Site('rn_0339c',                   'code', 'f9400288 90000015/9f00001f aa1403e0 f9401508 f94002b5/ffc003ff eb15011f 54000001/ff00001f 94000000/fc000000', 0),  # -> 0x700000339c
    Site('rn_033a8',                   'code', 'f9401508 f9447ab5 eb15011f 54000001/ff00001f 94000000/fc000000 aa1303e0 94000000/fc000000 b9400308', 0),  # -> 0x70000033a8
    Site('rn_036cc',                   'code', 'd63f0100 14000000/fc000000 aa1f03f3 14000000/fc000000 aa1303e0 52800101 d63f0100 aa0003f4', 0),  # -> 0x70000036cc
    Site('rn_033d4',                   'code', 'f9400268 90000018/9f00001f f9404108 f9400318/ffc003ff eb18011f 54000001/ff00001f 7941b268 37000008/fff8001f', 0),  # -> 0x70000033d4
    Site('rn_033dc',                   'code', 'f9404108 f9448318 eb18011f 54000001/ff00001f 7941b268 37000008/fff8001f aa1f03e8 f940766d', 0),  # -> 0x70000033dc
    Site('rn_0347c',                   'code', 'f9400008 aa0003f3 f9404108 eb18011f 54000001/ff00001f 7941b268 37000008/fff8001f aa1f03e8', 0),  # -> 0x700000347c
    Site('rn_03484',                   'code', 'f9404108 eb18011f 54000001/ff00001f 7941b268 37000008/fff8001f aa1f03e8 f940766d 9103826c', 0),  # -> 0x7000003484
    Site('rn_036e4',                   'code', 'd63f0100 aa0003f4 14000000/fc000000 9102e260 91026274 94000000/fc000000 aa1403e8 14000000/fc000000 f9400d2f eb0e01ff 54000003/ff00001f 14000000/fc000000 91008100 94000000/fc000000 14000000/fc000000 aa1303e0', 0),  # -> 0x70000036e4
    Site('rn_03728',                   'code', 'd63f0100 aa0003f4 14000000/fc000000 9102e260 91026274 94000000/fc000000 aa1403e8 14000000/fc000000 f9400d2f eb0e01ff 54000003/ff00001f 14000000/fc000000 91008100 94000000/fc000000 14000000/fc000000 d63f0100', 0),  # -> 0x7000003728
    Site('mc_05340',                     'code', 'f940e693 b5000013/ff00001f 9000000a/9f00001f 9100014a/ffc003ff f9400149 b4000009/ff00001f aa0003e8 b4000000/ff00001f f9400109', 8),  # -> 0x7000005340
    Site('mc_05348',                     'code', 'f940e693 b5000013/ff00001f 9000000a/9f00001f 9100014a/ffc003ff f9400149 b4000009/ff00001f aa0003e8 b4000000/ff00001f f9400109 9000000b/9f00001f f9401929', 10),  # -> 0x7000005348
    Site('mc_054b4',                     'code', 'a9017e7f a9000268 b4000000/ff00001f 7941b008 37000008/fff8001f aa1f03e8 aa0003eb f8478d69', 0),  # -> 0x70000054b4
    Site('mc_054b8',                     'code', 'a9000268 b4000000/ff00001f 7941b008 37000008/fff8001f aa1f03e8 aa0003eb f8478d69 b980156a', 0),  # -> 0x70000054b8
    Site('mc_05504',                     'code', 'f9000268 90000008/9f00001f aa1303e0 f9000113/ffc003ff 94000000/fc000000 f900e693 aa1303e0 a9484ff4', 0),  # -> 0x7000005504
    Site('mc_05514',                     'code', '94000000/fc000000 f900e693 aa1303e0 a9484ff4 f9403bf5 a9467bfd 910243ff d65f03c0', 0),  # -> 0x7000005514
    Site('mc_05554',                     'code', 'f9000660 b5000000/ff00001f 14000000/fc000000 9102e008 91026015 f9000fa0 aa0803e0 94000000/fc000000 f9400fa0 aa1503e8 14000000/fc000000 91008100 94000000/fc000000 14000000/fc000000 aa0003f3 aa0903e0 94000000/fc000000 9000000a/9f00001f aa0003e8 f940014a/ffc003ff aa1303e0 14000000/fc000000 f9000fa0', 0),  # -> 0x7000005554
    Site('mc_055c0',                     'code', 'd63f0120 aa1303ea aa0003f3 f9400fa0 14000000/fc000000 9102e109 f9000fa0 91026115 aa0903e0 f90013f0 aa0a03f3 f9001be8 94000000/fc000000 f94013f0 aa1503eb aa1303ea f9401be8 f9400fa0 14000000/fc000000 4b0203e2 3100053f', 0),  # -> 0x70000055c0
    Site('mc_04dd4',                     'code', 'f945f693 b5000013/ff00001f 9000000a/9f00001f 9100014a/ffc003ff f9400149 b4000009/ff00001f aa0003e8 b4000000/ff00001f f9400109', 8),  # -> 0x7000004dd4
    Site('mc_04ddc',                     'code', 'f945f693 b5000013/ff00001f 9000000a/9f00001f 9100014a/ffc003ff f9400149 b4000009/ff00001f aa0003e8 b4000000/ff00001f f9400109 9000000b/9f00001f f9401929', 10),  # -> 0x7000004ddc
    Site('mc_04f48',                     'code', 'a9017e7f a9000268 b4000000/ff00001f 7941b008 37000008/fff8001f aa1f03e8 aa0003eb f8478d69', 0),  # -> 0x7000004f48
    Site('mc_04f4c',                     'code', 'a9000268 b4000000/ff00001f 7941b008 37000008/fff8001f aa1f03e8 aa0003eb f8478d69 b980156a', 0),  # -> 0x7000004f4c
    Site('mc_04f98',                     'code', 'f9000268 90000008/9f00001f aa1303e0 f9000113/ffc003ff 94000000/fc000000 f905f693 aa1303e0 a9484ff4', 0),  # -> 0x7000004f98
    Site('mc_04fa8',                     'code', '94000000/fc000000 f905f693 aa1303e0 a9484ff4 f9403bf5 a9467bfd 910243ff d65f03c0', 0),  # -> 0x7000004fa8
    Site('mc_04fec',                     'code', 'f9000660 b5000000/ff00001f 14000000/fc000000 9102e008 91026015 f9000fa0 aa0803e0 94000000/fc000000 f9400fa0 aa1503e8 14000000/fc000000 91008100 94000000/fc000000 14000000/fc000000 aa0003f3 aa0903e0 94000000/fc000000 9000000a/9f00001f aa0003e8 f940014a/ffc003ff aa1303e0 14000000/fc000000 52800b01', 0),  # -> 0x7000004fec
    Site('mc_05058',                     'code', 'd63f0120 aa1303ea aa0003f3 f9400fa0 14000000/fc000000 9102e109 f9000fa0 91026115 aa0903e0 f90013f0 aa0a03f3 f9001be8 94000000/fc000000 f94013f0 aa1503eb aa1303ea f9401be8 f9400fa0 14000000/fc000000 4b0203e2 52800b01', 0),  # -> 0x7000005058
    Site('mc_03548',                     'code', 'f9400288 aa1403e0 f9401508 eb15011f 54000001/ff00001f 94000000/fc000000 f100073f 54000000/ff00001f', 0),  # -> 0x7000003548
    Site('mc_03550',                     'code', 'f9401508 eb15011f 54000001/ff00001f 94000000/fc000000 f100073f 54000000/ff00001f f94002c8 b9408900', 0),  # -> 0x7000003550
    Site('mc_03578',                     'code', 'f9400268 f9404108 eb18011f 54000001/ff00001f 7941b268 37000008/fff8001f aa1f03f8 f940766c', 0),  # -> 0x7000003578
    Site('mc_0357c',                     'code', 'f9404108 eb18011f 54000001/ff00001f 7941b268 37000008/fff8001f aa1f03f8 f940766c 9103826b', 0),  # -> 0x700000357c
    Site('mc_03640',                     'code', 'f9400288 aa1403e0 f9401508 eb15011f 54000001/ff00001f 94000000/fc000000 f10006ff 54000000/ff00001f', 0),  # -> 0x7000003640
    Site('mc_03648',                     'code', 'aa1403e0 f9401508 eb15011f 54000001/ff00001f 94000000/fc000000 f10006ff 54000000/ff00001f f94002c8 b9408900', 1),  # -> 0x7000003648
    Site('mc_03670',                     'code', 'f9400268 aa1303e0 f9401508 eb15011f 54000001/ff00001f 94000000/fc000000 a9454ff4 f94013f9', 0),  # -> 0x7000003670
    Site('mc_03678',                     'code', 'f9401508 eb15011f 54000001/ff00001f 94000000/fc000000 a9454ff4 f94013f9 a94457f6 a9435ff8', 0),  # -> 0x7000003678
    Site('mc_03764',                     'code', 'd63f0100 14000000/fc000000 aa1303e0 52800101 d63f0100 aa0003f4 14000000/fc000000 9102e260', 0),  # -> 0x7000003764
    Site('mc_03774',                     'code', 'd63f0100 aa0003f4 14000000/fc000000 9102e260 91026278 94000000/fc000000 14000000/fc000000 f9400d0e', 0),  # -> 0x7000003774
    Site('mc_037ac',                     'code', 'd63f0100 14000000/fc000000 d63f0100 14000000/fc000000', 0),  # -> 0x70000037ac
    Site('mc_037b4',                     'code', 'd63f0100 14000000/fc000000 d63f0100 14000000/fc000000', 2),  # -> 0x70000037b4
    Site('bt_0a784',                     'code', 'f9400109 9000000b/9f00001f f9401929 f940016b/ffc003ff eb0b013f 54000001/ff00001f f9400151 7941b109', 0),  # -> 0x700000a784
    Site('bt_0a78c',                     'code', 'f9401929 f9447d6b eb0b013f 54000001/ff00001f f9400151 7941b109 37000009/fff8001f aa1f03eb', 0),  # -> 0x700000a78c
    Site('bt_0a790',                     'code', 'f9447d6b eb0b013f 54000001/ff00001f f9400151 7941b109 37000009/fff8001f aa1f03eb b9409109', 0),  # -> 0x700000a790
    Site('bt_0a79c',                     'code', 'f9400151 7941b109 37000009/fff8001f aa1f03eb b9409109 531d7133 37f80009/fff8001f 7100227f', 0),  # -> 0x700000a79c
    Site('bt_0a7a0',                     'code', '7941b109 37000009/fff8001f aa1f03eb b9409109 531d7133 37f80009/fff8001f 7100227f 54000008/ff00001f', 0),  # -> 0x700000a7a0
    Site('bt_0a7ac',                     'code', 'b9409109 531d7133 37f80009/fff8001f 7100227f 54000008/ff00001f f940750c 9103810f eb0f019f', 0),  # -> 0x700000a7ac
    Site('bt_0a7c0',                     'code', 'f940750c 9103810f eb0f019f 54000000/ff00001f b980f509 cb0903ed 39437110 cb0901ee', 0),  # -> 0x700000a7c0
    Site('bt_0a7d0',                     'code', 'b980f509 cb0903ed 39437110 cb0901ee cb09018c 35000010/ff00001f f9400d90 f120fe1f', 0),  # -> 0x700000a7d0
    Site('bt_0a7d8',                     'code', '39437110 cb0901ee cb09018c 35000010/ff00001f f9400d90 f120fe1f 54000009/ff00001f 52810809', 0),  # -> 0x700000a7d8
    Site('bt_0a7e8',                     'code', 'f9400d90 f120fe1f 54000009/ff00001f 52810809 79402597 f9000d89 b980f511 8b0c0229', 0),  # -> 0x700000a7e8
    Site('bt_0a7f8',                     'code', '79402597 f9000d89 b980f511 8b0c0229 f940052e eb0f01df 54000001/ff00001f aa1f03f3', 0),  # -> 0x700000a7f8
    Site('bt_0a7fc',                     'code', 'f9000d89 b980f511 8b0c0229 f940052e eb0f01df 54000001/ff00001f aa1f03f3 f9400131', 0),  # -> 0x700000a7fc
    Site('bt_0a800',                     'code', 'b980f511 8b0c0229 f940052e eb0f01df 54000001/ff00001f aa1f03f3 f9400131 b4000011/ff00001f', 0),  # -> 0x700000a800
    Site('bt_0a808',                     'code', 'f940052e eb0f01df 54000001/ff00001f aa1f03f3 f9400131 b4000011/ff00001f f900062e f940052e', 0),  # -> 0x700000a808
    Site('bt_0a818',                     'code', 'f9400131 b4000011/ff00001f f900062e f940052e b400000e/ff00001f f9400131 f90001d1 a9007d3f', 0),  # -> 0x700000a818
    Site('bt_0a820',                     'code', 'f900062e f940052e b400000e/ff00001f f9400131 f90001d1 a9007d3f 9103e109 b940f10e', 0),  # -> 0x700000a820
    Site('bt_0a824',                     'code', 'f940052e b400000e/ff00001f f9400131 f90001d1 a9007d3f 9103e109 b940f10e b9409111', 0),  # -> 0x700000a824
    Site('bt_0a82c',                     'code', 'f9400131 f90001d1 a9007d3f 9103e109 b940f10e b9409111 510005ce 7100063f', 0),  # -> 0x700000a82c
    Site('bt_0a830',                     'code', 'f90001d1 a9007d3f 9103e109 b940f10e b9409111 510005ce 7100063f b900f10e', 0),  # -> 0x700000a830
    Site('bt_0a834',                     'code', 'a9007d3f 9103e109 b940f10e b9409111 510005ce 7100063f b900f10e b9810d0e', 0),  # -> 0x700000a834
    Site('bt_0a83c',                     'code', 'b940f10e b9409111 510005ce 7100063f b900f10e b9810d0e 8b0c01c1 54000001/ff00001f', 0),  # -> 0x700000a83c
    Site('bt_0a840',                     'code', 'b9409111 510005ce 7100063f b900f10e b9810d0e 8b0c01c1 54000001/ff00001f f940012e', 0),  # -> 0x700000a840
    Site('bt_0a84c',                     'code', 'b900f10e b9810d0e 8b0c01c1 54000001/ff00001f f940012e f9000121 a900242e b400000e/ff00001f', 0),  # -> 0x700000a84c
    Site('bt_0a850',                     'code', 'b9810d0e 8b0c01c1 54000001/ff00001f f940012e f9000121 a900242e b400000e/ff00001f f90005c1', 0),  # -> 0x700000a850
    Site('bt_0a85c',                     'code', 'f940012e f9000121 a900242e b400000e/ff00001f f90005c1 b9410909 11000529 b9010909', 0),  # -> 0x700000a85c
    Site('bt_0a860',                     'code', 'f9000121 a900242e b400000e/ff00001f f90005c1 b9410909 11000529 b9010909 d1218609', 0),  # -> 0x700000a860
    Site('bt_0a864',                     'code', 'a900242e b400000e/ff00001f f90005c1 b9410909 11000529 b9010909 d1218609 b100893f', 0),  # -> 0x700000a864
    Site('bt_0a86c',                     'code', 'f90005c1 b9410909 11000529 b9010909 d1218609 b100893f 54000008/ff00001f 8b17018d', 0),  # -> 0x700000a86c
    Site('bt_0a870',                     'code', 'b9410909 11000529 b9010909 d1218609 b100893f 54000008/ff00001f 8b17018d d121820e', 0),  # -> 0x700000a870
    Site('bt_0a878',                     'code', 'b9010909 d1218609 b100893f 54000008/ff00001f 8b17018d d121820e b90871bf 529ffff0', 0),  # -> 0x700000a878
    Site('bt_0a890',                     'code', 'b90871bf 529ffff0 f90435bf 912181a9 f90431bf f9043dae 7910e1b0 b980f50d', 0),  # -> 0x700000a890
    Site('bt_0a898',                     'code', 'f90435bf 912181a9 f90431bf f9043dae 7910e1b0 b980f50d b5000013/ff00001f 8b0d0129', 0),  # -> 0x700000a898
    Site('bt_0a8a0',                     'code', 'f90431bf f9043dae 7910e1b0 b980f50d b5000013/ff00001f 8b0d0129 f94001ed f90001e9', 0),  # -> 0x700000a8a0
    Site('bt_0a8a4',                     'code', 'f9043dae 7910e1b0 b980f50d b5000013/ff00001f 8b0d0129 f94001ed f90001e9 a9003d2d', 0),  # -> 0x700000a8a4
    Site('bt_0a8a8',                     'code', '7910e1b0 b980f50d b5000013/ff00001f 8b0d0129 f94001ed f90001e9 a9003d2d b400000d/ff00001f', 0),  # -> 0x700000a8a8
    Site('bt_0a8ac',                     'code', 'b980f50d b5000013/ff00001f 8b0d0129 f94001ed f90001e9 a9003d2d b400000d/ff00001f f90005a9', 0),  # -> 0x700000a8ac
    Site('bt_0a8b8',                     'code', 'f94001ed f90001e9 a9003d2d b400000d/ff00001f f90005a9 b940f109 11000529 b900f109', 0),  # -> 0x700000a8b8
    Site('bt_0a8bc',                     'code', 'f90001e9 a9003d2d b400000d/ff00001f f90005a9 b940f109 11000529 b900f109 7941b508', 0),  # -> 0x700000a8bc
    Site('bt_0a8c0',                     'code', 'a9003d2d b400000d/ff00001f f90005a9 b940f109 11000529 b900f109 7941b508 79002188', 0),  # -> 0x700000a8c0
    Site('bt_0a8c8',                     'code', 'f90005a9 b940f109 11000529 b900f109 7941b508 79002188 79402588 8b080188 91008113 b500000b/ff00001f 90000008/9f00001f 91000108/ffc003ff f9035660', 0),  # -> 0x700000a8c8
    Site('bt_0a8cc',                     'code', 'b940f109 11000529 b900f109 7941b508 79002188 79402588 8b080188 91008113 b500000b/ff00001f 90000008/9f00001f 91000108/ffc003ff f9035660', 0),  # -> 0x700000a8cc
    Site('bt_0a8d4',                     'code', 'b900f109 7941b508 79002188 79402588 8b080188 91008113 b500000b/ff00001f 90000008/9f00001f 91000108/ffc003ff f9035660', 0),  # -> 0x700000a8d4
    Site('bt_0a8d8',                     'code', '7941b508 79002188 79402588 8b080188 91008113 b500000b/ff00001f 90000008/9f00001f 91000108/ffc003ff f9035660', 0),  # -> 0x700000a8d8
    Site('bt_0a8dc',                     'code', '79002188 79402588 8b080188 91008113 b500000b/ff00001f 90000008/9f00001f 91000108/ffc003ff f9035660', 0),  # -> 0x700000a8dc
    Site('bt_0a8e0',                     'code', '79402588 8b080188 91008113 b500000b/ff00001f 90000008/9f00001f 91000108/ffc003ff f9035660 f9035a7f', 0),  # -> 0x700000a8e0
    Site('bt_0a8f8',                     'code', 'f9035660 f9035a7f 91004108 f9035e7f f9035268 911a8268 b4000000/ff00001f 7941b009', 0),  # -> 0x700000a8f8
    Site('bt_0a8fc',                     'code', 'f9035a7f 91004108 f9035e7f f9035268 911a8268 b4000000/ff00001f 7941b009 37000009/fff8001f', 0),  # -> 0x700000a8fc
    Site('bt_0a904',                     'code', 'f9035e7f f9035268 911a8268 b4000000/ff00001f 7941b009 37000009/fff8001f aa1f03f5 aa0003eb', 0),  # -> 0x700000a904
    Site('bt_0a908',                     'code', 'f9035268 911a8268 b4000000/ff00001f 7941b009 37000009/fff8001f aa1f03f5 aa0003eb f8478d69', 0),  # -> 0x700000a908
    Site('bt_0a914',                     'code', '7941b009 37000009/fff8001f aa1f03f5 aa0003eb f8478d69 b980156a 8b08014a f900016a', 0),  # -> 0x700000a914
    Site('bt_0a924',                     'code', 'f8478d69 b980156a 8b08014a f900016a a9002d49 b4000009/ff00001f f900052a b9408809', 0),  # -> 0x700000a924
    Site('bt_0a928',                     'code', 'b980156a 8b08014a f900016a a9002d49 b4000009/ff00001f f900052a b9408809 11000529', 0),  # -> 0x700000a928
    Site('bt_0a930',                     'code', 'f900016a a9002d49 b4000009/ff00001f f900052a b9408809 11000529 b9008809 b5000015/ff00001f', 0),  # -> 0x700000a930
    Site('bt_0a934',                     'code', 'a9002d49 b4000009/ff00001f f900052a b9408809 11000529 b9008809 b5000015/ff00001f 90000009/9f00001f', 0),  # -> 0x700000a934
    Site('bt_0a93c',                     'code', 'f900052a b9408809 11000529 b9008809 b5000015/ff00001f 90000009/9f00001f 91000129/ffc003ff f9000109', 0),  # -> 0x700000a93c
    Site('bt_0a940',                     'code', 'b9408809 11000529 b9008809 b5000015/ff00001f 90000009/9f00001f 91000129/ffc003ff f9000109 90000009/9f00001f', 0),  # -> 0x700000a940
    Site('bt_0a948',                     'code', 'b9008809 b5000015/ff00001f 90000009/9f00001f 91000129/ffc003ff f9000109 90000009/9f00001f 9100a260 f9000128/ffc003ff', 0),  # -> 0x700000a948
    Site('bt_0a958',                     'code', 'f9000109 90000009/9f00001f 9100a260 f9000128/ffc003ff 52802702 2a1f03e1 94000000/fc000000 91066268', 0),  # -> 0x700000a958
    Site('bt_0a964',                     'code', 'f9064128 52802702 2a1f03e1 94000000/fc000000 91066268 3906427f 90000009/9f00001f 38014d1f', 0),  # -> 0x700000a964
    Site('bt_0a970',                     'code', '94000000/fc000000 91066268 3906427f 90000009/9f00001f 38014d1f f9400129/ffc003ff 52802015 390aae7f', 0),  # -> 0x700000a970
    Site('bt_0a978',                     'code', '3906427f 90000009/9f00001f 38014d1f f9400129/ffc003ff 52802015 390aae7f b901aa75 9000000a/9f00001f', 0),  # -> 0x700000a978
    Site('bt_0a980',                     'code', '38014d1f f9438d29 52802015 390aae7f b901aa75 9000000a/9f00001f 9100014a/ffc003ff 12800017', 0),  # -> 0x700000a980
    Site('bt_0a984',                     'code', 'f9438d29 52802015 390aae7f b901aa75 9000000a/9f00001f 9100014a/ffc003ff 12800017 911a0260', 0),  # -> 0x700000a984
    Site('bt_0a98c',                     'code', '390aae7f b901aa75 9000000a/9f00001f 9100014a/ffc003ff 12800017 911a0260 91004129 f9000269', 0),  # -> 0x700000a98c
    Site('bt_0a990',                     'code', 'b901aa75 9000000a/9f00001f 9100014a/ffc003ff 12800017 911a0260 91004129 f9000269 90000009/9f00001f', 0),  # -> 0x700000a990
    Site('bt_0a9a8',                     'code', 'f9000269 90000009/9f00001f 9100414a f9400129/ffc003ff a9187e6a b902ca75 390f2e7f 91004136', 0),  # -> 0x700000a9a8
    Site('bt_0a9b4',                     'code', 'f947d929 a9187e6a b902ca75 390f2e7f 91004136 390f427f 91108269 f9015e76', 0),  # -> 0x700000a9b4
    Site('bt_0a9b8',                     'code', 'a9187e6a b902ca75 390f2e7f 91004136 390f427f 91108269 f9015e76 a919a276', 0),  # -> 0x700000a9b8
    Site('bt_0a9bc',                     'code', 'b902ca75 390f2e7f 91004136 390f427f 91108269 f9015e76 a919a276 d2e00028', 0),  # -> 0x700000a9bc
    Site('bt_0a9c0',                     'code', '390f2e7f 91004136 390f427f 91108269 f9015e76 a919a276 d2e00028 f9015a68', 0),  # -> 0x700000a9c0
    Site('bt_0a9c8',                     'code', '390f427f 91108269 f9015e76 a919a276 d2e00028 f9015a68 910ae268 38014d1f', 0),  # -> 0x700000a9c8
    Site('bt_0a9d0',                     'code', 'f9015e76 a919a276 d2e00028 f9015a68 910ae268 38014d1f f9016268 910f5268', 0),  # -> 0x700000a9d0
    Site('bt_0a9d4',                     'code', 'a919a276 d2e00028 f9015a68 910ae268 38014d1f f9016268 910f5268 f9000117', 0),  # -> 0x700000a9d4
    Site('bt_0a9dc',                     'code', 'f9015a68 910ae268 38014d1f f9016268 910f5268 f9000117 910f8268 7907ba7f', 0),  # -> 0x700000a9dc
    Site('bt_0a9e4',                     'code', '38014d1f f9016268 910f5268 f9000117 910f8268 7907ba7f 38014d1f f901f668', 0),  # -> 0x700000a9e4
    Site('bt_0a9e8',                     'code', 'f9016268 910f5268 f9000117 910f8268 7907ba7f 38014d1f f901f668 52800408', 0),  # -> 0x700000a9e8
    Site('bt_0a9f0',                     'code', 'f9000117 910f8268 7907ba7f 38014d1f f901f668 52800408 b903f268 90000008/9f00001f', 0),  # -> 0x700000a9f0
    Site('bt_0a9f8',                     'code', '7907ba7f 38014d1f f901f668 52800408 b903f268 90000008/9f00001f 91000108/ffc003ff 39104e7f', 0),  # -> 0x700000a9f8
    Site('bt_0a9fc',                     'code', '38014d1f f901f668 52800408 b903f268 90000008/9f00001f 91000108/ffc003ff 39104e7f 91004108', 0),  # -> 0x700000a9fc
    Site('bt_0aa00',                     'code', 'f901f668 52800408 b903f268 90000008/9f00001f 91000108/ffc003ff 39104e7f 91004108 7908327f', 0),  # -> 0x700000aa00
    Site('bt_0aa08',                     'code', 'b903f268 90000008/9f00001f 91000108/ffc003ff 39104e7f 91004108 7908327f b9043275 38014d3f', 0),  # -> 0x700000aa08
    Site('bt_0aa14',                     'code', '39104e7f 91004108 7908327f b9043275 38014d3f f9021669 3914ce7f f9021276', 0),  # -> 0x700000aa14
    Site('bt_0aa1c',                     'code', '7908327f b9043275 38014d3f f9021669 3914ce7f f9021276 b9054a75 39192e7f', 0),  # -> 0x700000aa1c
    Site('bt_0aa20',                     'code', 'b9043275 38014d3f f9021669 3914ce7f f9021276 b9054a75 39192e7f f9029e76', 0),  # -> 0x700000aa20
    Site('bt_0aa24',                     'code', '38014d3f f9021669 3914ce7f f9021276 b9054a75 39192e7f f9029e76 3919ce7f', 0),  # -> 0x700000aa24
    Site('bt_0aa28',                     'code', 'f9021669 3914ce7f f9021276 b9054a75 39192e7f f9029e76 3919ce7f f901f268', 0),  # -> 0x700000aa28
    Site('bt_0aa2c',                     'code', '3914ce7f f9021276 b9054a75 39192e7f f9029e76 3919ce7f f901f268 9114e268', 0),  # -> 0x700000aa2c
    Site('bt_0aa30',                     'code', 'f9021276 b9054a75 39192e7f f9029e76 3919ce7f f901f268 9114e268 38014d1f', 0),  # -> 0x700000aa30
    Site('bt_0aa34',                     'code', 'b9054a75 39192e7f f9029e76 3919ce7f f901f268 9114e268 38014d1f f902a268', 0),  # -> 0x700000aa34
    Site('bt_0aa38',                     'code', '39192e7f f9029e76 3919ce7f f901f268 9114e268 38014d1f f902a268 91194268', 0),  # -> 0x700000aa38
    Site('bt_0aa3c',                     'code', 'f9029e76 3919ce7f f901f268 9114e268 38014d1f f902a268 91194268 91005109', 0),  # -> 0x700000aa3c
    Site('bt_0aa40',                     'code', '3919ce7f f901f268 9114e268 38014d1f f902a268 91194268 91005109 3900511f', 0),  # -> 0x700000aa40
    Site('bt_0aa44',                     'code', 'f901f268 9114e268 38014d1f f902a268 91194268 91005109 3900511f 90000008/9f00001f', 0),  # -> 0x700000aa44
    Site('bt_0aa4c',                     'code', '38014d1f f902a268 91194268 91005109 3900511f 90000008/9f00001f f9032e69 52800209', 0),  # -> 0x700000aa4c
    Site('bt_0aa50',                     'code', 'f902a268 91194268 91005109 3900511f 90000008/9f00001f f9032e69 52800209 b9066269', 0),  # -> 0x700000aa50
    Site('bt_0aa5c',                     'code', '3900511f 90000008/9f00001f f9032e69 52800209 b9066269 f9400108/ffc003ff 91004108 f9032a68', 0),  # -> 0x700000aa5c
    Site('bt_0aa64',                     'code', 'f9032e69 52800209 b9066269 f9422908 91004108 f9032a68 90000008/9f00001f 91000108/ffc003ff', 0),  # -> 0x700000aa64
    Site('bt_0aa6c',                     'code', 'b9066269 f9422908 91004108 f9032a68 90000008/9f00001f 91000108/ffc003ff 790cf27f 390f467f', 0),  # -> 0x700000aa6c
    Site('bt_0aa70',                     'code', 'f9422908 91004108 f9032a68 90000008/9f00001f 91000108/ffc003ff 790cf27f 390f467f f9000113', 0),  # -> 0x700000aa70
    Site('bt_0aa78',                     'code', 'f9032a68 90000008/9f00001f 91000108/ffc003ff 790cf27f 390f467f f9000113 52800028 390f6668', 0),  # -> 0x700000aa78
    Site('bt_0aa84',                     'code', '790cf27f 390f467f f9000113 52800028 390f6668 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff', 0),  # -> 0x700000aa84
    Site('bt_0aa88',                     'code', '390f467f f9000113 52800028 390f6668 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff b906c27f', 0),  # -> 0x700000aa88
    Site('bt_0aa8c',                     'code', 'f9000113 52800028 390f6668 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff b906c27f f9000268', 0),  # -> 0x700000aa8c
    Site('bt_0aa94',                     'code', '390f6668 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff b906c27f f9000268 91012108 911fd269', 0),  # -> 0x700000aa94
    Site('bt_0aa98',                     'code', '94000000/fc000000 90000008/9f00001f 91000108/ffc003ff b906c27f f9000268 91012108 911fd269 f9034268', 0),  # -> 0x700000aa98
    Site('bt_0aaa4',                     'code', 'b906c27f f9000268 91012108 911fd269 f9034268 911b2268 9120126a 38014d1f', 0),  # -> 0x700000aaa4
    Site('bt_0aaa8',                     'code', 'f9000268 91012108 911fd269 f9034268 911b2268 9120126a 38014d1f f9036a68', 0),  # -> 0x700000aaa8
    Site('bt_0aab4',                     'code', 'f9034268 911b2268 9120126a 38014d1f f9036a68 911f9268 f900013f f900011f', 0),  # -> 0x700000aab4
    Site('bt_0aac0',                     'code', '38014d1f f9036a68 911f9268 f900013f f900011f f800511f 52802028 f800713f', 0),  # -> 0x700000aac0
    Site('bt_0aac4',                     'code', 'f9036a68 911f9268 f900013f f900011f f800511f 52802028 f800713f 91208269', 0),  # -> 0x700000aac4
    Site('bt_0aacc',                     'code', 'f900013f f900011f f800511f 52802028 f800713f 91208269 79101a68 91203a68', 0),  # -> 0x700000aacc
    Site('bt_0aad0',                     'code', 'f900011f f800511f 52802028 f800713f 91208269 79101a68 91203a68 391b127f', 0),  # -> 0x700000aad0
    Site('bt_0aad4',                     'code', 'f800511f 52802028 f800713f 91208269 79101a68 91203a68 391b127f b906da75', 0),  # -> 0x700000aad4
    Site('bt_0aadc',                     'code', 'f800713f 91208269 79101a68 91203a68 391b127f b906da75 391f6e7f f9036676', 0),  # -> 0x700000aadc
    Site('bt_0aae4',                     'code', '79101a68 91203a68 391b127f b906da75 391f6e7f f9036676 391f827f f9000157', 0),  # -> 0x700000aae4
    Site('bt_0aaec',                     'code', '391b127f b906da75 391f6e7f f9036676 391f827f f9000157 f9041e7f f800711f', 0),  # -> 0x700000aaec
    Site('bt_0aaf0',                     'code', 'b906da75 391f6e7f f9036676 391f827f f9000157 f9041e7f f800711f f900011f', 0),  # -> 0x700000aaf0
    Site('bt_0aaf4',                     'code', '391f6e7f f9036676 391f827f f9000157 f9041e7f f800711f f900011f f800f13f', 0),  # -> 0x700000aaf4
    Site('bt_0aaf8',                     'code', 'f9036676 391f827f f9000157 f9041e7f f800711f f900011f f800f13f f904167f', 0),  # -> 0x700000aaf8
    Site('bt_0aafc',                     'code', '391f827f f9000157 f9041e7f f800711f f900011f f800f13f f904167f f904127f', 0),  # -> 0x700000aafc
    Site('bt_0ab00',                     'code', 'f9000157 f9041e7f f800711f f900011f f800f13f f904167f f904127f f9064693', 0),  # -> 0x700000ab00
    Site('bt_0ab04',                     'code', 'f9041e7f f800711f f900011f f800f13f f904167f f904127f f9064693 aa1303e0', 0),  # -> 0x700000ab04
    Site('bt_0ab08',                     'code', 'f800711f f900011f f800f13f f904167f f904127f f9064693 aa1303e0 a9484ff4', 0),  # -> 0x700000ab08
    Site('bt_0ab0c',                     'code', 'f900011f f800f13f f904167f f904127f f9064693 aa1303e0 a9484ff4 a94757f6', 0),  # -> 0x700000ab0c
    Site('bt_0ab10',                     'code', 'f800f13f f904167f f904127f f9064693 aa1303e0 a9484ff4 a94757f6 a9465ff8', 0),  # -> 0x700000ab10
    Site('bt_0ab14',                     'code', 'f904167f f904127f f9064693 aa1303e0 a9484ff4 a94757f6 a9465ff8 a9457bfd', 0),  # -> 0x700000ab14
    Site('bt_0ab18',                     'code', 'f904127f f9064693 aa1303e0 a9484ff4 a94757f6 a9465ff8 a9457bfd 910243ff', 0),  # -> 0x700000ab18
    Site('bt_0ab1c',                     'code', 'f9064693 aa1303e0 a9484ff4 a94757f6 a9465ff8 a9457bfd 910243ff d65f03c0', 0),  # -> 0x700000ab1c
    Site('bt_0ab60',                     'code', 'f94002c0 b4000000/ff00001f 94000000/fc000000 aa1503e8 f90002e0 b5000000/ff00001f 14000000/fc000000 aa0003f3', 0),  # -> 0x700000ab60
    Site('bt_0ab70',                     'code', 'f90002e0 b5000000/ff00001f 14000000/fc000000 aa0003f3 aa0903e0 aa0a03f6 94000000/fc000000 aa1603ea', 0),  # -> 0x700000ab70
    Site('bt_0abb8',                     'code', 'f9000128 5280d708 f90002ff f900011f 5280d608 f900011f 14000000/fc000000 aa0803f6', 0),  # -> 0x700000abb8
    Site('bt_0abc0',                     'code', 'f90002ff f900011f 5280d608 f900011f 14000000/fc000000 aa0803f6 9102e008 91026015', 0),  # -> 0x700000abc0
    Site('bt_0abc4',                     'code', 'f900011f 5280d608 f900011f 14000000/fc000000 aa0803f6 9102e008 91026015 aa0003f7', 0),  # -> 0x700000abc4
    Site('bt_0abcc',                     'code', 'f900011f 14000000/fc000000 aa0803f6 9102e008 91026015 aa0003f7 aa0803e0 94000000/fc000000', 0),  # -> 0x700000abcc
    Site('bt_0ac20',                     'code', 'd63f0120 aa1303ea aa0003f3 aa1503e0 14000000/fc000000 9102e109 aa0003f5 91026118', 0),  # -> 0x700000ac20
    Site('bt_0ad88',                     'code', 'd63f0100 9000000a/9f00001f a941afe0 f940014a/ffc003ff aa1f03f3 14000000/fc000000 cb1101d3 14000000/fc000000', 0),  # -> 0x700000ad88
    Site('bu_61570',                     'code', 'f94396f7 b94012e8 b9402ae9 6b09011f 5400000a/ff00001f f9400ef3 b4000013/ff00001f f9400268', 0),  # -> 0x7000c61570
    Site('bu_61574',                     'code', 'b94012e8 b9402ae9 6b09011f 5400000a/ff00001f f9400ef3 b4000013/ff00001f f9400268 f9000ee8', 0),  # -> 0x7000c61574
    Site('bu_61578',                     'code', 'b9402ae9 6b09011f 5400000a/ff00001f f9400ef3 b4000013/ff00001f f9400268 f9000ee8 a9007e7f', 0),  # -> 0x7000c61578
    Site('bu_61584',                     'code', 'f9400ef3 b4000013/ff00001f f9400268 f9000ee8 a9007e7f 94000000/fc000000 f9000260 aa1303e8', 0),  # -> 0x7000c61584
    Site('bu_6158c',                     'code', 'f9400268 f9000ee8 a9007e7f 94000000/fc000000 f9000260 aa1303e8 f94002e9 f8010d1f', 0),  # -> 0x7000c6158c
    Site('bu_61590',                     'code', 'f9000ee8 a9007e7f 94000000/fc000000 f9000260 aa1303e8 f94002e9 f8010d1f f90002e8', 0),  # -> 0x7000c61590
    Site('bu_61594',                     'code', 'a9007e7f 94000000/fc000000 f9000260 aa1303e8 f94002e9 f8010d1f f90002e8 f9000e77', 0),  # -> 0x7000c61594
    Site('bu_6159c',                     'code', 'f9000260 aa1303e8 f94002e9 f8010d1f f90002e8 f9000e77 f9000109 b4000009/ff00001f', 0),  # -> 0x7000c6159c
    Site('bu_615a4',                     'code', 'f94002e9 f8010d1f f90002e8 f9000e77 f9000109 b4000009/ff00001f f9000528 b94012e8', 0),  # -> 0x7000c615a4
    Site('bu_615a8',                     'code', 'f8010d1f f90002e8 f9000e77 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508', 0),  # -> 0x7000c615a8
    Site('bu_615ac',                     'code', 'f90002e8 f9000e77 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8', 0),  # -> 0x7000c615ac
    Site('bu_615b0',                     'code', 'f9000e77 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8 94000000/fc000000', 0),  # -> 0x7000c615b0
    Site('bu_615b4',                     'code', 'f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff a9002260', 0),  # -> 0x7000c615b4
    Site('bu_615bc',                     'code', 'f9000528 b94012e8 11000508 b90012e8 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff a9002260', 0),  # -> 0x7000c615bc
    Site('bu_615c0',                     'code', 'b94012e8 11000508 b90012e8 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff a9002260 b94012e8', 0),  # -> 0x7000c615c0
    Site('bu_615c8',                     'code', 'b90012e8 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff a9002260 b94012e8 b9402ae9 6b09011f', 0),  # -> 0x7000c615c8
    Site('bu_615d8',                     'code', 'a9002260 b94012e8 b9402ae9 6b09011f 5400000a/ff00001f f9400ef4 b4000014/ff00001f f9400288', 0),  # -> 0x7000c615d8
    Site('bu_615dc',                     'code', 'b94012e8 b9402ae9 6b09011f 5400000a/ff00001f f9400ef4 b4000014/ff00001f f9400288 f9000ee8', 0),  # -> 0x7000c615dc
    Site('bu_615e0',                     'code', 'b9402ae9 6b09011f 5400000a/ff00001f f9400ef4 b4000014/ff00001f f9400288 f9000ee8 a9007e9f', 0),  # -> 0x7000c615e0
    Site('bu_615ec',                     'code', 'f9400ef4 b4000014/ff00001f f9400288 f9000ee8 a9007e9f 94000000/fc000000 f9000280 aa1403e8', 0),  # -> 0x7000c615ec
    Site('bu_615f4',                     'code', 'f9400288 f9000ee8 a9007e9f 94000000/fc000000 f9000280 aa1403e8 f94002e9 f8010d1f', 0),  # -> 0x7000c615f4
    Site('bu_615f8',                     'code', 'f9000ee8 a9007e9f 94000000/fc000000 f9000280 aa1403e8 f94002e9 f8010d1f f90002e8', 0),  # -> 0x7000c615f8
    Site('bu_615fc',                     'code', 'a9007e9f 94000000/fc000000 f9000280 aa1403e8 f94002e9 f8010d1f f90002e8 f9000e97', 0),  # -> 0x7000c615fc
    Site('bu_61604',                     'code', 'f9000280 aa1403e8 f94002e9 f8010d1f f90002e8 f9000e97 f9000109 b4000009/ff00001f', 0),  # -> 0x7000c61604
    Site('bu_6160c',                     'code', 'f94002e9 f8010d1f f90002e8 f9000e97 f9000109 b4000009/ff00001f f9000528 b94012e8', 0),  # -> 0x7000c6160c
    Site('bu_61610',                     'code', 'f8010d1f f90002e8 f9000e97 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508', 0),  # -> 0x7000c61610
    Site('bu_61614',                     'code', 'f90002e8 f9000e97 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8', 0),  # -> 0x7000c61614
    Site('bu_61618',                     'code', 'f9000e97 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8 52800038', 0),  # -> 0x7000c61618
    Site('bu_6161c',                     'code', 'f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8 52800038 72a00118', 0),  # -> 0x7000c6161c
    Site('bu_61624',                     'code', 'f9000528 b94012e8 11000508 b90012e8 52800038 72a00118 52800113 72b24453', 0),  # -> 0x7000c61624
    Site('bu_61628',                     'code', 'b94012e8 11000508 b90012e8 52800038 72a00118 52800113 72b24453 94000000/fc000000', 0),  # -> 0x7000c61628
    Site('bu_61630',                     'code', 'b90012e8 52800038 72a00118 52800113 72b24453 94000000/fc000000 90000019/9f00001f 91000339/ffc003ff', 0),  # -> 0x7000c61630
    Site('bu_61650',                     'code', 'a9006680 d53b4408 b2680108 d51b4408 94000000/fc000000 2a1f03e0 2a1303e1 94000000/fc000000', 0),  # -> 0x7000c61650
    Site('bu_61690',                     'code', 'f9438ad6 7100069f 790002df f9000edf a900fedf f941335a 5400000b/ff00001f 910083e8', 0),  # -> 0x7000c61690
    Site('bu_61698',                     'code', '790002df f9000edf a900fedf f941335a 5400000b/ff00001f 910083e8 91004349 b90023f4', 0),  # -> 0x7000c61698
    Site('bu_6169c',                     'code', 'f9000edf a900fedf f941335a 5400000b/ff00001f 910083e8 91004349 b90023f4 9100410a', 0),  # -> 0x7000c6169c
    Site('bu_616a0',                     'code', 'a900fedf f941335a 5400000b/ff00001f 910083e8 91004349 b90023f4 9100410a 90000008/9f00001f', 0),  # -> 0x7000c616a0
    Site('bu_616a4',                     'code', 'f941335a 5400000b/ff00001f 910083e8 91004349 b90023f4 9100410a 90000008/9f00001f 91000108/ffc003ff', 0),  # -> 0x7000c616a4
    Site('bu_6171c',                     'code', 'f86bd80d 93407d6c eb0801bf 54000000/ff00001f aa1f03ee 386e69af 386e6910 6b1001ff', 0),  # -> 0x7000c6171c
    Site('bu_61730',                     'code', '386e69af 386e6910 6b1001ff 54000000/ff00001f eb0901bf 54000000/ff00001f aa1f03ee 386e69af', 0),  # -> 0x7000c61730
    Site('bu_61734',                     'code', '386e6910 6b1001ff 54000000/ff00001f eb0901bf 54000000/ff00001f aa1f03ee 386e69af 386e6930', 0),  # -> 0x7000c61734
    Site('bu_6174c',                     'code', '386e69af 386e6930 6b1001ff 54000000/ff00001f eb0a01bf 54000000/ff00001f aa0a03ee aa1803ef', 0),  # -> 0x7000c6174c
    Site('bu_61750',                     'code', '386e6930 6b1001ff 54000000/ff00001f eb0a01bf 54000000/ff00001f aa0a03ee aa1803ef 384015b0', 0),  # -> 0x7000c61750
    Site('bu_617fc',                     'code', 'f9443508 2a1303e1 b9000113 94000000/fc000000 90000008/9f00001f f9400108/ffc003ff b9400109 34000009/ff00001f', 0),  # -> 0x7000c617fc
    Site('bu_61804',                     'code', 'b9000113 94000000/fc000000 90000008/9f00001f f9400108/ffc003ff b9400109 34000009/ff00001f f9400508 f9400113', 0),  # -> 0x7000c61804
    Site('bu_61810',                     'code', 'f943e108 b9400109 34000009/ff00001f f9400508 f9400113 90000008/9f00001f 91000108/ffc003ff 91004349', 0),  # -> 0x7000c61810
    Site('bu_61814',                     'code', 'b9400109 34000009/ff00001f f9400508 f9400113 90000008/9f00001f 91000108/ffc003ff 91004349 910083e1', 0),  # -> 0x7000c61814
    Site('bu_6181c',                     'code', 'f9400508 f9400113 90000008/9f00001f 91000108/ffc003ff 91004349 910083e1 a90223e9 aa1f03e0', 0),  # -> 0x7000c6181c
    Site('bu_61820',                     'code', 'f9400113 90000008/9f00001f 91000108/ffc003ff 91004349 910083e1 a90223e9 aa1f03e0 aa1303e2', 0),  # -> 0x7000c61820
    Site('bu_61858',                     'code', 'f9400288 90000009/9f00001f aa1403e0 f9401508 f9400129/ffc003ff eb09011f 54000001/ff00001f 94000000/fc000000', 0),  # -> 0x7000c61858
    Site('bu_61864',                     'code', 'f9401508 f9447929 eb09011f 54000001/ff00001f 94000000/fc000000 aa1303e0 94000000/fc000000 90000008/9f00001f', 0),  # -> 0x7000c61864
    Site('bu_61868',                     'code', 'f9447929 eb09011f 54000001/ff00001f 94000000/fc000000 aa1303e0 94000000/fc000000 90000008/9f00001f 90000009/9f00001f', 0),  # -> 0x7000c61868
    Site('bu_61888',                     'code', 'f9445d08 f9445929 90000014/9f00001f 91000294/ffc003ff f9000109 90000008/9f00001f f9400108/ffc003ff 3900f7ff', 0),  # -> 0x7000c61888
    Site('bu_6188c',                     'code', 'f9445929 90000014/9f00001f 91000294/ffc003ff f9000109 90000008/9f00001f f9400108/ffc003ff 3900f7ff 3900ffff', 0),  # -> 0x7000c6188c
    Site('bu_61898',                     'code', 'f9000109 90000008/9f00001f f9400108/ffc003ff 3900f7ff 3900ffff b90063ff a9402109 f802c3e8', 0),  # -> 0x7000c61898
    Site('bu_618a0',                     'code', 'f9446108 3900f7ff 3900ffff b90063ff a9402109 f802c3e8 52820008 f80243e9', 0),  # -> 0x7000c618a0
    Site('bu_618b0',                     'code', 'a9402109 f802c3e8 52820008 f80243e9 12800009 b9004be8 52800048 b90057e9', 0),  # -> 0x7000c618b0
    Site('bu_618d4',                     'code', '08dffe88 36000008/fff8001f 90000008/9f00001f b9400108/ffc003ff b90037e8 08dffe88 36000008/fff8001f 90000008/9f00001f', 0),  # -> 0x7000c618d4
    Site('bu_618e0',                     'code', 'b94dc108 b90037e8 08dffe88 36000008/fff8001f 90000008/9f00001f 52800029 3900f3ff b9400108/ffc003ff', 0),  # -> 0x7000c618e0
    Site('bu_618e8',                     'code', '08dffe88 36000008/fff8001f 90000008/9f00001f 52800029 3900f3ff b9400108/ffc003ff b90023e9 90000015/9f00001f', 0),  # -> 0x7000c618e8
    Site('bu_618fc',                     'code', 'b94dc508 b90023e9 90000015/9f00001f b9003be8 52a02008 f804c3e8 d2a00068 f2e00208', 0),  # -> 0x7000c618fc
    Site('bu_6192c',                     'code', 'f9421ab5 f2e00088 3900fbff f9002fe8 f94002a0 b4000000/ff00001f aa1303f4 b4000013/ff00001f', 0),  # -> 0x7000c6192c
    Site('bu_6193c',                     'code', 'f94002a0 b4000000/ff00001f aa1303f4 b4000013/ff00001f f9400288 90000009/9f00001f f9401908 f9400129/ffc003ff', 0),  # -> 0x7000c6193c
    Site('bu_6194c',                     'code', 'f9400288 90000009/9f00001f f9401908 f9400129/ffc003ff eb09011f 54000001/ff00001f f94002ae 7941b288', 0),  # -> 0x7000c6194c
    Site('bu_61954',                     'code', 'f9401908 f9447d29 eb09011f 54000001/ff00001f f94002ae 7941b288 37000008/fff8001f aa1f03f6', 0),  # -> 0x7000c61954
    Site('bu_61958',                     'code', 'f9447d29 eb09011f 54000001/ff00001f f94002ae 7941b288 37000008/fff8001f aa1f03f6 b9409288', 0),  # -> 0x7000c61958
    Site('bu_61964',                     'code', 'f94002ae 7941b288 37000008/fff8001f aa1f03f6 b9409288 531d7115 37f80008/fff8001f 710022bf', 0),  # -> 0x7000c61964
    Site('bu_61968',                     'code', '7941b288 37000008/fff8001f aa1f03f6 b9409288 531d7115 37f80008/fff8001f 710022bf 54000008/ff00001f', 0),  # -> 0x7000c61968
    Site('bu_61974',                     'code', 'b9409288 531d7115 37f80008/fff8001f 710022bf 54000008/ff00001f f9407688 9103828c eb0c011f', 0),  # -> 0x7000c61974
    Site('bu_61988',                     'code', 'f9407688 9103828c eb0c011f 54000000/ff00001f b980f689 cb0903ea 3943728d cb09018b', 0),  # -> 0x7000c61988
    Site('bu_61998',                     'code', 'b980f689 cb0903ea 3943728d cb09018b cb090108 3500000d/ff00001f f9400d1c f10a3f9f', 0),  # -> 0x7000c61998
    Site('bu_619a0',                     'code', '3943728d cb09018b cb090108 3500000d/ff00001f f9400d1c f10a3f9f 54000009/ff00001f 5280520a', 0),  # -> 0x7000c619a0
    Site('bu_619b0',                     'code', 'f9400d1c f10a3f9f 54000009/ff00001f 5280520a 79402509 f9000d0a b980f68f 8b0801ea', 0),  # -> 0x7000c619b0
    Site('bu_619c0',                     'code', '79402509 f9000d0a b980f68f 8b0801ea a9402d4e cb0f016f eb0c017f 9a8f03f5', 0),  # -> 0x7000c619c0
    Site('bu_619c4',                     'code', 'f9000d0a b980f68f 8b0801ea a9402d4e cb0f016f eb0c017f 9a8f03f5 b400000e/ff00001f', 0),  # -> 0x7000c619c4
    Site('bu_619c8',                     'code', 'b980f68f 8b0801ea a9402d4e cb0f016f eb0c017f 9a8f03f5 b400000e/ff00001f f90005cb', 0),  # -> 0x7000c619c8
    Site('bu_619d0',                     'code', 'a9402d4e cb0f016f eb0c017f 9a8f03f5 b400000e/ff00001f f90005cb f940054b b400000b/ff00001f', 0),  # -> 0x7000c619d0
    Site('bu_619e4',                     'code', 'f90005cb f940054b b400000b/ff00001f f940014e f900016e a9007d5f 9103e280 b940f28a', 0),  # -> 0x7000c619e4
    Site('bu_619e8',                     'code', 'f940054b b400000b/ff00001f f940014e f900016e a9007d5f 9103e280 b940f28a b940928b', 0),  # -> 0x7000c619e8
    Site('bu_619f0',                     'code', 'f940014e f900016e a9007d5f 9103e280 b940f28a b940928b 5100054a 7100057f', 0),  # -> 0x7000c619f0
    Site('bu_619f4',                     'code', 'f900016e a9007d5f 9103e280 b940f28a b940928b 5100054a 7100057f b900f28a', 0),  # -> 0x7000c619f4
    Site('bu_619f8',                     'code', 'a9007d5f 9103e280 b940f28a b940928b 5100054a 7100057f b900f28a b9810e8a', 0),  # -> 0x7000c619f8
    Site('bu_61a00',                     'code', 'b940f28a b940928b 5100054a 7100057f b900f28a b9810e8a 8b080141 54000001/ff00001f', 0),  # -> 0x7000c61a00
    Site('bu_61a04',                     'code', 'b940928b 5100054a 7100057f b900f28a b9810e8a 8b080141 54000001/ff00001f f940000a', 0),  # -> 0x7000c61a04
    Site('bu_61a10',                     'code', 'b900f28a b9810e8a 8b080141 54000001/ff00001f f940000a f9000001 a900002a b400000a/ff00001f', 0),  # -> 0x7000c61a10
    Site('bu_61a14',                     'code', 'b9810e8a 8b080141 54000001/ff00001f f940000a f9000001 a900002a b400000a/ff00001f f9000541', 0),  # -> 0x7000c61a14
    Site('bu_61a20',                     'code', 'f940000a f9000001 a900002a b400000a/ff00001f f9000541 b9410a8a 1100054a b9010a8a', 0),  # -> 0x7000c61a20
    Site('bu_61a24',                     'code', 'f9000001 a900002a b400000a/ff00001f f9000541 b9410a8a 1100054a b9010a8a d10ac78a', 0),  # -> 0x7000c61a24
    Site('bu_61a28',                     'code', 'a900002a b400000a/ff00001f f9000541 b9410a8a 1100054a b9010a8a d10ac78a b100895f', 0),  # -> 0x7000c61a28
    Site('bu_61a30',                     'code', 'f9000541 b9410a8a 1100054a b9010a8a d10ac78a b100895f 54000008/ff00001f 8b090109', 0),  # -> 0x7000c61a30
    Site('bu_61a34',                     'code', 'b9410a8a 1100054a b9010a8a d10ac78a b100895f 54000008/ff00001f 8b090109 d10ac38a', 0),  # -> 0x7000c61a34
    Site('bu_61a3c',                     'code', 'b9010a8a d10ac78a b100895f 54000008/ff00001f 8b090109 d10ac38a f901652a 529fffea', 0),  # -> 0x7000c61a3c
    Site('bu_61a54',                     'code', 'f901652a 529fffea b902c13f 910ac12b f9015d3f f901593f 7905812a b980f68a', 0),  # -> 0x7000c61a54
    Site('bu_61a5c',                     'code', 'b902c13f 910ac12b f9015d3f f901593f 7905812a b980f68a 8b0a0169 b5000015/ff00001f', 0),  # -> 0x7000c61a5c
    Site('bu_61a64',                     'code', 'f9015d3f f901593f 7905812a b980f68a 8b0a0169 b5000015/ff00001f f940018a f9000189', 0),  # -> 0x7000c61a64
    Site('bu_61a68',                     'code', 'f901593f 7905812a b980f68a 8b0a0169 b5000015/ff00001f f940018a f9000189 a900312a', 0),  # -> 0x7000c61a68
    Site('bu_61a6c',                     'code', '7905812a b980f68a 8b0a0169 b5000015/ff00001f f940018a f9000189 a900312a b400000a/ff00001f', 0),  # -> 0x7000c61a6c
    Site('bu_61a70',                     'code', 'b980f68a 8b0a0169 b5000015/ff00001f f940018a f9000189 a900312a b400000a/ff00001f f9000549', 0),  # -> 0x7000c61a70
    Site('bu_61a7c',                     'code', 'f940018a f9000189 a900312a b400000a/ff00001f f9000549 b940f289 11000529 b900f289', 0),  # -> 0x7000c61a7c
    Site('bu_61a80',                     'code', 'f9000189 a900312a b400000a/ff00001f f9000549 b940f289 11000529 b900f289 7941b689', 0),  # -> 0x7000c61a80
    Site('bu_61a84',                     'code', 'a900312a b400000a/ff00001f f9000549 b940f289 11000529 b900f289 7941b689 79002109', 0),  # -> 0x7000c61a84
    Site('bu_61a8c',                     'code', 'f9000549 b940f289 11000529 b900f289 7941b689 79002109 79402509 8b090108', 0),  # -> 0x7000c61a8c
    Site('bu_61a90',                     'code', 'b940f289 11000529 b900f289 7941b689 79002109 79402509 8b090108 91008114', 0),  # -> 0x7000c61a90
    Site('bu_61a98',                     'code', 'b900f289 7941b689 79002109 79402509 8b090108 91008114 b5000016/ff00001f 910083e1', 0),  # -> 0x7000c61a98
    Site('bu_61a9c',                     'code', '7941b689 79002109 79402509 8b090108 91008114 b5000016/ff00001f 910083e1 aa1403e0', 0),  # -> 0x7000c61a9c
    Site('bu_61aa0',                     'code', '79002109 79402509 8b090108 91008114 b5000016/ff00001f 910083e1 aa1403e0 94000000/fc000000', 0),  # -> 0x7000c61aa0
    Site('bu_61aa4',                     'code', '79402509 8b090108 91008114 b5000016/ff00001f 910083e1 aa1403e0 94000000/fc000000 90000008/9f00001f', 0),  # -> 0x7000c61aa4
    Site('bu_61abc',                     'code', '94000000/fc000000 90000008/9f00001f 9108a280 f9400108/ffc003ff f901129f 91004109 91060108 f9000289', 0),  # -> 0x7000c61abc
    Site('bu_61ac8',                     'code', 'f944c108 f901129f 91004109 91060108 f9000289 f9010e88 94000000/fc000000 b21f03e8', 0),  # -> 0x7000c61ac8
    Site('bu_61acc',                     'code', 'f901129f 91004109 91060108 f9000289 f9010e88 94000000/fc000000 b21f03e8 f9013e9f', 0),  # -> 0x7000c61acc
    Site('bu_61ad8',                     'code', 'f9000289 f9010e88 94000000/fc000000 b21f03e8 f9013e9f f9013a88 94000000/fc000000 b9028280', 0),  # -> 0x7000c61ad8
    Site('bu_61adc',                     'code', 'f9010e88 94000000/fc000000 b21f03e8 f9013e9f f9013a88 94000000/fc000000 b9028280 94000000/fc000000', 0),  # -> 0x7000c61adc
    Site('bu_61ae0',                     'code', '94000000/fc000000 b21f03e8 f9013e9f f9013a88 94000000/fc000000 b9028280 94000000/fc000000 b9028680', 0),  # -> 0x7000c61ae0
    Site('bu_61ae8',                     'code', 'f9013e9f f9013a88 94000000/fc000000 b9028280 94000000/fc000000 b9028680 90000008/9f00001f 91000108/ffc003ff', 0),  # -> 0x7000c61ae8
    Site('bu_61aec',                     'code', 'f9013a88 94000000/fc000000 b9028280 94000000/fc000000 b9028680 90000008/9f00001f 91000108/ffc003ff 91004349', 0),  # -> 0x7000c61aec
    Site('bu_61af4',                     'code', 'b9028280 94000000/fc000000 b9028680 90000008/9f00001f 91000108/ffc003ff 91004349 d100c3a1 390a229f', 0),  # -> 0x7000c61af4
    Site('bu_61afc',                     'code', 'b9028680 90000008/9f00001f 91000108/ffc003ff 91004349 d100c3a1 390a229f 52a06000 aa1303e2', 0),  # -> 0x7000c61afc
    Site('bu_61b10',                     'code', '390a229f 52a06000 aa1303e2 52800103 52800024 a93d23a9 2a1f03e5 94000000/fc000000', 0),  # -> 0x7000c61b10
    Site('bu_61b2c',                     'code', '94000000/fc000000 aa0003f5 94000000/fc000000 aa1f03f6 b4000000/ff00001f 94000000/fc000000 aa0003f6 90000008/9f00001f', 0),  # -> 0x7000c61b2c
    Site('bu_61b50',                     'code', '08dffd08 9000001b/9f00001f 9100037b/ffc003ff 36000008/fff8001f 2d400760 d100c3a2 aa1403e0 aa1503e1', 0),  # -> 0x7000c61b50
    Site('bu_61b60',                     'code', '2d400760 d100c3a2 aa1403e0 aa1503e1 5e21d821 5e21d800 2d3a07a0 94000000/fc000000', 0),  # -> 0x7000c61b60
    Site('bu_61b7c',                     'code', '94000000/fc000000 b5000016/ff00001f 52800048 aa1503e0 39085288 f94002a8 f9401508 d63f0100', 0),  # -> 0x7000c61b7c
    Site('bu_61b8c',                     'code', '39085288 f94002a8 f9401508 d63f0100 b94012e8 34000008/ff00001f f94002e9 7100011f', 0),  # -> 0x7000c61b8c
    Site('bu_61b90',                     'code', 'f94002a8 f9401508 d63f0100 b94012e8 34000008/ff00001f f94002e9 7100011f 9a9fc136', 0),  # -> 0x7000c61b90
    Site('bu_61b94',                     'code', 'f9401508 d63f0100 b94012e8 34000008/ff00001f f94002e9 7100011f 9a9fc136 b4000016/ff00001f', 0),  # -> 0x7000c61b94
    Site('bu_61b98',                     'code', 'd63f0100 b94012e8 34000008/ff00001f f94002e9 7100011f 9a9fc136 b4000016/ff00001f d10042da', 0),  # -> 0x7000c61b98
    Site('bu_61b9c',                     'code', 'b94012e8 34000008/ff00001f f94002e9 7100011f 9a9fc136 b4000016/ff00001f d10042da b400001a/ff00001f', 0),  # -> 0x7000c61b9c
    Site('bu_61ba4',                     'code', 'f94002e9 7100011f 9a9fc136 b4000016/ff00001f d10042da b400001a/ff00001f f9400749 eb19013f', 0),  # -> 0x7000c61ba4
    Site('bu_61bbc',                     'code', 'f9400749 eb19013f 54000000/ff00001f 3940012a 7101b55f 54000001/ff00001f 3940052a 7101855f', 0),  # -> 0x7000c61bbc
    Site('bu_61bc8',                     'code', '3940012a 7101b55f 54000001/ff00001f 3940052a 7101855f 54000001/ff00001f 3940092a 7101a55f', 0),  # -> 0x7000c61bc8
    Site('bu_61bd4',                     'code', '3940052a 7101855f 54000001/ff00001f 3940092a 7101a55f 54000001/ff00001f 39400d2a 7101b95f', 0),  # -> 0x7000c61bd4
    Site('bu_61be0',                     'code', '3940092a 7101a55f 54000001/ff00001f 39400d2a 7101b95f 54000001/ff00001f 39401129 35000009/ff00001f', 0),  # -> 0x7000c61be0
    Site('bu_61bec',                     'code', '39400d2a 7101b95f 54000001/ff00001f 39401129 35000009/ff00001f 7100051f 54000001/ff00001f 94000000/fc000000', 0),  # -> 0x7000c61bec
    Site('bu_61bf8',                     'code', '39401129 35000009/ff00001f 7100051f 54000001/ff00001f 94000000/fc000000 f9400008 aa0003f5 f9400d08', 0),  # -> 0x7000c61bf8
    Site('bu_61c0c',                     'code', 'f9400008 aa0003f5 f9400d08 d63f0100 f94002a8 aa1503e0 f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1803e9', 0),  # -> 0x7000c61c0c
    Site('bu_61c14',                     'code', 'f9400d08 d63f0100 f94002a8 aa1503e0 f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1803e9', 0),  # -> 0x7000c61c14
    Site('bu_61c18',                     'code', 'd63f0100 f94002a8 aa1503e0 f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1803e9', 0),  # -> 0x7000c61c18
    Site('bu_61c1c',                     'code', 'f94002a8 aa1503e0 f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1803e9', 0),  # -> 0x7000c61c1c
    Site('bu_61c24',                     'code', 'f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1803e9', 0),  # -> 0x7000c61c24
    Site('bu_61c28',                     'code', 'd63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1803e9 9000000a/9f00001f', 0),  # -> 0x7000c61c28
    Site('bu_61c2c',                     'code', 'f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1803e9 9000000a/9f00001f 9100014a/ffc003ff', 0),  # -> 0x7000c61c2c
    Site('bu_61c6c',                     'code', 'f9400008 aa0003f5 f9400d08 d63f0100 f94002a8 aa1503e0 f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1f03ea 5280002b 386a690c 386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f', 0),  # -> 0x7000c61c6c
    Site('bu_61c74',                     'code', 'f9400d08 d63f0100 f94002a8 aa1503e0 f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1f03ea 5280002b 386a690c 386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f', 0),  # -> 0x7000c61c74
    Site('bu_61c78',                     'code', 'd63f0100 f94002a8 aa1503e0 f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1f03ea 5280002b 386a690c 386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f', 0),  # -> 0x7000c61c78
    Site('bu_61c7c',                     'code', 'f94002a8 aa1503e0 f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1f03ea 5280002b 386a690c 386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f', 0),  # -> 0x7000c61c7c
    Site('bu_61c84',                     'code', 'f9400d08 d63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1f03ea 5280002b 386a690c 386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f', 0),  # -> 0x7000c61c84
    Site('bu_61c88',                     'code', 'd63f0100 f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1f03ea 5280002b 386a690c 386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f', 0),  # -> 0x7000c61c88
    Site('bu_61c8c',                     'code', 'f94006a8 90000009/9f00001f 91000129/ffc003ff eb09011f 54000000/ff00001f aa1f03ea 5280002b 386a690c 386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f', 0),  # -> 0x7000c61c8c
    Site('bu_61ca8',                     'code', '386a690c 386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f 54000001/ff00001f 14000000/fc000000 f10a439f', 0),  # -> 0x7000c61ca8
    Site('bu_61cac',                     'code', '386a692d 6b0d019f 54000001/ff00001f 3400000c/ff00001f f142015f 9100054a 1a9f27eb eb0a031f 54000001/ff00001f 14000000/fc000000 f10a439f', 0),  # -> 0x7000c61cac
    Site('bu_61cdc',                     'code', 'f9000d1c 14000000/fc000000 52805200 94000000/fc000000 aa0003f4 14000000/fc000000 3600000b/fff8001f f94002c8', 0),  # -> 0x7000c61cdc
    Site('bu_61ce8',                     'code', '94000000/fc000000 aa0003f4 14000000/fc000000 3600000b/fff8001f f94002c8 b4000008/ff00001f f94006c9 f9000509', 0),  # -> 0x7000c61ce8
    Site('bu_61cf8',                     'code', 'f94002c8 b4000008/ff00001f f94006c9 f9000509 f94006c8 b4000008/ff00001f f94002c9 f9000109', 0),  # -> 0x7000c61cf8
    Site('bu_61d00',                     'code', 'f94006c9 f9000509 f94006c8 b4000008/ff00001f f94002c9 f9000109 a9007edf b94012e8', 0),  # -> 0x7000c61d00
    Site('bu_61d04',                     'code', 'f9000509 f94006c8 b4000008/ff00001f f94002c9 f9000109 a9007edf b94012e8 51000508', 0),  # -> 0x7000c61d04
    Site('bu_61d08',                     'code', 'f94006c8 b4000008/ff00001f f94002c9 f9000109 a9007edf b94012e8 51000508 b90012e8', 0),  # -> 0x7000c61d08
    Site('bu_61d10',                     'code', 'f94002c9 f9000109 a9007edf b94012e8 51000508 b90012e8 f9400ee8 f81f02c8', 0),  # -> 0x7000c61d10
    Site('bu_61d14',                     'code', 'f9000109 a9007edf b94012e8 51000508 b90012e8 f9400ee8 f81f02c8 f9000efa', 0),  # -> 0x7000c61d14
    Site('bu_61d18',                     'code', 'a9007edf b94012e8 51000508 b90012e8 f9400ee8 f81f02c8 f9000efa b94012e8', 0),  # -> 0x7000c61d18
    Site('bu_61d1c',                     'code', 'b94012e8 51000508 b90012e8 f9400ee8 f81f02c8 f9000efa b94012e8 b9402ae9', 0),  # -> 0x7000c61d1c
    Site('bu_61d24',                     'code', 'b90012e8 f9400ee8 f81f02c8 f9000efa b94012e8 b9402ae9 6b09011f 5400000a/ff00001f', 0),  # -> 0x7000c61d24
    Site('bu_61d28',                     'code', 'f9400ee8 f81f02c8 f9000efa b94012e8 b9402ae9 6b09011f 5400000a/ff00001f f9400ef5', 0),  # -> 0x7000c61d28
    Site('bu_61d30',                     'code', 'f9000efa b94012e8 b9402ae9 6b09011f 5400000a/ff00001f f9400ef5 b4000015/ff00001f f94002a8', 0),  # -> 0x7000c61d30
    Site('bu_61d34',                     'code', 'b94012e8 b9402ae9 6b09011f 5400000a/ff00001f f9400ef5 b4000015/ff00001f f94002a8 f9000ee8', 0),  # -> 0x7000c61d34
    Site('bu_61d38',                     'code', 'b9402ae9 6b09011f 5400000a/ff00001f f9400ef5 b4000015/ff00001f f94002a8 f9000ee8 a9007ebf', 0),  # -> 0x7000c61d38
    Site('bu_61d44',                     'code', 'f9400ef5 b4000015/ff00001f f94002a8 f9000ee8 a9007ebf 94000000/fc000000 f90002a0 aa1503e8', 0),  # -> 0x7000c61d44
    Site('bu_61d4c',                     'code', 'f94002a8 f9000ee8 a9007ebf 94000000/fc000000 f90002a0 aa1503e8 f94002e9 f8010d1f', 0),  # -> 0x7000c61d4c
    Site('bu_61d50',                     'code', 'f9000ee8 a9007ebf 94000000/fc000000 f90002a0 aa1503e8 f94002e9 f8010d1f f90002e8', 0),  # -> 0x7000c61d50
    Site('bu_61d54',                     'code', 'a9007ebf 94000000/fc000000 f90002a0 aa1503e8 f94002e9 f8010d1f f90002e8 f9000eb7', 0),  # -> 0x7000c61d54
    Site('bu_61d5c',                     'code', 'f90002a0 aa1503e8 f94002e9 f8010d1f f90002e8 f9000eb7 f9000109 b4000009/ff00001f', 0),  # -> 0x7000c61d5c
    Site('bu_61d64',                     'code', 'f94002e9 f8010d1f f90002e8 f9000eb7 f9000109 b4000009/ff00001f f9000528 b94012e8', 0),  # -> 0x7000c61d64
    Site('bu_61d68',                     'code', 'f8010d1f f90002e8 f9000eb7 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508', 0),  # -> 0x7000c61d68
    Site('bu_61d6c',                     'code', 'f90002e8 f9000eb7 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8', 0),  # -> 0x7000c61d6c
    Site('bu_61d70',                     'code', 'f9000eb7 f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8 94000000/fc000000', 0),  # -> 0x7000c61d70
    Site('bu_61d74',                     'code', 'f9000109 b4000009/ff00001f f9000528 b94012e8 11000508 b90012e8 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff d2c00289', 0),  # -> 0x7000c61d74
    Site('bu_61d7c',                     'code', 'f9000528 b94012e8 11000508 b90012e8 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff d2c00289', 0),  # -> 0x7000c61d7c
    Site('bu_61d80',                     'code', 'b94012e8 11000508 b90012e8 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff d2c00289 a90022a0', 0),  # -> 0x7000c61d80
    Site('bu_61d88',                     'code', 'b90012e8 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff d2c00289 a90022a0 b24083e8 a90cffe8', 0),  # -> 0x7000c61d88
    Site('bu_61d9c',                     'code', 'a90022a0 b24083e8 a90cffe8 52800048 910083e2 d100c3a3 aa1403e0 b90093ff', 0),  # -> 0x7000c61d9c
    Site('bu_61df4',                     'code', 'f9433d08 f81d03a9 a902ffe8 f9400288 f9401508 d63f0100 90000008/9f00001f f9400108/ffc003ff', 0),  # -> 0x7000c61df4
    Site('bu_61e00',                     'code', 'f9400288 f9401508 d63f0100 90000008/9f00001f f9400108/ffc003ff f9400100 b5000000/ff00001f a9564ff4', 0),  # -> 0x7000c61e00
    Site('bu_61e04',                     'code', 'f9401508 d63f0100 90000008/9f00001f f9400108/ffc003ff f9400100 b5000000/ff00001f a9564ff4 a95557f6', 0),  # -> 0x7000c61e04
    Site('bu_61e08',                     'code', 'd63f0100 90000008/9f00001f f9400108/ffc003ff f9400100 b5000000/ff00001f a9564ff4 a95557f6 a9545ff8', 0),  # -> 0x7000c61e08
    Site('bu_61e10',                     'code', 'f9447108 f9400100 b5000000/ff00001f a9564ff4 a95557f6 a9545ff8 a95367fa a9526ffc', 0),  # -> 0x7000c61e10
    Site('bu_61e14',                     'code', 'f9400100 b5000000/ff00001f a9564ff4 a95557f6 a9545ff8 a95367fa a9526ffc a9517bfd', 0),  # -> 0x7000c61e14
    Site('bu_61e3c',                     'code', 'f9400755 94000000/fc000000 f9400348 d28a7ee9 f2b4bc69 f2d89369 f2e00409 d294fdaa', 0),  # -> 0x7000c61e3c
    Site('bu_61e44',                     'code', 'f9400348 d28a7ee9 f2b4bc69 f2d89369 f2e00409 d294fdaa f2a978ca f2d126ea', 0),  # -> 0x7000c61e44
    Site('bu_61e80',                     'code', 'f941054a 9b097d08 f9400149 9ac90d08 14000000/fc000000 90000009/9f00001f f9400129/ffc003ff f9400129', 0),  # -> 0x7000c61e80
    Site('bu_61e88',                     'code', 'f9400149 9ac90d08 14000000/fc000000 90000009/9f00001f f9400129/ffc003ff f9400129 9ac90d08 52807d09', 0),  # -> 0x7000c61e88
    Site('bu_61e98',                     'code', 'f9410529 f9400129 9ac90d08 52807d09 9b097d08 9e220100 52a88f48 1e270101', 0),  # -> 0x7000c61e98
    Site('bu_61e9c',                     'code', 'f9400129 9ac90d08 52807d09 9b097d08 9e220100 52a88f48 1e270101 90000001/9f00001f 91000021/ffc003ff 910083e0', 0),  # -> 0x7000c61e9c
    Site('bu_61ed0',                     'code', '94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280f009 90000008/9f00001f 91000108/ffc003ff f2c08709 f9000109 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280f009', 0),  # -> 0x7000c61ed0
    Site('bu_61ee0',                     'code', '94000000/fc000000 34000000/ff00001f d280f009 90000008/9f00001f 91000108/ffc003ff f2c08709 f9000109 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280f009', 0),  # -> 0x7000c61ee0
    Site('bu_61ef8',                     'code', 'f9000109 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280f009', 0),  # -> 0x7000c61ef8
    Site('bu_61f04',                     'code', '94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280f009 90000008/9f00001f 91000108/ffc003ff f2c08709 f9000109 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280a008', 0),  # -> 0x7000c61f04
    Site('bu_61f14',                     'code', '94000000/fc000000 34000000/ff00001f d280f009 90000008/9f00001f 91000108/ffc003ff f2c08709 f9000109 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280a008', 0),  # -> 0x7000c61f14
    Site('bu_61f2c',                     'code', 'f9000109 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280a008', 0),  # -> 0x7000c61f2c
    Site('bu_61f38',                     'code', '94000000/fc000000 14000000/fc000000 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 34000000/ff00001f d280a008 90000000/9f00001f', 0),  # -> 0x7000c61f38
    Site('bu_61f48',                     'code', '94000000/fc000000 34000000/ff00001f d280a008 90000000/9f00001f 91000000/ffc003ff f2c05a08 f9000368 94000000/fc000000', 0),  # -> 0x7000c61f48
    Site('bu_61f60',                     'code', 'f9000368 94000000/fc000000 14000000/fc000000 3400000f/ff00001f 910005ce eb0e031f 54000001/ff00001f 14000000/fc000000', 0),  # -> 0x7000c61f60
    Site('bu_61f64',                     'code', '94000000/fc000000 14000000/fc000000 3400000f/ff00001f 910005ce eb0e031f 54000001/ff00001f 14000000/fc000000 5280002d', 0),  # -> 0x7000c61f64
    Site('bu_61f84',                     'code', '390006cd f86c780d 14000000/fc000000 3400000f/ff00001f 910005ce eb0e031f 54000001/ff00001f 14000000/fc000000', 0),  # -> 0x7000c61f84
    Site('bu_61f88',                     'code', 'f86c780d 14000000/fc000000 3400000f/ff00001f 910005ce eb0e031f 54000001/ff00001f 14000000/fc000000 5280002d', 0),  # -> 0x7000c61f88
    Site('bu_61fa8',                     'code', '390002cd f86c780d 14000000/fc000000 34000010/ff00001f f10005ef 54000001/ff00001f 14000000/fc000000 9100058b', 0),  # -> 0x7000c61fa8
    Site('bu_61fac',                     'code', 'f86c780d 14000000/fc000000 34000010/ff00001f f10005ef 54000001/ff00001f 14000000/fc000000 9100058b f86b780c', 0),  # -> 0x7000c61fac
    Site('bu_61fc8',                     'code', 'f86b780c f90006cc 14000000/fc000000 f94017e8 a9012be0 b98047e9 f8697908 3875c908', 0),  # -> 0x7000c61fc8
    Site('bu_61fcc',                     'code', 'f90006cc 14000000/fc000000 f94017e8 a9012be0 b98047e9 f8697908 3875c908 381cd3bf', 0),  # -> 0x7000c61fcc
    Site('bu_61fe0',                     'code', 'f8697908 3875c908 381cd3bf 7100e91f 390123e8 381cc3a8 b9000fe8 54000001/ff00001f', 0),  # -> 0x7000c61fe0
    Site('bu_61fe4',                     'code', '3875c908 381cd3bf 7100e91f 390123e8 381cc3a8 b9000fe8 54000001/ff00001f 394103e9', 0),  # -> 0x7000c61fe4
    Site('bu_6200c',                     'code', 'f9400101 90000000/9f00001f 91000000/ffc003ff b9400fe3 90000002/9f00001f 91000042/ffc003ff 94000000/fc000000 f94017e8', 0),  # -> 0x7000c6200c
    Site('bu_62024',                     'code', '94000000/fc000000 f94017e8 b98047e9 b9805bea f869790b 91000548 b9005be8 3868696a', 0),  # -> 0x7000c62024
    Site('bu_62034',                     'code', 'f869790b 91000548 b9005be8 3868696a 3400000a/ff00001f a9412be0 2a0803f5 14000000/fc000000', 0),  # -> 0x7000c62034
    Site('bu_62040',                     'code', '3868696a 3400000a/ff00001f a9412be0 2a0803f5 14000000/fc000000 aa1f03f3 14000000/fc000000 aa1f03f4', 0),  # -> 0x7000c62040
    Site('bu_6206c',                     'code', 'd63f0100 14000000/fc000000 aa1603e0 94000000/fc000000 90000008/9f00001f 91004349 f9400108/ffc003ff d100c3a2', 0),  # -> 0x7000c6206c
    Site('bu_62078',                     'code', '94000000/fc000000 90000008/9f00001f 91004349 f9400108/ffc003ff d100c3a2 aa1603e1 f9400100 90000008/9f00001f', 0),  # -> 0x7000c62078
    Site('bu_62084',                     'code', 'f9446508 d100c3a2 aa1603e1 f9400100 90000008/9f00001f 91000108/ffc003ff a93d23a9 94000000/fc000000', 0),  # -> 0x7000c62084
    Site('bu_62090',                     'code', 'f9400100 90000008/9f00001f 91000108/ffc003ff a93d23a9 94000000/fc000000 aa1603e0 94000000/fc000000 90000008/9f00001f', 0),  # -> 0x7000c62090
    Site('bu_620a0',                     'code', '94000000/fc000000 aa1603e0 94000000/fc000000 90000008/9f00001f 90000002/9f00001f 91000042/ffc003ff f9400108/ffc003ff 90000003/9f00001f', 0),  # -> 0x7000c620a0
    Site('bu_620a8',                     'code', '94000000/fc000000 90000008/9f00001f 90000002/9f00001f 91000042/ffc003ff f9400108/ffc003ff 90000003/9f00001f 91000063/ffc003ff 52840004', 0),  # -> 0x7000c620a8
    Site('bu_620b8',                     'code', 'f9446908 90000003/9f00001f 91000063/ffc003ff 52840004 72a00064 f9400100 aa1603e1 94000000/fc000000', 0),  # -> 0x7000c620b8
    Site('bu_620cc',                     'code', 'f9400100 aa1603e1 94000000/fc000000 aa1603e0 94000000/fc000000 9000001a/9f00001f 90000002/9f00001f 91000042/ffc003ff', 0),  # -> 0x7000c620cc
    Site('bu_620d4',                     'code', '94000000/fc000000 aa1603e0 94000000/fc000000 9000001a/9f00001f 90000002/9f00001f 91000042/ffc003ff f940035a/ffc003ff 90000003/9f00001f', 0),  # -> 0x7000c620d4
    Site('bu_620dc',                     'code', '94000000/fc000000 9000001a/9f00001f 90000002/9f00001f 91000042/ffc003ff f940035a/ffc003ff 90000003/9f00001f 91000063/ffc003ff 90000004/9f00001f', 0),  # -> 0x7000c620dc
    Site('bu_620ec',                     'code', 'f9446f5a 90000003/9f00001f 91000063/ffc003ff 90000004/9f00001f 91000084/ffc003ff f9400340 aa1603e1 52a00205', 0),  # -> 0x7000c620ec
    Site('bu_62100',                     'code', 'f9400340 aa1603e1 52a00205 94000000/fc000000 f9400340 94000000/fc000000 14000000/fc000000 aa1f03f5', 0),  # -> 0x7000c62100
    Site('bu_6210c',                     'code', '94000000/fc000000 f9400340 94000000/fc000000 14000000/fc000000 aa1f03f5 14000000/fc000000 94000000/fc000000 14000000/fc000000', 0),  # -> 0x7000c6210c
    Site('bu_62110',                     'code', 'f9400340 94000000/fc000000 14000000/fc000000 aa1f03f5 14000000/fc000000 94000000/fc000000 14000000/fc000000 f94017e8', 0),  # -> 0x7000c62110
    Site('bu_62114',                     'code', '94000000/fc000000 14000000/fc000000 aa1f03f5 14000000/fc000000 94000000/fc000000 14000000/fc000000 f94017e8 f8697908', 0),  # -> 0x7000c62114
    Site('bu_62124',                     'code', '94000000/fc000000 14000000/fc000000 f94017e8 f8697908 3940010b 7100b57f 54000001/ff00001f 3940050b', 0),  # -> 0x7000c62124
    Site('bu_62130',                     'code', 'f8697908 3940010b 7100b57f 54000001/ff00001f 3940050b 3400000b/ff00001f a9012be0 9000000a/9f00001f', 0),  # -> 0x7000c62130
    Site('bu_62134',                     'code', '3940010b 7100b57f 54000001/ff00001f 3940050b 3400000b/ff00001f a9012be0 9000000a/9f00001f 9100014a/ffc003ff', 0),  # -> 0x7000c62134
    Site('bu_62140',                     'code', '3940050b 3400000b/ff00001f a9012be0 9000000a/9f00001f 9100014a/ffc003ff eb0a011f 54000000/ff00001f aa1f03eb', 0),  # -> 0x7000c62140
    Site('bu_62160',                     'code', '386b690c 386b694d 6b0d019f 54000001/ff00001f 3400000c/ff00001f 9100056b eb0b031f 54000001/ff00001f', 0),  # -> 0x7000c62160
    Site('bu_62164',                     'code', '386b694d 6b0d019f 54000001/ff00001f 3400000c/ff00001f 9100056b eb0b031f 54000001/ff00001f 14000000/fc000000', 0),  # -> 0x7000c62164
    Site('bu_621a8',                     'code', 'f9400d08 d63f0100 f9401fe8 aa1f03fb 387b6909 34000009/ff00001f 9100077b eb1b031f', 0),  # -> 0x7000c621a8
    Site('bu_621ac',                     'code', 'd63f0100 f9401fe8 aa1f03fb 387b6909 34000009/ff00001f 9100077b eb1b031f 54000001/ff00001f', 0),  # -> 0x7000c621ac
    Site('bu_621b8',                     'code', '387b6909 34000009/ff00001f 9100077b eb1b031f 54000001/ff00001f 2a1f03fb f85d03a8 d100c3a0', 0),  # -> 0x7000c621b8
    Site('bu_621d8',                     'code', 'f9400d08 d63f0100 f85d83a9 aa1f03e8 3868692a 3400000a/ff00001f 91000508 eb08031f 54000001/ff00001f 2a1f03e8 6b080369', 0),  # -> 0x7000c621d8
    Site('bu_621dc',                     'code', 'd63f0100 f85d83a9 aa1f03e8 3868692a 3400000a/ff00001f 91000508 eb08031f 54000001/ff00001f 2a1f03e8 6b080369', 0),  # -> 0x7000c621dc
    Site('bu_621e8',                     'code', '3868692a 3400000a/ff00001f 91000508 eb08031f 54000001/ff00001f 2a1f03e8 6b080369 b9000be9', 0),  # -> 0x7000c621e8
    Site('bu_62228',                     'code', 'f9400d08 d63f0100 3400001b/ff00001f f85d83a9 8b1c02a8 eb09011f 54000000/ff00001f aa1f03ea', 0),  # -> 0x7000c62228
    Site('bu_6222c',                     'code', 'd63f0100 3400001b/ff00001f f85d83a9 8b1c02a8 eb09011f 54000000/ff00001f aa1f03ea 386a690b', 0),  # -> 0x7000c6222c
    Site('bu_62248',                     'code', '386a690b 386a692c 6b0c017f 54000001/ff00001f 3400000b/ff00001f 9100054a eb1b015f 54000003/ff00001f 14000000/fc000000 b9400be8', 0),  # -> 0x7000c62248
    Site('bu_6224c',                     'code', '386a692c 6b0c017f 54000001/ff00001f 3400000b/ff00001f 9100054a eb1b015f 54000003/ff00001f 14000000/fc000000 b9400be8', 0),  # -> 0x7000c6224c
    Site('bu_62284',                     'code', '94000000/fc000000 aa0003f4 b5000000/ff00001f 14000000/fc000000 52805201 aa1403e0 52800102 d63f0100', 0),  # -> 0x7000c62284
    Site('bu_622a0',                     'code', 'd63f0100 14000000/fc000000 9102e280 91026296 aa0e03f5 94000000/fc000000 aa1503ee 14000000/fc000000', 0),  # -> 0x7000c622a0
    Site('bu_622b4',                     'code', '94000000/fc000000 aa1503ee 14000000/fc000000 4b1503f5 52805201 f9000fee aa1403e0 3100051f', 0),  # -> 0x7000c622b4
    Site('bu_622d8',                     'code', '94000000/fc000000 14000000/fc000000 910082c0 94000000/fc000000 14000000/fc000000 52805201 aa1403e0 f9000fee', 0),  # -> 0x7000c622d8
    Site('bu_622e4',                     'code', '94000000/fc000000 14000000/fc000000 52805201 aa1403e0 f9000fee 2a1503e2 94000000/fc000000 b4000000/ff00001f', 0),  # -> 0x7000c622e4
    Site('bu_622fc',                     'code', '94000000/fc000000 b4000000/ff00001f aa0003e8 14000000/fc000000 8b090108 f9400508 8b0a0108 eb0b011f', 0),  # -> 0x7000c622fc
    Site('bu_62310',                     'code', 'f9400508 8b0a0108 eb0b011f 54000001/ff00001f f9000fee f9400fe8 b4000008/ff00001f f9400fe8', 0),  # -> 0x7000c62310
    Site('bu_62330',                     'code', 'f9400900 b4000000/ff00001f 52805208 52800109 b81f03b5 a93d23b4 d100c3a1 b81e03a9', 0),  # -> 0x7000c62330
    Site('bu_62354',                     'code', 'f9400008 f9400108 d63f0100 aa1f03f4 14000000/fc000000 710005bf f9000fee 54000001/ff00001f', 0),  # -> 0x7000c62354
    Site('bu_62358',                     'code', 'f9400108 d63f0100 aa1f03f4 14000000/fc000000 710005bf f9000fee 54000001/ff00001f aa1f03ed', 0),  # -> 0x7000c62358
    Site('bu_6235c',                     'code', 'd63f0100 aa1f03f4 14000000/fc000000 710005bf f9000fee 54000001/ff00001f aa1f03ed f9400d0e', 0),  # -> 0x7000c6235c
    Site('bu_62378',                     'code', 'f9400d0e f10a41df 54000003/ff00001f b400000d/ff00001f f9400daf eb0e01ff 54000009/ff00001f aa0803ed', 0),  # -> 0x7000c62378
    Site('bu_62388',                     'code', 'f9400daf eb0e01ff 54000009/ff00001f aa0803ed 8b090108 f9400508 8b0a0108 eb0b011f', 0),  # -> 0x7000c62388
    Site('bu_6239c',                     'code', 'f9400508 8b0a0108 eb0b011f 54000001/ff00001f 14000000/fc000000 a90123e9 aa0c03fb 94000000/fc000000', 0),  # -> 0x7000c6239c
    Site('bu_623b8',                     'code', '94000000/fc000000 a94123e9 aa1b03ec 14000000/fc000000 8b15014b f940016a f9000169 a9002d2a', 0),  # -> 0x7000c623b8
    Site('bu_623cc',                     'code', 'f940016a f9000169 a9002d2a b500000a/ff00001f 14000000/fc000000 11000528 b90047e8 52800028', 0),  # -> 0x7000c623cc
    Site('bu_623d0',                     'code', 'f9000169 a9002d2a b500000a/ff00001f 14000000/fc000000 11000528 b90047e8 52800028 b9005be8', 0),  # -> 0x7000c623d0
    Site('bu_623d4',                     'code', 'a9002d2a b500000a/ff00001f 14000000/fc000000 11000528 b90047e8 52800028 b9005be8 14000000/fc000000', 0),  # -> 0x7000c623d4
    Site('bu_62404',                     'code', 'f9400d08 d63f0100 f9401fe9 aa1f03e8 3868692a 3400000a/ff00001f 91000508 eb08031f', 0),  # -> 0x7000c62404
    Site('bu_62408',                     'code', 'd63f0100 f9401fe9 aa1f03e8 3868692a 3400000a/ff00001f 91000508 eb08031f 54000001/ff00001f', 0),  # -> 0x7000c62408
    Site('bu_62414',                     'code', '3868692a 3400000a/ff00001f 91000508 eb08031f 54000001/ff00001f 2a1f03e8 9000000a/9f00001f 8b3b4129', 0),  # -> 0x7000c62414
    Site('bu_62438',                     'code', 'f9410d4a b9805bec 9a893148 f94017ea b98047e9 3940010d 91000588 f869794b', 0),  # -> 0x7000c62438
    Site('bu_6244c',                     'code', '3940010d 91000588 f869794b 7100e9bf 54000001/ff00001f 3868696c 1100052b b90047eb', 0),  # -> 0x7000c6244c
    Site('bu_62454',                     'code', 'f869794b 7100e9bf 54000001/ff00001f 3868696c 1100052b b90047eb 3400000c/ff00001f f8697949', 0),  # -> 0x7000c62454
    Site('bu_62460',                     'code', '3868696c 1100052b b90047eb 3400000c/ff00001f f8697949 8b080129 5280002a f9002be9', 0),  # -> 0x7000c62460
    Site('bu_62470',                     'code', 'f8697949 8b080129 5280002a f9002be9 52800028 b9005bea 14000000/fc000000 2a1503e2', 0),  # -> 0x7000c62470
    Site('bu_62490',                     'code', '94000000/fc000000 14000000/fc000000 710009bf 54000001/ff00001f aa1f03ed f9400d0e f10a41df 54000003/ff00001f', 0),  # -> 0x7000c62490
    Site('bu_624a4',                     'code', 'f9400d0e f10a41df 54000003/ff00001f b400000d/ff00001f f9400daf eb0e01ff 54000002/ff00001f aa0803ed', 0),  # -> 0x7000c624a4
    Site('bu_624b4',                     'code', 'f9400daf eb0e01ff 54000002/ff00001f aa0803ed 8b090108 f9400508 8b0a0108 eb0b011f', 0),  # -> 0x7000c624b4
    Site('bu_624c8',                     'code', 'f9400508 8b0a0108 eb0b011f 54000001/ff00001f 14000000/fc000000 aa1f03ed f10001bf f9400d0e', 0),  # -> 0x7000c624c8
    Site('bu_624e4',                     'code', 'f9400d0e 9a8d010f 8b090108 f9400508 f10a41df 9a8f31ad 8b0a0108 eb0b011f', 0),  # -> 0x7000c624e4
    Site('bu_624f0',                     'code', 'f9400508 f10a41df 9a8f31ad 8b0a0108 eb0b011f 54000001/ff00001f b400000d/ff00001f f9400dbc', 0),  # -> 0x7000c624f0
    Site('bu_6250c',                     'code', 'f9400dbc aa0d03e8 14000000/fc000000 aa0803ea b9005bea 3868696a 3500000a/ff00001f 5280002a', 0),  # -> 0x7000c6250c
    Site('bu_62520',                     'code', '3868696a 3500000a/ff00001f 5280002a 11000529 b9005bea 52800028 b90047e9 aa1f03e9', 0),  # -> 0x7000c62520
    Site('bu_62580',                     'code', 'f86bd949 14000000/fc000000 394103e8 34000008/ff00001f f9400141 90000000/9f00001f 91000000/ffc003ff b9400fe3', 0),  # -> 0x7000c62580
    Site('bu_62590',                     'code', 'f9400141 90000000/9f00001f 91000000/ffc003ff b9400fe3 90000002/9f00001f 91000042/ffc003ff 94000000/fc000000 14000000/fc000000', 0),  # -> 0x7000c62590
    Site('bu_625a8',                     'code', '94000000/fc000000 14000000/fc000000 b9400fea aa0b03e0 aa0803f5 7101c95f f9400fea 54000001/ff00001f', 0),  # -> 0x7000c625a8
    Site('bu_625cc',                     'code', 'f9000149 f9400fea aa0b03e0 aa0803f5 14000000/fc000000', 0),  # -> 0x7000c625cc
    Site('bu_952d0',                     'code', 'f9400008 aa0303f5 aa0203f6 aa0103f3 aa0003f4 f9402d08 d63f0100 90000008/9f00001f', 0),  # -> 0x7000e952d0
    Site('bu_952e4',                     'code', 'f9402d08 d63f0100 90000008/9f00001f 90000009/9f00001f 91000129/ffc003ff f9400108/ffc003ff 910023e1 aa1f03e0', 0),  # -> 0x7000e952e4
    Site('bu_952e8',                     'code', 'd63f0100 90000008/9f00001f 90000009/9f00001f 91000129/ffc003ff f9400108/ffc003ff 910023e1 aa1f03e0 aa1303e2', 0),  # -> 0x7000e952e8
    Site('bu_95320',                     'code', 'f9400288 aa0003f7 aa1403e0 aa1703e1 f9403908 d63f0100 f9002280 aa1703e0', 0),  # -> 0x7000e95320
    Site('bu_95330',                     'code', 'f9403908 d63f0100 f9002280 aa1703e0 f94002e8 f9401508 d63f0100 910023e0', 0),  # -> 0x7000e95330
    Site('bu_95334',                     'code', 'd63f0100 f9002280 aa1703e0 f94002e8 f9401508 d63f0100 910023e0 aa1603e1', 0),  # -> 0x7000e95334
    Site('bu_95338',                     'code', 'f9002280 aa1703e0 f94002e8 f9401508 d63f0100 910023e0 aa1603e1 f9002697', 0),  # -> 0x7000e95338
    Site('bu_95340',                     'code', 'f94002e8 f9401508 d63f0100 910023e0 aa1603e1 f9002697 94000000/fc000000 b94002a8', 0),  # -> 0x7000e95340
    Site('bu_95344',                     'code', 'f9401508 d63f0100 910023e0 aa1603e1 f9002697 94000000/fc000000 b94002a8 a90253f3', 0),  # -> 0x7000e95344
    Site('bu_95348',                     'code', 'd63f0100 910023e0 aa1603e1 f9002697 94000000/fc000000 b94002a8 a90253f3 34000008/ff00001f', 0),  # -> 0x7000e95348
    Site('bu_95354',                     'code', 'f9002697 94000000/fc000000 b94002a8 a90253f3 34000008/ff00001f b9000fe8 b94006a8 3100051f', 0),  # -> 0x7000e95354
    Site('bu_9535c',                     'code', 'b94002a8 a90253f3 34000008/ff00001f b9000fe8 b94006a8 3100051f 54000000/ff00001f b90013e8', 0),  # -> 0x7000e9535c
    Site('bu_9536c',                     'code', 'b94006a8 3100051f 54000000/ff00001f b90013e8 910023e0 94000000/fc000000 f9400288 f9001e80', 0),  # -> 0x7000e9536c
    Site('bu_95384',                     'code', 'f9400288 f9001e80 aa1403e0 f9403508 d63f0100 f9400288 aa1403e0 aa1303e1', 0),  # -> 0x7000e95384
    Site('bu_95388',                     'code', 'f9001e80 aa1403e0 f9403508 d63f0100 f9400288 aa1403e0 aa1303e1 f9403108', 0),  # -> 0x7000e95388
    Site('bu_95390',                     'code', 'f9403508 d63f0100 f9400288 aa1403e0 aa1303e1 f9403108 d63f0100 a9464ff4', 0),  # -> 0x7000e95390
    Site('bu_95394',                     'code', 'd63f0100 f9400288 aa1403e0 aa1303e1 f9403108 d63f0100 a9464ff4 f94023f7', 0),  # -> 0x7000e95394
    Site('bu_95398',                     'code', 'f9400288 aa1403e0 aa1303e1 f9403108 d63f0100 a9464ff4 f94023f7 a94557f6', 0),  # -> 0x7000e95398
    Site('bu_953a4',                     'code', 'f9403108 d63f0100 a9464ff4 f94023f7 a94557f6 a9437bfd 9101c3ff d65f03c0', 0),  # -> 0x7000e953a4
    Site('bu_953a8',                     'code', 'd63f0100 a9464ff4 f94023f7 a94557f6 a9437bfd 9101c3ff d65f03c0', 0),  # -> 0x7000e953a8
    Site('bv_188b8',                     'code', 'f9475e68 b5000008/ff00001f 9000000b/9f00001f f940016b/ffc003ff f9400169 b4000009/ff00001f aa0003e8 b4000000/ff00001f', 0),  # -> 0x7000d188b8
    Site('bv_188c4',                     'code', 'f942196b f9400169 b4000009/ff00001f aa0003e8 b4000000/ff00001f f9400109 9000000a/9f00001f f9401929', 0),  # -> 0x7000d188c4
    Site('bv_188c8',                     'code', 'f9400169 b4000009/ff00001f aa0003e8 b4000000/ff00001f f9400109 9000000a/9f00001f f9401929 f940014a/ffc003ff', 0),  # -> 0x7000d188c8
    Site('bv_188d8',                     'code', 'f9400109 9000000a/9f00001f f9401929 f940014a/ffc003ff eb0a013f 54000001/ff00001f f9400171 7941b109', 0),  # -> 0x7000d188d8
    Site('bv_188e0',                     'code', 'f9401929 f9447d4a eb0a013f 54000001/ff00001f f9400171 7941b109 37000009/fff8001f aa1f03e9', 0),  # -> 0x7000d188e0
    Site('bv_188e4',                     'code', 'f9447d4a eb0a013f 54000001/ff00001f f9400171 7941b109 37000009/fff8001f aa1f03e9 b940910a', 0),  # -> 0x7000d188e4
    Site('bv_188f0',                     'code', 'f9400171 7941b109 37000009/fff8001f aa1f03e9 b940910a 531d7142 37f8000a/fff8001f 7100205f', 0),  # -> 0x7000d188f0
    Site('bv_188f4',                     'code', '7941b109 37000009/fff8001f aa1f03e9 b940910a 531d7142 37f8000a/fff8001f 7100205f 54000008/ff00001f', 0),  # -> 0x7000d188f4
    Site('bv_18900',                     'code', 'b940910a 531d7142 37f8000a/fff8001f 7100205f 54000008/ff00001f f940750c 9103810f eb0f019f', 0),  # -> 0x7000d18900
    Site('bv_18914',                     'code', 'f940750c 9103810f eb0f019f 54000000/ff00001f b980f50a cb0a03ed 39437110 cb0a01ee', 0),  # -> 0x7000d18914
    Site('bv_18924',                     'code', 'b980f50a cb0a03ed 39437110 cb0a01ee cb0a018c 35000010/ff00001f f9400d90 f100be1f', 0),  # -> 0x7000d18924
    Site('bv_1892c',                     'code', '39437110 cb0a01ee cb0a018c 35000010/ff00001f f9400d90 f100be1f 54000009/ff00001f 5280060a', 0),  # -> 0x7000d1892c
    Site('bv_1893c',                     'code', 'f9400d90 f100be1f 54000009/ff00001f 5280060a 7940258e f9000d8a b980f50d 8b0c01aa', 0),  # -> 0x7000d1893c
    Site('bv_1894c',                     'code', '7940258e f9000d8a b980f50d 8b0c01aa f9400551 eb0f023f 54000001/ff00001f aa1f03ed', 0),  # -> 0x7000d1894c
    Site('bv_18950',                     'code', 'f9000d8a b980f50d 8b0c01aa f9400551 eb0f023f 54000001/ff00001f aa1f03ed f9400152', 0),  # -> 0x7000d18950
    Site('bv_18954',                     'code', 'b980f50d 8b0c01aa f9400551 eb0f023f 54000001/ff00001f aa1f03ed f9400152 b4000012/ff00001f', 0),  # -> 0x7000d18954
    Site('bv_1895c',                     'code', 'f9400551 eb0f023f 54000001/ff00001f aa1f03ed f9400152 b4000012/ff00001f f9000651 f9400551', 0),  # -> 0x7000d1895c
    Site('bv_1896c',                     'code', 'f9400152 b4000012/ff00001f f9000651 f9400551 b4000011/ff00001f f9400152 f9000232 a9007d5f', 0),  # -> 0x7000d1896c
    Site('bv_18974',                     'code', 'f9000651 f9400551 b4000011/ff00001f f9400152 f9000232 a9007d5f 9103e10a b940f111', 0),  # -> 0x7000d18974
    Site('bv_18978',                     'code', 'f9400551 b4000011/ff00001f f9400152 f9000232 a9007d5f 9103e10a b940f111 b9409112', 0),  # -> 0x7000d18978
    Site('bv_18980',                     'code', 'f9400152 f9000232 a9007d5f 9103e10a b940f111 b9409112 51000631 7100065f', 0),  # -> 0x7000d18980
    Site('bv_18984',                     'code', 'f9000232 a9007d5f 9103e10a b940f111 b9409112 51000631 7100065f b900f111', 0),  # -> 0x7000d18984
    Site('bv_18988',                     'code', 'a9007d5f 9103e10a b940f111 b9409112 51000631 7100065f b900f111 b9810d11', 0),  # -> 0x7000d18988
    Site('bv_18990',                     'code', 'b940f111 b9409112 51000631 7100065f b900f111 b9810d11 8b0c0221 54000001/ff00001f', 0),  # -> 0x7000d18990
    Site('bv_18994',                     'code', 'b9409112 51000631 7100065f b900f111 b9810d11 8b0c0221 54000001/ff00001f f9400151', 0),  # -> 0x7000d18994
    Site('bv_189a0',                     'code', 'b900f111 b9810d11 8b0c0221 54000001/ff00001f f9400151 f9000141 a9002831 b4000011/ff00001f', 0),  # -> 0x7000d189a0
    Site('bv_189a4',                     'code', 'b9810d11 8b0c0221 54000001/ff00001f f9400151 f9000141 a9002831 b4000011/ff00001f f9000621', 0),  # -> 0x7000d189a4
    Site('bv_189b0',                     'code', 'f9400151 f9000141 a9002831 b4000011/ff00001f f9000621 b941090a 1100054a b901090a', 0),  # -> 0x7000d189b0
    Site('bv_189b4',                     'code', 'f9000141 a9002831 b4000011/ff00001f f9000621 b941090a 1100054a b901090a d101460a', 0),  # -> 0x7000d189b4
    Site('bv_189b8',                     'code', 'a9002831 b4000011/ff00001f f9000621 b941090a 1100054a b901090a d101460a b100895f', 0),  # -> 0x7000d189b8
    Site('bv_189c0',                     'code', 'f9000621 b941090a 1100054a b901090a d101460a b100895f 54000008/ff00001f 8b0e018e', 0),  # -> 0x7000d189c0
    Site('bv_189c4',                     'code', 'b941090a 1100054a b901090a d101460a b100895f 54000008/ff00001f 8b0e018e d101420a', 0),  # -> 0x7000d189c4
    Site('bv_189cc',                     'code', 'b901090a d101460a b100895f 54000008/ff00001f 8b0e018e d101420a f8050ddf f9000dca', 0),  # -> 0x7000d189cc
    Site('bv_189e4',                     'code', 'f8050ddf f9000dca 529fffea b90011df f90005df 790021ca b980f510 b500000d/ff00001f', 0),  # -> 0x7000d189e4
    Site('bv_189e8',                     'code', 'f9000dca 529fffea b90011df f90005df 790021ca b980f510 b500000d/ff00001f f94001ed', 0),  # -> 0x7000d189e8
    Site('bv_189f0',                     'code', 'b90011df f90005df 790021ca b980f510 b500000d/ff00001f f94001ed 8b1001ca f90001ea', 0),  # -> 0x7000d189f0
    Site('bv_189f4',                     'code', 'f90005df 790021ca b980f510 b500000d/ff00001f f94001ed 8b1001ca f90001ea a9003d4d', 0),  # -> 0x7000d189f4
    Site('bv_189f8',                     'code', '790021ca b980f510 b500000d/ff00001f f94001ed 8b1001ca f90001ea a9003d4d b400000d/ff00001f', 0),  # -> 0x7000d189f8
    Site('bv_189fc',                     'code', 'b980f510 b500000d/ff00001f f94001ed 8b1001ca f90001ea a9003d4d b400000d/ff00001f f90005aa', 0),  # -> 0x7000d189fc
    Site('bv_18a04',                     'code', 'f94001ed 8b1001ca f90001ea a9003d4d b400000d/ff00001f f90005aa b940f10a 1100054a', 0),  # -> 0x7000d18a04
    Site('bv_18a0c',                     'code', 'f90001ea a9003d4d b400000d/ff00001f f90005aa b940f10a 1100054a b900f10a 7941b508', 0),  # -> 0x7000d18a0c
    Site('bv_18a10',                     'code', 'a9003d4d b400000d/ff00001f f90005aa b940f10a 1100054a b900f10a 7941b508 79002188', 0),  # -> 0x7000d18a10
    Site('bv_18a18',                     'code', 'f90005aa b940f10a 1100054a b900f10a 7941b508 79002188 79402588 8b080188', 0),  # -> 0x7000d18a18
    Site('bv_18a1c',                     'code', 'b940f10a 1100054a b900f10a 7941b508 79002188 79402588 8b080188 91008108', 0),  # -> 0x7000d18a1c
    Site('bv_18a24',                     'code', 'b900f10a 7941b508 79002188 79402588 8b080188 91008108 b5000009/ff00001f 90000009/9f00001f', 0),  # -> 0x7000d18a24
    Site('bv_18a28',                     'code', '7941b508 79002188 79402588 8b080188 91008108 b5000009/ff00001f 90000009/9f00001f aa0803ea', 0),  # -> 0x7000d18a28
    Site('bv_18a2c',                     'code', '79002188 79402588 8b080188 91008108 b5000009/ff00001f 90000009/9f00001f aa0803ea f9400129/ffc003ff', 0),  # -> 0x7000d18a2c
    Site('bv_18a30',                     'code', '79402588 8b080188 91008108 b5000009/ff00001f 90000009/9f00001f aa0803ea f9400129/ffc003ff 91004129', 0),  # -> 0x7000d18a30
    Site('bv_18a48',                     'code', 'f9447129 91004129 f8008d49 aa0a03e9 a9017d5f f8008d20 b4000000/ff00001f 7941b009', 0),  # -> 0x7000d18a48
    Site('bv_18a50',                     'code', 'f8008d49 aa0a03e9 a9017d5f f8008d20 b4000000/ff00001f 7941b009 37000009/fff8001f aa1f03e9', 0),  # -> 0x7000d18a50
    Site('bv_18a58',                     'code', 'a9017d5f f8008d20 b4000000/ff00001f 7941b009 37000009/fff8001f aa1f03e9 aa0003ed f8478dab', 0),  # -> 0x7000d18a58
    Site('bv_18a5c',                     'code', 'f8008d20 b4000000/ff00001f 7941b009 37000009/fff8001f aa1f03e9 aa0003ed f8478dab b98015ac', 0),  # -> 0x7000d18a5c
    Site('bv_18a64',                     'code', '7941b009 37000009/fff8001f aa1f03e9 aa0003ed f8478dab b98015ac 8b0a018c f90001ac', 0),  # -> 0x7000d18a64
    Site('bv_18a74',                     'code', 'f8478dab b98015ac 8b0a018c f90001ac a900358b b400000b/ff00001f f900056c b940880b', 0),  # -> 0x7000d18a74
    Site('bv_18a78',                     'code', 'b98015ac 8b0a018c f90001ac a900358b b400000b/ff00001f f900056c b940880b 1100056b', 0),  # -> 0x7000d18a78
    Site('bv_18a80',                     'code', 'f90001ac a900358b b400000b/ff00001f f900056c b940880b 1100056b b900880b b5000009/ff00001f', 0),  # -> 0x7000d18a80
    Site('bv_18a84',                     'code', 'a900358b b400000b/ff00001f f900056c b940880b 1100056b b900880b b5000009/ff00001f 90000009/9f00001f', 0),  # -> 0x7000d18a84
    Site('bv_18a8c',                     'code', 'f900056c b940880b 1100056b b900880b b5000009/ff00001f 90000009/9f00001f 91000129/ffc003ff f9000149', 0),  # -> 0x7000d18a8c
    Site('bv_18a90',                     'code', 'b940880b 1100056b b900880b b5000009/ff00001f 90000009/9f00001f 91000129/ffc003ff f9000149 90000009/9f00001f', 0),  # -> 0x7000d18a90
    Site('bv_18a98',                     'code', 'b900880b b5000009/ff00001f 90000009/9f00001f 91000129/ffc003ff f9000149 90000009/9f00001f 9000000b/9f00001f 9100016b/ffc003ff', 0),  # -> 0x7000d18a98
    Site('bv_18aa8',                     'code', 'f9000149 90000009/9f00001f 9000000b/9f00001f 9100016b/ffc003ff f900012a/ffc003ff 52a00029 f900010b b9002909', 0),  # -> 0x7000d18aa8
    Site('bv_18ab8',                     'code', 'f907592a 52a00029 f900010b b9002909 3900b11f f9075e68 f9403bf3 aa0803e0', 0),  # -> 0x7000d18ab8
    Site('bv_18ac0',                     'code', 'f900010b b9002909 3900b11f f9075e68 f9403bf3 aa0803e0 a9467bfd 910203ff', 0),  # -> 0x7000d18ac0
    Site('bv_18ac4',                     'code', 'b9002909 3900b11f f9075e68 f9403bf3 aa0803e0 a9467bfd 910203ff d65f03c0', 0),  # -> 0x7000d18ac4
    Site('bv_18ac8',                     'code', '3900b11f f9075e68 f9403bf3 aa0803e0 a9467bfd 910203ff d65f03c0 f9000fa0', 0),  # -> 0x7000d18ac8
    Site('bv_18acc',                     'code', 'f9075e68 f9403bf3 aa0803e0 a9467bfd 910203ff d65f03c0 f9000fa0 52800600', 0),  # -> 0x7000d18acc
    Site('bv_18ae4',                     'code', 'f9000fa0 52800600 94000000/fc000000 14000000/fc000000 f9000fa9 aa0b03e9 a902a3ea f9400120', 0),  # -> 0x7000d18ae4
    Site('bv_18af4',                     'code', 'f9000fa9 aa0b03e9 a902a3ea f9400120 b4000000/ff00001f 94000000/fc000000 f9400fa8 f9000100', 0),  # -> 0x7000d18af4
    Site('bv_18b00',                     'code', 'f9400120 b4000000/ff00001f 94000000/fc000000 f9400fa8 f9000100 a942a3ea b5000000/ff00001f 14000000/fc000000', 0),  # -> 0x7000d18b00
    Site('bv_18b08',                     'code', '94000000/fc000000 f9400fa8 f9000100 a942a3ea b5000000/ff00001f 14000000/fc000000 f9000fa0 aa0903e0', 0),  # -> 0x7000d18b08
    Site('bv_18b0c',                     'code', 'f9400fa8 f9000100 a942a3ea b5000000/ff00001f 14000000/fc000000 f9000fa0 aa0903e0 94000000/fc000000', 0),  # -> 0x7000d18b0c
    Site('bv_18b10',                     'code', 'f9000100 a942a3ea b5000000/ff00001f 14000000/fc000000 f9000fa0 aa0903e0 94000000/fc000000 9000000b/9f00001f', 0),  # -> 0x7000d18b10
    Site('bv_18b20',                     'code', 'f9000fa0 aa0903e0 94000000/fc000000 9000000b/9f00001f aa0003e8 f940016b/ffc003ff f9400fa0 b5000008/ff00001f', 0),  # -> 0x7000d18b20
    Site('bv_18b28',                     'code', '94000000/fc000000 9000000b/9f00001f aa0003e8 f940016b/ffc003ff f9400fa0 b5000008/ff00001f f9001bff 90000008/9f00001f', 0),  # -> 0x7000d18b28
    Site('bv_18b34',                     'code', 'f942196b f9400fa0 b5000008/ff00001f f9001bff 90000008/9f00001f aa0b03e9 f9400108/ffc003ff 5280010a', 0),  # -> 0x7000d18b34
    Site('bv_18b38',                     'code', 'f9400fa0 b5000008/ff00001f f9001bff 90000008/9f00001f aa0b03e9 f9400108/ffc003ff 5280010a 9100410b', 0),  # -> 0x7000d18b38
    Site('bv_18b4c',                     'code', 'f9447108 5280010a 9100410b 52800108 f90017e8 52800208 f900014b 5280020a', 0),  # -> 0x7000d18b4c
    Site('bv_18b64',                     'code', 'f900014b 5280020a f9000fa8 52800408 f900015f f900011f 52800308 f900011f', 0),  # -> 0x7000d18b64
    Site('bv_18b6c',                     'code', 'f9000fa8 52800408 f900015f f900011f 52800308 f900011f 14000000/fc000000 91026013', 0),  # -> 0x7000d18b6c
    Site('bv_18b74',                     'code', 'f900015f f900011f 52800308 f900011f 14000000/fc000000 91026013 f9000fa0 aa1303e0', 0),  # -> 0x7000d18b74
    Site('bv_18b78',                     'code', 'f900011f 52800308 f900011f 14000000/fc000000 91026013 f9000fa0 aa1303e0 a902a3ea', 0),  # -> 0x7000d18b78
    Site('bv_18b80',                     'code', 'f900011f 14000000/fc000000 91026013 f9000fa0 aa1303e0 a902a3ea 94000000/fc000000 a942a3ea', 0),  # -> 0x7000d18b80
    Site('bv_18b8c',                     'code', 'f9000fa0 aa1303e0 a902a3ea 94000000/fc000000 a942a3ea aa1303e9 f9400fa0 90000013/9f00001f', 0),  # -> 0x7000d18b8c
    Site('bv_18b98',                     'code', '94000000/fc000000 a942a3ea aa1303e9 f9400fa0 90000013/9f00001f 14000000/fc000000 aa0903e0 a902a3ea', 0),  # -> 0x7000d18b98
    Site('bv_18ba4',                     'code', 'f9400fa0 90000013/9f00001f 14000000/fc000000 aa0903e0 a902a3ea 94000000/fc000000 a942a3ea 14000000/fc000000', 0),  # -> 0x7000d18ba4
    Site('bv_18bb8',                     'code', '94000000/fc000000 a942a3ea 14000000/fc000000 f9000fa0 aa0803e0 52800601 52800102 d63f0120', 0),  # -> 0x7000d18bb8
    Site('bv_18bc4',                     'code', 'f9000fa0 aa0803e0 52800601 52800102 d63f0120 9000000b/9f00001f aa0003e8 f940016b/ffc003ff', 0),  # -> 0x7000d18bc4
    Site('bv_18bd4',                     'code', 'd63f0120 9000000b/9f00001f aa0003e8 f940016b/ffc003ff f9400fa0 14000000/fc000000 91026113 f9000fa0', 0),  # -> 0x7000d18bd4
    Site('bv_18be0',                     'code', 'f942196b f9400fa0 14000000/fc000000 91026113 f9000fa0 aa1303e0 f9001be8 f90013f1', 0),  # -> 0x7000d18be0
    Site('bv_18be4',                     'code', 'f9400fa0 14000000/fc000000 91026113 f9000fa0 aa1303e0 f9001be8 f90013f1 94000000/fc000000', 0),  # -> 0x7000d18be4
    Site('bv_18bf0',                     'code', 'f9000fa0 aa1303e0 f9001be8 f90013f1 94000000/fc000000 9000000b/9f00001f f94013f1 aa1303e9', 0),  # -> 0x7000d18bf0
    Site('bv_18c00',                     'code', '94000000/fc000000 9000000b/9f00001f f94013f1 aa1303e9 f9401be8 90000013/9f00001f f940016b/ffc003ff f9400fa0', 0),  # -> 0x7000d18c00
    Site('bv_18c18',                     'code', 'f942196b f9400fa0 14000000/fc000000 4b0203e2 3100055f f9001be8 a90227f1 f9000fa0', 0),  # -> 0x7000d18c18
    Site('bv_18c1c',                     'code', 'f9400fa0 14000000/fc000000 4b0203e2 3100055f f9001be8 a90227f1 f9000fa0 b9001be2', 0),  # -> 0x7000d18c1c
    Site('bv_18c34',                     'code', 'f9000fa0 b9001be2 54000001/ff00001f f9401be0 52800601 94000000/fc000000 14000000/fc000000 f9000fa0', 0),  # -> 0x7000d18c34
    Site('bv_18c48',                     'code', '94000000/fc000000 14000000/fc000000 f9000fa0 aa0903e0 f9001be8 94000000/fc000000 9000000b/9f00001f f940016b/ffc003ff', 0),  # -> 0x7000d18c48
    Site('bv_18c50',                     'code', 'f9000fa0 aa0903e0 f9001be8 94000000/fc000000 9000000b/9f00001f f940016b/ffc003ff f9401be8 14000000/fc000000', 0),  # -> 0x7000d18c50
    Site('bv_18c5c',                     'code', '94000000/fc000000 9000000b/9f00001f f940016b/ffc003ff f9401be8 14000000/fc000000 f9000fa0 aa0803e0 52800601', 0),  # -> 0x7000d18c5c
    Site('bv_18c64',                     'code', 'f942196b f9401be8 14000000/fc000000 f9000fa0 aa0803e0 52800601 a90227f1 f9001be8', 0),  # -> 0x7000d18c64
    Site('bv_18c70',                     'code', 'f9000fa0 aa0803e0 52800601 a90227f1 f9001be8 b9001be2 94000000/fc000000 aa0003ea', 0),  # -> 0x7000d18c70
    Site('bv_18c88',                     'code', '94000000/fc000000 aa0003ea b4000000/ff00001f 9000000b/9f00001f f9400fa0 aa0a03ec a942a3e9 f940016b/ffc003ff', 0),  # -> 0x7000d18c88
    Site('bv_18c98',                     'code', 'f9400fa0 aa0a03ec a942a3e9 f942196b 14000000/fc000000 7100061f a90227f1 b9001be2', 0),  # -> 0x7000d18c98
    Site('bv_18ca4',                     'code', 'f942196b 14000000/fc000000 7100061f a90227f1 b9001be2 f9001be8 f9000fa0 54000001/ff00001f', 0),  # -> 0x7000d18ca4
    Site('bv_18cbc',                     'code', 'f9000fa0 54000001/ff00001f aa1f03e8 f9400d89 f100c13f 54000003/ff00001f b4000008/ff00001f f9400d0b', 0),  # -> 0x7000d18cbc
    Site('bv_18cc8',                     'code', 'f9400d89 f100c13f 54000003/ff00001f b4000008/ff00001f f9400d0b eb09017f 54000009/ff00001f aa0c03e8', 0),  # -> 0x7000d18cc8
    Site('bv_18cd8',                     'code', 'f9400d0b eb09017f 54000009/ff00001f aa0c03e8 8b0a0189 f9400529 8b0d012c eb0e019f', 0),  # -> 0x7000d18cd8
    Site('bv_18cec',                     'code', 'f9400529 8b0d012c eb0e019f 54000001/ff00001f 14000000/fc000000 8b0a018c f940058c 8b0d018c', 0),  # -> 0x7000d18cec
    Site('bv_18d04',                     'code', 'f940058c 8b0d018c eb0e019f 54000001/ff00001f a90227f1 b9001be2 f9001be8 f9000fa0', 0),  # -> 0x7000d18d04
    Site('bv_18d20',                     'code', 'f9000fa0 f94013e8 b4000008/ff00001f f94013e8 f9400900 b4000000/ff00001f f9401be8 52800609 d100a3a1 f81f03a9 a93da7a8 52800108', 0),  # -> 0x7000d18d20
    Site('bv_18d30',                     'code', 'f9400900 b4000000/ff00001f f9401be8 52800609 d100a3a1 f81f03a9 a93da7a8 52800108', 0),  # -> 0x7000d18d30
    Site('bv_18d5c',                     'code', 'f9400008 f9400108 d63f0100 aa1f03e8 9000000b/9f00001f f9400fa0 f94017e9 f940016b/ffc003ff', 0),  # -> 0x7000d18d5c
    Site('bv_18d60',                     'code', 'f9400108 d63f0100 aa1f03e8 9000000b/9f00001f f9400fa0 f94017e9 f940016b/ffc003ff 14000000/fc000000', 0),  # -> 0x7000d18d60
    Site('bv_18d64',                     'code', 'd63f0100 aa1f03e8 9000000b/9f00001f f9400fa0 f94017e9 f940016b/ffc003ff 14000000/fc000000 cb0d022d', 0),  # -> 0x7000d18d64
    Site('bv_18d70',                     'code', 'f9400fa0 f94017e9 f942196b 14000000/fc000000 cb0d022d 14000000/fc000000 f9000fa0 aa0a03e0', 0),  # -> 0x7000d18d70
    Site('bv_18d78',                     'code', 'f942196b 14000000/fc000000 cb0d022d 14000000/fc000000 f9000fa0 aa0a03e0 f90003ee a902a3e9', 0),  # -> 0x7000d18d78
    Site('bv_18d88',                     'code', 'f9000fa0 aa0a03e0 f90003ee a902a3e9 a900b3f0 a901bfed 94000000/fc000000 9000000b/9f00001f', 0),  # -> 0x7000d18d88
    Site('bv_18da0',                     'code', '94000000/fc000000 9000000b/9f00001f a94043ee a941bfed f940016b/ffc003ff f9400bec a942a3e9 f9400fa0', 0),  # -> 0x7000d18da0
    Site('bv_18db0',                     'code', 'f942196b f9400bec a942a3e9 f9400fa0 14000000/fc000000 aa0b03ea f100c21f 54000000/ff00001f', 0),  # -> 0x7000d18db0
    Site('bv_18dbc',                     'code', 'f9400fa0 14000000/fc000000 aa0b03ea f100c21f 54000000/ff00001f aa1003eb f9000d90 14000000/fc000000', 0),  # -> 0x7000d18dbc
    Site('bv_18dd4',                     'code', 'f9000d90 14000000/fc000000 8b0d020f aa0b03ea f94001ed 8b1001cb f90001eb a9003d6d', 0),  # -> 0x7000d18dd4
    Site('bv_18de4',                     'code', 'f94001ed 8b1001cb f90001eb a9003d6d b400000d/ff00001f f90005ab b940f10b 1100056b', 0),  # -> 0x7000d18de4
    Site('bv_18dec',                     'code', 'f90001eb a9003d6d b400000d/ff00001f f90005ab b940f10b 1100056b b900f10b aa0a03eb', 0),  # -> 0x7000d18dec
    Site('bv_18df0',                     'code', 'a9003d6d b400000d/ff00001f f90005ab b940f10b 1100056b b900f10b aa0a03eb 14000000/fc000000', 0),  # -> 0x7000d18df0
    Site('bv_18df8',                     'code', 'f90005ab b940f10b 1100056b b900f10b aa0a03eb 14000000/fc000000 f9401be0 52800601', 0),  # -> 0x7000d18df8
    Site('bv_18dfc',                     'code', 'b940f10b 1100056b b900f10b aa0a03eb 14000000/fc000000 f9401be0 52800601 b9401be2', 0),  # -> 0x7000d18dfc
    Site('bv_18e04',                     'code', 'b900f10b aa0a03eb 14000000/fc000000 f9401be0 52800601 b9401be2 94000000/fc000000 14000000/fc000000', 0),  # -> 0x7000d18e04
    Site('bv_18e1c',                     'code', '94000000/fc000000 14000000/fc000000 71000a1f 54000001/ff00001f aa1f03e8 f9400d89 f100c13f 54000003/ff00001f', 0),  # -> 0x7000d18e1c
    Site('bv_18e30',                     'code', 'f9400d89 f100c13f 54000003/ff00001f b4000008/ff00001f f9400d0b eb09017f 54000002/ff00001f aa0c03e8', 0),  # -> 0x7000d18e30
    Site('bv_18e40',                     'code', 'f9400d0b eb09017f 54000002/ff00001f aa0c03e8 8b0a0189 f9400529 8b0d012c eb0e019f', 0),  # -> 0x7000d18e40
    Site('bv_18e54',                     'code', 'f9400529 8b0d012c eb0e019f 54000001/ff00001f 14000000/fc000000 aa1f03e8 f9400d89 f100011f', 0),  # -> 0x7000d18e54
    Site('bv_18e6c',                     'code', 'f9400d89 f100011f 9a88018b f100c13f 8b0a0189 f9400529 9a8b3108 8b0d012c', 0),  # -> 0x7000d18e6c
    Site('bv_18e80',                     'code', 'f9400529 9a8b3108 8b0d012c eb0e019f 54000001/ff00001f b4000008/ff00001f 9000000b/9f00001f aa0803ec', 0),  # -> 0x7000d18e80
    Site('bv_18ea0',                     'code', 'f9400d10 f9400fa0 a942a3e9 f942196b 14000000/fc000000', 0),  # -> 0x7000d18ea0
    Site('bv_18ea4',                     'code', 'f9400fa0 a942a3e9 f942196b 14000000/fc000000', 0),  # -> 0x7000d18ea4
    Site('bv_18eac',                     'code', 'f9400fa0 a942a3e9 f942196b 14000000/fc000000', 2),  # -> 0x7000d18eac
    Site('bw_05894',                     'code', 'b900301f a9025816 90000014/9f00001f aa0003f3 b900481f a903a008 f9400294/ffc003ff f9400280', 0),  # -> 0x7000005894
    Site('bw_05898',                     'code', 'a9025816 90000014/9f00001f aa0003f3 b900481f a903a008 f9400294/ffc003ff f9400280 a9057e7f', 0),  # -> 0x7000005898
    Site('bw_058a4',                     'code', 'b900481f a903a008 f9421a94 f9400280 a9057e7f b4000000/ff00001f aa1303e1 94000000/fc000000', 0),  # -> 0x70000058a4
    Site('bw_058a8',                     'code', 'a903a008 f9421a94 f9400280 a9057e7f b4000000/ff00001f aa1303e1 94000000/fc000000 f9400288', 0),  # -> 0x70000058a8
    Site('bw_058ac',                     'code', 'f9421a94 f9400280 a9057e7f b4000000/ff00001f aa1303e1 94000000/fc000000 f9400288 b4000008/ff00001f', 0),  # -> 0x70000058ac
    Site('bw_058b0',                     'code', 'f9400280 a9057e7f b4000000/ff00001f aa1303e1 94000000/fc000000 f9400288 b4000008/ff00001f b4000000/ff00001f', 0),  # -> 0x70000058b0
    Site('bw_058b4',                     'code', 'a9057e7f b4000000/ff00001f aa1303e1 94000000/fc000000 f9400288 b4000008/ff00001f b4000000/ff00001f f9400008', 0),  # -> 0x70000058b4
    Site('bw_058c0',                     'code', '94000000/fc000000 f9400288 b4000008/ff00001f b4000000/ff00001f f9400008 90000009/9f00001f f9401908 f9400129/ffc003ff', 0),  # -> 0x70000058c0
    Site('bw_058c4',                     'code', 'f9400288 b4000008/ff00001f b4000000/ff00001f f9400008 90000009/9f00001f f9401908 f9400129/ffc003ff eb09011f', 0),  # -> 0x70000058c4
    Site('bw_058d0',                     'code', 'f9400008 90000009/9f00001f f9401908 f9400129/ffc003ff eb09011f 54000001/ff00001f f940028d 7941b008', 0),  # -> 0x70000058d0
    Site('bw_058d8',                     'code', 'f9401908 f9447d29 eb09011f 54000001/ff00001f f940028d 7941b008 37000008/fff8001f aa1f03f5', 0),  # -> 0x70000058d8
    Site('bw_058dc',                     'code', 'f9447d29 eb09011f 54000001/ff00001f f940028d 7941b008 37000008/fff8001f aa1f03f5 b9409008', 0),  # -> 0x70000058dc
    Site('bw_058e8',                     'code', 'f940028d 7941b008 37000008/fff8001f aa1f03f5 b9409008 531d7102 37f80008/fff8001f 7100205f', 0),  # -> 0x70000058e8
    Site('bw_058ec',                     'code', '7941b008 37000008/fff8001f aa1f03f5 b9409008 531d7102 37f80008/fff8001f 7100205f 54000008/ff00001f', 0),  # -> 0x70000058ec
    Site('bw_058f8',                     'code', 'b9409008 531d7102 37f80008/fff8001f 7100205f 54000008/ff00001f f940740b 91038014 eb14017f', 0),  # -> 0x70000058f8
    Site('bw_0590c',                     'code', 'f940740b 91038014 eb14017f 54000000/ff00001f b980f408 cb0803e9 3943700c cb08028a', 0),  # -> 0x700000590c
    Site('bw_0591c',                     'code', 'b980f408 cb0803e9 3943700c cb08028a cb08016b 3500000c/ff00001f f9400d6c f101dd9f', 0),  # -> 0x700000591c
    Site('bw_05924',                     'code', '3943700c cb08028a cb08016b 3500000c/ff00001f f9400d6c f101dd9f 54000009/ff00001f 52800f08', 0),  # -> 0x7000005924
    Site('bw_05934',                     'code', 'f9400d6c f101dd9f 54000009/ff00001f 52800f08 79402569 f9000d68 b980f40e 8b0b01c8', 0),  # -> 0x7000005934
    Site('bw_05944',                     'code', '79402569 f9000d68 b980f40e 8b0b01c8 a940290d cb0e014e eb14015f 9a8e03f7', 0),  # -> 0x7000005944
    Site('bw_05948',                     'code', 'f9000d68 b980f40e 8b0b01c8 a940290d cb0e014e eb14015f 9a8e03f7 b400000d/ff00001f', 0),  # -> 0x7000005948
    Site('bw_0594c',                     'code', 'b980f40e 8b0b01c8 a940290d cb0e014e eb14015f 9a8e03f7 b400000d/ff00001f f90005aa', 0),  # -> 0x700000594c
    Site('bw_05954',                     'code', 'a940290d cb0e014e eb14015f 9a8e03f7 b400000d/ff00001f f90005aa f940050a b400000a/ff00001f', 0),  # -> 0x7000005954
    Site('bw_05968',                     'code', 'f90005aa f940050a b400000a/ff00001f f940010d f900014d a9007d1f 9103e008 b940f00a', 0),  # -> 0x7000005968
    Site('bw_0596c',                     'code', 'f940050a b400000a/ff00001f f940010d f900014d a9007d1f 9103e008 b940f00a b940900d', 0),  # -> 0x700000596c
    Site('bw_05974',                     'code', 'f940010d f900014d a9007d1f 9103e008 b940f00a b940900d 5100054a 710005bf', 0),  # -> 0x7000005974
    Site('bw_05978',                     'code', 'f900014d a9007d1f 9103e008 b940f00a b940900d 5100054a 710005bf b900f00a', 0),  # -> 0x7000005978
    Site('bw_0597c',                     'code', 'a9007d1f 9103e008 b940f00a b940900d 5100054a 710005bf b900f00a b9810c0a', 0),  # -> 0x700000597c
    Site('bw_05984',                     'code', 'b940f00a b940900d 5100054a 710005bf b900f00a b9810c0a 8b0b0141 54000001/ff00001f', 0),  # -> 0x7000005984
    Site('bw_05988',                     'code', 'b940900d 5100054a 710005bf b900f00a b9810c0a 8b0b0141 54000001/ff00001f f940010a', 0),  # -> 0x7000005988
    Site('bw_05994',                     'code', 'b900f00a b9810c0a 8b0b0141 54000001/ff00001f f940010a f9000101 a900202a b400000a/ff00001f', 0),  # -> 0x7000005994
    Site('bw_05998',                     'code', 'b9810c0a 8b0b0141 54000001/ff00001f f940010a f9000101 a900202a b400000a/ff00001f f9000541', 0),  # -> 0x7000005998
    Site('bw_059a4',                     'code', 'f940010a f9000101 a900202a b400000a/ff00001f f9000541 b9410808 11000508 b9010808', 0),  # -> 0x70000059a4
    Site('bw_059a8',                     'code', 'f9000101 a900202a b400000a/ff00001f f9000541 b9410808 11000508 b9010808 d1026588', 0),  # -> 0x70000059a8
    Site('bw_059ac',                     'code', 'a900202a b400000a/ff00001f f9000541 b9410808 11000508 b9010808 d1026588 b100891f', 0),  # -> 0x70000059ac
    Site('bw_059b4',                     'code', 'f9000541 b9410808 11000508 b9010808 d1026588 b100891f 54000008/ff00001f 8b090168', 0),  # -> 0x70000059b4
    Site('bw_059b8',                     'code', 'b9410808 11000508 b9010808 d1026588 b100891f 54000008/ff00001f 8b090168 d1026189', 0),  # -> 0x70000059b8
    Site('bw_059c0',                     'code', 'b9010808 d1026588 b100891f 54000008/ff00001f 8b090168 d1026189 f8098d1f f9000d09', 0),  # -> 0x70000059c0
    Site('bw_059d8',                     'code', 'f8098d1f f9000d09 529fffe9 b900111f f900051f 79002109 b980f409 b5000017/ff00001f', 0),  # -> 0x70000059d8
    Site('bw_059dc',                     'code', 'f9000d09 529fffe9 b900111f f900051f 79002109 b980f409 b5000017/ff00001f 8b090108', 0),  # -> 0x70000059dc
    Site('bw_059e4',                     'code', 'b900111f f900051f 79002109 b980f409 b5000017/ff00001f 8b090108 f9400289 f9000288', 0),  # -> 0x70000059e4
    Site('bw_059e8',                     'code', 'f900051f 79002109 b980f409 b5000017/ff00001f 8b090108 f9400289 f9000288 a9005109', 0),  # -> 0x70000059e8
    Site('bw_059ec',                     'code', '79002109 b980f409 b5000017/ff00001f 8b090108 f9400289 f9000288 a9005109 b4000009/ff00001f', 0),  # -> 0x70000059ec
    Site('bw_059f0',                     'code', 'b980f409 b5000017/ff00001f 8b090108 f9400289 f9000288 a9005109 b4000009/ff00001f f9000528', 0),  # -> 0x70000059f0
    Site('bw_059fc',                     'code', 'f9400289 f9000288 a9005109 b4000009/ff00001f f9000528 b940f008 11000508 b900f008', 0),  # -> 0x70000059fc
    Site('bw_05a00',                     'code', 'f9000288 a9005109 b4000009/ff00001f f9000528 b940f008 11000508 b900f008 7941b408', 0),  # -> 0x7000005a00
    Site('bw_05a04',                     'code', 'a9005109 b4000009/ff00001f f9000528 b940f008 11000508 b900f008 7941b408 79002168', 0),  # -> 0x7000005a04
    Site('bw_05a0c',                     'code', 'f9000528 b940f008 11000508 b900f008 7941b408 79002168 79402568 8b080168', 0),  # -> 0x7000005a0c
    Site('bw_05a10',                     'code', 'b940f008 11000508 b900f008 7941b408 79002168 79402568 8b080168 91008114', 0),  # -> 0x7000005a10
    Site('bw_05a18',                     'code', 'b900f008 7941b408 79002168 79402568 8b080168 91008114 b5000015/ff00001f aa1403f7', 0),  # -> 0x7000005a18
    Site('bw_05a1c',                     'code', '7941b408 79002168 79402568 8b080168 91008114 b5000015/ff00001f aa1403f7 90000008/9f00001f', 0),  # -> 0x7000005a1c
    Site('bw_05a20',                     'code', '79002168 79402568 8b080168 91008114 b5000015/ff00001f aa1403f7 90000008/9f00001f aa1403e0', 0),  # -> 0x7000005a20
    Site('bw_05a24',                     'code', '79402568 8b080168 91008114 b5000015/ff00001f aa1403f7 90000008/9f00001f aa1403e0 f8020eff', 0),  # -> 0x7000005a24
    Site('bw_05a40',                     'code', 'f8020eff f9458908 a902d29f f9001e9f 91004108 f9000288 94000000/fc000000 aa1403e8', 0),  # -> 0x7000005a40
    Site('bw_05a44',                     'code', 'f9458908 a902d29f f9001e9f 91004108 f9000288 94000000/fc000000 aa1403e8 52800409', 0),  # -> 0x7000005a44
    Site('bw_05a48',                     'code', 'a902d29f f9001e9f 91004108 f9000288 94000000/fc000000 aa1403e8 52800409 3901ce9f', 0),  # -> 0x7000005a48
    Site('bw_05a4c',                     'code', 'f9001e9f 91004108 f9000288 94000000/fc000000 aa1403e8 52800409 3901ce9f 38054d1f', 0),  # -> 0x7000005a4c
    Site('bw_05a54',                     'code', 'f9000288 94000000/fc000000 aa1403e8 52800409 3901ce9f 38054d1f b9005289 90000009/9f00001f', 0),  # -> 0x7000005a54
    Site('bw_05a58',                     'code', '94000000/fc000000 aa1403e8 52800409 3901ce9f 38054d1f b9005289 90000009/9f00001f 91000129/ffc003ff', 0),  # -> 0x7000005a58
    Site('bw_05a64',                     'code', '3901ce9f 38054d1f b9005289 90000009/9f00001f 91000129/ffc003ff 91004129 a9042289 90000008/9f00001f', 0),  # -> 0x7000005a64
    Site('bw_05a68',                     'code', '38054d1f b9005289 90000009/9f00001f 91000129/ffc003ff 91004129 a9042289 90000008/9f00001f 91000108/ffc003ff', 0),  # -> 0x7000005a68
    Site('bw_05a6c',                     'code', 'b9005289 90000009/9f00001f 91000129/ffc003ff 91004129 a9042289 90000008/9f00001f 91000108/ffc003ff f9000288', 0),  # -> 0x7000005a6c
    Site('bw_05a7c',                     'code', 'a9042289 90000008/9f00001f 91000108/ffc003ff f9000288 a9055274 90000008/9f00001f 91000108/ffc003ff f9402695', 0),  # -> 0x7000005a7c
    Site('bw_05a88',                     'code', 'f9000288 a9055274 90000008/9f00001f 91000108/ffc003ff f9402695 eb0802bf 54000000/ff00001f b9405288', 0),  # -> 0x7000005a88
    Site('bw_05a8c',                     'code', 'a9055274 90000008/9f00001f 91000108/ffc003ff f9402695 eb0802bf 54000000/ff00001f b9405288 aa1503e0', 0),  # -> 0x7000005a8c
    Site('bw_05a98',                     'code', 'f9402695 eb0802bf 54000000/ff00001f b9405288 aa1503e0 2a1f03e1 51000509 7100011f', 0),  # -> 0x7000005a98
    Site('bw_05aa4',                     'code', 'b9405288 aa1503e0 2a1f03e1 51000509 7100011f 1a89c3f8 93407f02 94000000/fc000000', 0),  # -> 0x7000005aa4
    Site('bw_05ac0',                     'code', '94000000/fc000000 3838cabf f9401e88 b5000008/ff00001f f9001e96 f94002c8 f90002d7 a9025a88', 0),  # -> 0x7000005ac0
    Site('bw_05ac4',                     'code', '3838cabf f9401e88 b5000008/ff00001f f9001e96 f94002c8 f90002d7 a9025a88 b4000008/ff00001f', 0),  # -> 0x7000005ac4
    Site('bw_05ac8',                     'code', 'f9401e88 b5000008/ff00001f f9001e96 f94002c8 f90002d7 a9025a88 b4000008/ff00001f f9000517', 0),  # -> 0x7000005ac8
    Site('bw_05ad0',                     'code', 'f9001e96 f94002c8 f90002d7 a9025a88 b4000008/ff00001f f9000517 b9403268 11000508', 0),  # -> 0x7000005ad0
    Site('bw_05ad4',                     'code', 'f94002c8 f90002d7 a9025a88 b4000008/ff00001f f9000517 b9403268 11000508 b9003268', 0),  # -> 0x7000005ad4
    Site('bw_05ad8',                     'code', 'f90002d7 a9025a88 b4000008/ff00001f f9000517 b9403268 11000508 b9003268 a9484ff4', 0),  # -> 0x7000005ad8
    Site('bw_05adc',                     'code', 'a9025a88 b4000008/ff00001f f9000517 b9403268 11000508 b9003268 a9484ff4 a94757f6', 0),  # -> 0x7000005adc
    Site('bw_05ae4',                     'code', 'f9000517 b9403268 11000508 b9003268 a9484ff4 a94757f6 a9465ff8 a9457bfd', 0),  # -> 0x7000005ae4
    Site('bw_05ae8',                     'code', 'b9403268 11000508 b9003268 a9484ff4 a94757f6 a9465ff8 a9457bfd 910243ff', 0),  # -> 0x7000005ae8
    Site('bw_05af0',                     'code', 'b9003268 a9484ff4 a94757f6 a9465ff8 a9457bfd 910243ff d65f03c0 52800f00', 0),  # -> 0x7000005af0
    Site('bw_05b10',                     'code', '94000000/fc000000 14000000/fc000000 f9401289 f9001e9f b4000009/ff00001f f940168a f900052a f9401689', 0),  # -> 0x7000005b10
    Site('bw_05b18',                     'code', 'f9401289 f9001e9f b4000009/ff00001f f940168a f900052a f9401689 b4000009/ff00001f f94002ea', 0),  # -> 0x7000005b18
    Site('bw_05b1c',                     'code', 'f9001e9f b4000009/ff00001f f940168a f900052a f9401689 b4000009/ff00001f f94002ea f900012a', 0),  # -> 0x7000005b1c
    Site('bw_05b24',                     'code', 'f940168a f900052a f9401689 b4000009/ff00001f f94002ea f900012a a9007eff b9401109', 0),  # -> 0x7000005b24
    Site('bw_05b28',                     'code', 'f900052a f9401689 b4000009/ff00001f f94002ea f900012a a9007eff b9401109 51000529', 0),  # -> 0x7000005b28
    Site('bw_05b2c',                     'code', 'f9401689 b4000009/ff00001f f94002ea f900012a a9007eff b9401109 51000529 b9001109', 0),  # -> 0x7000005b2c
    Site('bw_05b34',                     'code', 'f94002ea f900012a a9007eff b9401109 51000529 b9001109 14000000/fc000000 aa0803e0', 0),  # -> 0x7000005b34
    Site('bw_05b38',                     'code', 'f900012a a9007eff b9401109 51000529 b9001109 14000000/fc000000 aa0803e0 94000000/fc000000', 0),  # -> 0x7000005b38
    Site('bw_05b3c',                     'code', 'a9007eff b9401109 51000529 b9001109 14000000/fc000000 aa0803e0 94000000/fc000000 14000000/fc000000', 0),  # -> 0x7000005b3c
    Site('bw_05b40',                     'code', 'b9401109 51000529 b9001109 14000000/fc000000 aa0803e0 94000000/fc000000 14000000/fc000000 52800f01', 0),  # -> 0x7000005b40
    Site('bw_05b48',                     'code', 'b9001109 14000000/fc000000 aa0803e0 94000000/fc000000 14000000/fc000000 52800f01 52800102 d63f0100', 0),  # -> 0x7000005b48
    Site('bw_05b54',                     'code', '94000000/fc000000 14000000/fc000000 52800f01 52800102 d63f0100 aa0003f4 14000000/fc000000 9102e008', 0),  # -> 0x7000005b54
    Site('bw_05b64',                     'code', 'd63f0100 aa0003f4 14000000/fc000000 9102e008 91026015 aa0003f7 aa0803e0 aa0d03f4', 0),  # -> 0x7000005b64
    Site('bw_05b84',                     'code', '94000000/fc000000 aa1403ed aa1703e0 14000000/fc000000 4b0203e2 3100051f b90013e2 a90183ed', 0),  # -> 0x7000005b84
    Site('bw_05bb0',                     'code', '94000000/fc000000 14000000/fc000000 910082a0 94000000/fc000000 14000000/fc000000 52800f01 a90183ed b90013e2', 0),  # -> 0x7000005bb0
    Site('bw_05bbc',                     'code', '94000000/fc000000 14000000/fc000000 52800f01 a90183ed b90013e2 94000000/fc000000 aa0003e8 b4000000/ff00001f', 0),  # -> 0x7000005bbc
    Site('bw_05bd0',                     'code', '94000000/fc000000 aa0003e8 b4000000/ff00001f f94013e0 aa0803eb 14000000/fc000000 7100059f a90183ed', 0),  # -> 0x7000005bd0
    Site('bw_05bfc',                     'code', 'f9400d6d f101e1bf 54000003/ff00001f b400000c/ff00001f f9400d8e eb0d01df 54000009/ff00001f aa0b03ec', 0),  # -> 0x7000005bfc
    Site('bw_05c0c',                     'code', 'f9400d8e eb0d01df 54000009/ff00001f aa0b03ec 8b08016b f940056b 8b09016b eb0a017f', 0),  # -> 0x7000005c0c
    Site('bw_05c20',                     'code', 'f940056b 8b09016b eb0a017f 54000001/ff00001f 14000000/fc000000 8b08016b f940056b 8b09016b', 0),  # -> 0x7000005c20
    Site('bw_05c38',                     'code', 'f940056b 8b09016b eb0a017f 54000001/ff00001f a90183ed b90013e2 f9400fe8 b4000008/ff00001f', 0),  # -> 0x7000005c38
    Site('bw_05c5c',                     'code', 'f9400900 b4000000/ff00001f f94013e8 52800f09 9100a3e1 f90023e9 a902a7e8 52800108', 0),  # -> 0x7000005c5c
    Site('bw_05c88',                     'code', 'f9400008 f9400108 d63f0100 aa1f03f4 14000000/fc000000 a90183eb aa0803e0 a900b3e9', 0),  # -> 0x7000005c88
    Site('bw_05c8c',                     'code', 'f9400108 d63f0100 aa1f03f4 14000000/fc000000 a90183eb aa0803e0 a900b3e9 94000000/fc000000', 0),  # -> 0x7000005c8c
    Site('bw_05c90',                     'code', 'd63f0100 aa1f03f4 14000000/fc000000 a90183eb aa0803e0 a900b3e9 94000000/fc000000 a940b3e9', 0),  # -> 0x7000005c90
    Site('bw_05ca8',                     'code', '94000000/fc000000 a940b3e9 a94183eb 14000000/fc000000 f101e19f 54000000/ff00001f aa0c03e8 f9000d6c', 0),  # -> 0x7000005ca8
    Site('bw_05cc4',                     'code', 'f9000d6c 14000000/fc000000 8b17012a 8b090108 f9400149 f9000148 a9002909 b5000009/ff00001f', 0),  # -> 0x7000005cc4
    Site('bw_05cd4',                     'code', 'f9400149 f9000148 a9002909 b5000009/ff00001f 14000000/fc000000 f94013e0 52800f01 b94013e2', 0),  # -> 0x7000005cd4
    Site('bw_05cd8',                     'code', 'f9000148 a9002909 b5000009/ff00001f 14000000/fc000000 f94013e0 52800f01 b94013e2 94000000/fc000000', 0),  # -> 0x7000005cd8
    Site('bw_05cdc',                     'code', 'a9002909 b5000009/ff00001f 14000000/fc000000 f94013e0 52800f01 b94013e2 94000000/fc000000 14000000/fc000000', 0),  # -> 0x7000005cdc
    Site('bw_05cf4',                     'code', '94000000/fc000000 14000000/fc000000 7100099f 54000001/ff00001f aa1f03ec f9400d6d f101e1bf 54000003/ff00001f', 0),  # -> 0x7000005cf4
    Site('bw_05d08',                     'code', 'f9400d6d f101e1bf 54000003/ff00001f b400000c/ff00001f f9400d8e eb0d01df 54000002/ff00001f aa0b03ec', 0),  # -> 0x7000005d08
    Site('bw_05d18',                     'code', 'f9400d8e eb0d01df 54000002/ff00001f aa0b03ec 8b08016b f940056b 8b09016b eb0a017f', 0),  # -> 0x7000005d18
    Site('bw_05d2c',                     'code', 'f940056b 8b09016b eb0a017f 54000001/ff00001f 14000000/fc000000 aa1f03ec f100019f f9400d6d', 0),  # -> 0x7000005d2c
    Site('bw_05d48',                     'code', 'f9400d6d 9a8c016e 8b08016b f940056b f101e1bf 9a8e318c 8b09016b eb0a017f', 0),  # -> 0x7000005d48
    Site('bw_05d54',                     'code', 'f940056b f101e1bf 9a8e318c 8b09016b eb0a017f 54000001/ff00001f b400000c/ff00001f aa0c03eb', 0),  # -> 0x7000005d54
    Site('bw_05d74',                     'code', 'f9400d8c f94013e0 14000000/fc000000', 0),  # -> 0x7000005d74
    Site('bx_05d9c',                     'code', 'b900301f 90000015/9f00001f a9025816 aa0003f3 a903fc1f f94002b5/ffc003ff f900241f f94002a0', 0),  # -> 0x7000005d9c
    Site('bx_05da4',                     'code', 'a9025816 aa0003f3 a903fc1f f9421ab5 f900241f f94002a0 7900a27f b4000000/ff00001f', 0),  # -> 0x7000005da4
    Site('bx_05dac',                     'code', 'a903fc1f f9421ab5 f900241f f94002a0 7900a27f b4000000/ff00001f aa1303e1 94000000/fc000000', 0),  # -> 0x7000005dac
    Site('bx_05db0',                     'code', 'f9421ab5 f900241f f94002a0 7900a27f b4000000/ff00001f aa1303e1 94000000/fc000000 aa0003f4', 0),  # -> 0x7000005db0
    Site('bx_05db4',                     'code', 'f900241f f94002a0 7900a27f b4000000/ff00001f aa1303e1 94000000/fc000000 aa0003f4 9100a3e0', 0),  # -> 0x7000005db4
    Site('bx_05db8',                     'code', 'f94002a0 7900a27f b4000000/ff00001f aa1303e1 94000000/fc000000 aa0003f4 9100a3e0 f90017ff', 0),  # -> 0x7000005db8
    Site('bx_05dbc',                     'code', '7900a27f b4000000/ff00001f aa1303e1 94000000/fc000000 aa0003f4 9100a3e0 f90017ff 94000000/fc000000', 0),  # -> 0x7000005dbc
    Site('bx_05dc8',                     'code', '94000000/fc000000 aa0003f4 9100a3e0 f90017ff 94000000/fc000000 f94017e0 aa1403e1 52800102', 0),  # -> 0x7000005dc8
    Site('bx_05dd8',                     'code', '94000000/fc000000 f94017e0 aa1403e1 52800102 94000000/fc000000 f94017e2 aa0003e1 f9002660', 0),  # -> 0x7000005dd8
    Site('bx_05de8',                     'code', '94000000/fc000000 f94017e2 aa0003e1 f9002660 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 f94002a8', 0),  # -> 0x7000005de8
    Site('bx_05df4',                     'code', 'f9002660 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 f94002a8 b4000008/ff00001f aa1403e0 b4000014/ff00001f', 0),  # -> 0x7000005df4
    Site('bx_05e00',                     'code', '94000000/fc000000 f94002a8 b4000008/ff00001f aa1403e0 b4000014/ff00001f f9400008 90000009/9f00001f f9401908', 0),  # -> 0x7000005e00
    Site('bx_05e04',                     'code', 'f94002a8 b4000008/ff00001f aa1403e0 b4000014/ff00001f f9400008 90000009/9f00001f f9401908 f9400129/ffc003ff', 0),  # -> 0x7000005e04
    Site('bx_05e14',                     'code', 'f9400008 90000009/9f00001f f9401908 f9400129/ffc003ff eb09011f 54000001/ff00001f f94002ae 7941b008', 0),  # -> 0x7000005e14
    Site('bx_05e1c',                     'code', 'f9401908 f9447d29 eb09011f 54000001/ff00001f f94002ae 7941b008 37000008/fff8001f aa1f03e9', 0),  # -> 0x7000005e1c
    Site('bx_05e20',                     'code', 'f9447d29 eb09011f 54000001/ff00001f f94002ae 7941b008 37000008/fff8001f aa1f03e9 b9409008', 0),  # -> 0x7000005e20
    Site('bx_05e2c',                     'code', 'f94002ae 7941b008 37000008/fff8001f aa1f03e9 b9409008 531d7102 37f80008/fff8001f 7100205f', 0),  # -> 0x7000005e2c
    Site('bx_05e30',                     'code', '7941b008 37000008/fff8001f aa1f03e9 b9409008 531d7102 37f80008/fff8001f 7100205f 54000008/ff00001f', 0),  # -> 0x7000005e30
    Site('bx_05e3c',                     'code', 'b9409008 531d7102 37f80008/fff8001f 7100205f 54000008/ff00001f f940740c 91038015 eb15019f', 0),  # -> 0x7000005e3c
    Site('bx_05e50',                     'code', 'f940740c 91038015 eb15019f 54000000/ff00001f b980f408 cb0803ea 3943700d cb0802ab', 0),  # -> 0x7000005e50
    Site('bx_05e60',                     'code', 'b980f408 cb0803ea 3943700d cb0802ab cb08018c 3500000d/ff00001f f9400d8d f1021dbf', 0),  # -> 0x7000005e60
    Site('bx_05e68',                     'code', '3943700d cb0802ab cb08018c 3500000d/ff00001f f9400d8d f1021dbf 54000009/ff00001f 52801108', 0),  # -> 0x7000005e68
    Site('bx_05e78',                     'code', 'f9400d8d f1021dbf 54000009/ff00001f 52801108 7940258b f9000d88 b980f40a 8b0c0148', 0),  # -> 0x7000005e78
    Site('bx_05e88',                     'code', '7940258b f9000d88 b980f40a 8b0c0148 a940390f cb0a01ca eb1501df 9a8a03ea', 0),  # -> 0x7000005e88
    Site('bx_05e8c',                     'code', 'f9000d88 b980f40a 8b0c0148 a940390f cb0a01ca eb1501df 9a8a03ea b400000f/ff00001f', 0),  # -> 0x7000005e8c
    Site('bx_05e90',                     'code', 'b980f40a 8b0c0148 a940390f cb0a01ca eb1501df 9a8a03ea b400000f/ff00001f f90005ee', 0),  # -> 0x7000005e90
    Site('bx_05e98',                     'code', 'a940390f cb0a01ca eb1501df 9a8a03ea b400000f/ff00001f f90005ee f940050e b400000e/ff00001f', 0),  # -> 0x7000005e98
    Site('bx_05eac',                     'code', 'f90005ee f940050e b400000e/ff00001f f940010f f90001cf a9007d1f 9103e008 b940f00e', 0),  # -> 0x7000005eac
    Site('bx_05eb0',                     'code', 'f940050e b400000e/ff00001f f940010f f90001cf a9007d1f 9103e008 b940f00e b940900f', 0),  # -> 0x7000005eb0
    Site('bx_05eb8',                     'code', 'f940010f f90001cf a9007d1f 9103e008 b940f00e b940900f 510005ce 710005ff', 0),  # -> 0x7000005eb8
    Site('bx_05ebc',                     'code', 'f90001cf a9007d1f 9103e008 b940f00e b940900f 510005ce 710005ff b900f00e', 0),  # -> 0x7000005ebc
    Site('bx_05ec0',                     'code', 'a9007d1f 9103e008 b940f00e b940900f 510005ce 710005ff b900f00e b9810c0e', 0),  # -> 0x7000005ec0
    Site('bx_05ec8',                     'code', 'b940f00e b940900f 510005ce 710005ff b900f00e b9810c0e 8b0c01c1 54000001/ff00001f', 0),  # -> 0x7000005ec8
    Site('bx_05ecc',                     'code', 'b940900f 510005ce 710005ff b900f00e b9810c0e 8b0c01c1 54000001/ff00001f f940010e', 0),  # -> 0x7000005ecc
    Site('bx_05ed8',                     'code', 'b900f00e b9810c0e 8b0c01c1 54000001/ff00001f f940010e f9000101 a900202e b400000e/ff00001f', 0),  # -> 0x7000005ed8
    Site('bx_05edc',                     'code', 'b9810c0e 8b0c01c1 54000001/ff00001f f940010e f9000101 a900202e b400000e/ff00001f f90005c1', 0),  # -> 0x7000005edc
    Site('bx_05ee8',                     'code', 'f940010e f9000101 a900202e b400000e/ff00001f f90005c1 b9410808 11000508 b9010808', 0),  # -> 0x7000005ee8
    Site('bx_05eec',                     'code', 'f9000101 a900202e b400000e/ff00001f f90005c1 b9410808 11000508 b9010808 d102a5a8', 0),  # -> 0x7000005eec
    Site('bx_05ef0',                     'code', 'a900202e b400000e/ff00001f f90005c1 b9410808 11000508 b9010808 d102a5a8 b100891f', 0),  # -> 0x7000005ef0
    Site('bx_05ef8',                     'code', 'f90005c1 b9410808 11000508 b9010808 d102a5a8 b100891f 54000008/ff00001f 8b0b0188', 0),  # -> 0x7000005ef8
    Site('bx_05efc',                     'code', 'b9410808 11000508 b9010808 d102a5a8 b100891f 54000008/ff00001f 8b0b0188 d102a1ab', 0),  # -> 0x7000005efc
    Site('bx_05f04',                     'code', 'b9010808 d102a5a8 b100891f 54000008/ff00001f 8b0b0188 d102a1ab f80a8d1f f9000d0b', 0),  # -> 0x7000005f04
    Site('bx_05f1c',                     'code', 'f80a8d1f f9000d0b 529fffeb b900111f f900051f 7900210b b980f40b b500000a/ff00001f', 0),  # -> 0x7000005f1c
    Site('bx_05f20',                     'code', 'f9000d0b 529fffeb b900111f f900051f 7900210b b980f40b b500000a/ff00001f f94002aa', 0),  # -> 0x7000005f20
    Site('bx_05f28',                     'code', 'b900111f f900051f 7900210b b980f40b b500000a/ff00001f f94002aa 8b0b0108 f90002a8', 0),  # -> 0x7000005f28
    Site('bx_05f2c',                     'code', 'f900051f 7900210b b980f40b b500000a/ff00001f f94002aa 8b0b0108 f90002a8 a900550a', 0),  # -> 0x7000005f2c
    Site('bx_05f30',                     'code', '7900210b b980f40b b500000a/ff00001f f94002aa 8b0b0108 f90002a8 a900550a b400000a/ff00001f', 0),  # -> 0x7000005f30
    Site('bx_05f34',                     'code', 'b980f40b b500000a/ff00001f f94002aa 8b0b0108 f90002a8 a900550a b400000a/ff00001f f9000548', 0),  # -> 0x7000005f34
    Site('bx_05f3c',                     'code', 'f94002aa 8b0b0108 f90002a8 a900550a b400000a/ff00001f f9000548 b940f008 11000508', 0),  # -> 0x7000005f3c
    Site('bx_05f44',                     'code', 'f90002a8 a900550a b400000a/ff00001f f9000548 b940f008 11000508 b900f008 7941b408', 0),  # -> 0x7000005f44
    Site('bx_05f48',                     'code', 'a900550a b400000a/ff00001f f9000548 b940f008 11000508 b900f008 7941b408 79002188', 0),  # -> 0x7000005f48
    Site('bx_05f50',                     'code', 'f9000548 b940f008 11000508 b900f008 7941b408 79002188 79402588 8b080188', 0),  # -> 0x7000005f50
    Site('bx_05f54',                     'code', 'b940f008 11000508 b900f008 7941b408 79002188 79402588 8b080188 91008115', 0),  # -> 0x7000005f54
    Site('bx_05f5c',                     'code', 'b900f008 7941b408 79002188 79402588 8b080188 91008115 b5000009/ff00001f aa1503e0', 0),  # -> 0x7000005f5c
    Site('bx_05f60',                     'code', '7941b408 79002188 79402588 8b080188 91008115 b5000009/ff00001f aa1503e0 aa1403e1', 0),  # -> 0x7000005f60
    Site('bx_05f64',                     'code', '79002188 79402588 8b080188 91008115 b5000009/ff00001f aa1503e0 aa1403e1 94000000/fc000000', 0),  # -> 0x7000005f64
    Site('bx_05f68',                     'code', '79402588 8b080188 91008115 b5000009/ff00001f aa1503e0 aa1403e1 94000000/fc000000 90000014/9f00001f', 0),  # -> 0x7000005f68
    Site('bx_05f80',                     'code', '94000000/fc000000 90000014/9f00001f 90000009/9f00001f f9400294/ffc003ff f9002275 f9400288 f9400d08 f9400129/ffc003ff', 0),  # -> 0x7000005f80
    Site('bx_05f8c',                     'code', 'f9422e94 f9002275 f9400288 f9400d08 f9412929 eb09011f 54000001/ff00001f f9401ea9', 0),  # -> 0x7000005f8c
    Site('bx_05f90',                     'code', 'f9002275 f9400288 f9400d08 f9412929 eb09011f 54000001/ff00001f f9401ea9 910082a8', 0),  # -> 0x7000005f90
    Site('bx_05f94',                     'code', 'f9400288 f9400d08 f9412929 eb09011f 54000001/ff00001f f9401ea9 910082a8 b5000009/ff00001f', 0),  # -> 0x7000005f94
    Site('bx_05f98',                     'code', 'f9400d08 f9412929 eb09011f 54000001/ff00001f f9401ea9 910082a8 b5000009/ff00001f f9001eb6', 0),  # -> 0x7000005f98
    Site('bx_05f9c',                     'code', 'f9412929 eb09011f 54000001/ff00001f f9401ea9 910082a8 b5000009/ff00001f f9001eb6 f94002c9', 0),  # -> 0x7000005f9c
    Site('bx_05fa8',                     'code', 'f9401ea9 910082a8 b5000009/ff00001f f9001eb6 f94002c9 f90002c8 a9025aa9 b4000009/ff00001f', 0),  # -> 0x7000005fa8
    Site('bx_05fb4',                     'code', 'f9001eb6 f94002c9 f90002c8 a9025aa9 b4000009/ff00001f f9000528 b9403268 11000508', 0),  # -> 0x7000005fb4
    Site('bx_05fb8',                     'code', 'f94002c9 f90002c8 a9025aa9 b4000009/ff00001f f9000528 b9403268 11000508 b9003268', 0),  # -> 0x7000005fb8
    Site('bx_05fbc',                     'code', 'f90002c8 a9025aa9 b4000009/ff00001f f9000528 b9403268 11000508 b9003268 f9402268', 0),  # -> 0x7000005fbc
    Site('bx_05fc0',                     'code', 'a9025aa9 b4000009/ff00001f f9000528 b9403268 11000508 b9003268 f9402268 f9001e68', 0),  # -> 0x7000005fc0
    Site('bx_05fc8',                     'code', 'f9000528 b9403268 11000508 b9003268 f9402268 f9001e68 a9484ff4 f94033f7', 0),  # -> 0x7000005fc8
    Site('bx_05fcc',                     'code', 'b9403268 11000508 b9003268 f9402268 f9001e68 a9484ff4 f94033f7 a94757f6', 0),  # -> 0x7000005fcc
    Site('bx_05fd4',                     'code', 'b9003268 f9402268 f9001e68 a9484ff4 f94033f7 a94757f6 a9457bfd 910243ff', 0),  # -> 0x7000005fd4
    Site('bx_05fd8',                     'code', 'f9402268 f9001e68 a9484ff4 f94033f7 a94757f6 a9457bfd 910243ff d65f03c0', 0),  # -> 0x7000005fd8
    Site('bx_05fdc',                     'code', 'f9001e68 a9484ff4 f94033f7 a94757f6 a9457bfd 910243ff d65f03c0 52801100', 0),  # -> 0x7000005fdc
    Site('bx_05ffc',                     'code', '94000000/fc000000 14000000/fc000000 aa1403e0 d63f0100 90000008/9f00001f f9400108/ffc003ff f9400289 f9400d29', 0),  # -> 0x7000005ffc
    Site('bx_06008',                     'code', 'd63f0100 90000008/9f00001f f9400108/ffc003ff f9400289 f9400d29 eb08013f 54000000/ff00001f aa1403e0', 0),  # -> 0x7000006008
    Site('bx_06010',                     'code', 'f9412908 f9400289 f9400d29 eb08013f 54000000/ff00001f aa1403e0 aa0803f7 d63f0120', 0),  # -> 0x7000006010
    Site('bx_06014',                     'code', 'f9400289 f9400d29 eb08013f 54000000/ff00001f aa1403e0 aa0803f7 d63f0120 f9400288', 0),  # -> 0x7000006014
    Site('bx_06018',                     'code', 'f9400d29 eb08013f 54000000/ff00001f aa1403e0 aa0803f7 d63f0120 f9400288 f9400d08', 0),  # -> 0x7000006018
    Site('bx_0602c',                     'code', 'd63f0120 f9400288 f9400d08 eb17011f 54000000/ff00001f f9400697 aa1403e0 d63f0100', 0),  # -> 0x700000602c
    Site('bx_06030',                     'code', 'f9400288 f9400d08 eb17011f 54000000/ff00001f f9400697 aa1403e0 d63f0100 f9400689', 0),  # -> 0x7000006030
    Site('bx_06034',                     'code', 'f9400d08 eb17011f 54000000/ff00001f f9400697 aa1403e0 d63f0100 f9400689 eb0902ff', 0),  # -> 0x7000006034
    Site('bx_06040',                     'code', 'f9400697 aa1403e0 d63f0100 f9400689 eb0902ff 54000000/ff00001f 39400128 34000008/ff00001f', 0),  # -> 0x7000006040
    Site('bx_06048',                     'code', 'd63f0100 f9400689 eb0902ff 54000000/ff00001f 39400128 34000008/ff00001f aa1f03e8 91000529', 0),  # -> 0x7000006048
    Site('bx_0604c',                     'code', 'f9400689 eb0902ff 54000000/ff00001f 39400128 34000008/ff00001f aa1f03e8 91000529 f142011f', 0),  # -> 0x700000604c
    Site('bx_06058',                     'code', '39400128 34000008/ff00001f aa1f03e8 91000529 f142011f 54000000/ff00001f 3868692a 91000508', 0),  # -> 0x7000006058
    Site('bx_06070',                     'code', '3868692a 91000508 3500000a/ff00001f 14000000/fc000000 f94012aa f9001ebf b400000a/ff00001f f94016ab', 0),  # -> 0x7000006070
    Site('bx_06080',                     'code', 'f94012aa f9001ebf b400000a/ff00001f f94016ab f900054b f94016aa b400000a/ff00001f f940010b', 0),  # -> 0x7000006080
    Site('bx_06084',                     'code', 'f9001ebf b400000a/ff00001f f94016ab f900054b f94016aa b400000a/ff00001f f940010b f900014b', 0),  # -> 0x7000006084
    Site('bx_0608c',                     'code', 'f94016ab f900054b f94016aa b400000a/ff00001f f940010b f900014b a9007d1f b940112a', 0),  # -> 0x700000608c
    Site('bx_06090',                     'code', 'f900054b f94016aa b400000a/ff00001f f940010b f900014b a9007d1f b940112a 5100054a', 0),  # -> 0x7000006090
    Site('bx_06094',                     'code', 'f94016aa b400000a/ff00001f f940010b f900014b a9007d1f b940112a 5100054a b900112a', 0),  # -> 0x7000006094
    Site('bx_0609c',                     'code', 'f940010b f900014b a9007d1f b940112a 5100054a b900112a 14000000/fc000000 aa0803e0', 0),  # -> 0x700000609c
    Site('bx_060a0',                     'code', 'f900014b a9007d1f b940112a 5100054a b900112a 14000000/fc000000 aa0803e0 94000000/fc000000', 0),  # -> 0x70000060a0
    Site('bx_060a4',                     'code', 'a9007d1f b940112a 5100054a b900112a 14000000/fc000000 aa0803e0 94000000/fc000000 14000000/fc000000', 0),  # -> 0x70000060a4
    Site('bx_060a8',                     'code', 'b940112a 5100054a b900112a 14000000/fc000000 aa0803e0 94000000/fc000000 14000000/fc000000 52801101', 0),  # -> 0x70000060a8
    Site('bx_060b0',                     'code', 'b900112a 14000000/fc000000 aa0803e0 94000000/fc000000 14000000/fc000000 52801101 52800102 d63f0100', 0),  # -> 0x70000060b0
    Site('bx_060bc',                     'code', '94000000/fc000000 14000000/fc000000 52801101 52800102 d63f0100 aa0003f5 14000000/fc000000 9102e008', 0),  # -> 0x70000060bc
    Site('bx_060cc',                     'code', 'd63f0100 aa0003f5 14000000/fc000000 9102e008 91026017 f9000fee aa0003f5 aa0803e0', 0),  # -> 0x70000060cc
    Site('bx_060ec',                     'code', '94000000/fc000000 f9400fee aa1703e9 aa1503e0 14000000/fc000000 4b0203e2 52801101 f9000fee', 0),  # -> 0x70000060ec
    Site('bx_06110',                     'code', 'f9000fa9 f90013e0 b90013e2 54000001/ff00001f f94013e0 94000000/fc000000 14000000/fc000000 91008120', 0),  # -> 0x7000006110
    Site('bx_06124',                     'code', '94000000/fc000000 14000000/fc000000 91008120 94000000/fc000000 14000000/fc000000 52801101 f9000fee f9000fa9', 0),  # -> 0x7000006124
    Site('bx_06130',                     'code', '94000000/fc000000 14000000/fc000000 52801101 f9000fee f9000fa9 f90013e0 b90013e2 94000000/fc000000', 0),  # -> 0x7000006130
    Site('bx_06140',                     'code', 'f9000fa9 f90013e0 b90013e2 94000000/fc000000 aa0003e8 b4000000/ff00001f f94013e0 aa0803ec', 0),  # -> 0x7000006140
    Site('bx_0614c',                     'code', '94000000/fc000000 aa0003e8 b4000000/ff00001f f94013e0 aa0803ec f9400fa9 14000000/fc000000 710005bf', 0),  # -> 0x700000614c
    Site('bx_06160',                     'code', 'f9400fa9 14000000/fc000000 710005bf f9000fee f9000fa9 b90013e2 f90013e0 54000001/ff00001f', 0),  # -> 0x7000006160
    Site('bx_06170',                     'code', 'f9000fa9 b90013e2 f90013e0 54000001/ff00001f aa1f03e9 f9400d8d f10221bf 54000003/ff00001f', 0),  # -> 0x7000006170
    Site('bx_06184',                     'code', 'f9400d8d f10221bf 54000003/ff00001f b4000009/ff00001f f9400d2e eb0d01df 54000009/ff00001f aa0c03e9', 0),  # -> 0x7000006184
    Site('bx_06194',                     'code', 'f9400d2e eb0d01df 54000009/ff00001f aa0c03e9 8b08018c f940058c 8b0a018c eb0b019f', 0),  # -> 0x7000006194
    Site('bx_061a8',                     'code', 'f940058c 8b0a018c eb0b019f 54000001/ff00001f 14000000/fc000000 8b08018c f940058c 8b0a018c', 0),  # -> 0x70000061a8
    Site('bx_061c0',                     'code', 'f940058c 8b0a018c eb0b019f 54000001/ff00001f f9000fee f9000fa9 b90013e2 f90013e0', 0),  # -> 0x70000061c0
    Site('bx_061d4',                     'code', 'f9000fa9 b90013e2 f90013e0 f9400fe8 b4000008/ff00001f f9400fe8 f9400900 b4000000/ff00001f', 0),  # -> 0x70000061d4
    Site('bx_061ec',                     'code', 'f9400900 b4000000/ff00001f f94013e8 52801109 9100a3e1 f90023e9 a902a7e8 52800108', 0),  # -> 0x70000061ec
    Site('bx_06218',                     'code', 'f9400008 f9400108 d63f0100 f9400fa9 aa1f03f5 14000000/fc000000 a90183ec aa0803e0', 0),  # -> 0x7000006218
    Site('bx_0621c',                     'code', 'f9400108 d63f0100 f9400fa9 aa1f03f5 14000000/fc000000 a90183ec aa0803e0 f9000fa9', 0),  # -> 0x700000621c
    Site('bx_06220',                     'code', 'd63f0100 f9400fa9 aa1f03f5 14000000/fc000000 a90183ec aa0803e0 f9000fa9 f90003eb', 0),  # -> 0x7000006220
    Site('bx_06224',                     'code', 'f9400fa9 aa1f03f5 14000000/fc000000 a90183ec aa0803e0 f9000fa9 f90003eb a900abed', 0),  # -> 0x7000006224
    Site('bx_06238',                     'code', 'f9000fa9 f90003eb a900abed 94000000/fc000000 a94037eb f9400fa9 a94133ea f94013e0', 0),  # -> 0x7000006238
    Site('bx_06244',                     'code', '94000000/fc000000 a94037eb f9400fa9 a94133ea f94013e0 14000000/fc000000 f10221bf 54000000/ff00001f', 0),  # -> 0x7000006244
    Site('bx_0624c',                     'code', 'f9400fa9 a94133ea f94013e0 14000000/fc000000 f10221bf 54000000/ff00001f aa0d03e8 f9000d8d', 0),  # -> 0x700000624c
    Site('bx_06268',                     'code', 'f9000d8d 14000000/fc000000 8b0a016d 8b0b0108 f94001aa f90001a8 a900350a b500000a/ff00001f', 0),  # -> 0x7000006268
    Site('bx_06278',                     'code', 'f94001aa f90001a8 a900350a b500000a/ff00001f 14000000/fc000000 f94013e0 b94013e2 94000000/fc000000', 0),  # -> 0x7000006278
    Site('bx_0627c',                     'code', 'f90001a8 a900350a b500000a/ff00001f 14000000/fc000000 f94013e0 b94013e2 94000000/fc000000 14000000/fc000000', 0),  # -> 0x700000627c
    Site('bx_06280',                     'code', 'a900350a b500000a/ff00001f 14000000/fc000000 f94013e0 b94013e2 94000000/fc000000 14000000/fc000000 710009bf', 0),  # -> 0x7000006280
    Site('bx_06294',                     'code', '94000000/fc000000 14000000/fc000000 710009bf 54000001/ff00001f aa1f03e9 f9400d8d f10221bf 54000003/ff00001f', 0),  # -> 0x7000006294
    Site('bx_062a8',                     'code', 'f9400d8d f10221bf 54000003/ff00001f b4000009/ff00001f f9400d2e eb0d01df 54000002/ff00001f aa0c03e9', 0),  # -> 0x70000062a8
    Site('bx_062b8',                     'code', 'f9400d2e eb0d01df 54000002/ff00001f aa0c03e9 8b08018c f940058c 8b0a018c eb0b019f', 0),  # -> 0x70000062b8
    Site('bx_062cc',                     'code', 'f940058c 8b0a018c eb0b019f 54000001/ff00001f 14000000/fc000000 aa1f03e9 f100013f f9400d8d', 0),  # -> 0x70000062cc
    Site('bx_062e8',                     'code', 'f9400d8d 9a89018e 8b08018c f940058c f10221bf 9a8e3129 8b0a018c eb0b019f', 0),  # -> 0x70000062e8
    Site('bx_062f4',                     'code', 'f940058c f10221bf 9a8e3129 8b0a018c eb0b019f 54000001/ff00001f b4000009/ff00001f aa0903ec', 0),  # -> 0x70000062f4
    Site('bx_06314',                     'code', 'f9400d2d f94013e0 f9400fa9 14000000/fc000000 90000001/9f00001f aa1503e0 f9400021/ffc003ff 94000000/fc000000', 0),  # -> 0x7000006314
    Site('bx_0631c',                     'code', 'f9400fa9 14000000/fc000000 90000001/9f00001f aa1503e0 f9400021/ffc003ff 94000000/fc000000 14000000/fc000000', 0),  # -> 0x700000631c
    Site('bx_0632c',                     'code', 'aa1503e0 f9422c21 94000000/fc000000 14000000/fc000000', 1),  # -> 0x700000632c
    Site('bx_06330',                     'code', 'aa1503e0 f9422c21 94000000/fc000000 14000000/fc000000', 2),  # -> 0x7000006330
    Site('by_00908',                     'code', 'f9000008 aa0003f7 a9017c1f 90000008/9f00001f f8008eff f9400108/ffc003ff f9400108 b5000008/ff00001f', 0),  # -> 0x7000000908
    Site('by_00910',                     'code', 'a9017c1f 90000008/9f00001f f8008eff f9400108/ffc003ff f9400108 b5000008/ff00001f a9474ff4 a94657f6', 0),  # -> 0x7000000910
    Site('by_00918',                     'code', 'f8008eff f9421908 f9400108 b5000008/ff00001f a9474ff4 a94657f6 a9455ff8 a94467fa', 0),  # -> 0x7000000918
    Site('by_0091c',                     'code', 'f9421908 f9400108 b5000008/ff00001f a9474ff4 a94657f6 a9455ff8 a94467fa a9436ffc', 0),  # -> 0x700000091c
    Site('by_00920',                     'code', 'f9400108 b5000008/ff00001f a9474ff4 a94657f6 a9455ff8 a94467fa a9436ffc a9427bfd', 0),  # -> 0x7000000920
    Site('by_00950',                     'code', 'f947c108 f9400108 b4000008/ff00001f b9408900 94000000/fc000000 b4000000/ff00001f f9405808 9102e018', 0),  # -> 0x7000000950
    Site('by_00954',                     'code', 'f9400108 b4000008/ff00001f b9408900 94000000/fc000000 b4000000/ff00001f f9405808 9102e018 c85f7f14', 0),  # -> 0x7000000954
    Site('by_0095c',                     'code', 'b9408900 94000000/fc000000 b4000000/ff00001f f9405808 9102e018 c85f7f14 b2400289 c80a7f09', 0),  # -> 0x700000095c
    Site('by_00960',                     'code', '94000000/fc000000 b4000000/ff00001f f9405808 9102e018 c85f7f14 b2400289 c80a7f09 3500000a/ff00001f', 0),  # -> 0x7000000960
    Site('by_00968',                     'code', 'f9405808 9102e018 c85f7f14 b2400289 c80a7f09 3500000a/ff00001f b4000014/ff00001f b9406289', 0),  # -> 0x7000000968
    Site('by_00984',                     'code', 'b9406289 35000009/ff00001f f9400289 9000000a/9f00001f f9404529 f940014a/ffc003ff eb0a013f 54000001/ff00001f', 0),  # -> 0x7000000984
    Site('by_0098c',                     'code', 'f9400289 9000000a/9f00001f f9404529 f940014a/ffc003ff eb0a013f 54000001/ff00001f b9409289 7100053f', 0),  # -> 0x700000098c
    Site('by_00994',                     'code', 'f9404529 f944754a eb0a013f 54000001/ff00001f b9409289 7100053f f9401e8b 54000001/ff00001f', 0),  # -> 0x7000000994
    Site('by_00998',                     'code', 'f944754a eb0a013f 54000001/ff00001f b9409289 7100053f f9401e8b 54000001/ff00001f f9402289', 0),  # -> 0x7000000998
    Site('by_009a4',                     'code', 'b9409289 7100053f f9401e8b 54000001/ff00001f f9402289 9104416a 8b0b0129 eb13015f', 0),  # -> 0x70000009a4
    Site('by_009ac',                     'code', 'f9401e8b 54000001/ff00001f f9402289 9104416a 8b0b0129 eb13015f 54000008/ff00001f eb13013f', 0),  # -> 0x70000009ac
    Site('by_009b4',                     'code', 'f9402289 9104416a 8b0b0129 eb13015f 54000008/ff00001f eb13013f 54000009/ff00001f c85f7f08', 0),  # -> 0x70000009b4
    Site('by_009e4',                     'code', 'f90002f5 7941b2a8 37000008/fff8001f aa1f03f4 aa1503ea f8478d48 b9801549 8b130129', 0),  # -> 0x70000009e4
    Site('by_009e8',                     'code', '7941b2a8 37000008/fff8001f aa1f03f4 aa1503ea f8478d48 b9801549 8b130129 f9000149', 0),  # -> 0x70000009e8
    Site('by_009f8',                     'code', 'f8478d48 b9801549 8b130129 f9000149 a9002928 b4000008/ff00001f f9000509 b9408aa8', 0),  # -> 0x70000009f8
    Site('by_009fc',                     'code', 'b9801549 8b130129 f9000149 a9002928 b4000008/ff00001f f9000509 b9408aa8 11000508', 0),  # -> 0x70000009fc
    Site('by_00a04',                     'code', 'f9000149 a9002928 b4000008/ff00001f f9000509 b9408aa8 11000508 b9008aa8 b4000014/ff00001f', 0),  # -> 0x7000000a04
    Site('by_00a08',                     'code', 'a9002928 b4000008/ff00001f f9000509 b9408aa8 11000508 b9008aa8 b4000014/ff00001f 91008280', 0),  # -> 0x7000000a08
    Site('by_00a10',                     'code', 'f9000509 b9408aa8 11000508 b9008aa8 b4000014/ff00001f 91008280 a9474ff4 a94657f6', 0),  # -> 0x7000000a10
    Site('by_00a14',                     'code', 'b9408aa8 11000508 b9008aa8 b4000014/ff00001f 91008280 a9474ff4 a94657f6 a9455ff8', 0),  # -> 0x7000000a14
    Site('by_00a1c',                     'code', 'b9008aa8 b4000014/ff00001f 91008280 a9474ff4 a94657f6 a9455ff8 a94467fa a9436ffc', 0),  # -> 0x7000000a1c
    Site('by_00a44',                     'code', '14000000/fc000000 90000008/9f00001f 91000108/ffc003ff 91008100 94000000/fc000000 90000009/9f00001f 91000129/ffc003ff b9800128 34000008/ff00001f f9400534', 0),  # -> 0x7000000a44
    Site('by_00a54',                     'code', '94000000/fc000000 90000009/9f00001f 91000129/ffc003ff b9800128 34000008/ff00001f f9400534 90000018/9f00001f 8b080e88', 0),  # -> 0x7000000a54
    Site('by_00a60',                     'code', 'b9800128 34000008/ff00001f f9400534 90000018/9f00001f 8b080e88 f9000be8 f9400318/ffc003ff f9400288', 0),  # -> 0x7000000a60
    Site('by_00a68',                     'code', 'f9400534 90000018/9f00001f 8b080e88 f9000be8 f9400318/ffc003ff f9400288 f81f83a8 f9400108', 0),  # -> 0x7000000a68
    Site('by_00a78',                     'code', 'f9447718 f9400288 f81f83a8 f9400108 f9404508 eb18011f 54000001/ff00001f f85f83a8', 0),  # -> 0x7000000a78
    Site('by_00a7c',                     'code', 'f9400288 f81f83a8 f9400108 f9404508 eb18011f 54000001/ff00001f f85f83a8 b9409109', 0),  # -> 0x7000000a7c
    Site('by_00a84',                     'code', 'f9400108 f9404508 eb18011f 54000001/ff00001f f85f83a8 b9409109 f9401d08 7100053f', 0),  # -> 0x7000000a84
    Site('by_00a88',                     'code', 'f9404508 eb18011f 54000001/ff00001f f85f83a8 b9409109 f9401d08 7100053f 54000001/ff00001f', 0),  # -> 0x7000000a88
    Site('by_00a98',                     'code', 'b9409109 f9401d08 7100053f 54000001/ff00001f f85f83aa 91044109 f940214a 8b08014a eb13013f fa539140 54000009/ff00001f f85f83b9', 0),  # -> 0x7000000a98
    Site('by_00a9c',                     'code', 'f9401d08 7100053f 54000001/ff00001f f85f83aa 91044109 f940214a 8b08014a eb13013f fa539140 54000009/ff00001f f85f83b9', 0),  # -> 0x7000000a9c
    Site('by_00ab0',                     'code', 'f940214a 8b08014a eb13013f fa539140 54000009/ff00001f f85f83b9 b8864f3c f85f4328', 0),  # -> 0x7000000ab0
    Site('by_00ac8',                     'code', 'b8864f3c f85f4328 d100533a eb1a011f 54000000/ff00001f cb1c03fb cb1c0116 f85f83b5', 0),  # -> 0x7000000ac8
    Site('by_00af4',                     'code', 'f9400129 f9404529 eb18013f 54000001/ff00001f f85f83a9 b940912a f9401d29 7100055f', 0),  # -> 0x7000000af4
    Site('by_00af8',                     'code', 'f9404529 eb18013f 54000001/ff00001f f85f83a9 b940912a f9401d29 7100055f 54000001/ff00001f', 0),  # -> 0x7000000af8
    Site('by_00b08',                     'code', 'b940912a f9401d29 7100055f 54000001/ff00001f f85f83ab 9104412c f940216b 8b09016b eb13019f 54000008/ff00001f eb13017f 54000008/ff00001f 8b3cc2c9', 0),  # -> 0x7000000b08
    Site('by_00b0c',                     'code', 'f9401d29 7100055f 54000001/ff00001f f85f83ab 9104412c f940216b 8b09016b eb13019f 54000008/ff00001f eb13017f 54000008/ff00001f 8b3cc2c9', 0),  # -> 0x7000000b0c
    Site('by_00b20',                     'code', 'f940216b 8b09016b eb13019f 54000008/ff00001f eb13017f 54000008/ff00001f 8b3cc2c9 f9400529', 0),  # -> 0x7000000b20
    Site('by_00b3c',                     'code', 'f9400529 8b090376 4b0803e9 8b29c349 f81f83b6 eb0902df 54000001/ff00001f 14000000/fc000000', 0),  # -> 0x7000000b3c
    Site('by_00b68',                     'code', 'f9402108 8b090108 91044129 eb13013f 54000008/ff00001f eb13011f 54000009/ff00001f f85f83b9', 0),  # -> 0x7000000b68
    Site('by_00b88',                     'code', 'b8864f3c f85f4328 d100533a cb1c03fb cb1c0116 eb1a011f 54000001/ff00001f 90000008/9f00001f', 0),  # -> 0x7000000b88
    Site('by_00bb0',                     'code', '94000000/fc000000 f85f83b5 14000000/fc000000 9102e2a0 910262b4 94000000/fc000000 14000000/fc000000 aa1f03f4', 0),  # -> 0x7000000bb0
    Site('by_00bc4',                     'code', '94000000/fc000000 14000000/fc000000 aa1f03f4 c85f7f09 927ff929 c80a7f09 3500000a/ff00001f b5000008/ff00001f', 0),  # -> 0x7000000bc4
    Site('by_00bf4',                     'code', '94000000/fc000000 f9400315 b4000015/ff00001f eb15029f 54000001/ff00001f b4000016/ff00001f eb1402df 54000001/ff00001f', 0),  # -> 0x7000000bf4
    Site('by_00bf8',                     'code', 'f9400315 b4000015/ff00001f eb15029f 54000001/ff00001f b4000016/ff00001f eb1402df 54000001/ff00001f 90000009/9f00001f', 0),  # -> 0x7000000bf8
    Site('by_00c1c',                     'code', 'b9800128 34000008/ff00001f f9400535 8b080eae 90000008/9f00001f 91000108/ffc003ff f94002b4 f9400289', 0),  # -> 0x7000000c1c
    Site('by_00c24',                     'code', 'f9400535 8b080eae 90000008/9f00001f 91000108/ffc003ff f94002b4 f9400289 f9404529 eb08013f', 0),  # -> 0x7000000c24
    Site('by_00c34',                     'code', 'f94002b4 f9400289 f9404529 eb08013f 54000001/ff00001f b940928a 7100055f f9401e89', 0),  # -> 0x7000000c34
    Site('by_00c38',                     'code', 'f9400289 f9404529 eb08013f 54000001/ff00001f b940928a 7100055f f9401e89 54000001/ff00001f', 0),  # -> 0x7000000c38
    Site('by_00c3c',                     'code', 'f9404529 eb08013f 54000001/ff00001f b940928a 7100055f f9401e89 54000001/ff00001f f940228b', 0),  # -> 0x7000000c3c
    Site('by_00c48',                     'code', 'b940928a 7100055f f9401e89 54000001/ff00001f f940228b 9104412a 8b09016b eb13015f', 0),  # -> 0x7000000c48
    Site('by_00c50',                     'code', 'f9401e89 54000001/ff00001f f940228b 9104412a 8b09016b eb13015f fa539160 54000009/ff00001f', 0),  # -> 0x7000000c50
    Site('by_00c58',                     'code', 'f940228b 9104412a 8b09016b eb13015f fa539160 54000009/ff00001f aa1403f9 b8864f29', 0),  # -> 0x7000000c58
    Site('by_00c74',                     'code', 'b8864f29 f85f432a d100533a eb1a015f 54000000/ff00001f cb0903fb cb09015c 2a0903ea', 0),  # -> 0x7000000c74
    Site('by_00ca0',                     'code', 'f940028a f940454a eb08015f 54000001/ff00001f b940928b 7100057f f9401e8a 54000001/ff00001f', 0),  # -> 0x7000000ca0
    Site('by_00ca4',                     'code', 'f940454a eb08015f 54000001/ff00001f b940928b 7100057f f9401e8a 54000001/ff00001f f940228c', 0),  # -> 0x7000000ca4
    Site('by_00cb0',                     'code', 'b940928b 7100057f f9401e8a 54000001/ff00001f f940228c 9104414d 8b0a018c eb1301bf', 0),  # -> 0x7000000cb0
    Site('by_00cb8',                     'code', 'f9401e8a 54000001/ff00001f f940228c 9104414d 8b0a018c eb1301bf 54000008/ff00001f eb13019f', 0),  # -> 0x7000000cb8
    Site('by_00cc0',                     'code', 'f940228c 9104414d 8b0a018c eb1301bf 54000008/ff00001f eb13019f 54000008/ff00001f 8b16038a', 0),  # -> 0x7000000cc0
    Site('by_00ce0',                     'code', 'f940054a 8b0a0374 4b0903ea 8b2ac34a aa1403fc eb0a029f 54000001/ff00001f 14000000/fc000000', 0),  # -> 0x7000000ce0
    Site('by_00d08',                     'code', 'f9402289 8b0a0129 9104414a eb13015f 54000008/ff00001f eb13013f 54000009/ff00001f aa1403f9', 0),  # -> 0x7000000d08
    Site('by_00d28',                     'code', 'b8864f29 f85f432a d100533a cb0903fb cb09015c eb1a015f 54000001/ff00001f aa1403f5', 0),  # -> 0x7000000d28
    Site('by_00d48',                     'code', 'f9000314 90000008/9f00001f 91000108/ffc003ff 91008100 94000000/fc000000 f90002f5 b5000015/ff00001f 14000000/fc000000', 0),  # -> 0x7000000d48
    Site('by_00d58',                     'code', '94000000/fc000000 f90002f5 b5000015/ff00001f 14000000/fc000000 aa1403e0 aa1303e1 aa0803f5 d63f0120', 0),  # -> 0x7000000d58
    Site('by_00d5c',                     'code', 'f90002f5 b5000015/ff00001f 14000000/fc000000 aa1403e0 aa1303e1 aa0803f5 d63f0120 37000000/fff8001f', 0),  # -> 0x7000000d5c
    Site('by_00d74',                     'code', 'd63f0120 37000000/fff8001f aa1503e8 14000000/fc000000 f9402289 aa0b03ea 8b090169 d1044129', 0),  # -> 0x7000000d74
    Site('by_00d84',                     'code', 'f9402289 aa0b03ea 8b090169 d1044129 14000000/fc000000 a900bbe0 aa1403e0 aa1303e1', 0),  # -> 0x7000000d84
    Site('by_00da8',                     'code', 'd63f0140 36000000/fff8001f f85f83a8 90000009/9f00001f f9400108 f9404508 f9400129/ffc003ff eb09011f', 0),  # -> 0x7000000da8
    Site('by_00db8',                     'code', 'f9400108 f9404508 f9447529 eb09011f 54000001/ff00001f f85f83b4 90000008/9f00001f b940928b', 0),  # -> 0x7000000db8
    Site('by_00dbc',                     'code', 'f9404508 f9447529 eb09011f 54000001/ff00001f f85f83b4 90000008/9f00001f b940928b f9401e8a', 0),  # -> 0x7000000dbc
    Site('by_00dc0',                     'code', 'f9447529 eb09011f 54000001/ff00001f f85f83b4 90000008/9f00001f b940928b f9401e8a f9400108/ffc003ff', 0),  # -> 0x7000000dc0
    Site('by_00dd4',                     'code', 'b940928b f9401e8a f9447508 f9400bee 14000000/fc000000 f940228c aa0a03ed 8b0c014c', 0),  # -> 0x7000000dd4
    Site('by_00dd8',                     'code', 'f9401e8a f9447508 f9400bee 14000000/fc000000 f940228c aa0a03ed 8b0c014c d104418c', 0),  # -> 0x7000000dd8
    Site('by_00ddc',                     'code', 'f9447508 f9400bee 14000000/fc000000 f940228c aa0a03ed 8b0c014c d104418c 14000000/fc000000', 0),  # -> 0x7000000ddc
    Site('by_00de8',                     'code', 'f940228c aa0a03ed 8b0c014c d104418c 14000000/fc000000 90000008/9f00001f b9400329 f9400108/ffc003ff', 0),  # -> 0x7000000de8
    Site('by_00e00',                     'code', 'b9400329 f9447508 a940bbe0 14000000/fc000000 aa0803f5 eb14011f 54000000/ff00001f b94062a8', 0),  # -> 0x7000000e00
    Site('by_00e04',                     'code', 'f9447508 a940bbe0 14000000/fc000000 aa0803f5 eb14011f 54000000/ff00001f b94062a8 35000008/ff00001f', 0),  # -> 0x7000000e04
    Site('by_00e1c',                     'code', 'b94062a8 35000008/ff00001f f94002a8 90000009/9f00001f f9404508 f9400129/ffc003ff eb09011f 54000001/ff00001f', 0),  # -> 0x7000000e1c
    Site('by_00e24',                     'code', 'f94002a8 90000009/9f00001f f9404508 f9400129/ffc003ff eb09011f 54000001/ff00001f b94092a9 aa1503e8', 0),  # -> 0x7000000e24
    Site('by_00e2c',                     'code', 'f9404508 f9447529 eb09011f 54000001/ff00001f b94092a9 aa1503e8 7100053f f9401eaa', 0),  # -> 0x7000000e2c
    Site('by_00e30',                     'code', 'f9447529 eb09011f 54000001/ff00001f b94092a9 aa1503e8 7100053f f9401eaa 54000001/ff00001f', 0),  # -> 0x7000000e30
    Site('by_00e3c',                     'code', 'b94092a9 aa1503e8 7100053f f9401eaa 54000001/ff00001f f94022a8 91044149 8b0a0108', 0),  # -> 0x7000000e3c
    Site('by_00e48',                     'code', 'f9401eaa 54000001/ff00001f f94022a8 91044149 8b0a0108 aa1f03f6 eb13013f 54000008/ff00001f', 0),  # -> 0x7000000e48
    Site('by_00e50',                     'code', 'f94022a8 91044149 8b0a0108 aa1f03f6 eb13013f 54000008/ff00001f eb13011f 54000009/ff00001f', 0),  # -> 0x7000000e50
    Site('by_00e70',                     'code', 'f9000315 14000000/fc000000 aa1403e0 aa1303e1 aa0803f6 aa0e03f9 d63f0120 aa1903ee', 0),  # -> 0x7000000e70
    Site('by_00e88',                     'code', 'd63f0120 aa1903ee aa1603e8 37000000/fff8001f 14000000/fc000000 f940228a 8b0a012a d104414b', 0),  # -> 0x7000000e88
    Site('by_00e9c',                     'code', 'f940228a 8b0a012a d104414b aa0903ea 14000000/fc000000 f9402289 8b090149 d1044129', 0),  # -> 0x7000000e9c
    Site('by_00eb0',                     'code', 'f9402289 8b090149 d1044129 14000000/fc000000 aa1503e0 aa1303e1 94000000/fc000000 b4000000/ff00001f', 0),  # -> 0x7000000eb0
    Site('by_00ec8',                     'code', '94000000/fc000000 b4000000/ff00001f aa0003f4 eb15001f 54000001/ff00001f 14000000/fc000000 aa1603e0 aa1303e1', 0),  # -> 0x7000000ec8
    Site('by_00ee8',                     'code', '94000000/fc000000 b4000000/ff00001f aa0003f4 14000000/fc000000 aa1503f4 14000000/fc000000 f85f83a0 aa1303e1', 0),  # -> 0x7000000ee8
    Site('by_00f08',                     'code', 'd63f0100 37000000/fff8001f 14000000/fc000000 f85f83a9 f9402129 8b090109 d104412a aa0803e9 14000000/fc000000 f85f83a0 aa1303e1 d63f0120 36000000/fff8001f f85f83a8 f9400108 f9404508 eb18011f', 0),  # -> 0x7000000f08
    Site('by_00f18',                     'code', 'f9402129 8b090109 d104412a aa0803e9 14000000/fc000000 f85f83a0 aa1303e1 d63f0120 36000000/fff8001f f85f83a8 f9400108 f9404508 eb18011f', 0),  # -> 0x7000000f18
    Site('by_00f34',                     'code', 'd63f0120 36000000/fff8001f f85f83a8 f9400108 f9404508 eb18011f 54000001/ff00001f f85f83a8', 0),  # -> 0x7000000f34
    Site('by_00f40',                     'code', 'f9400108 f9404508 eb18011f 54000001/ff00001f f85f83a8 b940910a f9401d09 14000000/fc000000', 0),  # -> 0x7000000f40
    Site('by_00f44',                     'code', 'f9404508 eb18011f 54000001/ff00001f f85f83a8 b940910a f9401d09 14000000/fc000000 f85f83ab', 0),  # -> 0x7000000f44
    Site('by_00f54',                     'code', 'b940910a f9401d09 14000000/fc000000 f85f83ab aa0903ec f940216b 8b0b012b d104416b 14000000/fc000000 f85f83a8 f9402108 8b080128 d1044108 14000000/fc000000 f85f83b4', 0),  # -> 0x7000000f54
    Site('by_00f58',                     'code', 'f9401d09 14000000/fc000000 f85f83ab aa0903ec f940216b 8b0b012b d104416b 14000000/fc000000 f85f83a8 f9402108 8b080128 d1044108 14000000/fc000000 f85f83b4', 0),  # -> 0x7000000f58
    Site('by_00f68',                     'code', 'f940216b 8b0b012b d104416b 14000000/fc000000 f85f83a8 f9402108 8b080128 d1044108 14000000/fc000000 f85f83b4', 0),  # -> 0x7000000f68
    Site('by_00f7c',                     'code', 'f9402108 8b080128 d1044108 14000000/fc000000 f85f83b4 aa1303e1 aa1403e0 d63f0100', 0),  # -> 0x7000000f7c
    Site('by_00f98',                     'code', 'd63f0100 90000008/9f00001f 91000108/ffc003ff f9400bee 37000000/fff8001f 910022b5 eb0e02bf 54000001/ff00001f', 0),  # -> 0x7000000f98
    Site('by_00fc4',                     'code', 'b9800128 34000008/ff00001f f9400535 d37df116 f94002a0 aa1303e1 94000000/fc000000 f100001f f81f83a0 1a9f07e8 0a340108 37000008/fff8001f f85f83a8 b5000008/ff00001f 910022b5 f10022d6 54000001/ff00001f', 0),  # -> 0x7000000fc4
    Site('by_00fcc',                     'code', 'f9400535 d37df116 f94002a0 aa1303e1 94000000/fc000000 f100001f f81f83a0 1a9f07e8 0a340108 37000008/fff8001f f85f83a8 b5000008/ff00001f 910022b5 f10022d6 54000001/ff00001f', 0),  # -> 0x7000000fcc
    Site('by_00fd4',                     'code', 'f94002a0 aa1303e1 94000000/fc000000 f100001f f81f83a0 1a9f07e8 0a340108 37000008/fff8001f f85f83a8 b5000008/ff00001f 910022b5 f10022d6 54000001/ff00001f', 0),  # -> 0x7000000fd4
    Site('by_00fdc',                     'code', '94000000/fc000000 f100001f f81f83a0 1a9f07e8 0a340108 37000008/fff8001f f85f83a8 b5000008/ff00001f 910022b5 f10022d6 54000001/ff00001f', 0),  # -> 0x7000000fdc
    Site('by_01014',                     'code', '94000000/fc000000 f90002ff 14000000/fc000000 f85f83b4 14000000/fc000000 aa1503f6 14000000/fc000000 aa1503e0', 0),  # -> 0x7000001014
    Site('by_01018',                     'code', 'f90002ff 14000000/fc000000 f85f83b4 14000000/fc000000 aa1503f6 14000000/fc000000 aa1503e0 aa1303e1', 0),  # -> 0x7000001018
    Site('by_01038',                     'code', 'd63f0100 37000000/fff8001f 14000000/fc000000 f94022a8 aa0a03e9 8b080148 d1044108 14000000/fc000000 b9400328', 0),  # -> 0x7000001038
    Site('by_01044',                     'code', 'f94022a8 aa0a03e9 8b080148 d1044108 14000000/fc000000 b9400328 14000000/fc000000 f85f83a0', 0),  # -> 0x7000001044
    Site('by_01058',                     'code', 'b9400328 14000000/fc000000 f85f83a0 aa1303e1 d63f0100 37000000/fff8001f f9400be8 91002294', 0),  # -> 0x7000001058
    Site('by_01068',                     'code', 'd63f0100 37000000/fff8001f f9400be8 91002294 eb08029f 54000001/ff00001f aa1f03f8 52800034', 0),  # -> 0x7000001068
    Site('bz_939ac',                     'code', 'f9400288 aa1403e0 52820002 b940ce61 f9401908 d63f0100 b940ce61 94000000/fc000000', 0),  # -> 0x7000e939ac
    Site('bz_939b8',                     'code', 'b940ce61 f9401908 d63f0100 b940ce61 94000000/fc000000 b940d261 34000001/ff00001f f9400288', 0),  # -> 0x7000e939b8
    Site('bz_939bc',                     'code', 'f9401908 d63f0100 b940ce61 94000000/fc000000 b940d261 34000001/ff00001f f9400288 aa1403e0', 0),  # -> 0x7000e939bc
    Site('bz_939c0',                     'code', 'd63f0100 b940ce61 94000000/fc000000 b940d261 34000001/ff00001f f9400288 aa1403e0 52800102', 0),  # -> 0x7000e939c0
    Site('bz_939c4',                     'code', 'b940ce61 94000000/fc000000 b940d261 34000001/ff00001f f9400288 aa1403e0 52800102 f9401908', 0),  # -> 0x7000e939c4
    Site('bz_939cc',                     'code', 'b940d261 34000001/ff00001f f9400288 aa1403e0 52800102 f9401908 d63f0100 aa0003f6', 0),  # -> 0x7000e939cc
    Site('bz_939d4',                     'code', 'f9400288 aa1403e0 52800102 f9401908 d63f0100 aa0003f6 52800900 aa1403e1', 0),  # -> 0x7000e939d4
    Site('bz_939e0',                     'code', 'f9401908 d63f0100 aa0003f6 52800900 aa1403e1 52800102 94000000/fc000000 b940d262', 0),  # -> 0x7000e939e0
    Site('bz_939e4',                     'code', 'd63f0100 aa0003f6 52800900 aa1403e1 52800102 94000000/fc000000 b940d262 aa1603e1', 0),  # -> 0x7000e939e4
    Site('bz_939fc',                     'code', 'b940d262 aa1603e1 aa0003f7 94000000/fc000000 d503201f 10000000/9f00001f f900c277 d503201f', 0),  # -> 0x7000e939fc
    Site('bz_93a14',                     'code', 'f900c277 d503201f 10000001/9f00001f d503201f 10000002/9f00001f aa1703e3 94000000/fc000000 94000000/fc000000', 0),  # -> 0x7000e93a14
    Site('bz_93a3c',                     'code', 'f940d661 9106c260 94000000/fc000000 f940d661 91078260 94000000/fc000000 2d568660 90000000/9f00001f', 0),  # -> 0x7000e93a3c
    Site('bz_93a48',                     'code', 'f940d661 91078260 94000000/fc000000 2d568660 90000000/9f00001f 91000000/ffc003ff bd4002a2 bd011262', 0),  # -> 0x7000e93a48
    Site('bz_93a54',                     'code', '2d568660 90000000/9f00001f 91000000/ffc003ff bd4002a2 bd011262 7e21d800 bd4006a2 f9008e7f', 0),  # -> 0x7000e93a54
    Site('bz_93a60',                     'code', 'bd4002a2 bd011262 7e21d800 bd4006a2 f9008e7f bd011662 bd012260 7e21d820', 0),  # -> 0x7000e93a60
    Site('bz_93a64',                     'code', 'bd011262 7e21d800 bd4006a2 f9008e7f bd011662 bd012260 7e21d820 bd012660', 0),  # -> 0x7000e93a64
    Site('bz_93a6c',                     'code', 'bd4006a2 f9008e7f bd011662 bd012260 7e21d820 bd012660 94000000/fc000000 aa0003f8', 0),  # -> 0x7000e93a6c
    Site('bz_93a70',                     'code', 'f9008e7f bd011662 bd012260 7e21d820 bd012660 94000000/fc000000 aa0003f8 90000000/9f00001f', 0),  # -> 0x7000e93a70
    Site('bz_93a74',                     'code', 'bd011662 bd012260 7e21d820 bd012660 94000000/fc000000 aa0003f8 90000000/9f00001f 91000000/ffc003ff', 0),  # -> 0x7000e93a74
    Site('bz_93a78',                     'code', 'bd012260 7e21d820 bd012660 94000000/fc000000 aa0003f8 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000', 0),  # -> 0x7000e93a78
    Site('bz_93a80',                     'code', 'bd012660 94000000/fc000000 aa0003f8 90000000/9f00001f 91000000/ffc003ff 94000000/fc000000 b4000018/ff00001f aa0003f7', 0),  # -> 0x7000e93a80
    Site('bz_93ab8',                     'code', 'f9466508 f9400108 d63f0100 3942fa68 34000008/ff00001f b940e260 94000000/fc000000 2a0003e1', 0),  # -> 0x7000e93ab8
    Site('bz_93abc',                     'code', 'f9400108 d63f0100 3942fa68 34000008/ff00001f b940e260 94000000/fc000000 2a0003e1 90000008/9f00001f', 0),  # -> 0x7000e93abc
    Site('bz_93ac0',                     'code', 'd63f0100 3942fa68 34000008/ff00001f b940e260 94000000/fc000000 2a0003e1 90000008/9f00001f 910083e0', 0),  # -> 0x7000e93ac0
    Site('bz_93ac4',                     'code', '3942fa68 34000008/ff00001f b940e260 94000000/fc000000 2a0003e1 90000008/9f00001f 910083e0 f9400108/ffc003ff', 0),  # -> 0x7000e93ac4
    Site('bz_93acc',                     'code', 'b940e260 94000000/fc000000 2a0003e1 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100', 0),  # -> 0x7000e93acc
    Site('bz_93ad0',                     'code', '94000000/fc000000 2a0003e1 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100 52860000', 0),  # -> 0x7000e93ad0
    Site('bz_93ae0',                     'code', 'f9466908 f9400108 d63f0100 52860000 aa1403e1 52800102 94000000/fc000000 910083e1', 0),  # -> 0x7000e93ae0
    Site('bz_93ae4',                     'code', 'f9400108 d63f0100 52860000 aa1403e1 52800102 94000000/fc000000 910083e1 aa0003f6', 0),  # -> 0x7000e93ae4
    Site('bz_93ae8',                     'code', 'd63f0100 52860000 aa1403e1 52800102 94000000/fc000000 910083e1 aa0003f6 d63f0300', 0),  # -> 0x7000e93ae8
    Site('bz_93af8',                     'code', '94000000/fc000000 910083e1 aa0003f6 d63f0300 72001c1f 54000000/ff00001f aa1603e0 aa1703e1', 0),  # -> 0x7000e93af8
    Site('bz_93b04',                     'code', 'd63f0300 72001c1f 54000000/ff00001f aa1603e0 aa1703e1 94000000/fc000000 90000018/9f00001f 910083e2', 0),  # -> 0x7000e93b04
    Site('bz_93b18',                     'code', '94000000/fc000000 90000018/9f00001f 910083e2 f9400318/ffc003ff aa1603e0 2a1f03e1 f9400308 d63f0100', 0),  # -> 0x7000e93b18
    Site('bz_93b24',                     'code', 'f9468318 aa1603e0 2a1f03e1 f9400308 d63f0100 f9400308 910073e2 aa1603e0', 0),  # -> 0x7000e93b24
    Site('bz_93b30',                     'code', 'f9400308 d63f0100 f9400308 910073e2 aa1603e0 52800021 d63f0100 b94023e8', 0),  # -> 0x7000e93b30
    Site('bz_93b34',                     'code', 'd63f0100 f9400308 910073e2 aa1603e0 52800021 d63f0100 b94023e8 7100dd1f', 0),  # -> 0x7000e93b34
    Site('bz_93b38',                     'code', 'f9400308 910073e2 aa1603e0 52800021 d63f0100 b94023e8 7100dd1f 54000001/ff00001f', 0),  # -> 0x7000e93b38
    Site('bz_93b48',                     'code', 'd63f0100 b94023e8 7100dd1f 54000001/ff00001f b9401fe8 71003d1f 5400000b/ff00001f 3942fa68', 0),  # -> 0x7000e93b48
    Site('bz_93b64',                     'code', '3942fa68 3942fe69 2a090108 35000008/ff00001f 2a1f03e9 14000000/fc000000 2a1f03e1 14000000/fc000000', 0),  # -> 0x7000e93b64
    Site('bz_93b68',                     'code', '3942fe69 2a090108 35000008/ff00001f 2a1f03e9 14000000/fc000000 2a1f03e1 14000000/fc000000 90000008/9f00001f', 0),  # -> 0x7000e93b68
    Site('bz_93b8c',                     'code', 'f9469908 aa1603e0 aa1f03e2 f9400108 f9442c21 52800023 d63f0100 3942fe68', 0),  # -> 0x7000e93b8c
    Site('bz_93b98',                     'code', 'f9400108 f9442c21 52800023 d63f0100 3942fe68 3942fa69 b940e66a 3900b3e8', 0),  # -> 0x7000e93b98
    Site('bz_93b9c',                     'code', 'f9442c21 52800023 d63f0100 3942fe68 3942fa69 b940e66a 3900b3e8 2a090108', 0),  # -> 0x7000e93b9c
    Site('bz_93ba4',                     'code', 'd63f0100 3942fe68 3942fa69 b940e66a 3900b3e8 2a090108 52803d00 aa1403e1', 0),  # -> 0x7000e93ba4
    Site('bz_93ba8',                     'code', '3942fe68 3942fa69 b940e66a 3900b3e8 2a090108 52803d00 aa1403e1 52800102', 0),  # -> 0x7000e93ba8
    Site('bz_93bac',                     'code', '3942fa69 b940e66a 3900b3e8 2a090108 52803d00 aa1403e1 52800102 f90013f6', 0),  # -> 0x7000e93bac
    Site('bz_93bb0',                     'code', 'b940e66a 3900b3e8 2a090108 52803d00 aa1403e1 52800102 f90013f6 3900b7e8', 0),  # -> 0x7000e93bb0
    Site('bz_93bd4',                     'code', '94000000/fc000000 910083e1 aa0003f7 94000000/fc000000 9000001a/9f00001f aa1703e0 f940035a/ffc003ff aa1403e1', 0),  # -> 0x7000e93bd4
    Site('bz_93bec',                     'code', 'f941e35a aa1403e1 f9000357 94000000/fc000000 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108', 0),  # -> 0x7000e93bec
    Site('bz_93bf4',                     'code', 'f9000357 94000000/fc000000 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f', 0),  # -> 0x7000e93bf4
    Site('bz_93bf8',                     'code', '94000000/fc000000 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f 910083e0', 0),  # -> 0x7000e93bf8
    Site('bz_93c04',                     'code', 'f946f108 f9400108 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff 52800021 f9400108', 0),  # -> 0x7000e93c04
    Site('bz_93c08',                     'code', 'f9400108 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff 52800021 f9400108 d63f0100', 0),  # -> 0x7000e93c08
    Site('bz_93c0c',                     'code', 'd63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff 52800021 f9400108 d63f0100 f9400348', 0),  # -> 0x7000e93c0c
    Site('bz_93c18',                     'code', 'f946f508 52800021 f9400108 d63f0100 f9400348 910083e0 f9401901 90000008/9f00001f', 0),  # -> 0x7000e93c18
    Site('bz_93c20',                     'code', 'f9400108 d63f0100 f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff f9400108', 0),  # -> 0x7000e93c20
    Site('bz_93c24',                     'code', 'd63f0100 f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 b940d668', 0),  # -> 0x7000e93c24
    Site('bz_93c28',                     'code', 'f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 b940d668', 0),  # -> 0x7000e93c28
    Site('bz_93c30',                     'code', 'f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 b940d668 3100051f b9001fe8', 0),  # -> 0x7000e93c30
    Site('bz_93c38',                     'code', 'f946ed08 f9400108 d63f0100 b940d668 3100051f b9001fe8 54000001/ff00001f f9400308', 0),  # -> 0x7000e93c38
    Site('bz_93c3c',                     'code', 'f9400108 d63f0100 b940d668 3100051f b9001fe8 54000001/ff00001f f9400308 52800aa1', 0),  # -> 0x7000e93c3c
    Site('bz_93c40',                     'code', 'd63f0100 b940d668 3100051f b9001fe8 54000001/ff00001f f9400308 52800aa1 910073e2', 0),  # -> 0x7000e93c40
    Site('bz_93c44',                     'code', 'b940d668 3100051f b9001fe8 54000001/ff00001f f9400308 52800aa1 910073e2 aa1603e0', 0),  # -> 0x7000e93c44
    Site('bz_93c54',                     'code', 'f9400308 52800aa1 910073e2 aa1603e0 d63f0100 b9401fe8 93407d01 90000008/9f00001f', 0),  # -> 0x7000e93c54
    Site('bz_93c64',                     'code', 'd63f0100 b9401fe8 93407d01 90000008/9f00001f f9400108/ffc003ff 910083e0 f9400108 d63f0100 b940da68', 0),  # -> 0x7000e93c64
    Site('bz_93c74',                     'code', 'f946fd08 910083e0 f9400108 d63f0100 b940da68 3100051f b9001fe8 54000001/ff00001f', 0),  # -> 0x7000e93c74
    Site('bz_93c7c',                     'code', 'f9400108 d63f0100 b940da68 3100051f b9001fe8 54000001/ff00001f f9400308 52800a41', 0),  # -> 0x7000e93c7c
    Site('bz_93c80',                     'code', 'd63f0100 b940da68 3100051f b9001fe8 54000001/ff00001f f9400308 52800a41 910073e2', 0),  # -> 0x7000e93c80
    Site('bz_93c84',                     'code', 'b940da68 3100051f b9001fe8 54000001/ff00001f f9400308 52800a41 910073e2 aa1603e0', 0),  # -> 0x7000e93c84
    Site('bz_93c94',                     'code', 'f9400308 52800a41 910073e2 aa1603e0 d63f0100 b9401fe8 93407d01 90000008/9f00001f', 0),  # -> 0x7000e93c94
    Site('bz_93ca4',                     'code', 'd63f0100 b9401fe8 93407d01 90000008/9f00001f f9400108/ffc003ff 910083e0 f9400108 d63f0100 b940de68', 0),  # -> 0x7000e93ca4
    Site('bz_93cb4',                     'code', 'f946f908 910083e0 f9400108 d63f0100 b940de68 3100051f b9001fe8 54000001/ff00001f', 0),  # -> 0x7000e93cb4
    Site('bz_93cbc',                     'code', 'f9400108 d63f0100 b940de68 3100051f b9001fe8 54000001/ff00001f f9400308 52800b81', 0),  # -> 0x7000e93cbc
    Site('bz_93cc0',                     'code', 'd63f0100 b940de68 3100051f b9001fe8 54000001/ff00001f f9400308 52800b81 910073e2', 0),  # -> 0x7000e93cc0
    Site('bz_93cc4',                     'code', 'b940de68 3100051f b9001fe8 54000001/ff00001f f9400308 52800b81 910073e2 aa1603e0', 0),  # -> 0x7000e93cc4
    Site('bz_93cd4',                     'code', 'f9400308 52800b81 910073e2 aa1603e0 d63f0100 b9401fe8 93407d01 90000008/9f00001f', 0),  # -> 0x7000e93cd4
    Site('bz_93ce4',                     'code', 'd63f0100 b9401fe8 93407d01 90000008/9f00001f f9400108/ffc003ff 910083e0 f9400108 d63f0100 90000008/9f00001f', 0),  # -> 0x7000e93ce4
    Site('bz_93cf4',                     'code', 'f9470108 910083e0 f9400108 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108', 0),  # -> 0x7000e93cf4
    Site('bz_93cfc',                     'code', 'f9400108 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100 f9400288', 0),  # -> 0x7000e93cfc
    Site('bz_93d00',                     'code', 'd63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100 f9400288 aa0003f7', 0),  # -> 0x7000e93d00
    Site('bz_93d0c',                     'code', 'f9470508 f9400108 d63f0100 f9400288 aa0003f7 aa1403e0 aa1703e1 52820002', 0),  # -> 0x7000e93d0c
    Site('bz_93d10',                     'code', 'f9400108 d63f0100 f9400288 aa0003f7 aa1403e0 aa1703e1 52820002 f9401908', 0),  # -> 0x7000e93d10
    Site('bz_93d14',                     'code', 'd63f0100 f9400288 aa0003f7 aa1403e0 aa1703e1 52820002 f9401908 d63f0100', 0),  # -> 0x7000e93d14
    Site('bz_93d18',                     'code', 'f9400288 aa0003f7 aa1403e0 aa1703e1 52820002 f9401908 d63f0100 90000008/9f00001f', 0),  # -> 0x7000e93d18
    Site('bz_93d2c',                     'code', 'f9401908 d63f0100 90000008/9f00001f aa0003e1 f9400108/ffc003ff 910083e0 aa1703e2 f9400108', 0),  # -> 0x7000e93d2c
    Site('bz_93d30',                     'code', 'd63f0100 90000008/9f00001f aa0003e1 f9400108/ffc003ff 910083e0 aa1703e2 f9400108 d63f0100', 0),  # -> 0x7000e93d30
    Site('bz_93d3c',                     'code', 'f9470908 910083e0 aa1703e2 f9400108 d63f0100 52840000 aa1403e1 52800102', 0),  # -> 0x7000e93d3c
    Site('bz_93d48',                     'code', 'f9400108 d63f0100 52840000 aa1403e1 52800102 94000000/fc000000 f900ce60 90000008/9f00001f', 0),  # -> 0x7000e93d48
    Site('bz_93d4c',                     'code', 'd63f0100 52840000 aa1403e1 52800102 94000000/fc000000 f900ce60 90000008/9f00001f 910083e1', 0),  # -> 0x7000e93d4c
    Site('bz_93d5c',                     'code', '94000000/fc000000 f900ce60 90000008/9f00001f 910083e1 f9400108/ffc003ff f9400108 d63f0100 f9400340', 0),  # -> 0x7000e93d5c
    Site('bz_93d60',                     'code', 'f900ce60 90000008/9f00001f 910083e1 f9400108/ffc003ff f9400108 d63f0100 f9400340 f940ce61', 0),  # -> 0x7000e93d60
    Site('bz_93d6c',                     'code', 'f9473908 f9400108 d63f0100 f9400340 f940ce61 94000000/fc000000 52801900 aa1403e1', 0),  # -> 0x7000e93d6c
    Site('bz_93d70',                     'code', 'f9400108 d63f0100 f9400340 f940ce61 94000000/fc000000 52801900 aa1403e1 52800102', 0),  # -> 0x7000e93d70
    Site('bz_93d74',                     'code', 'd63f0100 f9400340 f940ce61 94000000/fc000000 52801900 aa1403e1 52800102 94000000/fc000000', 0),  # -> 0x7000e93d74
    Site('bz_93d78',                     'code', 'f9400340 f940ce61 94000000/fc000000 52801900 aa1403e1 52800102 94000000/fc000000 aa0003f7', 0),  # -> 0x7000e93d78
    Site('bz_93d7c',                     'code', 'f940ce61 94000000/fc000000 52801900 aa1403e1 52800102 94000000/fc000000 aa0003f7 94000000/fc000000', 0),  # -> 0x7000e93d7c
    Site('bz_93d80',                     'code', '94000000/fc000000 52801900 aa1403e1 52800102 94000000/fc000000 aa0003f7 94000000/fc000000 f940da61', 0),  # -> 0x7000e93d80
    Site('bz_93d90',                     'code', '94000000/fc000000 aa0003f7 94000000/fc000000 f940da61 910083e0 f9009a77 94000000/fc000000 f9409a68', 0),  # -> 0x7000e93d90
    Site('bz_93d9c',                     'code', 'f940da61 910083e0 f9009a77 94000000/fc000000 f9409a68 f94013e9 f9004d09 f9409a60', 0),  # -> 0x7000e93d9c
    Site('bz_93da4',                     'code', 'f9009a77 94000000/fc000000 f9409a68 f94013e9 f9004d09 f9409a60 b940a261 94000000/fc000000', 0),  # -> 0x7000e93da4
    Site('bz_93da8',                     'code', '94000000/fc000000 f9409a68 f94013e9 f9004d09 f9409a60 b940a261 94000000/fc000000 f9409a60', 0),  # -> 0x7000e93da8
    Site('bz_93dac',                     'code', 'f9409a68 f94013e9 f9004d09 f9409a60 b940a261 94000000/fc000000 f9409a60 3942f661', 0),  # -> 0x7000e93dac
    Site('bz_93db4',                     'code', 'f9004d09 f9409a60 b940a261 94000000/fc000000 f9409a60 3942f661 94000000/fc000000 2d568660', 0),  # -> 0x7000e93db4
    Site('bz_93db8',                     'code', 'f9409a60 b940a261 94000000/fc000000 f9409a60 3942f661 94000000/fc000000 2d568660 aa1403e1', 0),  # -> 0x7000e93db8
    Site('bz_93dbc',                     'code', 'b940a261 94000000/fc000000 f9409a60 3942f661 94000000/fc000000 2d568660 aa1403e1 f9409a60', 0),  # -> 0x7000e93dbc
    Site('bz_93dc0',                     'code', '94000000/fc000000 f9409a60 3942f661 94000000/fc000000 2d568660 aa1403e1 f9409a60 7e21d821', 0),  # -> 0x7000e93dc0
    Site('bz_93dc4',                     'code', 'f9409a60 3942f661 94000000/fc000000 2d568660 aa1403e1 f9409a60 7e21d821 f9400008', 0),  # -> 0x7000e93dc4
    Site('bz_93dc8',                     'code', '3942f661 94000000/fc000000 2d568660 aa1403e1 f9409a60 7e21d821 f9400008 7e21d800', 0),  # -> 0x7000e93dc8
    Site('bz_93dcc',                     'code', '94000000/fc000000 2d568660 aa1403e1 f9409a60 7e21d821 f9400008 7e21d800 2d010400', 0),  # -> 0x7000e93dcc
    Site('bz_93dd0',                     'code', '2d568660 aa1403e1 f9409a60 7e21d821 f9400008 7e21d800 2d010400 f9400908', 0),  # -> 0x7000e93dd0
    Site('bz_93dd8',                     'code', 'f9409a60 7e21d821 f9400008 7e21d800 2d010400 f9400908 d63f0100 b940a268', 0),  # -> 0x7000e93dd8
    Site('bz_93de0',                     'code', 'f9400008 7e21d800 2d010400 f9400908 d63f0100 b940a268 34000008/ff00001f 1e230100', 0),  # -> 0x7000e93de0
    Site('bz_93de8',                     'code', '2d010400 f9400908 d63f0100 b940a268 34000008/ff00001f 1e230100 90000008/9f00001f bd400101/ffc003ff', 0),  # -> 0x7000e93de8
    Site('bz_93dec',                     'code', 'f9400908 d63f0100 b940a268 34000008/ff00001f 1e230100 90000008/9f00001f bd400101/ffc003ff 52a84e08', 0),  # -> 0x7000e93dec
    Site('bz_93df0',                     'code', 'd63f0100 b940a268 34000008/ff00001f 1e230100 90000008/9f00001f bd400101/ffc003ff 52a84e08 1e212800', 0),  # -> 0x7000e93df0
    Site('bz_93df4',                     'code', 'b940a268 34000008/ff00001f 1e230100 90000008/9f00001f bd400101/ffc003ff 52a84e08 1e212800 1e270101', 0),  # -> 0x7000e93df4
    Site('bz_93e04',                     'code', 'bd46f501 52a84e08 1e212800 1e270101 90000008/9f00001f f9400108/ffc003ff 1e211800 f9400108', 0),  # -> 0x7000e93e04
    Site('bz_93e18',                     'code', 'f9410508 1e211800 f9400108 9e220101 1e210800 9e380008 f9009668 f9400340', 0),  # -> 0x7000e93e18
    Site('bz_93e20',                     'code', 'f9400108 9e220101 1e210800 9e380008 f9009668 f9400340 f9409a61 94000000/fc000000', 0),  # -> 0x7000e93e20
    Site('bz_93e30',                     'code', 'f9009668 f9400340 f9409a61 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff 08dffd08 90000019/9f00001f', 0),  # -> 0x7000e93e30
    Site('bz_93e34',                     'code', 'f9400340 f9409a61 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff 08dffd08 90000019/9f00001f 36000008/fff8001f', 0),  # -> 0x7000e93e34
    Site('bz_93e38',                     'code', 'f9409a61 94000000/fc000000 90000008/9f00001f 91000108/ffc003ff 08dffd08 90000019/9f00001f 36000008/fff8001f f9400348', 0),  # -> 0x7000e93e38
    Site('bz_93e3c',                     'code', '94000000/fc000000 90000008/9f00001f 91000108/ffc003ff 08dffd08 90000019/9f00001f 36000008/fff8001f f9400348 52801400', 0),  # -> 0x7000e93e3c
    Site('bz_93e48',                     'code', '08dffd08 90000019/9f00001f 36000008/fff8001f f9400348 52801400 aa1403e1 52800102 f9401917', 0),  # -> 0x7000e93e48
    Site('bz_93e54',                     'code', 'f9400348 52801400 aa1403e1 52800102 f9401917 94000000/fc000000 f900ae60 90000008/9f00001f', 0),  # -> 0x7000e93e54
    Site('bz_93e64',                     'code', 'f9401917 94000000/fc000000 f900ae60 90000008/9f00001f aa1703e1 f9400108/ffc003ff f9400108 d63f0100', 0),  # -> 0x7000e93e64
    Site('bz_93e68',                     'code', '94000000/fc000000 f900ae60 90000008/9f00001f aa1703e1 f9400108/ffc003ff f9400108 d63f0100 52802000', 0),  # -> 0x7000e93e68
    Site('bz_93e6c',                     'code', 'f900ae60 90000008/9f00001f aa1703e1 f9400108/ffc003ff f9400108 d63f0100 52802000 aa1403e1', 0),  # -> 0x7000e93e6c
    Site('bz_93e78',                     'code', 'f943d508 f9400108 d63f0100 52802000 aa1403e1 52800102 94000000/fc000000 f900a660', 0),  # -> 0x7000e93e78
    Site('bz_93e7c',                     'code', 'f9400108 d63f0100 52802000 aa1403e1 52800102 94000000/fc000000 f900a660 9000001b/9f00001f', 0),  # -> 0x7000e93e7c
    Site('bz_93e80',                     'code', 'd63f0100 52802000 aa1403e1 52800102 94000000/fc000000 f900a660 9000001b/9f00001f 910083e0', 0),  # -> 0x7000e93e80
    Site('bz_93e90',                     'code', '94000000/fc000000 f900a660 9000001b/9f00001f 910083e0 f940037b/ffc003ff f9400368 d63f0100 90000008/9f00001f', 0),  # -> 0x7000e93e90
    Site('bz_93e94',                     'code', 'f900a660 9000001b/9f00001f 910083e0 f940037b/ffc003ff f9400368 d63f0100 90000008/9f00001f 910083e0', 0),  # -> 0x7000e93e94
    Site('bz_93ea0',                     'code', 'f947d77b f9400368 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff aa1703e1 f9400108', 0),  # -> 0x7000e93ea0
    Site('bz_93ea4',                     'code', 'f9400368 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff aa1703e1 f9400108 d63f0100', 0),  # -> 0x7000e93ea4
    Site('bz_93ea8',                     'code', 'd63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff aa1703e1 f9400108 d63f0100 9000001c/9f00001f', 0),  # -> 0x7000e93ea8
    Site('bz_93eb4',                     'code', 'f947d108 aa1703e1 f9400108 d63f0100 9000001c/9f00001f 52800241 f940039c/ffc003ff 910083e0', 0),  # -> 0x7000e93eb4
    Site('bz_93ebc',                     'code', 'f9400108 d63f0100 9000001c/9f00001f 52800241 f940039c/ffc003ff 910083e0 f9400388 d63f0100', 0),  # -> 0x7000e93ebc
    Site('bz_93ec0',                     'code', 'd63f0100 9000001c/9f00001f 52800241 f940039c/ffc003ff 910083e0 f9400388 d63f0100 f9460b20', 0),  # -> 0x7000e93ec0
    Site('bz_93ecc',                     'code', 'f947df9c 910083e0 f9400388 d63f0100 f9460b20 aa1403e1 52820002 94000000/fc000000', 0),  # -> 0x7000e93ecc
    Site('bz_93ed4',                     'code', 'f9400388 d63f0100 f9460b20 aa1403e1 52820002 94000000/fc000000 90000008/9f00001f f9460b22', 0),  # -> 0x7000e93ed4
    Site('bz_93ed8',                     'code', 'd63f0100 f9460b20 aa1403e1 52820002 94000000/fc000000 90000008/9f00001f f9460b22 aa0003e1', 0),  # -> 0x7000e93ed8
    Site('bz_93edc',                     'code', 'f9460b20 aa1403e1 52820002 94000000/fc000000 90000008/9f00001f f9460b22 aa0003e1 f9400108/ffc003ff', 0),  # -> 0x7000e93edc
    Site('bz_93ee8',                     'code', '94000000/fc000000 90000008/9f00001f f9460b22 aa0003e1 f9400108/ffc003ff 910083e0 f9400108 d63f0100', 0),  # -> 0x7000e93ee8
    Site('bz_93ef0',                     'code', 'f9460b22 aa0003e1 f947d908 910083e0 f9400108 d63f0100 90000019/9f00001f f940a660', 0),  # -> 0x7000e93ef0
    Site('bz_93ef8',                     'code', 'f947d908 910083e0 f9400108 d63f0100 90000019/9f00001f f940a660 910083e1 f9400339/ffc003ff', 0),  # -> 0x7000e93ef8
    Site('bz_93f00',                     'code', 'f9400108 d63f0100 90000019/9f00001f f940a660 910083e1 f9400339/ffc003ff f9400328 d63f0100', 0),  # -> 0x7000e93f00
    Site('bz_93f04',                     'code', 'd63f0100 90000019/9f00001f f940a660 910083e1 f9400339/ffc003ff f9400328 d63f0100 f9400308', 0),  # -> 0x7000e93f04
    Site('bz_93f0c',                     'code', 'f940a660 910083e1 f947f339 f9400328 d63f0100 f9400308 52800281 910073e2', 0),  # -> 0x7000e93f0c
    Site('bz_93f14',                     'code', 'f947f339 f9400328 d63f0100 f9400308 52800281 910073e2 aa1703e0 b9001fff', 0),  # -> 0x7000e93f14
    Site('bz_93f18',                     'code', 'f9400328 d63f0100 f9400308 52800281 910073e2 aa1703e0 b9001fff d63f0100', 0),  # -> 0x7000e93f18
    Site('bz_93f1c',                     'code', 'd63f0100 f9400308 52800281 910073e2 aa1703e0 b9001fff d63f0100 f9400288', 0),  # -> 0x7000e93f1c
    Site('bz_93f20',                     'code', 'f9400308 52800281 910073e2 aa1703e0 b9001fff d63f0100 f9400288 aa1403e0', 0),  # -> 0x7000e93f20
    Site('bz_93f34',                     'code', 'd63f0100 f9400288 aa1403e0 b940c661 b9401fe2 f9401908 d63f0100 f900aa60', 0),  # -> 0x7000e93f34
    Site('bz_93f38',                     'code', 'f9400288 aa1403e0 b940c661 b9401fe2 f9401908 d63f0100 f900aa60 90000008/9f00001f', 0),  # -> 0x7000e93f38
    Site('bz_93f40',                     'code', 'b940c661 b9401fe2 f9401908 d63f0100 f900aa60 90000008/9f00001f f940ae60 f9400108/ffc003ff', 0),  # -> 0x7000e93f40
    Site('bz_93f48',                     'code', 'f9401908 d63f0100 f900aa60 90000008/9f00001f f940ae60 f9400108/ffc003ff d503201f 10000001/9f00001f', 0),  # -> 0x7000e93f48
    Site('bz_93f4c',                     'code', 'd63f0100 f900aa60 90000008/9f00001f f940ae60 f9400108/ffc003ff d503201f 10000001/9f00001f f9400108', 0),  # -> 0x7000e93f4c
    Site('bz_93f50',                     'code', 'f900aa60 90000008/9f00001f f940ae60 f9400108/ffc003ff d503201f 10000001/9f00001f f9400108 d63f0100', 0),  # -> 0x7000e93f50
    Site('bz_93f58',                     'code', 'f940ae60 f943e108 d503201f 10000001/9f00001f f9400108 d63f0100 90000008/9f00001f f940ae60', 0),  # -> 0x7000e93f58
    Site('bz_93f5c',                     'code', 'f943e108 d503201f 10000001/9f00001f f9400108 d63f0100 90000008/9f00001f f940ae60 aa0003e1', 0),  # -> 0x7000e93f5c
    Site('bz_93f68',                     'code', 'f9400108 d63f0100 90000008/9f00001f f940ae60 aa0003e1 f9400108/ffc003ff f9400108 d63f0100', 0),  # -> 0x7000e93f68
    Site('bz_93f6c',                     'code', 'd63f0100 90000008/9f00001f f940ae60 aa0003e1 f9400108/ffc003ff f9400108 d63f0100 f9400340', 0),  # -> 0x7000e93f6c
    Site('bz_93f74',                     'code', 'f940ae60 aa0003e1 f943e508 f9400108 d63f0100 f9400340 f940ae61 94000000/fc000000', 0),  # -> 0x7000e93f74
    Site('bz_93f7c',                     'code', 'f943e508 f9400108 d63f0100 f9400340 f940ae61 94000000/fc000000 f9400308 52800321', 0),  # -> 0x7000e93f7c
    Site('bz_93f80',                     'code', 'f9400108 d63f0100 f9400340 f940ae61 94000000/fc000000 f9400308 52800321 910073e2', 0),  # -> 0x7000e93f80
    Site('bz_93f84',                     'code', 'd63f0100 f9400340 f940ae61 94000000/fc000000 f9400308 52800321 910073e2 aa1603e0', 0),  # -> 0x7000e93f84
    Site('bz_93f88',                     'code', 'f9400340 f940ae61 94000000/fc000000 f9400308 52800321 910073e2 aa1603e0 d63f0100', 0),  # -> 0x7000e93f88
    Site('bz_93f8c',                     'code', 'f940ae61 94000000/fc000000 f9400308 52800321 910073e2 aa1603e0 d63f0100 f9400308', 0),  # -> 0x7000e93f8c
    Site('bz_93f90',                     'code', '94000000/fc000000 f9400308 52800321 910073e2 aa1603e0 d63f0100 f9400308 52800341', 0),  # -> 0x7000e93f90
    Site('bz_93f94',                     'code', 'f9400308 52800321 910073e2 aa1603e0 d63f0100 f9400308 52800341 910063e2', 0),  # -> 0x7000e93f94
    Site('bz_93fa4',                     'code', 'd63f0100 f9400308 52800341 910063e2 aa1603e0 d63f0100 f9400308 910053e2', 0),  # -> 0x7000e93fa4
    Site('bz_93fa8',                     'code', 'f9400308 52800341 910063e2 aa1603e0 d63f0100 f9400308 910053e2 aa1603e0', 0),  # -> 0x7000e93fa8
    Site('bz_93fb8',                     'code', 'd63f0100 f9400308 910053e2 aa1603e0 52800301 d63f0100 b940ca68 52802000', 0),  # -> 0x7000e93fb8
    Site('bz_93fbc',                     'code', 'f9400308 910053e2 aa1603e0 52800301 d63f0100 b940ca68 52802000 aa1403e1', 0),  # -> 0x7000e93fbc
    Site('bz_93fcc',                     'code', 'd63f0100 b940ca68 52802000 aa1403e1 b94017e9 52800102 b9401fea 1b082928', 0),  # -> 0x7000e93fcc
    Site('bz_93fd0',                     'code', 'b940ca68 52802000 aa1403e1 b94017e9 52800102 b9401fea 1b082928 51000508', 0),  # -> 0x7000e93fd0
    Site('bz_94018',                     'code', 'b9017a68 94000000/fc000000 f9400368 f900ba60 910083e0 d63f0100 f9400348 910083e0', 0),  # -> 0x7000e94018
    Site('bz_9401c',                     'code', '94000000/fc000000 f9400368 f900ba60 910083e0 d63f0100 f9400348 910083e0 f9401901', 0),  # -> 0x7000e9401c
    Site('bz_94020',                     'code', 'f9400368 f900ba60 910083e0 d63f0100 f9400348 910083e0 f9401901 90000008/9f00001f', 0),  # -> 0x7000e94020
    Site('bz_94024',                     'code', 'f900ba60 910083e0 d63f0100 f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff', 0),  # -> 0x7000e94024
    Site('bz_9402c',                     'code', 'd63f0100 f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 f9400388', 0),  # -> 0x7000e9402c
    Site('bz_94030',                     'code', 'f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 f9400388', 0),  # -> 0x7000e94030
    Site('bz_94038',                     'code', 'f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 f9400388 52800421 910083e0', 0),  # -> 0x7000e94038
    Site('bz_94040',                     'code', 'f947d108 f9400108 d63f0100 f9400388 52800421 910083e0 d63f0100 b9417a60', 0),  # -> 0x7000e94040
    Site('bz_94044',                     'code', 'f9400108 d63f0100 f9400388 52800421 910083e0 d63f0100 b9417a60 aa1403e1', 0),  # -> 0x7000e94044
    Site('bz_94048',                     'code', 'd63f0100 f9400388 52800421 910083e0 d63f0100 b9417a60 aa1403e1 52820002', 0),  # -> 0x7000e94048
    Site('bz_9404c',                     'code', 'f9400388 52800421 910083e0 d63f0100 b9417a60 aa1403e1 52820002 94000000/fc000000', 0),  # -> 0x7000e9404c
    Site('bz_94058',                     'code', 'd63f0100 b9417a60 aa1403e1 52820002 94000000/fc000000 90000008/9f00001f b9417a62 aa0003e1', 0),  # -> 0x7000e94058
    Site('bz_9405c',                     'code', 'b9417a60 aa1403e1 52820002 94000000/fc000000 90000008/9f00001f b9417a62 aa0003e1 f9400108/ffc003ff', 0),  # -> 0x7000e9405c
    Site('bz_94068',                     'code', '94000000/fc000000 90000008/9f00001f b9417a62 aa0003e1 f9400108/ffc003ff 910083e0 f9400108 d63f0100', 0),  # -> 0x7000e94068
    Site('bz_94070',                     'code', 'b9417a62 aa0003e1 f947d908 910083e0 f9400108 d63f0100 f940ba60 910083e1', 0),  # -> 0x7000e94070
    Site('bz_94078',                     'code', 'f947d908 910083e0 f9400108 d63f0100 f940ba60 910083e1 f9400328 d63f0100', 0),  # -> 0x7000e94078
    Site('bz_94080',                     'code', 'f9400108 d63f0100 f940ba60 910083e1 f9400328 d63f0100 f9400348 910083e0', 0),  # -> 0x7000e94080
    Site('bz_94084',                     'code', 'd63f0100 f940ba60 910083e1 f9400328 d63f0100 f9400348 910083e0 f9401901', 0),  # -> 0x7000e94084
    Site('bz_94088',                     'code', 'f940ba60 910083e1 f9400328 d63f0100 f9400348 910083e0 f9401901 90000008/9f00001f', 0),  # -> 0x7000e94088
    Site('bz_94090',                     'code', 'f9400328 d63f0100 f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff f9400108', 0),  # -> 0x7000e94090
    Site('bz_94094',                     'code', 'd63f0100 f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f', 0),  # -> 0x7000e94094
    Site('bz_94098',                     'code', 'f9400348 910083e0 f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f', 0),  # -> 0x7000e94098
    Site('bz_940a0',                     'code', 'f9401901 90000008/9f00001f f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff', 0),  # -> 0x7000e940a0
    Site('bz_940a8',                     'code', 'f9405508 f9400108 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100', 0),  # -> 0x7000e940a8
    Site('bz_940ac',                     'code', 'f9400108 d63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f f940a661', 0),  # -> 0x7000e940ac
    Site('bz_940b0',                     'code', 'd63f0100 90000008/9f00001f 910083e0 f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f f940a661', 0),  # -> 0x7000e940b0
    Site('bz_940bc',                     'code', 'f9405908 f9400108 d63f0100 90000008/9f00001f f940a661 910083e0 b940c262 52800403', 0),  # -> 0x7000e940bc
    Site('bz_940c0',                     'code', 'f9400108 d63f0100 90000008/9f00001f f940a661 910083e0 b940c262 52800403 52800417', 0),  # -> 0x7000e940c0
    Site('bz_940c4',                     'code', 'd63f0100 90000008/9f00001f f940a661 910083e0 b940c262 52800403 52800417 f9400108/ffc003ff', 0),  # -> 0x7000e940c4
    Site('bz_940cc',                     'code', 'f940a661 910083e0 b940c262 52800403 52800417 f9405d08 f9400108 d63f0100', 0),  # -> 0x7000e940cc
    Site('bz_940d4',                     'code', 'b940c262 52800403 52800417 f9405d08 f9400108 d63f0100 52800600 aa1403e1', 0),  # -> 0x7000e940d4
    Site('bz_940e0',                     'code', 'f9405d08 f9400108 d63f0100 52800600 aa1403e1 52800102 94000000/fc000000 f900b260', 0),  # -> 0x7000e940e0
    Site('bz_940e4',                     'code', 'f9400108 d63f0100 52800600 aa1403e1 52800102 94000000/fc000000 f900b260 90000008/9f00001f', 0),  # -> 0x7000e940e4
    Site('bz_940e8',                     'code', 'd63f0100 52800600 aa1403e1 52800102 94000000/fc000000 f900b260 90000008/9f00001f 910083e1', 0),  # -> 0x7000e940e8
    Site('bz_940f8',                     'code', '94000000/fc000000 f900b260 90000008/9f00001f 910083e1 f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f', 0),  # -> 0x7000e940f8
    Site('bz_940fc',                     'code', 'f900b260 90000008/9f00001f 910083e1 f9400108/ffc003ff f9400108 d63f0100 90000008/9f00001f f940b260', 0),  # -> 0x7000e940fc
    Site('bz_94108',                     'code', 'f9407108 f9400108 d63f0100 90000008/9f00001f f940b260 f9400108/ffc003ff f9400108 d63f0100', 0),  # -> 0x7000e94108
    Site('bz_9410c',                     'code', 'f9400108 d63f0100 90000008/9f00001f f940b260 f9400108/ffc003ff f9400108 d63f0100 f900b660', 0),  # -> 0x7000e9410c
    Site('bz_94110',                     'code', 'd63f0100 90000008/9f00001f f940b260 f9400108/ffc003ff f9400108 d63f0100 f900b660 52800800', 0),  # -> 0x7000e94110
    Site('bz_94118',                     'code', 'f940b260 f9407d08 f9400108 d63f0100 f900b660 52800800 aa1403e1 52800102', 0),  # -> 0x7000e94118
    Site('bz_9411c',                     'code', 'f9407d08 f9400108 d63f0100 f900b660 52800800 aa1403e1 52800102 94000000/fc000000', 0),  # -> 0x7000e9411c
    Site('bz_94120',                     'code', 'f9400108 d63f0100 f900b660 52800800 aa1403e1 52800102 94000000/fc000000 f900e260', 0),  # -> 0x7000e94120
    Site('bz_94124',                     'code', 'd63f0100 f900b660 52800800 aa1403e1 52800102 94000000/fc000000 f900e260 90000008/9f00001f', 0),  # -> 0x7000e94124
    Site('bz_94128',                     'code', 'f900b660 52800800 aa1403e1 52800102 94000000/fc000000 f900e260 90000008/9f00001f aa1603e1', 0),  # -> 0x7000e94128
    Site('bz_94138',                     'code', '94000000/fc000000 f900e260 90000008/9f00001f aa1603e1 f9400108/ffc003ff f9400108 d63f0100 3942f268', 0),  # -> 0x7000e94138
    Site('bz_9413c',                     'code', 'f900e260 90000008/9f00001f aa1603e1 f9400108/ffc003ff f9400108 d63f0100 3942f268 34000008/ff00001f', 0),  # -> 0x7000e9413c
    Site('bz_94148',                     'code', 'f9462108 f9400108 d63f0100 3942f268 34000008/ff00001f 29568e62 aa1403e0 aa1503e1', 0),  # -> 0x7000e94148
    Site('bz_9414c',                     'code', 'f9400108 d63f0100 3942f268 34000008/ff00001f 29568e62 aa1403e0 aa1503e1 94000000/fc000000', 0),  # -> 0x7000e9414c
    Site('bz_94150',                     'code', 'd63f0100 3942f268 34000008/ff00001f 29568e62 aa1403e0 aa1503e1 94000000/fc000000 f9008260', 0),  # -> 0x7000e94150
    Site('bz_94154',                     'code', '3942f268 34000008/ff00001f 29568e62 aa1403e0 aa1503e1 94000000/fc000000 f9008260 52802100', 0),  # -> 0x7000e94154
    Site('bz_9415c',                     'code', '29568e62 aa1403e0 aa1503e1 94000000/fc000000 f9008260 52802100 aa1403e1 52800102', 0),  # -> 0x7000e9415c
    Site('bz_94168',                     'code', '94000000/fc000000 f9008260 52802100 aa1403e1 52800102 94000000/fc000000 90000008/9f00001f aa0003f5', 0),  # -> 0x7000e94168
    Site('bz_9416c',                     'code', 'f9008260 52802100 aa1403e1 52800102 94000000/fc000000 90000008/9f00001f aa0003f5 f9400108/ffc003ff', 0),  # -> 0x7000e9416c
    Site('bz_9417c',                     'code', '94000000/fc000000 90000008/9f00001f aa0003f5 f9400108/ffc003ff 90000009/9f00001f 91000129/ffc003ff 52800400 aa1403e1 52800102 91004108', 0),  # -> 0x7000e9417c
    Site('bz_94188',                     'code', 'f9413108 90000009/9f00001f 91000129/ffc003ff 52800400 aa1403e1 52800102 91004108 a90227e8', 0),  # -> 0x7000e94188
    Site('bz_941a8',                     'code', '94000000/fc000000 d503201f 10000008/9f00001f aa0003f6 a9017c08 90000008/9f00001f 91000108/ffc003ff a9004c08', 0),  # -> 0x7000e941a8
    Site('bz_941b8',                     'code', 'a9017c08 90000008/9f00001f 91000108/ffc003ff a9004c08 b940ea60 94000000/fc000000 2a0003e4 910083e1', 0),  # -> 0x7000e941b8
    Site('bz_941c4',                     'code', 'a9004c08 b940ea60 94000000/fc000000 2a0003e4 910083e1 b90003f7 aa1503e0 aa1603e2', 0),  # -> 0x7000e941c4
    Site('bz_941c8',                     'code', 'b940ea60 94000000/fc000000 2a0003e4 910083e1 b90003f7 aa1503e0 aa1603e2 aa1403e3', 0),  # -> 0x7000e941c8
    Site('bz_941cc',                     'code', '94000000/fc000000 2a0003e4 910083e1 b90003f7 aa1503e0 aa1603e2 aa1403e3 2a1f03e5', 0),  # -> 0x7000e941cc
    Site('bz_941f4',                     'code', '94000000/fc000000 52800028 f900de75 910083e1 b90023e8 aa1503e0 b94023e9 1ac92108', 0),  # -> 0x7000e941f4
    Site('bz_941fc',                     'code', 'f900de75 910083e1 b90023e8 aa1503e0 b94023e9 1ac92108 b90023e8 94000000/fc000000', 0),  # -> 0x7000e941fc
    Site('bz_94218',                     'code', '94000000/fc000000 f940de60 f9400008 f9401908 d63f0100 a94b4ff4 a94a57f6 a9495ff8', 0),  # -> 0x7000e94218
    Site('bz_9421c',                     'code', 'f940de60 f9400008 f9401908 d63f0100 a94b4ff4 a94a57f6 a9495ff8 a94867fa', 0),  # -> 0x7000e9421c
    Site('bz_94220',                     'code', 'f9400008 f9401908 d63f0100 a94b4ff4 a94a57f6 a9495ff8 a94867fa a9476ffc', 0),  # -> 0x7000e94220
    Site('bz_94224',                     'code', 'f9401908 d63f0100 a94b4ff4 a94a57f6 a9495ff8 a94867fa a9476ffc a9467bfd', 0),  # -> 0x7000e94224
    Site('bz_94228',                     'code', 'd63f0100 a94b4ff4 a94a57f6 a9495ff8 a94867fa a9476ffc a9467bfd 910303ff d65f03c0 90000000/9f00001f', 0),  # -> 0x7000e94228
    Site('bz_94254',                     'code', '94000000/fc000000 34000000/ff00001f b940c268 90000000/9f00001f 91000000/ffc003ff 11008108 913ffd08 92745108', 0),  # -> 0x7000e94254
    Site('bz_9425c',                     'code', 'b940c268 90000000/9f00001f 91000000/ffc003ff 11008108 913ffd08 92745108 f9060b28 94000000/fc000000', 0),  # -> 0x7000e9425c
    Site('bz_94274',                     'code', 'f9060b28 94000000/fc000000 14000000/fc000000', 0),  # -> 0x7000e94274
    Site('bz_94278',                     'code', 'f9060b28 94000000/fc000000 14000000/fc000000', 1),  # -> 0x7000e94278
    Site('bz_939c8',                     'code', '94000000/fc000000 b940d261 34000301', 0),  # -> 0x7000e939c8
    Site('bz_93a08',                     'code', '94000000/fc000000 d503201f 10004500', 0),  # -> 0x7000e93a08
    Site('bz_93a30',                     'code', '94000000/fc000000 9106a260 941c3382', 0),  # -> 0x7000e93a30
    Site('bz_93be0',                     'code', '94000000/fc000000 b00076da aa1703e0', 0),  # -> 0x7000e93be0
    Site('bz_93d98',                     'code', '94000000/fc000000 f940da61 910083e0', 0),  # -> 0x7000e93d98
    Site('main_data', 'data', '', 0),
    Site('main_end', 'end', '', 0),
]

# Sites a version may lack, as a group: when one of them is neither found by its pattern nor listed in the version's
# KNOWN table, the whole group is left out (with its patches) instead of refusing the version. The mouse camera's
# sites go together: the stick input without the linear vertical part would square the mouse's (unclamped) motion.
# Without them the mouse turns the camera through the right stick, as before (runtime/hle/input.c); without the
# second group it turns it without the game's camera inversion options.
OPTIONAL_GROUPS = [
    OPT_TWO_SITES,
    ('lookat_update',),  # (the free camera: without it Home does nothing)
    ('gyro_scene_actor',),
    ('surf_contact', 'surf_boost_remove', 'surf_jump_request'),
    ('stale_actor_helper', 'stale_actor_target'),
    ('quick_menu_capture_alpha',),
    ('kf_angle',),
    ('yaz0_stream', 'yaz0_stream_ret'),
    ('pc_map_focus', 'pc_map_focus_target', 'pc_map_focus_now'),
    ('pc_button_group',),
    ('pc_cursor_manager', 'pc_cursor_activate', 'pc_pane_bounds'),
    ('cam_stick', 'cam_pitch_chase', 'cam_pitch_surf', 'cam_pitch_wakeboard', 'cam_pitch_aim', 'cam_pitch_item'),
    ('cam_reverse_x', 'cam_reverse_y'),
    ('traverse_scale', 'traverse_scale_default'),
    ('grass_range', 'grass_fade_blades', 'grass_fade_quads'),
    ('grass_blade_slots', 'grass_blade_cap_a', 'grass_blade_cap_b', 'grass_blade_cap_c', 'grass_blade_cap_c_max',
     'grass_blade_lateral_near',
     'grass_blade_lateral_far'),
    ('tree_ranges',),
    ('act_hold', 'act_trig', 'act_masks'),
    ('pouch_remove_arrows',),
    ('no_wear_store',),
    ('no_wear_hit', 'no_wear_ret'),
    ('link_life_store', 'link_life_tick'),
    ('stamina_store',),
    ('debug_cursor_pool_guard', 'debug_cursor_pane_guard'),  # (the boot crash, both its faults: without them a
                                   # machine where the game leaves the debug cursor's pool slot empty faults on the
                                   # pool object's vtable before the first frame — and past that guard, on the
                                   # pane the skipped setup never made)
    ('debug_menu_key_guard', 'debug_menu_len_guard', 'debug_menu_page_guard', 'debug_menu_cand_guard',
     'debug_menu_path_guard', 'debug_menu_hash_guard'),  # (one step past the cursor: the debug menu's page/item
                                   # functions, all entered through their vtable, look a page up by its key's
                                   # name — 0 where the menu's init left it empty; every dereference of that
                                   # name guarded, each to its function's own empty-name path)
    ('shader_queue_guard',),  # (the title screen's first shader link, on a machine where the shader holder's
                                   # queue member stayed empty: guard its first load, its empty-queue exit runs)
    ('debug_menu_reg_288_guard', 'debug_menu_reg_2b8_guard', 'debug_menu_reg_copy_guard',
     'debug_menu_reg_288c_guard', 'debug_menu_reg_288f_guard', 'debug_menu_reg_2b8f_guard',
     'debug_menu_reg_298_guard', 'debug_menu_reg_298c_guard', 'debug_menu_reg_298f_guard',
     'debug_menu_reg_2a8_guard', 'debug_menu_reg_2a8c_guard', 'debug_menu_reg_2a8f_guard',
     'debug_menu_reg_2c8_guard', 'debug_menu_reg_2c8c_guard', 'debug_menu_reg_2c8f_guard',
     'debug_menu_reg_278_guard', 'debug_menu_reg_278c_guard', 'debug_menu_reg_278f_guard'),  # (the title's
                                   # debug-menu entry registration and the whole sibling cluster over the table
                                   # the half-initialized menu never built: entry guards, nothing to register)
    ('uinj_db_guard',),  # (the title's actor creation, whose uinj actor-database member the never-completed
                                   # title init never built: guard the member load, hand out a zeroed default record)
    ('light_rig_flag_guard',),  # (run40's fault: the zeroed record's null light-rig back-pointer leaves the param
                                   # builder's entry loop on an unmapped 0x53658 base -- skip the entries it lacks)
    ('param_ctor_ctx_guard',),  # (run41's fault: the param-object constructors register their objects into the
                                   # actor context's entry list -- with the context never built, x3 is null: skip
                                   # the construction, its only purpose was the registration into that list)
    ('actor_param_ctx_guard',),  # (run42's fault: the message-parameter builder runs entirely on the never-built
                                   # actor context -- its descriptor and the message catalog it copies from are
                                   # both absent: return from the builder, its caller ignores the result)
    ('param_list_xfer_guard',),  # (run45's fault: the param transfer walks record 0 of the vector the guarded
                                   # ctor left never built -- a null vector has no object to transfer: return,
                                   # the sole caller ignores the result)
    ('param_subsys_guard',),  # (run46's fault: the title actor init's default-param block writes through the
                                 # subsystem field the never-built init left 0 -- skip the whole block on null,
                                 # its own count<1 merge label where nothing is left to initialize)
    ('gfx_system_list_guard',),  # (run47's fault: the gfx::System notify reads its actor-list count through the
                                    # base the never-built init left 0 -- skip the notify on null, the guest's
                                    # own busy-lock return label where nobody is notified)
    ('actor_reg_field_guard',  # (run48's fault family: the actor init's tail writes/looks through the subsystem
     'actor_list_reg_guard_1',   # fields the never-built init left 0 -- the vtable registration through
     'actor_list_reg_guard_2',   # [x20+0x5cd8] (the fault at 0x100), the two registry lookups through
     'actor_subsys_ref_guard'),  # [x20+0x55e8] (their guest -1 branches skip the entry read), and the vtable
                                 # consumer through [x20+0x55f0] (skip to its after-call merge)
    ('subsys_consume_guard',),  # (run49's fault: the subsystem consumer reads its flag word through the null
                                 # getter result for the never-built field [x20+0x51d8] -- return from its
                                 # entry, its caller ignores the result, nothing gets registered)
    ('registry_lookup_guard',),  # (run50's fault: the registry lookup reads its entry count through the null
                                 # registry the never-built init left in field [x2+0x55e8] -- return the
                                 # guest's own empty-registry -1, every caller's not-found branch follows)
    ('record_subsys_init_guard',),  # (run51's fault: the record subsystem init drives the registry base the
                                    # never-built lookup left null in the block's own field [x25+0x5d0] --
                                    # return from its entry, the sole caller ignores the result, the whole
                                    # record init is what the null registry means to skip)
    ('subsys_list_init_guard',   # (run52's fault family: the actor-list subsystem's registrar stores its
     'subsys_list_reg_guard'),    # resume-callback through the list base the never-built init left null in
                                  # the real block's field [x0+0x58] -- return from both its entry and the
                                  # sibling registration step's entry, both callers ignore the results)
    ('subsys_record_mode_guard',  # (run53's fault family: the boot's first function past the guarded tail
     'subsys_param_array_guard'), # drives the subsystem record the lookup thunk found (a real block) through
                                  # the fields the never-built init left null -- skip the mode store through
                                  # the null record field, and its param array loop to its own count skip)
    ('subsys_entry_lookup_guard',),  # (run54's fault: the name-entry lookup reads its bound pair through the
                                     # table base the never-built init left null in the real block's field
                                     # [x0+0x20] -- return the guest's own not-found -1 from its entry, the
                                     # sole caller's tbnz routes it to its own -1, nothing to find)
    ('subsys_index_get_guard_1',    # (run55's fault family: the init step's indexed getEntry lookups read
     'subsys_index_get_guard_2',    # their bound pair through the same null table base [x0+0x20] and their
     'subsys_index_get_guard_3'),   # entries through the null [x0+0x30] -- answer the guest's own null
                                    # entry from each entry, the callers' cbnz/cbz/csel handle it)
    ('subsys_entry_name_guard',    # (run56's fault family: the last entry lookups' list field [x+0x5c80]
     'subsys_entry_pick_guard'),    # the never-built init left null -- skip the first entry load and the
                                    # indexed pick to each function's own unknown-name string return, the
                                    # answer a null list already is)
    ('dir_entry_accessor_guard',   # (run57's fault family: the save-dir step's iterator accessor probes
     'dir_entry_accessor_guard_2',  #  the tag 0x2002 at three handle offsets and reads the value dword
     'dir_entry_accessor_guard_3',  #  after it -- its csel leaves 0 when no probe matches, our machine's
     'dir_entry_accessor_guard_4',  #  never-built fs state leaves the handle untagged; answer the neutral
     'dir_entry_accessor_guard_5'), #  0 the callers use as an offset: entry at the buffer head. run58
                                    #  extended the family to its four untagged-handle siblings: the tag
                                    #  0x2001 pair (tails +4/+8 -- the run58 fault) and the tag 0x2000
                                    #  pair (tails +4/+8), all answering the same neutral offset 0)
    ('fs_read_zero_guard',          # (run60's fault family: the accessor answer 0 sized the step's
     'fs_read_null_buffer_guard'),  #  allocation to nothing -- a null pool buffer -- and the SDK's
                                    #  ReadFile R_UNLESS(buffer) answered fs ResultNullptrArgument
                                    #  (0x2f5e02) which sead's X macro aborted: the wrapper answers 0
                                    #  bytes read, success, on a zero-size request, and run61 extended
                                    #  it to the impl's own null buffer field [x0+8] -- what the
                                    #  callers' cmp answered, requested already treat as nothing-read)
    ('fs_state_accessor_guard',     # (run63's fault family: the step f_7000f07ee0 passed its
     'fs_state_accessor_guard_2',   #  never-built fs state (dump x21 = 0) into the sead accessor
     'fs_state_query_guard',        #  chain and the thunk's ldr x0, [x0, #8] faulted at 0x8 -- the
     'fs_state_query_guard_2'),     #  sweep's four dereference sites all answer the established
                                    #  neutral 0 at the entry (tag-4 handle index 0, query flag miss)
    ('framework_swap_guard',        # (run64's fault family: physics/system init ran on the sead
     'physics_cfg_entry_guard'),    #  framework's global never built -- the swap helper's table and
                                    #  the config step's array base are both off the guest map (the
                                    #  dump's 0x6e0bebe98 and 0x7af992ff12): the helper answers its
                                    #  own "nothing converted" early return, the step its count-0
                                    #  tail -- the parsed flag still gets set, the entry list runs)
    ('load_balancer_entry_guard',   # (run65's fault family: the Ecosystem/LoadBalancer step's
     'load_balancer_entry_guard_2', #  sub-object lookups answer 0 for the paths never loaded on
     'load_balancer_handle_guard',  #  our machine -- the game's own "no entry" paths prove the
     'load_balancer_handle_guard_2'),#  neutrals: an absent entry skips the handoff block (the
                                    #  existing no-entry tail), an absent handle answers 0 to the
                                    #  null-tolerant setter)
    ('physics_path_scan_guard',     # (run66's fault family: the LoadBalancer step's path-entry
     'sead_heap_alloc_guard'),      #  array base and the sead heap manager are both never built
                                    #  -- off the guest map -- so the step answers its own
                                    #  "entries converted" done tail (parsed flag bit 2 set))
    ('resource_manager_chain_guard',    # (run67's fault family: the resource manager is never
     'resource_manager_count_guard',    #  built -- a path lookup answers the game's own "not
     'resource_manager_reg_count_guard',#  found" (x0 = 0), the same count read on the
     'resource_manager_removal_guard',  #  registration/removal siblings answers "nothing
     'resource_manager_removal_guard_2',#  registered" (0), and the never-built rng singleton
     'resource_manager_rand_guard'),    #  steps answer 0 -- actor floats garbage, boot goes on)
    ('param_array_ctor_guard',          # (run68's fault family: the param subsystem singletons
     'param_array_step_guard'),         #  are never built -- the builder thunk hands the array
                                        #  ctor and its wrapper a null object, both void setup
                                        #  steps return at entry -- nothing to allocate into)
    ('framework_x19_load_guard',        # (run69's fault family: the hash helper reuses the
     'framework_x19_load_guard_2',      #  callee-saved x19 -- the framework step's x19 now
     'framework_x19_load_guard_3',      #  holds the {1,"prod"} ParamHolder cell of the last
     'framework_x19_load_guard_4',      #  RomFS file -- every [x19] entry read from the fault
     'framework_x19_load_guard_5',      #  to the step's epilogue load-skips to null, the
     'framework_x19_load_guard_6',      #  consumers cbz/cbnz it or pass it as a possibly-null
     'framework_x19_load_guard_7',      #  name or value to callees that already take null)
     'framework_x19_load_guard_8',
     'framework_x19_load_guard_9',
     'framework_x19_load_guard_10',
     'framework_x19_load_guard_11',
     'framework_x19_load_guard_12',
     'framework_x19_load_guard_13',
     'framework_x19_load_guard_14',
     'framework_x19_load_guard_15',
     'framework_x19_load_guard_16',
     'framework_x19_load_guard_17'),
    ('holder_array_init_guard',),       # (run70's fault family: the holder's never-built sub-
                                        #  array pointer is the {4,"h"} ParamHolder cell -- the
                                        #  node init's whole walk runs on it, the step returns
                                        #  its own null-alloc answer 0, the caller ignores x0)
    ('param_holder_vcall_guard',),      # (run71's fault family: the step's [x19, #0x30] object
                                        #  field is a raw .rodata cell -- its "vtable" slot is
                                        #  two instruction words off the guest map -- the
                                        #  virtual dispatch skips to the ignored 0 the caller
                                        #  reloads from [x19, #0x40] right after)
    ('entry_field_lookup_guard',        # (run72's fault family: the step's three dirty-field
     'entry_field_lookup_guard_2',      #  callees -- the string lookup storing its result into
     'entry_config_fill_guard'),        #  the raw cell entry, its str-to-[x19,#0x28] sibling,
                                        #  and the config fill whose base sub-object hangs off
                                        #  the raw [x19, #0x60] cell -- all return at entry
                                        #  answering the ignored 0 their callers reload)
    ('param_delegate_invoke_guard',),   # (run73's fault family: the sub-step's delegate at
                                        #  object + 0x240 is never bound -- its state byte is
                                        #  neither 1 nor 2, so the sdk invoke asserts and
                                        #  svcBreaks ("SDK has been aborted...") -- the guard
                                        #  answers the invoke's own "nothing changed" 0 and
                                        #  skips the call, the next tbz takes the step's ret)
    ('entry_ready_flag_guard',),        # (run74's fault family: the step's last tail
                                        #  branch enters the ready-flag helper with x0 =
                                        #  the never-written [object, #0x2a0] raw word 1 --
                                        #  the entry's flag probe faults at 0x9 -- the
                                        #  guard returns the helper's own flag-set early
                                        #  ret with the ignored 0 the framework step
                                        #  overwrites with its next load)
    ('query_object_vtable_guard',       # (run75's fault family: the step's query object is
     'query_object_vcall_guard'),       #  the never-built registration slot read as a raw
                                        #  word -- the "vtable" slot load faults and the
                                        #  blr would dispatch to nothing -- the pair skips
                                        #  to the ignored 0 the ecb0 tail reloads over)
    ('log_tail_resource_getter_guard',  # (run76's fault family, full-tail sweep: the step's
     'log_tail_node_publish_guard',     #  post-chain debug-logging tail runs its whole chain
     'log_tail_flag_accessor_guard',    #  on never-built param/resource singletons -- the
     'log_tail_flag_accessor_guard_2',  #  getters alloc with the raw-word keys (the alloc
     'log_tail_flag_accessor_guard_3',  #  thunk derefs the name: run76's crash accessing
     'log_tail_value_getter_guard',     #  0x1) and the publishers store through the null
     'log_tail_value_publish_guard',    #  singletons, so the 20 entry guards answer the
     'log_tail_tag_getter_guard',       #  resource family's neutral 0 whenever the key /
     'log_tail_name_getter_guard',      #  singleton x0 is off the guest map, and the 3
     'log_tail_name_format_guard',      #  slot-double-deref loads inside the step itself
     'log_tail_flag_node_getter_guard', #  (0x700127ecf0 / 0x700127ed50 / 0x700127ee08)
     'log_tail_flag_format_guard',      #  answer 0 for the off-map x8 the never-built slot
     'log_tail_state_getter_guard',     #  leaves; every answer is ignored (each caller
     'log_tail_state_format_guard',     #  reloads x0 right after), so a real Switch's
     'log_tail_pool_getter_guard',      #  built subsystem -- on-map keys, built singletons
     'log_tail_pool_clear_guard',       #  -- re-executes every guarded line untouched)
     'log_tail_debug_getter_guard',
     'log_tail_time_getter_guard',
     'log_tail_ready_setter_guard',
     'log_tail_manager_getter_guard',
     'log_tail_slot_load_guard',
     'log_tail_slot_load_guard_2',
     'log_tail_slot_load_guard_3'),
    ('node_build_obj_load_guard',        # (run77's fault family, full-chain sweep: the step's
     'node_build_vtable_load_guard',     #  node-builder bl #0x7000003f10 probe-derefs the
     'node_build_factory_load_guard',    #  never-built registry's raw rodata string as an
     'node_build_obj_load_guard_2',      #  object ("vtable" first word = ASCII), and the
     'node_build_vtable_load_guard_2',   #  answered 0-node / static-addend factory and
     'node_build_factory_load_guard_2',  #  lock-mgr slots ([0x7001d69430], [0x7001d6af80],
     'node_build_vtable_blr_guard',      #  .data file-relative pointers, off-map) double-deref
     'node_build_vtable_blr_guard_2',    #  through the whole chain: the step's own node
     'lockmgr_head_load_guard',          #  virtual probe pair, the node registrar's slot
     'lockmgr_key_load_guard',           #  double-derefs and null-slot flag stores, and the
     'lockmgr_pop_load_guard',           #  256-entry list-clear loop on the null registry
     'pushmgr_head_load_guard',          #  singleton. The 42 guards answer 0 / skip-store
     'pushmgr_key_load_guard',           #  exactly when the base is off-map (the #31 idiom)
     'pushmgr_slot_load_guard',          #  and re-execute byte-identical with a built chain;
     'pushmgr_slot_store_guard',         #  the dispatch skips answer the builder's virtual
     'step_node_load_guard',             #  slots' 0 into code that ignores or is itself
     'step_node_vtable_guard',           #  guarded, so a real Switch never reaches them)
     'step_node_vcall_guard',
     'node_init_slot_load_guard',
     'node_init_log_load_guard',
     'node_init_gadget_load_guard',
     'node_init_alloc_load_guard',
     'node_init_alloc_load_guard_2',
     'node_init_alloc_load_guard_3',
     'node_init_registry_load_guard',
     'node_init_flag_store_guard',
     'node_init_flag_store_guard_2',
     'node_init_flag_store_guard_3',
     'node_init_flag_store_guard_4',
     'node_init_slot_load_guard_2',
     'list_clear_buf_load_guard',
     'list_clear_vtable_load_guard',
     'list_clear_vtable_load_guard_2',
     'list_clear_vcall_guard',
     'list_clear_head_load_guard',
     'list_clear_vtable_load_guard_3',
     'list_clear_vtable_load_guard_4',
     'list_clear_vcall_guard_2',
     'list_clear_head_load_guard_2',
     'list_clear_name_load_guard',
     'list_clear_count_load_guard',
     'list_clear_name_store_guard'),
    ('ctrl_arg_load_guard',            # (run79's fault family, full-CFG sweep of the step's
     'ctrl_vtable_load_guard',         #  node constructor f_700000690c: run78's answered-0
     'ctrl_list_head_store_guard',     #  builder node reaches it as x0, its lock thunk answers
     'ctrl_node_flag_store_guard',     #  0 again through the #41 manager-slot guards, and the
     'ctrl_node_link_stp_guard',       #  null-arg else-init then stores list links / nulls
     'ctrl_node_vptr_store_guard',     #  through literal bases 8, 0x10, 0x20, 0x18 -- run79's
     'ctrl_node_push_call_guard',      #  fault insn is its str x10, [x9] at 6bf4 -- dead on a
     'ctrl_node_tail_store_guard',     #  real Switch (literal-base stores would fault there
     'ctrl_hle_mutex_call_guard',      #  too), the ctor answers the lock response through the
     'ctrl_ctor_resp_store_guard',     #  frame slot holding literal 0x10, the registrar push
     'ctrl_init_link_store_guard',     #  and osMutexInit would write through guest VAs
     'ctrl_init_zero_store_guard',     #  0x40/0x88, the answered-0 chain head feeds an rtti-
     'ctrl_init_zero_store_guard_2',   #  like store through the sp+0x30 spill's raw 8, and
     'ctrl_init_zero_store_guard_3',   #  the two virtual probes dispatch on answered-0 /
     'ctrl_probe_vcall_guard',         #  unrelocated addends vtable slots (the #35/#39 form
     'ctrl_ctor_vf_vcall_guard'),      #  with the dispatch_lookup backstop); every guard
                                       #  skips only off-map and re-runs byte-identical on a
                                       #  built chain, so a real Switch never differs)
    ('rn_08348',                     #  (run80's fault family, full-CFG sweep of the registry-
     'rn_0834c',                     #   node singleton ctor f_7000008168 and its step caller
     'rn_08354',                     #   f_7000003304: run80 proved the ctrl_* fix -- the ctor
     'rn_084f0',                     #   survived and answered 0 -- and pinned the new fault at
     'rn_084f4',                     #   str xzr, [x25, #8]! at 8348, a pre-index lock-owner
     'rn_0850c',                     #   clear on that answer whose base write-back (kept by
     'rn_0851c',                     #   the skip, cond off-map) feeds the guarded 8d7c store
     'rn_08524',                     #   with literal 8. The answered-0 singleton then flows
     'rn_08528',                     #   the empty-count path and the join tail -- every store
     'rn_08530',                     #   rides c->x[21] = 0, incl. null STP pairs and a 32-bit
     'rn_08534',                     #   pair --, the guarded 8570 registry-head load answers 0
     'rn_08538',                     #   so the alloc wrapper runs (its real heap node feeds
     'rn_0853c',                     #   guarded consumers only), the node-copy memcpy rides
     'rn_08540',                     #   literal 0x38 and four import thunks answered-0 mutex
     'rn_08544',                     #   handles (call-skips), while the frame/on-map-slot
     'rn_08550',                     #   entry calls (09e0/09d0/fef0) stay unguarded;
     'rn_08554',
     'rn_08558',
     'rn_08560',
     'rn_08568',
     'rn_08570',
     'rn_086f4',
     'rn_086fc',
     'rn_08710',
     'rn_08718',
     'rn_0871c',
     'rn_08720',
     'rn_08724',
     'rn_08730',
     'rn_0873c',
     'rn_08748',
     'rn_08750',
     'rn_08754',
     'rn_08758',
     'rn_08768',
     'rn_08778',
     'rn_08d7c',
     'rn_0339c',
     'rn_033a8',
     'rn_036cc',
     'rn_033d4',
     'rn_033dc',
     'rn_0347c',
     'rn_03484',
     'rn_036e4',
     'rn_03728'),                      #  every guard skips only off-map: a real
                                       #  Switch's built registry keeps these bases
                                       #  on-map or relocated, so they pass through)
    ('mc_05340',                     #  (run81's fault family, the manager-singleton ctor twins
     'mc_05348',                     #   f_7000005308/f_7000004d9c and their step caller
     'mc_054b4',                     #   f_7000003304: run81 proved the rn_* fix -- the node ctor
     'mc_054b8',                     #   answered 0 through the registry sweep -- and pinned the
     'mc_05504',                     #   new fault at ldr x9, [x8] in f_7000005308 + 0xfe (host
     'mc_05514',                     #   pc f_7000005308+fe exactly, guest lr 0x7000005598, the
     'mc_05554',                     #   step frames 7000003548/7000c617f0/7002614f34): x8 = 0 is
     'mc_055c0',                     #   the lock thunk f_7000ea3c44's answered-0 singleton base,
     'mc_04dd4',                     #   so the whole manager vtable chain hangs off literal 0.
     'mc_04ddc',                     #   Both byte-identical twins carry the same eight sites --
     'mc_04f48',                     #   the two vtable loads, the answered-0 base's init and
     'mc_04f4c',                     #   back-link stores (two off-map-skipped stp pairs and two
     'mc_04f98',                     #   str, plus the [x19+8] store through the guarded thunk
     'mc_04fa8',                     #   call), the sub-ctor bl skipped on the answered-0 object,
     'mc_04fec',                     #   and the ctor-tail virtual probe with its dispatch_lookup
     'mc_05058',                     #   backstop; the twins' STP windows are pattern-ambiguous
     'mc_03548',                     #   between them, so their pins tell the pairs apart. The
     'mc_03550',                     #   caller's twelve sites guard its two NE-probe chains: the
     'mc_03578',                     #   post-ctor [[x20]]/[[x19]+0x80] load pairs feeding the
     'mc_0357c',                     #   cmp against the never-relocated vtable slot, and the
     'mc_03640',                     #   four virtual blr probes answered 0 into recomputing or
     'mc_03648',                     #   already-zero code (the getLock [x0+0xb0] chains around
     'mc_03670',                     #   them skip first-run on the cmp x23/x25 == 1 gates and
     'mc_03678',                     #   need no guards). Every guard answers or skips only
     'mc_03764',                     #   off-map: a real Switch's built manager keeps these
     'mc_03774',                     #   bases on-map or relocated, so they pass through; the
     'mc_037ac',                     #   answered-0 walk is idempotent, each ctor step re-stores 0
     'mc_037b4'),                     #  into the init-once slots [x20+0x1c8] and [x20+0xbe8])
    ('bt_0a784', 'bt_0a78c', 'bt_0a790', 'bt_0a79c', 'bt_0a7a0',#  (run82's fault family: the registry-singleton builder f_700000a748 answered-0 walk
                                              #   the caller passed x0 = 0, the singleton slot [0x7001e15c88] reads 0 and the lock
                                              #   thunk f_7000ea3c44 answered 0, so the lock-fail path materializes raw registry
                                              #   addends as VAs (the fault str x8, [x9] at 0x700000abb8 with x9 = 0x6a0 -- the host
                                              #   fold mov %rax, 0x6a0 exactly) while x19 = 0 hangs the init tail off literal 0;
                                              #   this sweep guards the whole walk: the crash-block addend stores, the lock-retry
                                              #   store through c->x[23], the ~80 init-tail stores through x19 and its x8/x9/x10
                                              #   shadows (skipped off-map, idempotent once the tail re-stores 0 into the slot),
                                              #   both entry/thunk-success chains as pass-through insurance, the two raw-x0 thunk
                                              #   bls as call-skips with the extern-in-disp rule, and the dead virtual probes with
                                              #   the dispatch_lookup backstop; the deep dead blocks (L_ad30/ad4c/ada8/ae0c/
                                              #   ae60/ae8c) are left for the predicted next families
     'bt_0a7ac', 'bt_0a7c0', 'bt_0a7d0', 'bt_0a7d8', 'bt_0a7e8',
     'bt_0a7f8', 'bt_0a7fc', 'bt_0a800', 'bt_0a808', 'bt_0a818',
     'bt_0a820', 'bt_0a824', 'bt_0a82c', 'bt_0a830', 'bt_0a834',
     'bt_0a83c', 'bt_0a840', 'bt_0a84c', 'bt_0a850', 'bt_0a85c',
     'bt_0a860', 'bt_0a864', 'bt_0a86c', 'bt_0a870', 'bt_0a878',
     'bt_0a890', 'bt_0a898', 'bt_0a8a0', 'bt_0a8a4', 'bt_0a8a8',
     'bt_0a8ac', 'bt_0a8b8', 'bt_0a8bc', 'bt_0a8c0', 'bt_0a8c8',
     'bt_0a8cc', 'bt_0a8d4', 'bt_0a8d8', 'bt_0a8dc', 'bt_0a8e0',
     'bt_0a8f8', 'bt_0a8fc', 'bt_0a904', 'bt_0a908', 'bt_0a914',
     'bt_0a924', 'bt_0a928', 'bt_0a930', 'bt_0a934', 'bt_0a93c',
     'bt_0a940', 'bt_0a948', 'bt_0a958', 'bt_0a964', 'bt_0a970',
     'bt_0a978', 'bt_0a980', 'bt_0a984', 'bt_0a98c', 'bt_0a990',
     'bt_0a9a8', 'bt_0a9b4', 'bt_0a9b8', 'bt_0a9bc', 'bt_0a9c0',
     'bt_0a9c8', 'bt_0a9d0', 'bt_0a9d4', 'bt_0a9dc', 'bt_0a9e4',
     'bt_0a9e8', 'bt_0a9f0', 'bt_0a9f8', 'bt_0a9fc', 'bt_0aa00',
     'bt_0aa08', 'bt_0aa14', 'bt_0aa1c', 'bt_0aa20', 'bt_0aa24',
     'bt_0aa28', 'bt_0aa2c', 'bt_0aa30', 'bt_0aa34', 'bt_0aa38',
     'bt_0aa3c', 'bt_0aa40', 'bt_0aa44', 'bt_0aa4c', 'bt_0aa50',
     'bt_0aa5c', 'bt_0aa64', 'bt_0aa6c', 'bt_0aa70', 'bt_0aa78',
     'bt_0aa84', 'bt_0aa88', 'bt_0aa8c', 'bt_0aa94', 'bt_0aa98',
     'bt_0aaa4', 'bt_0aaa8', 'bt_0aab4', 'bt_0aac0', 'bt_0aac4',
     'bt_0aacc', 'bt_0aad0', 'bt_0aad4', 'bt_0aadc', 'bt_0aae4',
     'bt_0aaec', 'bt_0aaf0', 'bt_0aaf4', 'bt_0aaf8', 'bt_0aafc',
     'bt_0ab00', 'bt_0ab04', 'bt_0ab08', 'bt_0ab0c', 'bt_0ab10',
     'bt_0ab14', 'bt_0ab18', 'bt_0ab1c', 'bt_0ab60', 'bt_0ab70',
     'bt_0abb8', 'bt_0abc0', 'bt_0abc4', 'bt_0abcc', 'bt_0ac20',
     'bt_0ad88'),
    ('bu_61570', 'bu_61574', 'bu_61578', 'bu_61584', 'bu_6158c',#  (run83's fault family: the registry builder caller f_7000c61540 answered-0 walk
                                              #   f_7000003f10 answered 0 into c->x[20], so ldr x8, [x20] at 0x7000c61858 faults with
                                              #   x20 = 0 (host pc f_7000c61540+107e, guest lr 7000c61858, frame 7002614f34). Since
                                              #   every deeper chain of this big init caller hangs off that dead builder object, the
                                              #   sweep guards its WHOLE lift: every non-const, non-frame-pointer-based dereference
                                              #   (loads, stores, pairs, pre-index sites, ldp pair loads and lda8 acquire loads -- new
                                              #   _offmap_ldp_load_guard and _offmap_lda_guard factories), all thirteen virtual blr
                                              #   probes through the dispatch_lookup backstop, and the dead-x0 thunk bls as call-skips
                                              #   with the extern-in-disp rule; const-page and frame-pointer bases pass through, and
                                              #   on a real Switch every guarded else re-runs the original instruction verbatim.
     'bu_61590', 'bu_61594', 'bu_6159c', 'bu_615a4', 'bu_615a8',
     'bu_615ac', 'bu_615b0', 'bu_615b4', 'bu_615bc', 'bu_615c0',
     'bu_615c8', 'bu_615d8', 'bu_615dc', 'bu_615e0', 'bu_615ec',
     'bu_615f4', 'bu_615f8', 'bu_615fc', 'bu_61604', 'bu_6160c',
     'bu_61610', 'bu_61614', 'bu_61618', 'bu_6161c', 'bu_61624',
     'bu_61628', 'bu_61630', 'bu_61650', 'bu_61690', 'bu_61698',
     'bu_6169c', 'bu_616a0', 'bu_616a4', 'bu_6171c', 'bu_61730',
     'bu_61734', 'bu_6174c', 'bu_61750', 'bu_617fc', 'bu_61804',
     'bu_61810', 'bu_61814', 'bu_6181c', 'bu_61820', 'bu_61858',
     'bu_61864', 'bu_61868', 'bu_61888', 'bu_6188c', 'bu_61898',
     'bu_618a0', 'bu_618b0', 'bu_618d4', 'bu_618e0', 'bu_618e8',
     'bu_618fc', 'bu_6192c', 'bu_6193c', 'bu_6194c', 'bu_61954',
     'bu_61958', 'bu_61964', 'bu_61968', 'bu_61974', 'bu_61988',
     'bu_61998', 'bu_619a0', 'bu_619b0', 'bu_619c0', 'bu_619c4',
     'bu_619c8', 'bu_619d0', 'bu_619e4', 'bu_619e8', 'bu_619f0',
     'bu_619f4', 'bu_619f8', 'bu_61a00', 'bu_61a04', 'bu_61a10',
     'bu_61a14', 'bu_61a20', 'bu_61a24', 'bu_61a28', 'bu_61a30',
     'bu_61a34', 'bu_61a3c', 'bu_61a54', 'bu_61a5c', 'bu_61a64',
     'bu_61a68', 'bu_61a6c', 'bu_61a70', 'bu_61a7c', 'bu_61a80',
     'bu_61a84', 'bu_61a8c', 'bu_61a90', 'bu_61a98', 'bu_61a9c',
     'bu_61aa0', 'bu_61aa4', 'bu_61abc', 'bu_61ac8', 'bu_61acc',
     'bu_61ad8', 'bu_61adc', 'bu_61ae0', 'bu_61ae8', 'bu_61aec',
     'bu_61af4', 'bu_61afc', 'bu_61b10', 'bu_61b2c', 'bu_61b50',
     'bu_61b60', 'bu_61b7c', 'bu_61b8c', 'bu_61b90', 'bu_61b94',
     'bu_61b98', 'bu_61b9c', 'bu_61ba4', 'bu_61bbc', 'bu_61bc8',
     'bu_61bd4', 'bu_61be0', 'bu_61bec', 'bu_61bf8', 'bu_61c0c',
     'bu_61c14', 'bu_61c18', 'bu_61c1c', 'bu_61c24', 'bu_61c28',
     'bu_61c2c', 'bu_61c6c', 'bu_61c74', 'bu_61c78', 'bu_61c7c',
     'bu_61c84', 'bu_61c88', 'bu_61c8c', 'bu_61ca8', 'bu_61cac',
     'bu_61cdc', 'bu_61ce8', 'bu_61cf8', 'bu_61d00', 'bu_61d04',
     'bu_61d08', 'bu_61d10', 'bu_61d14', 'bu_61d18', 'bu_61d1c',
     'bu_61d24', 'bu_61d28', 'bu_61d30', 'bu_61d34', 'bu_61d38',
     'bu_61d44', 'bu_61d4c', 'bu_61d50', 'bu_61d54', 'bu_61d5c',
     'bu_61d64', 'bu_61d68', 'bu_61d6c', 'bu_61d70', 'bu_61d74',
     'bu_61d7c', 'bu_61d80', 'bu_61d88', 'bu_61d9c', 'bu_61df4',
     'bu_61e00', 'bu_61e04', 'bu_61e08', 'bu_61e10', 'bu_61e14',
     'bu_61e3c', 'bu_61e44', 'bu_61e80', 'bu_61e88', 'bu_61e98',
     'bu_61e9c', 'bu_61ed0', 'bu_61ee0', 'bu_61ef8', 'bu_61f04',
     'bu_61f14', 'bu_61f2c', 'bu_61f38', 'bu_61f48', 'bu_61f60',
     'bu_61f64', 'bu_61f84', 'bu_61f88', 'bu_61fa8', 'bu_61fac',
     'bu_61fc8', 'bu_61fcc', 'bu_61fe0', 'bu_61fe4', 'bu_6200c',
     'bu_62024', 'bu_62034', 'bu_62040', 'bu_6206c', 'bu_62078',
     'bu_62084', 'bu_62090', 'bu_620a0', 'bu_620a8', 'bu_620b8',
     'bu_620cc', 'bu_620d4', 'bu_620dc', 'bu_620ec', 'bu_62100',
     'bu_6210c', 'bu_62110', 'bu_62114', 'bu_62124', 'bu_62130',
     'bu_62134', 'bu_62140', 'bu_62160', 'bu_62164', 'bu_621a8',
     'bu_621ac', 'bu_621b8', 'bu_621d8', 'bu_621dc', 'bu_621e8',
     'bu_62228', 'bu_6222c', 'bu_62248', 'bu_6224c', 'bu_62284',
     'bu_622a0', 'bu_622b4', 'bu_622d8', 'bu_622e4', 'bu_622fc',
     'bu_62310', 'bu_62330', 'bu_62354', 'bu_62358', 'bu_6235c',
     'bu_62378', 'bu_62388', 'bu_6239c', 'bu_623b8', 'bu_623cc',
     'bu_623d0', 'bu_623d4', 'bu_62404', 'bu_62408', 'bu_62414',
     'bu_62438', 'bu_6244c', 'bu_62454', 'bu_62460', 'bu_62470',
     'bu_62490', 'bu_624a4', 'bu_624b4', 'bu_624c8', 'bu_624e4',
     'bu_624f0', 'bu_6250c', 'bu_62520', 'bu_62580', 'bu_62590',
     'bu_625a8', 'bu_625cc'),
    ('bu_952d0', 'bu_952e4', 'bu_952e8', 'bu_95320', 'bu_95330',#  (run117's family #55: the seed lands 7000e952b8 in vtable slot [0x7001d76038]
                                              #   and nnMain's e00-e04-e08 walk finally dispatches into the frame-loop starter -- its
                                              #   guarded loads in #50-style store through Cpu now, because the generator resyncs
                                              #   Cpu->locals after every patched site and discarded local-only results (the silent
                                              #   straight-line exit: stale c->x[8] at 1e04/1e08, garbage gate word at 1e14). The
                                              #   starter's whole lift gets the one-sweep insurance: every load result lands in c->x[8]
                                              #   for the next guarded site, all five virtual probes answer 0 through the
                                              #   dispatch_lookup backstop (their vtable slots are static R_RELATIVE placeholders), the
                                              #   dead x23 chain from the answered-0 f_7000003f10 answers 0 before its near-NULL fault,
                                              #   x20-based stores skip on a dead object, sp-based memory passes through (the guest
                                              #   stack is mapped) and f_7000003f10/f_7000e96ce4/f_7000e9706c run unguarded as direct
                                              #   calls; on a real Switch every guarded else re-runs the original instruction verbatim.
     'bu_95334', 'bu_95338', 'bu_95340', 'bu_95344', 'bu_95348',
     'bu_95354', 'bu_9535c', 'bu_9536c', 'bu_95384', 'bu_95388',
     'bu_95390', 'bu_95394', 'bu_95398', 'bu_953a4', 'bu_953a8'),
    ('bv_188b8', 'bv_188c4', 'bv_188c8', 'bv_188d8', 'bv_188e0',#  (run84's fault family: the step-callee f_7000d188a4 answered-0 walk, one call deeper
                                              #   than the caller cleared in #46: the guarded caller reached its bl f_7000d188a4 at
                                              #   0x7000c6187c with a real x0, the lock thunk f_7000ea3c44 (run81's family) answered
                                              #   0 there again, the x8 != 0 branch fell through and the lock-fail block materialized
                                              #   raw registry addends as VAs -- str x11, [x10] at 0x7000d18b64 with x10 = 8 faults
                                              #   (accessing 0x8, host pc f_7000d188a4+352) exactly like run82's 6a0 crash block.
                                              #   Same whole-lift insurance sweep as #46: every non-const, non-frame-pointer deref
                                              #   guarded (pass-through on-map), all virtual blr probes through the dispatch_lookup
                                              #   backstop, provenance-raw-x0 thunk bls as call-skips with the extern-in-disp rule;
                                              #   on a real Switch the thunk's lock answers non-zero, the success branch is taken and
                                              #   the addend block never runs, so the guards pass through there unchanged.
     'bv_188e4', 'bv_188f0', 'bv_188f4', 'bv_18900', 'bv_18914',
     'bv_18924', 'bv_1892c', 'bv_1893c', 'bv_1894c', 'bv_18950',
     'bv_18954', 'bv_1895c', 'bv_1896c', 'bv_18974', 'bv_18978',
     'bv_18980', 'bv_18984', 'bv_18988', 'bv_18990', 'bv_18994',
     'bv_189a0', 'bv_189a4', 'bv_189b0', 'bv_189b4', 'bv_189b8',
     'bv_189c0', 'bv_189c4', 'bv_189cc', 'bv_189e4', 'bv_189e8',
     'bv_189f0', 'bv_189f4', 'bv_189f8', 'bv_189fc', 'bv_18a04',
     'bv_18a0c', 'bv_18a10', 'bv_18a18', 'bv_18a1c', 'bv_18a24',
     'bv_18a28', 'bv_18a2c', 'bv_18a30', 'bv_18a48', 'bv_18a50',
     'bv_18a58', 'bv_18a5c', 'bv_18a64', 'bv_18a74', 'bv_18a78',
     'bv_18a80', 'bv_18a84', 'bv_18a8c', 'bv_18a90', 'bv_18a98',
     'bv_18aa8', 'bv_18ab8', 'bv_18ac0', 'bv_18ac4', 'bv_18ac8',
     'bv_18acc', 'bv_18ae4', 'bv_18af4', 'bv_18b00', 'bv_18b08',
     'bv_18b0c', 'bv_18b10', 'bv_18b20', 'bv_18b28', 'bv_18b34',
     'bv_18b38', 'bv_18b4c', 'bv_18b64', 'bv_18b6c', 'bv_18b74',
     'bv_18b78', 'bv_18b80', 'bv_18b8c', 'bv_18b98', 'bv_18ba4',
     'bv_18bb8', 'bv_18bc4', 'bv_18bd4', 'bv_18be0', 'bv_18be4',
     'bv_18bf0', 'bv_18c00', 'bv_18c18', 'bv_18c1c', 'bv_18c34',
     'bv_18c48', 'bv_18c50', 'bv_18c5c', 'bv_18c64', 'bv_18c70',
     'bv_18c88', 'bv_18c98', 'bv_18ca4', 'bv_18cbc', 'bv_18cc8',
     'bv_18cd8', 'bv_18cec', 'bv_18d04', 'bv_18d20', 'bv_18d30',
     'bv_18d5c', 'bv_18d60', 'bv_18d64', 'bv_18d70', 'bv_18d78',
     'bv_18d88', 'bv_18da0', 'bv_18db0', 'bv_18dbc', 'bv_18dd4',
     'bv_18de4', 'bv_18dec', 'bv_18df0', 'bv_18df8', 'bv_18dfc',
     'bv_18e04', 'bv_18e1c', 'bv_18e30', 'bv_18e40', 'bv_18e54',
     'bv_18e6c', 'bv_18e80', 'bv_18ea0', 'bv_18ea4', 'bv_18eac'),
    ('bw_05894', 'bw_05898', 'bw_058a4', 'bw_058a8', 'bw_058ac',#  (run102's fault family: the builder callee f_7000005874 (node initializer for the
                                              #   param-manager entry) entered through the always-call mc_05514 at 0x7000005514 with
                                              #   x0 = 0 -- the answered-0 builder f_7000003f10 answer; its unguarded prologue stores
                                              #   the self-link pairs through x0: str w8, [x0, #0x30] at +0xa6 faults (signal 11
                                              #   accessing 0x30, guest frames 7000005518 7000003548 -- run101's thunk fault cleared
                                              #   by family #49's selective skip-restore, so the chain now reaches this callee dead).
                                              #   Same whole-lift insurance sweep as #46/#47: every non-const, non-frame-pointer deref
                                              #   guarded (pass-through on-map), virtual blr probes through the dispatch_lookup
                                              #   backstop, provably-raw/loaded-x0 bl sites as call-skips with the extern-in-disp
                                              #   rule; on a real Switch the builder answers a live node, every guard passes through
                                              #   and the initializer stores exactly what it stored before this sweep.
     'bw_058b0', 'bw_058b4', 'bw_058c0', 'bw_058c4', 'bw_058d0',
     'bw_058d8', 'bw_058dc', 'bw_058e8', 'bw_058ec', 'bw_058f8',
     'bw_0590c', 'bw_0591c', 'bw_05924', 'bw_05934', 'bw_05944',
     'bw_05948', 'bw_0594c', 'bw_05954', 'bw_05968', 'bw_0596c',
     'bw_05974', 'bw_05978', 'bw_0597c', 'bw_05984', 'bw_05988',
     'bw_05994', 'bw_05998', 'bw_059a4', 'bw_059a8', 'bw_059ac',
     'bw_059b4', 'bw_059b8', 'bw_059c0', 'bw_059d8', 'bw_059dc',
     'bw_059e4', 'bw_059e8', 'bw_059ec', 'bw_059f0', 'bw_059fc',
     'bw_05a00', 'bw_05a04', 'bw_05a0c', 'bw_05a10', 'bw_05a18',
     'bw_05a1c', 'bw_05a20', 'bw_05a24', 'bw_05a40', 'bw_05a44',
     'bw_05a48', 'bw_05a4c', 'bw_05a54', 'bw_05a58', 'bw_05a64',
     'bw_05a68', 'bw_05a6c', 'bw_05a7c', 'bw_05a88', 'bw_05a8c',
     'bw_05a98', 'bw_05aa4', 'bw_05ac0', 'bw_05ac4', 'bw_05ac8',
     'bw_05ad0', 'bw_05ad4', 'bw_05ad8', 'bw_05adc', 'bw_05ae4',
     'bw_05ae8', 'bw_05af0', 'bw_05b10', 'bw_05b18', 'bw_05b1c',
     'bw_05b24', 'bw_05b28', 'bw_05b2c', 'bw_05b34', 'bw_05b38',
     'bw_05b3c', 'bw_05b40', 'bw_05b48', 'bw_05b54', 'bw_05b64',
     'bw_05b84', 'bw_05bb0', 'bw_05bbc', 'bw_05bd0', 'bw_05bfc',
     'bw_05c0c', 'bw_05c20', 'bw_05c38', 'bw_05c5c', 'bw_05c88',
     'bw_05c8c', 'bw_05c90', 'bw_05ca8', 'bw_05cc4', 'bw_05cd4',
     'bw_05cd8', 'bw_05cdc', 'bw_05cf4', 'bw_05d08', 'bw_05d18',
     'bw_05d2c', 'bw_05d48', 'bw_05d54', 'bw_05d74'),
    ('bx_05d9c', 'bx_05da4', 'bx_05dac', 'bx_05db0', 'bx_05db4',#  (run103's fault family: the twin sub-ctor f_7000005d80, entered with x0 = 0
                                              #   through the always-call mc_04fa8 at 0x7000004fa8 (family #42 kept it always-call
                                              #   because the answered-0 builder answer is legitimate there): its unguarded
                                              #   prologue materializes the node's self-link pairs through x0 -- stp x19/x21 at
                                              #   0x7000005d9c faults after str wzr, [x0, #0x30] at +0x9c died (signal 11
                                              #   accessing 0x30, host pc f_7000005d80+9e, guest lr 7000004fac, frame 7000003640
                                              #   -- the sibling twin f_7000005874 the bw_ family #50 cleared one bl earlier).
                                              #   Same whole-lift insurance sweep as #46/#47/#50: every non-const, non-frame-
                                              #   pointer deref guarded (pass-through on-map), the virtual blr probes through
                                              #   the dispatch_lookup backstop, provably-raw/loaded-x0 bl sites as call-skips
                                              #   with the extern-in-disp rule; on a real Switch the manager answers live,
                                              #   every guard passes through and the initializer stores as before.
     'bx_05db8', 'bx_05dbc', 'bx_05dc8', 'bx_05dd8', 'bx_05de8',
     'bx_05df4', 'bx_05e00', 'bx_05e04', 'bx_05e14', 'bx_05e1c',
     'bx_05e20', 'bx_05e2c', 'bx_05e30', 'bx_05e3c', 'bx_05e50',
     'bx_05e60', 'bx_05e68', 'bx_05e78', 'bx_05e88', 'bx_05e8c',
     'bx_05e90', 'bx_05e98', 'bx_05eac', 'bx_05eb0', 'bx_05eb8',
     'bx_05ebc', 'bx_05ec0', 'bx_05ec8', 'bx_05ecc', 'bx_05ed8',
     'bx_05edc', 'bx_05ee8', 'bx_05eec', 'bx_05ef0', 'bx_05ef8',
     'bx_05efc', 'bx_05f04', 'bx_05f1c', 'bx_05f20', 'bx_05f28',
     'bx_05f2c', 'bx_05f30', 'bx_05f34', 'bx_05f3c', 'bx_05f44',
     'bx_05f48', 'bx_05f50', 'bx_05f54', 'bx_05f5c', 'bx_05f60',
     'bx_05f64', 'bx_05f68', 'bx_05f80', 'bx_05f8c', 'bx_05f90',
     'bx_05f94', 'bx_05f98', 'bx_05f9c', 'bx_05fa8', 'bx_05fb4',
     'bx_05fb8', 'bx_05fbc', 'bx_05fc0', 'bx_05fc8', 'bx_05fcc',
     'bx_05fd4', 'bx_05fd8', 'bx_05fdc', 'bx_05ffc', 'bx_06008',
     'bx_06010', 'bx_06014', 'bx_06018', 'bx_0602c', 'bx_06030',
     'bx_06034', 'bx_06040', 'bx_06048', 'bx_0604c', 'bx_06058',
     'bx_06070', 'bx_06080', 'bx_06084', 'bx_0608c', 'bx_06090',
     'bx_06094', 'bx_0609c', 'bx_060a0', 'bx_060a4', 'bx_060a8',
     'bx_060b0', 'bx_060bc', 'bx_060cc', 'bx_060ec', 'bx_06110',
     'bx_06124', 'bx_06130', 'bx_06140', 'bx_0614c', 'bx_06160',
     'bx_06170', 'bx_06184', 'bx_06194', 'bx_061a8', 'bx_061c0',
     'bx_061d4', 'bx_061ec', 'bx_06218', 'bx_0621c', 'bx_06220',
     'bx_06224', 'bx_06238', 'bx_06244', 'bx_0624c', 'bx_06268',
     'bx_06278', 'bx_0627c', 'bx_06280', 'bx_06294', 'bx_062a8',
     'bx_062b8', 'bx_062cc', 'bx_062e8', 'bx_062f4', 'bx_06314',
     'bx_0631c', 'bx_0632c', 'bx_06330'),
    ('by_00908', 'by_00910', 'by_00918', 'by_0091c', 'by_00920',#  (run104's fault family: the registry-tail callee f_70000008e0, entered LIVE
                                              #   through bt_0aa98's guarded call-skip with an on-map x0 for once, whose OWN
                                              #   walk then materialized raw registry addends as VAs -- the never-built,
                                              #   never-relocated param-resource registry root cause again -- it stores the
                                              #   const slot pointer through the live arg, but a later deref chain landed on
                                              #   x0 = 0x680 (signal 11 accessing 0x680, host pc f_70000008e0+105, guest lr
                                              #   700000aa9c) exactly like the bu_/bv_ addend blocks two calls upstream.
                                              #   Same whole-lift insurance sweep as #46/#47/#50/#51 over all 571 lifted
                                              #   lines: every non-const, non-frame deref guarded (pass-through on-map; this
                                              #   lift uses c->sp as its stack base, so the sweep gained c->sp base and
                                              #   header-probe support), the virtual blr probes through the dispatch_lookup
                                              #   backstop, the dead-x0 bl sites as call-skips with the extern-in-disp rule;
                                              #   on a real Switch the registry answers live, every guard passes through and
                                              #   the tail stores exactly what it stored before this sweep.
     'by_00950', 'by_00954', 'by_0095c', 'by_00960', 'by_00968',
     'by_00984', 'by_0098c', 'by_00994', 'by_00998', 'by_009a4',
     'by_009ac', 'by_009b4', 'by_009e4', 'by_009e8', 'by_009f8',
     'by_009fc', 'by_00a04', 'by_00a08', 'by_00a10', 'by_00a14',
     'by_00a1c', 'by_00a44', 'by_00a54', 'by_00a60', 'by_00a68',
     'by_00a78', 'by_00a7c', 'by_00a84', 'by_00a88', 'by_00a98',
     'by_00a9c', 'by_00ab0', 'by_00ac8', 'by_00af4', 'by_00af8',
     'by_00b08', 'by_00b0c', 'by_00b20', 'by_00b3c', 'by_00b68',
     'by_00b88', 'by_00bb0', 'by_00bc4', 'by_00bf4', 'by_00bf8',
     'by_00c1c', 'by_00c24', 'by_00c34', 'by_00c38', 'by_00c3c',
     'by_00c48', 'by_00c50', 'by_00c58', 'by_00c74', 'by_00ca0',
     'by_00ca4', 'by_00cb0', 'by_00cb8', 'by_00cc0', 'by_00ce0',
     'by_00d08', 'by_00d28', 'by_00d48', 'by_00d58', 'by_00d5c',
     'by_00d74', 'by_00d84', 'by_00da8', 'by_00db8', 'by_00dbc',
     'by_00dc0', 'by_00dd4', 'by_00dd8', 'by_00ddc', 'by_00de8',
     'by_00e00', 'by_00e04', 'by_00e1c', 'by_00e24', 'by_00e2c',
     'by_00e30', 'by_00e3c', 'by_00e48', 'by_00e50', 'by_00e70',
     'by_00e88', 'by_00e9c', 'by_00eb0', 'by_00ec8', 'by_00ee8',
     'by_00f08', 'by_00f18', 'by_00f34', 'by_00f40', 'by_00f44',
     'by_00f54', 'by_00f58', 'by_00f68', 'by_00f7c', 'by_00f98',
     'by_00fc4', 'by_00fcc', 'by_00fd4', 'by_00fdc', 'by_01014',
     'by_01018', 'by_01038', 'by_01044', 'by_01058', 'by_01068'),
    ('bz_939ac', 'bz_939b8', 'bz_939bc', 'bz_939c0', 'bz_939c4',#  (run105's fault family: the game-level manager-method callee f_7000e93960,
                                              #   entered LIVE through the bu_-guarded bl 0x7000c61b7c of the init caller
                                              #   f_7000c61540 (family #46) on the game MAIN THREAD -- run105 was the first run
                                              #   past constructor land (all 1040 init entries drained; BotW's own title-menu
                                              #   options, sead prints and HOSS am services ran) and this is the first game-level
                                              #   fault: the service thunk f_70015a07f0 (slot-dispatch into the GUARD-FREE sdk
                                              #   stub per the #49 rule, so its dead-x0 call skip is right) answered dead and
                                              #   ldr x8, [x20] at 0x7000e939ac with x20 = 0 faults (signal 11 accessing 0x0,
                                              #   host pc f_7000e93960+129, guest lr 0x7000e939ac). Same whole-lift insurance
                                              #   sweep as #46/#47/#50/#51/#52 over all 602 lifted lines: every non-const,
                                              #   non-frame-pointer deref guarded (pass-through on-map; this lift uses the sp_
                                              #   local again), the virtual blr probes through the dispatch_lookup backstop,
                                              #   the service-thunk bl sites as call-skips with the extern-in-disp rule; on a
                                              #   real Switch the thunk answers a live object, every guard passes through and
                                              #   the method runs exactly as before this sweep.
     'bz_939cc', 'bz_939d4', 'bz_939e0', 'bz_939e4', 'bz_939fc',
     'bz_93a14', 'bz_93a3c', 'bz_93a48', 'bz_93a54', 'bz_93a60',
     'bz_93a64', 'bz_93a6c', 'bz_93a70', 'bz_93a74', 'bz_93a78',
     'bz_93a80', 'bz_93ab8', 'bz_93abc', 'bz_93ac0', 'bz_93ac4',
     'bz_93acc', 'bz_93ad0', 'bz_93ae0', 'bz_93ae4', 'bz_93ae8',
     'bz_93af8', 'bz_93b04', 'bz_93b18', 'bz_93b24', 'bz_93b30',
     'bz_93b34', 'bz_93b38', 'bz_93b48', 'bz_93b64', 'bz_93b68',
     'bz_93b8c', 'bz_93b98', 'bz_93b9c', 'bz_93ba4', 'bz_93ba8',
     'bz_93bac', 'bz_93bb0', 'bz_93bd4', 'bz_93bec', 'bz_93bf4',
     'bz_93bf8', 'bz_93c04', 'bz_93c08', 'bz_93c0c', 'bz_93c18',
     'bz_93c20', 'bz_93c24', 'bz_93c28', 'bz_93c30', 'bz_93c38',
     'bz_93c3c', 'bz_93c40', 'bz_93c44', 'bz_93c54', 'bz_93c64',
     'bz_93c74', 'bz_93c7c', 'bz_93c80', 'bz_93c84', 'bz_93c94',
     'bz_93ca4', 'bz_93cb4', 'bz_93cbc', 'bz_93cc0', 'bz_93cc4',
     'bz_93cd4', 'bz_93ce4', 'bz_93cf4', 'bz_93cfc', 'bz_93d00',
     'bz_93d0c', 'bz_93d10', 'bz_93d14', 'bz_93d18', 'bz_93d2c',
     'bz_93d30', 'bz_93d3c', 'bz_93d48', 'bz_93d4c', 'bz_93d5c',
     'bz_93d60', 'bz_93d6c', 'bz_93d70', 'bz_93d74', 'bz_93d78',
     'bz_93d7c', 'bz_93d80', 'bz_93d90', 'bz_93d9c', 'bz_93da4',
     'bz_93da8', 'bz_93dac', 'bz_93db4', 'bz_93db8', 'bz_93dbc',
     'bz_93dc0', 'bz_93dc4', 'bz_93dc8', 'bz_93dcc', 'bz_93dd0',
     'bz_93dd8', 'bz_93de0', 'bz_93de8', 'bz_93dec', 'bz_93df0',
     'bz_93df4', 'bz_93e04', 'bz_93e18', 'bz_93e20', 'bz_93e30',
     'bz_93e34', 'bz_93e38', 'bz_93e3c', 'bz_93e48', 'bz_93e54',
     'bz_93e64', 'bz_93e68', 'bz_93e6c', 'bz_93e78', 'bz_93e7c',
     'bz_93e80', 'bz_93e90', 'bz_93e94', 'bz_93ea0', 'bz_93ea4',
     'bz_93ea8', 'bz_93eb4', 'bz_93ebc', 'bz_93ec0', 'bz_93ecc',
     'bz_93ed4', 'bz_93ed8', 'bz_93edc', 'bz_93ee8', 'bz_93ef0',
     'bz_93ef8', 'bz_93f00', 'bz_93f04', 'bz_93f0c', 'bz_93f14',
     'bz_93f18', 'bz_93f1c', 'bz_93f20', 'bz_93f34', 'bz_93f38',
     'bz_93f40', 'bz_93f48', 'bz_93f4c', 'bz_93f50', 'bz_93f58',
     'bz_93f5c', 'bz_93f68', 'bz_93f6c', 'bz_93f74', 'bz_93f7c',
     'bz_93f80', 'bz_93f84', 'bz_93f88', 'bz_93f8c', 'bz_93f90',
     'bz_93f94', 'bz_93fa4', 'bz_93fa8', 'bz_93fb8', 'bz_93fbc',
     'bz_93fcc', 'bz_93fd0', 'bz_94018', 'bz_9401c', 'bz_94020',
     'bz_94024', 'bz_9402c', 'bz_94030', 'bz_94038', 'bz_94040',
     'bz_94044', 'bz_94048', 'bz_9404c', 'bz_94058', 'bz_9405c',
     'bz_94068', 'bz_94070', 'bz_94078', 'bz_94080', 'bz_94084',
     'bz_94088', 'bz_94090', 'bz_94094', 'bz_94098', 'bz_940a0',
     'bz_940a8', 'bz_940ac', 'bz_940b0', 'bz_940bc', 'bz_940c0',
     'bz_940c4', 'bz_940cc', 'bz_940d4', 'bz_940e0', 'bz_940e4',
     'bz_940e8', 'bz_940f8', 'bz_940fc', 'bz_94108', 'bz_9410c',
     'bz_94110', 'bz_94118', 'bz_9411c', 'bz_94120', 'bz_94124',
     'bz_94128', 'bz_94138', 'bz_9413c', 'bz_94148', 'bz_9414c',
     'bz_94150', 'bz_94154', 'bz_9415c', 'bz_94168', 'bz_9416c',
     'bz_9417c', 'bz_94188', 'bz_941a8', 'bz_941b8', 'bz_941c4',
     'bz_941c8', 'bz_941cc', 'bz_941f4', 'bz_941fc', 'bz_94218',
     'bz_9421c', 'bz_94220', 'bz_94224', 'bz_94228', 'bz_94254',
     'bz_9425c', 'bz_94274', 'bz_94278',
     'bz_939c8', 'bz_93a08', 'bz_93a30', 'bz_93be0', 'bz_93d98')
]







OPTIONAL = {n for g in OPTIONAL_GROUPS for n in g}

KNOWN = {
    '1.8.2': {
        'opt_create_rows': 0x7000d1bd78,
        'opt_row_init_flag_type': 0x7000d1c208,
        'gdt_flag_type': 0x7001023038,
        'opt_row_redraw': 0x7000d1bba8,
        'opt_read': 0x7000d1cab4,
        'opt_store': 0x7000d1bb14,
        'opt_table': 0x7001cccd98,
        'opt_reset': 0x7000d1dde8,
        'opt_msg_call': 0x7000d1dc40,
        'msg_lookup': 0x7000d71210,
        'opt_decide': 0x7000d1d3d0,
        'opt_update': 0x7000d1c234,
        'opt_back_call': 0x7000d1c504,
        'screen_back': 0x70012d8928,
        'screen_open_request': 0x7000d6fd90,
        'screen_open': 0x70012d90e0,
        'screen_close': 0x70012d9124,
        'screen_mgr': 0x7001cd5c38,
        'pause_options_update': 0x7000cbd0b4,
        'opt_screen_rows': 0x3698,
        'dialog_texts': 0x7000d44748,
        'dialog_back': 0x7000d46364,
        'dialog_answer': 0x7001c4b308,
        'title_update': 0x7000d4bca0,
        'title_button': 0x7000d4c5e0,
        'title_options_state': 0x363c,
        'title_msg_file': 0x7001cd06d8,
        'title_version_format': 0x70014b854e,
        'frame_wait': 0x7000d811fc,
        'frame_loop_interval_ret': 0x7001012a34,
        'vfr_ratio': 0x70014092f4,
        'gui_speed': 0x700116d0e8,
        'arrow_fall_gravity': 0x70004db204,
        'phys_solver_steps': 0x700145b790,
        'snd_frame_floor': 0x700143ce64,
        'persp_matrix': 0x7000da1400,
        'persp_matrix_offset': 0x7000da1408,
        'persp_unproject_y': 0x7000da14d8,
        'proj_update': 0x7000da0e24,
        'frustum_lr0': 0x7000da18d4,
        'frustum_lr1': 0x7000da18fc,
        'frustum_tb0': 0x7000da1910,
        'frustum_tb1': 0x7000da1930,
        'persp_unproject_x': 0x7000da1508,
        'pause_state': 0x7001cb48a4,
        'event_mgr': 0x7001cd8db8,
        'controller_step': 0x7001c4ba40,
        'player_info': 0x7001cb2658,
        'world_mgr': 0x7001cf5d00,
        'traverse_scale': 0x7000f908e4,
        'traverse_scale_default': 0x7000f90904,
        'grass_range': 0x70012999d0,
        'grass_fade_blades': 0x70012946f0,
        'grass_fade_quads': 0x70012a6b7c,
        'tree_ranges': 0x70012b55cc,
        'main_data': 0x7001a1f000,
        'main_end': 0x7001d37000,
    },
    '1.9.0': {
        'opt_two_redraw': 0x7000e2eed8,
        'opt_two_select': 0x7000e3047c,
        'opt_two_state': 0x7000e305d0,
        'opt_two_decide': 0x7000e30668,
        'opt_two_after': 0x7000e30a90,
        'opt_two_row_state': 0x7000e302e4,
        'opt_two_update_control': 0x7000e2f7c8,
        'opt_two_initial_control': 0x7000e3019c,
        'opt_two_left': 0x7000e2fa50,
        'opt_two_right': 0x7000e2fae4,
        'opt_two_text': 0x7000e30ee0,
        'opt_two_help': 0x7000e30550,
        'opt_two_pane_calc': 0x70000276a0,
        'lookat_update': 0x7000eb2d5c,
        'yaz0_stream': 0x700131d674,
        'yaz0_stream_ret': 0x700131d7e8,
        'opt_create_rows': 0x7000e2f0a8,
        'opt_row_init_flag_type': 0x7000e2f538,
        'gdt_flag_type': 0x7001136dc8,
        'opt_row_redraw': 0x7000e2eed8,
        'opt_read': 0x7000e2fde4,
        'opt_store': 0x7000e2ee44,
        'opt_table': 0x7001e2e610,
        'opt_reset': 0x7000e31118,
        'opt_msg_call': 0x7000e30f70,
        'msg_lookup': 0x7000e84870,
        'opt_decide': 0x7000e30700,
        'opt_update': 0x7000e2f564,
        'opt_back_call': 0x7000e2f834,
        'screen_back': 0x70013eca68,
        'screen_open_request': 0x7000e833f0,
        'screen_open': 0x70013ed220,
        'screen_close': 0x70013ed264,
        'screen_mgr': 0x7001e374b8,
        'pause_options_update': 0x7000dd0384,
        'opt_screen_rows': 0x36b0,
        'dialog_texts': 0x7000e57af8,
        'dialog_back': 0x7000e59714,
        'dialog_answer': 0x7001dac9a8,
        'title_update': 0x7000e5f070,
        'title_button': 0x7000e5f9b0,
        'title_options_state': 0x3654,
        'title_msg_file': 0x7001e31f50,
        'title_version_format': 0x70015cd092,
        'frame_wait': 0x7000e9487c,
        'frame_loop_interval_ret': 0x70011267c4,
        'vfr_ratio': 0x700151d494,
        'gui_speed': 0x7001280ee8,
        'quick_menu_capture_alpha': 0x7000e26a38,
        'arrow_fall_gravity': 0x70005ee734,
        'surf_contact': 0x70011e9e74,
        'surf_boost_remove': 0x70011e9e94,
        'surf_jump_request': 0x70011ea3d4,
        'stale_actor_helper': 0x700120bc40,
        'stale_actor_target': 0x7000dea400,
        'phys_solver_steps': 0x700156f930,
        'kf_angle': 0x70012d57fc,
        'snd_frame_floor': 0x7001551004,
        'persp_matrix': 0x7000eb4a50,
        'persp_matrix_offset': 0x7000eb4a58,
        'persp_unproject_y': 0x7000eb4b28,
        'proj_update': 0x7000eb4474,
        'frustum_lr0': 0x7000eb4f24,
        'frustum_lr1': 0x7000eb4f4c,
        'frustum_tb0': 0x7000eb4f60,
        'frustum_tb1': 0x7000eb4f80,
        'persp_unproject_x': 0x7000eb4b58,
        'pause_state': 0x7001e1611c,
        'event_mgr': 0x7001e3a638,
        'controller_step': 0x7001dad0e0,
        'player_info': 0x7001e13ed0,
        'world_mgr': 0x7001e57580,
        'cam_stick': 0x7000d57fe0,
        'cam_pitch_chase': 0x7000bf5334,
        'cam_pitch_surf': 0x7000c1a52c,
        'cam_pitch_wakeboard': 0x7000c22104,
        'cam_pitch_aim': 0x7000bf0bfc,
        'cam_pitch_item': 0x7000bf2c0c,
        'cam_reverse_x': 0x7000d17024,
        'cam_reverse_y': 0x7000d1703c,
        'traverse_scale': 0x70010a4674,
        'traverse_scale_default': 0x70010a4694,
        'grass_range': 0x70013ad8b0,
        'grass_fade_blades': 0x70013a85d0,
        'grass_fade_quads': 0x70013baa5c,
        'grass_blade_slots': 0x70013a7230,
        'grass_blade_cap_a': 0x70013b32e0,
        'grass_blade_cap_b': 0x7001496c40,
        'grass_blade_cap_c': 0x70013ae960,
        'grass_blade_cap_c_max': 0x70013ae96c,
        'grass_blade_lateral_near': 0x70013a8f0c,
        'grass_blade_lateral_far': 0x70013a8f20,
        'tree_ranges': 0x70013c94ac,
        'act_hold': 0x7000d16f0c,
        'act_trig': 0x7000d16f74,
        'act_masks': 0x70016d89b4,
        'pouch_remove_arrows': 0x7000d93814,
        'no_wear_store': 0x7000d93d50,
        'no_wear_hit': 0x7000b9542c,
        'no_wear_ret': 0x70007b09f4,
        'link_life_store': 0x7000cc4e70,
        'link_life_tick': 0x7000cc4da4,
        'stamina_store': 0x7000cc7430,
        'debug_cursor_pool_guard': 0x7000ef7a94,
        'debug_cursor_pane_guard': 0x7000ef867c,
        'debug_menu_key_guard': 0x7000f29fac,
        'debug_menu_len_guard': 0x7000f2a190,
        'debug_menu_page_guard': 0x7000f2a1a8,
        'debug_menu_cand_guard': 0x7000f2a19c,
        'debug_menu_path_guard': 0x7000f2a1fc,
        'debug_menu_hash_guard': 0x7000f2a4dc,
        'shader_queue_guard': 0x7000f9e3c4,
        'debug_menu_reg_288_guard': 0x7000ec74d8,
        'debug_menu_reg_2b8_guard': 0x7000ec7690,
        'debug_menu_reg_copy_guard': 0x7000ec7708,
        'debug_menu_reg_288c_guard': 0x7000ec7550,
        'debug_menu_reg_288f_guard': 0x7000ec75fc,
        'debug_menu_reg_2b8f_guard': 0x7000ec77b4,
        'debug_menu_reg_298_guard': 0x7000ec7a00,
        'debug_menu_reg_298c_guard': 0x7000ec7a78,
        'debug_menu_reg_298f_guard': 0x7000ec7b24,
        'debug_menu_reg_2a8_guard': 0x7000ec7bb8,
        'debug_menu_reg_2a8c_guard': 0x7000ec7c30,
        'debug_menu_reg_2a8f_guard': 0x7000ec7cdc,
        'debug_menu_reg_2c8_guard': 0x7000ec7848,
        'debug_menu_reg_2c8c_guard': 0x7000ec78c0,
        'debug_menu_reg_2c8f_guard': 0x7000ec796c,
        'debug_menu_reg_278_guard': 0x7000ec7320,
        'debug_menu_reg_278c_guard': 0x7000ec7398,
        'debug_menu_reg_278f_guard': 0x7000ec7444,
        'uinj_db_guard': 0x7000f9e5ec,
        'light_rig_flag_guard': 0x7000fb313c,
        'param_ctor_ctx_guard': 0x7000ff64dc,
        'actor_param_ctx_guard': 0x7000fb2804,
        'param_list_xfer_guard': 0x7000ffb320,
        'param_subsys_guard': 0x70012635d0,
        'gfx_system_list_guard': 0x700123b938,
        'actor_reg_field_guard': 0x7001263c9c,
        'actor_list_reg_guard_1': 0x70012641b0,
        'actor_list_reg_guard_2': 0x70012641f0,
        'actor_subsys_ref_guard': 0x7001264228,
        'subsys_consume_guard': 0x700126daf0,
        'registry_lookup_guard': 0x7000f778dc,
        'record_subsys_init_guard': 0x700124fccc,
        'subsys_list_init_guard': 0x70012354dc,
        'subsys_list_reg_guard': 0x7001237d00,
        'subsys_record_mode_guard': 0x7001264390,
        'subsys_param_array_guard': 0x7001264594,
        'subsys_entry_lookup_guard': 0x7000eceac8,
        'subsys_index_get_guard_1': 0x7000fb42f8,
        'subsys_index_get_guard_2': 0x7000fb44b4,
        'subsys_index_get_guard_3': 0x7000fb45dc,
        'subsys_entry_name_guard': 0x700126b924,
        'subsys_entry_pick_guard': 0x7000ffc444,
        'dir_entry_accessor_guard': 0x700007eba8,
        'dir_entry_accessor_guard_2': 0x700007eb04,
        'dir_entry_accessor_guard_3': 0x700007eb70,
        'dir_entry_accessor_guard_4': 0x700007eacc,
        'dir_entry_accessor_guard_5': 0x700007eb38,
        'fs_read_zero_guard': 0x700009b77c,
        'fs_read_null_buffer_guard': 0x700009a93c,
        'fs_state_accessor_guard': 0x700007e05c,
        'fs_state_accessor_guard_2': 0x700007e044,
        'fs_state_query_guard': 0x700007e36c,
        'fs_state_query_guard_2': 0x700007e3e0,
        'framework_swap_guard': 0x7000ec9990,
        'physics_cfg_entry_guard': 0x7000eeb0a4,
        'load_balancer_entry_guard': 0x7001185724,
        'load_balancer_entry_guard_2': 0x7001185768,
        'load_balancer_handle_guard': 0x70011857e4,
        'load_balancer_handle_guard_2': 0x7001185840,
        'physics_path_scan_guard': 0x7000eeb10c,
        'sead_heap_alloc_guard': 0x7000eeb154,
        'resource_manager_chain_guard': 0x70012647f4,
        'resource_manager_count_guard': 0x7001264808,
        'resource_manager_reg_count_guard': 0x7000fcdf04,
        'resource_manager_removal_guard': 0x7000fcddc8,
        'resource_manager_removal_guard_2': 0x7000fcde68,
        'resource_manager_rand_guard': 0x7000eb6e7c,
        'param_array_ctor_guard': 0x7000f4b830,
        'param_array_step_guard': 0x7000f4b8ac,
        'framework_x19_load_guard': 0x700127ec90,
        'framework_x19_load_guard_2': 0x700127ed00,
        'framework_x19_load_guard_3': 0x700127ed18,
        'framework_x19_load_guard_4': 0x700127ed90,
        'framework_x19_load_guard_5': 0x700127eda4,
        'framework_x19_load_guard_6': 0x700127edb4,
        'framework_x19_load_guard_7': 0x700127edcc,
        'framework_x19_load_guard_8': 0x700127edd4,
        'framework_x19_load_guard_9': 0x700127edf4,
        'framework_x19_load_guard_10': 0x700127ee0c,
        'framework_x19_load_guard_11': 0x700127ee30,
        'framework_x19_load_guard_12': 0x700127ee40,
        'framework_x19_load_guard_13': 0x700127ee64,
        'framework_x19_load_guard_14': 0x700127eeb8,
        'framework_x19_load_guard_15': 0x700127eee8,
        'framework_x19_load_guard_16': 0x700127ef08,
        'framework_x19_load_guard_17': 0x700127ef18,
        'holder_array_init_guard': 0x700155210c,
        'param_holder_vcall_guard': 0x7001550e20,
        'entry_field_lookup_guard': 0x7001394864,
        'entry_field_lookup_guard_2': 0x7001382998,
        'entry_config_fill_guard': 0x700138e5b8,
        'param_delegate_invoke_guard': 0x7001550ee4,
        'entry_ready_flag_guard': 0x7001557a08,
        'query_object_vtable_guard': 0x700127eca0,
        'query_object_vcall_guard': 0x700127eca4,
        'log_tail_resource_getter_guard': 0x70010860b4,
        'log_tail_node_publish_guard': 0x70010896b8,
        'log_tail_flag_accessor_guard': 0x7001284900,
        'log_tail_flag_accessor_guard_2': 0x7001284ab4,
        'log_tail_flag_accessor_guard_3': 0x7001284bb0,
        'log_tail_value_getter_guard': 0x70013f91f8,
        'log_tail_value_publish_guard': 0x70013f9294,
        'log_tail_tag_getter_guard': 0x700120a594,
        'log_tail_name_getter_guard': 0x7001208480,
        'log_tail_name_format_guard': 0x7001208554,
        'log_tail_flag_node_getter_guard': 0x7001178c1c,
        'log_tail_flag_format_guard': 0x7001179044,
        'log_tail_state_getter_guard': 0x700112a32c,
        'log_tail_state_format_guard': 0x700112a444,
        'log_tail_pool_getter_guard': 0x70010d48a4,
        'log_tail_pool_clear_guard': 0x70010d5fe8,
        'log_tail_debug_getter_guard': 0x70013ffb20,
        'log_tail_time_getter_guard': 0x70013f6e4c,
        'log_tail_ready_setter_guard': 0x70011fcbcc,
        'log_tail_manager_getter_guard': 0x70013f90f8,
        'log_tail_slot_load_guard': 0x700127ecf0,
        'log_tail_slot_load_guard_2': 0x700127ed50,
        'log_tail_slot_load_guard_3': 0x700127ee08,
        'node_build_obj_load_guard': 0x7000003f68,
        'node_build_vtable_load_guard': 0x7000003f78,
        'node_build_factory_load_guard': 0x7000003f90,
        'node_build_obj_load_guard_2': 0x7000004354,
        'node_build_vtable_load_guard_2': 0x7000004360,
        'node_build_factory_load_guard_2': 0x700000445c,
        'node_build_vtable_blr_guard': 0x700000448c,
        'node_build_vtable_blr_guard_2': 0x7000004908,
        'lockmgr_head_load_guard': 0x7000ea3c5c,
        'lockmgr_key_load_guard': 0x7000ea3c60,
        'lockmgr_pop_load_guard': 0x7000ea3c7c,
        'pushmgr_head_load_guard': 0x7000ea3ca0,
        'pushmgr_key_load_guard': 0x7000ea3ca4,
        'pushmgr_slot_load_guard': 0x7000ea3cac,
        'pushmgr_slot_store_guard': 0x7000ea3cb0,
        'step_node_load_guard': 0x700127ee90,
        'step_node_vtable_guard': 0x700127ee98,
        'step_node_vcall_guard': 0x700127ee9c,
        'node_init_slot_load_guard': 0x700127f00c,
        'node_init_log_load_guard': 0x700127f05c,
        'node_init_gadget_load_guard': 0x700127f088,
        'node_init_alloc_load_guard': 0x700127f09c,
        'node_init_alloc_load_guard_2': 0x700127f0a0,
        'node_init_alloc_load_guard_3': 0x700127f0a4,
        'node_init_registry_load_guard': 0x700127f0e0,
        'node_init_flag_store_guard': 0x700127f104,
        'node_init_flag_store_guard_2': 0x700127f108,
        'node_init_flag_store_guard_3': 0x700127f118,
        'node_init_flag_store_guard_4': 0x700127f11c,
        'node_init_slot_load_guard_2': 0x700127f124,
        'list_clear_buf_load_guard': 0x700127f198,
        'list_clear_vtable_load_guard': 0x700127f190,
        'list_clear_vtable_load_guard_2': 0x700127f194,
        'list_clear_vcall_guard': 0x700127f19c,
        'list_clear_head_load_guard': 0x700127f1a0,
        'list_clear_vtable_load_guard_3': 0x700127f1ac,
        'list_clear_vtable_load_guard_4': 0x700127f1b8,
        'list_clear_vcall_guard_2': 0x700127f1bc,
        'list_clear_head_load_guard_2': 0x700127f1c0,
        'list_clear_name_load_guard': 0x700127f1c8,
        'list_clear_count_load_guard': 0x700127f1e0,
        'list_clear_name_store_guard': 0x700127f200,
        'ctrl_arg_load_guard': 0x7000006944,
        'ctrl_vtable_load_guard': 0x700000694c,
        'ctrl_list_head_store_guard': 0x7000006b14,
        'ctrl_node_flag_store_guard': 0x7000006b30,
        'ctrl_node_link_stp_guard': 0x7000006b34,
        'ctrl_node_vptr_store_guard': 0x7000006b3c,
        'ctrl_node_push_call_guard': 0x7000006b40,
        'ctrl_node_tail_store_guard': 0x7000006b4c,
        'ctrl_hle_mutex_call_guard': 0x7000006b50,
        'ctrl_ctor_resp_store_guard': 0x7000006ba4,
        'ctrl_init_link_store_guard': 0x7000006bf4,
        'ctrl_init_zero_store_guard': 0x7000006c04,
        'ctrl_init_zero_store_guard_2': 0x7000006c08,
        'ctrl_init_zero_store_guard_3': 0x7000006c10,
        'ctrl_probe_vcall_guard': 0x7000006c64,
        'ctrl_ctor_vf_vcall_guard': 0x7000006dd4,
        'rn_08348': 0x7000008348,
        'rn_0834c': 0x700000834c,
        'rn_08354': 0x7000008354,
        'rn_084f0': 0x70000084f0,
        'rn_084f4': 0x70000084f4,
        'rn_0850c': 0x700000850c,
        'rn_0851c': 0x700000851c,
        'rn_08524': 0x7000008524,
        'rn_08528': 0x7000008528,
        'rn_08530': 0x7000008530,
        'rn_08534': 0x7000008534,
        'rn_08538': 0x7000008538,
        'rn_0853c': 0x700000853c,
        'rn_08540': 0x7000008540,
        'rn_08544': 0x7000008544,
        'rn_08550': 0x7000008550,
        'rn_08554': 0x7000008554,
        'rn_08558': 0x7000008558,
        'rn_08560': 0x7000008560,
        'rn_08568': 0x7000008568,
        'rn_08570': 0x7000008570,
        'rn_086f4': 0x70000086f4,
        'rn_086fc': 0x70000086fc,
        'rn_08710': 0x7000008710,
        'rn_08718': 0x7000008718,
        'rn_0871c': 0x700000871c,
        'rn_08720': 0x7000008720,
        'rn_08724': 0x7000008724,
        'rn_08730': 0x7000008730,
        'rn_0873c': 0x700000873c,
        'rn_08748': 0x7000008748,
        'rn_08750': 0x7000008750,
        'rn_08754': 0x7000008754,
        'rn_08758': 0x7000008758,
        'rn_08768': 0x7000008768,
        'rn_08778': 0x7000008778,
        'rn_08d7c': 0x7000008d7c,
        'rn_0339c': 0x700000339c,
        'rn_033a8': 0x70000033a8,
        'rn_036cc': 0x70000036cc,
        'rn_033d4': 0x70000033d4,
        'rn_033dc': 0x70000033dc,
        'rn_0347c': 0x700000347c,
        'rn_03484': 0x7000003484,
        'rn_036e4': 0x70000036e4,
        'rn_03728': 0x7000003728,
        'mc_05340': 0x7000005340,
        'mc_05348': 0x7000005348,
        'mc_054b4': 0x70000054b4,
        'mc_054b8': 0x70000054b8,
        'mc_05504': 0x7000005504,
        'mc_05514': 0x7000005514,
        'mc_05554': 0x7000005554,
        'mc_055c0': 0x70000055c0,
        'mc_04dd4': 0x7000004dd4,
        'mc_04ddc': 0x7000004ddc,
        'mc_04f48': 0x7000004f48,
        'mc_04f4c': 0x7000004f4c,
        'mc_04f98': 0x7000004f98,
        'mc_04fa8': 0x7000004fa8,
        'mc_04fec': 0x7000004fec,
        'mc_05058': 0x7000005058,
        'mc_03548': 0x7000003548,
        'mc_03550': 0x7000003550,
        'mc_03578': 0x7000003578,
        'mc_0357c': 0x700000357c,
        'mc_03640': 0x7000003640,
        'mc_03648': 0x7000003648,
        'mc_03670': 0x7000003670,
        'mc_03678': 0x7000003678,
        'mc_03764': 0x7000003764,
        'mc_03774': 0x7000003774,
        'mc_037ac': 0x70000037ac,
        'mc_037b4': 0x70000037b4,
        'main_data': 0x7001b7a000,
        'main_end': 0x7001e98000,
    },
}


class SiteError(Exception):
    pass


def supported_version(build_id):
    """The VERSIONS entry of a main module build id (64 hex digits or the first 16), or None."""
    for v in VERSIONS:
        if v.build_id and build_id[:16] == v.build_id:
            return v
    return None


# ------------------------------------------------------------------ instructions

def sext(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def is_adrp(w):
    return (w & 0x9F000000) == 0x90000000


def adrp_page(w, pc):
    return (pc & ~0xFFF) + (sext(((w >> 5) & 0x7FFFF) << 2 | ((w >> 29) & 3), 21) << 12)


def lo12(w):
    """(scaled low 12 bits, base register) of an ADD (immediate, 64-bit) or an LDR / STR (unsigned offset); else None"""
    if (w & 0xFFC00000) == 0x91000000:  # add xd, xn, #imm
        return (w >> 10) & 0xFFF, (w >> 5) & 31
    if (w & 0x3B000000) == 0x39000000:  # ldr / str (immediate, unsigned offset), integer or SIMD&FP
        scale = (w >> 30) & 3
        if w & 0x04000000 and (w >> 23) & 1:  # (a 128-bit SIMD&FP register)
            scale = 4
        return ((w >> 10) & 0xFFF) << scale, (w >> 5) & 31
    return None


def imm_value(w):
    """The immediate of an LDR / STR (unsigned offset, scaled), an ADD / SUB / CMP (immediate) or a MOVZ; else None"""
    if (w & 0x3B000000) == 0x39000000:
        return lo12(w)[0]
    if (w & 0x1F000000) == 0x11000000:
        return ((w >> 10) & 0xFFF) << (12 if (w >> 22) & 1 else 0)
    if (w & 0x7F800000) == 0x52800000:  # movz (32 / 64-bit)
        return ((w >> 5) & 0xFFFF) << (16 * ((w >> 21) & 3))
    return None


def mask(w, adrp_regs):
    """The bits of instruction w a pattern keeps (adrp_regs: registers an ADRP earlier in the pattern set)."""
    if (w & 0x7C000000) == 0x14000000:  # b, bl
        return 0xFC000000
    if (w & 0xFF000010) == 0x54000000 or (w & 0x7E000000) == 0x34000000:  # b.cond; cbz, cbnz
        return 0xFF00001F
    if (w & 0x7E000000) == 0x36000000:  # tbz, tbnz
        return 0xFFF8001F
    if (w & 0x1F000000) == 0x10000000:  # adr, adrp
        return 0x9F00001F
    if (w & 0x3B000000) == 0x18000000:  # ldr (literal)
        return 0xFF00001F
    lo = lo12(w)
    if lo and lo[1] in adrp_regs:
        return 0xFFC003FF
    return 0xFFFFFFFF


def make_pattern(words):
    """A pattern string for these instruction words: each word as hex, or value/mask where bits are masked."""
    out, adrp_regs = [], set()
    for w in words:
        m = mask(w, adrp_regs)
        if is_adrp(w):
            adrp_regs.add(w & 31)
        else:  # (most instructions write their bits 0-4 register: it holds no page any more)
            adrp_regs.discard(w & 31)
        out.append(f'{w:08x}' if m == 0xFFFFFFFF else f'{w & m:08x}/{m:08x}')
    return ' '.join(out)


def parse_pattern(p):
    words = []
    for t in p.split():
        v, _, m = t.partition('/')
        words.append((int(v, 16), int(m, 16) if m else 0xFFFFFFFF))
    return words


def compile_pattern(p):
    parts = []
    for v, m in parse_pattern(p):
        for i in range(4):
            vb, mb = (v >> 8 * i) & 0xFF, (m >> 8 * i) & 0xFF
            if mb == 0xFF:
                parts.append(re.escape(bytes([vb])))
            elif mb == 0:
                parts.append(b'.')
            else:
                parts.append(b'[' + b''.join(re.escape(bytes([b])) for b in range(256) if b & mb == vb & mb) + b']')
    return re.compile(b''.join(parts), re.DOTALL)


# ------------------------------------------------------------------ a main module

class Main:
    def __init__(self, nso, base=MAIN_BASE):
        self.nso, self.base = nso, base
        self.text_off, self.text_size = nso.text
        self.text = bytes(nso.image[self.text_off:self.text_off + self.text_size])

    def word(self, a):
        return struct.unpack_from('<I', self.nso.image, a - self.base)[0]

    def find(self, pattern, limit=2):
        """Addresses (word-aligned, in .text) where the pattern matches; at most `limit`."""
        rx, out, pos = compile_pattern(pattern), [], 0
        while len(out) < limit:
            m = rx.search(self.text, pos)
            if not m:
                break
            if m.start() % 4:
                pos = m.start() + 1
                continue
            out.append(self.base + self.text_off + m.start())
            pos = m.start() + 4
        return out

    def target(self, kind, a):
        """What the site of this kind at instruction a is (see the module docstring)."""
        w = self.word(a)
        if kind == 'code':
            return a
        if kind == 'call':
            if (w & 0x7C000000) != 0x14000000:
                raise SiteError(f'{a:#x} is not a branch ({w:08x})')
            return a + sext(w & 0x3FFFFFF, 26) * 4
        if kind == 'imm':
            v = imm_value(w)
            if v is None:
                raise SiteError(f'{a:#x} has no immediate ({w:08x})')
            return v
        if is_adrp(w):
            v = adrp_page(w, a)
        else:
            lo = lo12(w)
            if not lo:
                raise SiteError(f'{a:#x} does not complete an address ({w:08x})')
            for b in range(a - 4, a - 4 * 33, -4):  # its ADRP
                pw = self.word(b)
                if is_adrp(pw) and (pw & 31) == lo[1]:
                    v = adrp_page(pw, b) + lo[0]
                    break
            else:
                raise SiteError(f'{a:#x}: no ADRP for x{lo[1]} above it')
        if kind == 'got':
            return self.base + struct.unpack_from('<Q', self.nso.image, v - self.base)[0]
        return v

    def locate(self, s):
        """(address, or None when the pattern doesn't find exactly one place; how many places it matches) of a site"""
        if s.kind == 'data':
            return self.base + self.nso.data[0], 1
        if s.kind == 'end':
            return self.base + self.nso.size, 1
        hits = []
        for p, at in s.pattern if isinstance(s.pattern, list) else [(s.pattern, s.at)] if s.pattern else []:
            hits = self.find(p)
            if len(hits) == 1:
                return self.target(s.kind, hits[0] + 4 * at), 1
        return None, len(hits)

    def text_words(self, a, n):
        return [self.word(a + 4 * i) for i in range(n)]

    def function_of(self, a):
        """(start, end) of the function holding a, from the module's unwind info (None: none there)."""
        import bisect
        from analyze import eh_frame_extents
        if not hasattr(self, 'fdes'):
            self.fdes = sorted((self.base + s, self.base + e) for s, e in eh_frame_extents(self.nso) if e > s)
        i = bisect.bisect_right(self.fdes, (a, 1 << 64)) - 1
        return self.fdes[i] if i >= 0 and a < self.fdes[i][1] else None

    def pattern_for(self, a, kind='code', shortest=8, longest=24):
        """A pattern that finds only a: (pattern, at). It stays inside a's function (the code around it may change
        on its own), starts as close above a as it can - at the ADRP for a ref or got site, whose address bits it
        masks then - and has `shortest` words at least (or the whole function): short ones are likelier to find
        another place in a new build."""
        f0, f1 = self.function_of(a) or (a - 64, a + 128)
        first = 0
        if kind in ('ref', 'got') and not is_adrp(self.word(a)):
            reg = lo12(self.word(a))[1]
            first = next(i for i in range(1, 33) if is_adrp(self.word(a - 4 * i)) and self.word(a - 4 * i) & 31 == reg)
        for back in range(first, (a - f0) // 4 + 1):
            s = a - 4 * back
            room = (f1 - s) // 4
            for n in range(min(max(shortest, back + 1), room), min(longest, room) + 1):
                p = make_pattern(self.text_words(s, n))
                if self.find(p) == [s]:
                    return p, back
        raise SiteError(f'no pattern inside its function finds only {a:#x}')


def common_pattern(ma, a, mb, b, kind='code', shortest=8, longest=32):
    """A pattern that finds only a in main module ma and only b in mb, the same code in two versions: the bits both
    keep (and make_pattern keeps). For an imm site the immediate itself is always masked. (pattern, at)"""
    fa, fb = ma.function_of(a) or (a - 64, a + 128), mb.function_of(b) or (b - 64, b + 128)
    first = 0
    if kind in ('ref', 'got') and not is_adrp(ma.word(a)):
        reg = lo12(ma.word(a))[1]
        first = next(i for i in range(1, 33) if is_adrp(ma.word(a - 4 * i)) and ma.word(a - 4 * i) & 31 == reg)
    for back in range(first, min(a - fa[0], b - fb[0]) // 4 + 1):
        sa, sb = a - 4 * back, b - 4 * back
        room = min(fa[1] - sa, fb[1] - sb) // 4
        for n in range(min(max(shortest, back + 1), room), min(longest, room) + 1):
            out = []
            for i, ((va, ka), (vb, kb)) in enumerate(zip(parse_pattern(make_pattern(ma.text_words(sa, n))),
                                                         parse_pattern(make_pattern(mb.text_words(sb, n))))):
                k = ka & kb & ~(va ^ vb) & 0xFFFFFFFF
                if kind == 'imm' and i == back:
                    k &= 0xFFE0001F if (va & 0x7F800000) == 0x52800000 else 0xFFC003FF
                out.append(f'{va & k:08x}' if k == 0xFFFFFFFF else f'{va & k:08x}/{k:08x}')
            p = ' '.join(out)
            if ma.find(p) == [sa] and mb.find(p) == [sb]:
                return p, back
    raise SiteError(f'no pattern inside both functions finds only {a:#x} and {b:#x}')


def resolve(main, known=None, log=None):
    """{site name: address} for this main module. known: the addresses listed for its build (or None)."""
    out, problems = {}, []
    for s in SITES:
        try:
            found, hits = main.locate(s)
        except SiteError as e:
            problems.append(f'{s.name}: {e}')
            continue
        # This experiment changes native object routing. A stale KNOWN address
        # must never turn it on after a failed signature check.
        if s.name in OPT_TWO_SITES and (found is None or
                                      (known and s.name in known and found != known[s.name])):
            if log:
                log(f'game_sites: {s.name}: spike signature did not match')
            continue
        k = (known or {}).get(s.name)
        if found is not None and k is not None and found != k:
            raise SiteError(f'{s.name}: the pattern finds {found:#x}, the table says {k:#x}')
        if found is None and k is None:
            if s.name in OPTIONAL:
                continue
            problems.append(f'{s.name}: the pattern matches {hits} places' + (' or more' if hits > 1 else ''))
            continue
        if found is None and log:
            log(f'game_sites: {s.name}: the pattern matches {hits} places; {k:#x} from the table')
        out[s.name] = found if found is not None else k
    if problems:
        raise SiteError('; '.join(problems))
    for g in OPTIONAL_GROUPS:
        missing = [n for n in g if n not in out]
        if not missing:
            continue
        if log:
            log(f'game_sites: {", ".join(missing)} not found: {", ".join(g)} left out')
        for n in g:
            out.pop(n, None)
    return out


def for_module(nso, base, allow_unsupported=False, log=None):
    """(version name, sites) for the main module nso at base. Refuses a build that VERSIONS doesn't support, unless
    allow_unsupported (bringing up a new version: its sites must then all be found by pattern)."""
    v = supported_version(nso.build_id)
    if not v or not v.supported:
        what = f'version {v.name}, not supported yet' if v else 'not a version Savage Wind knows'
        if not allow_unsupported:
            raise SiteError(f'main module build {nso.build_id[:16]}: {what}')
        if log:
            log(f'game_sites: main module build {nso.build_id[:16]}: {what}; sites by pattern only')
    name = v.name if v else nso.build_id[:16]
    return name, resolve(Main(nso, base), KNOWN.get(name) if v and v.supported else None, log)


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('find', 'pattern', 'common'):
        sys.exit(__doc__)
    from nso import Nso
    m = Main(Nso(sys.argv[2]))
    if sys.argv[1] == 'common':
        mb, a, b = Main(Nso(sys.argv[4])), int(sys.argv[3], 16), int(sys.argv[5], 16)
        kind = sys.argv[6] if len(sys.argv) > 6 else 'code'
        p, at = common_pattern(m, a, mb, b, kind)
        print(f"    Site('<name>', '{kind}', '{p}', {at}),  # -> {m.target(kind, a):#x} / {mb.target(kind, b):#x}")
        return
    if sys.argv[1] == 'pattern':
        a = int(sys.argv[3], 16)
        kind = sys.argv[4] if len(sys.argv) > 4 else 'code'
        p, at = m.pattern_for(a, kind)
        print(f"    Site('<name>', '{kind}', '{p}', {at}),  # -> {m.target(kind, a):#x}")
        return
    v = supported_version(m.nso.build_id)
    known = KNOWN.get(v.name, {}) if v else {}
    print(f'main module build {m.nso.build_id[:16]}: ' + (f'version {v.name}' + ('' if v.supported else
          ' (not supported yet)') if v else 'not in VERSIONS'))
    bad = 0
    for s in SITES:
        try:
            found, hits = m.locate(s)
        except SiteError as e:
            found, hits = None, str(e)
        k = known.get(s.name)
        state = (f'{hits} matches' if found is None else
                 'ok' if k == found else 'new' if k is None else f'TABLE SAYS {k:#x}')
        bad += state not in ('ok', 'new')
        print(f"        '{s.name}': {found:#x},  # {state}" if found is not None else
              f"        # '{s.name}': {state}" + (f' (table {k:#x})' if k is not None else ''))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
