#pragma once
#include "board.h"
typedef struct {
    int32_t x, y;
} Point;
void touch_init(void);
bool touch_raw(Point *p);
bool touch_down(void);
bool touch_calibrate(const Point raw[3]);
Point touch_map(Point raw);
bool touch_points_valid(const Point raw[3]);
void touch_get_calibration(Point raw[3]);
bool touch_load(void);
bool touch_save(void);
