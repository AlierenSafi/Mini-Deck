/**
 * board.c — LPC1768 hardware support
 *
 * Initializes clocks, GPIO, UART and watchdog. Shared counters and ring buffers
 * bridge interrupt handlers with the non-interrupt application loop.
 *
 * Author: Ali Eren Safi
 * License: MIT (third-party font data retains SIL OFL 1.1)
 */
#include "board.h"
volatile uint32_t ticks;
uint32_t cpu_hz = 4000000u;
/* Single ISR producer / main-loop consumer; aligned indices are atomic on M3. */
static volatile uint8_t rx_buffer[512];
static volatile unsigned rx_head, rx_tail;
volatile uint32_t uart_rx_errors;
void UART0_IRQHandler(void) {
    for (unsigned budget = 0; budget < 32; budget++) {
        uint32_t cause = REG(0x4000c008);
        if (cause & 1)
            break;
        uint32_t status = REG(0x4000c014);
        if (status & 0x1e)
            ++uart_rx_errors;
        if (status & 1) {
            uint8_t byte = (uint8_t)REG(0x4000c000);
            unsigned next = (rx_head + 1) & 511u;
            if (next != rx_tail) {
                rx_buffer[rx_head] = byte;
                rx_head = next;
            } else
                ++uart_rx_errors;
        }
    }
}
static void pll_feed(void) {
    REG(0x400fc08c) = 0xaa;
    REG(0x400fc08c) = 0x55;
}
static void clock_init(void) {
    /* Disconnect/disable PLL before selecting the 12 MHz board crystal. */
    REG(0x400fc080) = 1;
    pll_feed();
    REG(0x400fc080) = 0;
    pll_feed();
    REG(0x400fc10c) = 0;
    REG(0x400fc104) = 0;
    REG(0x400fc000) = 0x303a; /* Flash access: 4 clocks, safe through 80 MHz. */
    REG(0x400fc1a0) |= 1u << 5;
    unsigned timeout = 1000000;
    while (!(REG(0x400fc1a0) & (1u << 6)) && --timeout) {
    }
    if (!timeout)
        return; /* Remain on 4 MHz IRC. */
    REG(0x400fc10c) = 1;
    REG(0x400fc084) = 11;
    pll_feed();          /* FCCO=2*12*12 MHz = 288 MHz. */
    REG(0x400fc104) = 5; /* CCLK=288/6=48 MHz. */
    REG(0x400fc080) = 1;
    pll_feed();
    timeout = 1000000;
    while (!(REG(0x400fc088) & (1u << 26)) && --timeout) {
    }
    if (!timeout) {
        REG(0x400fc080) = 0;
        pll_feed();
        REG(0x400fc10c) = 0;
        REG(0x400fc104) = 0;
        return;
    }
    REG(0x400fc080) = 3;
    pll_feed();
    cpu_hz = 48000000u;
}
void SysTick_Handler(void) {
    ++ticks;
}
void watchdog_feed(void) {
    /* Prevent interrupts between the mandatory two writes. */
    uint32_t saved;
    __asm volatile("mrs %0, primask\ncpsid i" : "=r"(saved)::"memory");
    REG(0x40000008) = 0xaa;
    REG(0x40000008) = 0x55;
    __asm volatile("msr primask, %0" ::"r"(saved) : "memory");
}
void delay_ms(uint32_t ms) {
    uint32_t start = ticks;
    while ((uint32_t)(ticks - start) < ms) {
        watchdog_feed();
        __asm volatile("wfi");
    }
}
void delay_us(uint32_t us) {
    uint32_t start = REG(0xe0001004), cycles = us * (cpu_hz / 1000000u);
    while ((uint32_t)(REG(0xe0001004) - start) < cycles) {
    }
}
void led_set(unsigned led, bool on) {
    uint32_t mask = led == 1 ? LED1 : LED2;
    if (on)
        low(3, mask);
    else
        high(3, mask); /* Board LEDs are active low. */
}
void uart_puts(const char *s) {
    while (*s) {
        uint32_t start = ticks;
        while (!(REG(0x4000c014) & 0x20)) {
            if ((uint32_t)(ticks - start) > 50)
                return;
        }
        REG(0x4000c000) = (uint8_t)*s++;
    }
}
void uart_hex(uint32_t v) {
    char s[9];
    for (unsigned i = 0; i < 8; i++)
        s[i] = "0123456789ABCDEF"[(v >> (28 - 4 * i)) & 15];
    s[8] = 0;
    uart_puts(s);
}
void uart_uint(uint32_t v) {
    char s[11];
    unsigned n = 10;
    s[n] = 0;
    do {
        s[--n] = '0' + v % 10;
        v /= 10;
    } while (v);
    uart_puts(&s[n]);
}
int uart_get(void) {
    if (rx_tail == rx_head)
        return -1;
    int byte = rx_buffer[rx_tail];
    rx_tail = (rx_tail + 1) & 511u;
    return byte;
}
void board_init(void) {
    clock_init();
    REG(0x400fc040) = 1; /* Map physical flash, not the ISP ROM vector overlay. */
    REG(0xe000ed08) = 0; /* Vector table in flash. */
    REG(0x400fc0c4) |= (1u << 3) | (1u << 15) | (1u << 21);
    PINSEL(0) = (PINSEL(0) & ~0xf0u) | 0x50u;                     /* UART0 P0.2/3. */
    REG(0x400fc1a8) = (REG(0x400fc1a8) & ~(3u << 6)) | (1u << 6); /* UART PCLK=CCLK. */
    REG(0x4000c00c) = 0x83;
    REG(0x4000c000) = cpu_hz == 48000000 ? 26 : 2;
    REG(0x4000c004) = 0;
    REG(0x4000c028) = cpu_hz == 48000000 ? 0x10 : 0xc1;
    REG(0x4000c00c) = 3;
    REG(0x4000c008) = 7;
    REG(0x4000c004) = 0;
    REG(0x4000c004) = 5;       /* RDA, CTI and line-status IRQs; 1-byte FIFO trigger. */
    REG(0xe000e100) = 1u << 5; /* UART0 IRQ5. */
    PINSEL(7) &= ~(0xfu << 18);
    high(3, LED1 | LED2);
    GPIO(3, 0) |= LED1 | LED2;
    PINSEL(3) &= ~(0xffu << 20);
    high(1, LCD_BL | (1u << 27) | (1u << 28) | (1u << 29));
    GPIO(1, 0) |= LCD_BL | (1u << 27) | (1u << 28) | (1u << 29);
    PINSEL(4) &= ~(0xfffu << 16); /* LCD CS, keys, PENIRQ. */
    high(2, 1u << 8);
    GPIO(2, 0) |= 1u << 8;
    GPIO(2, 0) &= ~((1u << 10) | (1u << 11) | (1u << 12) | TP_IRQ);
    REG(0xe000edfc) |= 1u << 24;
    REG(0xe0001000) |= 1;
    REG(0xe0001004) = 0;
    REG(0xe000e014) = cpu_hz / 1000 - 1;
    REG(0xe000e018) = 0;
    REG(0xe000e010) = 7;
    REG(0x40000010) = 0; /* Watchdog clock: independent 4 MHz IRC / 4. */
    REG(0x40000004) = 8000000;
    REG(0x40000000) = 3;
    watchdog_feed();
    __asm volatile("cpsie i");
    uart_puts("\r\nMINI DECK v1\r\nCPU=");
    uart_uint(cpu_hz);
    uart_puts(" UART=115200 8N1\r\n");
    firmware_report();
}
void firmware_report(void) {
    extern uint8_t _flash_end;
    uint32_t size = (uint32_t)(uintptr_t)&_flash_end, crc = 0xffffffffu;
    for (uint32_t address = 0; address < size; address++) {
        crc ^= *(volatile const uint8_t *)(uintptr_t)address;
        for (unsigned bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ ((0u - (crc & 1)) & 0xedb88320u);
    }
    uart_puts("FLASH_CRC32=");
    uart_hex(~crc);
    uart_puts(" LEN=");
    uart_uint(size);
    uart_puts("\r\n");
}
