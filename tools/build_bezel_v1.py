"""Replacement bezel only; never rewrites the proven body, stand or original plate."""

import hashlib
import json
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle
from build_enclosure import OUT, bezel, rounded, zero, mesh, export_3mf, body, cover_screws, cyl


def main():
    protected = [OUT / name for name in ("01_body.stl", "02_bezel.stl", "03_stand.stl")]
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    # Screw-plane homography, measured on the user's assembled-case photo.
    points = [(185, 350), (960, 333), (156, 1185), (959, 1209)]
    a = []
    b = []
    for (x, y), (u, v) in zip(points, cover_screws[:2] + cover_screws[2:]):
        a.extend([[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]])
        b.extend([u, v])
    h = np.append(np.linalg.solve(a, b), 1).reshape(3, 3)

    def project(x, y):
        p = h @ [x, y, 1]
        return (p[:2] / p[2]).tolist()

    right = [project(712, 449), project(697, 1062)]
    # 8.5 mm left shift, 1 mm extra horizontal clearance per side; Y is unchanged.
    # bezel() uses 50 mm width; enlarge only that same through-window to 52 mm.
    lid = bezel(40.5, 52.5) - rounded(52, 70, 5, 1.2, (14.5, 17.5, 21))
    printable = zero(lid.rotate((180, 0, 0)))
    t = mesh(printable)
    assert (
        t.is_watertight and t.is_winding_consistent and t.volume > 0 and len(lid.decompose()) == 1
    )
    assert np.allclose(t.extents, [98, 106, 3.6], atol=0.001)
    assert abs((body ^ lid).volume()) < 0.01
    for x, y in cover_screws:
        assert abs((lid ^ cyl(1.39, 6, (x, y, 20))).volume()) < 0.001
    t.export(OUT / "02_bezel_v1.stl")
    export_3mf(
        OUT / "mini-deck-bezel-v1.3mf",
        [("02_bezel_v1", printable, (15, 15, 0))],
        "Mini Deck replacement bezel v1 - shifted 8.5 mm left",
    )
    report = dict(
        photo="assembly-fit-reference (not distributed)",
        screw_centres_px=points,
        projected_lcd_right_mm=right,
        old_opening_mm=[50, 70],
        new_opening_mm=[52, 70],
        old_centre_mm=[49, 52.5],
        new_centre_mm=[40.5, 52.5],
        horizontal_shift_mm=-8.5,
        vertical_shift_mm=0,
        photo_uncertainty_mm=1,
        physical_fit="not yet printed; left LCD edge is occluded in reference photo",
        watertight=bool(t.is_watertight),
        connected_components=len(lid.decompose()),
        bounds_mm=t.extents.tolist(),
        body_overlap_mm3=(body ^ lid).volume(),
        unchanged_sha256=hashes,
    )
    for p in protected:
        assert hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name]
    (OUT / "bezel-v1-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    fig, ax = plt.subplots(figsize=(6, 6.6), layout="constrained")
    ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            98,
            106,
            boxstyle="round,pad=0,rounding_size=6",
            facecolor="#e7e7e4",
            edgecolor="#30383a",
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (14.5, 17.5),
            52,
            70,
            boxstyle="round,pad=0,rounding_size=1.2",
            facecolor="#80c9b0",
            edgecolor="#245f4b",
            label="v1: 52 × 70 mm",
        )
    )
    ax.add_patch(
        FancyBboxPatch(
            (24, 17.5),
            50,
            70,
            boxstyle="round,pad=0,rounding_size=1.2",
            facecolor="none",
            edgecolor="#ae563b",
            linestyle="--",
            label="Önceki: 50 × 70 mm",
        )
    )
    for x, y in cover_screws:
        ax.add_patch(Circle((x, y), 1.4, color="#30383a"))
    ax.annotate(
        "", xy=(40.5, 95), xytext=(49, 95), arrowprops=dict(arrowstyle="->", color="#245f4b", lw=2)
    )
    ax.text(49, 99, "8,5 mm sola", ha="center")
    ax.set_title("Ön çerçeve v1 · ekranın okuma yönünden")
    ax.set(xlim=(-3, 101), ylim=(110, -3), aspect="equal", xlabel="mm", ylabel="mm")
    ax.legend(loc="upper left", fontsize=9)
    fig.savefig(OUT / "bezel-v1-comparison.png", dpi=160)
    plt.close(fig)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
