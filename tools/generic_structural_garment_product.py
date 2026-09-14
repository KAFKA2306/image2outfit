#!/usr/bin/env python3
"""Reusable Blender builder for GenWorks products with a tracked structural OBJ."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def _args():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p=argparse.ArgumentParser(); p.add_argument("--job", required=True); return p.parse_args(raw)
def _repo_path(value:str)->Path:
    path=(ROOT/value).resolve()
    if path != ROOT and ROOT not in path.parents: raise ValueError(f"path escapes repository: {value}")
    return path
def _require_bpy():
    try: import bpy
    except ImportError as exc: raise RuntimeError("generic_structural_garment_product.py must run inside Blender") from exc
    return bpy
def _select_only(bpy, objects):
    bpy.ops.object.select_all(action="DESELECT")
    for item in objects: item.select_set(True)
    if objects: bpy.context.view_layer.objects.active=objects[0]
def main()->int:
    args=_args(); job_path=Path(args.job).resolve(); job=json.loads(job_path.read_text(encoding="utf-8-sig"))
    product_id=job["id"]; product_root=_repo_path(job["productRoot"]); prototype=product_root/"Source/Prototype/structural.obj"
    if not prototype.is_file(): raise FileNotFoundError(f"structural prototype missing: {prototype}")
    target_value=job.get("targetSourcePath")
    if not isinstance(target_value,str) or not target_value: raise ValueError("job.targetSourcePath is required")
    target_path=_repo_path(target_value)
    if not target_path.is_file(): raise FileNotFoundError(f"target avatar source missing: {target_path}")
    bpy=_require_bpy(); bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.fbx(filepath=str(target_path))
    target_objects=list(bpy.context.scene.objects); armatures=[x for x in target_objects if x.type=="ARMATURE"]; body_meshes=[x for x in target_objects if x.type=="MESH"]
    if not armatures or not body_meshes: raise RuntimeError("target import did not produce armature and mesh")
    armature=max(armatures,key=lambda x:len(x.data.bones)); body=max(body_meshes,key=lambda x:len(x.data.vertices))
    before=set(bpy.context.scene.objects)
    bpy.ops.wm.obj_import(filepath=str(prototype),forward_axis="NEGATIVE_Y",up_axis="Z",use_split_objects=True,use_split_groups=True,import_vertex_groups=True)
    garment=[x for x in bpy.context.scene.objects if x not in before and x.type=="MESH"]
    if not garment: raise RuntimeError("prototype import produced no garment meshes")
    total_vertices=0; transferred=[]
    for item in garment:
        total_vertices += len(item.data.vertices)
        solid=item.modifiers.new(name="Image2OutfitThickness",type="SOLIDIFY"); solid.thickness=.003; solid.offset=0.0
        bpy.context.view_layer.objects.active=item; item.select_set(True); bpy.ops.object.modifier_apply(modifier=solid.name); item.select_set(False)
        transfer=item.modifiers.new(name="Image2OutfitWeightTransfer",type="DATA_TRANSFER"); transfer.object=body; transfer.use_vert_data=True; transfer.data_types_verts={"VGROUP_WEIGHTS"}; transfer.vert_mapping="POLYINTERP_NEAREST"; transfer.layers_vgroup_select_src="ALL"; transfer.layers_vgroup_select_dst="NAME"; transfer.mix_mode="REPLACE"; transfer.mix_factor=1.0
        bpy.context.view_layer.objects.active=item; item.select_set(True); bpy.ops.object.modifier_apply(modifier=transfer.name); item.select_set(False)
        arm=item.modifiers.new(name="Armature",type="ARMATURE"); arm.object=armature; item.parent=armature
        transferred.append({"name":item.name,"vertices":len(item.data.vertices),"vertexGroups":len(item.vertex_groups)})
    blend_path=_repo_path(job["blendPath"]); fbx_path=_repo_path(job["fbxAssetPath"]); blend_path.parent.mkdir(parents=True,exist_ok=True); fbx_path.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path)); _select_only(bpy,[armature,*garment]); bpy.ops.export_scene.fbx(filepath=str(fbx_path),use_selection=True,add_leaf_bones=False,bake_anim=False,object_types={"ARMATURE","MESH"})
    report_path=product_root/"Evidence/Blender/structural-build.json"; report_path.parent.mkdir(parents=True,exist_ok=True)
    report={"schemaVersion":1,"productId":product_id,"builder":"tools/generic_structural_garment_product.py","prototype":str(prototype.relative_to(ROOT)).replace("\\","/"),"prototypeAxes":{"forward":"NEGATIVE_Y","up":"Z"},"targetSource":target_value,"build":"PASS","weightTransfer":"PASS","visualFit":"UNVERIFIED","poseValidation":"UNVERIFIED","garmentObjects":transferred,"garmentObjectCount":len(garment),"sourceVertexCountBeforeSolidify":total_vertices,"blendPath":job["blendPath"],"fbxAssetPath":job["fbxAssetPath"]}
    report_path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8"); print(json.dumps(report,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
