/**
 * boot_logo.h — Startup identity
 *
 * Draws the startup monogram using the generated mask and active theme.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "logo_mask.h"
static uint16_t logo_blend(uint16_t fg, uint16_t bg, unsigned a) {
    unsigned r = (((fg >> 11) & 31) * a + ((bg >> 11) & 31) * (3 - a)) / 3;
    unsigned g = (((fg >> 5) & 63) * a + ((bg >> 5) & 63) * (3 - a)) / 3;
    unsigned b = ((fg & 31) * a + (bg & 31) * (3 - a)) / 3;
    return (uint16_t)((r << 11) | (g << 5) | b);
}
static unsigned logo_alpha(unsigned x, unsigned y) {
    return (logo_mask[y * 35 + x / 4] >> (6 - 2 * (x % 4))) & 3;
}
static __attribute__((noinline)) void boot_logo(void) {
    lcd_fill(0, 0, 240, 320, BG);
    for (unsigned y = 0; y < 170; y++) {
        uint16_t colors[4];
        for (unsigned a = 0; a < 4; a++)
            colors[a] = logo_blend(y >= 150 ? MUTED : TEAL, BG, a);
        for (unsigned x = 0; x < 140;) {
            unsigned a = logo_alpha(x, y), end = x + 1;
            while (end < 140 && logo_alpha(end, y) == a)
                ++end;
            if (a)
                lcd_fill(50 + (int)x, 80 + (int)y, (int)(end - x), 1, colors[a]);
            x = end;
        }
    }
}
