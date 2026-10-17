#include <snes.h>
#include <string.h>
#include "modsprite.h"

/* The Modular Sprite Editor's SNES demo: it starts on the project's first scene (the Prince of Persia example's
   Swordfight) and shows everything else with one button each, no combinations:

   UP / DOWN     what to show: scenes, animations, frames, modules
   LEFT / RIGHT  previous / next (held: faster and faster)
   A             play / pause
   B             hitboxes and points (animations, frames)
   X             next look: every mapping with every palette swap, then (animations) the same animation twice,
                 the second re-skinned and recoloured through ms_draw_anim_player_as
   START         the controls and what the frame costs (time, sprites, tiles)

   The screen shows what is playing and the look; START opens the rest. Text costs time on the 65816 (816-tcc's code
   takes a couple of hundred cycles a character, about a seventh of a frame a row): a row is put together only when it
   changes, in one frame, and written in the next, with indices (816-tcc does not step pointers reliably), straight
   into the text map (consoleDrawText formats through vsprintf: about half a frame a row). The library's font has odd lower-case letters, so the text is
   in capitals.

   A streamed export (MS_STREAMED, see modsprite.h) draws through the default slot, and the side-by-side look's second
   character through a slot of its own; the tiles go into video memory right after WaitForVBlank (ms_upload_tiles). A
   text row waits for a frame whose uploads leave room for the text map in the vertical blank. */

enum
{
    VIEW_SCENE = 0,
    VIEW_ANIMATION = 1,
    VIEW_FRAME = 2,
    VIEW_MODULE = 3,
    VIEW_COUNT = 4,
};

#define UI_TEXT_COL 1
#define UI_TEXT_WIDTH 30       /* 32 columns, one left free on each side (a TV's border may hide them) */
#define UI_TEXT_LINES 27       /* rows 0 .. 26 */
#define LINE_BUFFER 72         /* a row while it is put together (the look can take two rows) */
#define NAME_MAX 24
#define ROW_TITLE 1
#define ROW_LOOK 2             /* and 3 when it does not fit */
#define ROW_STATUS 4
#define ROW_CONTROLS 6         /* the controls (START), 8 rows */
#define CONTROL_ROWS 8
#define ROW_NUMBERS 15         /* what the frame costs (START), 7 rows */
#define NUMBER_ROWS 7
#define ROW_HINT 25
#define PROFILE_UI_PERIOD 30   /* refresh the numbers twice a second */
#define FLASH_FRAMES 60        /* how long an event or a toggle stays on the status line */
#define REPEAT_DELAY 16        /* LEFT / RIGHT held: first repeat after this many frames, */
#define REPEAT_SLOW 4          /* then every 4 frames, */
#define REPEAT_FAST_AFTER 64   /* and every frame once held this long */
#define SPRITE_DRAW_X 128      /* where scenes and characters are drawn: centred, three quarters down (the editor's */
#define SPRITE_DRAW_Y 168      /* Timeline screen guide puts the scene origin there) */
#define SIDE_BY_SIDE_SPACING 40   /* the side-by-side look: the two characters this far left / right of the centre */
#define BACKDROP RGB5(12, 12, 12)
/* The most a frame's tile uploads may cost (bytes of DMA, ms_upload_queued) for the text map to go in the same vertical
   blank: PVSnesLib's interrupt sends it (2 KB, 12 scanlines) after the sprite table, before ms_upload_tiles. */
#define UPLOADS_WITH_TEXT 2688
#define REG_SLHV (*(vuint8 *)0x2137)
#define REG_OPVCT (*(vuint8 *)0x213D)

static u16 g_view = VIEW_SCENE;
static u16 g_index[VIEW_COUNT];
static u16 g_look = 0;        /* index into the looks: mapping + palette swap, or side by side */
static u8 g_pause = FALSE;
static u8 g_show_markers = FALSE;
static u8 g_show_panel = FALSE;
static u16 g_prev_pad = 0;
static u16 g_held_frames = 0;
/* The status line's message for a while: a text, or the events of the step that started (put together with the row). */
#define FLASH_EVENTS 2
static const char *g_flash_text = NULL;
static u16 g_flash_event_count = 0;
static u16 g_flash_event_type[FLASH_EVENTS];
static s16 g_flash_event_value[FLASH_EVENTS];
static u16 g_flash_frames = 0;
static const char *g_error = NULL;

/* The text: the rows to put together and write again, and the row put together (g_line from g_ready_from), which the
   next frame writes. */
static u8 g_row_dirty[UI_TEXT_LINES];
static u8 g_rows_dirty = FALSE;
static char g_line[LINE_BUFFER];
static u8 g_row_ready = FALSE;
static u16 g_ready_row = 0;
static u16 g_ready_from = 0;
static u16 g_profile_ui_counter = 0;

static MS_FrameProfile g_frame_profile;
static MS_FrameProfile g_disp_frame_profile;
static u16 g_draw_lines = 0;     /* scanlines the sprite list took this frame */
static u16 g_work_lines = 0;     /* scanlines the whole frame's work took */
static u16 g_loops = 0;          /* main loop passes since g_second_start */
static u16 g_second_start = 0;
static u16 g_fps = 0;
static u8 g_line_overflow = 0;   /* STAT77: 0x40 more than 32 sprites on a line, 0x80 more than 34 tiles */
static u16 g_disp_draw_lines = 0;
static u16 g_disp_work_lines = 0;
static u8 g_disp_overflow = 0;
static u8 g_latch;

static MS_AnimPlayer g_anim_player;
static MS_ScenePlayer g_scene_player;
static MS_Slot g_second_slot;      /* the side-by-side look's second character (streamed exports) */
static u16 g_period_uploads = 0;   /* the most tiles one frame uploaded since the numbers were last shown */
static u16 g_period_waits = 0;     /* draws that showed what their slot held, their upload waiting, since then */
static u16 g_disp_uploads = 0;
static u16 g_disp_waits = 0;

/* Hitbox / point overlay (B): corner marks for boxes and a cross for points, two colours of sprite palette 7 (the
   runtime's palettes start at 0; a project with eight palette entries shares it with the last). A mark is a small
   sprite whose top-left tile holds it, so it works with every pair of sprite sizes; it goes after the runtime's tiles. */
#define MARK_PALETTE 7
#define MARK_BOX_COLOUR 1
#define MARK_POINT_COLOUR 2
#define MARK_ATTR (0x30 | (MARK_PALETTE << 1))  /* priority 3, sprite palette 7 */
static u16 g_corner_tile = 0xFFFF;
static u16 g_cross_tile = 0xFFFF;
static u16 g_shown_boxes = 0;
static u16 g_shown_points = 0;
static u8 g_mark_rows[2][4 * 32];  /* the first row of tiles of each mark's block: the mark, then empty tiles */
static u8 g_empty_row[4 * 32];

static const char *const g_view_names[VIEW_COUNT] = {
    "SCENE",
    "ANIMATION",
    "FRAME",
    "MODULE",
};

static const char *const g_controls[CONTROL_ROWS] = {
    "UP/DOWN    SCENES, ANIMATIONS,",
    "           FRAMES, MODULES",
    "LEFT/RIGHT PREVIOUS, NEXT",
    "           (HOLD: FASTER)",
    "A          PLAY, PAUSE",
    "B          HITBOXES AND POINTS",
    "X          CHANGE THE LOOK",
    "START      CLOSE",
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

/* Small text writers: each appends to g_line at `at` (in capitals) and returns the new end. */
static u16 put_str(u16 at, const char *src)
{
    u16 i = 0;
    char c;

    while (src && at < LINE_BUFFER - 1)
    {
        c = src[i++];
        if (!c)
            break;
        if (c >= 'a' && c <= 'z')
            c -= 'a' - 'A';
        g_line[at++] = c;
    }
    g_line[at] = '\0';
    return at;
}

/* A name from the project, cut to NAME_MAX characters. */
static u16 put_name(u16 at, const char *src)
{
    u16 end = at + NAME_MAX < LINE_BUFFER - 1 ? at + NAME_MAX : LINE_BUFFER - 1;
    u16 i = 0;
    char c;

    while (src && at < end)
    {
        c = src[i++];
        if (!c)
            break;
        if (c >= 'a' && c <= 'z')
            c -= 'a' - 'A';
        g_line[at++] = c;
    }
    g_line[at] = '\0';
    return at;
}

/* A number in decimal, by subtracting powers of ten (a division is a library call on the 65816). */
static u16 put_u16(u16 at, u16 value)
{
    static const u16 powers[4] = { 10000, 1000, 100, 10 };
    u16 p, digit;
    u8 started = FALSE;

    for (p = 0; p < 4; p++)
    {
        digit = 0;
        while (value >= powers[p])
        {
            value -= powers[p];
            digit++;
        }
        if ((digit || started) && at < LINE_BUFFER - 2)
        {
            g_line[at++] = (char)('0' + digit);
            started = TRUE;
        }
    }
    g_line[at++] = (char)('0' + value);
    g_line[at] = '\0';
    return at;
}

/* "NORMAL + BLUE GUARD": the mapping and the palette swap of a combination ("ORIGINAL" for neither). */
static u16 put_combination(u16 at, u16 mapping, u16 swap)
{
    if (mapping == 0 && swap == 0)
        return put_str(at, "Original");
    if (mapping > 0)
        at = put_name(at, ms_mapping_name(mapping));
    if (mapping > 0 && swap > 0)
        at = put_str(at, " + ");
    if (swap > 0)
        at = put_name(at, ms_palette_swap_name(swap));
    return at;
}

/* The text map is PVSnesLib's (scr_txt_font_map, 32 x 32 BG map entries as consoleDrawText writes them: the
   character minus 32, with the priority bit); scr_txt_dirty sends it to video memory in the next vertical blank. */
#define TEXT_ENTRY(c) ((u16)((c) - 32) | 0x2000)

/* The row is put together: g_line from `from` (up to UI_TEXT_WIDTH characters) goes into it next frame. */
static void ui_write_row(u16 row, u16 from)
{
    g_ready_row = row;
    g_ready_from = from;
    g_row_ready = TRUE;
}

/* The row put together into the text map, padded with spaces. */
static void ui_put_ready_row(void)
{
    u16 *map = (u16 *)scr_txt_font_map;
    u16 at = (g_ready_row << 5) + UI_TEXT_COL;
    u8 ended = FALSE;
    u16 i;
    char c;

    for (i = 0; i < UI_TEXT_WIDTH; i++)
    {
        c = ' ';
        if (!ended)
        {
            c = g_line[g_ready_from + i];
            if (!c)
            {
                ended = TRUE;
                c = ' ';
            }
        }
        map[at + i] = TEXT_ENTRY(c);
    }
    scr_txt_dirty = 1;
    g_row_ready = FALSE;
}

static void ui_clear_row(u16 row)
{
    g_line[0] = '\0';
    ui_write_row(row, 0);
}

/* These rows change: they are put together again, one a frame. */
static void ui_mark(u16 first, u16 count)
{
    u16 row;

    for (row = first; row < first + count; row++)
        g_row_dirty[row] = TRUE;
    g_rows_dirty = TRUE;
}

static void demo_flash(const char *text)
{
    g_flash_text = text;
    g_flash_event_count = 0;
    g_flash_frames = FLASH_FRAMES;
    ui_mark(ROW_STATUS, 1);
}

/* SCENE  SWORDFIGHT              1/1 */
static void ui_title(void)
{
    static char counter[12];
    u16 count = demo_view_count(g_view);
    u16 index = g_index[g_view];
    u16 at, len, end, i;

    /* "1/68", put together at the end of g_line, then moved to the right edge */
    len = put_u16(UI_TEXT_WIDTH + 2, count ? (u16)(index + 1) : 0);
    len = put_str(len, "/");
    len = put_u16(len, count) - (UI_TEXT_WIDTH + 2);
    for (i = 0; i < len; i++)
        counter[i] = g_line[UI_TEXT_WIDTH + 2 + i];
    at = put_str(0, g_view_names[g_view]);
    at = put_str(at, "  ");
    if (count)
        at = put_name(at, demo_view_name(g_view, index));
    end = (u16)(UI_TEXT_WIDTH - len);
    if (at >= end)  /* a long name gives way to the counter */
        at = end > 0 ? (u16)(end - 1) : 0;
    while (at < end)
        g_line[at++] = ' ';
    for (i = 0; i < len; i++)
        g_line[at++] = counter[i];
    g_line[at] = '\0';
    ui_write_row(ROW_TITLE, 0);
}

/* LOOK: NORMAL + BLUE GUARD (over two rows when it does not fit one), or side by side LEFT: ORIGINAL and
   RIGHT: NORMAL + BLUE GUARD: `half` 0 or 1. */
static void ui_look(u16 half)
{
    u16 at, cut;

    if (g_look == 0)
    {
        ui_clear_row(ROW_LOOK + half);
        return;
    }
    if (demo_is_side_by_side())
    {
        if (half == 0)
            put_str(0, "Left:  Original");
        else
            put_combination(put_str(0, "Right: "), demo_second_mapping(), demo_second_swap());
        ui_write_row(ROW_LOOK + half, 0);
        return;
    }
    at = put_str(0, "Look: ");
    at = put_combination(at, demo_look_mapping(g_look), demo_look_swap(g_look));
    if (at <= UI_TEXT_WIDTH)
    {
        if (half)
            ui_clear_row(ROW_LOOK + 1);
        else
            ui_write_row(ROW_LOOK, 0);
        return;
    }
    cut = UI_TEXT_WIDTH;  /* broken at the last space that lets the first row hold the most */
    while (cut > 0 && g_line[cut] != ' ')
        cut--;
    if (cut == 0)
        cut = UI_TEXT_WIDTH;
    g_line[cut] = '\0';
    if (half)
        ui_write_row(ROW_LOOK + 1, cut + 1);
    else
        ui_write_row(ROW_LOOK, 0);
}

static void ui_status(void)
{
    u16 at = 0;
    u16 i;

    g_line[0] = '\0';
    if (g_error)
        put_str(0, g_error);
    else if (g_flash_frames && g_flash_event_count)
    {
        /* HIT, FOOTSTEP 2 */
        for (i = 0; i < g_flash_event_count; i++)
        {
            if (at)
                at = put_str(at, ", ");
            at = put_name(at, ms_event_name(g_flash_event_type[i]));
            if (g_flash_event_value[i] > 0)
            {
                at = put_str(at, " ");
                at = put_u16(at, (u16)g_flash_event_value[i]);
            }
        }
    }
    else if (g_flash_frames)
        put_str(0, g_flash_text);
    else if (g_pause)
        put_str(0, "Paused");
    ui_write_row(ROW_STATUS, 0);
}

/* Tenths of a millisecond in a number of scanlines (about 64 us each: 63.6 on NTSC, 64.1 on PAL). */
static u16 demo_lines_to_tenths(u16 lines)
{
    return (u16)((lines * 64u + 50u) / 100u);
}

/* The numbers' lines that only show when they apply, in order: whether one does, and its text into g_line. */
static u8 ui_optional_applies(u16 item)
{
    if (item == 0)
        return g_disp_frame_profile.sprites_dropped ? TRUE : FALSE;
    if (item == 1)
        return (g_disp_overflow & 0x40) ? TRUE : FALSE;
    if (item == 2)
        return (g_disp_overflow & 0x80) ? TRUE : FALSE;
    if (item == 3)
        return g_disp_waits ? TRUE : FALSE;
    return (g_show_markers && (g_view == VIEW_ANIMATION || g_view == VIEW_FRAME)) ? TRUE : FALSE;
}

static void ui_optional_line(u16 item)
{
    u16 at;

    if (item == 0)
    {
        at = put_u16(0, g_disp_frame_profile.sprites_dropped);
        put_str(at, " sprites over the 128");
    }
    else if (item == 1)
        put_str(0, "Over 32 sprites on a line");
    else if (item == 2)
        put_str(0, "Over 34 sprite tiles a line");
    else if (item == 3)
    {
        at = put_u16(0, g_disp_waits);
        put_str(at, g_disp_waits == 1 ? " draw waited for its tiles" : " draws waited for tiles");
    }
    else
    {
        at = put_u16(0, g_shown_boxes);
        at = put_str(at, g_shown_boxes == 1 ? " hitbox  " : " hitboxes  ");
        at = put_u16(at, g_shown_points);
        put_str(at, g_shown_points == 1 ? " point" : " points");
    }
}

/* The r-th line of what the frame costs (START). */
static void ui_number(u16 r)
{
    const MS_FrameProfile *prof = &g_disp_frame_profile;
    u16 at, tenths, whole, item, found;

    g_line[0] = '\0';
    if (!g_show_panel)
        ;
    else if (r == 0)
    {
        /* 60 FPS  CPU 21%  2.1 MS DRAW: the share of the frame the work took, and the sprite list's part of it */
        at = put_u16(0, g_fps);
        at = put_str(at, " fps  CPU ");
        at = put_u16(at, (u16)((g_disp_work_lines * 100u) / (snes_50hz ? 312u : 262u)));
        at = put_str(at, "%  ");
        tenths = demo_lines_to_tenths(g_disp_draw_lines);
        for (whole = 0; tenths >= 10; whole++)
            tenths -= 10;
        at = put_u16(at, whole);
        at = put_str(at, ".");
        at = put_u16(at, tenths);
        put_str(at, " ms draw");
    }
    else if (r == 1)
    {
        /* 26 PARTS  26 OF 128 SPRITES */
        at = put_u16(0, prof->parts_submitted);
        at = put_str(at, " parts  ");
        at = put_u16(at, prof->hw_sprites);
        put_str(at, " of 128 sprites");
    }
    else if (r == 2)
    {
        if (ms_slot_tiles())
        {
            /* streamed: 37 OF 64 SLOT TILES UPLOADED (the most one frame uploaded) */
            at = put_u16(0, g_disp_uploads);
            at = put_str(at, " of ");
            at = put_u16(at, ms_tiles_used());
            put_str(at, " slot tiles uploaded");
        }
        else
        {
            at = put_u16(0, ms_tiles_used());
            put_str(at, " of 512 sprite tiles");
        }
    }
    else
    {
        found = 3;
        for (item = 0; item < 5; item++)
        {
            if (!ui_optional_applies(item))
                continue;
            if (found == r)
            {
                ui_optional_line(item);
                break;
            }
            found++;
        }
    }
    ui_write_row(ROW_NUMBERS + r, 0);
}

static void ui_row(u16 row)
{
    if (row == ROW_TITLE)
        ui_title();
    else if (row == ROW_LOOK || row == ROW_LOOK + 1)
        ui_look(row - ROW_LOOK);
    else if (row == ROW_STATUS)
        ui_status();
    else if (row >= ROW_CONTROLS && row < ROW_CONTROLS + CONTROL_ROWS)
    {
        if (g_show_panel)
            put_str(0, g_controls[row - ROW_CONTROLS]);
        else
            g_line[0] = '\0';
        ui_write_row(row, 0);
    }
    else if (row >= ROW_NUMBERS && row < ROW_NUMBERS + NUMBER_ROWS)
        ui_number(row - ROW_NUMBERS);
    else if (row == ROW_HINT)
    {
        put_str(0, g_show_panel ? "" : "START: controls");
        ui_write_row(ROW_HINT, 0);
    }
    else
        ui_clear_row(row);
}

/* A frame either writes the row put together in the last one or puts the first row that changed together. */
static void ui_update(void)
{
    u16 row;

    if (g_row_ready)
    {
        if (ms_upload_queued() <= UPLOADS_WITH_TEXT)  /* else the next frame: the tiles first */
            ui_put_ready_row();
        return;
    }
    if (!g_rows_dirty)
        return;
    for (row = 0; row < UI_TEXT_LINES; row++)
    {
        if (g_row_dirty[row])
        {
            g_row_dirty[row] = FALSE;
            ui_row(row);
            return;
        }
    }
    g_rows_dirty = FALSE;
}

/* ------------------------------------------------------------------ timing */

/* The scanline the PPU is on (its V counter, latched by reading SLHV). */
static u16 demo_scanline(void)
{
    u16 v;

    g_latch = REG_SLHV;
    g_latch = REG_STAT78;  /* the next OPVCT read gives the low byte */
    v = REG_OPVCT;
    v |= (u16)(REG_OPVCT & 1) << 8;
    return v;
}

/* Scanlines since `start`, across the end of the frame (262 lines a frame on NTSC, 312 on PAL). */
static u16 demo_lines_since(u16 start)
{
    u16 now = demo_scanline();

    return now >= start ? (u16)(now - start) : (u16)(now + (snes_50hz ? 312 : 262) - start);
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
    s16 value;

    if (count == 0)
        return;
    value = (s16)g_index[g_view] + delta;
    if (value < 0)
        value += (s16)count;
    if (value >= (s16)count)
        value -= (s16)count;
    g_index[g_view] = (u16)value;
    demo_restart_player();
    ui_mark(ROW_TITLE, 1);
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
    ui_mark(ROW_TITLE, 3);  /* the title and the look */
    ui_mark(ROW_NUMBERS, NUMBER_ROWS);
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
        demo_flash("No mappings or swaps to show");
        return;
    }
    g_look = (u16)((g_look + 1) % count);
    demo_apply_look();
    ui_mark(ROW_LOOK, 2);
}

static void demo_toggle_markers(void)
{
    g_show_markers = !g_show_markers;
    if (!g_show_markers)
        g_flash_frames = 0;
    else if (g_corner_tile == 0xFFFF)
        demo_flash("No room for the marks' tiles");
    else if (g_view == VIEW_ANIMATION || g_view == VIEW_FRAME)
        demo_flash("Hitboxes and points");
    else
        demo_flash("Shown in animations, frames");
    ui_mark(ROW_STATUS, 1);
    ui_mark(ROW_NUMBERS, NUMBER_ROWS);
}

/* The events of a step, on the status line when the step starts ("HIT", "FOOTSTEP 2"). */
static void demo_report_events(const MS_AnimPlayer *player)
{
    u16 i;
    u16 count;

    if (!player->step_started)
        return;
    count = ms_anim_player_event_count(player);
    if (count == 0)
        return;
    g_flash_event_count = 0;
    for (i = 0; i < count && g_flash_event_count < FLASH_EVENTS; i++)
    {
        const MS_StepEvent *event = ms_anim_player_event(player, i);

        if (!event)
            continue;
        g_flash_event_type[g_flash_event_count] = event->type;
        g_flash_event_value[g_flash_event_count] = event->value;
        g_flash_event_count++;
    }
    g_flash_frames = FLASH_FRAMES;
    ui_mark(ROW_STATUS, 1);
}

/* ------------------------------------------------------------------ hitboxes and points */

/* The first block of side x side tiles (aligned to side in both directions, 16 tiles to a row) at or after tile
   `from`, or 0xFFFF when the sprite tables are full. */
static u16 demo_free_block(u16 from, u16 side)
{
    u16 row = from >> 4;
    u16 col = from & 15;

    if (row & (side - 1))
    {
        row = (row + side) & ~(side - 1);
        col = 0;
    }
    else
    {
        col = (col + side - 1) & ~(side - 1);
        if (col >= 16)
        {
            row += side;
            col = 0;
        }
    }
    if (row >= 32)
        return 0xFFFF;
    return (row << 4) | col;
}

/* Put one mark's block of tiles into video memory (the screen is off). */
static void demo_load_mark(u16 tile, u16 side, u8 *first_row)
{
    u16 r, address;

    address = ms_tile_base() + (tile << 4);
    dmaCopyVram(first_row, address, side * 32);
    for (r = 1; r < side; r++)
    {
        address += 16 << 4;  /* the next row of tiles: 16 tiles of 16 words further */
        dmaCopyVram(g_empty_row, address, side * 32);
    }
}

static void demo_init_markers(void)
{
    u16 side = MS_SMALL_SIZE >> 3;
    u16 row;

    memset(g_mark_rows, 0, sizeof(g_mark_rows));
    memset(g_empty_row, 0, sizeof(g_empty_row));
    for (row = 0; row < 8; row++)
    {
        /* 4 bpp planar: per row a byte of plane 0 and of plane 1, then (16 bytes on) planes 2 and 3 */
        g_mark_rows[0][row * 2] = row == 0 ? 0xFF : 0x80;   /* a corner in colour 1 (plane 0) */
        if (row == 3)
            g_mark_rows[1][row * 2 + 1] = 0xFE;              /* a cross in colour 2 (plane 1) */
        else if (row < 7)
            g_mark_rows[1][row * 2 + 1] = 0x10;
    }
    g_corner_tile = demo_free_block(ms_tiles_end() + ms_slot_tiles(), side);  /* after the second slot (streamed) */
    g_cross_tile = g_corner_tile == 0xFFFF ? 0xFFFF : demo_free_block(g_corner_tile + 1, side);
    if (g_cross_tile == 0xFFFF)
    {
        g_corner_tile = 0xFFFF;
        return;
    }
    demo_load_mark(g_corner_tile, side, g_mark_rows[0]);
    demo_load_mark(g_cross_tile, side, g_mark_rows[1]);
    setPaletteColor(128 + MARK_PALETTE * 16 + MARK_BOX_COLOUR, RGB5(31, 8, 8));
    setPaletteColor(128 + MARK_PALETTE * 16 + MARK_POINT_COLOUR, RGB5(8, 31, 12));
}

/* Marks go into the sprite list before the character, so they show on top of it; a corner mark flipped is the other
   corners. */
static void demo_draw_markers(const MS_Hitbox *boxes, u16 box_count, const MS_Point *points, u16 point_count, s16 ox,
                              s16 oy)
{
    u16 i;

    if (box_count != g_shown_boxes || point_count != g_shown_points)
    {
        g_shown_boxes = box_count;
        g_shown_points = point_count;
        if (g_show_markers && g_show_panel)
            ui_mark(ROW_NUMBERS, NUMBER_ROWS);
    }
    if (!g_show_markers || g_corner_tile == 0xFFFF)
        return;
    for (i = 0; i < point_count; i++)
        ms_add_hw_sprite(ox + points[i].x - 3, oy + points[i].y - 3, g_cross_tile, MARK_ATTR, FALSE);
    for (i = 0; i < box_count; i++)
    {
        s16 x0 = ox + boxes[i].x;
        s16 y0 = oy + boxes[i].y;
        s16 x1 = x0 + boxes[i].w - MS_SMALL_SIZE;
        s16 y1 = y0 + boxes[i].h - MS_SMALL_SIZE;

        ms_add_hw_sprite(x0, y0, g_corner_tile, MARK_ATTR, FALSE);
        ms_add_hw_sprite(x1, y0, g_corner_tile, MARK_ATTR | 0x40, FALSE);
        ms_add_hw_sprite(x0, y1, g_corner_tile, MARK_ATTR | 0x80, FALSE);
        ms_add_hw_sprite(x1, y1, g_corner_tile, MARK_ATTR | 0xC0, FALSE);
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
                ui_mark(ROW_TITLE, 1);
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
    u16 pad = padsCurrent(0);
    u16 press = pad & ~g_prev_pad;
    u16 held_step = 0;

    g_prev_pad = pad;
    /* LEFT / RIGHT: one step per press; held, it repeats, then runs. */
    if (pad & (KEY_LEFT | KEY_RIGHT))
    {
        g_held_frames++;
        if (g_held_frames >= REPEAT_FAST_AFTER)
            held_step = 1;
        else if (g_held_frames >= REPEAT_DELAY && ((g_held_frames - REPEAT_DELAY) % REPEAT_SLOW) == 0)
            held_step = 1;
    }
    else
        g_held_frames = 0;
    if ((press & KEY_LEFT) || (held_step && (pad & KEY_LEFT)))
        demo_browse(-1);
    if ((press & KEY_RIGHT) || (held_step && (pad & KEY_RIGHT)))
        demo_browse(1);

    if (press & KEY_UP)
        demo_switch_view(-1);
    if (press & KEY_DOWN)
        demo_switch_view(1);
    if (press & KEY_A)
    {
        g_pause = !g_pause;
        ui_mark(ROW_STATUS, 1);
    }
    if (press & KEY_B)
        demo_toggle_markers();
    if (press & KEY_X)
        demo_next_look();
    if (press & KEY_START)
    {
        g_show_panel = !g_show_panel;
        ui_mark(ROW_CONTROLS, CONTROL_ROWS);
        ui_mark(ROW_NUMBERS, NUMBER_ROWS);
        ui_mark(ROW_HINT, 1);
    }
}

int main(void)
{
    u16 view;
    u16 start;

    consoleInitDefaultText(0);
    bgSetGfxPtr(0, 0x3000);
    bgSetMapPtr(0, 0x6800, SC_32x32);
    setMode(BG_MODE1, 0);
    bgSetDisable(1);
    bgSetDisable(2);
    setPaletteColor(0, BACKDROP);
    memset(scr_txt_font_map, 0, sizeof(scr_txt_font_map));  /* blank: the library does not clear it */
    scr_txt_dirty = 1;
    ms_init();  /* sprite tiles at 0x0000-0x1FFF, the palette entries in sprite palettes 0, 1, ... */
    ms_slot_init(&g_second_slot, ms_tiles_end());  /* after the default slot (streamed) */
    demo_init_markers();
    /* PVSnesLib's start-up code leaves RAM as the console powered on: what C would start at zero starts here. */
    for (view = 0; view < VIEW_COUNT; view++)
        g_index[view] = 0;
    memset(g_row_dirty, 0, sizeof(g_row_dirty));
    memset(&g_disp_frame_profile, 0, sizeof(g_disp_frame_profile));
    /* Start on the first scene (the Swordfight in the Prince of Persia example), or the first thing there is. */
    g_view = VIEW_COUNT - 1;
    demo_switch_view(1);
    ms_anim_player_init(&g_anim_player, 0);
    ms_scene_player_init(&g_scene_player, 0);
    demo_apply_look();
    if (!ms_palettes_fit())
        g_error = "More palettes than the 8";
    ui_mark(ROW_TITLE, 4);  /* the title, the look, the status */
    ui_mark(ROW_HINT, 1);
    setScreenOn();

    while (1)
    {
        start = demo_scanline();
        demo_input();
        ms_begin_frame();
        g_draw_lines = demo_scanline();
        demo_draw();
        ms_end_frame();
        g_draw_lines = demo_lines_since(g_draw_lines);
        ms_get_frame_profile(&g_frame_profile);
        if (g_frame_profile.tiles_uploaded > g_period_uploads)
            g_period_uploads = g_frame_profile.tiles_uploaded;
        g_period_waits += g_frame_profile.uploads_waiting;
        if (g_flash_frames && --g_flash_frames == 0)
            ui_mark(ROW_STATUS, 1);
        ui_update();
        g_work_lines = demo_lines_since(start);
        WaitForVBlank();
        ms_upload_tiles();             /* right after the vertical blank starts: the slots' new tiles (streamed), */
        ms_palette_tick();             /* then the colour cycles turn */
        g_line_overflow |= REG_STAT77 & 0xC0;  /* the last frame's sprite lines (cleared when the blank ends) */
        g_loops++;
        if ((u16)(snes_vblank_count - g_second_start) >= snes_fps)
        {
            g_fps = g_loops;
            g_loops = 0;
            g_second_start = snes_vblank_count;
        }
        g_profile_ui_counter++;
        if (g_profile_ui_counter >= PROFILE_UI_PERIOD)
        {
            g_profile_ui_counter = 0;
            g_disp_draw_lines = g_draw_lines;
            g_disp_work_lines = g_work_lines;
            g_disp_frame_profile = g_frame_profile;
            g_disp_overflow = g_line_overflow;
            g_line_overflow = 0;
            g_disp_uploads = g_period_uploads;
            g_disp_waits = g_period_waits;
            g_period_uploads = 0;
            g_period_waits = 0;
            if (g_show_panel)
                ui_mark(ROW_NUMBERS, NUMBER_ROWS);  /* the numbers only show with the panel */
        }
    }
    return 0;
}
