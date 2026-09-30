#pragma once
#include "board.h"
#define FRAME_MAX 256
bool protocol_poll(char *body);
void protocol_send(const char *body);
void protocol_numbers(char type, const uint32_t *values, unsigned count);
bool protocol_parse(const char *body, char type, uint32_t *values, unsigned count);
