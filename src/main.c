/**
 * main.c — Application coordinator
 *
 * Runs the cooperative event loop, routes touch events, and renders the active page.
 * Interrupts only collect input; protocol parsing and LCD updates run here.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "lcd.h"
#include "touch.h"
#include "protocol.h"
#include "slots.h"
#include "preferences.h"
#include "display_power.h"
static const uint16_t palettes[2][7] = {{0x10e4, 0x2166, 0xe75c, 0xa575, 0x8656, 0xdd50, 0x9df8},
                                        {0xded9, 0xef3b, 0x31a6, 0x632c, 0x4b6c, 0x91e6, 0x4b6c}};
#define BG palettes[preferences.theme][0]
#define PANEL palettes[preferences.theme][1]
#define WHITE palettes[preferences.theme][2]
#define MUTED palettes[preferences.theme][3]
#define TEAL palettes[preferences.theme][4]
#define ORANGE palettes[preferences.theme][5]
#define BLUE palettes[preferences.theme][6]
#include "boot_logo.h"
static bool settings_open;
static bool online, dirty = true, touch_ready, last_sync;
static unsigned page = 1, app_page; /* 0: media, 1: apps (3 banks), 2: monitor, 3: game */
static uint32_t metrics[7], last_metrics, last_hello, sequence, pending, sent_at;
static unsigned highlighted = 99;
static uint32_t highlight_at, status_until;
#define HISTORY_COUNT 60
#define MISSING 0xffffu
static uint16_t history[5][HISTORY_COUNT];
static unsigned history_pos, history_count, monitor_detail = 4;
static uint32_t history_at, extra_at, fps_pid;
static int monitor_values[5] = {-1, -1, -1, -1, -1};
static const char *monitor_names[5] = {"CPU", "RAM", "GPU", "FPS", "FRAMETIME"};
static int old_cpu = -1, old_ram = -1, shown_graph_value = -2;
static unsigned shown_graph_max;
static uint8_t shown_heights[HISTORY_COUNT];
static uint8_t mini_heights[4][24];
static uint32_t shown_header = 0xffffffffu;
static char notice[32] = "PC BAGLANTISI BEKLENIYOR";
static void set_notice(const char *text) {
    unsigned i = 0;
    for (; text[i] && i < sizeof(notice) - 1; i++)
        notice[i] = text[i];
    notice[i] = 0;
    status_until = ticks + 2000;
    if (!settings_open && page != 2) {
        lcd_fill(12, 27, 186, 9, BG);
        lcd_text(12, 27, notice, MUTED, BG, 1);
    }
}
static void card(int x, int y, int w, int h, uint16_t color) {
    lcd_fill(x + 4, y, w - 8, h, color);
    lcd_fill(x, y + 4, w, h - 8, color);
    lcd_fill(x + 2, y + 1, w - 4, h - 2, color);
}
static void number_string(int value, unsigned width, char text[6]) {
    for (unsigned i = 0; i < width; i++)
        text[i] = ' ';
    text[width] = 0;
    if (value < 0) {
        text[0] = '-';
        text[1] = '-';
        return;
    }
    char reverse[5];
    unsigned n = 0;
    do {
        reverse[n++] = (char)('0' + value % 10);
        value /= 10;
    } while (value && n < width);
    for (unsigned i = 0; i < n; i++)
        text[i] = reverse[n - 1 - i];
}
static void number_update(int x, int y, int value, int previous, unsigned width, uint16_t fg,
                          uint16_t bg, unsigned scale) {
    if (value == previous)
        return;
    char current[6], old[6];
    number_string(value, width, current);
    number_string(previous, width, old);
    for (unsigned i = 0; i < width; i++)
        if (previous == -2 || current[i] != old[i]) {
            char glyph[2] = {current[i], 0};
            lcd_text(x + (int)(i * 6 * scale), y, glyph, fg, bg, scale);
        }
}
static void metric_update(int x, int value, int previous, uint16_t accent) {
    number_update(x + 10, 66, value, previous, 3, WHITE, PANEL, 3);
    int length = value < 0 ? 0 : value * 84 / 100, old = previous < 0 ? 0 : previous * 84 / 100;
    if (length > old)
        lcd_fill(x + 10 + old, 93, length - old, 3, accent);
    else if (length < old)
        lcd_fill(x + 10 + length, 93, old - length, 3, BG);
}
static void metric(int x, const char *name, int value, uint16_t accent) {
    card(x, 43, 104, 61, PANEL);
    lcd_text(x + 10, 51, name, MUTED, PANEL, 1);
    lcd_text(x + 69, 75, "%", MUTED, PANEL, 1);
    lcd_fill(x + 10, 93, 84, 3, BG);
    metric_update(x, value, -2, accent);
}
static void icon(int x, int y, unsigned id, uint16_t fg, uint16_t bg) {
    if (id <= 2) {
        if (id == 0 || id == 2)
            lcd_fill(x + (id == 0 ? 0 : 25), y, 3, 18, fg);
        for (int col = 0; col < 18; col++) {
            int h = id == 0 ? col + 1 : 18 - col;
            lcd_fill(x + 5 + col, y + (18 - h) / 2, 1, h, fg);
        }
    } else if (id <= 5) {
        lcd_fill(x + 3, y + 6, 5, 7, fg);
        for (int r = 0; r < 5; r++)
            lcd_fill(x + 8 + r, y + 5 - r, 1, 9 + r * 2, fg);
        lcd_fill(x + 17, y + 8, 10, 2, fg);
        if (id == 5)
            lcd_fill(x + 21, y + 4, 2, 10, fg);
        if (id == 4) {
            for (int r = 0; r < 9; r++)
                lcd_fill(x + 17 + r, y + 4 + r, 2, 2, fg);
        }
    } else if (id == 6) {
        lcd_fill(x + 2, y + 3, 11, 4, fg);
        lcd_fill(x + 2, y + 7, 25, 14, fg);
        lcd_fill(x + 4, y + 10, 21, 9, bg);
    } else if (id == 7) {
        lcd_fill(x + 5, y, 20, 23, fg);
        lcd_fill(x + 8, y + 3, 14, 4, bg);
        for (int row = 0; row < 2; row++)
            for (int col = 0; col < 3; col++)
                lcd_fill(x + 8 + col * 5, y + 10 + row * 6, 3, 3, bg);
    } else if (id == 8) {
        lcd_fill(x + 5, y, 20, 23, fg);
        lcd_fill(x + 7, y + 2, 16, 19, bg);
        for (int row = 0; row < 3; row++)
            lcd_fill(x + 10, y + 5 + row * 5, 10, 2, fg);
    } else if (id == 9) {
        lcd_fill(x + 1, y + 1, 28, 18, fg);
        lcd_fill(x + 3, y + 3, 24, 13, bg);
        lcd_fill(x + 13, y + 19, 4, 3, fg);
        lcd_fill(x + 8, y + 22, 14, 2, fg);
    } else if (id == 10) {
        lcd_fill(x + 3, y + 13, 5, 10, fg);
        lcd_fill(x + 12, y + 3, 5, 20, fg);
        lcd_fill(x + 21, y + 8, 5, 15, fg);
    } else {
        for (int row = 0; row < 3; row++) {
            lcd_fill(x + 2, y + 4 + row * 7, 26, 2, fg);
            lcd_fill(x + (row == 1 ? 19 : 8), y + 1 + row * 7, 4, 8, fg);
        }
    }
}
static const char *fallback[6] = {"ONCEKI", "OYNAT", "SONRAKI", "SES -", "SESSIZ", "SES +"};
static void tile(unsigned slot, bool pressed) {
    unsigned id = slot + (page == 1 ? 6 + app_page * 6 : 0);
    if (id >= SLOT_COUNT)
        return;
    int x = page == 1 ? 8 + (int)(slot % 2) * 116 : 12 + (int)(slot % 3) * 74;
    int y = page == 1 ? 38 + (int)(slot / 2) * 70 : 115 + (int)(slot / 3) * 63;
    int width = page == 1 ? 108 : 68;
    uint16_t bg = pressed ? TEAL : PANEL, fg = pressed ? BG : (online ? WHITE : MUTED);
    card(x, y, width, page == 1 ? 64 : 55, bg);
    const char *label =
        deck_slot(id)->label[0] ? deck_slot(id)->label : (id < 6 ? fallback[id] : "BOS SLOT");
    if (deck_slot(id)->enabled) {
        lcd_icon_background = bg;
        lcd_icon_foreground = TEAL;
        if (page == 1)
            lcd_icon48(x + 30, y + (preferences.large_text ? 0 : 2), deck_slot(id)->pixels);
        else
            lcd_bitmap(x + 18, y + 3, ICON_SIZE, ICON_SIZE, deck_slot(id)->pixels);
    } else if (id < 6 && !deck_configured)
        icon(x + 20, y + 5, id, fg, bg);
    else {
        int cx = x + width / 2;
        lcd_fill(cx - 8, y + 22, 17, 3, MUTED);
        lcd_fill(cx - 1, y + 15, 3, 17, MUTED);
    }
    unsigned length = 0;
    while (label[length])
        ++length;
    if (page == 1 && preferences.large_text) {
        char large[9];
        unsigned n = length > 8 ? 8 : length;
        for (unsigned i = 0; i < n; i++)
            large[i] = label[i];
        large[n] = 0;
        lcd_text(x + (width - (int)n * 12) / 2, y + 48, large, fg, bg, 2);
    } else
        lcd_text(x + (width - (int)length * 6) / 2, y + (page == 1 ? 53 : 39), label, fg, bg, 1);
}
static void arrow(int x, int y, bool right) {
    for (int i = 0; i < 7; i++)
        lcd_fill(x + (right ? i : 6 - i), y + i, 2, 15 - 2 * i, WHITE);
}
static void footer(void) {
    if (page >= 2)
        return;
    if (page != 1) {
        lcd_fill(12, 255, 216, 14, BG);
        lcd_text(12, 258, "KEY1: SAYFA  KEY2: UYGULAMA", MUTED, BG, 1);
        return;
    }
    card(8, 246, 44, 30, PANEL);
    arrow(26, 253, false);
    card(188, 246, 44, 30, PANEL);
    arrow(206, 253, true);
    for (unsigned i = 0; i < 3; i++) {
        int x = 66 + (int)i * 38;
        uint16_t bg = i == app_page ? TEAL : PANEL;
        card(x, 246, 32, 30, bg);
        lcd_number(x + 10, 253, i + 1, i == app_page ? BG : WHITE, bg, 2);
    }
}
bool monitor_telemetry(uint32_t gpu, uint32_t fps, uint32_t pid) {
    if (gpu > 101 || fps > 10000)
        return false;
    if (pid != fps_pid) {
        for (unsigned i = 0; i < HISTORY_COUNT; i++)
            history[3][i] = history[4][i] = MISSING;
        fps_pid = pid;
    }
    monitor_values[2] = gpu == 101 ? -1 : (int)gpu;
    monitor_values[3] = fps == 10000 ? -1 : (int)fps;
    extra_at = ticks;
    return true;
}
void monitor_sample(void) {
    monitor_values[0] = (int)metrics[0];
    monitor_values[1] = (int)metrics[1];
    if ((uint32_t)(ticks - extra_at) > 2000)
        monitor_values[2] = monitor_values[3] = monitor_values[4] = -1;
    if (history_count && (uint32_t)(ticks - history_at) < 500)
        return;
    history_at = ticks;
    for (unsigned i = 0; i < 5; i++)
        history[i][history_pos] = monitor_values[i] < 0 ? MISSING : (uint16_t)monitor_values[i];
    history_pos = (history_pos + 1) % HISTORY_COUNT;
    if (history_count < HISTORY_COUNT)
        ++history_count;
}
static void monitor_graph(bool full) {
    unsigned id = page == 3 ? 4 : monitor_detail, maximum = id == 3 ? 60 : id == 4 ? 50 : 100;
    for (unsigned i = 0; i < history_count; i++) {
        unsigned index = (history_pos + HISTORY_COUNT - history_count + i) % HISTORY_COUNT;
        uint16_t value = history[id][index];
        if (value != MISSING && value > maximum)
            maximum = value;
    }
    if (id == 3)
        maximum = ((maximum + 29) / 30) * 30;
    if (full) {
        lcd_text(14, 44, monitor_names[id], TEAL, BG, 2);
        lcd_text(112, 86, id == 3 ? "KARE/S" : id == 4 ? "MS" : "YUZDE", MUTED, BG, 1);
        for (unsigned row = 0; row < 4; row++)
            lcd_fill(24, 123 + (int)row * 30, 192, 1, PANEL);
        lcd_text(14, 219, "-30 SN", MUTED, BG, 1);
        lcd_text(192, 219, "SIMDI", MUTED, BG, 1);
        card(12, 242, 80, 32, PANEL);
        lcd_text(28, 251, "GERI", WHITE, PANEL, 2);
        lcd_text(108, 251, "SON 30 SANIYE", MUTED, BG, 1);
        shown_graph_value = -2;
        shown_graph_max = 0;
        for (unsigned i = 0; i < HISTORY_COUNT; i++)
            shown_heights[i] = 0;
    }
    int value = online ? monitor_values[id] : -1;
    number_update(14, 72, value, shown_graph_value, 4, WHITE, BG, 3);
    shown_graph_value = value;
    number_update(14, 108, (int)maximum, shown_graph_max ? (int)shown_graph_max : -2, 5, MUTED, BG,
                  1);
    shown_graph_max = maximum;
    for (unsigned i = 0; i < HISTORY_COUNT; i++) {
        unsigned height = 0;
        if (i >= HISTORY_COUNT - history_count) {
            unsigned index = (history_pos + i) % HISTORY_COUNT;
            uint16_t sample = history[id][index];
            if (sample != MISSING) {
                height = sample * 90u / maximum;
                if (!height)
                    height = 1;
            }
        }
        unsigned old = shown_heights[i];
        int x = 30 + (int)i * 3;
        if (height > old)
            lcd_fill(x, 213 - (int)height, 2, (int)(height - old), TEAL);
        else if (height < old) {
            int top = 213 - (int)old, bottom = 213 - (int)height;
            lcd_fill(x, top, 2, bottom - top, BG);
            for (int y = 123; y <= 213; y += 30)
                if (y >= top && y < bottom)
                    lcd_fill(x, y, 2, 1, PANEL);
        }
        shown_heights[i] = (uint8_t)height;
    }
}
#include "ui_type.h"
#include "monitor_ui.h"
#include "game_ui.h"
#include "settings_ui.h"

static void header(void) {
    if (page == 2) {
        monitor_weather();
        return;
    }
    uint32_t state = online ? metrics[5] * 60 + metrics[6] : 1440;
    if (state == shown_header)
        return;
    shown_header = state;
    lcd_fill(142, 14, 52, 9, BG);
    lcd_fill(142, 16, 5, 5, online ? TEAL : ORANGE);
    if (online) {
        char time[6] = {(char)('0' + metrics[5] / 10), (char)('0' + metrics[5] % 10), ':',
                        (char)('0' + metrics[6] / 10), (char)('0' + metrics[6] % 10), 0};
        lcd_text(154, 14, time, MUTED, BG, 1);
    } else
        lcd_text(152, 14, "YOK", MUTED, BG, 1);
}
static void screen(void) {
    if (settings_open) {
        settings_screen();
        return;
    }
    shown_header = 0xffffffffu;
    lcd_fill(0, 0, 240, 320, BG);
    if (page == 2)
        ui_text(12, 9, "ALIEREN", WHITE, BG, 2);
    else
        lcd_text(12, 12, "MINI DECK", WHITE, BG, 2);
    header();
    if (page != 2)
        lcd_text(12, 27, notice, MUTED, BG, 1);
    if (page == 2)
        ui_round(200, 2, 38, 34, 8, PANEL);
    else
        card(200, 2, 38, 34, PANEL);
    card(209, 10, 20, 18, MUTED);
    card(213, 14, 12, 10, PANEL);
    lcd_fill(216, 7, 6, 24, MUTED);
    lcd_fill(207, 16, 24, 6, MUTED);
    lcd_fill(216, 16, 6, 6, PANEL);
    const char *tabs[4] = {"MEDYA", "SLOT", "IZLEME", "OYUN"};
    lcd_fill(0, 280, 240, 40, PANEL);
    for (unsigned i = 0; i < 4; i++) {
        int x = 4 + (int)i * 60;
        uint16_t bg = i == page ? (page == 2 ? MONITOR_ACCENT : TEAL) : PANEL,
                 fg = i == page ? BG : MUTED;
        if (page == 2)
            ui_round(x, 283, 52, 34, 8, bg);
        else
            card(x, 283, 52, 34, bg);
        if (i == 1) {
            for (int r = 0; r < 2; r++)
                for (int c = 0; c < 2; c++)
                    lcd_fill(x + 19 + c * 8, 287 + r * 7, 5, 5, fg);
        } else if (i == 2) {
            lcd_fill(x + 17, 294, 4, 6, fg);
            lcd_fill(x + 24, 290, 4, 10, fg);
            lcd_fill(x + 31, 286, 4, 14, fg);
        } else if (i == 0) {
            lcd_fill(x + 22, 287, 3, 11, fg);
            lcd_fill(x + 22, 287, 12, 3, fg);
            lcd_fill(x + 31, 287, 3, 11, fg);
            lcd_fill(x + 18, 296, 7, 4, fg);
            lcd_fill(x + 27, 296, 7, 4, fg);
        } else {
            card(x + 15, 289, 24, 12, fg);
            lcd_fill(x + 20, 291, 2, 8, bg);
            lcd_fill(x + 17, 294, 8, 2, bg);
            lcd_fill(x + 31, 292, 2, 2, bg);
            lcd_fill(x + 34, 296, 2, 2, bg);
        }
        unsigned len = 0;
        while (tabs[i][len])
            ++len;
        if (page == 2)
            ui_text(x + (52 - (int)len * 6) / 2, 304, tabs[i], fg, bg, 1);
        else
            lcd_text(x + (52 - (int)len * 6) / 2, 306, tabs[i], fg, bg, 1);
    }
    old_cpu = online ? (int)metrics[0] : -1;
    old_ram = online ? (int)metrics[1] : -1;
    if (page == 0) {
        metric(12, "CPU", old_cpu, TEAL);
        metric(124, "RAM", old_ram, BLUE);
    }
    if (page == 3)
        game_screen(true);
    else if (page == 2)
        monitor_screen(true);
    else
        for (unsigned i = 0; i < 6u; i++)
            tile(i, false);
    footer();
    dirty = false;
    highlighted = 99;
}
void update_metrics(void) {
    if (settings_open)
        return;
    header();
    int cpu = online ? (int)metrics[0] : -1, ram = online ? (int)metrics[1] : -1;
    if (page == 0 && cpu != old_cpu) {
        metric_update(12, cpu, old_cpu, TEAL);
        old_cpu = cpu;
    }
    if (page == 0 && ram != old_ram) {
        metric_update(124, ram, old_ram, BLUE);
        old_ram = ram;
    }
    if (page == 2)
        monitor_screen(false);
    if (page == 3)
        game_screen(false);
}
static void command(unsigned slot) {
    if (!online) {
        set_notice("PC UYGULAMASINI BASLATIN");
        return;
    }
    if (deck_syncing || !deck_configured) {
        set_notice("SLOTLAR HAZIRLANIYOR");
        return;
    }
    unsigned id = slot + (page == 1 ? 6u + app_page * 6u : 0u);
    if (id >= SLOT_COUNT || !deck_slot(id)->enabled) {
        set_notice("BOS SLOT / PC'DEN AYARLA");
        return;
    }
    if (pending)
        return;
    pending = ++sequence;
    if (!pending)
        pending = ++sequence;
    sent_at = ticks;
    game_pending = false;
    uint32_t values[3] = {pending, id, deck_revision};
    protocol_numbers('E', values, 3);
    highlighted = slot;
    highlight_at = ticks;
    tile(slot, true);
    led_set(2, true);
    set_notice("KOMUT GONDERILDI");
}
/* Consume a wake gesture before hit testing; a sleeping display must not launch a shortcut. */
void handle_tap(int x, int y) {
    if (display_activity())
        return;
    if (x < 0 || y < 0 || x >= 240 || y >= 320)
        return;
    if (settings_open) {
        settings_tap(x, y);
        return;
    }
    if (x >= 200 && y < 38) {
        preferences_before = preferences;
        settings_open = true;
        settings_error = false;
        settings_page = 0;
        dirty = true;
        highlighted = 99;
        return;
    }
    if (y >= 280 && y < 320) {
        {
            page = (unsigned)x / 60;
            monitor_detail = 4;
            game_detail = 0;
            dirty = true;
            highlighted = 99;
        }
        return;
    }
    if (page == 3) {
        game_tap(x, y);
        return;
    }
    if (page == 2) {
        if (monitor_detail < 4) {
            if (x >= 12 && x < 92 && y >= 242 && y < 274) {
                monitor_detail = 4;
                dirty = true;
            }
        } else if (y >= 246 && y < 278) {
            if (x < 60)
                monitor_bank = (monitor_bank + 2) % 3;
            else if (x >= 180)
                monitor_bank = (monitor_bank + 1) % 3;
            else
                monitor_bank = (unsigned)(x - 60) / 40;
            dirty = true;
        } else if (monitor_bank == 0 && x >= 8 && x < 232) {
            if (y >= 58 && y < 122)
                monitor_detail = 0;
            else if (y >= 130 && y < 194)
                monitor_detail = 2;
            else if (y >= 202 && y < 242)
                monitor_detail = 1;
            else
                return;
            dirty = true;
        }
        return;
    }
    if (page == 1 && y >= 246 && y < 276) {
        if (x >= 8 && x < 52)
            app_page = (app_page + 2) % 3;
        else if (x >= 188 && x < 232)
            app_page = (app_page + 1) % 3;
        else if (x >= 66 && x < 174 && (x - 66) % 38 < 32)
            app_page = (unsigned)(x - 66) / 38;
        else
            return;
        dirty = true;
        highlighted = 99;
        return;
    }
    if (page == 1 && x >= 8 && x < 232 && (x - 8) % 116 < 108) {
        int dy = y - 38;
        if (dy >= 0 && dy < 204 && dy % 70 < 64)
            command((unsigned)(dy / 70) * 2 + (unsigned)(x - 8) / 116);
    } else if (page == 0 && x >= 12 && x < 228 && (x - 12) % 74 < 68) {
        int dy = y - 115;
        if (dy >= 0 && dy < 126 && dy % 63 < 55)
            command((unsigned)(dy / 63) * 3 + (unsigned)(x - 12) / 74);
    }
}
/* Process only a bounded number of frames per loop so touch and watchdog work cannot starve. */
void receive(void) {
    char body[FRAME_MAX];
    uint32_t v[7];
    for (unsigned budget = 0; budget < 4 && protocol_poll(body); budget++) {
        if (deck_receive(body) || game_receive(body) || monitor_receive(body))
            continue;
        if (protocol_parse(body, 'M', v, 7) && v[0] <= 100 && v[1] <= 100 && v[2] <= 100 &&
            v[3] <= 999999 && v[4] <= 999999 && v[5] < 24 && v[6] < 60) {
            for (unsigned i = 0; i < 7; i++)
                metrics[i] = v[i];
            display_clock_sync(v[5], v[6]);
            monitor_sample();
            last_metrics = ticks;
            if (!online) {
                online = true;
                dirty = true;
                set_notice("PC BAGLANDI / HAZIR");
            }
            led_set(1, true);
            if (!dirty)
                update_metrics();
        } else if (protocol_parse(body, 'T', v, 3)) {
            monitor_telemetry(v[0], v[1], v[2]);
        } else if (protocol_parse(body, 'K', v, 2) && pending && v[0] == pending && v[1] <= 1) {
            uint32_t elapsed = ticks - sent_at;
            pending = 0;
            led_set(2, false);
            set_notice(v[1] ? "ISLEM BASLATILDI" : "KOMUT HATASI / PC LOG");
            if (v[1] && !settings_open) {
                lcd_number(132, 27, elapsed, MUTED, BG, 1);
                lcd_text(168, 27, "MS", MUTED, BG, 1);
            }
        } else if (body[0] == 'Q' && !body[1]) {
            protocol_numbers(
                'D',
                (uint32_t[]){uart_rx_errors, cpu_hz, 10, deck_revision, deck_syncing, touch_ready},
                6);
        } else if (body[0] == 'V' && !body[1]) {
            firmware_report();
        }
    }
}
static void cross(Point p, uint16_t color) {
    lcd_fill(p.x - 12, p.y - 1, 25, 3, color);
    lcd_fill(p.x - 1, p.y - 12, 3, 25, color);
}
static Point wait_touch(void) {
    Point p = {0, 0};
    uint32_t released = ticks;
    /* Require a stable release before every target. */
    for (;;) {
        watchdog_feed();
        if (uart_get() == '?')
            firmware_report();
        if (touch_down())
            released = ticks;
        else if ((uint32_t)(ticks - released) > 100)
            break;
        delay_ms(5);
    }
    for (;;) {
        watchdog_feed();
        if (uart_get() == '?')
            firmware_report();
        if (touch_raw(&p)) {
            Point q;
            delay_ms(35);
            if (touch_raw(&q) && q.x - p.x < 50 && p.x - q.x < 50 && q.y - p.y < 50 &&
                p.y - q.y < 50) {
                uart_puts("TOUCH RAW ");
                uart_uint(q.x);
                uart_puts(",");
                uart_uint(q.y);
                uart_puts("\r\n");
                return q;
            }
        }
        delay_ms(5);
    }
}
static void calibrate(void) {
    const Point targets[3] = {{24, 64}, {215, 160}, {120, 295}};
    Point raw[3];
    uart_puts("CALIBRATION: tap 3 crosses, then center cross\r\n");
    for (;;) {
        lcd_fill(0, 0, 240, 320, BG);
        lcd_text(12, 10, "KALIBRASYON", WHITE, BG, 2);
        lcd_text(12, 34, "ARTI ISARETINE DOKUN", MUTED, BG, 1);
        for (unsigned i = 0; i < 3; i++) {
            cross(targets[i], TEAL);
            raw[i] = wait_touch();
            cross(targets[i], BG);
            lcd_fill(85, 110, 80, 16, BG);
            lcd_text(85, 110, "ADIM", MUTED, BG, 1);
            lcd_number(121, 110, i + 1, WHITE, BG, 1);
        }
        if (!touch_calibrate(raw)) {
            uart_puts("CALIBRATION RETRY: degenerate points\r\n");
            continue;
        }
        cross((Point){120, 180}, ORANGE);
        lcd_text(40, 220, "SON HEDEFE DOKUN", WHITE, BG, 1);
        Point check = touch_map(wait_touch());
        if (check.x >= 102 && check.x <= 138 && check.y >= 162 && check.y <= 198)
            break;
        uart_puts("CALIBRATION RETRY: validation outside 18 pixels\r\n");
    }
    while (touch_down())
        delay_ms(10);
    delay_ms(100);
    uart_puts("CALIBRATION OK\r\n");
    touch_ready = true;
    if (touch_save())
        uart_puts("CALIBRATION SAVED\r\n");
    else {
        uart_puts("CALIBRATION SAVE FAILED\r\n");
        set_notice("AYAR KAYDEDILEMEDI");
    }
}

/* Initialize hardware and persistent state before entering the non-blocking control loop. */
int main(void) {
    board_init();
    touch_init();
    deck_init();
    preferences_load();
    page = preferences.start_page;
    display_init();
    if (!lcd_init()) {
        uart_puts("ERROR: LCD INIT\n");
        for (;;) {
            led_set(1, true);
            delay_ms(150);
            led_set(1, false);
            delay_ms(850);
        }
    }
    touch_ready = touch_load();
    if (preferences.boot_logo) {
        boot_logo();
        delay_ms(1000);
    }
    if (!touch_ready)
        set_notice("AYAR ICIN IKI TUSA BASIN");
    protocol_send("R,10");
    screen();
    bool held = false, key_raw[2] = {false, false}, key_stable[2] = {false, false};
    uint32_t release = ticks, touch_at = ticks, key_changed[2] = {0, 0}, both_since = 0;
    for (;;) {
        watchdog_feed();
        receive();
        display_tick();
        if (display_theme_refresh())
            dirty = true;
        if (online && (uint32_t)(ticks - last_metrics) > 2000) {
            online = false;
            pending = 0;
            dirty = true;
            history_count = 0;
            led_set(1, false);
            led_set(2, false);
            set_notice("PC BAGLANTISI KESILDI");
        }
        if (!online && (uint32_t)(ticks - last_hello) >= 1000) {
            protocol_send("R,10");
            last_hello = ticks;
        }
        if (pending && (uint32_t)(ticks - sent_at) > (game_pending ? 6000u : 1000u)) {
            pending = 0;
            led_set(2, false);
            set_notice("YANIT YOK / TEKRAR DENE");
        }
        if ((uint32_t)(ticks - touch_at) >= 8) {
            touch_at = ticks;
            Point raw;
            if (touch_ready && touch_raw(&raw)) {
                bool waking = display_activity();
                if (waking)
                    held = true;
                release = ticks;
                Point p = touch_map(raw);
                if (!held && p.x >= 0 && p.x < 240 && p.y >= 0 && p.y < 320) {
                    held = true;
                    handle_tap(p.x, p.y);
                }
            } else if (!touch_down() && (uint32_t)(ticks - release) >= 35)
                held = false;
        }
        for (unsigned i = 0; i < 2; i++) {
            bool down = !pin(2, 1u << (11 + i));
            if (down != key_raw[i]) {
                key_raw[i] = down;
                key_changed[i] = ticks;
            }
            if (down != key_stable[i] && (uint32_t)(ticks - key_changed[i]) >= 25) {
                key_stable[i] = down;
                if (down && !display_activity()) {
                    if (i == 0) {
                        page = (page + 1) % 4;
                        monitor_detail = 4;
                    } else {
                        if (page == 1)
                            app_page = (app_page + 1) % 3;
                        page = 1;
                    }
                    dirty = true;
                    highlighted = 99;
                }
            }
        }
        if (key_stable[0] && key_stable[1]) {
            if (!both_since)
                both_since = ticks;
            if ((uint32_t)(ticks - both_since) >= 1200) {
                online = false;
                pending = 0;
                history_count = 0;
                led_set(1, false);
                led_set(2, false);
                calibrate();
                display_activity();
                dirty = true;
                both_since = 0;
                held = true;
                release = ticks;
                protocol_send("R,10");
            }
        } else
            both_since = 0;
        if (last_sync != deck_syncing) {
            last_sync = deck_syncing;
            set_notice(deck_syncing ? "SLOTLAR ESITLENIYOR" : "SLOTLAR HAZIR / DOKUN");
        }
        uint32_t changed = deck_take_changes();
        if (!settings_open && !dirty && page < 2)
            for (unsigned i = 0; i < 6u; i++)
                if (changed & (1u << (i + (page == 1 ? 6u + app_page * 6u : 0u))))
                    tile(i, false);
        if (dirty)
            screen();
        if (!settings_open && highlighted < 6 && (uint32_t)(ticks - highlight_at) >= 120) {
            tile(highlighted, false);
            highlighted = 99;
        }
        if (status_until && (int32_t)(ticks - status_until) >= 0) {
            status_until = 0;
            set_notice(!touch_ready   ? "AYAR ICIN IKI TUSA BASIN"
                       : deck_syncing ? "SLOTLAR ESITLENIYOR"
                       : online       ? "PC BAGLI / DOKUN VE YONET"
                                      : "PC BAGLANTISI BEKLENIYOR");
            status_until = 0;
        }
        __asm volatile("wfi");
    }
}
