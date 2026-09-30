/**
 * calibration.c — Touch calibration storage
 *
 * Validates and persists calibration records in the reserved flash sector.
 * Invalid records must not silently become a usable calibration.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "touch.h"
#define CAL_START 0x78000u
#define CAL_END 0x80000u
#define CAL_MAGIC 0x324c4143u
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
static bool valid(const uint32_t *p) {
    return p[0] == CAL_MAGIC && p[1] == 1 && checksum((const uint8_t *)p, 32) == p[8] &&
           touch_points_valid((const Point *)(p + 2));
}
bool touch_load(void) {
    const uint32_t *latest = 0;
    for (uint32_t address = CAL_START; address < CAL_END; address += 256) {
        const uint32_t *p = (const uint32_t *)(uintptr_t)address;
        if (valid(p))
            latest = p;
    }
    return latest && touch_calibrate((const Point *)(latest + 2));
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
bool touch_save(void) {
    Point raw[3];
    touch_get_calibration(raw);
    if (!touch_points_valid(raw))
        return false;
    for (unsigned i = 0; i < 64; i++)
        record[i] = 0xffffffffu;
    record[0] = CAL_MAGIC;
    record[1] = 1;
    for (unsigned i = 0; i < 3; i++) {
        record[2 + i * 2] = (uint32_t)raw[i].x;
        record[3 + i * 2] = (uint32_t)raw[i].y;
    }
    record[8] = checksum((const uint8_t *)record, 32);
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
    if (latest && latest[8] == record[8])
        return true;
    if (!target) {
        if (!iap(50, 29, 29, 0, 0) || !iap(52, 29, 29, cpu_hz / 1000, 0))
            return false;
        target = CAL_START;
    }
    if (!iap(50, 29, 29, 0, 0) || !iap(51, target, (uint32_t)(uintptr_t)record, 256, cpu_hz / 1000))
        return false;
    const uint32_t *p = (const uint32_t *)(uintptr_t)target;
    for (unsigned i = 0; i < 64; i++)
        if (p[i] != record[i])
            return false;
    return valid(p);
}
