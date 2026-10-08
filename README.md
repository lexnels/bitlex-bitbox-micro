# BitLex - 1010 bitbox micro modded firmware

> [!WARNING]
> **Install at your own risk.** This is unofficial custom firmware, not made or supported by 1010music. It has not
> been tried on a real bitbox micro yet: everything below is tested in an emulator against the real firmware code,
> not on hardware. Any custom firmware carries some risk of bricking your module, losing settings or projects, or
> behaving unexpectedly, and installing it may affect your warranty. The authors accept no responsibility for any
> damage. Keep your stock firmware file and back up your SD card before installing.

Unofficial firmware mod for the 1010music **bitbox micro**. It patches the official firmware and adds features to it.
Everything stock still works.

**Based on:** the official bitbox micro firmware **version 2.3.4** from 1010music, the file `MICRO.bin`
(671,376 bytes, SHA-256 `54ecc3e5c09b9aed7ad8e2d9d1c9f8ee63e06a8351c857304c3ff21fcb9c4365`).
The patcher only accepts that exact file, so it won't work on other versions. The modded firmware reports its version
as **2.3.4-L1**.

## What it adds

- **Live Loop pads:** a pad that keeps recording. Set **Live Loop** (last entry on the pad's first settings page,
  after Pad Note) to **Replace** or **Overdub**, and the pad records its input all the time in loops of the recording
  **Length** (1/4 bar up to 128 bars), locked to the tempo and the bar grid. Each pass is what the pad plays during
  the next one, and playback never stops while it records:
  - **Replace:** every pass replaces the loop, so the pad always plays the last bar(s) you played into it.
  - **Overdub:** every pass is added on top of the loop.

  It uses the normal recording settings: **Rec Input** (In 1/2, In 1, In 2 or Resam), recording **Gain** and
  **Length**, per pad or global as **RecConfig** says. The loop plays through the pad's own envelope, filter, level,
  pan, mute and sends.
- **Fidelity:** the pad's **Interp** setting becomes **Fidelity**, with vintage sampler modes after Normal and HighQ:
  **SP1200**, **SP-12**, **S950**, **MPC60** and **SP Raw** (SP1200 without its output filter), then plain sample-rate
  crunch from **16k** down to **2k**. The machine modes change how the pad reads its sample, like those machines'
  pitch logic, so the grit moves with the note; all are 12 bit.
- **24 dB filter:** the pad filter becomes a 24 dB/oct state-variable filter (two stages after Mutable Instruments'
  stmlib SVF) in place of the stock 12 dB one. Filter and Res keep their ranges (low-pass left of centre, high-pass
  right of it, off at centre). From noon up, Res also drives the filter, so high resonance growls instead of only
  getting louder.

### Using Live Loop

1. On the pad, set **Live Loop** to Replace or Overdub, and set the loop **Length** (Rec settings), for example 1 bar.
2. The pad needs a sample for it to play, so record the pad once the stock way (with **RecToPlay** on). From then on
   it loops: the first pass plays that recording, and every pass after plays what came in during the one before.
3. Start the transport. Loops start on multiples of their length (a 2 bar loop starts on bars 1, 3, 5, ...).

Good to know:
- Up to **four** Live Loop pads at a time; a fifth plays its sample as usual.
- A loop can be up to **10.9 seconds** long (4 bars down to 88 BPM). Longer loops play the pad's sample as stock.
- Changing the tempo or the Length, or loading a new sample into the pad, starts the loop over from the pad's sample.
- The loops live in RAM only. Nothing is written to the SD card, and the pad's sample file stays as you recorded it,
  so a live loop is gone after power-off. To keep one, resample it.
- The mod sets aside 16 MB of the sample memory for the four loops at boot, so there is that much less for samples.
- Live Loop with Length set to Custom counts as 1 bar.

## Install

You need your own copy of the official bitbox micro firmware **version 2.3.4** from 1010music (the mod can't include
it).

**In your browser (easiest):** open the [web patcher](https://lexnels.github.io/bitlex-bitbox-micro/), choose your
stock 2.3.4 `MICRO.bin`, and save the modded `MICRO.bin` it gives you. The file never leaves your computer: the page
patches it locally. If your browser saves it as `MICRO (1).bin` because the stock file is in the same folder, rename
it to `MICRO.bin`. Then copy it to the microSD card as in step 3 below.

**Or with Python 3** (built into macOS; on Windows get it from python.org):

1. Download [`releases/bitlex-micro-v0.1-patcher.py`](https://github.com/lexnels/bitlex-bitbox-micro/raw/main/releases/bitlex-micro-v0.1-patcher.py)
   (the newest patcher in the [`releases`](releases) folder).
2. In a terminal, run it on your stock firmware file:
   ```
   python3 bitlex-micro-v0.1-patcher.py "path/to/stock/MICRO.bin"
   ```
   It checks that the file is the right stock firmware, then writes the modded `MICRO.bin` into a `modded` folder next
   to the patcher, so your stock file is never overwritten.
3. Copy the modded `MICRO.bin` to the root of the microSD card and install it the same way as an official 1010music
   firmware update (see 1010music's bitbox micro update instructions).

The modded file is about 6.7 KB longer than the stock one (the mod's code is appended at the end).

### Going back to stock firmware

> **Back up your projects first** (copy the whole microSD card to your computer). Presets saved with the modded
> firmware keep the new settings (Live Loop, the new Fidelity modes), which the stock firmware doesn't know, so they
> may load differently there.

1. Back up the microSD card to your computer.
2. Copy your stock `MICRO.bin` (version 2.3.4) to the root of the card and install it like a 1010music firmware
   update.

## Not ported from blackbox-mod

[blackbox-mod](https://github.com/j3threejay/blackbox-mod) is for the 1010music blackbox, the micro's sister. Its
sequencer features (chords, conditional trigs, sequencer fixes) are left out since the micro has no sequencer.
These were left out for now:

| feature | why |
|---|---|
| Compressor models | The micro's master compressor already has the full set of controls (attack, release, threshold, ratio, knee, lookahead, auto makeup and release, Peak / RMS / Expander, wet/dry), which the blackbox's character models approximate. |
| Room reverb | The micro's reverb engine is the same plate as the blackbox's, so Room's DSP would drop in, but its settings screen is a fixed set of knobs and the mod has no tested way to add a Type selector to it yet. |
| Munchi delay | Same as Room: it needs new controls on the FX screen. |
| CPU meter | The micro's screen drawing hasn't been mapped yet, so there is nowhere tested to draw it. |
| Solo, slicer knobs | Both change how the pads and knobs behave in the UI, which hasn't been mapped on the micro. |
| Duck mod sources | The micro routes its CV inputs differently from the blackbox, and that path hasn't been traced yet. |
| Saturation (input drive) | Its blackbox setting slot is a different setting (Loop Fade) on the micro. |

## Credits and licences

- Fidelity and the 24 dB filter are ported from [j3threejay/blackbox-mod](https://github.com/j3threejay/blackbox-mod)
  by Justin Joe, **MIT**; the patching approach follows it too.
- The filter follows Emilie Gillet's stmlib SVF (Mutable Instruments), **MIT**.
- Licence texts: [`THIRD_PARTY.md`](THIRD_PARTY.md).
- The stock firmware is 1010music's property and is not included here. The patchers in `releases/` only carry the
  mod's own changes.

---

# Technical notes

## How it works

`MICRO.bin` is one image for the STM32H7's Cortex-M7, mapped at `0x08040000` (the bootloader below it isn't in the
file). The stock image ends at `0x080E3E90`; the mod's code (`src/`, built into `out/cave.bin`, about 6.7 KB) is
appended there, and a few `bl` instructions are redirected into it. The startup copy table already lists
`0x080E3E90` as an empty section, so nothing at boot touches the appended code. The cave has no `.data` or `.bss`
(the build fails if any appears); the mod's state lives in SRAM4 at `0x38000000` (64 KB, unused by the stock
firmware), laid out in `src/mod.h`.

Hooks (`patches/`, each patch checks the stock bytes before writing):

| site | stock call | new | what |
|---|---|---|---|
| `0x0806B34A` | `FUN_08069E7C` (register list) | `mod_register` | Interp list becomes Fidelity; registers Live Loop (id `0x17C`, xml `liveloop`); allocates the loops |
| `0x08089740`, `0x08089960` | `FUN_0808951E` (store add) | `mod_pad_store` | adds Live Loop (Off) to every pad's settings store |
| `0x0809418A` | `FUN_08096530` (engine block) | `engine_block` | the looper runs before and after each 128-frame block |
| `0x080B25D6` | `FUN_080AEC34` (voice render) | `loop_voice_render` | a Live Loop pad's voice plays the loop |
| `0x080AD960`, `0x080B5CCC` | `FUN_080B8420` (pad filter) | `filter_voice_a/b` | 24 dB SVF, crunch |
| `0x080AEE92`, `0x080AF0D8`, `0x080AF19A`, and six reader calls | sample readers | `voice_read`, `read_normal`, `read_hq` | Fidelity machine modes |
| `0x080C7892`, `0x080C7AAE` | empty page slot | `0x17C` | Live Loop on the pad settings page |
| `0x080C5770` | `"2.3.4"` | `"2.3.4-L1"` | version string |

## Live Loop in detail

`src/looper.c`. Each block, before the audio graph runs, `looper_block` walks the 20 pad settings stores
(`app + 0x1840`, 4 rows x 5 columns) and, for each pad with Live Loop on, works out the loop length in frames from the
Length setting (pad store when RecConfig is Per Pad, else the global rec store) and the transport tempo, and the loop
position from the transport's tempo anchor (960 ticks per quarter), so a loop of N bars starts on a multiple of N
bars. It then reads this block of the loop into a play buffer and writes the input over the loop at the same place
(Replace) or adds it (Overdub): read before write, so what plays is always the previous pass. The input is bus 0
(In 1/2), one side of it doubled (In 1, In 2), or a copy of the Resam bus (bus 3) taken after the previous block;
the recording Gain applies to the inputs, not to Resam. On the first pass, the loop is filled from the pad's sample as
it plays.

`loop_voice_render` replaces the per-voice render: for a Live Loop pad whose play buffer is ready this block, it runs
the voice's modulation tick, writes the play buffer as the voice's output (the first voice of the pad per block; any
others are silent), then runs the voice's stock stage (`FUN_080AD870`: envelope, gain, pan, filter). Otherwise it
calls the stock render.

Loops: four slots of 4 MB (524,288 stereo frames) taken from the top of the sample memory (SDRAM) at boot.

## Build

Needs `arm-none-eabi-gcc` and Python 3 (and `pip install unicorn capstone` for the tests). Put your stock 2.3.4 image
at `firmware/MICRO-2.3.4.bin` (SHA-256 `54ecc3e5c09b9aed7ad8e2d9d1c9f8ee63e06a8351c857304c3ff21fcb9c4365`).

```
./build.sh                      # src/ -> out/cave.bin
python3 patch.py all            # -> out/mod/MICRO.bin (mod, filter, looper, cave)
python3 tests/test_filter.py    # Fidelity and filter hooks on the real firmware code under Unicorn
python3 tests/test_looper.py    # Live Loop under Unicorn: phase lock, replace, overdub, inputs, gain, fallbacks (a few minutes)
python3 tools/make_patcher.py v0.1   # -> out/release/bitlex-micro-v0.1-patcher.py (copy it to releases/)
python3 tools/make_web.py       # -> docs/index.html, the browser patcher (GitHub Pages, from main /docs)
```

Never commit firmware images: `*.bin` is git-ignored. `ghidra/` has headless import/decompile scripts (the
decompiled listings stay local), and `tools/` has the emulator, disassembler and branch finder used by the tests.
