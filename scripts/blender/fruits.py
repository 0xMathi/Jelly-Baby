# Builds the six collectible fruits and exports one GLB each.
# Run: /Applications/Blender.app/Contents/MacOS/Blender -b -P scripts/blender/fruits.py -- <out_dir> [preview.png]
# Models are unit-sized (largest dimension = 2), Y-up after export, origin at the bottom centre.
# Material names (skin/seed/leaf/stem) are re-dressed with physical parameters in src/graphics/fruits.ts.
import bpy, bmesh, math, random, sys
from mathutils import Vector, Matrix, noise

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if not args:
    raise SystemExit('usage: blender -b -P fruits.py -- <out_dir> [preview.png]')
OUT = args[0]
PREVIEW = args[1] if len(args) > 1 else None

bpy.ops.wm.read_factory_settings(use_empty=True)
random.seed(7)

def material(name, color, rough=0.4, tinted=True):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = rough
    if not tinted:
        return m
    # Show vertex colour in the preview render; glTF exports COLOR_0 regardless.
    attr = m.node_tree.nodes.new('ShaderNodeVertexColor')
    attr.layer_name = 'Col'
    mix = m.node_tree.nodes.new('ShaderNodeMixRGB')
    mix.blend_type = 'MULTIPLY'; mix.inputs['Fac'].default_value = 1
    mix.inputs['Color1'].default_value = (1, 1, 1, 1)
    m.node_tree.links.new(attr.outputs['Color'], mix.inputs['Color1'])
    mix.inputs['Color2'].default_value = (*color, 1)
    m.node_tree.links.new(mix.outputs['Color'], bsdf.inputs['Base Color'])
    return m

def sphere_object(name, mat, shape, colour, u=128, v=96):
    """UV sphere whose vertices are moved by shape(direction)->position and tinted by colour(direction, position)."""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=1)
    for vert in bm.verts:
        d = vert.co.normalized()
        vert.co = shape(d)
    layer = bm.loops.layers.color.new('Col')
    for face in bm.faces:
        face.smooth = True
        for loop in face.loops:
            c = colour(loop.vert.co.normalized(), loop.vert.co)
            loop[layer] = (*c, 1)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh); bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    return obj

def ellipsoid_object(name, mat, radii, subdiv=2):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1)
    for vert in bm.verts:
        vert.co = Vector((vert.co.x * radii[0], vert.co.y * radii[1], vert.co.z * radii[2]))
    for face in bm.faces:
        face.smooth = True
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh); bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    return obj

def place(obj, position, normal, spin=0.0):
    """Orient obj's +Z along normal at position."""
    rot = Vector((0, 0, 1)).rotation_difference(normal.normalized()).to_matrix().to_4x4()
    obj.matrix_world = Matrix.Translation(position) @ rot @ Matrix.Rotation(spin, 4, 'Z')

def stem(mat, top, direction, length=0.28, radius=0.045, bend=0.25):
    curve = bpy.data.curves.new('stem', 'CURVE'); curve.dimensions = '3D'
    curve.bevel_depth = radius; curve.bevel_resolution = 4; curve.use_fill_caps = True
    spline = curve.splines.new('BEZIER'); spline.bezier_points.add(1)
    a, b = spline.bezier_points
    side = direction.orthogonal().normalized()
    end = top + direction * length + side * bend * length
    a.co = top - direction * 0.05; b.co = end
    for p in (a, b):
        p.handle_left_type = p.handle_right_type = 'AUTO'
    b.radius = 0.7
    obj = bpy.data.objects.new('stem', curve)
    obj.data.materials.append(mat)
    bpy.context.collection.objects.link(obj)
    return obj

def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.convert(target='MESH')
    # Parts without tint get white so COLOR_0 never darkens their material.
    for o in objs:
        if 'Col' not in o.data.color_attributes:
            attr = o.data.color_attributes.new('Col', 'BYTE_COLOR', 'CORNER')
            for item in attr.data:
                item.color = (1, 1, 1, 1)
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    return obj

def finish(obj, tilt):
    """Lay the fruit down, normalise to largest dimension 2, put origin at bottom centre."""
    obj.matrix_world = tilt @ obj.matrix_world
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    pts = [v.co for v in obj.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    s = 2 / max(hi - lo)
    centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for v in obj.data.vertices:
        v.co = (v.co - centre) * s
    obj.data.update()
    return obj

def fib_points(n):
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - 2 * (i + .5) / n
        r = math.sqrt(1 - y * y)
        yield Vector((math.cos(golden * i) * r, math.sin(golden * i) * r, y))

def lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

# ---------------------------------------------------------------- materials
leaf = material('leaf', (0.09, 0.32, 0.04), 0.5)
stem_mat = material('stem', (0.16, 0.20, 0.05), 0.6)
seed = material('seed', (0.80, 0.55, 0.12), 0.35)

def strawberry():
    skin = material('skin', (1, 1, 1), 0.3)
    seeds = list(fib_points(110))
    seeds = [s for s in seeds if s.z < 0.72]
    def width(z):  # z: +1 shoulder (calyx) .. -1 tip
        t = (z + 1) / 2
        return 0.30 + 0.78 * t ** 0.55 - 0.12 * t ** 6
    def shape(d):
        p = Vector((d.x * width(d.z), d.y * width(d.z), d.z * 1.08))
        if d.z > 0.8:
            p.z -= (d.z - 0.8) * 0.9  # shallow dish where the calyx sits
        for s in seeds:
            k = (d - s).length
            if k < .09:
                p -= d * 0.035 * (1 - k / .09) ** 2
        return p
    def colour(d, p):
        t = max(0, (d.z - 0.45) / 0.45)
        base = lerp((0.50, 0.005, 0.015), (0.85, 0.40, 0.25), t ** 1.8)
        n = noise.noise(d * 3.0) * 0.08
        return tuple(max(0, c + n) for c in base)
    body = sphere_object('strawberry', skin, shape, colour)
    parts = [body]
    for s in seeds:
        w = width(s.z)
        pos = Vector((s.x * w, s.y * w, s.z * 1.08)) - s * 0.02
        o = ellipsoid_object('seed', seed, (0.019, 0.014, 0.032), 1)
        place(o, pos, Vector((s.x, s.y, s.z * 0.6)), random.random() * 3)
        parts.append(o)
    top = Vector((0, 0, 1.08 - 0.18))
    for i in range(7):
        a = i / 7 * math.tau + random.uniform(-.15, .15)
        o = ellipsoid_object('leaf', leaf, (0.36, 0.11, 0.025), 3)
        # Leaves lie back over the shoulders, tip drooping.
        for v in o.data.vertices:
            x = v.co.x + 0.36
            v.co.z -= 0.35 * (x / 0.72) ** 2
            v.co.x = x
        o.matrix_world = Matrix.Translation(top) @ Matrix.Rotation(a, 4, 'Z') @ Matrix.Rotation(-0.25, 4, 'Y')
        parts.append(o)
    parts.append(stem(stem_mat, top, Vector((0.1, 0, 1)), 0.34, 0.05))
    obj = join(parts, 'strawberry')
    # Lie on its side with the tip slightly down.
    return finish(obj, Matrix.Rotation(math.radians(-78), 4, 'Y'))

def berry(name, base_colour, dark_colour, elong, rough=0.45):
    skin = material('skin', (1, 1, 1), rough)
    def shape(d):
        p = Vector((d.x, d.y, d.z * elong))
        p += d * noise.noise(d * 2.2) * 0.015
        if d.z > 0.9:
            p.z -= (d.z - 0.9) * 0.5
        return p
    def colour(d, p):
        t = (noise.noise(d * 2.5) + 1) / 2
        c = lerp(dark_colour, base_colour, t * 0.6 + 0.2 + 0.2 * max(0, -d.z))
        return c
    body = sphere_object(name, skin, shape, colour, 96, 72)
    tip = Vector((0, 0, elong - 0.05))
    obj = join([body, stem(stem_mat, tip, Vector((0.2, 0, 1)), 0.22, 0.05, 0.4)], name)
    return finish(obj, Matrix.Rotation(math.radians(-70), 4, 'Y'))

def blueberry():
    skin = material('skin', (1, 1, 1), 0.6)
    def shape(d):
        p = Vector((d.x, d.y, d.z * 0.82))
        theta = math.acos(max(-1, min(1, d.z)))
        phi = math.atan2(d.y, d.x)
        if theta < 0.42:
            crown = math.exp(-((theta - 0.27) / 0.07) ** 2) * (0.07 + 0.05 * max(0, math.cos(5 * phi)))
            p += d * crown
            p -= d * 0.18 * max(0, 1 - theta / 0.22) ** 2
        return p
    def colour(d, p):
        theta = math.acos(max(-1, min(1, d.z)))
        n = (noise.noise(d * 3) + 1) / 2
        c = lerp((0.05, 0.08, 0.30), (0.30, 0.38, 0.62), n * 0.7)
        if theta < 0.34:
            c = lerp(c, (0.10, 0.07, 0.16), 0.7)
        return c
    obj = sphere_object('blueberry', skin, shape, colour)
    return finish(obj, Matrix.Rotation(math.radians(-35), 4, 'Y'))

def kumquat():
    skin = material('skin', (1, 1, 1), 0.28)
    def shape(d):
        p = Vector((d.x, d.y, d.z * 1.28))
        pores = noise.noise(d * 46) * 0.004 + noise.noise(d * 7) * 0.004
        return p + d * pores
    def colour(d, p):
        n = (noise.noise(d * 4) + 1) / 2
        c = lerp((1.0, 0.42, 0.0), (1.0, 0.60, 0.02), n * 0.6)
        if d.z > 0.85:
            c = lerp(c, (0.45, 0.45, 0.05), (d.z - 0.85) / 0.15 * 0.6)
        return c
    body = sphere_object('kumquat', skin, shape, colour, 160, 120)
    button = ellipsoid_object('stem', stem_mat, (0.11, 0.11, 0.05), 2)
    button.location = (0, 0, 1.27)
    obj = join([body, button, stem(stem_mat, Vector((0, 0, 1.3)), Vector((0.15, 0, 1)), 0.14, 0.03)], 'kumquat')
    return finish(obj, Matrix.Rotation(math.radians(-82), 4, 'Y'))

def mirabelle():
    skin = material('skin', (1, 1, 1), 0.42)
    def shape(d):
        p = Vector((d.x, d.y, d.z * 0.96))
        phi = math.atan2(d.y, d.x)
        groove = math.exp(-(phi / 0.12) ** 2) * 0.035 * math.sqrt(max(0, 1 - d.z * d.z))
        p -= d * groove
        if d.z > 0.9:
            p.z -= (d.z - 0.9) * 0.6
        return p
    def colour(d, p):
        n = (noise.noise(d * 3) + 1) / 2
        c = lerp((0.92, 0.70, 0.02), (1.0, 0.86, 0.10), n)
        blush = max(0, noise.noise(d * 1.6 + Vector((3, 1, 2)))) * 1.4
        freckle = max(0, noise.noise(d * 30) - 0.55) * 3
        return lerp(c, (0.85, 0.30, 0.03), min(0.55, blush * 0.3 + freckle * 0.5))
    body = sphere_object('mirabelle', skin, shape, colour)
    obj = join([body, stem(stem_mat, Vector((0, 0, 0.9)), Vector((0.1, 0, 1)), 0.4, 0.035, 0.5)], 'mirabelle')
    return finish(obj, Matrix.Rotation(math.radians(-30), 4, 'X'))

builders = {
    'strawberry': strawberry,
    'grape': lambda: berry('grape', (0.30, 0.05, 0.38), (0.08, 0.0, 0.12), 1.14),
    'blueberry': blueberry,
    'kumquat': kumquat,
    'mirabelle': mirabelle,
    'greenGrape': lambda: berry('greenGrape', (0.62, 0.78, 0.22), (0.34, 0.50, 0.06), 1.14, 0.35),
}

import os
os.makedirs(OUT, exist_ok=True)
built = []
for name, build in builders.items():
    obj = build()
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name + '.glb'), use_selection=True,
                              export_format='GLB', export_yup=True, export_apply=True,
                              export_colors=True, export_normals=True, export_texcoords=False)
    built.append(obj)
    print('exported', name, len(obj.data.polygons), 'faces')

if PREVIEW:
    for i, obj in enumerate(built):
        obj.location.x = (i - 2.5) * 2.4
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'; scene.cycles.samples = 48; scene.cycles.device = 'CPU'
    scene.render.resolution_x, scene.render.resolution_y = 1800, 500
    world = bpy.data.worlds.new('w'); world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.9, 0.85, 0.78, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.7
    scene.world = world
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 3.5; sun.rotation_euler = (math.radians(40), math.radians(20), math.radians(30))
    bpy.context.collection.objects.link(sun)
    floor = bpy.data.meshes.new('floor'); bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=40); bm.to_mesh(floor)
    f = bpy.data.objects.new('floor', floor); bpy.context.collection.objects.link(f)
    f.data.materials.append(material('floor', (0.75, 0.6, 0.45), 0.6, False))
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); cam.data.lens = 42
    bpy.context.collection.objects.link(cam); scene.camera = cam
    cam.location = (0, -19, 6.5); cam.rotation_euler = (math.radians(75), 0, 0)
    scene.render.filepath = PREVIEW
    bpy.ops.render.render(write_still=True)
