/*
 * Per-voice filter call sites. r0 = filter object, r1 = audio buffer; r2 = the pad object the voice belongs to.
 * Sample voices (FUN_080ad870, bl at 0x080ad960): the pad is in r5.
 * Slicer voices (FUN_080b5aa8, bl at 0x080b5ccc): the pad is in r6.
 */
    .syntax unified
    .thumb
    .text

    .global filter_voice_a
    .thumb_func
    .type filter_voice_a, %function
filter_voice_a:
    mov     r2, r5
    b.w     filter_process

    .global filter_voice_b
    .thumb_func
    .type filter_voice_b, %function
filter_voice_b:
    mov     r2, r6
    b.w     filter_process
