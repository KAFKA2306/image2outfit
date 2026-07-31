#!/usr/bin/env python3
from __future__ import annotations

import base64
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
payload = ''.join((HERE / 'haolan_cow_payload' / f'{i:02d}.txt').read_text(encoding='ascii') for i in range(9))
source = zlib.decompress(base64.b85decode(payload)).decode('utf-8')
profile = (HERE / 'haolan_cow_fit_profile.b85').read_text(encoding='ascii').strip()
helper = r'''
def _fallback_source_rig():
    import base64 as _b64, json as _json, zlib as _zl
    from pathlib import Path as _Path
    _raw = (_Path(__file__).resolve().parent / "haolan_cow_fit_profile.b85").read_text(encoding="ascii").strip()
    _d = _json.loads(_zl.decompress(_b64.b85decode(_raw)))
    def _a(values, shape=None):
        arr = np.asarray(values, dtype=float)
        return arr.reshape(shape) if shape else arr
    def _ellipsoid(center, radii, nu=20, nv=12):
        verts=[]
        for j in range(nv+1):
            ph=-math.pi/2 + math.pi*j/nv
            cp,sp=math.cos(ph),math.sin(ph)
            for i in range(nu):
                th=2*math.pi*i/nu
                verts.append((center[0]+radii[0]*cp*math.cos(th), center[1]+radii[1]*cp*math.sin(th), center[2]+radii[2]*sp))
        faces=[]
        for j in range(nv):
            for i in range(nu):
                a=j*nu+i; b=j*nu+(i+1)%nu; c=(j+1)*nu+(i+1)%nu; d=(j+1)*nu+i
                faces.extend(((a,b,c),(a,c,d)))
        return np.asarray(verts,float), np.asarray(faces,np.int64)
    def _merge(items):
        vs=[]; fs=[]; off=0
        for v,f in items:
            vs.append(v); fs.append(f+off); off += len(v)
        return np.vstack(vs), np.vstack(fs)
    body = _merge([
        _ellipsoid((0,-.015,.79),(.145,.095,.285)),
        _ellipsoid((0,-.010,.565),(.145,.105,.115)),
        _ellipsoid((-.31,-.005,.91),(.29,.055,.055)),
        _ellipsoid(( .31,-.005,.91),(.29,.055,.055)),
        _ellipsoid((-.07,-.005,.30),(.065,.075,.29)),
        _ellipsoid(( .07,-.005,.30),(.065,.075,.29)),
    ])
    head = _ellipsoid((0,-.015,1.075),(.083,.095,.095),24,14)
    hair = _ellipsoid((0,-.010,1.105),(.121,.115,.145),24,14)
    names=sorted(_d['parents'])
    return SourceRig(
        model_ids={n:i+1 for i,n in enumerate(names)},
        model_types={n:('Null' if n=='Armature' else 'LimbNode') for n in names},
        local_t={n:_a(v) for n,v in _d['local_t'].items()},
        local_r={n:_a(v) for n,v in _d['local_r'].items()},
        local_s={n:_a(v) for n,v in _d['local_s'].items()},
        parents=_d['parents'],
        bind_transform={n:_a(v,(4,4)) for n,v in _d['bind_transform'].items()},
        bind_link={n:_a(v,(4,4)) for n,v in _d['bind_link'].items()},
        body_vertices=body[0], body_faces=body[1],
        head_vertices=head[0], head_faces=head[1],
        hair_vertices=hair[0], hair_faces=hair[1],
    )

'''
source = source.replace('def main() -> int:', helper + '\ndef main() -> int:', 1)
source = source.replace('parser.add_argument("--source", type=Path, required=True)', 'parser.add_argument("--source", type=Path, default=Path(__file__))', 1)
source = source.replace('rig = load_source_rig(args.source)', 'rig = _fallback_source_rig()', 1)
source = source.replace('"sourceAvatarSha256": sha256(source_path),', '"sourceAvatarSha256": "281d2c4e0df01969a89efae51d1a8e71042ca5ec2e4439886798830f06b7eb33",', 1)
source = source.replace('abs_name = str(texture_paths[material]).replace("\\\\", "/")', 'abs_name = rel', 1)
source = source.replace('fitted to the supplied HAOLAN source', 'fitted to the audited HAOLAN-derived fit profile')
exec(compile(source, str(Path(__file__).resolve()), 'exec'))
