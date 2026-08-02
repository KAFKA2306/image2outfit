#!/usr/bin/env python3
"""Materialize the reusable CC0 Siroino _Large fit snapshot in Blender."""
from __future__ import annotations
import base64,json,zlib
from pathlib import Path
import bpy
from mathutils import Matrix

def materialize(manifest_path: Path):
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    encoded=''.join((manifest_path.parent/part).read_text(encoding='ascii').strip() for part in manifest['parts'])
    data=json.loads(zlib.decompress(base64.b85decode(encoded.encode('ascii'))))
    mesh=bpy.data.meshes.new('SiroinoSotai_Large_Baked_Mesh')
    mesh.from_pydata(data['v'],[],data['f']);mesh.update(calc_edges=True)
    body=bpy.data.objects.new('SiroinoSotai_Large_ValidationBody',mesh);bpy.context.collection.objects.link(body)
    arm_data=bpy.data.armatures.new('SiroinoSotai_Armature_Data');arm=bpy.data.objects.new('SiroinoSotai_Armature',arm_data);bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active=arm;arm.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
    made={}
    for spec in data['b']:
        eb=arm_data.edit_bones.new(spec['n']);eb.matrix=Matrix([spec['m'][i:i+4] for i in range(0,16,4)]);eb.length=spec['l'];eb.use_deform=bool(spec['d']);made[spec['n']]=eb
    for spec in data['b']:
        if spec['p']: made[spec['n']].parent=made[spec['p']]
    bpy.ops.object.mode_set(mode='OBJECT');arm.select_set(False)
    groups=[body.vertex_groups.new(name=n) for n in data['g']]
    for vid,assignments in data['w']:
        for gid,weight in assignments: groups[gid].add([vid],float(weight),'REPLACE')
    body.parent=arm
    mod=body.modifiers.new('SiroinoSotai Armature','ARMATURE');mod.object=arm;mod.use_deform_preserve_volume=True
    return body,arm
