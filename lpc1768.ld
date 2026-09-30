ENTRY(Reset_Handler)
MEMORY {
  FLASH (rx) : ORIGIN = 0, LENGTH = 448K /* Sector 28: UI preferences; sector 29: calibration. */
  AHB (rwx) : ORIGIN = 0x2007c000, LENGTH = 32K
  RAM (rwx) : ORIGIN = 0x10000000, LENGTH = 32K
}
_stack_top = ORIGIN(RAM)+LENGTH(RAM)-32; /* IAP owns top 32 bytes. */
SECTIONS {
  .vectors : { KEEP(*(.vectors)) } > FLASH
  .crp 0x2fc : { LONG(0xffffffff) } > FLASH
  .text 0x300 : { *(.text*) *(.rodata*) . = ALIGN(4); } > FLASH
  .ARM.exidx : { *(.ARM.exidx*) } > FLASH
  _sidata = LOADADDR(.data);
  .data : { . = ALIGN(4); _sdata = .; *(.data*) . = ALIGN(4); _edata = .; } > RAM AT> FLASH
  _flash_end = LOADADDR(.data) + SIZEOF(.data);
  .bss (NOLOAD) : { . = ALIGN(4); _sbss = .; *(.bss*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
  .ahb_slots (NOLOAD) : { . = ALIGN(4); *(.ahb_slots) . = ALIGN(4); } > AHB
  ASSERT(_ebss <= _stack_top - 4096, "Insufficient space for 4 KiB stack")
}
