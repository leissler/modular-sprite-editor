#include <genesis.h>
#include <string.h>
#include "modsprite.h"

/* The Modular Sprite Editor demo: it starts on the project's first scene (the Prince of Persia example's Swordfight)
   and shows everything else with one button each, no combinations:

   UP / DOWN     what to show: scenes, animations, frames, modules
   LEFT / RIGHT  previous / next (held: faster and faster)
   A             play / pause
   B             hitboxes and points (animations, frames)
   C             next look: every mapping with every palette swap, then (animations) the same animation twice,
                 the second re-skinned and recoloured through ms_draw_anim_player_as
   START         the controls and what the frame costs (time, sprites, tiles)

   The screen shows what is playing and the look; START opens the rest. A streamed export (MS_STREAMED, see modsprite.h)
   draws through the default slot, and the side-by-side look's second character through a slot of its own. */

enum
{
    VIEW_SCENE = 0,
    VIEW_ANIMATION = 1,
    VIEW_FRAME = 2,
    VIEW_MODULE = 3,
    VIEW_COUNT = 4,
};

#define UI_TEXT_COL 1
#define UI_TEXT_WIDTH 39
#define UI_TEXT_LINES 27
#define LINE_BUFFER 96          /* a line while it is put together: names are cut to NAME_MAX, the screen to the width */
#define NAME_MAX 30
#define ROW_TITLE 0
#define ROW_LOOK 1
#define ROW_STATUS 2
#define ROW_PANEL 4          /* the controls and the numbers (START) */
#define ROW_HINT 26
#define PROFILE_UI_PERIOD 30   /* refresh the numbers twice a second */
#define UI_LINES_PER_FRAME 1   /* text lines redrawn per frame: drawing many in one frame drops it */
#define FLASH_FRAMES 60        /* how long an event or a toggle stays on the status line */
#define REPEAT_DELAY 16        /* LEFT / RIGHT held: first repeat after this many frames, */
#define REPEAT_SLOW 4          /* then every 4 frames, */
#define REPEAT_FAST_AFTER 64   /* and every frame once held this long */
#define SPRITE_DRAW_X 160
#define SPRITE_DRAW_Y 168
#define SIDE_BY_SIDE_SPACING 48   /* the side-by-side look: the two characters this far left / right of the centre */
#define BACKDROP_LUMA 96

static u16 g_view = VIEW_SCENE;
static u16 g_index[VIEW_COUNT];
static u16 g_look = 0;        /* index into the looks: mapping + palette swap, or side by side */
static u8 g_pause = FALSE;
static u8 g_show_markers = FALSE;
static u8 g_show_panel = FALSE;
static u16 g_prev_pad = 0;
static u16 g_held_frames = 0;
static char g_flash[UI_TEXT_WIDTH + 1];
static u16 g_flash_frames = 0;
static const char *g_error = NULL;

static char g_ui_cache[UI_TEXT_LINES][UI_TEXT_WIDTH + 1];   /* what is on screen */
static char g_ui_target[UI_TEXT_LINES][UI_TEXT_WIDTH + 1];  /* what should be */
static u8 g_ui_pending = FALSE;  /* the targets changed and the screen does not show all of them yet */
static u8 g_ui_dirty = TRUE;
static u16 g_profile_ui_counter = 0;

static MS_FrameProfile g_frame_profile;
static MS_FrameProfile g_disp_frame_profile;
static u16 g_render_lines = 0;
static u16 g_update_lines = 0;
static u32 g_fps = 0;
static u16 g_cpu_load = 0;
static u32 g_disp_render_us = 0;
static u32 g_disp_update_us = 0;
static u32 g_disp_fps = 0;
static u16 g_disp_cpu_load = 0;

static MS_AnimPlayer g_anim_player;
static MS_ScenePlayer g_scene_player;
static MS_Slot g_second_slot;      /* the side-by-side look's second character (streamed exports) */
static u16 g_period_uploads = 0;   /* the most tiles one frame uploaded since the numbers were last shown */
static u16 g_disp_uploads = 0;

/* Hitbox / point overlay (B): corner marks for boxes and a cross for points, in two colours of PAL0 (the demo's own
   line, with the backdrop and the text): the sprites' palette lines start at PAL1, a palette swap's included. */
#define MARK_BOX_COLOUR 13
#define MARK_POINT_COLOUR 14
static u16 g_marker_tile = 0;
static u16 g_shown_boxes = 0;
static u16 g_shown_points = 0;

static const char *const g_view_names[VIEW_COUNT] = {
    "SCENE",
    "ANIMATION",
    "FRAME",
    "MODULE",
};

/* ------------------------------------------------------------------ what there is to show */

static u16 demo_view_count(u16 view)
{
    if (view == VIEW_SCENE)
        return (u16)MS_SCENE_COUNT;
    if (view == VIEW_ANIMATION)
        return (u16)MS_ANIMATION_COUNT;
    if (view == VIEW_FRAME)
        return (u16)MS_FRAME_COUNT;
    return (u16)MS_MODULE_COUNT;
}

static const char *demo_view_name(u16 view, u16 index)
{
    if (view == VIEW_SCENE)
        return ms_scene_name(index);
    if (view == VIEW_ANIMATION)
        return ms_animation_name(index);
    if (view == VIEW_FRAME)
        return ms_frame_name(index);
    return ms_module_name(index);
}

static u16 demo_mapping_count(void)
{
    return MS_MAPPING_COUNT > 0 ? (u16)MS_MAPPING_COUNT : 1;
}

static u16 demo_swap_count(void)
{
    return MS_PALETTE_SWAP_COUNT > 0 ? (u16)MS_PALETTE_SWAP_COUNT : 1;
}

/* The looks: every mapping with every palette swap (mapping 0 and swap 0 are the original), then, for animations,
   the side-by-side look when there is anything to compare. */
static u16 demo_combination_count(void)
{
    return (u16)(demo_mapping_count() * demo_swap_count());
}

static u8 demo_has_side_by_side(void)
{
    return g_view == VIEW_ANIMATION && demo_combination_count() > 1;
}

static u16 demo_look_count(void)
{
    return (u16)(demo_combination_count() + (demo_has_side_by_side() ? 1 : 0));
}

static u8 demo_is_side_by_side(void)
{
    return demo_has_side_by_side() && g_look == demo_combination_count();
}

static u16 demo_look_mapping(u16 look)
{
    return (u16)(look % demo_mapping_count());
}

static u16 demo_look_swap(u16 look)
{
    return (u16)(look / demo_mapping_count());
}

/* The right one of the side-by-side look: the first mapping with the first palette swap (the Prince of Persia
   example's guard in blue). */
static u16 demo_second_mapping(void)
{
    return demo_mapping_count() > 1 ? 1 : 0;
}

static u16 demo_second_swap(void)
{
    return demo_swap_count() > 1 ? 1 : 0;
}

/* ------------------------------------------------------------------ text */

/* Small text writers: sprintf with 32-bit numbers divides in software on the 68000 and made one HUD
   refresh take most of a frame; 16-bit division is a single instruction. */
static char *put_str(char *dst, const char *src)
{
    while (src && *src)
        *dst++ = *src++;
    *dst = '\0';
    return dst;
}

/* A name from the project, cut to NAME_MAX characters. */
static char *put_name(char *dst, const char *src)
{
    u16 n = 0;

    while (src && src[n] && n < NAME_MAX)
    {
        *dst++ = src[n];
        n++;
    }
    *dst = '\0';
    return dst;
}

static char *put_u16(char *dst, u16 value)
{
    char digits[5];
    u16 n = 0;

    do
    {
        digits[n++] = (char)('0' + (value % 10));
        value /= 10;
    } while (value);
    while (n)
        *dst++ = digits[--n];
    *dst = '\0';
    return dst;
}

static u16 clamp_u16(u32 value)
{
    return value > 0xFFFFu ? 0xFFFFu : (u16)value;
}

/* "Normal + Blue guard": the mapping and the palette swap of a combination ("Original" for neither). */
static char *put_combination(char *dst, u16 mapping, u16 swap)
{
    if (mapping == 0 && swap == 0)
        return put_str(dst, "Original");
    if (mapping > 0)
        dst = put_name(dst, ms_mapping_name(mapping));
    if (mapping > 0 && swap > 0)
        dst = put_str(dst, " + ");
    if (swap > 0)
        dst = put_name(dst, ms_palette_swap_name(swap));
    return dst;
}

static void demo_flash(const char *text)
{
    strncpy(g_flash, text ? text : "", UI_TEXT_WIDTH);
    g_flash[UI_TEXT_WIDTH] = '\0';
    g_flash_frames = FLASH_FRAMES;
    g_ui_dirty = TRUE;
}

static void demo_ui_format_padded(char *dst, const char *src)
{
    u16 i = 0;

    while (src && i < UI_TEXT_WIDTH && src[i])
    {
        dst[i] = src[i];
        i++;
    }
    while (i < UI_TEXT_WIDTH)
        dst[i++] = ' ';
    dst[UI_TEXT_WIDTH] = '\0';
}

/* Draw a few changed lines per frame (the cache starts empty, so every line is drawn once); nothing to
   compare once the screen shows all targets. */
static void demo_ui_flush(u16 max_lines)
{
    u16 row;

    if (!g_ui_pending)
        return;
    for (row = 0; row < UI_TEXT_LINES; row++)
    {
        if (strcmp(g_ui_cache[row], g_ui_target[row]) != 0)
        {
            if (max_lines == 0)
                return;
            VDP_drawText(g_ui_target[row], UI_TEXT_COL, row);
            strcpy(g_ui_cache[row], g_ui_target[row]);
            max_lines--;
        }
    }
    g_ui_pending = FALSE;
}

static void draw_panel(char lines[UI_TEXT_LINES][LINE_BUFFER])
{
    const MS_FrameProfile *prof = &g_disp_frame_profile;
    char *p;
    u16 row = ROW_PANEL;

    put_str(lines[row++], "UP/DOWN     scenes, animations, frames,");
    put_str(lines[row++], "            modules");
    put_str(lines[row++], "LEFT/RIGHT  previous, next (hold: fast)");
    put_str(lines[row++], "A           play, pause");
    put_str(lines[row++], "B           hitboxes and points");
    put_str(lines[row++], "C           change the look");
    put_str(lines[row++], "START       close");
    row++;

    /* 60 fps  CPU 21%  2.2 ms to draw: the sprite list and its upload, a frame lasts 16.7 ms */
    {
        u16 tenths = clamp_u16((g_disp_render_us + g_disp_update_us + 50) / 100);
        p = put_u16(lines[row], clamp_u16(g_disp_fps));
        p = put_str(p, " fps  CPU ");
        p = put_u16(p, g_disp_cpu_load);
        p = put_str(p, "%  ");
        p = put_u16(p, (u16)(tenths / 10));
        p = put_str(p, ".");
        p = put_u16(p, (u16)(tenths % 10));
        put_str(p, " ms to draw");
    }
    row++;
    /* 26 parts  26 of 80 sprites  305 tiles */
    p = put_u16(lines[row], prof->parts_submitted);
    p = put_str(p, " parts  ");
    p = put_u16(p, prof->hw_sprites);
    p = put_str(p, " of 80 sprites  ");
    p = put_u16(p, ms_tiles_used());
    put_str(p, " tiles");
    row++;
    if (ms_slot_tiles())
    {
        /* streamed: up to 39 tiles a frame uploaded */
        p = put_str(lines[row], "streamed: up to ");
        p = put_u16(p, g_disp_uploads);
        put_str(p, " tiles a frame uploaded");
        row++;
    }
    if (prof->sprites_dropped)
    {
        p = put_u16(lines[row], prof->sprites_dropped);
        put_str(p, " sprites dropped: more than 80 at once");
        row++;
    }
    if (g_show_markers && (g_view == VIEW_ANIMATION || g_view == VIEW_FRAME))
    {
        p = put_u16(lines[row], g_shown_boxes);
        p = put_str(p, g_shown_boxes == 1 ? " hitbox  " : " hitboxes  ");
        p = put_u16(p, g_shown_points);
        put_str(p, g_shown_points == 1 ? " point" : " points");
    }
}

static void draw_ui(void)
{
    static char lines[UI_TEXT_LINES][LINE_BUFFER];
    char counter[12];
    char *p;
    u16 row;
    u16 count = demo_view_count(g_view);
    u16 index = g_index[g_view];

    if (!g_ui_dirty)
        return;
    for (row = 0; row < UI_TEXT_LINES; row++)
        lines[row][0] = '\0';

    /* SCENE  Swordfight                  1/1 */
    p = put_str(lines[ROW_TITLE], g_view_names[g_view]);
    p = put_str(p, "  ");
    if (count)
        put_name(p, demo_view_name(g_view, index));
    p = put_u16(counter, count ? (u16)(index + 1) : 0);
    p = put_str(p, "/");
    put_u16(p, count);
    {
        u16 len = (u16)strlen(lines[ROW_TITLE]);
        u16 at = (u16)(UI_TEXT_WIDTH - strlen(counter));
        while (len < at)
            lines[ROW_TITLE][len++] = ' ';
        if (len > at)  /* a long name gives way to the counter */
            len = at > 0 ? (u16)(at - 1) : 0;
        put_str(lines[ROW_TITLE] + len, counter);
    }

    if (g_look > 0)
    {
        p = put_str(lines[ROW_LOOK], "Look: ");
        if (demo_is_side_by_side())
        {
            p = put_str(p, "Original | ");
            put_combination(p, demo_second_mapping(), demo_second_swap());
        }
        else
            put_combination(p, demo_look_mapping(g_look), demo_look_swap(g_look));
    }

    if (g_error)
        put_str(lines[ROW_STATUS], g_error);
    else if (g_flash_frames)
        put_str(lines[ROW_STATUS], g_flash);
    else if (g_pause)
        put_str(lines[ROW_STATUS], "Paused");

    if (g_show_panel)
        draw_panel(lines);
    else
        put_str(lines[ROW_HINT], "START: controls");

    for (row = 0; row < UI_TEXT_LINES; row++)
        demo_ui_format_padded(g_ui_target[row], lines[row]);
    g_ui_pending = TRUE;
    g_ui_dirty = FALSE;
}

/* ------------------------------------------------------------------ timing */

/* Timing in scanlines from the VDP's V counter (getSubTick() only advances per scanline and jumps around vblank).
   The 8-bit counter wraps from 255 to 0, so spans shorter than a frame come out right modulo 256. */
static u16 demo_lines_since(u16 start)
{
    return (u16)((GET_VCOUNTER - start) & 0xFF);
}

static u32 demo_lines_to_us(u16 lines)
{
    /* One scanline is 64 us on PAL and 63.56 us on NTSC. */
    if (IS_PAL_SYSTEM)
        return (u32)lines * 64u;
    return ((u32)lines * 6356u + 50u) / 100u;
}

/* ------------------------------------------------------------------ actions */

static void demo_apply_look(void);

static void demo_restart_player(void)
{
    if (g_view == VIEW_ANIMATION)
        ms_anim_player_init(&g_anim_player, g_index[VIEW_ANIMATION]);
    else if (g_view == VIEW_SCENE)
        ms_scene_player_init(&g_scene_player, g_index[VIEW_SCENE]);
}

static void demo_browse(s16 delta)
{
    u16 count = demo_view_count(g_view);
    s32 value;

    if (count == 0)
        return;
    value = (s32)g_index[g_view] + delta;
    while (value < 0)
        value += count;
    while (value >= count)
        value -= count;
    g_index[g_view] = (u16)value;
    demo_restart_player();
    g_ui_dirty = TRUE;
}

/* UP / DOWN: the next view that has something to show. */
static void demo_switch_view(s16 delta)
{
    u16 tries;

    for (tries = 0; tries < VIEW_COUNT; tries++)
    {
        g_view = (u16)((g_view + VIEW_COUNT + delta) % VIEW_COUNT);
        if (demo_view_count(g_view) > 0)
            break;
    }
    if (g_look >= demo_look_count())
    {
        g_look = 0;  /* side by side is for animations only */
        demo_apply_look();
    }
    demo_restart_player();
    g_ui_dirty = TRUE;
}

static void demo_apply_look(void)
{
    if (demo_is_side_by_side())
    {
        ms_set_mapping(0);
        ms_set_palette_swap(0);
    }
    else
    {
        ms_set_mapping(demo_look_mapping(g_look));
        ms_set_palette_swap(demo_look_swap(g_look));
    }
}

static void demo_next_look(void)
{
    u16 count = demo_look_count();

    if (count <= 1)
    {
        demo_flash("This project has no mappings or swaps");
        return;
    }
    g_look = (u16)((g_look + 1) % count);
    demo_apply_look();
    g_ui_dirty = TRUE;
}

static void demo_toggle_markers(void)
{
    g_show_markers = !g_show_markers;
    if (!g_show_markers)
        g_flash_frames = 0;
    else if (g_view == VIEW_ANIMATION || g_view == VIEW_FRAME)
        demo_flash("Hitboxes and points");
    else
        demo_flash("Hitboxes show in animations and frames");
    g_ui_dirty = TRUE;
}

/* The events of a step, on the status line when the step starts ("hit", "footstep 2"). */
static void demo_report_events(const MS_AnimPlayer *player)
{
    char msg[UI_TEXT_WIDTH + 1];
    char *p = msg;
    u16 i;
    u16 count;

    if (!player->step_started)
        return;
    count = ms_anim_player_event_count(player);
    if (count == 0)
        return;
    msg[0] = '\0';
    for (i = 0; i < count; i++)
    {
        const MS_StepEvent *event = ms_anim_player_event(player, i);

        if (!event || (u16)(p - msg) > UI_TEXT_WIDTH - 20)
            continue;
        if (p != msg)
            p = put_str(p, ", ");
        p = put_name(p, ms_event_name(event->type));
        if (event->value > 0)
        {
            p = put_str(p, " ");
            p = put_u16(p, (u16)event->value);
        }
    }
    demo_flash(msg);
}

/* ------------------------------------------------------------------ hitboxes and points */

/* Five 8x8 marks: box corners (top-left, top-right, bottom-left, bottom-right), point cross. */
static void demo_init_markers(void)
{
    u32 tiles[5 * 8];
    u16 t, row, col;

    for (t = 0; t < 5; t++)
    {
        for (row = 0; row < 8; row++)
        {
            u32 line = 0;
            for (col = 0; col < 8; col++)
            {
                u8 on;
                if (t == 0) on = (row == 0 || col == 0);
                else if (t == 1) on = (row == 0 || col == 7);
                else if (t == 2) on = (row == 7 || col == 0);
                else if (t == 3) on = (row == 7 || col == 7);
                else on = ((row == 3 && col <= 6) || (col == 3 && row <= 6));
                if (on)
                    line |= (u32)(t < 4 ? MARK_BOX_COLOUR : MARK_POINT_COLOUR) << ((7 - col) * 4);
            }
            tiles[t * 8 + row] = line;
        }
    }
    g_marker_tile = ms_tile_base() + ms_tiles_used();
    /* CPU, not DMA: a release build (link-time optimisation) sees that SGDK's DMA never reads this array in C and
       drops the stores that fill it. */
    VDP_loadTileData(tiles, g_marker_tile, 5, CPU);
    PAL_setColor(PAL0 * 16 + MARK_BOX_COLOUR, RGB24_TO_VDPCOLOR(0xFF4040));
    PAL_setColor(PAL0 * 16 + MARK_POINT_COLOUR, RGB24_TO_VDPCOLOR(0x40FF60));
}

/* Marks go into the sprite list before the character, so they show on top of it. */
static void demo_draw_markers(const MS_Hitbox *boxes, u16 box_count, const MS_Point *points, u16 point_count, s16 ox, s16 oy)
{
    u16 i;

    g_shown_boxes = box_count;
    g_shown_points = point_count;
    if (!g_show_markers)
        return;
    for (i = 0; i < point_count; i++)
        ms_add_hw_sprite(ox + points[i].x - 3, oy + points[i].y - 3, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL0, TRUE, FALSE, FALSE, g_marker_tile + 4));
    for (i = 0; i < box_count; i++)
    {
        s16 x0 = ox + boxes[i].x;
        s16 y0 = oy + boxes[i].y;
        s16 x1 = x0 + boxes[i].w - 8;
        s16 y1 = y0 + boxes[i].h - 8;
        ms_add_hw_sprite(x0, y0, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL0, TRUE, FALSE, FALSE, g_marker_tile + 0));
        ms_add_hw_sprite(x1, y0, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL0, TRUE, FALSE, FALSE, g_marker_tile + 1));
        ms_add_hw_sprite(x0, y1, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL0, TRUE, FALSE, FALSE, g_marker_tile + 2));
        ms_add_hw_sprite(x1, y1, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL0, TRUE, FALSE, FALSE, g_marker_tile + 3));
    }
}

/* ------------------------------------------------------------------ drawing */

static void demo_draw(void)
{
    const MS_Hitbox *boxes;
    const MS_Point *points;
    u16 index = g_index[g_view];

    if (demo_view_count(g_view) == 0)
        return;
    if (g_view == VIEW_SCENE)
    {
        if (!g_pause)
            ms_scene_player_tick(&g_scene_player);
        ms_draw_scene_player(&g_scene_player, SPRITE_DRAW_X, SPRITE_DRAW_Y);
    }
    else if (g_view == VIEW_ANIMATION)
    {
        s16 x = demo_is_side_by_side() ? (SPRITE_DRAW_X - SIDE_BY_SIDE_SPACING) : SPRITE_DRAW_X;
        u16 nb, np;

        if (!g_pause)
        {
            u16 before = g_anim_player.animation_index;
            ms_anim_player_tick(&g_anim_player);
            if (g_anim_player.animation_index != before)
            {
                /* The animation ended and its follow-up took over. */
                g_index[VIEW_ANIMATION] = g_anim_player.animation_index;
                g_ui_dirty = TRUE;
            }
            demo_report_events(&g_anim_player);
        }
        nb = ms_anim_player_hitboxes(&g_anim_player, &boxes);
        np = ms_anim_player_points(&g_anim_player, &points);
        demo_draw_markers(boxes, nb, points, np, x, SPRITE_DRAW_Y);
        ms_draw_anim_player(&g_anim_player, x, SPRITE_DRAW_Y);
        if (demo_is_side_by_side())  /* one animation, re-skinned and recoloured for this draw only */
        {
            ms_set_slot(&g_second_slot);
            ms_draw_anim_player_as(&g_anim_player, demo_second_mapping(), demo_second_swap(),
                                   SPRITE_DRAW_X + SIDE_BY_SIDE_SPACING, SPRITE_DRAW_Y);
            ms_set_slot(NULL);
        }
    }
    else if (g_view == VIEW_FRAME)
    {
        u16 nb = ms_frame_hitboxes(index, &boxes);
        u16 np = ms_frame_points(index, &points);
        demo_draw_markers(boxes, nb, points, np, SPRITE_DRAW_X, SPRITE_DRAW_Y);
        ms_draw_frame(index, SPRITE_DRAW_X, SPRITE_DRAW_Y);
    }
    else
        ms_draw_module(index, SPRITE_DRAW_X, SPRITE_DRAW_Y);
}

/* ------------------------------------------------------------------ input */

static void demo_input(void)
{
    u16 pad;
    u16 press;
    u16 held_step = 0;

    JOY_update();
    pad = JOY_readJoypad(JOY_1);
    press = pad & ~g_prev_pad;
    g_prev_pad = pad;

    /* LEFT / RIGHT: one step per press; held, it repeats, then runs. */
    if (pad & (BUTTON_LEFT | BUTTON_RIGHT))
    {
        g_held_frames++;
        if (g_held_frames >= REPEAT_FAST_AFTER)
            held_step = 1;
        else if (g_held_frames >= REPEAT_DELAY && ((g_held_frames - REPEAT_DELAY) % REPEAT_SLOW) == 0)
            held_step = 1;
    }
    else
        g_held_frames = 0;
    if ((press & BUTTON_LEFT) || (held_step && (pad & BUTTON_LEFT)))
        demo_browse(-1);
    if ((press & BUTTON_RIGHT) || (held_step && (pad & BUTTON_RIGHT)))
        demo_browse(1);

    if (press & BUTTON_UP)
        demo_switch_view(-1);
    if (press & BUTTON_DOWN)
        demo_switch_view(1);
    if (press & BUTTON_A)
    {
        g_pause = !g_pause;
        g_ui_dirty = TRUE;
    }
    if (press & BUTTON_B)
        demo_toggle_markers();
    if (press & BUTTON_C)
        demo_next_look();
    if (press & BUTTON_START)
    {
        g_show_panel = !g_show_panel;
        g_ui_dirty = TRUE;
    }
}

int main(bool hardReset)
{
    u16 view;

    VDP_setScreenWidth320();
    PAL_setColor(0, RGB24_TO_VDPCOLOR(((u32)BACKDROP_LUMA << 16) | ((u32)BACKDROP_LUMA << 8) | BACKDROP_LUMA));
    VDP_setBackgroundColor(0);
    JOY_init();
    ms_init();
    demo_init_markers();
    ms_slot_init(&g_second_slot, g_marker_tile + 5);  /* after the marks */
    for (view = 0; view < VIEW_COUNT; view++)
        g_index[view] = 0;
    /* Start on the first scene (the Swordfight in the Prince of Persia example), or the first thing there is. */
    g_view = VIEW_COUNT - 1;
    demo_switch_view(1);
    ms_anim_player_init(&g_anim_player, 0);
    ms_scene_player_init(&g_scene_player, 0);
    demo_apply_look();
    if (!ms_data_is_ready())
        g_error = "Error: blob load failed";
    else if (!ms_tiles_fit())
        g_error = "Error: tiles do not fit in VRAM";

    while (1)
    {
        demo_input();

        ms_begin_frame();
        g_render_lines = GET_VCOUNTER;
        demo_draw();
        g_render_lines = demo_lines_since(g_render_lines);
        ms_get_frame_profile(&g_frame_profile);
        if (g_frame_profile.tiles_uploaded > g_period_uploads)
            g_period_uploads = g_frame_profile.tiles_uploaded;
        g_fps = SYS_getFPS();
        g_cpu_load = SYS_getCPULoad();
        if (g_flash_frames && --g_flash_frames == 0)
            g_ui_dirty = TRUE;
        draw_ui();
        demo_ui_flush(UI_LINES_PER_FRAME);
        g_update_lines = GET_VCOUNTER;
        ms_end_frame();
        g_update_lines = demo_lines_since(g_update_lines);
        ms_palette_tick();  /* colour cycles turn once per video frame */
        SYS_doVBlankProcess();
        g_profile_ui_counter++;
        if (g_profile_ui_counter >= PROFILE_UI_PERIOD)
        {
            g_profile_ui_counter = 0;
            g_disp_fps = g_fps;
            g_disp_cpu_load = g_cpu_load;
            g_disp_render_us = demo_lines_to_us(g_render_lines);
            g_disp_update_us = demo_lines_to_us(g_update_lines);
            g_disp_frame_profile = g_frame_profile;
            g_disp_uploads = g_period_uploads;
            g_period_uploads = 0;
            if (g_show_panel)
                g_ui_dirty = TRUE;  /* the numbers only show with the panel */
        }
    }

    return 0;
}
