#!/usr/bin/env python3
"""Generate the original SiroinoSotai wide-cargo VRChat outfit."""
from __future__ import annotations

import hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path

import bpy, bmesh
from PIL import Image, ImageDraw, ImageFont
import siroino_strappy_knit_build as c

ROOT = Path(__file__).resolve().parents[1]
PID = "siroino-wide-cargo"


def now(): return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def rp(v): return c.repo_path(v)
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def maps(out: Path):
    out.mkdir(parents=True, exist_ok=True); n = 1024
    values = {k: [] for k in ("fa", "fn", "fr", "sa", "sn", "sr")}
    for y in range(n):
        for x in range(n):
            a, b = math.sin(x*math.tau/9), math.sin(y*math.tau/11)
            t, m = math.sin((x+y*1.8)*math.tau/31), math.sin(x*.61+y*.37)
            v = max(7, min(28, int(14+2.5*a+2*b+2.5*t+m)))
            values["fa"].append((v,v+1,v+4)); values["fn"].append((int(128+16*a+7*t),int(128+13*b-5*t),251)); values["fr"].append(int(171+15*t+7*m))
            r=.5+.5*math.sin(x*math.tau/20); q=int(9+8*r+2*m)
            values["sa"].append((q,q,q+2)); values["sn"].append((int(128+26*math.sin(x*math.tau/20)),128,250)); values["sr"].append(int(135+20*(1-r)))
    result={}
    for key,name,mode in (("fa","black_cargo_albedo.png","RGB"),("fn","black_cargo_normal.png","RGB"),("fr","black_cargo_roughness.png","L"),("sa","black_strap_albedo.png","RGB"),("sn","black_strap_normal.png","RGB"),("sr","black_strap_roughness.png","L")):
        p=out/name; im=Image.new(mode,(n,n)); im.putdata(values[key]); im.save(p,optimize=True); result[key]=p
    return result


def mesh_obj(name, verts, faces, mat, arm, body, keys=True):
    me=bpy.data.meshes.new(name+"_Mesh"); me.from_pydata(verts,[],faces); me.update(calc_edges=True); me.materials.append(mat)
    ob=bpy.data.objects.new(name,me); bpy.context.collection.objects.link(ob); ob.parent=arm
    mod=ob.modifiers.new("SiroinoSotai Armature","ARMATURE"); mod.object=arm; mod.use_deform_preserve_volume=True
    bpy.ops.object.select_all(action="DESELECT"); ob.select_set(True); bpy.context.view_layer.objects.active=ob
    s=ob.modifiers.new("Fabric thickness","SOLIDIFY"); s.thickness=.0015; s.offset=0; s.use_even_offset=True; bpy.ops.object.modifier_apply(modifier=s.name)
    b=ob.modifiers.new("Finished edges","BEVEL"); b.width=.0008; b.segments=2; bpy.ops.object.modifier_apply(modifier=b.name)
    bm=bmesh.new(); bm.from_mesh(me); bmesh.ops.dissolve_degenerate(bm,dist=1e-7,edges=list(bm.edges)); bmesh.ops.triangulate(bm,faces=list(bm.faces))
    bad=[f for f in bm.faces if f.calc_area()<=1e-12]
    if bad: bmesh.ops.delete(bm,geom=bad,context="FACES")
    bm.to_mesh(me); bm.free(); me.update(calc_edges=True)
    for p in me.polygons: p.use_smooth=True
    c.transfer_nearest_body_weights(ob,body)
    if keys: c.add_nearest_shape_keys(ob,body)
    ob.select_set(False); return ob


def tube(name,rings,cx,mat,arm,body,seg=40):
    v=[]; f=[]
    for z,rx,ry,cy in rings:
        for i in range(seg):
            a=math.tau*i/seg; v.append((cx+rx*math.cos(a),cy+ry*math.sin(a),z))
    for r in range(len(rings)-1):
        for i in range(seg):
            j=(i+1)%seg; a=r*seg+i; f.append((a,r*seg+j,(r+1)*seg+j,(r+1)*seg+i))
    return mesh_obj(name,v,f,mat,arm,body)


def sector(name,rings,start,end,mat,arm,body,seg=28):
    v=[]; f=[]; w=seg+1
    for z,rx,ry in rings:
        for i in range(w):
            a=start+(end-start)*i/seg; v.append((rx*math.cos(a),ry*math.sin(a),z))
    for r in range(len(rings)-1):
        for i in range(seg):
            a=r*w+i; f.append((a,a+1,(r+1)*w+i+1,(r+1)*w+i))
    return mesh_obj(name,v,f,mat,arm,body)


def box(name,loc,scale,mat,arm,body,rot=(0,0,0),bevel=.004):
    bpy.ops.mesh.primitive_cube_add(location=loc,rotation=rot); ob=bpy.context.active_object; ob.name=name; ob.scale=scale; bpy.ops.object.transform_apply(location=False,rotation=False,scale=True); ob.data.materials.append(mat)
    b=ob.modifiers.new("Rounded edges","BEVEL"); b.width=bevel; b.segments=3; bpy.context.view_layer.objects.active=ob; bpy.ops.object.modifier_apply(modifier=b.name)
    ob.parent=arm; m=ob.modifiers.new("SiroinoSotai Armature","ARMATURE"); m.object=arm; c.transfer_nearest_body_weights(ob,body); c.add_nearest_shape_keys(ob,body); return ob


def loop(cx,cy,z,rx,ry,n=64): return [(cx+rx*math.cos(math.tau*i/n),cy+ry*math.sin(math.tau*i/n),z) for i in range(n)]


def buckle(name,center,w,h,metal,arm,body):
    x,y,z=center; ob=c.curve_tube(name,[(x-w,y,z-h),(x+w,y,z-h),(x+w,y,z+h),(x-w,y,z+h)],.0018,metal,arm,"Hips",cyclic=True,resolution=3); c.transfer_nearest_body_weights(ob,body); return ob


def outfit(body,arm,fabric,strap,metal):
    o=[]; rings=[(.775,.151,.112),(.704,.158,.120),(.660,.151,.114)]
    o += [sector("Cargo_Waist_Front",rings,math.radians(198),math.radians(342),fabric,arm,body),sector("Cargo_Waist_Back",rings,math.radians(18),math.radians(162),fabric,arm,body)]
    for side,sgn in (("L",-1),("R",1)):
        cx=sgn*.082
        o += [tube(f"Cargo_UpperLeg_{side}",[(.690,.091,.105,.002),(.615,.112,.111,0),(.525,.129,.112,-.002),(.455,.145,.108,-.004)],cx,fabric,arm,body),tube(f"Cargo_LowerLeg_{side}",[(.390,.151,.108,-.004),(.300,.166,.112,-.002),(.165,.193,.121,0),(.055,.213,.132,.006),(.018,.218,.135,.010)],cx,fabric,arm,body)]
        for k,z in enumerate((.438,.404)):
            s=c.curve_tube(f"Knee_Strap_{side}_{k+1}",loop(cx,-.004,z,.151+k*.002,.111),.0032,strap,arm,f"LowerLeg_{side}",cyclic=True,resolution=3); c.transfer_nearest_body_weights(s,body); o.append(s)
        ox=cx+sgn*.133
        o += [box(f"Cargo_Pocket_{side}",(ox,-.017,.548),(.046,.026,.067),fabric,arm,body,(0,math.radians(sgn*3),math.radians(sgn*-4)),.006),box(f"Cargo_Pocket_Flap_{side}",(ox,-.045,.606),(.051,.008,.018),strap,arm,body,(0,0,math.radians(sgn*-4)),.003)]
        pts=[(cx+sgn*.116,-.112,.442),(cx+sgn*.119,-.116,.404),(cx+sgn*.124,-.118,.360)]
        z=c.curve_tube(f"Knee_Zip_{side}",pts,.00125,metal,arm,f"LowerLeg_{side}",resolution=2); c.transfer_nearest_body_weights(z,body); o += [z,buckle(f"Knee_Zip_Pull_{side}",pts[-1],.006,.009,metal,arm,body)]
    for name,pts,r in (("Primary_Waist_Belt",loop(0,0,.784,.158,.116,72),.0042),("Asymmetric_Waist_Belt",[(.166*math.cos(math.tau*i/72),.123*math.sin(math.tau*i/72),.800+.017*math.sin(math.tau*i/72+.72)) for i in range(73)],.0033)):
        b=c.curve_tube(name,pts,r,strap,arm,"Hips",cyclic=True,resolution=3); c.transfer_nearest_body_weights(b,body); o.append(b)
    o += [buckle("Front_Belt_Buckle",(.073,-.124,.792),.017,.015,metal,arm,body),buckle("Side_Belt_Buckle",(-.143,-.050,.810),.014,.013,metal,arm,body)]
    z=c.curve_tube("Long_Center_Zipper",[(0,-.123,.772),(0,-.128,.702),(0,-.125,.618)],.00145,metal,arm,"Hips",resolution=2); c.transfer_nearest_body_weights(z,body); o += [z,buckle("Center_Zip_Pull",(0,-.130,.608),.007,.011,metal,arm,body)]
    for side,sgn in (("L",-1),("R",1)):
        for k,zv in enumerate((.754,.714)):
            b=c.curve_tube(f"Hip_Window_Bridge_{side}_{k+1}",[(sgn*.127,-.080,zv),(sgn*.170,-.002,zv-.004),(sgn*.128,.081,zv)],.0032,strap,arm,"Hips",resolution=3); c.transfer_nearest_body_weights(b,body); o.append(b)
        r=c.torus(f"Hip_Ring_{side}",(sgn*.171,-.004,.735),.010,.0019,metal,arm,"Hips"); r.rotation_euler=(math.pi/2,0,0); c.transfer_nearest_body_weights(r,body); o.append(r)
    return o


def clear(arm):
    for b in arm.pose.bones: b.rotation_mode="XYZ"; b.rotation_euler=(0,0,0); b.location=(0,0,0); b.scale=(1,1,1)
    bpy.context.view_layer.update()


def rot(arm,name,deg):
    b=arm.pose.bones.get(name)
    if b: b.rotation_mode="XYZ"; b.rotation_euler=tuple(math.radians(x) for x in deg)


def pose(arm,name):
    clear(arm)
    if name=="wide-stance": rot(arm,"UpperLeg_L",(0,0,9)); rot(arm,"UpperLeg_R",(0,0,-9))
    elif name=="walk": rot(arm,"UpperLeg_L",(20,0,1.5)); rot(arm,"LowerLeg_L",(-18,0,0)); rot(arm,"UpperLeg_R",(-16,0,-1.5)); rot(arm,"LowerLeg_R",(-4,0,0))
    elif name=="crouch":
        rot(arm,"UpperLeg_L",(48,0,6)); rot(arm,"UpperLeg_R",(48,0,-6)); rot(arm,"LowerLeg_L",(-72,0,0)); rot(arm,"LowerLeg_R",(-72,0,0))
        if arm.pose.bones.get("Hips"): arm.pose.bones["Hips"].location.z=-.10
    elif name=="sit":
        rot(arm,"UpperLeg_L",(65,0,2)); rot(arm,"UpperLeg_R",(65,0,-2)); rot(arm,"LowerLeg_L",(-65,0,0)); rot(arm,"LowerLeg_R",(-65,0,0))
        if arm.pose.bones.get("Hips"): arm.pose.bones["Hips"].location.z=-.16
    elif name=="prone": rot(arm,"UpperLeg_L",(-18,0,3)); rot(arm,"UpperLeg_R",(-18,0,-3)); rot(arm,"LowerLeg_L",(24,0,0)); rot(arm,"LowerLeg_R",(24,0,0))
    bpy.context.view_layer.update()


def render(cam,path,loc,target=(0,0,.43)):
    path.parent.mkdir(parents=True,exist_ok=True); c.point_camera(cam,loc,target); bpy.context.scene.render.filepath=str(path); bpy.ops.render.render(write_still=True)


def previews(cam,arm,views,pose_dir):
    s=bpy.context.scene; s.render.engine="CYCLES"; s.cycles.device="CPU"; s.cycles.samples=28; s.cycles.use_denoising=True; s.cycles.use_adaptive_sampling=True; s.cycles.adaptive_threshold=.045; s.render.resolution_x=1200; s.render.resolution_y=1200; s.render.resolution_percentage=100; s.render.image_settings.file_format="PNG"; s.render.image_settings.color_mode="RGBA"; s.view_settings.look="AgX - Medium High Contrast"
    clear(arm); positions={"front":(0,-2.45,.58),"back":(0,2.45,.58),"left":(2.45,0,.58),"right":(-2.45,0,.58),"three-quarter":(1.62,-1.90,.64)}
    for n,p in views.items(): render(cam,p,positions[n])
    pp={}
    for n in ("neutral","wide-stance","walk","crouch","sit","prone"):
        pose(arm,n); p=pose_dir/f"{n}.png"; render(cam,p,(1.72,-2.05,.46) if n in ("sit","crouch") else (1.62,-1.90,.64),(0,0,.40)); pp[n]=p
    clear(arm); return pp


def sheet(paths,out):
    tile=600; names=list(paths); canvas=Image.new("RGB",(tile*3,tile*math.ceil(len(names)/3)),(26,29,38)); d=ImageDraw.Draw(canvas)
    try: font=ImageFont.truetype("DejaVuSans.ttf",30)
    except OSError: font=ImageFont.load_default()
    for i,n in enumerate(names):
        im=Image.open(paths[n]).convert("RGB"); im.thumbnail((tile,tile),Image.Resampling.LANCZOS); x=i%3*tile; y=i//3*tile; canvas.paste(im,(x+(tile-im.width)//2,y)); d.rounded_rectangle((x+18,y+18,x+240,y+62),14,fill=(15,18,25)); d.text((x+30,y+24),n.upper(),fill=(245,245,248),font=font)
    out.parent.mkdir(parents=True,exist_ok=True); canvas.save(out,"WEBP",quality=94,method=6)


def main():
    job_path,j=c.load_job(); c.clean_scene(); source=rp(j["targetSourcePath"]); blend=rp(j["blendPath"]); fbx=rp(j["fbxAssetPath"]); prefab=rp(j["prefabAssetPath"]); art=rp(j["artifactDir"]); root=fbx.parents[1]; tex=root/"Textures"; pv=root/"Previews"; pd=pv/"Poses"; art.mkdir(parents=True,exist_ok=True)
    bpy.ops.import_scene.fbx(filepath=str(source),use_anim=False); body=next(x for x in bpy.context.scene.objects if x.type=="MESH" and x.name.startswith("SiroinoSotai_PC")); arm=next(x for x in bpy.context.scene.objects if x.type=="ARMATURE"); arm.name="SiroinoSotai_Armature"; c.set_skin_material(body)
    mp=maps(tex); fabric=c.textured_material("MAT_Black_Cargo_Fabric",mp["fa"],mp["fn"],mp["fr"],normal_strength=.38,sheen=.10); strap=c.textured_material("MAT_Black_Cargo_Straps",mp["sa"],mp["sn"],mp["sr"],normal_strength=.24,sheen=.04); metal=c.plain_material("MAT_Brushed_Gunmetal",(.24,.28,.34,1),roughness=.19,metallic=.94); garments=outfit(body,arm,fabric,strap,metal)
    blend.parent.mkdir(parents=True,exist_ok=True); bpy.ops.wm.save_as_mainfile(filepath=str(blend),check_existing=False); _,cam=c.studio_setup(); cam.data.ortho_scale=1.23; view={n:rp(v) for n,v in j["previewPaths"].items()}; pp=previews(cam,arm,view,pd); sheet(view,pv/"siroino-wide-cargo-multiview.webp"); sheet(pp,pv/"siroino-wide-cargo-pose-review.webp")
    clear(arm); body.hide_render=True; c.export_fbx(fbx,arm,garments); side=c.write_unity_sidecars(fbx,prefab,"SiroinoWideCargo"); m=c.metrics(garments); passed=m["meshObjects"]>=12 and m["vertices"]>=3000 and m["triangles"]>=5000 and m["unweightedVertices"]==0 and m["weightSumErrors"]==0 and m["degenerateTriangles"]==0 and m["maxBoneInfluences"]<=4
    report={"schemaVersion":1,"passed":passed,"checkedAt":now(),"productId":PID,"blenderVersion":bpy.app.version_string,"targetSource":str(source.relative_to(ROOT)).replace("\\","/"),"targetSourceSha256":digest(source),"metrics":m,"previews":{n:{"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":digest(p),"width":Image.open(p).width,"height":Image.open(p).height} for n,p in view.items()},"poses":{n:{"path":str(p.relative_to(ROOT)).replace("\\","/"),"sha256":digest(p)} for n,p in pp.items()},"design":{"originalRedesign":True,"brandMarksIncluded":False}}
    (art/"blender-product.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    readme=root/"README.md"; readme.write_text(f"# Siroino Wide Cargo\n\nOriginal logo-free wide cargo outfit for SiroinoSotai v1.0. Drag `Prefabs/Outfit/SiroinoWideCargo.prefab` under the avatar root; Modular Avatar merges the armature at build time.\n\nMetrics: {m['vertices']} vertices, {m['triangles']} triangles, {m['maxBoneInfluences']} max bone influences.\n",encoding="utf-8")
    manifest=root/"ProductManifest.json"; data=json.loads(manifest.read_text(encoding="utf-8-sig")) if manifest.exists() else {}; data.update({"schemaVersion":1,"productId":PID,"productName":"Siroino Wide Cargo","status":"MODELED" if passed else "NO-GO","targetAdapterId":"siroino-v1.0","productRoot":"Assets/GenWorks/Products/siroino-wide-cargo","outfitPrefabPath":"Assets/GenWorks/Products/siroino-wide-cargo/Prefabs/Outfit/SiroinoWideCargo.prefab","integratedPrefabPath":"Assets/GenWorks/Products/siroino-wide-cargo/Prefabs/Integrated/SiroinoSotai/SiroinoSotai_WideCargo.prefab","previewPath":"Assets/GenWorks/Products/siroino-wide-cargo/Previews/front.png","documentationPath":"Assets/GenWorks/Products/siroino-wide-cargo/README.md","sourceJobPath":"Assets/_Local/Jobs/siroino-wide-cargo/job.json","generatedAt":report["checkedAt"],"blenderVersion":report["blenderVersion"],"metrics":m}); manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    files=[blend,fbx,prefab,readme,manifest,*side,*mp.values(),*view.values(),*pp.values(),pv/"siroino-wide-cargo-multiview.webp",pv/"siroino-wide-cargo-pose-review.webp"]; (root/"SOURCE_HASHES.txt").write_text("\n".join(f"{digest(p)}  {p.relative_to(root).as_posix()}" for p in sorted(files) if p.is_file())+"\n",encoding="utf-8"); print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if passed else 2


if __name__=="__main__": raise SystemExit(main())
