/**
 * monitor_ui.h — Hardware monitor UI
 *
 * Caches values and redraws changed regions only. Explicit unknown values and
 * timeouts prevent a disconnected sensor from looking like a real zero.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
/* v9 monitor: bounded fields and partial redraw, no framebuffer or allocation. */
#define MONITOR_PANEL (preferences.theme ? 0xff9cu : 0x2166u)
#define MONITOR_BORDER (preferences.theme ? 0x9c71u : 0x4acbu)
#define SENSOR_UNKNOWN 999999u
#define MONITOR_ACCENT (preferences.theme ? ORANGE : TEAL)
static unsigned monitor_bank;
static uint32_t sensors[6] = {999999, 999999, 999999, 999999, 999999, 999999};
static uint32_t ram_size[2] = {999999, 999999}, weather[3] = {255, 255, 1};
static uint32_t sensors_at, ram_at, weather_at;
static bool sensors_valid, ram_valid, weather_valid;
static char model_names[2][27] = {"CPU", "GPU"};
/* Initialized by every full render; AHB keeps the 4 KiB stack reserve intact. */
static char monitor_labels[12][31] __attribute__((section(".ahb_slots")));
static int monitor_numbers[3];
static unsigned monitor_bars[2];
static uint32_t weather_shown = 0xffffffffu;

static void monitor_surface(int x, int y, int w, int h, uint16_t color) {
    if (w < 30) {
        ui_round(x, y, w, h, w / 2, color);
        return;
    }
    ui_round(x, y, w, h, 9, MONITOR_BORDER);
    ui_round(x + 1, y + 1, w - 2, h - 2, 8, color);
}
static void monitor_chevron(int x, int y, bool right) {
    for (int i = 0; i < 6; i++) {
        lcd_fill(x + (right ? i : 5 - i), y + i, 2, 2, WHITE);
        lcd_fill(x + (right ? i : 5 - i), y + 10 - i, 2, 2, WHITE);
    }
}
static uint16_t monitor_plot[96 * 26] __attribute__((section(".ahb_slots")));
static void monitor_text(unsigned id, int x, int y, const char *text, unsigned width,
                         unsigned scale, uint16_t fg, uint16_t bg) {
    bool end = false;
    for (unsigned i = 0; i < width; i++) {
        char c = ' ';
        if (!end) {
            c = text[i];
            if (!c) {
                end = true;
                c = ' ';
            }
        }
        if (c != monitor_labels[id][i]) {
            char glyph[2] = {c, 0};
            ui_text(x + (int)(i * 6 * scale), y, glyph, fg, bg, scale);
            monitor_labels[id][i] = c;
        }
    }
}
static unsigned monitor_uint(char *out, uint32_t n) {
    char reverse[10];
    unsigned len = 0;
    do {
        reverse[len++] = (char)('0' + n % 10);
        n /= 10;
    } while (n && len < 10);
    for (unsigned i = 0; i < len; i++)
        out[i] = reverse[len - 1 - i];
    out[len] = 0;
    return len;
}
static void monitor_format(char *out, uint32_t value, unsigned decimals, const char *suffix) {
    unsigned n = 0;
    if (value == SENSOR_UNKNOWN) {
        out[n++] = '-';
        out[n++] = '-';
    } else {
        unsigned divisor = decimals == 2 ? 100 : decimals == 1 ? 10 : 1;
        n = monitor_uint(out, value / divisor);
        if (decimals) {
            out[n++] = '.';
            if (decimals == 2)
                out[n++] = (char)('0' + value / 10 % 10);
            out[n++] = (char)('0' + value % 10);
        }
    }
    for (unsigned i = 0; suffix[i] && n < 29; i++)
        out[n++] = suffix[i];
    out[n] = 0;
}
static void monitor_capacity(unsigned id, int y, uint32_t used, uint32_t total) {
    char text[31], part[31];
    monitor_format(text, used, 2, "");
    unsigned n = 0;
    while (text[n])
        n++;
    text[n++] = ' ';
    text[n++] = '/';
    text[n++] = ' ';
    monitor_format(part, total, 2, " GB");
    for (unsigned i = 0; part[i] && n < 30; i++)
        text[n++] = part[i];
    text[n] = 0;
    monitor_text(id, 20, y, text, 30, 1, WHITE, MONITOR_PANEL);
}
static void monitor_bar(unsigned id, int x, int y, unsigned width, uint32_t used, uint32_t total) {
    unsigned pixels = 0;
    if (used != SENSOR_UNKNOWN && total != SENSOR_UNKNOWN && total)
        pixels = (used > total ? total : used) * width / total;
    unsigned old = monitor_bars[id];
    if (pixels > old)
        lcd_fill(x + (int)old, y, (int)(pixels - old), 3, MONITOR_ACCENT);
    if (pixels < old)
        lcd_fill(x + (int)pixels, y, (int)(old - pixels), 3, BG);
    monitor_bars[id] = pixels;
}
static void monitor_weather(void) {
    bool valid = online && weather_valid && ticks - weather_at < 5000 && weather[0] <= 200 &&
                 weather[1] <= 99;
    uint32_t state = valid ? weather[0] + weather[1] * 256 + weather[2] * 65536 : 0xfffffffeu;
    if (shown_header == 0xffffffffu)
        weather_shown = 0xffffffffu;
    shown_header = 0;
    if (state == weather_shown)
        return;
    weather_shown = state;
    lcd_fill(130, 6, 68, 19, BG);
    if (!valid) {
        ui_text(149, 12, "-- C", MUTED, BG, 1);
        return;
    }
    uint16_t color = MONITOR_ACCENT;
    unsigned code = weather[1];
    if (code <= 1) {
        monitor_surface(134, 9, 10, 10, color);
        if (!weather[2])
            lcd_fill(138, 8, 7, 7, BG);
        else {
            lcd_fill(138, 6, 2, 2, color);
            lcd_fill(138, 20, 2, 2, color);
            lcd_fill(130, 13, 2, 2, color);
        }
    } else {
        lcd_fill(132, 12, 15, 6, color);
        lcd_fill(136, 9, 7, 3, color);
        if (code >= 51) {
            lcd_fill(134, 20, 2, 3, color);
            lcd_fill(141, 20, 2, 3, color);
        }
        if (code == 45 || code == 48)
            lcd_fill(132, 20, 15, 1, color);
    }
    char text[12];
    unsigned n = 0;
    int temp = (int)weather[0] - 100;
    if (temp < 0) {
        text[n++] = '-';
        temp = -temp;
    }
    n += monitor_uint(text + n, (unsigned)temp);
    text[n++] = ' ';
    text[n++] = 'C';
    text[n] = 0;
    ui_text(151, 12, text, WHITE, BG, 1);
}
/* Render a changed plot in one bounded bitmap transfer rather than clearing the whole screen. */
static void monitor_spark(unsigned id, int y, bool full) {
    uint8_t heights[24];
    bool changed = full;
    for (unsigned i = 0; i < 24; i++) {
        unsigned age = (23 - i) * 59 / 23, h = 0;
        if (preferences.mini_graphs && online && age < history_count) {
            unsigned v = history[id][(history_pos + HISTORY_COUNT - 1 - age) % HISTORY_COUNT];
            if (v != MISSING)
                h = 1 + (v > 100 ? 100 : v) * 23 / 100;
        }
        heights[i] = (uint8_t)h;
        if (h != mini_heights[id][i])
            changed = true;
        mini_heights[id][i] = (uint8_t)h;
    }
    if (!changed)
        return;
    uint16_t shade = ui_blend(MONITOR_ACCENT, MONITOR_PANEL, 3);
    for (unsigned x = 0; x < 96; x++) {
        unsigned i = x / 4, j = i < 23 ? i + 1 : i;
        int h = heights[i] && heights[j]
                    ? ((int)heights[i] * (4 - (int)(x % 4)) + (int)heights[j] * (int)(x % 4)) / 4
                    : 0;
        for (unsigned row = 0; row < 26; row++) {
            int dist = (int)row - (25 - h);
            uint16_t c = MONITOR_PANEL;
            if (h && dist >= 0)
                c = dist < 2 ? MONITOR_ACCENT : shade;
            monitor_plot[row * 96 + x] = c;
        }
    }
    lcd_bitmap(124, y - 26, 96, 26, monitor_plot);
}
static void monitor_screen(bool full) {
    if (monitor_detail < 4) {
        monitor_graph(full);
        return;
    }
    bool fresh = online && sensors_valid && ticks - sensors_at < 5000;
    bool ramfresh = online && ram_valid && ticks - ram_at < 5000;
    if (full) {
        for (unsigned i = 0; i < 12; i++)
            for (unsigned j = 0; j < 31; j++)
                monitor_labels[i][j] = 127;
        for (unsigned i = 0; i < 3; i++)
            monitor_numbers[i] = -2;
        monitor_bars[0] = monitor_bars[1] = 0;
        ui_text(12, 42,
                monitor_bank == 0   ? "Performans"
                : monitor_bank == 1 ? "GPU Detaylari"
                                    : "Ag / Disk",
                MONITOR_ACCENT, BG, 1);
        ui_text(204, 42,
                monitor_bank == 0   ? "1/3"
                : monitor_bank == 1 ? "2/3"
                                    : "3/3",
                MUTED, BG, 1);
        monitor_chevron(26, 253, false);
        monitor_chevron(206, 253, true);
        for (unsigned i = 0; i < 3; i++)
            monitor_surface(76 + (int)i * 40, 254, 10, 10,
                            i == monitor_bank ? MONITOR_ACCENT : MUTED);
        if (monitor_bank == 0) {
            monitor_surface(8, 58, 224, 64, MONITOR_PANEL);
            monitor_surface(8, 130, 224, 64, MONITOR_PANEL);
            monitor_surface(8, 202, 224, 40, MONITOR_PANEL);
            ui_text(18, 66, "CPU", MONITOR_ACCENT, MONITOR_PANEL, 1);
            ui_text(18, 138, "GPU", MONITOR_ACCENT, MONITOR_PANEL, 1);
            ui_text(18, 208, "RAM", MONITOR_ACCENT, MONITOR_PANEL, 1);
            lcd_fill(20, 236, 200, 3, BG);
        } else if (monitor_bank == 1) {
            const char *names[4] = {"SICAKLIK C", "FAN %", "GUC W", "FREKANS MHZ"};
            for (unsigned i = 0; i < 4; i++) {
                int x = 8 + (int)(i % 2) * 116, y = 78 + (int)(i / 2) * 62;
                monitor_surface(x, y, 108, 56, MONITOR_PANEL);
                ui_text(x + 10, y + 8, names[i], MONITOR_ACCENT, MONITOR_PANEL, 1);
            }
            monitor_surface(8, 208, 224, 34, MONITOR_PANEL);
            ui_text(18, 212, "VRAM", MONITOR_ACCENT, MONITOR_PANEL, 1);
            lcd_fill(20, 237, 200, 3, BG);
        } else {
            monitor_surface(8, 58, 224, 114, MONITOR_PANEL);
            monitor_surface(8, 180, 224, 62, MONITOR_PANEL);
            ui_text(20, 68, "INDIRME", MONITOR_ACCENT, MONITOR_PANEL, 1);
            ui_text(20, 120, "YUKLEME", MONITOR_ACCENT, MONITOR_PANEL, 1);
            ui_text(20, 188, "DISK C:", MONITOR_ACCENT, MONITOR_PANEL, 1);
            lcd_fill(20, 232, 200, 3, BG);
        }
    }
    if (monitor_bank == 0) {
        for (unsigned i = 0; i < 2; i++) {
            unsigned id = i ? 2 : 0;
            int y = 58 + (int)i * 72, v = online ? monitor_values[id] : -1;
            monitor_text(i, 48, y + 8, model_names[i], 26, 1, MUTED, MONITOR_PANEL);
            ui_number(18, y + 27, v, monitor_numbers[i], 3, WHITE, MONITOR_PANEL, 3);
            monitor_numbers[i] = v;
            if (full)
                ui_text(76, y + 36, "%", MUTED, MONITOR_PANEL, 1);
            monitor_spark(id, y + 56, full);
        }
        monitor_capacity(2, 223, ramfresh ? ram_size[0] : SENSOR_UNKNOWN,
                         ramfresh ? ram_size[1] : SENSOR_UNKNOWN);
        int ram = online ? monitor_values[1] : -1;
        ui_number(186, 208, ram, monitor_numbers[2], 3, WHITE, MONITOR_PANEL, 1);
        monitor_numbers[2] = ram;
        if (full)
            ui_text(207, 208, "%", WHITE, MONITOR_PANEL, 1);
        monitor_bar(0, 20, 236, 200, ram < 0 ? SENSOR_UNKNOWN : (unsigned)ram, 100);
    } else if (monitor_bank == 1) {
        monitor_text(0, 12, 62, model_names[1], 26, 1, MUTED, BG);
        for (unsigned i = 0; i < 4; i++) {
            char text[31];
            monitor_format(text, fresh ? sensors[i] : SENSOR_UNKNOWN, i == 2 ? 1 : 0, "");
            monitor_text(i + 1, 18 + (int)(i % 2) * 116, 104 + (int)(i / 2) * 62, text, 8, 2, WHITE,
                         MONITOR_PANEL);
        }
        monitor_capacity(5, 224, fresh ? sensors[4] : SENSOR_UNKNOWN,
                         fresh ? sensors[5] : SENSOR_UNKNOWN);
        monitor_bar(0, 20, 237, 200, fresh ? sensors[4] : SENSOR_UNKNOWN,
                    fresh ? sensors[5] : SENSOR_UNKNOWN);
    } else {
        for (unsigned i = 0; i < 2; i++) {
            char text[31];
            unsigned value = metrics[3 + i];
            monitor_format(
                text, online ? (value >= 1024 ? value * 10 / 1024 : value) : SENSOR_UNKNOWN,
                online && value >= 1024 ? 1 : 0, online && value >= 1024 ? " MB/s" : " KB/s");
            monitor_text(i, 20, 86 + (int)i * 52, text, 16, 2, WHITE, MONITOR_PANEL);
        }
        int disk = online ? (int)metrics[2] : -1;
        ui_number(20, 200, disk, monitor_numbers[0], 3, WHITE, MONITOR_PANEL, 3);
        monitor_numbers[0] = disk;
        if (full)
            ui_text(80, 214, "%", MUTED, MONITOR_PANEL, 1);
        monitor_bar(0, 20, 232, 200, disk < 0 ? SENSOR_UNKNOWN : (unsigned)disk, 100);
    }
}
/* Validate a complete packet before updating its freshness timestamp or cached values. */
static bool monitor_receive(const char *body) {
    uint32_t v[6];
    if (protocol_parse(body, 'S', v, 6)) {
        const uint32_t limits[6] = {200, 100, 20000, 20000, 999998, 999998};
        for (unsigned i = 0; i < 6; i++)
            if (v[i] > limits[i] && v[i] != SENSOR_UNKNOWN)
                return true;
        for (unsigned i = 0; i < 6; i++)
            sensors[i] = v[i];
        sensors_at = ticks;
        sensors_valid = true;
        return true;
    }
    if (protocol_parse(body, 'L', v, 2)) {
        if (v[0] <= SENSOR_UNKNOWN && v[1] <= SENSOR_UNKNOWN) {
            ram_size[0] = v[0];
            ram_size[1] = v[1];
            ram_at = ticks;
            ram_valid = true;
        }
        return true;
    }
    if (protocol_parse(body, 'O', v, 3)) {
        if ((v[0] <= 200 || v[0] == 255) && (v[1] <= 99 || v[1] == 255) && v[2] <= 1) {
            for (unsigned i = 0; i < 3; i++)
                weather[i] = v[i];
            weather_at = ticks;
            weather_valid = true;
        }
        return true;
    }
    if (body[0] == 'I' && body[1] == ',' && body[2] >= '0' && body[2] <= '1' && body[3] == ',') {
        unsigned len = 0;
        while (body[4 + len] && len < 27)
            len++;
        if (len != 26)
            return true;
        for (unsigned i = 0; i < 26; i++)
            if (body[4 + i] < 32 || body[4 + i] > 126)
                return true;
        for (unsigned i = 0; i < 26; i++)
            model_names[(unsigned)(body[2] - '0')][i] = body[4 + i];
        return true;
    }
    return false;
}
