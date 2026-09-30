#pragma once
#include "board.h"
#define LCD_W 240
#define LCD_H 320
bool lcd_init(void);
void lcd_flip_x(void);
void lcd_flip_y(void);
void lcd_fill(int x, int y, int w, int h, uint16_t color);
void lcd_text(int x, int y, const char *text, uint16_t fg, uint16_t bg, unsigned scale);
void lcd_number(int x, int y, unsigned number, uint16_t fg, uint16_t bg, unsigned scale);
void lcd_bitmap(int x, int y, unsigned w, unsigned h, const uint16_t *pixels);
void lcd_icon48(int x, int y, const uint16_t *pixels);
extern uint16_t lcd_id;
extern bool lcd_parallel;
extern uint16_t lcd_icon_background;
extern uint16_t lcd_icon_foreground;
