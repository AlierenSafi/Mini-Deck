#pragma once
#include "protocol.h"
#define SLOT_COUNT 24
#define ICON_SIZE 32
#define ICON_PIXELS (ICON_SIZE * ICON_SIZE)
typedef struct {
    uint16_t pixels[ICON_PIXELS];
    char label[11];
    bool enabled;
} DeckSlot;
DeckSlot *deck_slot(unsigned index);
void deck_init(void);
extern uint32_t deck_revision;
extern bool deck_syncing, deck_configured;
bool deck_receive(const char *body);
uint32_t deck_take_changes(void);
