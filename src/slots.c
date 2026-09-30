/**
 * slots.c — Profile and icon synchronization
 *
 * Stages a revision before activation and acknowledges individual transfer steps.
 * Icon storage is split across SRAM banks to preserve stack headroom.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "slots.h"
/* Split icon storage across local and AHB SRAM; leave local stack headroom. */
static DeckSlot local_slots[12];
static DeckSlot ahb_slots[12] __attribute__((section(".ahb_slots")));
DeckSlot *deck_slot(unsigned index) {
    if (index >= SLOT_COUNT)
        return 0;
    return index < 12 ? &local_slots[index] : &ahb_slots[index - 12];
}
void deck_init(void) {
    for (unsigned i = 0; i < SLOT_COUNT; i++) {
        DeckSlot *slot = deck_slot(i);
        for (unsigned j = 0; j < ICON_PIXELS; j++)
            slot->pixels[j] = 0;
        for (unsigned j = 0; j < sizeof(slot->label); j++)
            slot->label[j] = 0;
        slot->enabled = false;
    }
}
uint32_t deck_revision;
bool deck_syncing, deck_configured;
static uint32_t staging_revision, completed, changes, last_id, last_result;
static bool have_last;
static unsigned loading = SLOT_COUNT, offset;
static bool number(const char **cursor, uint32_t *value) {
    const char *p = *cursor;
    if (*p < '0' || *p > '9')
        return false;
    uint32_t v = 0;
    do {
        unsigned digit = (unsigned)(*p++ - '0');
        if (v > 429496729u || (v == 429496729u && digit > 5))
            return false;
        v = v * 10 + digit;
    } while (*p >= '0' && *p <= '9');
    *cursor = p;
    *value = v;
    return true;
}
static bool next(const char **p, uint32_t *value) {
    if (**p != ',')
        return false;
    ++*p;
    return number(p, value);
}
static int hex(char c) {
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}
bool deck_receive(const char *body) {
    if (body[0] != 'X' || body[1] != ',')
        return false;
    const char *p = body + 2;
    uint32_t id, slot = 0, arg = 0;
    bool ok = false;
    if (!number(&p, &id) || !id || *p++ != ',')
        return true;
    if (have_last && id == last_id) {
        protocol_numbers('Y', (uint32_t[]){id, last_result}, 2);
        return true;
    }
    char operation = *p++;
    if (operation == 'B' && next(&p, &arg) && !*p && arg) {
        staging_revision = arg;
        completed = 0;
        loading = SLOT_COUNT;
        deck_syncing = true;
        ok = true;
    } else if (operation == 'b' && deck_configured && !deck_syncing && next(&p, &arg) && arg &&
               next(&p, &slot) && slot == deck_revision && !*p) {
        staging_revision = arg;
        completed = (1u << SLOT_COUNT) - 1;
        loading = SLOT_COUNT;
        deck_syncing = true;
        ok = true;
    } else if (operation == 'L' && deck_syncing && next(&p, &slot) && slot < SLOT_COUNT &&
               next(&p, &arg) && arg <= 1 && *p++ == ',') {
        unsigned len = 0;
        bool valid = true;
        while (p[len]) {
            if (len >= 10 || p[len] < 32 || p[len] > 126 || p[len] == ',' || p[len] == '*' ||
                p[len] == '@') {
                valid = false;
                break;
            }
            ++len;
        }
        if (valid && len) {
            for (unsigned i = 0; i <= len; i++)
                deck_slot(slot)->label[i] = p[i];
            deck_slot(slot)->enabled = arg != 0;
            loading = slot;
            offset = 0;
            completed &= ~(1u << slot);
            ok = true;
        }
    } else if (operation == 'I' && deck_syncing && next(&p, &slot) && slot == loading &&
               slot < SLOT_COUNT && next(&p, &arg) && arg == offset && *p++ == ',') {
        uint16_t words[48];
        unsigned len = 0;
        while (p[len] && len < 193)
            ++len;
        if (len && len <= 192 && len % 4 == 0 && offset + len / 4 <= ICON_PIXELS) {
            ok = true;
            for (unsigned i = 0; i < len / 4 && ok; i++) {
                unsigned value = 0;
                for (unsigned j = 0; j < 4; j++) {
                    int h = hex(p[i * 4 + j]);
                    if (h < 0) {
                        ok = false;
                        break;
                    }
                    value = (value << 4) | (unsigned)h;
                }
                words[i] = (uint16_t)value;
            }
            if (ok) {
                for (unsigned i = 0; i < len / 4; i++)
                    deck_slot(slot)->pixels[offset + i] = words[i];
                offset += len / 4;
            }
        }
    } else if (operation == 'F' && deck_syncing && next(&p, &slot) && slot == loading &&
               slot < SLOT_COUNT && !*p &&
               (offset == ICON_PIXELS || (!deck_slot(slot)->enabled && offset == 0))) {
        completed |= 1u << slot;
        changes |= 1u << slot;
        loading = SLOT_COUNT;
        ok = true;
    } else if (operation == 'Z' && deck_syncing && next(&p, &arg) && arg == staging_revision &&
               !*p && completed == ((1u << SLOT_COUNT) - 1)) {
        deck_revision = staging_revision;
        deck_syncing = false;
        deck_configured = true;
        ok = true;
    }
    last_id = id;
    last_result = ok;
    have_last = true;
    protocol_numbers('Y', (uint32_t[]){id, ok}, 2);
    return true;
}
uint32_t deck_take_changes(void) {
    uint32_t result = changes;
    changes = 0;
    return result;
}
