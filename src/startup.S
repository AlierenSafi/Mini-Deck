.syntax unified
.cpu cortex-m3
.thumb
.section .vectors,"a",%progbits
.global vectors
vectors:
.word _stack_top, Reset_Handler, Default_Handler, Default_Handler
.word Default_Handler, Default_Handler, Default_Handler, 0
.word 0,0,0,Default_Handler,Default_Handler,0,Default_Handler,SysTick_Handler
.rept 5
.word Default_Handler
.endr
.word UART0_IRQHandler
.rept 29
.word Default_Handler
.endr
.section .text.Reset_Handler,"ax",%progbits
.balign 4
.global Reset_Handler
.type Reset_Handler,%function
.thumb_func
Reset_Handler:
  cpsid i
  ldr r0, =_stack_top
  mov sp, r0
  ldr r0, =_sidata
  ldr r1, =_sdata
  ldr r2, =_edata
1: cmp r1, r2
  bcs 2f
  ldr r3, [r0], #4
  str r3, [r1], #4
  b 1b
2: ldr r1, =_sbss
  ldr r2, =_ebss
  movs r3, #0
3: cmp r1, r2
  bcs 4f
  str r3, [r1], #4
  b 3b
4: bl main
  b .
.size Reset_Handler, .-Reset_Handler
.section .text.Default_Handler,"ax",%progbits
.thumb_func
Default_Handler:
  ldr r0, =0xe000ed0c
  ldr r1, =0x05fa0004
  str r1, [r0]
  b .
