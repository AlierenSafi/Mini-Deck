/**
 * preferences.c — Persistent UI preferences
 *
 * Loads versioned, CRC-checked records from reserved flash. Old records are
 * migrated with defaults; settings changes are saved only on explicit commit.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "preferences.h"
#define CAL_START 0x70000u
#define CAL_END 0x78000u
#define CAL_MAGIC 0x32554950u
static uint32_t record[64];
static uint32_t checksum(const uint8_t *data, unsigned count) {
    uint32_t crc = 0xffffffffu;
    for (unsigned i = 0; i < count; i++) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ ((0u - (crc & 1)) & 0xedb88320u);
    }
    return ~crc;
}
/* Treat stored flash as untrusted: validate each field as well as the record checksum. */
static bool valid(const uint32_t *p) {
    bool base = p[0] == CAL_MAGIC && p[2] <= 1 && p[3] <= 1 && p[4] <= 3 && p[5] <= 1 &&
                p[6] <= 1 && (p[7] <= 1 || p[7] == 0xffffffffu);
    if (!base)
        return false;
    if (p[1] == 1)
        return checksum((const uint8_t *)p, 32) == p[8];
    return p[1] == 2 && checksum((const uint8_t *)p, 60) == p[15] && p[8] >= 10 && p[8] <= 100 &&
           p[9] <= 3600 && p[10] <= 100 && p[11] <= 120 && p[12] <= 1 && p[13] < 1440 &&
           p[14] < 1440;
}
Preferences preferences = {0, 0, 1, 1, 1, 1, 100, 120, 50, 10, 0, 1140, 360};
void preferences_load(void) {
    const uint32_t *latest = 0;
    for (uint32_t a = CAL_START; a < CAL_END; a += 256) {
        const uint32_t *p = (const uint32_t *)(uintptr_t)a;
        if (valid(p))
            latest = p;
    }
    if (latest) {
        preferences = (Preferences){
            latest[2], latest[3], latest[4], latest[5], latest[6], latest[7] == 0 ? 0 : 1, 100, 120,
            50,        10,        0,         1140,      360};
        if (latest[1] == 2) {
            preferences.brightness = latest[8];
            preferences.idle_seconds = latest[9];
            preferences.dim_percent = latest[10];
            preferences.dim_seconds = latest[11];
            preferences.auto_theme = latest[12];
            preferences.mint_start = latest[13];
            preferences.mint_end = latest[14];
        }
    }
}
static bool iap(uint32_t cmd, uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
    uint32_t input[5] = {cmd, a, b, c, d}, output[5];
    output[0] = 0xffffffffu;
    uint32_t mask;
    watchdog_feed();
    __asm volatile("mrs %0, primask\ncpsid i" : "=r"(mask)::"memory");
    ((void (*)(uint32_t *, uint32_t *))0x1fff1ff1u)(input, output);
    __asm volatile("msr primask, %0" ::"r"(mask) : "memory");
    watchdog_feed();
    return output[0] == 0;
}
bool preferences_save(void) {
    for (unsigned i = 0; i < 64; i++)
        record[i] = 0xffffffffu;
    record[0] = CAL_MAGIC;
    record[1] = 2;
    record[2] = preferences.theme;
    record[3] = preferences.large_text;
    record[4] = preferences.start_page;
    record[5] = preferences.mini_graphs;
    record[6] = preferences.auto_game;
    record[7] = preferences.boot_logo;
    record[8] = preferences.brightness;
    record[9] = preferences.idle_seconds;
    record[10] = preferences.dim_percent;
    record[11] = preferences.dim_seconds;
    record[12] = preferences.auto_theme;
    record[13] = preferences.mint_start;
    record[14] = preferences.mint_end;
    record[15] = checksum((const uint8_t *)record, 60);
    uint32_t target = 0;
    const uint32_t *latest = 0;
    for (uint32_t address = CAL_START; address < CAL_END; address += 256) {
        const uint32_t *p = (const uint32_t *)(uintptr_t)address;
        bool blank = true;
        for (unsigned i = 0; i < 64; i++)
            if (p[i] != 0xffffffffu) {
                blank = false;
                break;
            }
        if (blank && !target)
            target = address;
        if (valid(p))
            latest = p;
    }
    if (latest && latest[1] == 2) {
        bool same = true;
        for (unsigned i = 0; i < 16; i++)
            if (latest[i] != record[i])
                same = false;
        if (same)
            return true;
    }
    if (!target) {
        if (!iap(50, 28, 28, 0, 0) || !iap(52, 28, 28, cpu_hz / 1000, 0))
            return false;
        target = CAL_START;
    }
    if (!iap(50, 28, 28, 0, 0) || !iap(51, target, (uint32_t)(uintptr_t)record, 256, cpu_hz / 1000))
        return false;
    const uint32_t *p = (const uint32_t *)(uintptr_t)target;
    for (unsigned i = 0; i < 64; i++)
        if (p[i] != record[i])
            return false;
    return valid(p);
}
