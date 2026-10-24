; The SNES runtime's hot loops in 65816 assembly: a render frame's sprites into the OAM buffer (as it is or mirrored;
; with give-way levels taken back when it does not fit, and then waiting), a game's own sprite (with give-way levels
; waiting when it does not fit), the give-way level, sprites moved up in the buffer (draws that gave way taken out), the
; end of a frame (hiding what is not drawn any more, packing the high table) and a streamed export's uploads into its
; slots (and the slot cache's lookup). Exactly ms_put_render_frame, ms_put_render_frame_flipped, ms_draw_put,
; ms_put_watched, ms_push_hw_sprite, ms_add_hw_sprite, ms_set_give_way, ms_move_sprites, ms_finish_oam,
; ms_send_uploads and ms_cache_hit in modsprite.c (the C versions
; the host tests run, which tools/check_snes_rom.py compares with these in an emulator); 816-tcc's code for them was
; several to ten times slower.
;
; Calling convention (816-tcc): arguments on the stack, 16 bits each (a u8 one byte), a pointer as its address then
; its bank (after jsl's 3 bytes the first argument is at 4,s); 16-bit A, X and Y; direct page 0 with tcc's scratch registers
; (tcc__r0 .. tcc__r10h and tcc__f2 .. tcc__f3h, free to use); the caller removes the arguments. The runtime's globals
; are reached with long addressing (initialised ones live in bank $7F, the others in $7E, wherever the linker puts
; them), so nothing depends on the data bank register.

.include "hdr.asm"
.accu 16
.index 16
.16bit

.SECTION ".ms_draw_text" SUPERFREE

; void ms_put_render_frame(u16 render_index, s16 ox, s16 oy)
;   The render frame's record (ms_rf_pages[index >> 10] + (index & 1023) * 22), the profile (a render call, its parts),
;   then its sprites: run_count runs of a palette entry (byte) and a sprite count (byte), each followed by that many
;   sprites (x, y, tile, attribute, size bit, 0: 8 bytes), in OAM order. Each sprite goes to OAM entry ms_hw_count with
;   its run's palette bits and priority 2 and its tile counted from ms_slot_base (a streamed export's slot, else 0),
;   unless it lies off the screen (256 x 224) or the limit is reached (ms_dropped counts those). When the frame's box is
;   on the screen with X >= 0 and all its sprites fit under the limit, nothing is tested per sprite (the fast loop). The
;   caller checked render_index.
ms_put_render_frame:
    lda 6,s
    sta.b tcc__r9               ; ox
    lda 8,s
    sta.b tcc__r9h              ; oy
    lda 4,s
    xba
    and.w #$00FC                ; (index >> 10) * 4: the page's pointer
    tax
    lda.l ms_rf_pages,x
    sta.b tcc__r10
    lda.l ms_rf_pages+2,x
    sta.b tcc__r10h
    lda 4,s
    and.w #$03FF
    asl a
    sta.b tcc__f2               ; 2i
    asl a
    sta.b tcc__f2h              ; 4i
    asl a
    asl a                       ; 16i
    clc
    adc.b tcc__f2
    clc
    adc.b tcc__f2h              ; 22i
    clc
    adc.b tcc__r10
    sta.b tcc__r10              ; the record
    lda.l ms_frame_profile      ; the profile: one more render call,
    inc a
    sta.l ms_frame_profile
    ldy.w #12
    lda [tcc__r10],y            ; the sprite count (low byte), the part count (high byte)
    sta.b tcc__f3
    xba
    and.w #$00FF
    clc
    adc.l ms_frame_profile+2    ; its parts
    sta.l ms_frame_profile+2
    ldy.w #2
    lda [tcc__r10],y            ; the sprites' chunk (low byte), the run count (high byte)
    sta.b tcc__f3h
    xba
    and.w #$00FF
    bne ms_pr_has_runs
    rtl
ms_pr_has_runs:
    sta.b tcc__r5               ; runs left
    ; the sprites: ms_chunks[chunk] + offset, as four pointers (a sprite's x, y, tile and size at 0, 2, 4, 6)
    lda.b tcc__f3h
    and.w #$00FF
    asl a
    asl a
    tax
    lda.l ms_chunks+2,x
    sta.b tcc__r0h
    sta.b tcc__r1h
    sta.b tcc__r2h
    sta.b tcc__r3h
    lda [tcc__r10]              ; the offset
    clc
    adc.l ms_chunks,x
    sta.b tcc__r0
    inc a
    inc a
    sta.b tcc__r1
    inc a
    inc a
    sta.b tcc__r2
    inc a
    inc a
    sta.b tcc__r3
    ; fast? (as ms_draw_render_frame in modsprite.c decides it)
    stz.b tcc__r5h
    lda.b tcc__f3
    and.w #$00FF
    clc
    adc.l ms_hw_count
    cmp.l ms_sprite_limit
    beq ms_pr_room
    bcs ms_pr_go                ; not all of them fit
ms_pr_room:
    ldy.w #14
    lda [tcc__r10],y            ; min x
    clc
    adc.b tcc__r9
    bmi ms_pr_go                ; x < 0 somewhere
    ldy.w #18
    lda [tcc__r10],y            ; max x: x + size - small < 256
    clc
    adc.b tcc__r9
    sec
    sbc.l ms_small_size
    bmi ms_pr_x_in
    cmp.w #256
    bcs ms_pr_go
ms_pr_x_in:
    ldy.w #16
    lda [tcc__r10],y            ; min y: y > -small
    clc
    adc.b tcc__r9h
    clc
    adc.l ms_small_size
    dec a
    bmi ms_pr_go
    ldy.w #20
    lda [tcc__r10],y            ; max y: y + size - small < 224
    clc
    adc.b tcc__r9h
    sec
    sbc.l ms_small_size
    bmi ms_pr_y_in
    cmp.w #224
    bcs ms_pr_go
ms_pr_y_in:
    inc.b tcc__r5h              ; fast
ms_pr_go:
    lda.l ms_hw_count
    asl a
    asl a
    tax                         ; X: the next sprite's OAM offset, all the way through
    ldy.w #0                    ; Y: where in the runs

ms_pr_run:
    lda [tcc__r0],y             ; the palette entry (low byte), the sprite count (high byte)
    iny
    iny
    phx
    pha
    and.w #$00FF
    clc
    adc.l ms_swap_bits_at       ; under the active palette swap (256 bytes a swap)
    tax
    lda.l ms_swap_bits,x        ; the entry's palette bits
    xba
    and.w #$FF00
    ora.w #$2000                ; and priority 2: the attribute's bits, added to each sprite's tile word
    clc
    adc.l ms_slot_base          ; with the slot's first tile (the sum stays below 512: no carry into the palette)
    sta.b tcc__r4
    pla
    xba
    and.w #$00FF
    asl a
    asl a
    asl a
    sty.b tcc__r4h
    clc
    adc.b tcc__r4h
    sta.b tcc__r4h              ; the run's end
    plx
    lda.b tcc__r5h
    bne ms_pr_fast
    jmp ms_pr_careful

ms_pr_fast:
    lda [tcc__r2],y             ; the tile, the attribute (flips, tile bit 8)
    clc
    adc.b tcc__r4
    sta.l oamMemory+2,x
    sep #$20
.accu 8
    lda [tcc__r0],y             ; x: its low byte is enough (0 <= x < 256)
    clc
    adc.b tcc__r9
    sta.l oamMemory,x
    lda [tcc__r1],y             ; y: its low byte (above the top it wraps from line 255, as the hardware draws it)
    clc
    adc.b tcc__r9h
    sta.l oamMemory+1,x
    lda [tcc__r3],y             ; the size bit (X bit 8 is 0)
    sta.l ms_high_bits,x
    rep #$20
.accu 16
    tya
    clc
    adc.w #8
    tay
    inx
    inx
    inx
    inx
    cpy.b tcc__r4h
    bne ms_pr_fast
    jmp ms_pr_next_run

ms_pr_careful:
    lda [tcc__r0],y             ; x
    clc
    adc.b tcc__r9
    sta.b tcc__r10
    lda [tcc__r1],y             ; y
    clc
    adc.b tcc__r9h
    sta.b tcc__r10h
    lda [tcc__r3],y             ; the size bit: 0 small, 2 large
    and.w #$0002
    sta.b tcc__f2
    beq ms_pr_small
    lda.l ms_large_size
    bra ms_pr_sized
ms_pr_small:
    lda.l ms_small_size
ms_pr_sized:
    dec a
    sta.b tcc__f2h              ; size - 1
    ; on the screen: -size < x < 256 and -size < y < 224, i.e. (u16)(x + size - 1) < 255 + size, and so for y
    clc
    adc.w #256
    sta.b tcc__f3
    lda.b tcc__f2h
    clc
    adc.b tcc__r10
    cmp.b tcc__f3
    bcs ms_pr_off
    lda.b tcc__f2h
    clc
    adc.w #224
    sta.b tcc__f3
    lda.b tcc__f2h
    clc
    adc.b tcc__r10h
    cmp.b tcc__f3
    bcs ms_pr_off
    txa
    lsr a
    lsr a
    cmp.l ms_sprite_limit
    bcs ms_pr_dropped
    lda [tcc__r2],y             ; the tile, the attribute
    clc
    adc.b tcc__r4
    sta.l oamMemory+2,x
    lda.b tcc__r10
    sta.l oamMemory,x           ; x (its high byte lands on y, written next)
    sep #$20
.accu 8
    lda.b tcc__r10h
    sta.l oamMemory+1,x         ; y
    lda.b tcc__r10+1            ; X bit 8
    and #$01
    ora.b tcc__f2               ; and the size bit
    sta.l ms_high_bits,x
    rep #$20
.accu 16
    inx
    inx
    inx
    inx
ms_pr_off:
    tya
    clc
    adc.w #8
    tay
    cpy.b tcc__r4h
    beq ms_pr_next_run
    jmp ms_pr_careful
ms_pr_dropped:
    lda.l ms_dropped
    inc a
    sta.l ms_dropped
    bra ms_pr_off

ms_pr_next_run:
    dec.b tcc__r5
    beq ms_pr_done
    jmp ms_pr_run

ms_pr_done:
    txa
    lsr a
    lsr a
    sta.l ms_hw_count
    sta.l ms_frame_profile+4    ; hw_sprites
    lda.l ms_dropped
    sta.l ms_frame_profile+6    ; sprites_dropped
    rtl

; void ms_put_render_frame_flipped(u16 render_index, s16 ox, s16 oy, u16 flip)
;   ms_put_render_frame mirrored around (ox, oy), flip bit 0 left-right, bit 1 top-bottom (neither: ms_put_render_frame
;   draws it): each sprite goes to its mirror image (on a mirrored axis -x - size, its own size), its flip bits toggled,
;   in the same order; the fast loop's test takes the mirrored box (on a mirrored axis from -max to -min). A sprite's
;   place on the screen is its size's base plus its x XOR the axis' mask: ox + x, or mirrored (ox - size + 1) + ~x; y
;   alike. The sprites are read through the data bank (their chunk's), which leaves the registers ms_put_render_frame's
;   pointers take to the mirroring. The caller checked render_index.
ms_put_render_frame_flipped:
    lda 10,s
    and.w #$0003
    bne ms_pf_mirrored
    jmp ms_put_render_frame     ; as it is (its arguments are where it takes them)
ms_pf_mirrored:
    lda 4,s
    xba
    and.w #$00FC                ; (index >> 10) * 4: the page's pointer
    tax
    lda.l ms_rf_pages,x
    sta.b tcc__r10
    lda.l ms_rf_pages+2,x
    sta.b tcc__r10h
    lda 4,s
    and.w #$03FF
    asl a
    sta.b tcc__f2               ; 2i
    asl a
    sta.b tcc__f2h              ; 4i
    asl a
    asl a                       ; 16i
    clc
    adc.b tcc__f2
    clc
    adc.b tcc__f2h              ; 22i
    clc
    adc.b tcc__r10
    sta.b tcc__r10              ; the record
    lda.l ms_frame_profile      ; the profile: one more render call,
    inc a
    sta.l ms_frame_profile
    ldy.w #12
    lda [tcc__r10],y            ; the sprite count (low byte), the part count (high byte)
    sta.b tcc__f3
    xba
    and.w #$00FF
    clc
    adc.l ms_frame_profile+2    ; its parts
    sta.l ms_frame_profile+2
    ldy.w #2
    lda [tcc__r10],y            ; the sprites' chunk (low byte), the run count (high byte)
    sta.b tcc__f3h
    xba
    and.w #$00FF
    bne ms_pf_has_runs
    rtl
ms_pf_has_runs:
    sta.b tcc__r0               ; runs left
    ; the sprites: ms_chunks[chunk] + offset
    lda.b tcc__f3h
    and.w #$00FF
    asl a
    asl a
    tax
    lda [tcc__r10]              ; the offset
    clc
    adc.l ms_chunks,x
    sta.b tcc__r9               ; their address,
    lda.l ms_chunks+2,x
    sta.b tcc__r9h              ; their bank
    ; the mirroring: x bases for small and large sprites, the x mask, the tile word's flip bits; y alike
    lda 10,s
    lsr a
    bcs ms_pf_mirror_x
    lda 6,s
    sta.b tcc__r2               ; ox, whatever the size
    sta.b tcc__r2h
    stz.b tcc__r4
    stz.b tcc__r5
    bra ms_pf_y
ms_pf_mirror_x:
    lda 6,s
    sec
    sbc.l ms_small_size
    inc a
    sta.b tcc__r2               ; ox - small + 1
    lda 6,s
    sec
    sbc.l ms_large_size
    inc a
    sta.b tcc__r2h              ; ox - large + 1
    lda.w #$FFFF
    sta.b tcc__r4
    lda.w #$4000                ; H
    sta.b tcc__r5
ms_pf_y:
    lda 10,s
    and.w #$0002
    bne ms_pf_mirror_y
    lda 8,s
    sta.b tcc__r3               ; oy, whatever the size
    sta.b tcc__r3h
    stz.b tcc__r4h
    bra ms_pf_fast_test
ms_pf_mirror_y:
    lda 8,s
    sec
    sbc.l ms_small_size
    inc a
    sta.b tcc__r3               ; oy - small + 1
    lda 8,s
    sec
    sbc.l ms_large_size
    inc a
    sta.b tcc__r3h              ; oy - large + 1
    lda.w #$FFFF
    sta.b tcc__r4h
    lda.b tcc__r5
    ora.w #$8000                ; V
    sta.b tcc__r5
ms_pf_fast_test:
    ; fast? (as ms_put_render_frame decides it, with the mirrored box: left, right, top, bottom)
    stz.b tcc__r1h
    lda.b tcc__f3
    and.w #$00FF
    clc
    adc.l ms_hw_count
    cmp.l ms_sprite_limit
    beq ms_pf_room
    bcc ms_pf_room
    jmp ms_pf_go                ; not all of them fit
ms_pf_room:
    lda 10,s
    lsr a
    bcs ms_pf_box_x_mirrored
    ldy.w #14
    lda [tcc__r10],y            ; min x
    clc
    adc 6,s
    sta.b tcc__f2
    ldy.w #18
    lda [tcc__r10],y            ; max x
    clc
    adc 6,s
    sta.b tcc__f2h
    bra ms_pf_box_y
ms_pf_box_x_mirrored:
    lda 6,s
    ldy.w #18
    sec
    sbc [tcc__r10],y            ; ox - max x
    sta.b tcc__f2
    lda 6,s
    ldy.w #14
    sec
    sbc [tcc__r10],y            ; ox - min x
    sta.b tcc__f2h
ms_pf_box_y:
    lda 10,s
    and.w #$0002
    bne ms_pf_box_y_mirrored
    ldy.w #16
    lda [tcc__r10],y            ; min y
    clc
    adc 8,s
    sta.b tcc__f3
    ldy.w #20
    lda [tcc__r10],y            ; max y
    clc
    adc 8,s
    sta.b tcc__f3h
    bra ms_pf_box
ms_pf_box_y_mirrored:
    lda 8,s
    ldy.w #20
    sec
    sbc [tcc__r10],y            ; oy - max y
    sta.b tcc__f3
    lda 8,s
    ldy.w #16
    sec
    sbc [tcc__r10],y            ; oy - min y
    sta.b tcc__f3h
ms_pf_box:
    lda.b tcc__f2               ; left >= 0
    bmi ms_pf_go
    lda.b tcc__f2h              ; right - small < 256
    sec
    sbc.l ms_small_size
    bmi ms_pf_x_in
    cmp.w #256
    bcs ms_pf_go
ms_pf_x_in:
    lda.b tcc__f3               ; top > -small
    clc
    adc.l ms_small_size
    dec a
    bmi ms_pf_go
    lda.b tcc__f3h              ; bottom - small < 224
    sec
    sbc.l ms_small_size
    bmi ms_pf_y_in
    cmp.w #224
    bcs ms_pf_go
ms_pf_y_in:
    inc.b tcc__r1h              ; fast
ms_pf_go:
    lda.l ms_hw_count
    asl a
    asl a
    tax                         ; X: the next sprite's OAM offset, all the way through
    ldy.b tcc__r9               ; Y: the next sprite, in the data bank
    sep #$20
.accu 8
    phb
    lda.b tcc__r9h
    pha
    plb                         ; the data bank: the sprites' chunk's
    rep #$20
.accu 16

ms_pf_run:
    lda.w $0000,y               ; the palette entry (low byte), the sprite count (high byte)
    iny
    iny
    phx
    pha
    and.w #$00FF
    clc
    adc.l ms_swap_bits_at       ; under the active palette swap (256 bytes a swap)
    tax
    lda.l ms_swap_bits,x        ; the entry's palette bits
    xba
    and.w #$FF00
    ora.w #$2000                ; and priority 2: the attribute's bits, added to each sprite's tile word
    clc
    adc.l ms_slot_base          ; with the slot's first tile (the sum stays below 512: no carry into the palette)
    sta.b tcc__r1
    pla
    xba
    and.w #$00FF
    asl a
    asl a
    asl a
    sty.b tcc__r0h
    clc
    adc.b tcc__r0h
    sta.b tcc__r0h              ; the run's end
    plx
    lda.b tcc__r1h
    bne ms_pf_fast
    jmp ms_pf_careful

ms_pf_fast:
    lda.w $0004,y               ; the tile, the attribute (flips, tile bit 8)
    eor.b tcc__r5               ; the flips toggled
    clc
    adc.b tcc__r1
    sta.l oamMemory+2,x
    sep #$20
.accu 8
    lda.w $0006,y               ; the size bit (X bit 8 is 0)
    sta.l ms_high_bits,x
    bne ms_pf_fast_large
    lda.w $0000,y               ; x: its low byte is enough (0 <= x < 256)
    eor.b tcc__r4
    clc
    adc.b tcc__r2
    sta.l oamMemory,x
    lda.w $0002,y               ; y: its low byte (above the top it wraps from line 255, as the hardware draws it)
    eor.b tcc__r4h
    clc
    adc.b tcc__r3
    sta.l oamMemory+1,x
    bra ms_pf_fast_placed
ms_pf_fast_large:
    lda.w $0000,y
    eor.b tcc__r4
    clc
    adc.b tcc__r2h
    sta.l oamMemory,x
    lda.w $0002,y
    eor.b tcc__r4h
    clc
    adc.b tcc__r3h
    sta.l oamMemory+1,x
ms_pf_fast_placed:
    rep #$20
.accu 16
    tya
    clc
    adc.w #8
    tay
    inx
    inx
    inx
    inx
    cpy.b tcc__r0h
    bne ms_pf_fast
    jmp ms_pf_next_run

ms_pf_careful:
    lda.w $0006,y               ; the size bit: 0 small, 2 large
    and.w #$0002
    sta.b tcc__r5h
    bne ms_pf_large
    lda.w $0000,y               ; x
    eor.b tcc__r4
    clc
    adc.b tcc__r2
    sta.b tcc__r9
    lda.w $0002,y               ; y
    eor.b tcc__r4h
    clc
    adc.b tcc__r3
    sta.b tcc__r9h
    lda.l ms_small_size
    bra ms_pf_sized
ms_pf_large:
    lda.w $0000,y
    eor.b tcc__r4
    clc
    adc.b tcc__r2h
    sta.b tcc__r9
    lda.w $0002,y
    eor.b tcc__r4h
    clc
    adc.b tcc__r3h
    sta.b tcc__r9h
    lda.l ms_large_size
ms_pf_sized:
    dec a
    sta.b tcc__r10              ; size - 1
    ; on the screen: -size < x < 256 and -size < y < 224, as ms_put_render_frame tests it
    clc
    adc.w #256
    sta.b tcc__r10h
    lda.b tcc__r10
    clc
    adc.b tcc__r9
    cmp.b tcc__r10h
    bcs ms_pf_off
    lda.b tcc__r10
    clc
    adc.w #224
    sta.b tcc__r10h
    lda.b tcc__r10
    clc
    adc.b tcc__r9h
    cmp.b tcc__r10h
    bcs ms_pf_off
    txa
    lsr a
    lsr a
    cmp.l ms_sprite_limit
    bcs ms_pf_dropped
    lda.w $0004,y               ; the tile, the attribute
    eor.b tcc__r5               ; the flips toggled
    clc
    adc.b tcc__r1
    sta.l oamMemory+2,x
    lda.b tcc__r9
    sta.l oamMemory,x           ; x (its high byte lands on y, written next)
    sep #$20
.accu 8
    lda.b tcc__r9h
    sta.l oamMemory+1,x         ; y
    lda.b tcc__r9+1             ; X bit 8
    and #$01
    ora.b tcc__r5h              ; and the size bit
    sta.l ms_high_bits,x
    rep #$20
.accu 16
    inx
    inx
    inx
    inx
ms_pf_off:
    tya
    clc
    adc.w #8
    tay
    cpy.b tcc__r0h
    beq ms_pf_next_run
    jmp ms_pf_careful
ms_pf_dropped:
    lda.l ms_dropped
    inc a
    sta.l ms_dropped
    bra ms_pf_off

ms_pf_next_run:
    dec.b tcc__r0
    beq ms_pf_done
    jmp ms_pf_run

ms_pf_done:
    plb
    txa
    lsr a
    lsr a
    sta.l ms_hw_count
    sta.l ms_frame_profile+4    ; hw_sprites
    lda.l ms_dropped
    sta.l ms_frame_profile+6    ; sprites_dropped
    rtl

; u8 ms_push_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large)
;   x 4,s, y 6,s, tile 8,s, then attribute 10,s and large 11,s (816-tcc pushes a u8 argument as one byte). A game's
;   own sprite at OAM entry ms_hw_count, unless it lies off the screen (TRUE, nothing drawn) or the limit is reached
;   (FALSE, ms_dropped counts it); the profile's sprite counts follow (ms_add_hw_sprite in modsprite.c calls it, after
;   looking at give-way levels). Exactly ms_push_sprite and ms_push_hw_sprite in modsprite.c.
ms_push_hw_sprite:
    lda 11,s
    and.w #$00FF
    beq ms_ah_small
    lda.l ms_large_size
    bra ms_ah_sized
ms_ah_small:
    lda.l ms_small_size
ms_ah_sized:
    dec a
    sta.b tcc__r2h              ; size - 1
    ; on the screen: -size < x < 256 and -size < y < 224, as ms_put_render_frame tests it
    clc
    adc.w #256
    sta.b tcc__r1
    lda.b tcc__r2h
    clc
    adc 4,s
    cmp.b tcc__r1
    bcs ms_ah_off
    lda.b tcc__r2h
    clc
    adc.w #224
    sta.b tcc__r1
    lda.b tcc__r2h
    clc
    adc 6,s
    cmp.b tcc__r1
    bcs ms_ah_off
    lda.l ms_hw_count
    cmp.l ms_sprite_limit
    bcs ms_ah_dropped
    asl a
    asl a
    tax
    lda 4,s
    sta.l oamMemory,x           ; x (its high byte lands on y, written next)
    sep #$20
.accu 8
    lda 6,s
    sta.l oamMemory+1,x         ; y
    lda 8,s
    sta.l oamMemory+2,x         ; the tile's low byte
    lda 9,s
    and #$01
    ora 10,s
    sta.l oamMemory+3,x         ; the attribute with the tile's bit 8
    lda 11,s
    beq ms_ah_size_bit
    lda #$02
ms_ah_size_bit:
    sta.b tcc__r2h
    lda 5,s                     ; X bit 8
    and #$01
    ora.b tcc__r2h              ; and the size bit
    sta.l ms_high_bits,x
    rep #$20
.accu 16
    lda.l ms_hw_count
    inc a
    sta.l ms_hw_count
ms_ah_off:
    lda.w #$00FF                ; TRUE
    sta.b tcc__r0
    bra ms_ah_profile
ms_ah_dropped:
    lda.l ms_dropped
    inc a
    sta.l ms_dropped
    stz.b tcc__r0               ; FALSE
ms_ah_profile:
    lda.l ms_hw_count
    sta.l ms_frame_profile+4    ; hw_sprites
    lda.l ms_dropped
    sta.l ms_frame_profile+6    ; sprites_dropped
    rtl

; u8 ms_add_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large)
;   x 4,s, y 6,s, tile 8,s, attribute 10,s, large 11,s. Without give-way levels (ms_levels 0) ms_push_hw_sprite. With
;   them a sprite on the screen waits for ms_end_frame (queued as a game's own sprite, TRUE) when the frame waits or the
;   buffer is full (the frame waits from then on; past ms_queue_room it is left out and dropped); else it is pushed,
;   and noted among the give-way draws when ms_give_way is set. Exactly ms_add_hw_sprite in modsprite.c.
ms_add_hw_sprite:
    sep #$20
.accu 8
    lda.l ms_levels
    rep #$20
.accu 16
    and.w #$00FF
    bne ms_as_watched
    jmp ms_push_hw_sprite       ; its arguments are where it takes them
ms_as_watched:
    lda 11,s
    and.w #$00FF
    beq ms_as_small
    lda.l ms_large_size
    bra ms_as_sized
ms_as_small:
    lda.l ms_small_size
ms_as_sized:
    dec a
    sta.b tcc__r2h              ; size - 1
    ; on the screen: -size < x < 256 and -size < y < 224, as ms_push_hw_sprite tests it (off it, nothing is drawn)
    clc
    adc.w #256
    sta.b tcc__r1
    lda.b tcc__r2h
    clc
    adc 4,s
    cmp.b tcc__r1
    bcs ms_as_push
    lda.b tcc__r2h
    clc
    adc.w #224
    sta.b tcc__r1
    lda.b tcc__r2h
    clc
    adc 6,s
    cmp.b tcc__r1
    bcs ms_as_push
    sep #$20
.accu 8
    lda.l ms_waiting
    rep #$20
.accu 16
    and.w #$00FF
    bne ms_as_wait              ; the frame waits
    lda.l ms_hw_count
    cmp.l ms_sprite_limit
    bcc ms_as_room
ms_as_wait:
    jmp ms_as_queue             ; the buffer is full: it waits
ms_as_push:
    jmp ms_push_hw_sprite
ms_as_room:
    pha                         ; first: the arguments from 6,s on now
    sep #$20
.accu 8
    lda 13,s
    pha                         ; large
    lda 13,s
    pha                         ; attribute
    rep #$20
.accu 16
    lda 12,s
    pha                         ; tile
    lda 12,s
    pha                         ; y
    lda 12,s
    pha                         ; x
    jsl ms_push_hw_sprite       ; (its TRUE or FALSE in tcc__r0)
    tsc
    clc
    adc.w #8
    tcs                         ; first at 1,s
    sep #$20
.accu 8
    lda.l ms_give_way
    rep #$20
.accu 16
    and.w #$00FF
    beq ms_as_done
    lda.l ms_hw_count
    cmp 1,s
    beq ms_as_done
    lda.l ms_give_way_count
    cmp.l ms_give_way_room
    bcs ms_as_done
    tax
    inc a
    sta.l ms_give_way_count
    sep #$20
.accu 8
    lda 1,s
    sta.l ms_give_way_first,x
    lda.l ms_hw_count
    sta.l ms_give_way_end,x
    lda.l ms_give_way
    sta.l ms_give_way_level,x
    rep #$20
.accu 16
ms_as_done:
    pla
    rtl
ms_as_queue:
    sep #$20
.accu 8
    lda #$FF
    sta.l ms_waiting
    rep #$20
.accu 16
    lda.w #$00FF
    sta.b tcc__r0               ; TRUE: it waits
    lda.l ms_queued_count
    cmp.l ms_queue_room
    bcs ms_as_left_out
    inc a
    sta.l ms_queued_count
    dec a
    asl a
    asl a
    asl a
    asl a
    tax                         ; its entry
    lda.w #$FFFF
    sta.l ms_queued_draws,x     ; a game's own sprite
    lda 4,s
    sta.l ms_queued_draws+2,x   ; x
    lda 6,s
    sta.l ms_queued_draws+4,x   ; y
    lda 8,s
    sta.l ms_queued_draws+6,x   ; its tile
    lda.w #1
    sta.l ms_queued_draws+8,x   ; a sprite
    lda.l ms_give_way
    and.w #$00FF
    asl a
    asl a
    sta.b tcc__r1
    lda 11,s
    and.w #$00FF
    beq ms_as_small_queued
    inc.b tcc__r1               ; large
ms_as_small_queued:
    lda 10,s
    xba
    and.w #$FF00                ; its attribute in the high byte
    ora.b tcc__r1
    sta.l ms_queued_draws+10,x  ; large | level << 2, then the attribute
    rtl
ms_as_left_out:
    lda.l ms_frame_profile+14   ; draws_left_out
    inc a
    sta.l ms_frame_profile+14
    lda.l ms_dropped
    inc a
    sta.l ms_dropped
    sta.l ms_frame_profile+6
    rtl

; u8 ms_cache_hit(u16 render_index, const u16 *loads)
;   render_index 4,s, loads 6,s (address) and 8,s (bank): each render frame's load list. With the slot cache (streamed
;   exports): TRUE when the render frame shows nothing (MS_NO_LIST: no slot needed) or the cache holds its list (the
;   entry in the bucket of the list's low six bits, ms_cache_buckets, along their next links; 16-byte entries: list at 8,
;   drawn at 12, next at 14): then the entry's slot is drawn through (ms_slot) and the entry marked drawn this frame
;   (ms_frame_number; MS_FrameProfile's slots_used counts it once a frame). FALSE when it does not hold it. Exactly
;   ms_cache_hit in modsprite.c.
ms_cache_hit:
    lda 6,s
    sta.b tcc__r1
    lda 8,s
    sta.b tcc__r1h
    lda 4,s
    asl a
    tay
    lda [tcc__r1],y             ; the list
    cmp.w #$FFFF
    beq ms_ch_yes               ; it shows nothing
    sta.b tcc__r2
    and.w #$003F
    tax
    sep #$20
.accu 8
    lda.l ms_cache_buckets,x    ; the bucket's first entry
    rep #$20
.accu 16
ms_ch_walk:
    and.w #$00FF
    cmp.w #$00FF
    beq ms_ch_no                ; not in the cache
    asl a
    asl a
    asl a
    asl a
    tax                         ; the entry
    lda.l ms_cache+8,x          ; its list
    cmp.b tcc__r2
    beq ms_ch_found
    lda.l ms_cache+14,x         ; the next in the bucket (low byte)
    bra ms_ch_walk
ms_ch_found:
    lda.l ms_cache+12,x         ; drawn
    cmp.l ms_frame_number
    beq ms_ch_slot
    lda.l ms_frame_number
    sta.l ms_cache+12,x
    lda.l ms_frame_profile+12   ; slots_used
    inc a
    sta.l ms_frame_profile+12
ms_ch_slot:
    txa
    clc
    adc.w #loword(ms_cache)
    sta.l ms_slot               ; the entry's slot: its address,
    lda.w #:ms_cache
    sta.l ms_slot+2             ; its bank
ms_ch_yes:
    lda.w #$00FF
    sta.b tcc__r0               ; TRUE
    rtl
ms_ch_no:
    stz.b tcc__r0               ; FALSE
    rtl

; void ms_set_give_way(u8 level)
;   level 4,s (one byte): the level draws take from now on, at most 63; a level other than 0 turns the watching on
;   (ms_levels, where the runtime has its queue: ms_levels_possible). Exactly ms_set_give_way in modsprite.c.
ms_set_give_way:
    sep #$20
.accu 8
    lda 4,s
    cmp #63
    bcc ms_sg_level
    lda #63
ms_sg_level:
    sta.l ms_give_way
    cmp #0
    beq ms_sg_done              ; level 0: nothing more
    lda.l ms_levels_possible
    beq ms_sg_done
    sta.l ms_levels
ms_sg_done:
    rep #$20
.accu 16
    rtl

; void ms_draw_put(u16 render_index, s16 ox, s16 oy, u16 flip)
;   A render frame into the OAM buffer for ms_draw_render in modsprite.c: without give-way levels (ms_levels 0)
;   ms_put_render_frame_flipped (flip 0: ms_put_render_frame), with them watched (below). Exactly ms_draw_put in
;   modsprite.c.
ms_draw_put:
    sep #$20
.accu 8
    lda.l ms_levels
    rep #$20
.accu 16
    and.w #$00FF
    bne ms_put_watched
    jmp ms_put_render_frame_flipped  ; as it is (its arguments are where it takes them)

; void ms_put_watched(u16 render_index, s16 ox, s16 oy, u16 flip)
;   A draw with give-way levels: ms_put_render_frame_flipped (flip 0: as it is). While
;   the frame does not wait (ms_waiting) and it dropped nothing, it stays: a give-way draw (ms_give_way not 0) that put
;   sprites into the buffer is noted in ms_give_way_first, _end and _level while there is room (ms_give_way_room).
;   Else it is taken back (ms_hw_count, ms_dropped and the profile's counts as they were, ms_written_end the highest
;   entry it wrote), the frame waits from it on, and when it asked for sprites on the screen (its own plus the dropped
;   ones) it goes into ms_queued_draws (16 bytes: render frame, x, y, ms_slot_base, the sprites, flips | level << 2, 0,
;   ms_swap_bits_at), or past ms_queue_room it is left out (the profile's draws_left_out, its sprites dropped). Exactly
;   ms_put_watched in modsprite.c.
ms_put_watched:
    lda.l ms_hw_count
    pha                         ; first
    lda.l ms_dropped
    pha                         ; dropped: the arguments are 4 bytes further now
    lda 14,s
    pha                         ; flip
    lda 14,s
    pha                         ; oy
    lda 14,s
    pha                         ; ox
    lda 14,s
    pha                         ; render_index
    jsl ms_put_render_frame_flipped
    pla
    pla
    pla
    pla                         ; first at 3,s, dropped at 1,s, the arguments from 8,s on again
    sep #$20
.accu 8
    lda.l ms_waiting
    rep #$20
.accu 16
    and.w #$00FF
    bne ms_pw_back              ; the frame waits: so does every draw
    lda.l ms_dropped
    cmp 1,s
    bne ms_pw_back              ; it did not fit
    sep #$20
.accu 8
    lda.l ms_give_way
    rep #$20
.accu 16
    and.w #$00FF
    beq ms_pw_done              ; not a give-way draw
    lda.l ms_hw_count
    cmp 3,s
    beq ms_pw_done              ; nothing on the screen
    lda.l ms_give_way_count
    cmp.l ms_give_way_room
    bcs ms_pw_done              ; no room to note it: it stays
    tax
    inc a
    sta.l ms_give_way_count
    sep #$20
.accu 8
    lda 3,s
    sta.l ms_give_way_first,x
    lda.l ms_hw_count
    sta.l ms_give_way_end,x
    lda.l ms_give_way
    sta.l ms_give_way_level,x
    rep #$20
.accu 16
ms_pw_done:
    pla
    pla
    rtl
ms_pw_back:
    lda.l ms_hw_count
    cmp.l ms_written_end
    bcc ms_pw_cost
    sta.l ms_written_end
ms_pw_cost:
    sec
    sbc 3,s                     ; the sprites it wrote,
    clc
    adc.l ms_dropped
    sec
    sbc 1,s                     ; and the ones it dropped
    sta.b tcc__r0               ; what it asks for
    lda 3,s
    sta.l ms_hw_count
    sta.l ms_frame_profile+4    ; hw_sprites
    lda 1,s
    sta.l ms_dropped
    sta.l ms_frame_profile+6    ; sprites_dropped
    sep #$20
.accu 8
    lda #$FF
    sta.l ms_waiting
    rep #$20
.accu 16
    lda.b tcc__r0
    beq ms_pw_end               ; nothing on the screen: nothing waits
    lda.l ms_queued_count
    cmp.l ms_queue_room
    bcs ms_pw_left_out
    inc a
    sta.l ms_queued_count
    dec a
    asl a
    asl a
    asl a
    asl a
    tax                         ; its entry
    lda 8,s
    sta.l ms_queued_draws,x     ; the render frame
    lda 10,s
    sta.l ms_queued_draws+2,x   ; x
    lda 12,s
    sta.l ms_queued_draws+4,x   ; y
    lda.l ms_slot_base
    sta.l ms_queued_draws+6,x   ; its tiles' first
    lda.b tcc__r0
    sta.l ms_queued_draws+8,x   ; its sprites
    lda.l ms_give_way
    and.w #$00FF
    asl a
    asl a
    sta.b tcc__r1
    lda 14,s
    and.w #$0003
    ora.b tcc__r1
    sta.l ms_queued_draws+10,x  ; its flips and level (and the attribute byte 0)
    lda.l ms_swap_bits_at
    sta.l ms_queued_draws+12,x  ; its palette swap
ms_pw_end:
    pla
    pla
    rtl
ms_pw_left_out:
    lda.l ms_frame_profile+14   ; draws_left_out
    inc a
    sta.l ms_frame_profile+14
    lda.l ms_dropped
    clc
    adc.b tcc__r0
    sta.l ms_dropped
    sta.l ms_frame_profile+6
    bra ms_pw_end

; void ms_move_sprites(u16 to, u16 from, u16 count)
;   to 4,s, from 6,s, count 8,s: the OAM entries from .. from + count - 1 to to .. (to < from), their four bytes in
;   oamMemory and their high bits in ms_high_bits (at the same offset), each a block move upwards (MVN: 7 cycles a byte,
;   the overlap copied in order). Exactly ms_move_sprites in modsprite.c.
ms_move_sprites:
    lda 8,s
    bne ms_mv_go
    rtl
ms_mv_go:
    asl a
    asl a
    dec a
    sta.b tcc__r0               ; the bytes less one
    lda 6,s
    asl a
    asl a
    sta.b tcc__r0h              ; from's offset
    lda 4,s
    asl a
    asl a
    sta.b tcc__r1               ; to's offset
    phb
    lda.b tcc__r0h
    clc
    adc.w #loword(oamMemory)
    tax
    lda.b tcc__r1
    clc
    adc.w #loword(oamMemory)
    tay
    lda.b tcc__r0
    mvn :oamMemory, :oamMemory
    lda.b tcc__r0h
    clc
    adc.w #loword(ms_high_bits)
    tax
    lda.b tcc__r1
    clc
    adc.w #loword(ms_high_bits)
    tay
    lda.b tcc__r0
    mvn :ms_high_bits, :ms_high_bits
    plb
    rtl

; void ms_finish_oam(u8 *high_table, u16 count, u16 shown)
;   The entries count .. shown-1 (drawn last frame, not now) go where unused entries wait (ms_hidden_y); the high
;   table (oamMemory + 512) gets the two bits of each drawn sprite from ms_high_bits, the sprites after the last drawn
;   one in its group of four none, and its bytes after that 0 up to the last frame's groups (the bytes after those are
;   0 already).
ms_finish_oam:
    lda 4,s
    sta.b tcc__r2               ; the high table: address,
    lda 6,s
    sta.b tcc__r2h              ; bank
    lda 10,s
    asl a
    asl a
    sta.b tcc__r1               ; the last frame's end (an OAM offset)
    lda 8,s
    asl a
    asl a
    sta.b tcc__r0               ; this frame's end
    tax
    sep #$20
.accu 8
    lda.l ms_hidden_y           ; (its low byte)
ms_fo_hide:
    cpx.b tcc__r1
    bcs ms_fo_hidden
    sta.l oamMemory+1,x
    inx
    inx
    inx
    inx
    bra ms_fo_hide
ms_fo_hidden:
    rep #$20
.accu 16
    lda.b tcc__r0
    clc
    adc.w #15
    and.w #$FFF0
    sta.b tcc__r3               ; the end of the last group of four drawn sprites
    ldx.b tcc__r0
    sep #$20
.accu 8
    lda #0
ms_fo_clear:
    cpx.b tcc__r3
    bcs ms_fo_cleared
    sta.l ms_high_bits,x
    inx
    inx
    inx
    inx
    bra ms_fo_clear
ms_fo_cleared:
    ldx.w #0
    ldy.w #0
ms_fo_pack:
    cpx.b tcc__r3
    bcs ms_fo_packed
    lda.l ms_high_bits+12,x
    asl a
    asl a
    ora.l ms_high_bits+8,x
    asl a
    asl a
    ora.l ms_high_bits+4,x
    asl a
    asl a
    ora.l ms_high_bits,x
    sta [tcc__r2],y
    iny
    rep #$20
.accu 16
    txa
    clc
    adc.w #16
    tax
    sep #$20
.accu 8
    bra ms_fo_pack
ms_fo_packed:
    rep #$20
.accu 16
    lda.b tcc__r1
    clc
    adc.w #15
    lsr a
    lsr a
    lsr a
    lsr a
    sta.b tcc__r1               ; the last frame's groups
    sep #$20
.accu 8
    lda #0
ms_fo_zero:
    cpy.b tcc__r1
    bcs ms_fo_done
    sta [tcc__r2],y
    iny
    bra ms_fo_zero
ms_fo_done:
    rep #$20
.accu 16
    rtl

; u16 ms_send_uploads(const MS_LoadList *lists)
;   lists 4,s (address) and 6,s (bank): the load lists' records (8 bytes: their runs' offset, chunk, group count, ...).
;   A streamed export's load lists queued this frame (ms_upload_lists, ms_upload_count) into their slots (ms_upload_vram:
;   a slot's VRAM word address): a list is group_count groups, each the chunk its runs read (a byte) and their count (a
;   byte), then the runs (6 bytes: a VRAM word offset in the slot, an offset in the chunk, bytes), a DMA each on channel
;   0 (two registers, VMDATAL and VMDATAH, VMAIN 0x80). Before each list and after it HVBJOY says whether the vertical
;   blank still lasts: the lists from the first that did not arrive whole are not counted. Returns the lists sent (in
;   tcc__r0). Exactly ms_send_uploads in modsprite.c. The runs are read through the data bank (their chunk's), the
;   registers with long addressing.
ms_send_uploads:
    lda 4,s
    sta.b tcc__r1               ; the records: address,
    lda 6,s
    sta.b tcc__r1h              ; bank
    phb
    stz.b tcc__r0               ; lists sent
    sep #$20
.accu 8
    lda #$80
    sta.l $002115               ; VMAIN: the address goes up a word after VMDATAH
    lda #$01
    sta.l $004300               ; DMAP0: A to B, two registers once, the source going up
    lda #$18
    sta.l $004301               ; BBAD0: VMDATAL
    rep #$20
.accu 16
ms_su_list:
    lda.b tcc__r0
    cmp.l ms_upload_count
    bcc ms_su_vblank
    jmp ms_su_done
ms_su_vblank:
    sep #$20
.accu 8
    lda.l $004212               ; HVBJOY: bit 7 while the vertical blank lasts
    rep #$20
.accu 16
    bmi ms_su_start
    jmp ms_su_done
ms_su_start:
    lda.b tcc__r0
    asl a
    tax
    lda.l ms_upload_vram,x
    sta.b tcc__r5               ; the slot's VRAM word address
    lda.l ms_upload_lists,x
    asl a
    asl a
    asl a
    tay                         ; the list's record: index * 8
    lda [tcc__r1],y             ; its runs' offset
    sta.b tcc__r2
    iny
    iny
    lda [tcc__r1],y             ; their chunk (low byte), the group count (high byte)
    sta.b tcc__r3
    xba
    and.w #$00FF
    sta.b tcc__r10              ; groups left
    lda.b tcc__r3
    and.w #$00FF
    asl a
    asl a
    tax
    lda.l ms_chunks,x
    clc
    adc.b tcc__r2
    tay                         ; Y: the first group, in the data bank
    sep #$20
.accu 8
    lda.l ms_chunks+2,x
    pha
    plb                         ; the data bank: the runs' chunk's
    rep #$20
.accu 16
ms_su_group:
    lda.w $0000,y               ; the group's chunk (low byte), its run count (high byte)
    iny
    iny
    sta.b tcc__r3
    xba
    and.w #$00FF
    sta.b tcc__r9h              ; runs left in the group
    lda.b tcc__r3
    and.w #$00FF
    asl a
    asl a
    tax
    lda.l ms_chunks,x
    sta.b tcc__r9               ; the chunk's address
    sep #$20
.accu 8
    lda.l ms_chunks+2,x
    sta.l $004304               ; A1B0: its bank
    rep #$20
.accu 16
ms_su_run:
    lda.w $0000,y               ; the run's place in the slot (VRAM words)
    clc
    adc.b tcc__r5
    sta.l $002116               ; VMADD
    lda.w $0002,y               ; its offset in the chunk
    clc
    adc.b tcc__r9
    sta.l $004302               ; A1T0
    lda.w $0004,y               ; its bytes
    sta.l $004305               ; DAS0
    sep #$20
.accu 8
    lda #$01
    sta.l $00420B               ; MDMAEN: channel 0 (the CPU waits until it is done)
    rep #$20
.accu 16
    tya
    clc
    adc.w #6
    tay
    dec.b tcc__r9h
    bne ms_su_run
    dec.b tcc__r10
    bne ms_su_group
    sep #$20
.accu 8
    lda.l $004212               ; did the vertical blank last the whole list?
    rep #$20
.accu 16
    bpl ms_su_done
    inc.b tcc__r0
    jmp ms_su_list
ms_su_done:
    plb
    rtl

.ENDS
