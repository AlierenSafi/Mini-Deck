/**
 * settings_ui.h — On-device settings UI
 *
 * Edits a preview of preferences. Save commits a record; returning without save
 * restores the previous values so navigation does not cause flash writes.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
/* Modal settings: changes preview immediately, Save persists, Back restores. */
static Preferences preferences_before;
static bool settings_error;
static unsigned settings_page;
static void settings_time(int x, int y, unsigned minutes) {
    char text[6] = {(char)('0' + minutes / 60 / 10), (char)('0' + minutes / 60 % 10), ':',
                    (char)('0' + minutes % 60 / 10), (char)('0' + minutes % 10),      0};
    lcd_text(x, y, text, TEAL, PANEL, 1);
}
static unsigned setting_cycle(unsigned current, const unsigned *values, unsigned count, bool plus) {
    unsigned i = 0;
    while (i < count && values[i] != current)
        ++i;
    if (i == count)
        i = 0;
    return values[(i + count + (plus ? 1u : count - 1)) % count];
}
static void settings_screen(void) {
    lcd_fill(0, 0, 240, 320, BG);
    lcd_text(12, 12, "AYARLAR", WHITE, BG, 2);
    lcd_text(12, 31, settings_error ? "KAYIT BASARISIZ / TEKRAR DENE" : "DEGISTIRMEK ICIN DOKUN",
             settings_error ? ORANGE : MUTED, BG, 1);
    const char *labels[6] = {"TEMA",           "SLOT YAZISI",  "ACILIS SAYFASI", "KUCUK GRAFIKLER",
                             "PUBG OTO GECIS", "ACILIS LOGOSU"};
    const char *pages[4] = {"MEDYA", "SLOT", "IZLEME", "OYUN"};
    const char *values[6] = {preferences.theme ? "SICAK TAS" : "GRAFIT MINT",
                             preferences.large_text ? "BUYUK" : "NORMAL",
                             pages[preferences.start_page],
                             preferences.mini_graphs ? "ACIK" : "KAPALI",
                             preferences.auto_game ? "ACIK" : "KAPALI",
                             preferences.boot_logo ? "ACIK" : "KAPALI"};
    for (unsigned i = 0; i < (settings_page ? 4u : 6u); i++) {
        int y = 46 + (int)i * 34;
        card(8, y, 224, 32, PANEL);
        if (!settings_page) {
            lcd_text(18, y + 5, labels[i], MUTED, PANEL, 1);
            lcd_text(18, y + 18, values[i], TEAL, PANEL, 1);
            arrow(214, y + 9, true);
        } else if (settings_page == 1) {
            const char *names[4] = {"NORMAL PARLAKLIK", "DOKUNMADAN BEKLEME", "KARARMA PARLAKLIGI",
                                    "KAPANMADAN BEKLEME"};
            unsigned val[4] = {preferences.brightness, preferences.idle_seconds,
                               preferences.dim_percent, preferences.dim_seconds};
            lcd_text(18, y + 5, names[i], MUTED, PANEL, 1);
            if (i == 1 && !val[i])
                lcd_text(70, y + 18, "SUREKLI ACIK", TEAL, PANEL, 1);
            else {
                lcd_number(70, y + 18, val[i], TEAL, PANEL, 1);
                lcd_text(107, y + 18, (i == 0 || i == 2) ? "%" : "SANIYE", TEAL, PANEL, 1);
            }
            lcd_text(18, y + 18, "-", TEAL, PANEL, 1);
            lcd_text(210, y + 18, "+", TEAL, PANEL, 1);
        } else {
            const char *names[4] = {"OTOMATIK TEMA", "MINT BASLANGIC", "MINT BITIS", "KART SAATI"};
            lcd_text(18, y + 5, names[i], MUTED, PANEL, 1);
            if (i == 0)
                lcd_text(18, y + 18, preferences.auto_theme ? "ACIK" : "KAPALI", TEAL, PANEL, 1);
            else if (i < 3)
                settings_time(90, y + 18, i == 1 ? preferences.mint_start : preferences.mint_end);
            else {
                int now = display_clock_minutes();
                if (now >= 0)
                    settings_time(18, y + 18, (unsigned)now);
                else
                    lcd_text(18, y + 18, "PC SAATI BEKLENIYOR", TEAL, PANEL, 1);
            }
            if (i == 1 || i == 2) {
                lcd_text(18, y + 18, "-15", TEAL, PANEL, 1);
                lcd_text(198, y + 18, "+15", TEAL, PANEL, 1);
            }
        }
    }
    if (settings_page == 1) {
        lcd_text(12, 195, "SOL: AZALT / SAG: ARTIR", MUTED, BG, 1);
        lcd_text(12, 212, "DOKUN: UYAN / SONRA KULLAN", MUTED, BG, 1);
    }
    if (settings_page == 2) {
        lcd_text(12, 195, "DIGER SAATLER: SICAK TAS", MUTED, BG, 1);
        lcd_text(12, 212, "MANUEL TEMA OTOYU KAPATIR", MUTED, BG, 1);
        lcd_text(12, 229, "AYNI SAAT: TUM GUN MINT", MUTED, BG, 1);
    }
    card(8, 250, 224, 26, PANEL);
    arrow(20, 257, false);
    arrow(214, 257, true);
    const char *tabs[3] = {"GENEL  1/3", "EKRAN  2/3", "OTO TEMA 3/3"};
    lcd_text(72, 259, tabs[settings_page], TEAL, PANEL, 1);
    card(8, 281, 96, 34, PANEL);
    lcd_text(32, 292, "GERI", WHITE, PANEL, 2);
    card(112, 281, 120, 34, TEAL);
    lcd_text(136, 292, "KAYDET", BG, TEAL, 2);
    dirty = false;
}
static void settings_tap(int x, int y) {
    if (y >= 250 && y < 276 && x >= 8 && x < 232) {
        settings_page = (settings_page + (x < 120 ? 2 : 1)) % 3;
        dirty = true;
        return;
    }
    if (x >= 8 && x < 232 && y >= 46 && y < 248 && (y - 46) % 34 < 32) {
        unsigned row = (unsigned)(y - 46) / 34;
        bool plus = x >= 120;
        if (settings_page && row >= 4)
            return;
        if (settings_page == 1) {
            const unsigned idle[] = {0, 30, 60, 120, 300, 600, 900, 1800, 3600},
                           delay[] = {0, 5, 10, 15, 30, 60, 120};
            if (row == 0)
                preferences.brightness =
                    plus ? (preferences.brightness >= 100 ? 10 : preferences.brightness + 10)
                         : (preferences.brightness <= 10 ? 100 : preferences.brightness - 10);
            else if (row == 1)
                preferences.idle_seconds = setting_cycle(preferences.idle_seconds, idle, 9, plus);
            else if (row == 2)
                preferences.dim_percent =
                    plus ? (preferences.dim_percent >= 100 ? 0 : preferences.dim_percent + 10)
                         : (preferences.dim_percent < 10 ? 100 : preferences.dim_percent - 10);
            else
                preferences.dim_seconds = setting_cycle(preferences.dim_seconds, delay, 7, plus);
        } else if (settings_page == 2) {
            if (row == 0)
                preferences.auto_theme ^= 1;
            else if (row == 1)
                preferences.mint_start = (preferences.mint_start + (plus ? 15 : 1425)) % 1440;
            else if (row == 2)
                preferences.mint_end = (preferences.mint_end + (plus ? 15 : 1425)) % 1440;
            display_theme_refresh();
        } else if (row == 0) {
            preferences.theme ^= 1;
            preferences.auto_theme = 0;
        } else if (row == 1)
            preferences.large_text ^= 1;
        else if (row == 2)
            preferences.start_page = (preferences.start_page + 1) % 4;
        else if (row == 3)
            preferences.mini_graphs ^= 1;
        else if (row == 4)
            preferences.auto_game ^= 1;
        else
            preferences.boot_logo ^= 1;
        display_activity();
        settings_error = false;
        dirty = true;
    } else if (y >= 281 && y < 315) {
        if (x >= 8 && x < 104) {
            preferences = preferences_before;
            display_activity();
            settings_open = false;
            dirty = true;
        } else if (x >= 112 && x < 232) {
            if (preferences_save())
                settings_open = false;
            else
                settings_error = true;
            dirty = true;
        }
    }
}
