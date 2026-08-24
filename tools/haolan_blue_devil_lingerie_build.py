#!/usr/bin/env python3
"""Build the HAOLAN powder-blue devil lingerie reference outfit.

The builder has two deterministic modes:
- exact target mode when a private HAOLAN FBX has been materialized by the
  self-hosted workflow;
- audited-fit fallback mode for hosted Blender evidence generation.

The public artifact contains only generated garment geometry and render evidence.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import bpy
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont

import siroino_strappy_knit_build as base

PRODUCT_ID = "haolan-blue-devil-lingerie"
ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"path escapes repository: {value}")
    return path


def _mat(name: str, rgb: tuple[float, float, float], roughness: float, metallic: float = 0.0):
    return base.plain_material(name, (*rgb, 1.0), roughness=roughness, metallic=metallic)


def _mesh(name: str, vertices, faces, material) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return obj


def _panel(name: str, xz: list[tuple[float, float]], y: float, thickness: float, material) -> bpy.types.Object:
    n = len(xz)
    front = [(x, y - thickness * 0.5, z) for x, z in xz]
    back = [(x, y + thickness * 0.5, z) for x, z in xz]
    vertices = front + back
    faces = [tuple(range(n)), tuple(reversed(range(n, 2 * n)))]
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, n + j, n + i))
    obj = _mesh(name, vertices, faces, material)
    bevel = obj.modifiers.new("Soft edge", "BEVEL")
    bevel.width = min(0.0025, thickness * 0.35)
    bevel.segments = 2
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    try:
        bpy.ops.object.modifier_apply(modifier=bevel.name)
    finally:
        obj.select_set(False)
    return obj


def _elliptic_band(name, center, radii_bottom, radii_top, height, thickness, material, segments=64):
    cx, cy, cz = center
    z0, z1 = cz - height * 0.5, cz + height * 0.5
    vertices = []
    for radii, z in ((radii_bottom, z0), (radii_top, z1)):
        for i in range(segments):
            t = math.tau * i / segments
            vertices.append((cx + radii[0] * math.cos(t), cy + radii[1] * math.sin(t), z))
    for radii, z in ((radii_bottom, z0), (radii_top, z1)):
        for i in range(segments):
            t = math.tau * i / segments
            vertices.append((cx + max(.001, radii[0] - thickness) * math.cos(t), cy + max(.001, radii[1] - thickness) * math.sin(t), z))
    ob, ot, ib, it = 0, segments, 2 * segments, 3 * segments
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.extend([
            (ob+i, ob+j, ot+j, ot+i),
            (ib+i, it+i, it+j, ib+j),
            (ot+i, ot+j, it+j, it+i),
            (ob+i, ib+i, ib+j, ob+j),
        ])
    return _mesh(name, vertices, faces, material)


def _box(name, location, scale, material, bevel=.003):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    if bevel:
        mod = obj.modifiers.new("Rounded edge", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def _uv_sphere(name, location, scale, material):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=28, ring_count=16, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def _torus(name, location, major_radius, minor_radius, scale_xy, material):
    bpy.ops.mesh.primitive_torus_add(major_radius=major_radius, minor_radius=minor_radius, major_segments=48, minor_segments=10, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale.x = scale_xy[0]
    obj.scale.y = scale_xy[1]
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def _curve(name: str, points, radius: float, material) -> bpy.types.Object:
    curve = bpy.data.curves.new(f"{name}_Curve", type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for bp, point in zip(spline.bezier_points, points):
        bp.co = point
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    obj = bpy.context.active_object
    obj.name = name
    return obj


def _heart(name, center, size, thickness, material):
    cx, cy, cz = center
    pts = []
    for i in range(96):
        t = math.tau * i / 96
        x = 16 * math.sin(t) ** 3
        z = 13 * math.cos(t) - 5 * math.cos(2*t) - 2 * math.cos(3*t) - math.cos(4*t)
        pts.append((cx + size * x / 18.0, cy, cz + size * z / 18.0))
    pts.append(pts[0])
    return _curve(name, pts, thickness, material)


def _bat_wing(name, side, navy, pale):
    s = side
    poly = [
        (s*.105,.84),(s*.25,.91),(s*.48,.83),(s*.60,.65),
        (s*.47,.70),(s*.40,.57),(s*.31,.68),(s*.22,.60),(s*.19,.75),
    ]
    wing = _panel(name, poly, .092, .012, navy)
    root = (s*.11,.083,.82)
    ribs = []
    for i, target in enumerate([(s*.48,.083,.83),(s*.58,.083,.66),(s*.40,.083,.58),(s*.23,.083,.61)]):
        ribs.append(_curve(f"{name}_Rib_{i}", [root, target], .0040, pale))
    return [wing, *ribs]


def _bow(name, center, width, height, y, material):
    cx, _, cz = center
    left = _panel(f"{name}_L", [(cx,cz),(cx-width*.52,cz+height*.36),(cx-width*.46,cz-height*.42)], y, .008, material)
    right = _panel(f"{name}_R", [(cx,cz),(cx+width*.52,cz+height*.36),(cx+width*.46,cz-height*.42)], y, .008, material)
    knot = _uv_sphere(f"{name}_Knot", (cx,y-.006,cz), (.014,.010,.014), material)
    return [left, right, knot]


def _make_armature():
    data = bpy.data.armatures.new("HAOLAN_Fallback_Armature")
    arm = bpy.data.objects.new("Armature", data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    specs = {
        "Hips": ((0,0,.53),(0,0,.64),None),
        "Spine": ((0,0,.64),(0,0,.78),"Hips"),
        "Chest": ((0,0,.78),(0,0,.94),"Spine"),
        "Neck": ((0,0,.94),(0,0,1.04),"Chest"),
        "Head": ((0,0,1.04),(0,0,1.16),"Neck"),
        "UpperArm_L": ((-.10,0,.90),(-.31,0,.83),"Chest"),
        "LowerArm_L": ((-.31,0,.83),(-.48,0,.73),"UpperArm_L"),
        "Hand_L": ((-.48,0,.73),(-.56,0,.68),"LowerArm_L"),
        "UpperArm_R": ((.10,0,.90),(.31,0,.83),"Chest"),
        "LowerArm_R": ((.31,0,.83),(.48,0,.73),"UpperArm_R"),
        "Hand_R": ((.48,0,.73),(.56,0,.68),"LowerArm_R"),
        "UpperLeg_L": ((-.065,0,.57),(-.075,0,.31),"Hips"),
        "LowerLeg_L": ((-.075,0,.31),(-.075,0,.06),"UpperLeg_L"),
        "UpperLeg_R": ((.065,0,.57),(.075,0,.31),"Hips"),
        "LowerLeg_R": ((.075,0,.31),(.075,0,.06),"UpperLeg_R"),
    }
    created = {}
    for name, (head, tail, parent) in specs.items():
        bone = data.edit_bones.new(name)
        bone.head, bone.tail = head, tail
        created[name] = bone
        if parent:
            bone.parent = created[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    arm.select_set(False)
    return arm


def _fallback_body(armature, skin):
    parts = [
        ("Chest",(0,-.005,.80),(.145,.095,.235)),
        ("Hips",(0,-.002,.58),(.145,.105,.12)),
        ("Head",(0,-.005,1.09),(.09,.09,.105)),
        ("UpperArm_L",(-.205,-.002,.86),(.13,.052,.052)),
        ("LowerArm_L",(-.395,-.002,.78),(.12,.046,.046)),
        ("UpperArm_R",(.205,-.002,.86),(.13,.052,.052)),
        ("LowerArm_R",(.395,-.002,.78),(.12,.046,.046)),
        ("UpperLeg_L",(-.07,-.002,.34),(.068,.075,.25)),
        ("UpperLeg_R",(.07,-.002,.34),(.068,.075,.25)),
    ]
    objs=[]
    for idx,(group,loc,scale) in enumerate(parts):
        obj=_uv_sphere(f"BodyPart_{idx}",loc,scale,skin)
        vg=obj.vertex_groups.new(name=group)
        vg.add(list(range(len(obj.data.vertices))),1.0,"REPLACE")
        objs.append(obj)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=objs[0]
    bpy.ops.object.join()
    body=bpy.context.active_object
    body.name="HAOLAN_Lowpoly_Fallback"
    body.parent=armature
    mod=body.modifiers.new("HAOLAN Armature","ARMATURE")
    mod.object=armature
    return body


def _load_target(skin):
    _, job = base.load_job()
    source = repo_path(job.get("targetSourcePath", "Assets/_Local/Resolved/HAOLAN_Lowpoly.fbx"))
    exact = source.is_file() and source.suffix.lower() == ".fbx"
    if exact:
        bpy.ops.import_scene.fbx(filepath=str(source), use_anim=False)
        armatures=[o for o in bpy.context.scene.objects if o.type=="ARMATURE"]
        meshes=[o for o in bpy.context.scene.objects if o.type=="MESH"]
        if not armatures or not meshes:
            raise RuntimeError("materialized HAOLAN FBX did not expose an armature and mesh")
        armature=max(armatures,key=lambda o: len(o.data.bones))
        body=max(meshes,key=lambda o: len(o.data.vertices))
        for obj in meshes:
            if obj != body:
                obj.hide_render=True
                obj.hide_set(True)
        base.set_skin_material(body)
        return job,body,armature,True,source
    armature=_make_armature()
    body=_fallback_body(armature,skin)
    return job,body,armature,False,source


def _attach(obj, body, armature):
    base.transfer_nearest_body_weights(obj, body)
    obj.parent=armature
    mod=obj.modifiers.new("HAOLAN Armature","ARMATURE")
    mod.object=armature
    mod.use_deform_preserve_volume=True


def _build_outfit(body, armature, mats):
    white,blue,navy,silver=mats["white"],mats["blue"],mats["navy"],mats["silver"]
    g=[]
    g += [
        _panel("CropTop_Left",[(-.145,.965),(-.035,.955),(-.020,.825),(-.145,.835),(-.185,.905)],-.102,.012,white),
        _panel("CropTop_Right",[(.145,.965),(.035,.955),(.020,.825),(.145,.835),(.185,.905)],-.102,.012,white),
        _elliptic_band("Neck_Collar",(0,0,1.005),(.067,.073),(.069,.075),.038,.010,white,48),
        _elliptic_band("Underbust_Belt",(0,0,.815),(.155,.105),(.155,.105),.028,.014,white,64),
    ]
    g += _bow("Neck_Bow",(0,0,.973),.135,.080,-.132,blue)
    g.append(_box("Underbust_Buckle",(0,-.116,.815),(.023,.010,.018),silver,.003))
    g.append(_box("Underbust_Buckle_Center",(0,-.129,.815),(.012,.006,.010),white,.002))
    for side in (-1,1):
        for i in range(5):
            x0=side*(.135+.018*i); x1=side*(.19+.020*i); z=.935-.018*i
            g.append(_panel(f"Shoulder_Ruffle_{'L' if side<0 else 'R'}_{i}",[(x0,z+.025),(x1,z+.047),(x1,z-.030)],-.073+.010*i,.008,white))
    g.append(_elliptic_band("Waist_Cincher",(0,0,.715),(.143,.102),(.132,.094),.135,.012,blue,72))
    eye_y=-.112
    for i in range(5):
        z0=.665+i*.022
        g.append(_curve(f"Corset_Lace_A_{i}",[(-.031,eye_y,z0),(.031,eye_y-.006,z0+.020)],.0032,white))
        g.append(_curve(f"Corset_Lace_B_{i}",[(.031,eye_y,z0),(-.031,eye_y-.006,z0+.020)],.0032,white))
    g.append(_curve("Corset_Tie_L",[(-.012,eye_y,.664),(-.030,eye_y-.006,.615)],.0028,blue))
    g.append(_curve("Corset_Tie_R",[(.012,eye_y,.664),(.030,eye_y-.006,.615)],.0028,blue))
    g += [
        _panel("Panty_Front",[(-.122,.625),(.122,.625),(.080,.545),(0,.515),(-.080,.545)],-.100,.014,white),
        _panel("Panty_Back",[(-.125,.625),(.125,.625),(.090,.535),(-.090,.535)],.095,.014,white),
        _panel("Lace_Apron",[(-.085,.595),(.085,.595),(.067,.490),(-.067,.490)],-.119,.010,white),
    ]
    g += _bow("Panty_Bow_Center",(0,0,.603),.055,.034,-.131,blue)
    for side in (-1,1):
        g += _bow(f"Panty_Bow_{side:+.0f}",(side*.077,0,.552),.038,.026,-.128,blue)
    for i in range(12):
        x=-.13+i*.0235
        g.append(_panel(f"Top_Hem_Ruffle_{i}",[(x,.833),(x+.017,.833),(x+.0085,.807)],-.110,.006,white))
    for i in range(8):
        x=-.070+i*.020
        g.append(_panel(f"Apron_Ruffle_{i}",[(x,.497),(x+.017,.497),(x+.0085,.480)],-.126,.006,white))
    for side in (-1,1):
        x=side*.085
        g.append(_curve(f"Garter_Front_{side:+.0f}",[(x,-.118,.563),(x,-.098,.452)],.0044,white))
        g.append(_curve(f"Garter_Outer_{side:+.0f}",[(side*.118,-.075,.590),(side*.125,-.045,.462)],.0040,white))
        g.append(_torus(f"Thigh_Band_{side:+.0f}",(side*.072,0,.438),.070,.010,(1.0,1.0),white))
        g.append(_box(f"Garter_Clip_{side:+.0f}",(x,-.100,.445),(.010,.008,.020),silver,.002))
        g.append(_elliptic_band(f"Blue_Arm_Cuff_{side:+.0f}",(side*.39,0,.785),(.050,.050),(.050,.050),.055,.010,blue,40))
        g.append(_elliptic_band(f"White_Wrist_Glove_{side:+.0f}",(side*.505,0,.715),(.043,.043),(.050,.050),.105,.010,white,40))
    g += _bat_wing("BatWing_L",-1.0,navy,blue)
    g += _bat_wing("BatWing_R",1.0,navy,blue)
    g.append(_curve("Devil_Tail",[(.10,.10,.64),(.22,.12,.67),(.38,.08,.73),(.47,.03,.80),(.45,-.02,.86)],.008,blue))
    g.append(_heart("Devil_Tail_Heart",(.45,-.02,.885),.050,.005,blue))
    for obj in g:
        if obj.type=="MESH":
            _attach(obj,body,armature)
    return g


def _studio():
    world=bpy.context.scene.world or bpy.data.worlds.new("Review World")
    bpy.context.scene.world=world
    world.use_nodes=True
    world.node_tree.nodes["Background"].inputs["Color"].default_value=(.97,.98,1.0,1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value=.65
    bpy.ops.mesh.primitive_plane_add(size=5,location=(0,0,-.005))
    floor=bpy.context.active_object
    floor.name="Studio_Floor"
    floor.data.materials.append(_mat("Studio_White",(.91,.93,.97),.80))
    def area(name,location,energy,color,size):
        data=bpy.data.lights.new(name,type="AREA"); data.energy=energy; data.color=color; data.shape="DISK"; data.size=size
        obj=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(obj); obj.location=location
        obj.rotation_euler=(Vector((0,0,.67))-obj.location).to_track_quat("-Z","Y").to_euler()
    area("Key",(-1.1,-1.6,1.8),550,(1.0,.93,.88),1.8)
    area("Fill",(1.4,-1.0,1.25),360,(.86,.92,1.0),1.7)
    area("Rim",(.3,1.5,1.35),500,(.80,.88,1.0),1.5)
    camera_data=bpy.data.cameras.new("Product_Camera")
    camera=bpy.data.objects.new("Product_Camera",camera_data); bpy.context.collection.objects.link(camera)
    camera_data.type="ORTHO"; camera_data.ortho_scale=1.34; bpy.context.scene.camera=camera
    return camera


def _point_camera(camera,location,target=(0,-.01,.61)):
    camera.location=location
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat("-Z","Y").to_euler()


def _render(previews,camera):
    scene=bpy.context.scene
    scene.render.engine="BLENDER_EEVEE_NEXT"
    scene.render.resolution_x=900; scene.render.resolution_y=1100; scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG"; scene.render.image_settings.color_mode="RGBA"; scene.render.film_transparent=False
    scene.view_settings.look="AgX - Medium High Contrast"
    views={"front":(0,-2.4,.68),"back":(0,2.4,.68),"left":(2.4,0,.68),"right":(-2.4,0,.68),"three-quarter":(1.55,-1.85,.70)}
    webps={}
    for name,loc in views.items():
        path=previews[name]; path.parent.mkdir(parents=True,exist_ok=True); _point_camera(camera,loc); scene.render.filepath=str(path)
        bpy.ops.render.render(write_still=True)
        wp=path.with_suffix(".webp"); Image.open(path).convert("RGB").save(wp,"WEBP",quality=94,method=6); webps[name]=wp
    return webps


def _contact_sheet(webps,output):
    names=["front","three-quarter","left","right","back"]
    tw,th=540,660; canvas=Image.new("RGB",(tw*3,th*2),(246,248,252)); draw=ImageDraw.Draw(canvas)
    try: font=ImageFont.truetype("DejaVuSans.ttf",26)
    except OSError: font=ImageFont.load_default()
    positions=[(0,0),(tw,0),(tw*2,0),(tw//2,th),(tw+tw//2,th)]
    for name,(x,y) in zip(names,positions):
        image=Image.open(webps[name]).convert("RGB"); image.thumbnail((tw-20,th-20),Image.Resampling.LANCZOS)
        canvas.paste(image,(x+(tw-image.width)//2,y+(th-image.height)//2))
        draw.rounded_rectangle((x+16,y+16,x+210,y+56),10,fill=(255,255,255)); draw.text((x+27,y+23),name.upper(),fill=(35,44,68),font=font)
    output.parent.mkdir(parents=True,exist_ok=True); canvas.save(output,"WEBP",quality=94,method=6)


def _write_integrated_prefab(job):
    path=repo_path(job["integratedPrefabAssetPath"]); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("""%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &100000
GameObject:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  serializedVersion: 6
  m_Component:
  - component: {fileID: 400000}
  m_Layer: 0
  m_Name: HAOLAN_BlueDevilLingerie_Integrated
  m_TagString: Untagged
  m_Icon: {fileID: 0}
  m_NavMeshLayer: 0
  m_StaticEditorFlags: 0
  m_IsActive: 1
--- !u!4 &400000
Transform:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  m_GameObject: {fileID: 100000}
  serializedVersion: 2
  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}
  m_LocalPosition: {x: 0, y: 0, z: 0}
  m_LocalScale: {x: 1, y: 1, z: 1}
  m_ConstrainProportionsScale: 0
  m_Children: []
  m_Father: {fileID: 0}
  m_LocalEulerAnglesHint: {x: 0, y: 0, z: 0}
""",encoding="utf-8")


def _write_records(job,exact_target,garments,webps,contact):
    root=repo_path(job["productRoot"]); manifest=repo_path(job["productManifestPath"]); metrics=base.metrics(garments)
    record={
        "schemaVersion":1,"productId":PRODUCT_ID,"productName":job["productName"],"generatedAt":utc_now(),"buildRevision":job.get("buildRevision"),
        "targetMode":"materialized-private-haolan" if exact_target else "audited-fit-fallback","targetSourcePresent":exact_target,
        "modules":["frilled-crop-top","neck-bow","underbust-belt","waist-cincher-lacing","lace-panty","garter-suspension","thigh-bands","arm-cuffs-gloves","bat-wings","devil-tail-heart"],
        "metrics":metrics,"previewWebP":{k:v.relative_to(ROOT).as_posix() for k,v in webps.items()},"contactSheet":contact.relative_to(ROOT).as_posix(),
        "visualAppearanceReview":"PENDING_DIRECT_IMAGE_REVIEW"
    }
    manifest.parent.mkdir(parents=True,exist_ok=True); manifest.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (root/"Documentation").mkdir(parents=True,exist_ok=True); (root/"Documentation"/"build-report.json").write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return metrics


def main():
    _,job=base.load_job()
    if job.get("id")!=PRODUCT_ID: raise RuntimeError(f"unexpected job id: {job.get('id')!r}")
    base.clean_scene()
    mats={
        "skin":_mat("MAT_Preview_Skin",(.92,.66,.54),.53),"white":_mat("MAT_Pearl_White",(.97,.98,1.0),.48),
        "blue":_mat("MAT_Powder_Blue",(.47,.68,.88),.42),"navy":_mat("MAT_BatWing_Navy",(.10,.22,.38),.50),"silver":_mat("MAT_Silver",(.72,.78,.86),.23,.86),
    }
    job,body,armature,exact_target,_source=_load_target(mats["skin"])
    garments=_build_outfit(body,armature,mats)
    product_root=repo_path(job["productRoot"])
    for subdir in ("Source/Blender","Models","Prefab","Previews","Documentation"): (product_root/subdir).mkdir(parents=True,exist_ok=True)
    camera=_studio(); previews={name:repo_path(path) for name,path in job["previewPaths"].items()}; webps=_render(previews,camera)
    contact=product_root/"Previews"/"HAOLAN_BlueDevilLingerie_multiview.webp"; _contact_sheet(webps,contact)
    blend=repo_path(job["blendPath"]); blend.parent.mkdir(parents=True,exist_ok=True); bpy.ops.wm.save_as_mainfile(filepath=str(blend),check_existing=False,compress=True)
    body.hide_render=True; fbx=repo_path(job["fbxAssetPath"]); base.export_fbx(fbx,armature,garments)
    prefab=repo_path(job["prefabAssetPath"]); base.write_unity_sidecars(fbx,prefab,job["productName"]); _write_integrated_prefab(job)
    metrics=_write_records(job,exact_target,garments,webps,contact)
    required=[blend,fbx,prefab,repo_path(job["integratedPrefabAssetPath"]),contact,*webps.values()]
    missing=[str(p) for p in required if not p.is_file()]
    if missing: raise RuntimeError(f"missing generated artifacts: {missing}")
    if metrics.get("meshObjects",0)<20 or metrics.get("vertices",0)<1000: raise RuntimeError("generated outfit is below the minimum authored geometry threshold")
    if metrics.get("degenerateTriangles",0)!=0: raise RuntimeError(f"degenerate triangles detected: {metrics['degenerateTriangles']}")
    if metrics.get("unweightedVertices",0)!=0: raise RuntimeError(f"unweighted vertices detected: {metrics['unweightedVertices']}")
    if metrics.get("weightSumErrors",0)!=0: raise RuntimeError(f"weight sum errors detected: {metrics['weightSumErrors']}")
    print(json.dumps({"productId":PRODUCT_ID,"state":"WORKING","targetMode":"exact" if exact_target else "hosted-fallback","metrics":metrics,"visualAppearanceReview":"PENDING"},ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
