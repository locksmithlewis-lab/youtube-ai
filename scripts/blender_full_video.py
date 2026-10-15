"""Generic Rolixa Blender full-video renderer.
Builds a real animated 3D scene from a project manifest and renders headlessly with Blender.
"""
import bpy, json, math, sys
from pathlib import Path
from mathutils import Vector
args=sys.argv[sys.argv.index('--')+1:]
manifest=json.loads(Path(args[0]).read_text(encoding='utf-8')); out=args[1]
FPS=int(manifest.get('fps',8)); W=int(manifest.get('width',1280)); H=int(manifest.get('height',720))
scene=bpy.context.scene
# Eevee is fast enough for a five-video CI batch. The workflow runs Blender
# inside Xvfb with Mesa software OpenGL, avoiding both GPU dependencies and
# the multi-hour per-video cost of CPU path tracing.
# Debian/Ubuntu runners currently package Blender 4.0, where Eevee is named BLENDER_EEVEE.
# Newer Blender releases renamed the engine to BLENDER_EEVEE_NEXT.
engine_ids = {item.identifier for item in scene.render.bl_rna.properties['engine'].enum_items}
if 'BLENDER_EEVEE_NEXT' in engine_ids:
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
elif 'BLENDER_EEVEE' in engine_ids:
    scene.render.engine = 'BLENDER_EEVEE'
else:
    raise RuntimeError(f'No supported Eevee render engine in Blender {bpy.app.version_string}: {sorted(engine_ids)}')
scene.render.threads_mode = 'FIXED'
scene.render.threads = 2
# Eevee settings live on different properties across Blender versions.
if hasattr(scene, 'eevee') and hasattr(scene.eevee, 'taa_render_samples'):
    scene.eevee.taa_render_samples = 16
elif hasattr(scene, 'eevee_next') and hasattr(scene.eevee_next, 'taa_render_samples'):
    scene.eevee_next.taa_render_samples = 16
scene.render.resolution_x=W; scene.render.resolution_y=H; scene.render.resolution_percentage=100; scene.render.fps=FPS
scene.render.image_settings.file_format='FFMPEG'; scene.render.ffmpeg.format='MPEG4'; scene.render.ffmpeg.codec='H264'; scene.render.ffmpeg.constant_rate_factor='MEDIUM'; scene.render.filepath=out
scene.frame_start=1; scene.frame_end=max(2,int(float(manifest['duration'])*FPS)); scene.world.color=(.006,.008,.015)

def mat(name,c,metal=0,rough=.5,emit=None):
    m=bpy.data.materials.new(name); m.diffuse_color=(*c,1); m.use_nodes=True; b=m.node_tree.nodes.get('Principled BSDF')
    if b:
        b.inputs['Base Color'].default_value=(*c,1); b.inputs['Metallic'].default_value=metal; b.inputs['Roughness'].default_value=rough
        if emit:
            e=b.inputs.get('Emission Color') or b.inputs.get('Emission')
            if e: e.default_value=(*emit,1)
            s=b.inputs.get('Emission Strength')
            if s: s.default_value=2.5
    return m

def look(o,p): o.rotation_euler=(Vector(p)-o.location).to_track_quat('-Z','Y').to_euler()
def clear(): bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
floor=mat('RolixaFloor',(.025,.035,.055),.35,.42); dark=mat('RolixaDark',(.035,.045,.07),.65,.32); cyan=mat('RolixaCyan',(.02,.25,.42),.2,.22,(.02,.35,.8)); amber=mat('RolixaAmber',(.45,.10,.025),.1,.3,(.8,.12,.02)); white=mat('RolixaWhite',(.55,.58,.65),.05,.35)

def environment():
    bpy.ops.mesh.primitive_plane_add(size=80,location=(0,0,0)); bpy.context.object.data.materials.append(floor)
    for x in (-9,9): bpy.ops.mesh.primitive_cube_add(location=(x,8,4),scale=(.3,18,4)); bpy.context.object.data.materials.append(dark)
    for y in range(-10,31,6): bpy.ops.mesh.primitive_cube_add(location=(0,y,7),scale=(9,.08,.08)); bpy.context.object.data.materials.append(white)

def lights():
    for loc,en,col in [((-5,-6,8),1100,(.55,.72,1)),((6,5,6),900,(.05,.45,1)),((0,-2,4),450,(1,.18,.04))]:
        bpy.ops.object.light_add(type='AREA',location=loc); l=bpy.context.object; l.data.energy=en; l.data.shape='DISK'; l.data.size=5; l.data.color=col; look(l,(0,6,1))

def attach_preserving_world(obj, parent):
    # Keep face parts in world position when parenting; otherwise Blender adds
    # the root translation again and the facial rig can drift away from the head.
    world_matrix = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_world = world_matrix


def subjects():
    skin=mat('NaturalWarmSkin',(.62,.39,.27),0,.72)
    hair=mat('NaturalDarkHair',(.035,.022,.018),0,.82)
    eye_white=mat('EyeWhites',(.92,.90,.84),0,.28)
    iris=mat('BrownIris',(.20,.085,.035),0,.3)
    pupil=mat('DarkPupils',(.012,.009,.008),0,.2)
    brows=mat('Eyebrows',(.075,.043,.028),0,.8)
    mouth=mat('NaturalMouth',(.22,.055,.045),0,.65)
    for i in range(4):
        x=(i-1.5)*2.1; y=1.1+i*.25; z=1.15
        root=bpy.data.objects.new(f'SUBJECT_{i}',None); bpy.context.collection.objects.link(root)
        bpy.ops.mesh.primitive_cylinder_add(vertices=16,radius=.48,depth=1.5,location=(x,y,z))
        body=bpy.context.object; body.name=f'SUBJECT_{i}_TORSO'; body.data.materials.append(cyan if i%2==0 else dark); attach_preserving_world(body,root)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=16,radius=.42,location=(x,y,z+1.15))
        head=bpy.context.object; head.name=f'SUBJECT_{i}_HEAD'; head.scale=(.92,.86,1.08); head.data.materials.append(skin); attach_preserving_world(head,root)
        # A real face rig: eyes, irises, pupils, brows, nose, mouth, ears and a hair cap.
        bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12,radius=.19,location=(x,y,z+1.53))
        cap=bpy.context.object; cap.name=f'SUBJECT_{i}_HAIR'; cap.scale=(1.75,1.0,1.0); cap.data.materials.append(hair); attach_preserving_world(cap,root)
        for side in (-1,1):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=10,radius=.073,location=(x+side*.145,y-.342,z+1.24))
            ew=bpy.context.object; ew.name=f'SUBJECT_{i}_EYE_WHITE_{side}'; ew.scale=(1.0,.48,.78); ew.data.materials.append(eye_white); attach_preserving_world(ew,root)
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=10,radius=.043,location=(x+side*.145,y-.377,z+1.24))
            ir=bpy.context.object; ir.name=f'SUBJECT_{i}_IRIS_{side}'; ir.data.materials.append(iris); attach_preserving_world(ir,root)
            bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,radius=.024,location=(x+side*.145,y-.397,z+1.24))
            pu=bpy.context.object; pu.name=f'SUBJECT_{i}_PUPIL_{side}'; pu.data.materials.append(pupil); attach_preserving_world(pu,root)
            bpy.ops.mesh.primitive_cube_add(size=1,location=(x+side*.145,y-.347,z+1.34))
            brow=bpy.context.object; brow.name=f'SUBJECT_{i}_BROW_{side}'; brow.scale=(.13,.035,.035); brow.rotation_euler.y=side*-.08; brow.data.materials.append(brows); attach_preserving_world(brow,root)
            bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,radius=.095,location=(x+side*.385,y,z+1.15))
            ear=bpy.context.object; ear.name=f'SUBJECT_{i}_EAR_{side}'; ear.scale=(.55,.42,1.0); ear.data.materials.append(skin); attach_preserving_world(ear,root)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=10,radius=.07,location=(x,y-.386,z+1.13))
        nose=bpy.context.object; nose.name=f'SUBJECT_{i}_NOSE'; nose.scale=(.72,.65,1.0); nose.data.materials.append(skin); attach_preserving_world(nose,root)
        bpy.ops.mesh.primitive_cube_add(size=1,location=(x,y-.365,z+1.025))
        lips=bpy.context.object; lips.name=f'SUBJECT_{i}_MOUTH'; lips.scale=(.14,.035,.028); lips.data.materials.append(mouth); attach_preserving_world(lips,root)
        # Keep the cast near the camera so facial features remain legible, with subtle motion only.
        root.keyframe_insert('location',frame=1)
        root.location.x+=math.sin(i+1)*.45; root.location.y+=.55
        root.keyframe_insert('location',frame=scene.frame_end)


def beat_objects(s):
    idx=int(s.get('index',0)); start=int(float(s['start'])*FPS)+1; end=min(scene.frame_end,max(start+2,int(float(s['end'])*FPS)))
    root=bpy.data.objects.new(f'BEAT_{idx}',None); bpy.context.collection.objects.link(root)
    kind=str(s.get('kind','general'))
    if kind in ('data','technology','science','gaming'):
        for n in range(5):
            bpy.ops.mesh.primitive_cube_add(location=(-5+n*2.5,8,1.2+(n%2)),scale=(.65,.65,.65)); o=bpy.context.object; o.data.materials.append(cyan if n%2 else amber); o.parent=root; o.keyframe_insert('rotation_euler',frame=start); o.rotation_euler.z+=math.pi; o.keyframe_insert('rotation_euler',frame=end)
    else:
        bpy.ops.mesh.primitive_torus_add(major_radius=2.4,minor_radius=.12,location=(0,10,3),rotation=(math.pi/2,0,0),major_segments=40,minor_segments=8); o=bpy.context.object; o.data.materials.append(cyan); o.parent=root; o.keyframe_insert('rotation_euler',frame=start); o.rotation_euler.z+=math.pi; o.keyframe_insert('rotation_euler',frame=end)

def build():
    clear(); environment(); lights(); subjects()
    bpy.ops.object.camera_add(location=(0,-11,4.2)); cam=bpy.context.object; scene.camera=cam; cam.data.lens=44
    for s in manifest.get('scenes',[]):
        start=int(float(s['start'])*FPS)+1; end=min(scene.frame_end,max(start+2,int(float(s['end'])*FPS))); idx=int(s.get('index',0))
        beat_objects(s)
        # Each beat gets a camera move across its full duration, not a single
        # keyframe at the beginning. This prevents long static shots when a
        # manifest has gaps or when the final beat extends to the video end.
        if idx % 3 == 0:
            # Recurring face close-ups are intentional, not optional background figures.
            focus=idx % 4
            fx=(focus-1.5)*2.1
            fy=1.1+focus*.25+.25
            cam.location=(fx+.18,fy-4.4,2.75)
            cam.data.lens=62
            look(cam,(fx,fy,2.30))
            cam.keyframe_insert('location',frame=start); cam.keyframe_insert('rotation_euler',frame=start); cam.data.keyframe_insert('lens',frame=start)
            cam.location.x+=.32; cam.location.y+=.35
            cam.data.lens=58
            look(cam,(fx,fy+.12,2.28))
            cam.keyframe_insert('location',frame=end); cam.keyframe_insert('rotation_euler',frame=end); cam.data.keyframe_insert('lens',frame=end)
        else:
            cam.location=(math.sin(idx*.7)*5,-11+min(8,idx*.8),3.5+math.cos(idx)*.8)
            cam.data.lens=44
            look(cam,(0,6,1.4)); cam.keyframe_insert('location',frame=start); cam.keyframe_insert('rotation_euler',frame=start); cam.data.keyframe_insert('lens',frame=start)
            cam.location.x += 1.1
            cam.location.y += 1.0
            cam.location.z += 0.25
            look(cam,(0.35,6.5,1.5))
            cam.keyframe_insert('location',frame=end); cam.keyframe_insert('rotation_euler',frame=end); cam.data.keyframe_insert('lens',frame=end)
    # Guarantee camera movement over the tail even if the final scene ends
    # before the full narration duration. Use linear interpolation so motion
    # continues smoothly instead of easing into a multi-second freeze.
    if cam.animation_data and cam.animation_data.action:
        for curve in cam.animation_data.action.fcurves:
            for key in curve.keyframe_points:
                key.interpolation='LINEAR'
    scene['rolixa_blender_full_video']=True; scene['topic']=manifest.get('topic',''); scene['scenes_json']=json.dumps(manifest.get('scenes',[]))
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(out).with_suffix('.blend')))
    bpy.ops.render.render(animation=True)
build()
