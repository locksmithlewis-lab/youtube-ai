"""Build one deterministic BLACKSTAR episode segment inside Blender.

The renderer is deliberately optimized for GitHub-hosted CPU runners: it renders a
720p/18fps source master that is normalized to 1080p/24fps during final assembly.
Approved Rolixa portrait crops are attached as face identity plates so the same
operator faces remain recognizable across the dashboard and animation.
"""
import bpy
import json
import math
import re
import sys
from pathlib import Path
from mathutils import Vector

args = sys.argv[sys.argv.index('--') + 1:]
manifest_path = Path(args[0])
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
out = args[1]
seg = manifest['segment']
bible = manifest['bible']
idx = int(seg['index'])
shots = list(seg.get('shots') or [])
root_dir = manifest_path.parent

scene = bpy.context.scene
for engine in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'CYCLES'):
    try:
        scene.render.engine = engine
        print(f'Using render engine: {engine}')
        break
    except (TypeError, ValueError):
        continue
else:
    raise RuntimeError('No supported Blender render engine found')

# GitHub CPU runners were spending too long on 1920x1080 x 1440 frames per worker.
# 720p/18fps preserves a cinematic source while cutting expensive frame work; the
# assembler later delivers the required 1920x1080/24fps master.
SOURCE_FPS = 18
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.render.fps = SOURCE_FPS
scene.frame_start = 1
scene.frame_end = max(2, int(float(seg['duration']) * SOURCE_FPS))
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
scene.render.filepath = out
scene.world.color = (0.004, 0.007, 0.015)

# Keep EEVEE cheap and deterministic when the installed Blender version exposes
# these controls. Avoid volumetrics, which were the largest unnecessary CPU cost.
if hasattr(scene, 'eevee'):
    for attr, value in [('taa_render_samples', 16), ('taa_samples', 16), ('use_gtao', True)]:
        if hasattr(scene.eevee, attr):
            setattr(scene.eevee, attr, value)


def look(obj, pt):
    obj.rotation_euler = (Vector(pt) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def mat(name, rgba, metallic=0.0, rough=.5, emission=None):
    m = bpy.data.materials.new(name)
    m.diffuse_color = rgba
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value = rgba
        bsdf.inputs['Metallic'].default_value = metallic
        bsdf.inputs['Roughness'].default_value = rough
        if emission:
            e = bsdf.inputs.get('Emission Color') or bsdf.inputs.get('Emission')
            if e:
                e.default_value = emission
            strength = bsdf.inputs.get('Emission Strength')
            if strength:
                strength.default_value = 2.5
    return m


def image_mat(name, image_path):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nodes = m.node_tree.nodes
    links = m.node_tree.links
    bsdf = nodes.get('Principled BSDF')
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = bpy.data.images.load(str(image_path), check_existing=True)
    links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    if 'Roughness' in bsdf.inputs:
        bsdf.inputs['Roughness'].default_value = .55
    return m


graphite = mat('GraphiteArmor', (0.045, .055, .07, 1), .65, .34)
steel = mat('IndustrialSteel', (.07, .09, .12, 1), .55, .42)
cyan = mat('CyanTech', (.02, .16, .20, 1), .2, .25, (.02, .65, 1.0, 1))
amber = mat('EmergencyAmber', (.15, .06, .01, 1), .1, .35, (1.0, .20, .02, 1))
enemy_mat = mat('VeyrCeramic', (.12, .13, .14, 1), .4, .3)
skin_mats = {
    'MARA_VOSS': mat('Skin_Voss', (.39,.22,.15,1), 0, .6),
    'JAX_MERCER': mat('Skin_Jax', (.20,.10,.07,1), 0, .65),
    'IMANI_VALE': mat('Skin_Vale', (.42,.24,.16,1), 0, .6),
    'ROOK': mat('Skin_Rook', (.50,.30,.20,1), 0, .6),
}
accent_mats = {
    'MARA_VOSS': cyan,
    'JAX_MERCER': amber,
    'IMANI_VALE': cyan,
    'ROOK': cyan,
}

# Environment geometry: enough depth for camera motion without the former volume cube.
bpy.ops.mesh.primitive_plane_add(size=70, location=(0, 5, 0))
ground = bpy.context.object
ground.name = 'BLACKSTAR_ENVIRONMENT_FLOOR'
ground.data.materials.append(steel)
for side in (-1, 1):
    bpy.ops.mesh.primitive_cube_add(location=(side * 8.5, 7, 3.5), scale=(.35, 16, 3.5))
    bpy.context.object.data.materials.append(steel)
for y in range(-6, 24, 6):
    bpy.ops.mesh.primitive_cube_add(location=(0, y, 6.8), scale=(8.5, .14, .14))
    bpy.context.object.data.materials.append(steel)

characters = {}
for i, ch in enumerate(bible.get('characters', [])):
    cid = ch['id']
    x = (i - 1.5) * 1.65
    y = -1.5 - i * .25
    root = bpy.data.objects.new(cid, None)
    bpy.context.collection.objects.link(root)
    root.location = (x, y, 0)

    # Human head/neck remains visible instead of the old opaque geometric helmet.
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=10, radius=.30, location=(x, y, 1.78))
    head = bpy.context.object
    head.name = cid + '_HEAD'
    head.scale = (.88, .78, 1.08)
    head.data.materials.append(skin_mats.get(cid, graphite))
    head.parent = root

    # A small portrait plane over the facial region carries the exact approved face.
    portrait = root_dir / 'portraits' / f'{cid}.jpg'
    if portrait.exists():
        bpy.ops.mesh.primitive_plane_add(size=.56, location=(x, y-.245, 1.80), rotation=(math.pi/2, 0, 0))
        face = bpy.context.object
        face.name = cid + '_PORTRAIT_FACE'
        face.scale.x = .78
        face.scale.y = 1.0
        face.data.materials.append(image_mat('Portrait_'+cid, portrait))
        face.parent = root

    # Layered outfit: fabric core, armor shell, chest rig, role accent.
    bpy.ops.mesh.primitive_cube_add(location=(x, y, 1.05), scale=(.45, .28, .56))
    torso = bpy.context.object
    torso.name = cid + '_TORSO'
    torso.data.materials.append(graphite)
    torso.parent = root
    bpy.ops.mesh.primitive_cube_add(location=(x, y-.30, 1.10), scale=(.34, .06, .25))
    rig = bpy.context.object
    rig.name = cid + '_CHEST_RIG'
    rig.data.materials.append(accent_mats.get(cid, cyan))
    rig.parent = root
    for sx in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(location=(x + sx*.57, y, 1.08), scale=(.12, .12, .48))
        arm = bpy.context.object
        arm.name = f"{cid}_ARM_{'R' if sx>0 else 'L'}"
        arm.data.materials.append(graphite)
        arm.parent = root
        bpy.ops.mesh.primitive_cube_add(location=(x + sx*.22, y, .35), scale=(.14, .14, .52))
        leg = bpy.context.object
        leg.name = f"{cid}_LEG_{'R' if sx>0 else 'L'}"
        leg.data.materials.append(graphite)
        leg.parent = root
    characters[cid] = root

# Kestrel is a holographic support presence, not a physical squad body.
bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=10, radius=.34, location=(0,-.8,2.8))
kestrel = bpy.context.object
kestrel.name = 'KESTREL_HOLOGRAM'
kestrel.data.materials.append(cyan)
kestrel.hide_render = idx not in (1,2,12,18,20)

# Veyr use a distinct silhouette and luminous mask.
enemies = []
for i in range(6):
    x = -5 + i * 2.0
    y = 10 + i*.5
    root = bpy.data.objects.new(f'VEYR_UNIT_{i+1}', None)
    bpy.context.collection.objects.link(root)
    root.location=(x, y, 0)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=.38, location=(x,y,1.75))
    h=bpy.context.object; h.scale=(.8,.65,1.15); h.data.materials.append(enemy_mat); h.parent=root
    bpy.ops.mesh.primitive_cube_add(location=(x,y,1.0),scale=(.48,.30,.72))
    b=bpy.context.object; b.data.materials.append(enemy_mat); b.parent=root
    bpy.ops.mesh.primitive_cube_add(location=(x,y-.31,1.78),scale=(.23,.04,.10))
    f=bpy.context.object; f.data.materials.append(cyan); f.parent=root
    enemies.append(root)

shot_text = ' '.join(shots).lower()
if any(k in shot_text for k in ('gateway','portal')) or idx in range(14,19):
    for r in (2.3, 3.0):
        bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=.07, location=(0,13,3.4), rotation=(math.pi/2,0,0), major_segments=32, minor_segments=8)
        bpy.context.object.data.materials.append(cyan)
if any(k in shot_text for k in ('drone','signal')) or idx in (7,8,9):
    for n in range(3):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=.23, location=(-2+n*2.0,5+n*.5,2.1+n*.2))
        d=bpy.context.object; d.name=f'DRONE_{n+1}'; d.data.materials.append(enemy_mat)
if any(k in shot_text for k in ('dropship','landing','orbit','exterior','extraction')) or idx in (1,2,3,18,19,20):
    bpy.ops.mesh.primitive_cube_add(location=(0,17,6), scale=(2.3,4.6,.72))
    ship=bpy.context.object; ship.name='KESTREL_DROPSHIP'; ship.data.materials.append(graphite)
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=2.4, radius2=.2, depth=3.6, location=(0,13.0,6), rotation=(math.pi/2,0,0))
    bpy.context.object.data.materials.append(graphite)

action = idx in {8,10,11,12,13,16,17,18,19}
if action:
    for n in range(10):
        x = -6 + (n % 5) * 2.5
        y = 2 + (n // 5) * 5.0
        z = .3 + (n % 4) * .35
        bpy.ops.mesh.primitive_cube_add(location=(x,y,z), scale=(.10,.12,.08))
        piece=bpy.context.object; piece.data.materials.append(steel)
        piece.rotation_euler=(n*.31,n*.17,n*.23)
        piece.keyframe_insert('location',frame=1)
        piece.location.z += 1.2 + (n%4)*.25
        piece.location.x += math.sin(n)*.8
        piece.keyframe_insert('location',frame=scene.frame_end)

# Shared tactical movement contract.
for ci, root in enumerate(characters.values()):
    root.keyframe_insert('location', frame=1)
    if idx <= 6:
        root.location.y += 5.0 + ci*.25
    elif idx <= 13:
        root.location.y += 8.0
        root.location.x += (-1 if ci%2 else 1) * 1.0
    elif idx <= 18:
        root.location.y += 10.5
        root.location.x += (-1.8 + ci*1.2)
    else:
        root.location.y += 14.0
    root.keyframe_insert('location', frame=scene.frame_end)

for ei, root in enumerate(enemies):
    root.hide_render = idx < 9 or idx == 20
    if not root.hide_render:
        root.keyframe_insert('location', frame=1)
        root.location.y -= 3.5 + (ei % 3)
        root.location.x += math.sin(ei + idx) * 1.2
        root.keyframe_insert('location', frame=scene.frame_end)

bpy.ops.object.camera_add(location=(0,-10,3.8))
cam=bpy.context.object
cam.name='BLACKSTAR_CAMERA'
scene.camera=cam
cam.data.lens=42
shot_count=max(1,len(shots))
for s in range(shot_count):
    frame = 1 + int((scene.frame_end-1) * s / max(1, shot_count-1)) if shot_count > 1 else 1
    phase = idx * .61 + s * 1.27
    cam.location = (math.sin(phase)*3.5, -4.5 + s*(11.0/max(1,shot_count-1)), 2.4 + .9*math.cos(phase*.7))
    look(cam,(0, 4.0 + s*(6.5/max(1,shot_count-1)), 1.35))
    cam.data.lens = 36 + (s % 3) * 7
    cam.keyframe_insert('location',frame=frame)
    cam.keyframe_insert('rotation_euler',frame=frame)
    cam.data.keyframe_insert('lens',frame=frame)
    marker = re.sub('[^A-Za-z0-9]+','_',shots[s])[:32] if shots else 'BEAT'
    scene.timeline_markers.new(f'SHOT_{s+1}_{marker}',frame=frame)

for name,loc,energy,size,color in [
    ('KEY',(-4,-4,7),1150,5,(.65,.80,1.0)),
    ('RIM',(5,4,5),900,4,(.1,.65,1.0)),
    ('FILL',(0,-1,4),350,6,(1.0,.42,.16)),
]:
    bpy.ops.object.light_add(type='AREA',location=loc)
    l=bpy.context.object
    l.name=name
    l.data.energy=energy
    l.data.shape='DISK'
    l.data.size=size
    l.data.color=color
    look(l,(0,4,1))

scene['episode_segment_index']=idx
scene['continuity_in']=str(seg.get('continuity_in',''))
scene['continuity_out']=str(seg.get('continuity_out',''))
scene['shot_plan']=json.dumps(shots)
scene['source_render_fps']=SOURCE_FPS
scene['portrait_identity_enabled']=True
scene.render.filepath=out
bpy.ops.wm.save_as_mainfile(filepath=str(Path(out).with_suffix('.blend')))
bpy.ops.render.render(animation=True)
