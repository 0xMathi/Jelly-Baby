# Builds the six collectible fruits and exports one GLB each.
# Run: /Applications/Blender.app/Contents/MacOS/Blender -b -P scripts/blender/fruits.py -- <out_dir> [preview.png]
# Then compress the geometry (the game loads them with the meshopt decoder):
#   for f in <out_dir>/*.glb; do npx -y gltfpack -i $f -o $f -cc -km -kn; done
#
# Each fruit skin gets a procedural Cycles material (pores, bloom, freckles, seed pits ...) that is
# baked to base colour, roughness and tangent-space normal textures on the sphere's UVs, so the
# detail survives the trip to glTF/Three.js. Seeds, leaves and stems stay small flat-colour parts.
# Models are unit-sized (largest dimension = 2), Y-up after export, origin at the bottom centre.
# Material names (skin/seed/leaf/stem) are re-dressed with physical parameters in src/graphics/fruits.ts.
import bpy, bmesh, math, os, random, sys, tempfile
from mathutils import Vector, Matrix, noise

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if not args:
    raise SystemExit('usage: blender -b -P fruits.py -- <out_dir> [preview.png]')
OUT = args[0]
PREVIEW = args[1] if len(args) > 1 else None
TEXTURE_SIZE = 1024
BAKE_DIR = tempfile.mkdtemp(prefix='fruit-bake-')

bpy.ops.wm.read_factory_settings(use_empty=True)
random.seed(7)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 16

# ---------------------------------------------------------------- node helpers

class Graph:
    """Tiny wrapper to wire shader nodes without a page of boilerplate per fruit."""
    def __init__(self, material):
        self.nodes = material.node_tree.nodes
        self.links = material.node_tree.links
        self.bsdf = self.nodes['Principled BSDF']
        coords = self.nodes.new('ShaderNodeTexCoord')
        self.obj = coords.outputs['Object']

    def node(self, kind, **inputs):
        n = self.nodes.new(kind)
        for key, value in inputs.items():
            self.set(n.inputs[key], value)
        return n

    def set(self, socket, value):
        if hasattr(value, 'is_output'):
            self.links.new(value, socket)
        elif isinstance(value, tuple) and len(value) == 3 and socket.type == 'RGBA':
            socket.default_value = (*value, 1)
        else:
            socket.default_value = value

    def noise(self, scale, detail=4.0, roughness=0.5, distortion=0.0, vector=None):
        n = self.node('ShaderNodeTexNoise', Scale=scale, Detail=detail, Roughness=roughness, Distortion=distortion)
        self.links.new(vector or self.obj, n.inputs['Vector'])
        return n.outputs['Fac']

    def voronoi(self, scale, randomness=1.0, feature='F1', vector=None):
        n = self.node('ShaderNodeTexVoronoi', Scale=scale, Randomness=randomness)
        n.feature = feature
        self.links.new(vector or self.obj, n.inputs['Vector'])
        return n.outputs['Distance']

    def ramp(self, fac, stops):
        """stops: [(position, (r,g,b)) ...] -> colour; with float stops -> greyscale value."""
        n = self.nodes.new('ShaderNodeValToRGB')
        elements = n.color_ramp.elements
        while len(elements) < len(stops):
            elements.new(0.5)
        for element, (pos, colour) in zip(elements, stops):
            element.position = pos
            element.color = (*colour, 1) if isinstance(colour, tuple) else (colour, colour, colour, 1)
        self.links.new(fac, n.inputs['Fac'])
        return n.outputs['Color']

    def mix(self, fac, a, b, blend='MIX'):
        n = self.node('ShaderNodeMixRGB', Fac=fac, Color1=a, Color2=b)
        n.blend_type = blend
        return n.outputs['Color']

    def axis(self, name):
        sep = self.node('ShaderNodeSeparateXYZ')
        self.links.new(self.obj, sep.inputs['Vector'])
        return sep.outputs[name]

    def maprange(self, value, lo, hi):
        n = self.node('ShaderNodeMapRange', Value=value)
        n.inputs['From Min'].default_value = lo
        n.inputs['From Max'].default_value = hi
        return n.outputs['Result']

    def math(self, op, a, b):
        n = self.node('ShaderNodeMath')
        n.operation = op
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        return n.outputs['Value']

    def bloom(self, amount):
        """Fine, even powdery dust (grape/plum bloom): speckles at texture scale, gently varying cover."""
        dust = self.ramp(self.noise(16, 3, 0.5), [(0.3, 0.2), (0.75, 1.0)])
        cover = self.ramp(self.noise(1.8, 2), [(0.2, 0.4), (0.8, 1.0)])
        return self.math('MULTIPLY', self.math('MULTIPLY', dust, cover), amount)

    def finish(self, colour, roughness, height, bump_strength=0.4, bump_distance=0.02):
        self.set(self.bsdf.inputs['Base Color'], colour)
        self.set(self.bsdf.inputs['Roughness'], roughness)
        bump = self.node('ShaderNodeBump', Strength=bump_strength, Distance=bump_distance, Height=height)
        self.links.new(bump.outputs['Normal'], self.bsdf.inputs['Normal'])


def plain(name, colour, rough=0.4):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes['Principled BSDF']
    bsdf.inputs['Base Color'].default_value = (*colour, 1)
    bsdf.inputs['Roughness'].default_value = rough
    return m

def procedural(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m, Graph(m)

# ---------------------------------------------------------------- geometry helpers

def sphere_object(name, material, shape, u=160, v=120):
    """UV sphere (with UVs) whose vertices are moved by shape(direction) -> position."""
    bm = bmesh.new()
    bm.loops.layers.uv.new('UVMap')
    bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=1, calc_uvs=True)
    for vert in bm.verts:
        vert.co = shape(vert.co.normalized())
    for face in bm.faces:
        face.smooth = True
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh); bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(material)
    bpy.context.collection.objects.link(obj)
    return obj

def ellipsoid_object(name, material, radii, subdiv=2):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=1)
    for vert in bm.verts:
        vert.co = Vector((vert.co.x * radii[0], vert.co.y * radii[1], vert.co.z * radii[2]))
    for face in bm.faces:
        face.smooth = True
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh); bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(material)
    bpy.context.collection.objects.link(obj)
    return obj

def place(obj, position, normal, spin=0.0):
    """Orient obj's +Z along normal at position."""
    rot = Vector((0, 0, 1)).rotation_difference(normal.normalized()).to_matrix().to_4x4()
    obj.matrix_world = Matrix.Translation(position) @ rot @ Matrix.Rotation(spin, 4, 'Z')

def stem(material, top, direction, length=0.28, radius=0.045, bend=0.25):
    curve = bpy.data.curves.new('stem', 'CURVE'); curve.dimensions = '3D'
    curve.bevel_depth = radius; curve.bevel_resolution = 4; curve.use_fill_caps = True
    spline = curve.splines.new('BEZIER'); spline.bezier_points.add(1)
    a, b = spline.bezier_points
    side = direction.orthogonal().normalized()
    a.co = top - direction * 0.05
    b.co = top + direction * length + side * bend * length
    for p in (a, b):
        p.handle_left_type = p.handle_right_type = 'AUTO'
    b.radius = 0.7
    obj = bpy.data.objects.new('stem', curve)
    obj.data.materials.append(material)
    bpy.context.collection.objects.link(obj)
    return obj

def leaf(material, length, width):
    """A pointed, slightly cupped leaf lying along +X with a raised midrib."""
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=16, y_segments=6, size=1)
    for vert in bm.verts:
        t = (vert.co.x + 1) / 2                       # 0 at base .. 1 at tip
        profile = math.sin(math.pi * min(1, t * 1.05)) ** 0.8 * (1 - t * 0.25)
        vert.co.y *= width * profile
        vert.co.x = t * length
        vert.co.z = 0.35 * abs(vert.co.y) / max(width, 1e-6) * width - 0.28 * t * t * length
    bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=0.012)
    for face in bm.faces:
        face.smooth = True
    mesh = bpy.data.meshes.new('leaf')
    bm.to_mesh(mesh); bm.free()
    obj = bpy.data.objects.new('leaf', mesh)
    obj.data.materials.append(material)
    bpy.context.collection.objects.link(obj)
    return obj

def bake(obj, material, graph):
    """Bake the procedural skin to textures and swap in an export-friendly material."""
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    images = {}
    for kind, colourspace in (('DIFFUSE', 'sRGB'), ('ROUGHNESS', 'Non-Color'), ('NORMAL', 'Non-Color')):
        image = bpy.data.images.new(f'{obj.name}-{kind.lower()}', TEXTURE_SIZE, TEXTURE_SIZE, alpha=False)
        image.colorspace_settings.name = colourspace
        node = graph.nodes.new('ShaderNodeTexImage')
        node.image = image
        graph.nodes.active = node
        if kind == 'DIFFUSE':
            bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, margin=16, use_clear=True)
        else:
            bpy.ops.object.bake(type=kind, margin=16, use_clear=True)
        path = os.path.join(BAKE_DIR, image.name + '.png')
        image.filepath_raw = path
        image.file_format = 'PNG'
        image.save()
        graph.nodes.remove(node)
        images[kind] = image
    # Export material: textures only, which glTF understands.
    skin = bpy.data.materials.new('skin')
    skin.use_nodes = True
    nodes, links = skin.node_tree.nodes, skin.node_tree.links
    bsdf = nodes['Principled BSDF']
    def tex(image):
        n = nodes.new('ShaderNodeTexImage'); n.image = image
        return n
    links.new(tex(images['DIFFUSE']).outputs['Color'], bsdf.inputs['Base Color'])
    rough = nodes.new('ShaderNodeSeparateRGB')
    links.new(tex(images['ROUGHNESS']).outputs['Color'], rough.inputs['Image'])
    links.new(rough.outputs['G'], bsdf.inputs['Roughness'])
    normal_map = nodes.new('ShaderNodeNormalMap')
    links.new(tex(images['NORMAL']).outputs['Color'], normal_map.inputs['Color'])
    links.new(normal_map.outputs['Normal'], bsdf.inputs['Normal'])
    obj.data.materials[0] = skin

def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.convert(target='MESH')
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

leaf_mat = plain('leaf', (0.08, 0.30, 0.035), 0.45)
stem_mat = plain('stem', (0.14, 0.19, 0.05), 0.6)
seed_mat = plain('seed', (0.85, 0.62, 0.16), 0.3)

# ---------------------------------------------------------------- fruit

def strawberry():
    m, g = procedural('strawberry-skin')
    height = g.axis('Z')
    shoulder = g.maprange(height, 0.6, 1.0)                      # 0 in the body, 1 at the calyx
    mottle = g.noise(4.5, 6, 0.55)
    base = g.ramp(mottle, [(0.3, (0.42, 0.004, 0.012)), (0.7, (0.66, 0.02, 0.03))])
    colour = g.mix(g.ramp(shoulder, [(0.0, 0.0), (1.0, 1.0)]), base, (0.95, 0.52, 0.34))
    gloss = g.ramp(g.noise(9, 3), [(0.3, 0.16), (0.8, 0.32)])
    fine = g.noise(70, 2)
    g.finish(colour, gloss, fine, bump_strength=0.15)

    seeds = [s for s in fib_points(170) if s.z < 0.7]
    def width(z):  # z: +1 shoulder (calyx) .. -1 tip
        t = (z + 1) / 2
        return 0.30 + 0.80 * t ** 0.55 - 0.13 * t ** 6
    def shape(d):
        p = Vector((d.x * width(d.z), d.y * width(d.z), d.z * 1.08))
        if d.z > 0.8:
            p.z -= (d.z - 0.8) * 0.9          # shallow dish where the calyx sits
        for s in seeds:
            k = (d - s).length
            if k < .085:
                p -= d * 0.045 * (1 - k / .085) ** 2   # a pit for each seed
        return p
    body = sphere_object('strawberry', m, shape, 192, 144)
    bake(body, m, g)
    parts = [body]
    for s in seeds:
        w = width(s.z)
        pos = Vector((s.x * w, s.y * w, s.z * 1.08)) - s * 0.03
        o = ellipsoid_object('seed', seed_mat, (0.016, 0.012, 0.028), 1)
        place(o, pos, Vector((s.x, s.y, s.z * 0.6)), random.random() * 3)
        parts.append(o)
    top = Vector((0, 0, 1.08 - 0.18))
    for i in range(8):
        a = i / 8 * math.tau + random.uniform(-.12, .12)
        o = leaf(leaf_mat, random.uniform(0.62, 0.78), 0.16)
        o.matrix_world = Matrix.Translation(top) @ Matrix.Rotation(a, 4, 'Z') @ Matrix.Rotation(-0.2, 4, 'Y')
        parts.append(o)
    parts.append(stem(stem_mat, top, Vector((0.1, 0, 1)), 0.34, 0.05))
    obj = join(parts, 'strawberry')
    return finish(obj, Matrix.Rotation(math.radians(-78), 4, 'Y'))

def berry(name, skin_colours, bloom_colour, bloom_amount, elong, stripes=False):
    m, g = procedural(name + '-skin')
    deep, bright = skin_colours
    base = g.ramp(g.noise(2.5, 3), [(0.2, deep), (0.9, bright)])
    if stripes:
        # Faint longitudinal veins, typical for pale grapes.
        wave = g.node('ShaderNodeTexWave', Scale=5.5, Distortion=1.5, Detail=2)
        wave.bands_direction = 'Z'
        g.links.new(g.obj, wave.inputs['Vector'])
        veins = g.ramp(wave.outputs['Fac'], [(0.45, 0.0), (0.6, 0.25)])
        base = g.mix(veins, base, deep, 'MIX')
    bloom = g.bloom(bloom_amount)
    colour = g.mix(bloom, base, bloom_colour)
    rough = g.ramp(bloom, [(0.0, 0.24), (0.6, 0.6)])
    g.finish(colour, rough, g.noise(45, 2), bump_strength=0.08)
    def shape(d):
        p = Vector((d.x, d.y, d.z * elong))
        p += d * noise.noise(d * 1.4) * 0.035
        if d.z > 0.9:
            p.z -= (d.z - 0.9) * 0.5
        return p
    body = sphere_object(name, m, shape, 128, 96)
    bake(body, m, g)
    tip = Vector((0, 0, elong - 0.05))
    scar = ellipsoid_object('stem', stem_mat, (0.07, 0.07, 0.03), 2)
    scar.location = tip + Vector((0, 0, 0.02))
    obj = join([body, scar, stem(stem_mat, tip, Vector((0.2, 0, 1)), 0.22, 0.045, 0.4)], name)
    return finish(obj, Matrix.Rotation(math.radians(-70), 4, 'Y'))

def blueberry():
    m, g = procedural('blueberry-skin')
    top = g.maprange(g.axis('Z'), 0.55, 0.8)                    # crown region
    base = g.ramp(g.noise(2.5, 3), [(0.2, (0.03, 0.045, 0.15)), (0.9, (0.07, 0.1, 0.27))])
    bloom = g.bloom(0.45)
    colour = g.mix(bloom, base, (0.3, 0.37, 0.56))
    colour = g.mix(top, colour, (0.05, 0.04, 0.09))
    rough = g.ramp(bloom, [(0.0, 0.4), (0.6, 0.75)])
    g.finish(colour, rough, g.noise(40, 2), bump_strength=0.06)
    def shape(d):
        p = Vector((d.x, d.y, d.z * 0.82))
        theta = math.acos(max(-1, min(1, d.z)))
        phi = math.atan2(d.y, d.x)
        if theta < 0.42:
            crown = math.exp(-((theta - 0.27) / 0.07) ** 2) * (0.07 + 0.06 * max(0, math.cos(5 * phi)))
            p += d * crown
            p -= d * 0.18 * max(0, 1 - theta / 0.22) ** 2
        return p
    obj = sphere_object('blueberry', m, shape)
    bake(obj, m, g)
    return finish(obj, Matrix.Rotation(math.radians(-35), 4, 'Y'))

def citrus_peel(g, colours, pit_colour, scale, tip_colour=None, tip_axis=None):
    """Pitted, glossy citrus peel: oil-gland pits as bump, slightly darker and rougher in the pits."""
    pits = g.ramp(g.voronoi(scale, 1.0), [(0.0, 0.0), (0.5, 1.0)])      # 0 in a pit, 1 on the peel
    micro = g.noise(scale * 4, 2)
    height = g.math('ADD', pits, g.math('MULTIPLY', micro, 0.15))
    base = g.ramp(g.noise(2.5, 3), [(0.2, colours[0]), (0.9, colours[1])])
    colour = g.mix(g.math('MULTIPLY', g.math('SUBTRACT', 1.0, pits), 0.45), base, pit_colour)
    if tip_colour:
        tips = g.maprange(g.math('ABSOLUTE', tip_axis, 0), 1.15, 1.55)
        colour = g.mix(g.math('MULTIPLY', tips, 0.6), colour, tip_colour)
    rough = g.ramp(pits, [(0.0, 0.5), (1.0, 0.24)])
    g.finish(colour, rough, height, bump_strength=0.9, bump_distance=0.025)

def mandarin():
    m, g = procedural('mandarin-skin')
    citrus_peel(g, ((1.0, 0.24, 0.0), (1.0, 0.36, 0.0)), (0.8, 0.13, 0.0), 26)
    def shape(d):
        theta = math.acos(max(-1, min(1, d.z)))
        phi = math.atan2(d.y, d.x)
        lobes = 1 + 0.02 * math.cos(10 * phi) * math.sin(theta) ** 2     # faint segment bulges
        p = Vector((d.x * lobes, d.y * lobes, d.z * 0.78))
        p += d * noise.noise(d * 1.6) * 0.025
        if d.z > 0.9:
            p.z -= (d.z - 0.9) * 0.9                                      # stem dimple
        if d.z < -0.93:
            p.z += (-0.93 - d.z) * 0.8                                    # navel
        return p
    body = sphere_object('mandarin', m, shape, 192, 144)
    bake(body, m, g)
    button = ellipsoid_object('stem', stem_mat, (0.1, 0.1, 0.05), 2)
    button.location = (0, 0, 0.7)
    small_leaf = leaf(leaf_mat, 0.55, 0.2)
    small_leaf.matrix_world = Matrix.Translation((0, 0, 0.73)) @ Matrix.Rotation(0.6, 4, 'Z') @ Matrix.Rotation(0.35, 4, 'Y')
    obj = join([body, button, small_leaf, stem(stem_mat, Vector((0, 0, 0.72)), Vector((0.1, 0, 1)), 0.1, 0.03)], 'mandarin')
    return finish(obj, Matrix.Rotation(math.radians(-12), 4, 'Y'))

def lemon():
    m, g = procedural('lemon-skin')
    citrus_peel(g, ((1.0, 0.62, 0.0), (1.0, 0.74, 0.0)), (0.9, 0.5, 0.0), 24,
                tip_colour=(0.55, 0.62, 0.04), tip_axis=g.axis('Z'))
    def shape(d):
        p = Vector((d.x, d.y, d.z * 1.3))
        p += d * noise.noise(d * 1.5) * 0.03
        # The two lemon tips: a proud nipple on top, a smaller one below.
        if d.z > 0.88:
            p.z += 0.34 * ((d.z - 0.88) / 0.12) ** 2
        if d.z < -0.9:
            p.z -= 0.2 * ((-d.z - 0.9) / 0.1) ** 2
        return p
    body = sphere_object('lemon', m, shape, 192, 144)
    bake(body, m, g)
    button = ellipsoid_object('stem', stem_mat, (0.06, 0.06, 0.04), 2)
    button.location = (0, 0, 1.64)
    obj = join([body, button], 'lemon')
    return finish(obj, Matrix.Rotation(math.radians(-84), 4, 'Y'))

builders = {
    'strawberry': strawberry,
    'grape': lambda: berry('grape', ((0.05, 0.0, 0.08), (0.17, 0.02, 0.22)), (0.3, 0.26, 0.42), 0.3, 1.14),
    'blueberry': blueberry,
    'mandarin': mandarin,
    'lemon': lemon,
    'greenGrape': lambda: berry('greenGrape', ((0.32, 0.48, 0.06), (0.55, 0.72, 0.16)), (0.75, 0.82, 0.6), 0.14, 1.14, stripes=True),
}

os.makedirs(OUT, exist_ok=True)
built = []
for name, build in builders.items():
    obj = build()
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, name + '.glb'), use_selection=True,
                              export_format='GLB', export_yup=True, export_apply=True,
                              export_image_format='JPEG', export_colors=False,
                              export_normals=True, export_texcoords=True, export_tangents=False)
    built.append(obj)
    print('exported', name, len(obj.data.polygons), 'faces')

if PREVIEW:
    for i, obj in enumerate(built):
        obj.location.x = (i - 2.5) * 2.4
    scene.cycles.samples = 64
    scene.render.resolution_x, scene.render.resolution_y = 2400, 700
    world = bpy.data.worlds.new('w'); world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.9, 0.85, 0.78, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.7
    scene.world = world
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 3.5; sun.rotation_euler = (math.radians(40), math.radians(20), math.radians(30))
    bpy.context.collection.objects.link(sun)
    floor = bpy.data.meshes.new('floor'); bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=40); bm.to_mesh(floor)
    f = bpy.data.objects.new('floor', floor); bpy.context.collection.objects.link(f)
    f.data.materials.append(plain('floor', (0.75, 0.6, 0.45), 0.6))
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); cam.data.lens = 42
    bpy.context.collection.objects.link(cam); scene.camera = cam
    cam.location = (0, -17, 4.5); cam.rotation_euler = (math.radians(78), 0, 0)
    scene.render.filepath = PREVIEW
    bpy.ops.render.render(write_still=True)
