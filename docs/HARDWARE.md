# Hardware Notes

Target: Haoyu/PowerMCU LPC1768 Mini-DK2 with the HY28A-style 240 × 320 resistive touchscreen. The firmware contains controller/orientation handling for the tested panel; similarly named replacement panels may differ.

- [Board schematic](https://www.haoyuelectronics.com/Attachment/LPC1768-Mini-DK2/LPC1768-Mini-DK2_Schematic.pdf)
- [HY28A schematic](https://www.haoyuelectronics.com/Attachment/LPC1768-Mini-DK2/HY28A_Schematic.pdf)
- [NXP LPC17xx user manual](https://www.nxp.com/docs/en/user-guide/UM10360.pdf)

Manufacturer PDFs are linked rather than bundled. Check supply and connector specifications against your board revision.

## Enclosure

The board outline is 95 × 78 mm. The stand places the display at approximately 55 degrees. Body mounting holes and connector alignment were reported to fit the original board. The replacement bezel shifts the display opening left by 8.5 mm and widens it to 52 mm; this revision still requires fit confirmation.

See [enclosure files](enclosure/README.md). STL and 3MF files contain geometry, not printer-specific G-code.
