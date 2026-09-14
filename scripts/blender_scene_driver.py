"""Executed inside Blender to build one deterministic cinematic episode segment.

The scene is fully original and procedural. It uses stable character IDs and
segment-specific shot descriptors so every worker renders the same cast/style but
different story action. Production-grade external assets can later replace these
stable-ID objects without changing the orchestration contract.
"""
import bpy
import json
import math
import re
import sys
from pathlib import Path
from mathutils import Vector

args = sys.argv[sys.argv.index('--') + 1:]
manifest = json.loads(Path(args[0]).read_text(encoding='utf-8'))
out = args[1]
seg = manifest['segment']
bible = manifest['bible']
idx = int(seg['index'])
shots = list(seg.get('shots') or [])

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE_NEXT'
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.resolution_percentage = 100
scene.render.fps = 24
scene.frame_start = 1
scene.frame_end = max(2, int(float(seg['duration']) * 24))
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format = 'MPEG4'
scene.render.ffmpeg.codec = 'H264'
scene.render.ffmpeg.constant_rate_factor = 'MEDIUM'
scene.render.filepath = out
scene.world.color = (0.004, 0.007, 0.015)


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
            bsdf.inputs['Emission Color'].default_value = emission
            bsdf.inputs['Emission Strength'].default_value = 4.0
    return m


graphite = mat('GraphiteArmor', (0.045, .055, .07, 1), .72, .28)
steel = mat('IndustrialSteel', (.07, .09, .12, 1), .65, .38)
cyan = mat('CyanTech', (.02, .16, .20, 1), .3, .2, (.02, .8, 1.0, 1))
amber = mat('EmergencyAmber', (.15, .06, .01, 1), .2, .3, (1.0, .24, .02, 1))
enemy_mat = mat('VeyrCeramic', (.12, .13, .14, 1), .45, .25)

# Environment: an original modular military-colony / underground set.
bpy.ops.mesh.primitive_plane_add(size=90, location=(0, 4, 0))
ground = bpy.context.object
ground.name = 'BLACKSTAR_ENVIRONMENT_FLOOR'
ground.data.materials.append(steel)
for side in (-1, 1):
    bpy.ops.mesh.primitive_cube_add(location=(side * 8.5, 6, 3.5), scale=(.4, 18, 3.5))
    bpy.context.object.data.materials.append(steel)
for y in range(-8, 24, 4):
    bpy.ops.mesh.primitive_cube_add(location=(0, y, 6.8), scale=(8.5, .18, .18))
    bpy.context.object.data.materials.append(steel)

# Persistent cast using stable names. Bodies are articulated from separate pieces,
# not a single cube, so later rig/asset replacement can preserve animation hooks.
characters = {}
for i, ch in enumerate(bible.get('characters', [])):
    x = (i - 1.5) * 1.65
    root = bpy.data.objects.new(ch['id'], None)
    bpy.context.collection.objects.link(root)
    root.location = (x, -1.5 - i * .25, 0)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=.31, location=(x, -1.5 - i*.25, 1.77))
    head = bpy.context.object; head.name = ch['id'] + '_HELMET'; head.data.materials.append(graphite); head.parent = root
    bpy.ops.mesh.primitive_cube_add(location=(x, -1.5 - i*.25, 1.05), scale=(.46, .29, .58))
    torso = bpy.context.object; torso.name = ch['id'] + '_TORSO'; torso.data.materials.append(graphite); torso.parent = root
    for sx in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(location=(x + sx*.58, -1.5-i*.25, 1.05), scale=(.12, .12, .5))
        arm = bpy.context.object; arm.name = f"{ch['id']}_ARM_{'R' if sx>0 else 'L'}"; arm.data.materials.append(graphite); arm.parent = root
        bpy.ops.mesh.primitive_cube_add(location=(x + sx*.22, -1.5-i*.25, .34), scale=(.14, .14, .54))
        leg = bpy.context.object; leg.name = f"{ch['id']}_LEG_{'R' if sx>0 else 'L'}"; leg.data.materials.append(graphite); leg.parent = root
    characters[ch['id']] = root

# Opposing Veyr units; original silhouette and luminous faceplate.
enemies = []
for i in range(6):
    x = -5 + i * 2.0
    root = bpy.data.objects.new(f'VEYR_UNIT_{i+1}', None); bpy.context.collection.objects.link(root); root.location=(x, 10+i*.5, 0)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=.38, location=(x,10+i*.5,1.75)); h=bpy.context.object; h.scale=(.8,.65,1.15); h.data.materials.append(enemy_mat); h.parent=root
    bpy.ops.mesh.primitive_cube_add(location=(x,10+i*.5,1.0),scale=(.48,.30,.72)); b=bpy.context.object; b.data.materials.append(enemy_mat); b.parent=root
    bpy.ops.mesh.primitive_cube_add(location=(x,9.69+i*.5,1.78),scale=(.23,.04,.10)); f=bpy.context.object; f.data.materials.append(cyan); f.parent=root
    enemies.append(root)

# Segment-specific hero props driven by shot text.
shot_text = ' '.join(shots).lower()
if any(k in shot_text for k in ('gateway','portal')) or idx in range(14,19):
    for r in (2.2, 2.8, 3.4):
        bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=.08, location=(0,13,3.4), rotation=(math.pi/2,0,0))
        bpy.context.object.data.materials.append(cyan)
if any(k in shot_text for k in ('drone','signal')) or idx in (7,8,9):
    for n in range(5):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=.23, location=(-3+n*1.4,5+n*.5,2.1+n*.2))
        d=bpy.context.object; d.name=f'DRONE_{n+1}'; d.data.materials.append(enemy_mat)
if any(k in shot_text for k in ('dropship','landing','orbit','exterior','extraction')) or idx in (1,2,3,18,19,20):
    bpy.ops.mesh.primitive_cube_add(location=(0,17,6), scale=(2.4,5.2,.75))
    ship=bpy.context.object; ship.name='KESTREL_DROPSHIP'; ship.data.materials.append(graphite)
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=2.5, radius2=.2, depth=4, location=(0,12.6,6), rotation=(math.pi/2,0,0))
    bpy.context.object.data.materials.append(graphite)

# Controlled debris for combat/collapse segments.
action = idx in {8,10,11,12,13,16,17,18,19}
if action:
    for n in range(26):
        x = -7 + (n % 9) * 1.7
        y = 1 + (n // 9) * 4.5
        z = .25 + (n % 5) * .35
        bpy.ops.mesh.primitive_cube_add(location=(x,y,z), scale=(.08+.03*(n%3),.12,.05+.02*(n%4)))
        piece=bpy.context.object; piece.data.materials.append(steel)
        piece.rotation_euler=(n*.31,n*.17,n*.23)
        piece.keyframe_insert('location',frame=1)
        piece.location.z += 1.2 + (n%4)*.35; piece.location.x += math.sin(n)*1.1
        piece.keyframe_insert('location',frame=scene.frame_end)

# Character blocking follows story phase.
for ci, root in enumerate(characters.values()):
    root.keyframe_insert('location', frame=1)
    if idx <= 6:
        root.location.y += 5.5 + ci*.25
    elif idx <= 13:
        root.location.y += 8.5
        root.location.x += (-1 if ci%2 else 1) * 1.2
    elif idx <= 18:
        root.location.y += 11.0
        root.location.x += (-2.0 + ci*1.3)
    else:
        root.location.y += 15.0
    root.keyframe_insert('location', frame=scene.frame_end)

# Enemy advance/retreat only when the story has revealed them.
for ei, root in enumerate(enemies):
    root.hide_render = idx < 9 or idx == 20
    if not root.hide_render:
        root.keyframe_insert('location', frame=1)
        root.location.y -= 4.0 + (ei % 3)
        root.location.x += math.sin(ei + idx) * 1.4
        root.keyframe_insert('location', frame=scene.frame_end)

# Camera: one motivated move per shot, creating real shot changes while preserving
# overall screen direction. Blender interpolates between the locked shot beats.
bpy.ops.object.camera_add(location=(0,-10,3.8))
cam=bpy.context.object; cam.name='BLACKSTAR_CAMERA'; scene.camera=cam; cam.data.lens=42
shot_count=max(1,len(shots))
for s in range(shot_count):
    frame = 1 + int((scene.frame_end-1) * s / max(1, shot_count-1)) if shot_count > 1 else 1
    phase = (idx * .61 + s * 1.27)
    radius = 8.5 if not action else 6.5
    cam.location = (math.sin(phase)*3.8, -4.5 + s*(12.0/max(1,shot_count-1)), 2.4 + 1.1*math.cos(phase*.7))
    look(cam,(0, 4.5 + s*(7.0/max(1,shot_count-1)), 1.25))
    cam.data.lens = 34 + (s % 4) * 6
    cam.keyframe_insert('location',frame=frame)
    cam.keyframe_insert('rotation_euler',frame=frame)
    cam.data.keyframe_insert('lens',frame=frame)
    scene.timeline_markers.new(f'SHOT_{s+1}_{re.sub("[^A-Za-z0-9]+","_",shots[s])[:32] if shots else "BEAT"}',frame=frame)

# Lighting and atmosphere.
for name,loc,energy,size,color in [
    ('KEY',(-4,-4,7),1900,5,(.65,.80,1.0)),
    ('RIM',(5,4,5),1500,4,(.1,.65,1.0)),
    ('FILL',(0,-1,4),600,6,(1.0,.42,.16)),
]:
    bpy.ops.object.light_add(type='AREA',location=loc)
    l=bpy.context.object; l.name=name; l.data.energy=energy; l.data.shape='DISK'; l.data.size=size; l.data.color=color; look(l,(0,4,1))

bpy.ops.mesh.primitive_cube_add(size=36,location=(0,7,9))
vol=bpy.context.object; vol.name='ATMOSPHERE'
vm=bpy.data.materials.new('Volume'); vm.use_nodes=True; nodes=vm.node_tree.nodes; links=vm.node_tree.links; nodes.clear()
outn=nodes.new('ShaderNodeOutputMaterial'); p=nodes.new('ShaderNodeVolumePrincipled'); p.inputs['Density'].default_value=.006 if not action else .012; links.new(p.outputs['Volume'],outn.inputs['Volume']); vol.data.materials.append(vm); vol.display_type='WIRE'

# Segment identity stored in the .blend for later audit/replacement.
scene['episode_segment_index']=idx
scene['continuity_in']=str(seg.get('continuity_in',''))
scene['continuity_out']=str(seg.get('continuity_out',''))
scene['shot_plan']=json.dumps(shots)
scene.render.filepath=out
bpy.ops.wm.save_as_mainfile(filepath=str(Path(out).with_suffix('.blend')))
bpy.ops.render.render(animation=True)
