/**
 * display_power.c — Backlight and theme scheduler
 *
 * Controls PWM brightness, inactivity stages and local RTC theme scheduling.
 * The first touch after dim/sleep wakes the display without executing an action.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "display_power.h"
#define PWM(o) REG(0x40018000u + (o))
#define RTC(o) REG(0x40024000u + (o))
#define CLOCK_MAGIC 0x4d44434bu
static bool pwm_ready;
static uint32_t last_activity;
static unsigned stage, applied = 101;
void backlight_set(unsigned percent) {
    if (percent > 100)
        percent = 100;
    if (!pwm_ready) {
        REG(0x400fc0c4) |= 1u << 6;
        REG(0x400fc1a8) = (REG(0x400fc1a8) & ~(3u << 12)) | (1u << 12);
        PWM(4) = 2;
        PWM(0x0c) = 0;
        PWM(0x70) = 0;
        PWM(0x14) = 2;
        PWM(0x18) = cpu_hz / 2000u; /* 2 kHz, single-edge PWM1.6 on P1.26 */
        PWM(0x4c) = 1u << 14;
        PWM(0x48) = cpu_hz / 2000u;
        PWM(0x50) = 0x41;
        PWM(4) = 9;
        pwm_ready = true;
    }
    if (percent == 0 || percent == 100) {
        if (percent)
            high(1, LCD_BL);
        else
            low(1, LCD_BL);
        GPIO(1, 0) |= LCD_BL;
        PINSEL(3) &= ~(3u << 20);
    } else {
        PWM(0x48) = (cpu_hz / 2000u) * percent / 100u;
        PWM(0x50) = 1u << 6;
        PINSEL(3) = (PINSEL(3) & ~(3u << 20)) | (2u << 20);
    }
}
int display_clock_minutes(void) {
    if (RTC(0x44) != CLOCK_MAGIC || !(RTC(8) & 1))
        return -1;
    uint32_t ct = RTC(0x14);
    unsigned h = (ct >> 16) & 31, m = (ct >> 8) & 63;
    return h < 24 && m < 60 ? (int)(h * 60 + m) : -1;
}
void display_clock_sync(unsigned hour, unsigned minute) {
    if (hour >= 24 || minute >= 60)
        return;
    if (display_clock_minutes() == (int)(hour * 60 + minute))
        return;
    RTC(8) = 2;
    RTC(0x0c) = 0;
    RTC(0x10) = 255;
    RTC(0x20) = 0;
    RTC(0x24) = minute;
    RTC(0x28) = hour;
    RTC(0x2c) = 1;
    RTC(0x30) = 0;
    RTC(0x34) = 1;
    RTC(0x38) = 1;
    RTC(0x3c) = 2026;
    RTC(0x44) = CLOCK_MAGIC;
    RTC(8) = 1;
}
bool display_theme_refresh(void) {
    int minute = display_clock_minutes();
    if (!preferences.auto_theme || minute < 0)
        return false;
    unsigned start = preferences.mint_start, end = preferences.mint_end, t = (unsigned)minute;
    bool mint = start == end || (start < end ? (t >= start && t < end) : (t >= start || t < end));
    unsigned theme = mint ? 0 : 1;
    if (theme == preferences.theme)
        return false;
    preferences.theme = theme;
    return true;
}
void display_tick(void) {
    uint32_t elapsed = (uint32_t)(ticks - last_activity) / 1000u;
    if (stage != 2 || !preferences.idle_seconds) {
        stage = 0;
        if (preferences.idle_seconds && elapsed >= preferences.idle_seconds)
            stage = elapsed - preferences.idle_seconds >= preferences.dim_seconds ? 2 : 1;
    }
    unsigned value = stage == 2 ? 0 : stage == 1 ? preferences.dim_percent : preferences.brightness;
    if (value > preferences.brightness)
        value = preferences.brightness;
    if (value != applied) {
        backlight_set(value);
        applied = value;
    }
}
bool display_activity(void) {
    bool wake = stage != 0;
    last_activity = ticks;
    stage = 0;
    display_tick();
    return wake;
}
bool display_sleeping(void) {
    return stage != 0;
}
void display_init(void) {
    REG(0x400fc0c4) |= 1u << 9;
    last_activity = ticks;
    stage = 0;
    applied = 101;
    display_tick();
    display_theme_refresh();
}
