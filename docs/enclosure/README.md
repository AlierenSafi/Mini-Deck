# Mini Deck Desktop Enclosure

| File | Purpose |
|------|---------|
| `01_body.stl` | Main housing; mounting/port fit reported successful |
| `02_bezel_v1.stl` | Replacement front plate; verify display clearance |
| `03_stand.stl` | Angled desktop support |
| `04_fit_check.stl` | Fit-check part |
| `mini-deck-bezel-v1.3mf` | Replacement bezel geometry |
| `mini-deck-fit-check.3mf` | Fit-check geometry |
| `02_bezel.stl` | Original reference plate, retained for CAD regression checks; do not use for the revised opening |

Source generators are `tools/build_enclosure.py` and `tools/build_bezel_v1.py`. Install `cad-dependencies.txt` separately if editing the model. Run the base generator before the bezel generator. Dimensions and estimation assumptions are recorded in `measurements.json`.

Import geometry into Bambu Studio or your slicer and select the actual printer/material. No printer profile or G-code is supplied. Check connector cable clearance and the bezel before printing the complete set.
