#pragma once
#include <stdint.h>
#include <stdbool.h>
#define REG(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define GPIO(p, o) REG(0x2009c000u + (p) * 0x20u + (o))
#define PINSEL(n) REG(0x4002c000u + (n) * 4u)
#define LED1 (1u << 25)
#define LED2 (1u << 26)
#define LCD_BL (1u << 26)
#define LCD_CS (1u << 16)
#define TP_CS (1u << 6)
#define TP_CLK (1u << 7)
#define TP_MISO (1u << 8)
#define TP_MOSI (1u << 9)
#define TP_IRQ (1u << 13)
extern volatile uint32_t ticks;
extern uint32_t cpu_hz;
void board_init(void);
void firmware_report(void);
void delay_ms(uint32_t ms);
void delay_us(uint32_t us);
void watchdog_feed(void);
void uart_puts(const char *s);
void uart_hex(uint32_t value);
void uart_uint(uint32_t value);
int uart_get(void);
extern volatile uint32_t uart_rx_errors;
void led_set(unsigned led, bool on);
static inline void high(unsigned p, uint32_t m) {
    GPIO(p, 0x18) = m;
}
static inline void low(unsigned p, uint32_t m) {
    GPIO(p, 0x1c) = m;
}
static inline bool pin(unsigned p, uint32_t m) {
    return (GPIO(p, 0x14) & m) != 0;
}
