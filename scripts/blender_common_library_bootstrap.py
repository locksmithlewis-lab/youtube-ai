"""Blender bootstrap that applies the immutable BLACKSTAR common library.

Loaded before blender_scene_driver.py. A render_pre handler applies the same HDRI,
physical surface texture and segment-appropriate generated background plate to
every worker after the procedural scene has been built.
"""
import json, math, os
from pathlib import Path
import bpy

ROOT=Path(os.environ.get("BLACKSTAR_LIBRARY_DIR", ".blackstar-library"))
MANIFEST=ROOT/"library.json"


def asset_file(provider=None, contains=None):
    if not MANIFEST.exists(): raise RuntimeError(f"BLACKSTAR common library missing: {MANIFEST}")
    data=json.loads(MANIFEST.read_text(encoding="utf-8"))
    assets=data.get("assets",[])
    for a in assets:
        if provider and a.get("provider")!=provider: continue
        if contains and contains not in a.get("file",""): continue
        p=ROOT/a["file"]
        if p.exists(): return p
    if provider and contains:
        for a in assets:
            if contains not in a.get("file",""): continue
            p=ROOT/a["file"]
            if p.exists():
                print(f"BLACKSTAR using {a.get('provider')} fallback for {provider} slot: {p.name}")
                return p
    return None


def image_material(name,path,strength=1.0):
    m=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes=True; nodes=m.node_tree.nodes; links=m.node_tree.links; nodes.clear()
    out=nodes.new("ShaderNodeOutputMaterial"); em=nodes.new("ShaderNodeEmission"); tex=nodes.new("ShaderNodeTexImage")
    tex.image=bpy.data.images.load(str(path),check_existing=True); em.inputs["Strength"].default_value=strength
    links.new(tex.outputs["Color"],em.inputs["Color"]); links.new(em.outputs["Emission"],out.inputs["Surface"])
    return m


def apply(_scene):
    scene=bpy.context.scene
    if scene.get("blackstar_common_library_applied"): return
    idx=int(scene.get("episode_segment_index",1))

    hdri=asset_file("Poly Haven","environment")
    if hdri:
        world=scene.world or bpy.data.worlds.new("BLACKSTAR_WORLD"); scene.world=world; world.use_nodes=True
        n=world.node_tree.nodes; l=world.node_tree.links; n.clear()
        out=n.new("ShaderNodeOutputWorld"); bg=n.new("ShaderNodeBackground"); env=n.new("ShaderNodeTexEnvironment")
        env.image=bpy.data.images.load(str(hdri),check_existing=True); bg.inputs["Strength"].default_value=.18
        l.new(env.outputs["Color"],bg.inputs["Color"]); l.new(bg.outputs["Background"],out.inputs["Surface"])

    surface=asset_file("Poly Haven","surface")
    steel=bpy.data.materials.get("IndustrialSteel")
    if surface and steel:
        steel.use_nodes=True; nodes=steel.node_tree.nodes; links=steel.node_tree.links
        bsdf=nodes.get("Principled BSDF"); tex=nodes.get("BLACKSTAR_SHARED_SURFACE") or nodes.new("ShaderNodeTexImage"); tex.name="BLACKSTAR_SHARED_SURFACE"
        tex.image=bpy.data.images.load(str(surface),check_existing=True); tex.interpolation="Linear"
        if bsdf: links.new(tex.outputs["Color"],bsdf.inputs["Base Color"])

    if idx<=5: plate=asset_file("Runway","runway-erebus")
    elif idx<=13: plate=asset_file("Luma AI","luma-shaft")
    elif idx<=19: plate=asset_file("Runway","runway-gateway")
    else: plate=asset_file("Luma AI","luma-orbit")
    if not plate: raise RuntimeError(f"BLACKSTAR shared plate missing for segment {idx}")
    bpy.ops.mesh.primitive_plane_add(size=2,location=(0,30,7),rotation=(math.pi/2,0,0))
    p=bpy.context.object; p.name="BLACKSTAR_SHARED_BACKGROUND"; p.scale=(16,9,1)
    p.data.materials.append(image_material("BLACKSTAR_SHARED_PLATE",plate,.7))

    scene["blackstar_common_library_applied"]=True
    scene["blackstar_common_library_version"]=3
    print(f"BLACKSTAR common library applied to segment {idx}: {plate}")

bpy.app.handlers.render_pre.append(apply)
