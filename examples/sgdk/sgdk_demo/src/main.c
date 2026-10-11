#include <genesis.h>
#include <string.h>
#include "modsprite.h"

enum
{
    DEMO_UNIT_MODULE = 0,
    DEMO_UNIT_FRAME = 1,
    DEMO_UNIT_ANIMATION = 2,
    DEMO_UNIT_SCENE = 3,
};

#define ID_EDIT_MAX 31
#define UI_TEXT_COL 1
#define UI_TEXT_WIDTH 39
#define UI_TEXT_LINES 14
#define PROFILE_UI_PERIOD 30   /* refresh the numbers twice a second */
#define UI_LINES_PER_FRAME 1   /* text lines redrawn per frame: drawing many in one frame drops it */
#define SPRITE_DRAW_X 160
#define SPRITE_DRAW_Y 168
#define HUD_TOGGLE_BUTTONS (BUTTON_MODE | BUTTON_Z)

static u16 g_unit = DEMO_UNIT_ANIMATION;
static u16 g_mapping_index = 0;
static u8 g_bg_luma = 96;
static u16 g_index_module = 0;
static u16 g_index_frame = 0;
static u16 g_index_animation = 0;
static u16 g_index_scene = 0;
static u16 g_prev_pad = 0;
/* START is also a modifier: it cycles the mapping on release, unless another button was pressed while held. */
static u8 g_start_chord = FALSE;
static u8 g_pause = FALSE;
static u8 g_minimal_hud = FALSE;
static u8 g_id_edit_mode = FALSE;
static u16 g_id_cursor = 0;
static char g_id_edit[ID_EDIT_MAX + 1];
static char g_status_line[40];
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

/* Hitbox / point overlay (START+A): corner marks for boxes (PAL2) and a cross for points (PAL3). */
static u8 g_show_markers = FALSE;
static u16 g_marker_tile = 0;
static u16 g_shown_boxes = 0;
static u16 g_shown_points = 0;

static const char *const g_unit_names[] = {
    "Module",
    "Frame",
    "Animation",
    "Scene",
};

static const char g_id_chars[] =
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_-x";

static u8 demo_is_hud_toggle_pressed(u16 pad, u16 press)
{
    if (press & HUD_TOGGLE_BUTTONS)
        return TRUE;
    if ((pad & BUTTON_START) && (press & BUTTON_C))
        return TRUE;
    return FALSE;
}

static u16 demo_unit_count(u16 unit)
{
    if (unit == DEMO_UNIT_MODULE)
        return (u16)MS_MODULE_COUNT;
    if (unit == DEMO_UNIT_FRAME)
        return (u16)MS_FRAME_COUNT;
    if (unit == DEMO_UNIT_ANIMATION)
        return (u16)MS_ANIMATION_COUNT;
    return (u16)MS_SCENE_COUNT;
}

static u16 *demo_unit_index_ptr(u16 unit)
{
    if (unit == DEMO_UNIT_MODULE)
        return &g_index_module;
    if (unit == DEMO_UNIT_FRAME)
        return &g_index_frame;
    if (unit == DEMO_UNIT_ANIMATION)
        return &g_index_animation;
    return &g_index_scene;
}

static const char *demo_unit_id(u16 unit, u16 index)
{
    if (unit == DEMO_UNIT_MODULE)
        return ms_module_id(index);
    if (unit == DEMO_UNIT_FRAME)
        return ms_frame_id(index);
    if (unit == DEMO_UNIT_ANIMATION)
        return ms_animation_id(index);
    return ms_scene_id(index);
}

static const char *demo_unit_name(u16 unit, u16 index)
{
    if (unit == DEMO_UNIT_MODULE)
        return ms_module_name(index);
    if (unit == DEMO_UNIT_FRAME)
        return ms_frame_name(index);
    if (unit == DEMO_UNIT_ANIMATION)
        return ms_animation_name(index);
    return ms_scene_name(index);
}

static s16 demo_find_index_by_id(u16 unit, const char *id)
{
    if (unit == DEMO_UNIT_MODULE)
        return ms_find_module_index_by_id(id);
    if (unit == DEMO_UNIT_FRAME)
        return ms_find_frame_index_by_id(id);
    if (unit == DEMO_UNIT_ANIMATION)
        return ms_find_animation_index_by_id(id);
    return ms_find_scene_index_by_id(id);
}

static void demo_set_status(const char *text)
{
    strncpy(g_status_line, text ? text : "", sizeof(g_status_line) - 1);
    g_status_line[sizeof(g_status_line) - 1] = '\0';
    g_ui_dirty = TRUE;
}

static void demo_ui_format_padded(char *dst, const char *src)
{
    u16 i = 0;

    if (src)
    {
        while (i < UI_TEXT_WIDTH && src[i])
        {
            dst[i] = src[i];
            i++;
        }
    }

    while (i < UI_TEXT_WIDTH)
    {
        dst[i] = ' ';
        i++;
    }
    dst[UI_TEXT_WIDTH] = '\0';
}

static void demo_ui_present(char lines[UI_TEXT_LINES][UI_TEXT_WIDTH + 1])
{
    u16 row;

    for (row = 0; row < UI_TEXT_LINES; row++)
        demo_ui_format_padded(g_ui_target[row], lines[row]);
    g_ui_pending = TRUE;
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

static void demo_apply_bg_color(void)
{
    u32 rgb24;

    rgb24 = ((u32)g_bg_luma << 16) | ((u32)g_bg_luma << 8) | (u32)g_bg_luma;
    PAL_setColor(0, RGB24_TO_VDPCOLOR(rgb24));
    VDP_setBackgroundColor(0);
}

static void demo_change_bg_luma(s16 delta)
{
    s16 next;

    next = (s16)g_bg_luma + delta;
    if (next < 24)
        next = 24;
    if (next > 208)
        next = 208;
    g_bg_luma = (u8)next;
    demo_apply_bg_color();
}

static u16 demo_mapping_count(void)
{
    if (MS_MAPPING_COUNT == 0)
        return 1;
    return (u16)MS_MAPPING_COUNT;
}

static const char *demo_mapping_name(u16 mapping_index)
{
    if ((MS_MAPPING_COUNT == 0) || (mapping_index >= MS_MAPPING_COUNT))
        return "";
    return ms_mapping_name(mapping_index);
}

static void demo_cycle_mapping(s16 delta)
{
    u16 count;
    s32 next;

    if (MS_MAPPING_COUNT == 0)
        return;

    count = (u16)MS_MAPPING_COUNT;
    next = (s32)g_mapping_index + (s32)delta;
    while (next < 0)
        next += count;
    while (next >= count)
        next -= count;

    g_mapping_index = (u16)next;
    g_ui_dirty = TRUE;
}

/* Show the events of a step on the status line when the step starts. */
static void demo_report_events(const MS_AnimPlayer *player)
{
    char msg[64];
    char number[8];
    u16 i;
    u16 count;
    u16 len;

    if (!player->step_started)
        return;
    count = ms_anim_player_event_count(player);
    if (count == 0)
        return;
    strcpy(msg, "Event:");
    len = (u16)strlen(msg);
    for (i = 0; i < count; i++)
    {
        const MS_StepEvent *event = ms_anim_player_event(player, i);
        const char *name;
        u16 n;

        if (!event)
            continue;
        name = ms_event_name(event->type);
        if ((u16)(len + 1 + 12 + 1 + 6 + 1) >= (u16)sizeof(msg))
            break;
        msg[len++] = ' ';
        for (n = 0; name[n] && n < 12; n++)
            msg[len++] = name[n];
        if (event->value != 0)
        {
            msg[len++] = '=';
            sprintf(number, "%d", (s16)event->value);
            for (n = 0; number[n] && n < 6; n++)
                msg[len++] = number[n];
        }
        msg[len] = '\0';
    }
    demo_set_status(msg);
}

static void demo_sync_players(void)
{
    ms_set_mapping(g_mapping_index);
    ms_anim_player_init(&g_anim_player, g_index_animation);
    ms_scene_player_init(&g_scene_player, g_index_scene);
}

static void demo_prefill_id_editor(void)
{
    const char *id;

    id = demo_unit_id(g_unit, *demo_unit_index_ptr(g_unit));
    strncpy(g_id_edit, id ? id : "", sizeof(g_id_edit) - 1);
    g_id_edit[sizeof(g_id_edit) - 1] = '\0';
    g_id_cursor = (u16)strlen(g_id_edit);
    if (g_id_cursor > ID_EDIT_MAX)
        g_id_cursor = ID_EDIT_MAX;
    g_ui_dirty = TRUE;
}

static void demo_change_index(s16 delta)
{
    u16 count;
    u16 *index_ptr;
    s32 value;

    count = demo_unit_count(g_unit);
    index_ptr = demo_unit_index_ptr(g_unit);
    if (count == 0)
    {
        *index_ptr = 0;
        return;
    }

    value = (s32)(*index_ptr) + (s32)delta;
    while (value < 0)
        value += count;
    while (value >= count)
        value -= count;
    *index_ptr = (u16)value;

    if (g_unit == DEMO_UNIT_ANIMATION)
        ms_anim_player_init(&g_anim_player, *index_ptr);
    else if (g_unit == DEMO_UNIT_SCENE)
        ms_scene_player_init(&g_scene_player, *index_ptr);
    g_ui_dirty = TRUE;
}

static u16 demo_char_index(char ch)
{
    u16 i;

    for (i = 0; g_id_chars[i]; i++)
    {
        if (g_id_chars[i] == ch)
            return i;
    }
    return 0;
}

static void demo_cycle_id_char(s16 delta)
{
    u16 max_chars;
    u16 idx;
    s16 next;
    char ch;

    if (g_id_cursor >= ID_EDIT_MAX)
        return;

    ch = g_id_edit[g_id_cursor];
    if (ch == '\0')
    {
        g_id_edit[g_id_cursor] = g_id_chars[0];
        if ((g_id_cursor + 1) <= ID_EDIT_MAX)
            g_id_edit[g_id_cursor + 1] = '\0';
        ch = g_id_edit[g_id_cursor];
    }

    idx = demo_char_index(ch);
    max_chars = (u16)strlen(g_id_chars);
    next = (s16)idx + delta;
    while (next < 0)
        next += (s16)max_chars;
    while (next >= (s16)max_chars)
        next -= (s16)max_chars;
    g_id_edit[g_id_cursor] = g_id_chars[next];
    g_ui_dirty = TRUE;
}

static void demo_backspace_id_char(void)
{
    u16 len;
    u16 i;

    len = (u16)strlen(g_id_edit);
    if (len == 0)
        return;
    if (g_id_cursor > 0)
        g_id_cursor--;
    if (g_id_cursor >= len)
    {
        g_id_edit[len - 1] = '\0';
        g_ui_dirty = TRUE;
        return;
    }
    for (i = g_id_cursor; i < len; i++)
        g_id_edit[i] = g_id_edit[i + 1];
    g_ui_dirty = TRUE;
}

static void demo_apply_id_jump(void)
{
    s16 found;
    u16 *index_ptr;
    char msg[40];

    found = demo_find_index_by_id(g_unit, g_id_edit);
    if (found < 0)
    {
        sprintf(msg, "ID not found: %s", g_id_edit);
        demo_set_status(msg);
        return;
    }

    index_ptr = demo_unit_index_ptr(g_unit);
    *index_ptr = (u16)found;

    if (g_unit == DEMO_UNIT_ANIMATION)
        ms_anim_player_init(&g_anim_player, *index_ptr);
    else if (g_unit == DEMO_UNIT_SCENE)
        ms_scene_player_init(&g_scene_player, *index_ptr);

    sprintf(msg, "Jumped to %s", g_id_edit);
    demo_set_status(msg);
}

/* Five 8×8 marks in colour 1: box corners (top-left, top-right, bottom-left, bottom-right), point cross. */
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
                    line |= 1ul << ((7 - col) * 4);
            }
            tiles[t * 8 + row] = line;
        }
    }
    g_marker_tile = ms_tile_base() + ms_tiles_used();
    VDP_loadTileData(tiles, g_marker_tile, 5, DMA);
    PAL_setColor(PAL2 * 16 + 1, RGB24_TO_VDPCOLOR(0xFF4040));
    PAL_setColor(PAL3 * 16 + 1, RGB24_TO_VDPCOLOR(0x40FF60));
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
        ms_add_hw_sprite(ox + points[i].x - 3, oy + points[i].y - 3, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL3, TRUE, FALSE, FALSE, g_marker_tile + 4));
    for (i = 0; i < box_count; i++)
    {
        s16 x0 = ox + boxes[i].x;
        s16 y0 = oy + boxes[i].y;
        s16 x1 = x0 + boxes[i].w - 8;
        s16 y1 = y0 + boxes[i].h - 8;
        ms_add_hw_sprite(x0, y0, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL2, TRUE, FALSE, FALSE, g_marker_tile + 0));
        ms_add_hw_sprite(x1, y0, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL2, TRUE, FALSE, FALSE, g_marker_tile + 1));
        ms_add_hw_sprite(x0, y1, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL2, TRUE, FALSE, FALSE, g_marker_tile + 2));
        ms_add_hw_sprite(x1, y1, SPRITE_SIZE(1, 1), TILE_ATTR_FULL(PAL2, TRUE, FALSE, FALSE, g_marker_tile + 3));
    }
}

/* Small text writers: sprintf with 32-bit numbers divides in software on the 68000 and made one HUD
   refresh take most of a frame; 16-bit division is a single instruction. */
static char *put_str(char *dst, const char *src)
{
    while (src && *src)
        *dst++ = *src++;
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

static void draw_ui(void)
{
    char lines[UI_TEXT_LINES][UI_TEXT_WIDTH + 1];
    char *p;
    const MS_FrameProfile *prof = &g_disp_frame_profile;
    u16 count;
    u16 index;
    u16 row;

    if (!g_ui_dirty)
        return;

    for (row = 0; row < UI_TEXT_LINES; row++)
        lines[row][0] = '\0';

    p = put_str(lines[0], "FPS:");
    p = put_u16(p, clamp_u16(g_disp_fps));
    p = put_str(p, " CPU:");
    p = put_u16(p, g_disp_cpu_load);
    p = put_str(p, "% Draw:");
    p = put_u16(p, clamp_u16(g_disp_render_us));
    p = put_str(p, "us Upload:");
    p = put_u16(p, clamp_u16(g_disp_update_us));
    put_str(p, "us");
    if (g_minimal_hud)
    {
        demo_ui_present(lines);
        g_ui_dirty = FALSE;
        return;
    }

    count = demo_unit_count(g_unit);
    index = *demo_unit_index_ptr(g_unit);

    if (!g_id_edit_mode)
    {
        p = put_str(lines[1], g_unit_names[g_unit]);
        p = put_str(p, " ");
        p = put_u16(p, (u16)(index + 1));
        p = put_str(p, "/");
        put_u16(p, count);
        p = put_str(lines[2], "Name: ");
        put_str(p, demo_unit_name(g_unit, index));
        p = put_str(lines[3], "ID: ");
        put_str(p, demo_unit_id(g_unit, index));
        p = put_str(lines[4], "Mapping ");
        p = put_u16(p, (u16)(g_mapping_index + 1));
        p = put_str(p, "/");
        p = put_u16(p, demo_mapping_count());
        p = put_str(p, ": ");
        put_str(p, demo_mapping_name(g_mapping_index));

        p = put_str(lines[6], "Parts:");
        p = put_u16(p, prof->parts_submitted);
        p = put_str(p, " Sprites:");
        p = put_u16(p, prof->hw_sprites);
        p = put_str(p, " Dropped:");
        put_u16(p, prof->sprites_dropped);
        p = put_str(lines[7], "Boxes:");
        p = put_u16(p, g_shown_boxes);
        p = put_str(p, " Points:");
        p = put_u16(p, g_shown_points);
        p = put_str(p, " Tiles:");
        put_u16(p, ms_tiles_used());

        put_str(lines[9], "UP/DOWN unit  LEFT/RIGHT +/-1");
        put_str(lines[10], "X/Y +/-10     A pause   B reset");
        put_str(lines[11], "START map  START+UP/DN bg  C jump");
        put_str(lines[12], g_show_markers ? "START+A boxes ON  MODE/Z minimal HUD" : "START+A boxes  MODE/Z minimal HUD");
    }
    else
    {
        put_str(lines[1], "ID Jump Editor");
        p = put_str(lines[2], "Target Unit: ");
        put_str(p, g_unit_names[g_unit]);
        p = put_str(lines[3], "ID: ");
        put_str(p, g_id_edit);
        for (row = 0; row < 39; row++)
            lines[4][row] = ' ';
        lines[4][39] = '\0';
        if ((g_id_cursor + 4) < 39)
            lines[4][g_id_cursor + 4] = '^';
        put_str(lines[9], "UP/DOWN char  LEFT/RIGHT cursor");
        put_str(lines[10], "A apply  B cancel  X clear  Y bksp");
    }

    put_str(lines[13], g_status_line);
    demo_ui_present(lines);
    g_ui_dirty = FALSE;
}

int main(void)
{
    u16 pad;
    u16 press;
    u16 release;

    VDP_setScreenWidth320();
    demo_apply_bg_color();
    JOY_init();
    JOY_setSupport(PORT_1, JOY_SUPPORT_6BTN);
    JOY_setSupport(PORT_2, JOY_SUPPORT_OFF);
    ms_init();
    demo_init_markers();
    demo_sync_players();
    if (!ms_data_is_ready())
        demo_set_status("Error: blob load failed");
    else if (!ms_tiles_fit())
        demo_set_status("Error: tiles do not fit in VRAM");
    else
        demo_set_status("Ready with mapping <none>");

    while (1)
    {
        u8 toggle_hud;

        JOY_update();
        pad = JOY_readJoypad(JOY_1);
        press = pad & ~g_prev_pad;
        release = g_prev_pad & ~pad;
        g_prev_pad = pad;
        toggle_hud = demo_is_hud_toggle_pressed(pad, press);
        if (press & BUTTON_START)
            g_start_chord = FALSE;
        if ((pad & BUTTON_START) && (press & ~BUTTON_START))
            g_start_chord = TRUE;

        if (!g_id_edit_mode)
        {
            u8 consumed_up = FALSE;
            u8 consumed_down = FALSE;

            if ((pad & BUTTON_START) && (press & BUTTON_UP))
            {
                char msg[40];
                demo_change_bg_luma(16);
                sprintf(msg, "BG brightness: %u", g_bg_luma);
                demo_set_status(msg);
                consumed_up = TRUE;
            }
            if ((pad & BUTTON_START) && (press & BUTTON_DOWN))
            {
                char msg[40];
                demo_change_bg_luma(-16);
                sprintf(msg, "BG brightness: %u", g_bg_luma);
                demo_set_status(msg);
                consumed_down = TRUE;
            }

            if ((press & BUTTON_UP) && !consumed_up)
            {
                g_unit = (u16)((g_unit + 3) & 3);
                g_ui_dirty = TRUE;
                demo_set_status("Changed unit");
            }
            if ((press & BUTTON_DOWN) && !consumed_down)
            {
                g_unit = (u16)((g_unit + 1) & 3);
                g_ui_dirty = TRUE;
                demo_set_status("Changed unit");
            }
            if (press & BUTTON_LEFT)
                demo_change_index(-1);
            if (press & BUTTON_RIGHT)
                demo_change_index(1);
            if (press & BUTTON_X)
                demo_change_index(-10);
            if (press & BUTTON_Y)
                demo_change_index(10);
            if ((release & BUTTON_START) && !g_start_chord)
            {
                char msg[40];
                demo_cycle_mapping(1);
                demo_sync_players();
                sprintf(msg, "Mapping: %s", demo_mapping_name(g_mapping_index));
                demo_set_status(msg);
            }

            if ((press & BUTTON_A) && (pad & BUTTON_START))
            {
                g_show_markers = !g_show_markers;
                g_ui_dirty = TRUE;
                demo_set_status(g_show_markers ? "Hitboxes and points shown" : "Hitboxes and points hidden");
            }
            else if (press & BUTTON_A)
            {
                g_pause = !g_pause;
                demo_set_status(g_pause ? "Paused" : "Playing");
            }
            if (press & BUTTON_B)
            {
                demo_sync_players();
                demo_set_status("Playback reset");
            }
            if ((press & BUTTON_C) && !toggle_hud)
            {
                g_id_edit_mode = TRUE;
                g_ui_dirty = TRUE;
                demo_prefill_id_editor();
                demo_set_status("Edit ID then press A");
            }
            if (toggle_hud)
            {
                g_minimal_hud = !g_minimal_hud;
                g_id_edit_mode = FALSE;
                g_ui_dirty = TRUE;
                demo_set_status(g_minimal_hud ? "HUD: minimal" : "HUD: full");
            }
        }
        else
        {
            if (press & BUTTON_LEFT)
            {
                if (g_id_cursor > 0)
                    g_id_cursor--;
                g_ui_dirty = TRUE;
            }
            if (press & BUTTON_RIGHT)
            {
                if (g_id_cursor < ID_EDIT_MAX)
                    g_id_cursor++;
                g_ui_dirty = TRUE;
            }
            if (press & BUTTON_UP)
                demo_cycle_id_char(1);
            if (press & BUTTON_DOWN)
                demo_cycle_id_char(-1);
            if (press & BUTTON_Y)
                demo_backspace_id_char();
            if (press & BUTTON_X)
            {
                g_id_edit[0] = '\0';
                g_id_cursor = 0;
                g_ui_dirty = TRUE;
            }
            if (press & BUTTON_B)
            {
                g_id_edit_mode = FALSE;
                demo_set_status("Canceled ID jump");
            }
            if (press & BUTTON_A)
            {
                g_id_edit_mode = FALSE;
                demo_apply_id_jump();
            }
            if (toggle_hud)
            {
                g_minimal_hud = !g_minimal_hud;
                g_id_edit_mode = FALSE;
                g_ui_dirty = TRUE;
                demo_set_status(g_minimal_hud ? "HUD: minimal" : "HUD: full");
            }
        }

        ms_begin_frame();

        g_render_lines = GET_VCOUNTER;
        if (g_unit == DEMO_UNIT_MODULE)
        {
            if (MS_MODULE_COUNT > 0)
                ms_draw_module(g_index_module, SPRITE_DRAW_X, SPRITE_DRAW_Y);
        }
        else if (g_unit == DEMO_UNIT_FRAME)
        {
            if (MS_FRAME_COUNT > 0)
            {
                const MS_Hitbox *boxes;
                const MS_Point *points;
                u16 nb = ms_frame_hitboxes(g_index_frame, &boxes);
                u16 np = ms_frame_points(g_index_frame, &points);
                demo_draw_markers(boxes, nb, points, np, SPRITE_DRAW_X, SPRITE_DRAW_Y);
                ms_draw_frame(g_index_frame, SPRITE_DRAW_X, SPRITE_DRAW_Y);
            }
        }
        else if (g_unit == DEMO_UNIT_ANIMATION)
        {
            if (MS_ANIMATION_COUNT > 0)
            {
                if (!g_pause)
                {
                    u16 before = g_anim_player.animation_index;
                    ms_anim_player_tick(&g_anim_player);
                    if (g_anim_player.animation_index != before)
                    {
                        /* The animation ended and its follow-up took over. */
                        g_index_animation = g_anim_player.animation_index;
                        demo_set_status("Continues with follow-up");
                    }
                    demo_report_events(&g_anim_player);
                }
                {
                    const MS_Hitbox *boxes;
                    const MS_Point *points;
                    u16 nb = ms_anim_player_hitboxes(&g_anim_player, &boxes);
                    u16 np = ms_anim_player_points(&g_anim_player, &points);
                    demo_draw_markers(boxes, nb, points, np, SPRITE_DRAW_X, SPRITE_DRAW_Y);
                }
                ms_draw_anim_player(&g_anim_player, SPRITE_DRAW_X, SPRITE_DRAW_Y);
            }
        }
        else
        {
            if (MS_SCENE_COUNT > 0)
            {
                if (!g_pause)
                    ms_scene_player_tick(&g_scene_player);
                ms_draw_scene_player(&g_scene_player, SPRITE_DRAW_X, SPRITE_DRAW_Y);
            }
        }
        g_render_lines = demo_lines_since(g_render_lines);
        ms_get_frame_profile(&g_frame_profile);
        g_fps = SYS_getFPS();
        g_cpu_load = SYS_getCPULoad();
        draw_ui();
        demo_ui_flush(UI_LINES_PER_FRAME);
        g_update_lines = GET_VCOUNTER;
        ms_end_frame();
        g_update_lines = demo_lines_since(g_update_lines);
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
            g_ui_dirty = TRUE;
        }
    }

    return 0;
}
