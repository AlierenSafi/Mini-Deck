#pragma once
#include "preferences.h"
void backlight_set(unsigned percent);
void display_init(void);
bool display_activity(void); /* true: consume this wake gesture */
void display_tick(void);
bool display_sleeping(void);
void display_clock_sync(unsigned hour, unsigned minute);
int display_clock_minutes(void);
bool display_theme_refresh(void);
