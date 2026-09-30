/**
 * game_ui.h — Game and Discord UI
 *
 * Renders bounded host-supplied summaries and sends numbered control events.
 * The board contains no API credentials and does not contact game services.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
/* Included after common drawing primitives. All strings/buffers are bounded. */
static uint32_t game_values[7] = {0, 101, 2, 2, 0, 0, 10000};
static uint32_t game_extra[7] = {0, 0, 0, 0, 0, 10000, 0};
static uint32_t game_at;
static unsigned game_detail;
static int game_shown[12];
static char game_names[6][23], game_names_shown[6][23];
static uint8_t game_states[4] = {3, 3, 3, 3}, game_states_shown[4];
static bool game_pending;
static char reports[4][6][19], report_shown[6][19];
static uint16_t report_kills[10];
static uint8_t report_heights[10];
static bool report_received;

static void report_screen(bool full, bool fresh) {
    unsigned index = game_detail - 4;
    if (full) {
        const char *titles[4] = {"TAKIM 1 / 2", "TAKIM 2 / 2", "BUGUN", "SON 10 MAC"};
        lcd_text(12, 44, titles[index], TEAL, BG, 2);
        for (unsigned i = 0; i < 6; i++)
            for (unsigned j = 0; j < 19; j++)
                report_shown[i][j] = 127;
        for (unsigned i = 0; i < 10; i++)
            report_heights[i] = 0;
        card(8, 240, 52, 36, PANEL);
        lcd_text(16, 254, "GERI", WHITE, PANEL, 1);
        card(66, 240, 76, 36, PANEL);
        lcd_text(80, 254, "ONCEKI", WHITE, PANEL, 1);
        card(148, 240, 84, 36, PANEL);
        lcd_text(165, 254, "SONRAKI", WHITE, PANEL, 1);
    }
    for (unsigned row = 0; row < (index == 3 ? 2u : 6u); row++) {
        int y = 72 + (int)row * 27;
        for (unsigned col = 0; col < 18; col++) {
            char c = fresh && report_received ? reports[index][row][col] : ' ';
            if (!c)
                c = ' ';
            if (c != report_shown[row][col]) {
                char glyph[2] = {c, 0};
                lcd_text(12 + (int)col * 12, y, glyph, row % 3 == 0 ? BLUE : WHITE, BG, 2);
                report_shown[row][col] = c;
            }
        }
    }
    if (index == 3) {
        unsigned max = 1;
        for (unsigned i = 0; i < 10; i++)
            if (report_kills[i] < 1000 && report_kills[i] > max)
                max = report_kills[i];
        for (unsigned i = 0; i < 10; i++) {
            unsigned h = fresh && report_received && report_kills[i] < 1000
                             ? 1 + report_kills[i] * 78 / max
                             : 0;
            unsigned old = report_heights[i];
            int x = 13 + (int)i * 22;
            if (h > old)
                lcd_fill(x, 212 - (int)h, 15, (int)(h - old), TEAL);
            if (h < old)
                lcd_fill(x, 212 - (int)old, 15, (int)(old - h), BG);
            report_heights[i] = (uint8_t)h;
        }
        if (full)
            lcd_text(12, 220, "ESKI                 YENI", MUTED, BG, 1);
    }
}

static void game_text(int x, int y, const char *text, char *previous, unsigned width,
                      uint16_t color, uint16_t bg) {
    for (unsigned i = 0; i < width; i++)
        if (text[i] != previous[i]) {
            char glyph[2] = {text[i] ? text[i] : ' ', 0};
            lcd_text(x + (int)i * 6, y, glyph, color, bg, 1);
            previous[i] = text[i];
        }
}
static void game_icon(int x, int y, unsigned id, uint16_t fg, uint16_t bg) {
    if (id == 0) {
        card(x + 9, y, 10, 17, fg);
        lcd_fill(x + 6, y + 10, 2, 9, fg);
        lcd_fill(x + 20, y + 10, 2, 9, fg);
        lcd_fill(x + 7, y + 19, 14, 2, fg);
        lcd_fill(x + 13, y + 20, 2, 4, fg);
        lcd_fill(x + 8, y + 24, 12, 2, fg);
    } else if (id == 1)
        icon(x, y + 3, 3, fg, bg);
    else if (id == 2 || id == 3) {
        lcd_fill(x + 3, y + 11, 22, 4, fg);
        if (id == 3)
            lcd_fill(x + 12, y + 2, 4, 22, fg);
    } else if (id == 4) {
        card(x + 3, y + 10, 8, 14, fg);
        card(x + 16, y + 2, 8, 14, fg);
        lcd_fill(x + 4, y + 4, 6, 4, fg);
        lcd_fill(x + 17, y + 19, 6, 4, fg);
    } else
        icon(x, y, 10, fg, bg);
}
/* 18x22 status glyphs; a slash also identifies disabled states without color. */
static void voice_icon(int x, int y, bool headphones, bool disabled) {
    uint16_t fg = disabled ? ORANGE : TEAL;
    lcd_fill(x, y, 18, 22, PANEL);
    if (headphones) {
        lcd_fill(x + 4, y + 2, 10, 2, fg);
        lcd_fill(x + 2, y + 4, 2, 12, fg);
        lcd_fill(x + 14, y + 4, 2, 12, fg);
        lcd_fill(x + 1, y + 11, 5, 9, fg);
        lcd_fill(x + 12, y + 11, 5, 9, fg);
    } else {
        lcd_fill(x + 6, y + 1, 6, 12, fg);
        lcd_fill(x + 3, y + 9, 2, 7, fg);
        lcd_fill(x + 13, y + 9, 2, 7, fg);
        lcd_fill(x + 4, y + 16, 10, 2, fg);
        lcd_fill(x + 8, y + 18, 2, 3, fg);
        lcd_fill(x + 5, y + 20, 8, 2, fg);
    }
    if (disabled)
        for (int i = 0; i < 16; i++)
            lcd_fill(x + i, y + 2 + i, 2, 2, fg);
}
static void game_button(unsigned id, bool full, bool fresh) {
    int x = 8 + (int)(id % 2) * 116, y = id < 2 ? 98 : 180 + (int)((id - 2) / 2) * 32;
    int state = 0;
    if (id == 0)
        state = fresh ? (int)game_values[3] : 2;
    if (id == 1)
        state = fresh ? (int)game_values[2] : 2;
    if (id == 4)
        state = fresh ? (int)game_values[4] : 2;
    if (!full && game_shown[4 + id] == state)
        return;
    game_shown[4 + id] = state;
    const char *labels[6] = {"MIKROFON", "DISCORD", "SES -", "SES +", "AYAK SESI", "AKICILIK"};
    uint16_t accent = TEAL;
    if (state == 1)
        accent = id == 4 ? TEAL : ORANGE;
    if (state == 2)
        accent = MUTED;
    card(x, y, 108, id < 2 ? 76 : 28, PANEL);
    const char *hint = id == 0   ? (state == 2 ? (game_extra[6] ? "BENI SEC" : "AYARLA")
                                    : state    ? "KAPALI"
                                               : "ACIK")
                       : id == 1 ? (state == 2 ? "BEKLIYOR"
                                    : state    ? "SESSIZ"
                                               : "ACIK")
                       : id == 4 ? (state == 2 ? "BAGLANTI"
                                    : state    ? "ODAK ACIK"
                                               : "NORMAL")
                       : id == 2 ? "AZALT"
                       : id == 3 ? "ARTIR"
                                 : "GRAFIK";
    if (id < 2) {
        game_icon(x + 40, y + 6, id, accent, PANEL);
        if (id == 0 && state == 1)
            for (int i = 0; i < 26; i++)
                lcd_fill(x + 40 + i, y + 6 + i, 2, 2, accent);
        lcd_text(x + 30, y + 36, labels[id], WHITE, PANEL, 1);
        card(x + 12, y + 50, 84, 20, accent);
        unsigned n = 0;
        while (hint[n])
            ++n;
        lcd_text(x + (108 - (int)n * 6) / 2, y + 56, hint, BG, accent, 1);
    } else {
        lcd_text(x + 8, y + 5, labels[id], WHITE, PANEL, 1);
        lcd_text(x + 8, y + 16, hint, accent, PANEL, 1);
    }
}
static void game_screen(bool full) {
    bool fresh = online && (uint32_t)(ticks - game_at) < 2500;
    if (full) {
        for (unsigned i = 0; i < 12; i++)
            game_shown[i] = -2;
        for (unsigned i = 0; i < 6; i++)
            for (unsigned j = 0; j < 23; j++)
                game_names_shown[i][j] = (char)127;
        for (unsigned i = 0; i < 4; i++)
            game_states_shown[i] = 255;
    }
    if (game_detail >= 4) {
        report_screen(full, fresh);
        return;
    }
    if (game_detail == 3) {
        monitor_graph(full);
        if (full)
            lcd_text(136, 49, "1%LOW", MUTED, BG, 1);
        int low = fresh && game_extra[5] < 10000 ? (int)game_extra[5] : -1;
        number_update(174, 49, low, game_shown[11], 4, TEAL, BG, 1);
        game_shown[11] = low;
        return;
    }
    if (game_detail == 1) {
        if (full) {
            lcd_text(12, 44, "SES ODASI", BLUE, BG, 2);
            for (unsigned i = 0; i < 4; i++)
                card(8, 82 + (int)i * 36, 224, 32, PANEL);
            card(8, 242, 90, 32, PANEL);
            lcd_text(28, 254, "GERI", WHITE, PANEL, 1);
            card(108, 242, 124, 32, PANEL);
            lcd_text(126, 254, "SONRAKI 4", WHITE, PANEL, 1);
        }
        char missing[23] = "DISCORD IZNI GEREKLI   ";
        game_text(12, 67, fresh ? game_names[4] : missing, game_names_shown[4], 22, MUTED, BG);
        for (unsigned i = 0; i < 4; i++) {
            uint8_t state = fresh ? game_states[i] : 3;
            uint16_t color = state == 1 ? TEAL : state == 2 ? ORANGE : MUTED;
            if (state != game_states_shown[i]) {
                lcd_fill(17, 94 + (int)i * 36, 7, 7, color);
                lcd_fill(176, 87 + (int)i * 36, 48, 22, PANEL);
                if (state != 3) {
                    voice_icon(177, 87 + (int)i * 36, false, state == 2 || state == 5);
                    voice_icon(205, 87 + (int)i * 36, true, state == 4 || state == 5);
                }
                game_states_shown[i] = state;
            }
            char blank[23] = "                      ";
            game_text(32, 95 + (int)i * 36, state == 3 ? blank : game_names[i], game_names_shown[i],
                      22, WHITE, PANEL);
        }
        return;
    }
    if (game_detail == 2) {
        if (full) {
            lcd_text(12, 44, "SON MAC", ORANGE, BG, 2);
            const char *labels[3] = {"OLDURME", "HASAR", "SIRALAMA"};
            for (unsigned i = 0; i < 3; i++) {
                int y = 96 + (int)i * 44;
                card(8, y, 224, 38, PANEL);
                lcd_text(20, y + 14, labels[i], MUTED, PANEL, 1);
            }
            card(8, 242, 90, 32, PANEL);
            lcd_text(28, 254, "GERI", WHITE, PANEL, 1);
            card(108, 242, 124, 32, PANEL);
            lcd_text(130, 254, "RAPORLAR", WHITE, PANEL, 1);
        }
        int state = fresh ? (int)game_extra[1] : 2;
        if (game_shown[3] != state) {
            lcd_text(12, 70,
                     state == 1   ? "SON TAMAMLANAN MAC      "
                     : state == 0 ? "PC'DEN PUBG API AYARLA  "
                     : state == 3 ? "MAC VERISI BEKLENIYOR   "
                                  : "VERI ALINAMADI         ",
                     MUTED, BG, 1);
            game_shown[3] = state;
        }
        for (unsigned i = 0; i < 3; i++) {
            int value = state == 1 ? (int)game_extra[2 + i] : -1;
            number_update(142, 106 + (int)i * 44, value, game_shown[i], 5, WHITE, PANEL, 2);
            game_shown[i] = value;
        }
        game_text(12, 232, game_names[5], game_names_shown[5], 22, MUTED, BG);
        return;
    }
    if (full) {
        const char *labels[3] = {"FPS", "GPU %", "DAKIKA"};
        for (unsigned i = 0; i < 3; i++) {
            int x = 8 + (int)i * 76;
            card(x, 41, 72, 48, PANEL);
            lcd_text(x + 8, 48, labels[i], MUTED, PANEL, 1);
        }
        card(8, 250, 108, 26, PANEL);
        lcd_text(29, 259, "SES ODASI", TEAL, PANEL, 1);
        card(124, 250, 108, 26, PANEL);
        lcd_text(148, 259, "SON MAC", ORANGE, PANEL, 1);
    }
    int values[3] = {fresh ? monitor_values[3] : -1, fresh ? monitor_values[2] : -1,
                     fresh ? (int)game_values[5] : -1};
    for (unsigned i = 0; i < 3; i++) {
        number_update(16 + (int)i * 76, 63, values[i], game_shown[i], 4, WHITE, PANEL, 2);
        game_shown[i] = values[i];
    }
    for (unsigned i = 0; i < 6; i++)
        game_button(i, full, fresh);
    int volume = fresh && game_values[1] <= 100 ? (int)game_values[1] : -1;
    number_update(104, 90, volume, game_shown[10], 3, TEAL, BG, 1);
    game_shown[10] = volume;
    if (full) {
        lcd_text(12, 90, "DISCORD SES", MUTED, BG, 1);
        lcd_text(124, 90, "%", MUTED, BG, 1);
    }
}
static void game_command(unsigned action) {
    if (!online || pending)
        return;
    pending = ++sequence;
    if (!pending)
        pending = ++sequence;
    game_pending = true;
    sent_at = ticks;
    protocol_numbers('J', (uint32_t[]){pending, action}, 2);
    set_notice("OYUN KOMUTU GONDERILDI");
}
static bool game_receive(const char *body) {
    uint32_t v[7];
    if (protocol_parse(body, 'W', v, 4)) {
        if (!v[0] || v[1] > 3 || v[2] > (v[1] == 2 ? 4u : v[1] == 3 ? 7u : 3u) || v[3] > 2)
            return true;
        display_activity();
        unsigned detail = v[1] == 3 ? game_detail : v[1] == 2 ? monitor_detail : 0;
        if (page != v[1] || detail != v[2] || (v[1] == 1 && app_page != v[3])) {
            page = v[1];
            app_page = v[3];
            monitor_detail = v[1] == 2 ? v[2] : 4;
            game_detail = v[1] == 3 ? v[2] : 0;
            dirty = true;
            highlighted = 99;
        }
        protocol_numbers('H', (uint32_t[]){v[0], 1}, 2);
        return true;
    }
    if (body[0] == 'P' && body[1] == ',' && body[2] >= '0' && body[2] <= '3' && body[3] == ',' &&
        body[4] >= '0' && body[4] <= '5' && body[5] == ',') {
        unsigned n = 0;
        while (body[6 + n] && n < 19)
            ++n;
        if (n != 18)
            return true;
        for (unsigned i = 0; i < 18; i++)
            reports[(unsigned)(body[2] - '0')][(unsigned)(body[4] - '0')][i] = body[6 + i];
        report_received = true;
        return true;
    }
    if (protocol_parse(body, 'B', v, 2)) {
        if (v[0] < 10 && v[1] <= 1000)
            report_kills[v[0]] = (uint16_t)v[1];
        return true;
    }
    if (protocol_parse(body, 'G', v, 7)) {
        if (v[0] > 1 || v[1] > 101 || v[2] > 2 || v[3] > 2 || v[4] > 1 || v[5] > 999 ||
            v[6] > 10000)
            return true;
        if (preferences.auto_game && !display_sleeping() && v[0] && !game_values[0]) {
            page = 3;
            game_detail = 0;
            dirty = true;
            highlighted = 99;
        }
        for (unsigned i = 0; i < 7; i++)
            game_values[i] = v[i];
        monitor_values[4] = v[6] == 10000 ? -1 : (int)v[6];
        game_at = ticks;
        return true;
    }
    if (protocol_parse(body, 'U', v, 7)) {
        if (v[0] > 2 || v[1] > 3 || v[2] > 999 || v[3] > 99999 || v[4] > 999 || v[5] > 10000 ||
            v[6] > 1)
            return true;
        if (v[6] != game_extra[6])
            game_shown[4] = -2;
        for (unsigned i = 0; i < 7; i++)
            game_extra[i] = v[i];
        return true;
    }
    if (body[0] == 'N' && body[1] == ',' && body[2] >= '0' && body[2] <= '5' && body[3] == ',' &&
        body[4] >= '0' && body[4] <= '5' && body[5] == ',') {
        unsigned row = (unsigned)(body[2] - '0'), length = 0;
        while (body[6 + length] && length < 23)
            ++length;
        if (length != 22)
            return true;
        for (unsigned i = 0; i < 22; i++)
            game_names[row][i] = body[6 + i];
        game_names[row][22] = 0;
        if (row < 4)
            game_states[row] = (uint8_t)(body[4] - '0');
        return true;
    }
    return false;
}
static void game_tap(int x, int y) {
    if (game_detail >= 4) {
        if (y >= 240 && y < 276) {
            if (x >= 8 && x < 60)
                game_detail = 2;
            else if (x >= 66 && x < 142)
                game_detail = game_detail == 4 ? 7 : game_detail - 1;
            else if (x >= 148 && x < 232)
                game_detail = game_detail == 7 ? 4 : game_detail + 1;
            else
                return;
            dirty = true;
        }
        return;
    }
    if (game_detail) {
        if (y >= 242 && y < 274) {
            if (x >= 8 && x < 98) {
                game_detail = 0;
                dirty = true;
            } else if (x >= 108 && x < 232 && game_detail != 3) {
                if (game_detail == 1)
                    game_command(5);
                else {
                    game_detail = 4;
                    dirty = true;
                }
            }
        }
        return;
    }
    if (y >= 41 && y < 89 && x >= 8 && x < 156) {
        page = 2;
        monitor_detail = x < 84 ? 3 : 2;
        dirty = true;
        return;
    }
    if (x >= 8 && x < 232 && (x - 8) % 116 < 108 &&
        ((y >= 98 && y < 174) || (y >= 180 && y < 240 && (y - 180) % 32 < 28))) {
        unsigned id = (y < 174 ? 0 : 2 + (unsigned)(y - 180) / 32 * 2) + (unsigned)(x - 8) / 116;
        if (id == 5) {
            game_detail = 3;
            dirty = true;
        } else
            game_command(id);
    } else if (y >= 250 && y < 276 && x >= 8 && x < 232 && (x - 8) % 116 < 108) {
        game_detail = x < 124 ? 1 : 2;
        dirty = true;
    }
}
