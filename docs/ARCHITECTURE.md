# Software Architecture

## Firmware Modules

| Module | Responsibility |
|--------|----------------|
| `board.c` | Clock, GPIO, UART ring buffers, tick timer and watchdog |
| `lcd.c`, `touch.c` | Display bus and resistive-touch sampling |
| `calibration.c` | Calibrated touch coordinates and flash records |
| `main.c` | Cooperative event loop, navigation and legacy media/slot views |
| `monitor_ui.h`, `ui_type.h` | Three monitoring pages, partial redraw and glyph rendering |
| `game_ui.h` | Discord state and PUBG report views |
| `slots.c` | Icon/profile transfer staging and revision tracking |
| `protocol.c` | Bounded CRC16 frame parsing |
| `preferences.c`, `display_power.c` | Persistent settings, PWM dimming, RTC theme scheduling |

The UI headers are intentionally included after shared drawing primitives in `main.c`. Their state is private to that translation unit. Generated glyph data is kept separate from handwritten code.

## Host Modules

`app.py` owns application lifecycle. `desktop.py` builds the shell, `editor.py` edits profiles, and `app_picker.py` discovers applications. `bridge.py` owns serial I/O; UI callbacks exchange queued events instead of writing to the port directly. `sync.py` handles acknowledged full/delta transfers. `actions.py` executes locally configured actions, with `--dry-run` available for validation.

`performance.py` reads NVML and PresentMon. `weather_service.py` performs network work in its own thread. `game.py` combines Discord, audio and PUBG services without coupling their network latency to the serial loop. `programmer.py` coordinates the separate ISP process.

## Data Flow

```text
Touch → slot ID + sequence → serial bridge → local profile → Windows action
PC sensors → bounded telemetry frames → firmware cache → changed display regions
Profile editor → revision + changed icons → acknowledged sync → active slot bank
```

Frames use `@BODY*CRC16\n`; CRC16-CCITT starts at `0xFFFF`. Invalid, oversized and timed-out frames are discarded. The current firmware announces `R,10`; older supported versions receive only compatible extensions.

| Frame | Purpose |
|-------|---------|
| M / T | Core metrics and GPU/FPS sample |
| S / L | GPU sensors and RAM capacity |
| O / I | Weather and sanitized CPU/GPU model names |
| E / K | Slot action and acknowledgement |
| J / W | Game command and remote navigation |
| X | Profile/icon synchronization |
| Q / D / V | Diagnostics and firmware identity |

The v9+ sensor extension sends one additional frame per 250 ms cycle, rotating through five packets. Unknown sensors use `999999`; unknown weather uses `255`. Capacities are hundredths of GiB, GPU power is tenths of watts. On-screen GB/KB/MB labels use binary units.

## Memory & Persistence

The linker reserves sectors 28/29 for settings and calibration and asserts at least 4 KiB of stack space. AHB RAM stores slot data and bounded rendering buffers. Interrupt handlers collect bytes/ticks; parsing and drawing run in the main loop. No heap allocation is used in firmware.

Partial redraw caches must be reset on every full screen render. Tests compare incremental output with a fresh full render, including stale telemetry, offline transitions and both themes.

## Development Checks

Build before running tests: the emulator executes the compiled ELF. The test suite stubs hardware boundaries while preserving ARM application logic. For physical validation, check touch calibration, display orientation, sleep/wake, reconnect and ISP read-back on the target board.
