; The SNES runtime's hot loops in 65816 assembly: a render frame's sprites into the OAM buffer, a game's own sprite, the
; end of a frame (hiding what is not drawn any more, packing the high table) and a streamed export's uploads into its
; slots. Exactly ms_put_render_frame, ms_add_hw_sprite, ms_finish_oam and ms_send_uploads in modsprite.c (the C versions
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

; u8 ms_add_hw_sprite(s16 x, s16 y, u16 tile, u8 attribute, u8 large)
;   x 4,s, y 6,s, tile 8,s, then attribute 10,s and large 11,s (816-tcc pushes a u8 argument as one byte). A game's
;   own sprite at OAM entry ms_hw_count, unless it lies off the screen (TRUE, nothing drawn) or the limit is reached
;   (FALSE, ms_dropped counts it); the profile's sprite counts follow. Exactly ms_push_sprite and ms_add_hw_sprite in
;   modsprite.c.
ms_add_hw_sprite:
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
