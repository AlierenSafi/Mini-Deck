/**
 * ui_type.h — Antialiased text renderer
 *
 * Expands 4-bit glyph coverage into a bounded reusable AHB buffer. The atlas is
 * generated from Roboto Mono under SIL OFL 1.1, not a Windows system font.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
/* Fixed-cell antialiased display font, independent of the legacy slot font. */
#include "ui_font_data.h"
static uint16_t ui_glyph_pixels[540] __attribute__((section(".ahb_slots")));
static uint16_t ui_blend(uint16_t fg, uint16_t bg, unsigned alpha) {
    unsigned inv = 15 - alpha;
    return (uint16_t)(((((fg >> 11) * alpha + (bg >> 11) * inv + 7) / 15) << 11) |
                      (((((fg >> 5) & 63) * alpha + ((bg >> 5) & 63) * inv + 7) / 15) << 5) |
                      (((fg & 31) * alpha + (bg & 31) * inv + 7) / 15));
}
static void ui_text(int x, int y, const char *text, uint16_t fg, uint16_t bg, unsigned scale) {
    if (scale < 1 || scale > 3)
        return;
    unsigned w = 6 * scale, h = scale == 1 ? 12 : scale == 2 ? 20 : 30, stride = w * h / 2;
    const uint8_t *font = scale == 1 ? ui_font_1 : scale == 2 ? ui_font_2 : ui_font_3;
    while (*text && x + (int)w <= 240) {
        unsigned c = (unsigned char)*text++;
        if (c < 32 || c > 126)
            c = '?';
        const uint8_t *glyph = font + (c - 32) * stride;
        for (unsigned i = 0; i < w * h; i++)
            ui_glyph_pixels[i] = ui_blend(fg, bg, (i & 1) ? glyph[i / 2] & 15 : glyph[i / 2] >> 4);
        lcd_bitmap(x, y, w, h, ui_glyph_pixels);
        x += (int)w;
    }
}
static void ui_number(int x, int y, int value, int previous, unsigned width, uint16_t fg,
                      uint16_t bg, unsigned scale) {
    if (value == previous)
        return;
    char text[6], old[6];
    number_string(value, width, text);
    number_string(previous, width, old);
    for (unsigned i = 0; i < width; i++)
        if (previous == -2 || text[i] != old[i]) {
            char ch[2] = {text[i], 0};
            ui_text(x + (int)(i * 6 * scale), y, ch, fg, bg, scale);
        }
}
static void ui_round(int x, int y, int w, int h, int r, uint16_t color) {
    for (int row = 0; row < h; row++) {
        int dy = row < r ? r - 1 - row : row >= h - r ? row - (h - r) : 0, cut = 0;
        if (row < r || row >= h - r) {
            while (cut < r && (r - cut) * (r - cut) + dy * dy > r * r)
                cut++;
        }
        lcd_fill(x + cut, y + row, w - 2 * cut, 1, color);
    }
}
