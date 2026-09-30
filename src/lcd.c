/**
 * lcd.c — Display driver
 *
 * Owns the LCD bus and controller coordinate transforms. Pixel transfers are
 * bounded to the panel; application code requests rectangles, glyphs or bitmaps.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "lcd.h"
/* HY28A: SPI ILI9320 panel PB or 16-bit 8080 panel PA. See docs schematics. */
uint16_t lcd_id;
bool lcd_parallel;
static bool bus_error;
/* HY28A-LCDA: keep scan registers fixed; map the panel's bottom-origin Y in lcd_fill. */
static uint16_t source_direction = 0x0000;
static uint16_t gate_direction = 0x2700;
#define RS (1u << 27)
#define WR (1u << 28)
#define RD (1u << 29)
#define DATA0 (0xffu << 15)
#define DATA2 0xffu
#define SSP(o) REG(0x40088000u + (o))
static uint8_t spi(uint8_t data) {
    uint32_t start = ticks;
    while (!(SSP(0x0c) & 2)) {
        if ((uint32_t)(ticks - start) > 20) {
            bus_error = true;
            return 0;
        }
    }
    SSP(8) = data;
    while (!(SSP(0x0c) & 4)) {
        if ((uint32_t)(ticks - start) > 20) {
            bus_error = true;
            return 0;
        }
    }
    return (uint8_t)SSP(8);
}
static void select(bool active) {
    if (lcd_parallel) {
        if (active)
            low(2, 1u << 8);
        else
            high(2, 1u << 8);
    } else {
        if (active)
            low(0, LCD_CS);
        else
            high(0, LCD_CS);
    }
}
static void par_out(uint16_t v) {
    low(0, DATA0);
    low(2, DATA2);
    high(0, ((uint32_t)v >> 8) << 15);
    high(2, v & 255);
    low(1, WR);
    __asm volatile("nop\nnop\nnop\nnop");
    high(1, WR);
}
static void index_reg(uint16_t r) {
    select(true);
    if (lcd_parallel) {
        low(1, RS);
        par_out(r);
        high(1, RS);
    } else {
        spi(0x70);
        spi(r >> 8);
        spi(r);
    }
    select(false);
}
static void write_reg(uint16_t r, uint16_t v) {
    index_reg(r);
    select(true);
    if (lcd_parallel)
        par_out(v);
    else {
        spi(0x72);
        spi(v >> 8);
        spi(v);
    }
    select(false);
}
static uint16_t read_reg(uint16_t r) {
    index_reg(r);
    select(true);
    uint16_t v;
    if (lcd_parallel) {
        GPIO(0, 0) &= ~DATA0;
        GPIO(2, 0) &= ~DATA2;
        low(1, RD);
        delay_us(2);
        v = (uint16_t)(((GPIO(0, 0x14) >> 15) & 255) << 8) | (GPIO(2, 0x14) & 255);
        high(1, RD);
        select(false);
        GPIO(0, 0) |= DATA0;
        GPIO(2, 0) |= DATA2;
    } else {
        spi(0x73);
        spi(0);
        v = (uint16_t)spi(0) << 8;
        v |= spi(0);
        select(false);
    }
    return v;
}
void lcd_flip_x(void) {
    source_direction ^= 0x0100;
    write_reg(1, source_direction);
    uart_puts("LCD SS=");
    uart_hex(source_direction);
    uart_puts("\r\n");
}
void lcd_flip_y(void) {
    gate_direction ^= 0x8000;
    write_reg(0x60, gate_direction);
    uart_puts("LCD GS=");
    uart_hex(gate_direction);
    uart_puts("\r\n");
}
static bool supported(uint16_t id) {
    return id == 0x9320 || id == 0x9325 || id == 0x5408;
}
bool lcd_init(void) {
    /* SSP0 mode 3, 8 bits. Slow probe first; SD-card CS is kept inactive. */
    high(1, 1u << 21);
    GPIO(1, 0) |= 1u << 21;
    PINSEL(0) = (PINSEL(0) & ~(3u << 30)) | (2u << 30);
    PINSEL(1) = (PINSEL(1) & ~0x3fu) | 0x28;
    high(0, LCD_CS);
    GPIO(0, 0) |= LCD_CS;
    REG(0x400fc1ac) = (REG(0x400fc1ac) & ~(3u << 10)) | (1u << 10);
    SSP(4) = 0;
    SSP(0) = 0xc7;
    SSP(0x10) = 120;
    SSP(4) = 2;
    delay_ms(100);
    lcd_id = read_reg(0);
    uart_puts("LCD SPI ID=");
    uart_hex(lcd_id);
    uart_puts("\r\n");
    if (!supported(lcd_id)) {
        SSP(4) = 0;
        PINSEL(0) &= ~(3u << 30);
        PINSEL(1) &= ~0x3fffu;
        lcd_parallel = true;
        GPIO(0, 0) |= DATA0;
        GPIO(2, 0) |= DATA2;
        lcd_id = read_reg(0);
        uart_puts("LCD PARALLEL ID=");
        uart_hex(lcd_id);
        uart_puts("\r\n");
    } else {
        SSP(4) = 0;
        SSP(0x10) = 12;
        SSP(4) = 2;
    } /* 4 MHz at 48 MHz CCLK. */
    if (!supported(lcd_id) || bus_error)
        return false;
    /* SPFD5408 / ILI9320/9325 register-compatible initialization.
       Power values follow the controller reference; scan direction is panel-specific. */
    if (lcd_id == 0x9325) {
        write_reg(0xe3, 0x3008);
        write_reg(0xe7, 0x0012);
        write_reg(0xef, 0x1231);
    } else {
        write_reg(0xe5, 0x8000);
        write_reg(0, 1);
    }
    if (lcd_id != 0x5408)
        source_direction = 0x0100;
    write_reg(1, source_direction);
    write_reg(2, 0x0700);
    write_reg(3, 0x1030);
    write_reg(4, 0);
    write_reg(8, 0x0202);
    write_reg(9, 0);
    write_reg(0xa, 0);
    write_reg(0xc, 0);
    write_reg(0xd, 0);
    write_reg(0xf, 0);
    write_reg(0x10, 0);
    write_reg(0x11, 7);
    write_reg(0x12, 0);
    write_reg(0x13, 0);
    delay_ms(200);
    write_reg(0x10, 0x17b0);
    write_reg(0x11, lcd_id == 0x5408 ? 7 : 0x0031);
    delay_ms(50);
    write_reg(0x12, lcd_id == 0x5408 ? 0x013a : 0x0138);
    delay_ms(50);
    write_reg(0x13, lcd_id == 0x5408 ? 0x1a00 : 0x1800);
    write_reg(0x29, lcd_id == 0x5408 ? 12 : 8);
    delay_ms(50);
    write_reg(0x30, 0);
    write_reg(0x31, 0x0505);
    write_reg(0x32, 4);
    write_reg(0x35, 6);
    write_reg(0x36, 0x0707);
    write_reg(0x37, 0x0105);
    write_reg(0x38, 2);
    write_reg(0x39, 0x0707);
    write_reg(0x3c, 0x0704);
    write_reg(0x3d, 0x0807);
    write_reg(0x50, 0);
    write_reg(0x51, 239);
    write_reg(0x52, 0);
    write_reg(0x53, 319);
    if (lcd_id != 0x5408)
        gate_direction = 0x2700;
    write_reg(0x60, gate_direction);
    write_reg(0x61, 1);
    write_reg(0x6a, 0);
    for (unsigned r = 0x80; r <= 0x85; r++)
        write_reg(r, 0);
    write_reg(0x90, 0x10);
    write_reg(0x92, 0);
    write_reg(0x93, 3);
    write_reg(0x95, 0x0110);
    write_reg(0x97, 0);
    write_reg(0x98, 0);
    write_reg(7, 0x0173);
    uart_puts("LCD READY ");
    uart_puts(lcd_parallel ? "PARALLEL\r\n" : "SPI\r\n");
    return !bus_error;
}
void lcd_fill(int x, int y, int w, int h, uint16_t color) {
    if (x < 0) {
        w += x;
        x = 0;
    }
    if (y < 0) {
        h += y;
        y = 0;
    }
    if (x + w > LCD_W)
        w = LCD_W - x;
    if (y + h > LCD_H)
        h = LCD_H - y;
    if (w <= 0 || h <= 0 || bus_error)
        return;
    /* This SPFD5408 panel is vertically mirrored at SS=0 / GS=0.
       Transform every primitive AFTER clipping, including subsequent text redraws.
       The touch calibration still uses logical screen coordinates (top-left origin). */
    if (lcd_id == 0x5408)
        y = LCD_H - y - h;
    write_reg(0x50, x);
    write_reg(0x51, x + w - 1);
    write_reg(0x52, y);
    write_reg(0x53, y + h - 1);
    write_reg(0x20, x);
    write_reg(0x21, y);
    index_reg(0x22);
    select(true);
    if (!lcd_parallel)
        spi(0x72);
    for (int row = 0; row < h; row++) {
        for (int col = 0; col < w; col++) {
            if (lcd_parallel)
                par_out(color);
            else {
                spi(color >> 8);
                spi(color);
            }
            if (bus_error) {
                select(false);
                return;
            }
        }
        watchdog_feed();
    }
    select(false);
}
/* Original compact 5x7 uppercase/digit font; each byte is one vertical column. */
static const uint8_t digits[10][5] = {
    {62, 81, 73, 69, 62},  {0, 66, 127, 64, 0},  {66, 97, 81, 73, 70}, {33, 65, 69, 75, 49},
    {24, 20, 18, 127, 16}, {39, 69, 69, 69, 57}, {60, 74, 73, 73, 48}, {1, 113, 9, 5, 3},
    {54, 73, 73, 73, 54},  {6, 73, 73, 41, 30}};
static const uint8_t letters[26][5] = {
    {126, 17, 17, 17, 126}, {127, 73, 73, 73, 54}, {62, 65, 65, 65, 34},  {127, 65, 65, 34, 28},
    {127, 73, 73, 73, 65},  {127, 9, 9, 9, 1},     {62, 65, 73, 73, 122}, {127, 8, 8, 8, 127},
    {0, 65, 127, 65, 0},    {32, 64, 65, 63, 1},   {127, 8, 20, 34, 65},  {127, 64, 64, 64, 64},
    {127, 2, 12, 2, 127},   {127, 4, 8, 16, 127},  {62, 65, 65, 65, 62},  {127, 9, 9, 9, 6},
    {62, 65, 81, 33, 94},   {127, 9, 25, 41, 70},  {38, 73, 73, 73, 50},  {1, 1, 127, 1, 1},
    {63, 64, 64, 64, 63},   {31, 32, 64, 32, 31},  {63, 64, 56, 64, 63},  {99, 20, 8, 20, 99},
    {7, 8, 112, 8, 7},      {97, 81, 73, 69, 67}};
static uint8_t glyph(char c, unsigned col) {
    if (c >= 'a' && c <= 'z')
        c -= 32;
    if (c >= '0' && c <= '9')
        return digits[c - '0'][col];
    if (c >= 'A' && c <= 'Z')
        return letters[c - 'A'][col];
    if (c == '-')
        return 8;
    if (c == '+')
        return col == 2 ? 62 : 8;
    if (c == ':')
        return col == 2 ? 0x24 : 0;
    if (c == '.')
        return col == 2 ? 64 : 0;
    if (c == '/')
        return 32 >> col;
    if (c == '%') {
        static const uint8_t v[5] = {99, 19, 8, 100, 99};
        return v[col];
    }
    if (c == '*')
        return col == 2 ? 28 : 8;
    return 0;
}
/* One GRAM window per glyph, instead of one window per lit pixel.
   Rows are reversed for the established SPFD5408 logical Y transform. */
static void glyph_draw(int x, int y, char c, uint16_t fg, uint16_t bg, unsigned scale) {
    int w = (int)(6 * scale), h = (int)(8 * scale);
    if (x < 0 || y < 0 || x + w > LCD_W || y + h > LCD_H || bus_error)
        return;
    int physical_y = lcd_id == 0x5408 ? LCD_H - y - h : y;
    write_reg(0x50, x);
    write_reg(0x51, x + w - 1);
    write_reg(0x52, physical_y);
    write_reg(0x53, physical_y + h - 1);
    write_reg(0x20, x);
    write_reg(0x21, physical_y);
    index_reg(0x22);
    select(true);
    if (!lcd_parallel)
        spi(0x72);
    for (int r = 0; r < h; r++) {
        unsigned row = (unsigned)(lcd_id == 0x5408 ? h - 1 - r : r) / scale;
        for (int col = 0; col < w; col++) {
            unsigned column = (unsigned)col / scale;
            uint16_t color = (column < 5 && row < 7 && (glyph(c, column) & (1u << row))) ? fg : bg;
            if (lcd_parallel)
                par_out(color);
            else {
                spi(color >> 8);
                spi(color);
            }
            if (bus_error) {
                select(false);
                return;
            }
        }
    }
    select(false);
}
void lcd_text(int x, int y, const char *s, uint16_t fg, uint16_t bg, unsigned scale) {
    if (scale < 1 || scale > 4)
        return;
    while (*s && x + (int)(6 * scale) <= LCD_W) {
        glyph_draw(x, y, *s++, fg, bg, scale);
        x += 6 * scale;
    }
}
void lcd_number(int x, int y, unsigned v, uint16_t fg, uint16_t bg, unsigned scale) {
    char s[11];
    unsigned n = 10;
    s[n] = 0;
    do {
        s[--n] = '0' + v % 10;
        v /= 10;
    } while (v);
    lcd_text(x, y, s + n, fg, bg, scale);
}
uint16_t lcd_icon_background;
uint16_t lcd_icon_foreground;
void lcd_bitmap(int x, int y, unsigned w, unsigned h, const uint16_t *pixels) {
    if (!w || !h || w > LCD_W || h > LCD_H || x < 0 || y < 0 || x + (int)w > LCD_W ||
        y + (int)h > LCD_H || bus_error)
        return;
    int py = lcd_id == 0x5408 ? LCD_H - y - (int)h : y;
    write_reg(0x50, x);
    write_reg(0x51, x + w - 1);
    write_reg(0x52, py);
    write_reg(0x53, py + h - 1);
    write_reg(0x20, x);
    write_reg(0x21, py);
    index_reg(0x22);
    select(true);
    if (!lcd_parallel)
        spi(0x72);
    for (unsigned r = 0; r < h; r++) {
        unsigned row = lcd_id == 0x5408 ? h - 1 - r : r;
        for (unsigned col = 0; col < w; col++) {
            uint16_t color = pixels[row * w + col];
            if (color == 1)
                color = lcd_icon_background;
            else if (color == 2)
                color = lcd_icon_foreground;
            if (lcd_parallel)
                par_out(color);
            else {
                spi(color >> 8);
                spi(color);
            }
            if (bus_error) {
                select(false);
                return;
            }
        }
        watchdog_feed();
    }
    select(false);
}

/* 32px source -> 48px display, streamed directly without a framebuffer. */
void lcd_icon48(int x, int y, const uint16_t *pixels) {
    if (x < 0 || y < 0 || x + 48 > LCD_W || y + 48 > LCD_H || bus_error)
        return;
    int py = lcd_id == 0x5408 ? LCD_H - y - 48 : y;
    write_reg(0x50, x);
    write_reg(0x51, x + 47);
    write_reg(0x52, py);
    write_reg(0x53, py + 47);
    write_reg(0x20, x);
    write_reg(0x21, py);
    index_reg(0x22);
    select(true);
    if (!lcd_parallel)
        spi(0x72);
    for (unsigned r = 0; r < 48; r++) {
        unsigned row = (lcd_id == 0x5408 ? 47 - r : r) * 2 / 3;
        for (unsigned col = 0; col < 48; col++) {
            uint16_t color = pixels[row * 32 + col * 2 / 3];
            if (color == 1)
                color = lcd_icon_background;
            else if (color == 2)
                color = lcd_icon_foreground;
            if (lcd_parallel)
                par_out(color);
            else {
                spi(color >> 8);
                spi(color);
            }
            if (bus_error) {
                select(false);
                return;
            }
        }
        watchdog_feed();
    }
    select(false);
}
