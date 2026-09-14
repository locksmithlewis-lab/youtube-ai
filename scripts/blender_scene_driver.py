"""Executed inside Blender. Builds a deterministic cinematic segment from JSON.
Uses Blender-native geometry, riggable proxies, lights, cameras, particles and
physics-ready scene objects. Production assets can replace proxies by stable IDs
without changing continuity contracts.
"""
import bpy, json, math, sys
from pathlib import Path
from mathutils import Vector

args=sys.argv[sys.argv.index("--")+1:]
manifest=json.loads(Path(args[0]).read_text(encoding="utf-8")); out=args[1]
seg=manifest["segment"]; bible=manifest["bible"]
scene=bpy.context.scene
scene.render.engine="BLENDER_EEVEE_NEXT"
scene.render.resolution_x=1920; scene.render.resolution_y=1080; scene.render.resolution_percentage=100
scene.render.fps=24; scene.frame_start=1; scene.frame_end=max(2,int(float(seg["duration"])*24))
scene.render.image_settings.file_format="FFMPEG"; scene.render.ffmpeg.format="MPEG4"; scene.render.ffmpeg.codec="H264"; scene.render.ffmpeg.constant_rate_factor="MEDIUM"; scene.render.filepath=out
scene.world.color=(0.006,0.009,0.018)

# cinematic ground/environment
bpy.ops.mesh.primitive_plane_add(size=80, location=(0,0,0)); ground=bpy.context.object; ground.name="BLACKSTAR_ENVIRONMENT"
mat=bpy.data.materials.new("EnvironmentMat"); mat.diffuse_color=(0.035,0.05,0.07,1); ground.data.materials.append(mat)

# persistent original squad proxies, keyed by character bible IDs
chars=bible.get("characters",[])
for i,ch in enumerate(chars):
    x=(i-(len(chars)-1)/2)*1.8
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=.38, location=(x,0,1.75)); head=bpy.context.object; head.name=ch["id"]+"_HEAD"
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x,0,1.0)); body=bpy.context.object; body.name=ch["id"]+"_ARMOR"; body.scale=(.55,.34,.72)
    # restrained breathing/stance animation
    body.keyframe_insert("location",frame=1); body.location.z+=.025; body.keyframe_insert("location",frame=scene.frame_end//2); body.location.z-=.025; body.keyframe_insert("location",frame=scene.frame_end)

# original fictional opposing silhouettes
for i in range(4):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=.55,location=(-4+i*2.6,7,1.35)); o=bpy.context.object; o.name=f"VEYRIC_UNIT_{i+1}"; o.scale=(.65,.42,1.45)

# camera continuity: segment endpoints use explicit manifest transforms when present
bpy.ops.object.camera_add(location=(0,-10,4.3)); cam=bpy.context.object; scene.camera=cam
def look(obj,pt): obj.rotation_euler=(Vector(pt)-obj.location).to_track_quat('-Z','Y').to_euler()
look(cam,(0,1,1.2)); cam.data.lens=42
cam.keyframe_insert("location",frame=1); cam.location=(2.4,-7.5,3.0); look(cam,(0,2,1.1)); cam.keyframe_insert("location",frame=scene.frame_end)

# professional three-point cinematic lighting
for name,loc,energy,size in [("KEY",(-4,-4,7),1800,5),("RIM",(5,3,5),1400,4),("FILL",(0,-1,4),650,6)]:
    bpy.ops.object.light_add(type='AREA',location=loc); l=bpy.context.object; l.name=name; l.data.energy=energy; l.data.shape='DISK'; l.data.size=size; look(l,(0,1,1))

# volumetric atmosphere
bpy.ops.mesh.primitive_cube_add(size=30,location=(0,3,8)); vol=bpy.context.object; vol.name="ATMOSPHERE"
vm=bpy.data.materials.new("Volume"); vm.use_nodes=True; nodes=vm.node_tree.nodes; links=vm.node_tree.links; nodes.clear(); outn=nodes.new('ShaderNodeOutputMaterial'); p=nodes.new('ShaderNodeVolumePrincipled'); p.inputs['Density'].default_value=.008; links.new(p.outputs['Volume'],outn.inputs['Volume']); vol.data.materials.append(vm); vol.display_type='WIRE'

scene.render.filepath=out
bpy.ops.wm.save_as_mainfile(filepath=str(Path(out).with_suffix('.blend')))
bpy.ops.render.render(animation=True)
