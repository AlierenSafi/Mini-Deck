/**
 * protocol.c — Serial frame codec
 *
 * Accepts bounded printable frames with CRC16 protection. Malformed, stale or
 * oversized input is discarded before the application receives a message.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "protocol.h"
static char frame[FRAME_MAX];
static unsigned used;
static bool active;
static uint32_t last_byte, errors_seen;
static uint16_t crc_byte(uint16_t crc, uint8_t byte) {
    crc ^= (uint16_t)byte << 8;
    for (unsigned i = 0; i < 8; i++)
        crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    return crc;
}
static int hex(char c) {
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}
/* Resynchronize on @ and publish a body only after length, character and CRC checks succeed. */
bool protocol_poll(char *body) {
    if (errors_seen != uart_rx_errors) {
        errors_seen = uart_rx_errors;
        active = false;
        used = 0;
    }
    if (active && (uint32_t)(ticks - last_byte) > 250) {
        active = false;
        used = 0;
    }
    int ch;
    for (unsigned budget = 0; budget < 256 && (ch = uart_get()) >= 0; budget++) {
        last_byte = ticks;
        if (ch == '@') {
            active = true;
            used = 0;
            continue;
        }
        if (!active || ch == '\r')
            continue;
        if (ch == '\n') {
            active = false;
            if (used < 6 || frame[used - 5] != '*')
                continue;
            unsigned len = used - 5;
            uint16_t crc = 0xffff, received = 0;
            bool valid = true;
            for (unsigned i = 0; i < len; i++)
                crc = crc_byte(crc, (uint8_t)frame[i]);
            for (unsigned i = len + 1; i < used; i++) {
                int nibble = hex(frame[i]);
                if (nibble < 0) {
                    valid = false;
                    break;
                }
                received = (uint16_t)((received << 4) | (unsigned)nibble);
            }
            if (!valid || crc != received)
                continue;
            for (unsigned i = 0; i < len; i++)
                body[i] = frame[i];
            body[len] = 0;
            return true;
        }
        if (ch < 32 || ch > 126 || used >= FRAME_MAX - 1) {
            active = false;
            used = 0;
            continue;
        }
        frame[used++] = (char)ch;
    }
    return false;
}
void protocol_send(const char *body) {
    uint16_t crc = 0xffff;
    char trailer[8] = {'*', 0, 0, 0, 0, '\n', 0, 0};
    for (const char *p = body; *p; p++)
        crc = crc_byte(crc, (uint8_t)*p);
    for (unsigned i = 0; i < 4; i++)
        trailer[1 + i] = "0123456789ABCDEF"[(crc >> (12 - i * 4)) & 15];
    uart_puts("@");
    uart_puts(body);
    uart_puts(trailer);
}
void protocol_numbers(char type, const uint32_t *values, unsigned count) {
    char body[FRAME_MAX];
    unsigned n = 0;
    body[n++] = type;
    if (count > 7)
        return;
    for (unsigned i = 0; i < count; i++) {
        char reversed[10];
        unsigned digits = 0;
        uint32_t value = values[i];
        body[n++] = ',';
        do {
            reversed[digits++] = (char)('0' + value % 10);
            value /= 10;
        } while (value);
        while (digits)
            body[n++] = reversed[--digits];
    }
    body[n] = 0;
    protocol_send(body);
}
bool protocol_parse(const char *p, char type, uint32_t *values, unsigned count) {
    if (*p++ != type)
        return false;
    for (unsigned i = 0; i < count; i++) {
        if (*p++ != ',')
            return false;
        if (*p < '0' || *p > '9')
            return false;
        uint32_t value = 0;
        do {
            unsigned digit = (unsigned)(*p++ - '0');
            if (value > 429496729u || (value == 429496729u && digit > 5))
                return false;
            value = value * 10 + digit;
        } while (*p >= '0' && *p <= '9');
        values[i] = value;
    }
    return *p == 0;
}
