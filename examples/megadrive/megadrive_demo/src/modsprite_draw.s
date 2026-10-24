/* The Mega Drive runtime's draw loops in 68000 assembly: modsprite.c decides how a render frame is drawn and calls
   them to put its pieces into the sprite table when it has MS_ASM_SPRITES hardware sprites or more (a smaller one
   draws faster through its C loops). Those C loops, all it uses under MS_PUT_FRAME_C (the host tests' build), write
   the same sprite table: tools/check_megadrive_rom.py compares the two in BlastEm.

   SGDK assembles the .s files in src through the C preprocessor (registers without %). Records (modsprite_data.h,
   SGDK's vdp_spr.h):
   MS_Part     0 first_piece.w  2 piece_count.b  3 flip.b  4 x.w  6 y.w
   MS_Piece    0 x.w  2 y.w  4 size.b  5 palette entry.b  6 tile offset.w
   VDPSprite   0 y.w  2 size.b  3 link.b  4 attribute.w  6 x.w
   A sprite's width less 8 is (size >> 2 & 3) << 3, its height less 8 (size & 3) << 3. The arguments are on the stack,
   4 bytes each (gcc's), from 48(sp) once the 11 registers are saved:

   48 end      the part after the last one drawn (the parts go from the last, which is on top, to the first)
   54 count    the parts
   56 sprite   the sprite table entry the first piece goes to
   62 link     the sprites in the table before it
   66 x, 70 y  where the frame is drawn (ms_put_parts: 0x80 added)
   74 attribute  its tiles' first (g_attr_base): each piece adds its part's flip bits, its tile offset and the palette
               bits of its entry (entry_bits)
   76 entry_bits, 80 pieces
   87 flip     bit 0 left-right, bit 1 top-bottom: the frame mirrored around (x, y), each sprite at its mirror image
               (a sprite w wide that its part and piece put at px drawn at x - px - w), its flip bits toggled
   ms_put_parts_careful also: 90 limit (the sprite limit), 94 the screen's width, 98 its height, 100 dropped (where the
   pieces that met the limit are counted).

   Registers: a0 the part, a1 the sprite table, a2 entry_bits, a3 pieces, a4 the piece, a5 / a6 the part's x / y,
   d0-d3 the piece (movem.w: x, y, size and entry, tile offset), d4 scratch or the parts left (dbra), d5 the sprites in
   the table, d6 the part's attribute, d7 its pieces left (dbra). */

#ifndef MS_PUT_FRAME_C

/* The part a0 steps back to, from its first piece to its attribute in d6 (its flip toggled when the frame is
   mirrored); to 8f when it has no pieces. */
    .macro PART mirrored
    subq.l  #8,a0
    moveq   #0,d7
    move.b  2(a0),d7
    beq     8f
    subq.w  #1,d7
    moveq   #0,d0
    move.w  (a0),d0
    lsl.l   #3,d0
    lea     0(a3,d0.l),a4
    moveq   #0,d6
    move.b  3(a0),d6
    .if \mirrored
    move.b  87(sp),d0
    eor.b   d0,d6
    .endif
    ror.w   #5,d6
    or.w    74(sp),d6
    .endm

/* The piece's entry, link and attribute into the table after its y (in d1, written): d2 is its size and the link
   after it (below 128) then. */
    .macro LINK_ATTRIBUTE
    move.w  d1,(a1)+
    moveq   #0,d1
    move.b  d2,d1
    addq.b  #1,d5
    move.b  d5,d2
    move.w  d2,(a1)+
    add.w   d1,d1
    add.w   0(a2,d1.w),d3
    add.w   d6,d3
    move.w  d3,(a1)+
    .endm

/* ms_put_parts for one way of mirroring (xflip, yflip): every piece into the table, no tests. a5 / a6: the part's x and
   y (0x80 added), mirrored less 8. 116 cycles a sprite as it is, 152 mirrored one way, 188 both; about 190 a part. A
   frame mirrored top-bottom counts the parts down on the stack (d4 is the y's scratch). */
    .macro FAST xflip, yflip
    .if \yflip
    tst.w   54(sp)
    beq     9f
    .else
    move.w  54(sp),d4
    subq.w  #1,d4
    bmi     9f
    .endif
1:  PART    (\xflip | \yflip)
    move.w  66(sp),a5
    .if \xflip
    suba.w  4(a0),a5
    subq.w  #8,a5
    .else
    adda.w  4(a0),a5
    .endif
    move.w  70(sp),a6
    .if \yflip
    suba.w  6(a0),a6
    subq.w  #8,a6
    .else
    adda.w  6(a0),a6
    .endif
2:  movem.w (a4)+,d0-d3
    .if \yflip
    move.w  d2,d4
    lsr.w   #5,d4
    and.w   #0x18,d4
    add.w   d1,d4
    move.w  a6,d1
    sub.w   d4,d1
    .else
    add.w   a6,d1
    .endif
    LINK_ATTRIBUTE
    .if \xflip
    lsr.w   #7,d2
    and.w   #0x18,d2
    add.w   d0,d2
    move.w  a5,d0
    sub.w   d2,d0
    .else
    add.w   a5,d0
    .endif
    move.w  d0,(a1)+
    dbra    d7,2b
8:
    .if \yflip
    subq.w  #1,54(sp)
    bne     1b
    .else
    dbra    d4,1b
    .endif
    bra     9f
    .endm

/* ms_put_parts_careful for one way of mirroring: a piece off the screen is left out (x >= width, y >= height,
   x + w <= 0 or y + h <= 0, as ms_on_screen tests it), one on the screen past the limit is counted in the high word
   of d5. a5 / a6: the part's x and y plus 8, mirrored its x and y less the part's; the tests take x + 8 and y + 8
   (in 16 bits, as the C's s16) against the width and height plus 8 (at 94 and 98) and x + w, y + h against 0 (tst:
   the sign of the 16 bits, not of a subtraction that overflowed), which comes to the C's tests for every x and y.
   About 285 cycles a sprite drawn. */
    .macro CAREFUL xflip, yflip
    tst.w   54(sp)
    beq     9f
1:  PART    (\xflip | \yflip)
    move.w  66(sp),a5
    .if \xflip
    suba.w  4(a0),a5
    .else
    adda.w  4(a0),a5
    addq.w  #8,a5
    .endif
    move.w  70(sp),a6
    .if \yflip
    suba.w  6(a0),a6
    .else
    adda.w  6(a0),a6
    addq.w  #8,a6
    .endif
2:  movem.w (a4)+,d0-d3
    .if \xflip
    move.w  a5,d4
    sub.w   d0,d4
    tst.w   d4
    ble     7f
    move.w  d2,d0
    lsr.w   #7,d0
    and.w   #0x18,d0
    sub.w   d0,d4
    move.w  d4,d0
    cmp.w   94(sp),d0
    bge     7f
    .else
    add.w   a5,d0
    cmp.w   94(sp),d0
    bge     7f
    move.w  d2,d4
    lsr.w   #7,d4
    and.w   #0x18,d4
    add.w   d0,d4
    ble     7f
    .endif
    .if \yflip
    move.w  a6,d4
    sub.w   d1,d4
    tst.w   d4
    ble     7f
    move.w  d2,d1
    lsr.w   #5,d1
    and.w   #0x18,d1
    sub.w   d1,d4
    move.w  d4,d1
    cmp.w   98(sp),d1
    bge     7f
    .else
    add.w   a6,d1
    cmp.w   98(sp),d1
    bge     7f
    move.w  d2,d4
    lsr.w   #5,d4
    and.w   #0x18,d4
    add.w   d1,d4
    ble     7f
    .endif
    cmp.w   90(sp),d5
    bcc     6f
    add.w   #120,d1
    LINK_ATTRIBUTE
    add.w   #120,d0
    move.w  d0,(a1)+
    dbra    d7,2b
    bra     8f
6:  swap    d5
    addq.w  #1,d5
    swap    d5
7:  dbra    d7,2b
8:  subq.w  #1,54(sp)
    bne     1b
    bra     9f
    .endm

    .text

/* The registers saved and the arguments every loop takes. */
    .macro ENTER
    movem.l d2-d7/a2-a6,-(sp)
    move.l  48(sp),a0
    move.l  56(sp),a1
    moveq   #0,d5
    move.w  62(sp),d5
    move.l  76(sp),a2
    move.l  80(sp),a3
    .endm

/* u16 ms_put_parts(const MS_Part *end, u16 count, VDPSprite *sprite, u16 link, s16 x, s16 y, u16 attribute,
                    const u16 *entry_bits, const MS_Piece *pieces)
   ms_put_render_frame's copy when the frame lies on the screen and fits under the limit (x and y with 0x80 added).
   Returns the sprites in the table. */
    .globl  ms_put_parts
ms_put_parts:
    ENTER
.Lput_as_it_is:
    FAST    0, 0
9:  move.l  d5,d0
    movem.l (sp)+,d2-d7/a2-a6
    rts

/* u16 ms_put_parts_flipped(const MS_Part *end, u16 count, VDPSprite *sprite, u16 link, s16 x, s16 y,
                            u16 attribute, const u16 *entry_bits, const MS_Piece *pieces, u8 flip)
   ms_put_render_frame_flipped's: the same mirrored (flip 0 draws as ms_put_parts does). */
    .globl  ms_put_parts_flipped
ms_put_parts_flipped:
    ENTER
    move.b  87(sp),d0
    and.w   #3,d0
    add.w   d0,d0
    move.w  10f(pc,d0.w),d0
    jmp     10f(pc,d0.w)
10: .word   .Lput_as_it_is-10b, 12f-10b, 13f-10b, 14f-10b
12: FAST    1, 0
13: FAST    0, 1
14: FAST    1, 1
9:  move.l  d5,d0
    movem.l (sp)+,d2-d7/a2-a6
    rts

/* u16 ms_put_parts_careful(const MS_Part *end, u16 count, VDPSprite *sprite, u16 link, s16 x, s16 y, u16 attribute,
                            const u16 *entry_bits, const MS_Piece *pieces, u8 flip, u16 limit, s16 screen_w,
                            s16 screen_h, u16 *dropped)
   Their careful loops (the frame across an edge of the screen, or past the limit): each piece tested as
   ms_push_sprite tests it. Returns the sprites in the table; adds the pieces dropped at the limit to *dropped. */
    .globl  ms_put_parts_careful
ms_put_parts_careful:
    ENTER
    addq.w  #8,94(sp)
    addq.w  #8,98(sp)
    move.b  87(sp),d0
    and.w   #3,d0
    add.w   d0,d0
    move.w  20f(pc,d0.w),d0
    jmp     20f(pc,d0.w)
20: .word   21f-20b, 22f-20b, 23f-20b, 24f-20b
21: CAREFUL 0, 0
22: CAREFUL 1, 0
23: CAREFUL 0, 1
24: CAREFUL 1, 1
9:  move.l  100(sp),a0
    swap    d5
    add.w   d5,(a0)
    clr.w   d5
    swap    d5
    move.l  d5,d0
    movem.l (sp)+,d2-d7/a2-a6
    rts

#endif
