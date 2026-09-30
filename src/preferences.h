#pragma once
#include "board.h"
typedef struct {
    uint32_t theme, large_text, start_page, mini_graphs, auto_game, boot_logo;
    uint32_t brightness, idle_seconds, dim_percent, dim_seconds, auto_theme, mint_start, mint_end;
} Preferences;
extern Preferences preferences;
void preferences_load(void);
bool preferences_save(void);
