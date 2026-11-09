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
