/**
 * touch.c — Resistive touch driver
 *
 * Samples raw touch coordinates and applies the saved affine calibration.
 * Display navigation uses calibrated coordinates, never raw ADC values.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "touch.h"
static Point calibration[3];
static int64_t determinant;
void touch_init(void) {
    PINSEL(0) &= ~(0xffu << 12);
    high(0, TP_CS);
    low(0, TP_CLK | TP_MOSI);
    GPIO(0, 0) |= TP_CS | TP_CLK | TP_MOSI;
    GPIO(0, 0) &= ~TP_MISO;
}
bool touch_down(void) {
    return !pin(2, TP_IRQ);
}
static uint8_t shift(uint8_t out) {
    uint8_t in = 0;
    for (unsigned i = 0; i < 8; i++) {
        low(0, TP_CLK);
        if (out & 128)
            high(0, TP_MOSI);
        else
            low(0, TP_MOSI);
        out <<= 1;
        delay_us(2);
        high(0, TP_CLK);
        delay_us(2);
        in = (in << 1) | (pin(0, TP_MISO) ? 1 : 0);
    }
    low(0, TP_CLK);
    return in;
}
static uint16_t channel(uint8_t cmd) {
    low(0, TP_CS);
    shift(cmd);
    delay_us(5);
    uint16_t value = (uint16_t)shift(0) << 8;
    value |= shift(0);
    high(0, TP_CS);
    return (value >> 3) & 4095;
}
static int median(int32_t a[5]) {
    for (unsigned i = 1; i < 5; i++) {
        int32_t t = a[i];
        unsigned j = i;
        while (j && a[j - 1] > t) {
            a[j] = a[j - 1];
            --j;
        }
        a[j] = t;
    }
    return a[2];
}
bool touch_raw(Point *p) {
    if (!touch_down())
        return false;
    int32_t x[5], y[5];
    for (unsigned i = 0; i < 5; i++) {
        x[i] = channel(0xd0);
        y[i] = channel(0x90); /* 12-bit differential, power down after read. */
    }
    p->x = median(x);
    p->y = median(y);
    return touch_down() && x[4] - x[0] < 100 && y[4] - y[0] < 100 && p->x > 50 && p->x < 4045 &&
           p->y > 50 && p->y < 4045;
}
bool touch_points_valid(const Point raw[3]) {
    for (unsigned i = 0; i < 3; i++)
        if (raw[i].x < 50 || raw[i].x > 4045 || raw[i].y < 50 || raw[i].y > 4045)
            return false;
    int64_t d = (int64_t)(raw[1].x - raw[0].x) * (raw[2].y - raw[0].y) -
                (int64_t)(raw[2].x - raw[0].x) * (raw[1].y - raw[0].y);
    return d > 50000 || d < -50000;
}
bool touch_calibrate(const Point raw[3]) {
    if (!touch_points_valid(raw))
        return false;
    for (unsigned i = 0; i < 3; i++)
        calibration[i] = raw[i];
    determinant = (int64_t)(raw[1].x - raw[0].x) * (raw[2].y - raw[0].y) -
                  (int64_t)(raw[2].x - raw[0].x) * (raw[1].y - raw[0].y);
    return true;
}
void touch_get_calibration(Point raw[3]) {
    for (unsigned i = 0; i < 3; i++)
        raw[i] = calibration[i];
}
Point touch_map(Point p) {
    if (!determinant)
        return (Point){0, 0};
    int64_t a = (int64_t)(p.x - calibration[0].x) * (calibration[2].y - calibration[0].y) -
                (int64_t)(calibration[2].x - calibration[0].x) * (p.y - calibration[0].y);
    int64_t b = (int64_t)(calibration[1].x - calibration[0].x) * (p.y - calibration[0].y) -
                (int64_t)(p.x - calibration[0].x) * (calibration[1].y - calibration[0].y);
    Point result = {24 + (int32_t)((191 * a + 96 * b) / determinant),
                    64 + (int32_t)((96 * a + 231 * b) / determinant)};
    return result;
}
