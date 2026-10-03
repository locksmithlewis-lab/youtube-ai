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
for eng in ('BLENDER_EEVEE_NEXT','BLENDER_EEVEE','BLENDER_WORKBENCH'):
    try: scene.render.engine=eng; break
    except (TypeError,ValueError): pass
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

def subjects():
    for i in range(4):
        x=(i-1.5)*2.1; y=1.5+i*.4; z=1.15; root=bpy.data.objects.new(f'SUBJECT_{i}',None); bpy.context.collection.objects.link(root)
        bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=.48,depth=1.5,location=(x,y,z)); body=bpy.context.object; body.data.materials.append(cyan if i%2==0 else dark); body.parent=root
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,radius=.42,location=(x,y,z+1.15)); head=bpy.context.object; head.data.materials.append(white); head.parent=root
        root.keyframe_insert('location',frame=1); root.location.x+=math.sin(i+1)*2; root.location.y+=6+i*.4; root.keyframe_insert('location',frame=scene.frame_end)

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
        beat_objects(s); cam.location=(math.sin(idx*.7)*5,-11+min(8,idx*.8),3.5+math.cos(idx)*.8); look(cam,(0,6,1.4)); cam.keyframe_insert('location',frame=start); cam.keyframe_insert('rotation_euler',frame=start)
    scene['rolixa_blender_full_video']=True; scene['topic']=manifest.get('topic',''); scene['scenes_json']=json.dumps(manifest.get('scenes',[]))
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(out).with_suffix('.blend')))
    bpy.ops.render.render(animation=True)
build()
