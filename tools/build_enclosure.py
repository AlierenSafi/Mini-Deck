"""Parametric, original Mini Deck case. Millimetres; estimated fit from supplied photos.
Exports watertight meshes and standard 3MF geometry, never printer G-code.
"""

from pathlib import Path
import json, math, zipfile, xml.etree.ElementTree as ET
import numpy as np
import manifold3d as mf
import trimesh

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/enclosure"
OUT.mkdir(exist_ok=True)
P = json.loads((OUT / "measurements.json").read_text(encoding="utf-8"))
W, H, D = P["design"]["enclosure_size"]
WALL = P["design"]["wall"]
ANGLE = 55


def box(x, y, z, at=(0, 0, 0)):
    return mf.Manifold.cube((x, y, z)).translate(at)


def cyl(r, h, at=(0, 0, 0)):
    return mf.Manifold.cylinder(h, r, circular_segments=48).translate(at)


def rounded(w, h, z, r=4, at=(0, 0, 0)):
    return mf.Manifold.extrude(
        mf.CrossSection.square((w - 2 * r, h - 2 * r))
        .offset(r, circular_segments=48)
        .translate((r, r)),
        z,
    ).translate(at)


def place(m):
    return m.rotate((ANGLE, 0, 0)).translate((0, 20, 8))


def mesh(m):
    q = m.to_mesh()
    return trimesh.Trimesh(
        np.asarray(q.vert_properties)[:, :3], np.asarray(q.tri_verts), process=True
    )


def zero(m):
    b = m.bounding_box()
    return m.translate((-b[0], -b[1], -b[2]))


# Portrait PCB position: native photo top edge becomes the case's left edge.
mounts = [(13 + 78 - y, 5.5 + x) for x, y in P["mounting_holes_native_from_top_left"]]
cover_screws = [(5, 5), (W - 5, 5), (5, H - 5), (W - 5, H - 5)]
stand_screws = [(30, 36), (68, 36), (30, 73), (68, 73)]
body = rounded(W, H, 22, 6) - rounded(W - 2 * WALL, H - 2 * WALL, 24, 3.6, (WALL, WALL, WALL))
for x, y in mounts:
    body += cyl(4.4, 6, (x, y, 0))
    body -= cyl(2.3, 8, (x, y, -1))  # M3 through-bolt + washers allows photo tolerance
for x, y in cover_screws:
    body += cyl(3.8, 8, (x, y, 14))
    body -= cyl(1.05, 9, (x, y, 14))  # M2.5 plastic pilot, not a precision thread
for p in P["ports"]:
    y = 5.5 + p["centre_along_native_top"]
    width = p["opening_width"]
    height = p["opening_height"]
    # Rounded side tunnels; each opening has a closed perimeter.
    cutter = rounded(width, height, 20, 1).rotate((90, 0, 90))
    # Rotation maps original x to y, original y to z, extrusion to x.
    cutter = cutter.translate(
        (-1 if p["side"] == "left" else W - 19, y - width / 2, p["bottom_above_floor"])
    )
    body -= cutter
# ISP/RESET access from right edge. A recessed service slot remains separately enclosed.
for native_x in (10.3, 29.3):
    body -= cyl(2.4, 14).rotate((0, 90, 0)).translate((W - 10, 5.5 + native_x, 9.5))
# Ventilation on rear plate, away from screw positions. No electrical components exposed at front.
for x in (40, 46, 52, 58):
    body -= rounded(2.2, 26, 4, 1, (x, 43, -0.5))
for x, y in stand_screws:
    body -= cyl(1.7, 5, (x, y, -1))
    body -= mf.Manifold.cylinder(1.6, 1.7, 3.1, circular_segments=48).translate((x, y, 0.8))


def bezel(cx=49, cy=52.5):
    lid = rounded(W, H, 2.4, 6, (0, 0, 22))
    lid -= rounded(50, 70, 5, 1.2, (cx - 25, cy - 35, 21))
    # A shallow locating rim, with interrupted sections clear of ports and PCB.
    rim = rounded(W - 5.6, H - 5.6, 1.2, 3.2, (2.8, 2.8, 20.8)) - rounded(
        W - 8, H - 8, 2, 2, (4, 4, 20.5)
    )
    for p in P["ports"]:
        if p["side"] == "left":
            rim -= box(
                7,
                p["opening_width"] + 4,
                5,
                (0, 5.5 + p["centre_along_native_top"] - p["opening_width"] / 2 - 2, 19),
            )
    for x, y in cover_screws:
        rim -= cyl(4.1, 3, (x, y, 20))
    lid += rim
    for x, y in cover_screws:
        lid -= cyl(1.4, 6, (x, y, 20))
        lid -= mf.Manifold.cylinder(1.3, 1.4, 2.6, circular_segments=48).translate((x, y, 23.1))
    return lid


lid = bezel()

# Separate, bolted 55 degree desktop wedge. The rear support is independent of port walls.
base = rounded(82, 88, 3.6, 6, (8, 4, 0))
support = place(box(62, 70, 4, (18, 14, -4)))
stand = base + support
start_y = 20 + 14 * math.cos(math.radians(ANGLE))
end_y = 20 + 84 * math.cos(math.radians(ANGLE))
start_z = 8 + 14 * math.sin(math.radians(ANGLE)) - 3.5
end_z = 8 + 84 * math.sin(math.radians(ANGLE)) - 3.5
profile = mf.CrossSection([[(start_y, 3), (end_y, 3), (end_y, end_z), (start_y, start_z)]])
profile = profile - profile.offset(-5)
stand += mf.Manifold.extrude(profile, 62).transform(((0, 0, 1, 18), (1, 0, 0, 0), (0, 1, 0, 0)))
for x, y in stand_screws:
    stand -= place(cyl(1.3, 7, (x, y, -6)))
# Four adhesive rubber-foot pockets (optional 8 mm feet).
for x, y in ((18, 14), (80, 14), (18, 82), (80, 82)):
    stand -= cyl(4.1, 0.8, (x, y, -0.1))

# Fit skeleton uses exactly the production mounting holes and port geometry.
fit = body - box(W - 40, H - 30, 3.5, (20, 15, -0.5))

parts = {"01_body": zero(body), "02_bezel": zero(lid.rotate((180, 0, 0))), "03_stand": zero(stand)}


def export_3mf(path, items, title):
    ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    ET.register_namespace("", ns)
    model = ET.Element(
        "{" + ns + "}model",
        unit="millimeter",
        attrib={"{http://www.w3.org/XML/1998/namespace}lang": "en-US"},
    )
    ET.SubElement(model, "metadata", name="Title").text = title
    ET.SubElement(model, "metadata", name="Description").text = (
        "Photo-estimated fit prototype. Geometry only; select Bambu A1 and filament in slicer. Not G-code."
    )
    resources = ET.SubElement(model, "resources")
    build = ET.SubElement(model, "build")
    for i, (name, m, position) in enumerate(items, 1):
        t = mesh(m)
        obj = ET.SubElement(resources, "object", id=str(i), type="model", name=name)
        mm = ET.SubElement(obj, "mesh")
        vs = ET.SubElement(mm, "vertices")
        ts = ET.SubElement(mm, "triangles")
        for v in t.vertices:
            ET.SubElement(vs, "vertex", x=f"{v[0]:.6f}", y=f"{v[1]:.6f}", z=f"{v[2]:.6f}")
        for f in t.faces:
            ET.SubElement(ts, "triangle", v1=str(f[0]), v2=str(f[1]), v3=str(f[2]))
        ET.SubElement(
            build,
            "item",
            objectid=str(i),
            transform=f"1 0 0 0 1 0 0 0 1 {position[0]} {position[1]} {position[2]}",
        )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
        )
        z.writestr("3D/3dmodel.model", ET.tostring(model, encoding="utf-8", xml_declaration=True))


def main():
    report = {}
    for name, m in {
        **parts,
        "04_fit_check": zero(fit),
        "05_bezel_photo5": zero(bezel(46, 53).rotate((180, 0, 0))),
    }.items():
        t = mesh(m)
        assert (
            m.status() == mf.Error.NoError
            and t.is_watertight
            and t.is_winding_consistent
            and t.volume > 0
        ), name
        assert len(m.decompose()) == 1, (name, "disconnected shells")
        t.export(OUT / (name + ".stl"))
        report[name] = {
            "watertight": bool(t.is_watertight),
            "volume_mm3": float(t.volume),
            "bounds_mm": t.extents.tolist(),
            "triangles": len(t.faces),
        }
    positions = [(8, 8, 0), (116, 8, 0), (8, 124, 0)]
    items = [(name, m, pos) for (name, m), pos in zip(parts.items(), positions)]
    for name, m, pos in items:
        b = mesh(m).bounds + pos
        assert np.all(b[0] >= 0) and np.all(b[1] < 256), (name, b)
    export_3mf(OUT / "mini-deck-a1-v1.3mf", items, "Mini Deck 55 degree case - fit prototype v1")
    export_3mf(
        OUT / "mini-deck-fit-check.3mf",
        [("Fit check", zero(fit), (15, 15, 0))],
        "Print first - PCB and port fit check",
    )
    export_3mf(
        OUT / "mini-deck-bezel-photo5.3mf",
        [("Alternate photo 5 bezel", zero(bezel(46, 53).rotate((180, 0, 0))), (15, 15, 0))],
        "Alternate LCD offset from photo 5",
    )
    # Collision check is exact CSG; shared boundaries have zero volume.
    report["assembly_overlap_mm3"] = {
        "body_bezel": (body ^ lid).volume(),
        "body_stand": (place(body) ^ stand).volume(),
    }
    # ^ is intersection in manifold3d.
    assert all(abs(v) < 0.01 for v in report["assembly_overlap_mm3"].values()), report[
        "assembly_overlap_mm3"
    ]
    (OUT / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    render()
    print(json.dumps(report, indent=2))


def render():
    from render_enclosure import render_views

    screen = place(box(49.8, 69.8, 0.3, (24.1, 17.6, 22.8)))
    render_views(
        [
            (mesh(place(body)), (64, 72, 85)),
            (mesh(place(lid)), (85, 96, 112)),
            (mesh(stand), (45, 52, 65)),
            (mesh(screen), (30, 187, 165)),
        ],
        OUT / "four-views-v1.png",
    )


if __name__ == "__main__":
    main()
