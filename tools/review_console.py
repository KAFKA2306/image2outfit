#!/usr/bin/env python3
"""Generate and optionally serve a read-only image2outfit review console.

The console reads canonical product manifests, release policy, preview images, and
review/evidence files. It never mutates product workspaces or executes release
commands.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import socketserver
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Iterable

DEFAULT_VIEWS = ("front", "back", "left", "right", "three-quarter")
PRODUCT_STATES = (
    "WORKING",
    "TECHNICAL_READY",
    "HUMAN_REVIEW_PENDING",
    "REJECTED",
    "RELEASED",
)


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return default


def first(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_url(path: Path, output_dir: Path) -> str:
    return Path(os.path.relpath(path, output_dir)).as_posix()


def severity(item: Any) -> str:
    if isinstance(item, dict):
        return str(first(item, "severity", "level", "priority", default="UNKNOWN")).upper()
    return "UNKNOWN"


def issue_message(item: Any) -> str:
    if isinstance(item, dict):
        return str(first(item, "message", "title", "name", "reason", "description", default=item))
    return str(item)


def is_open_issue(item: Any) -> bool:
    if not isinstance(item, dict):
        return True
    status = str(first(item, "status", "state", "resolution", default="open")).lower()
    return status not in {"closed", "resolved", "fixed", "passed", "pass", "done"}


def manifest_state(manifest: dict[str, Any]) -> str:
    state = str(first(manifest, "state", "status", "product_state", "release_state", default="WORKING")).upper()
    return state if state in PRODUCT_STATES else "WORKING"


def release_requirements(policy: dict[str, Any]) -> tuple[list[str], list[str]]:
    views = first(policy, "required_views", "views", default=DEFAULT_VIEWS)
    poses = first(policy, "required_poses", "poses", default=[])
    if isinstance(views, dict):
        views = views.get("required", DEFAULT_VIEWS)
    if isinstance(poses, dict):
        poses = poses.get("required", [])
    return [str(value) for value in as_list(views)], [str(value) for value in as_list(poses)]


@dataclass
class AssetRecord:
    kind: str
    name: str
    status: str
    path: str | None
    sha256: str | None


@dataclass
class ProductRecord:
    slug: str
    state: str
    updated_at: str
    blocker_count: int
    blockers: list[dict[str, str]]
    resume_point: str
    candidate_hash: str
    human_review_url: str
    workspace: str
    manifest_path: str
    assets: list[AssetRecord]
    gates: list[dict[str, str]]
    evidence: list[dict[str, str]]


def find_image(base: Path, name: str) -> Path | None:
    candidates = [
        base / f"{name}.png",
        base / f"{name}.webp",
        base / f"{name}.jpg",
        base / f"{name}.jpeg",
        base / f"{name.replace('-', '_')}.png",
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def gate_rows(manifest: dict[str, Any]) -> list[dict[str, str]]:
    raw = first(manifest, "gates", "gate_results", "checks", "validation", default=[])
    rows: list[dict[str, str]] = []
    if isinstance(raw, dict):
        raw = [{"name": key, **(value if isinstance(value, dict) else {"status": value})} for key, value in raw.items()]
    for index, item in enumerate(as_list(raw), start=1):
        if isinstance(item, dict):
            rows.append(
                {
                    "name": str(first(item, "name", "gate", "check", default=f"gate-{index}")),
                    "status": str(first(item, "status", "result", "state", default="UNKNOWN")).upper(),
                    "detail": str(first(item, "message", "reason", "detail", default="")),
                }
            )
        else:
            rows.append({"name": f"gate-{index}", "status": str(item).upper(), "detail": ""})
    return rows


def evidence_rows(manifest: dict[str, Any], workspace: Path, output_dir: Path) -> list[dict[str, str]]:
    raw = as_list(first(manifest, "evidence", "artifacts", "proof", "review_evidence", default=[]))
    rows: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            path_value = first(item, "path", "file", "url")
            label = str(first(item, "label", "title", "name", "type", default=f"evidence-{index}"))
            status = str(first(item, "status", "state", "result", default="UNKNOWN")).upper()
        else:
            path_value, label, status = item, f"evidence-{index}", "UNKNOWN"
        path_text = str(path_value or "")
        target = workspace / path_text if path_text and not path_text.startswith(("http://", "https://")) else None
        href = (
            path_text
            if path_text.startswith(("http://", "https://"))
            else relative_url(target, output_dir)
            if target and target.exists()
            else ""
        )
        rows.append({"label": label, "status": status, "href": href})
    return rows


def collect_product(
    workspace: Path,
    output_dir: Path,
    required_views: list[str],
    required_poses: list[str],
) -> ProductRecord:
    manifest_path = workspace / "ProductManifest.json"
    manifest = load_json(manifest_path, {})
    issues = []
    for item in as_list(first(manifest, "blockers", "defects", "issues", "findings", default=[])):
        if is_open_issue(item):
            issues.append({"severity": severity(item), "message": issue_message(item)})
    previews = workspace / "Previews"
    assets: list[AssetRecord] = []
    for view in required_views:
        path = find_image(previews, view)
        assets.append(
            AssetRecord(
                kind="view",
                name=view,
                status="PASS" if path else "MISSING",
                path=relative_url(path, output_dir) if path else None,
                sha256=sha256(path) if path else None,
            )
        )
    pose_dir = previews / "Poses"
    for pose in required_poses:
        path = find_image(pose_dir, pose)
        assets.append(
            AssetRecord(
                kind="pose",
                name=pose,
                status="PASS" if path else "MISSING",
                path=relative_url(path, output_dir) if path else None,
                sha256=sha256(path) if path else None,
            )
        )

    candidate = first(manifest, "candidate", "candidate_manifest", default={})
    review = first(manifest, "human_review", "review", default={})
    updated = first(manifest, "updated_at", "last_updated", "generated_at")
    if not updated and manifest_path.exists():
        updated = datetime.fromtimestamp(manifest_path.stat().st_mtime, timezone.utc).isoformat()
    return ProductRecord(
        slug=workspace.name,
        state=manifest_state(manifest),
        updated_at=str(updated or "UNKNOWN"),
        blocker_count=len(issues),
        blockers=issues,
        resume_point=str(first(manifest, "resume_point", "restart_from", "next_action", "resume_from", default="未登録")),
        candidate_hash=str(first(candidate if isinstance(candidate, dict) else {}, "sha256", "hash", "candidate_hash", default=first(manifest, "candidate_hash", default="UNKNOWN"))),
        human_review_url=str(first(review if isinstance(review, dict) else {}, "url", "pr_review_url", "review_url", default=first(manifest, "human_review_url", default=""))),
        workspace=relative_url(workspace, output_dir),
        manifest_path=relative_url(manifest_path, output_dir),
        assets=assets,
        gates=gate_rows(manifest),
        evidence=evidence_rows(manifest, workspace, output_dir),
    )


CSS = r"""
:root{--bg:#11131a;--surface:#1b1e28;--surface2:#242837;--ink:#f3f5f9;--muted:#adb6c7;--line:rgba(255,255,255,.16);--accent:#8bdcff;--pass:#9ce9bc;--fail:#ef9faa;--warn:#ffd37a;font-family:Inter,"Noto Sans JP",system-ui,sans-serif}*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:90px}body{margin:0;color:var(--ink);background:radial-gradient(circle at 7% 0,rgba(55,112,175,.25),transparent 30rem),var(--bg);font-size:16px;line-height:1.6}a{color:inherit}button,input,select{font:inherit;min-height:44px}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,[tabindex="-1"]:focus-visible{outline:3px solid var(--accent);outline-offset:3px}.skip{position:fixed;top:8px;left:8px;z-index:1000;padding:11px 15px;border-radius:10px;background:#fff;color:#11131a;transform:translateY(-150%)}.skip:focus{transform:translateY(0)}header{position:sticky;top:0;z-index:40;display:flex;justify-content:space-between;align-items:center;gap:18px;padding:12px max(16px,calc((100% - 1320px)/2));border-bottom:1px solid var(--line);background:rgba(17,19,26,.94);backdrop-filter:blur(18px)}.brand{font-weight:900}.brand span{color:var(--accent)}header nav{display:flex;flex-wrap:wrap;gap:5px}header a{display:inline-flex;min-height:44px;align-items:center;padding:8px 10px;border-radius:999px;text-decoration:none;color:var(--muted);font-weight:800}main{width:min(1320px,calc(100% - 28px));margin:auto;padding:44px 0}.hero{display:grid;grid-template-columns:1.25fr .75fr;gap:22px;align-items:end}.eyebrow{margin:0 0 8px;color:var(--accent);font-size:12px;font-weight:900;letter-spacing:.12em}h1{margin:0;max-width:15ch;font-size:clamp(44px,7vw,76px);line-height:.98;letter-spacing:-.06em}.hero p:last-child{max-width:760px;color:var(--muted)}.hero aside,.controls,.product-list,.product-detail{border:1px solid var(--line);border-radius:20px;background:rgba(27,30,40,.94);box-shadow:0 22px 60px rgba(0,0,0,.32)}.hero aside{padding:20px}.hero aside strong,.hero aside span{display:block}.hero aside span{color:var(--muted)}.controls{display:grid;grid-template-columns:1.6fr .8fr .8fr auto;gap:10px;align-items:end;margin-top:24px;padding:15px}.controls label{display:grid;gap:5px;color:var(--muted);font-size:12px;font-weight:800}.controls input,.controls select{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:10px;background:var(--surface2);color:var(--ink)}.controls button{padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--surface2);color:var(--ink);cursor:pointer;font-weight:800}.workspace{display:grid;grid-template-columns:340px minmax(0,1fr);gap:15px;margin-top:16px;align-items:start}.product-list,.product-detail{padding:16px}.product-list{position:sticky;top:76px;max-height:calc(100dvh - 92px);overflow-y:auto}.product-list h2,.product-detail h2{margin:0}.product-buttons{display:grid;gap:7px;margin-top:12px}.product-button{display:grid;grid-template-columns:1fr auto;gap:6px;padding:10px;border:1px solid var(--line);border-radius:11px;background:var(--surface2);color:var(--ink);cursor:pointer;text-align:left}.product-button[aria-current="true"]{border-color:var(--accent);box-shadow:0 0 0 2px rgba(139,220,255,.2)}.product-button small{grid-column:1/-1;color:var(--muted)}.state,.gate-status,.asset-status{display:inline-flex;min-height:28px;align-items:center;padding:4px 8px;border:1px solid currentColor;border-radius:999px;font-size:11px;font-weight:900}.state-WORKING{color:var(--warn)}.state-TECHNICAL_READY,.state-RELEASED{color:var(--pass)}.state-HUMAN_REVIEW_PENDING{color:var(--accent)}.state-REJECTED{color:var(--fail)}.detail-head{display:flex;justify-content:space-between;gap:18px;align-items:start}.detail-head p{margin:5px 0;color:var(--muted)}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:15px 0}.summary-grid div,.gate-card,.evidence-card{padding:10px;border-radius:10px;background:var(--surface2)}.summary-grid dt{color:var(--muted);font-size:11px;font-weight:850}.summary-grid dd{margin:3px 0 0;overflow-wrap:anywhere}.section{margin-top:22px;padding-top:17px;border-top:1px solid var(--line)}.section-head{display:flex;justify-content:space-between;align-items:end;gap:14px;margin-bottom:10px}.section-head h3{margin:0}.image-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.image-card{position:relative;overflow:hidden;border:1px solid var(--line);border-radius:13px;background:var(--surface2)}.image-card img{width:100%;aspect-ratio:1;object-fit:contain;display:block;background:#101219}.image-card button{position:absolute;inset:0;border:0;background:transparent;color:transparent;cursor:zoom-in}.image-meta{display:flex;justify-content:space-between;gap:8px;padding:8px;color:var(--muted);font-size:12px}.asset-status-PASS,.gate-status-PASS{color:var(--pass)}.asset-status-MISSING,.gate-status-FAIL,.gate-status-FAILED{color:var(--fail)}.gate-grid,.evidence-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.gate-card strong,.gate-card span,.gate-card small{display:block}.gate-card span,.gate-card small{color:var(--muted)}.blocker-list{margin:0;padding-left:22px}.blocker-list li+li{margin-top:5px}.evidence-card a{display:inline-flex;min-height:40px;align-items:center;color:var(--accent);font-weight:800}.empty{padding:34px;text-align:center;color:var(--muted)}.viewer{position:fixed;inset:0;z-index:100;display:grid;place-items:center;padding:20px;background:rgba(0,0,0,.88)}.viewer[hidden]{display:none}.viewer img{max-width:min(92vw,1200px);max-height:82vh;object-fit:contain}.viewer-controls{position:absolute;top:15px;right:15px;display:flex;gap:6px}.viewer button{padding:8px 12px;border:1px solid var(--line);border-radius:9px;background:var(--surface2);color:var(--ink);cursor:pointer}.viewer-caption{position:absolute;bottom:14px;left:50%;transform:translateX(-50%);padding:7px 11px;border-radius:999px;background:var(--surface2)}footer{width:min(1320px,calc(100% - 28px));margin:auto;padding:22px 0;border-top:1px solid var(--line);color:var(--muted)}@media(max-width:980px){.hero{grid-template-columns:1fr}.workspace{grid-template-columns:1fr}.product-list{position:static;max-height:none}.product-buttons{grid-template-columns:repeat(2,1fr)}.summary-grid{grid-template-columns:1fr 1fr}.image-grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){header{position:static;align-items:flex-start;flex-direction:column}.controls,.product-buttons,.summary-grid,.image-grid,.gate-grid,.evidence-grid{grid-template-columns:1fr}.workspace{margin-top:10px}.detail-head{flex-direction:column}main{width:min(100% - 18px,1320px);padding-top:30px}h1{font-size:43px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
"""

JS = r"""
(()=>{'use strict';const DATA=window.REVIEW_CONSOLE_DATA;const state={q:'',status:'all',blockers:'all',slug:new URLSearchParams(location.search).get('product')||'',assetIndex:0};const $=s=>document.querySelector(s);const esc=(v='')=>String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'})[c]);const records=DATA.products||[];const bySlug=s=>records.find(r=>r.slug===s);function filtered(){const q=state.q.toLowerCase();return records.filter(r=>(!q||`${r.slug} ${r.state} ${r.resume_point} ${r.blockers.map(b=>b.message).join(' ')}`.toLowerCase().includes(q))&&(state.status==='all'||r.state===state.status)&&(state.blockers==='all'||(state.blockers==='yes'?r.blocker_count>0:r.blocker_count===0)))}function writeUrl(){const p=new URLSearchParams;if(state.slug)p.set('product',state.slug);history.replaceState(null,'',`${location.pathname}${p.size?`?${p}`:''}`)}function renderList(){const list=filtered();$('#product-count').textContent=`${list.length}件 / 全${records.length}件`;$('#products').innerHTML=list.length?list.map(r=>`<button class="product-button" type="button" data-product="${esc(r.slug)}" aria-current="${r.slug===state.slug}"><strong>${esc(r.slug)}</strong><span class="state state-${r.state}">${esc(r.state)}</span><small>blocker ${r.blocker_count} · ${esc(r.updated_at)}</small></button>`).join(''):'<div class="empty">条件に一致する製品がありません。</div>';$('#products').querySelectorAll('[data-product]').forEach(b=>b.addEventListener('click',()=>{state.slug=b.dataset.product;writeUrl();renderList();renderDetail();$('#detail').focus()}))}function statusBadge(status,kind='gate'){return`<span class="${kind}-status ${kind}-status-${esc(status)}">${esc(status)}</span>`}function renderDetail(){const r=bySlug(state.slug);$('#detail-empty').hidden=Boolean(r);$('#detail-content').hidden=!r;if(!r)return;$('#title').textContent=r.slug;$('#state').className=`state state-${r.state}`;$('#state').textContent=r.state;$('#updated').textContent=`最終更新 ${r.updated_at}`;const values={blockers:r.blocker_count,resume:r.resume_point,hash:r.candidate_hash,review:r.human_review_url||'未登録'};for(const[k,v]of Object.entries(values))$(`[data-summary="${k}"]`).textContent=v;$('#blockers-list').innerHTML=r.blockers.length?r.blockers.map(b=>`<li><strong>${esc(b.severity)}</strong> ${esc(b.message)}</li>`).join(''):'<li>未解決blockerなし</li>';const assets=r.assets||[];$('#asset-count').textContent=`${assets.filter(a=>a.status==='PASS').length}/${assets.length} available`;$('#images').innerHTML=assets.length?assets.map((a,i)=>`<article class="image-card"><div>${a.path?`<img src="${esc(a.path)}" alt="${esc(r.slug)} ${esc(a.kind)} ${esc(a.name)}">`:'<div class="empty">画像なし</div>'}<button type="button" data-viewer="${i}" aria-label="${esc(a.name)}を拡大"></button></div><div class="image-meta"><span>${esc(a.kind)} / ${esc(a.name)}</span>${statusBadge(a.status,'asset')}</div></article>`).join(''):'<div class="empty">required assetなし</div>';$('#images').querySelectorAll('[data-viewer]').forEach(b=>b.addEventListener('click',()=>openViewer(Number(b.dataset.viewer))));$('#gates').innerHTML=r.gates.length?r.gates.map(g=>`<article class="gate-card"><strong>${esc(g.name)}</strong>${statusBadge(g.status)}<span>${esc(g.detail)}</span></article>`).join(''):'<div class="empty">gate結果なし</div>';$('#evidence-grid').innerHTML=r.evidence.length?r.evidence.map(e=>`<article class="evidence-card"><strong>${esc(e.label)}</strong>${statusBadge(e.status)}${e.href?`<a href="${esc(e.href)}">証拠を開く →</a>`:'<span>リンクなし</span>'}</article>`).join(''):'<div class="empty">証拠なし</div>'}function openViewer(index){const r=bySlug(state.slug),assets=(r?.assets||[]).filter(a=>a.path);if(!assets.length)return;state.assetIndex=Math.max(0,Math.min(index,assets.length-1));const a=assets[state.assetIndex];$('#viewer-image').src=a.path;$('#viewer-image').alt=`${r.slug} ${a.kind} ${a.name}`;$('#viewer-caption').textContent=`${a.kind} / ${a.name} / ${a.status}`;$('#viewer').hidden=false;$('#viewer-close').focus()}function moveViewer(delta){const r=bySlug(state.slug),assets=(r?.assets||[]).filter(a=>a.path);if(!assets.length)return;state.assetIndex=(state.assetIndex+delta+assets.length)%assets.length;openViewer(state.assetIndex)}function bind(){$('#q').addEventListener('input',e=>{state.q=e.target.value;renderList()});$('#status-filter').addEventListener('change',e=>{state.status=e.target.value;renderList()});$('#blocker-filter').addEventListener('change',e=>{state.blockers=e.target.value;renderList()});$('#clear').addEventListener('click',()=>{state.q='';state.status='all';state.blockers='all';$('#q').value='';$('#status-filter').value='all';$('#blocker-filter').value='all';renderList();$('#q').focus()});$('#viewer-close').addEventListener('click',()=>{$('#viewer').hidden=true});$('#viewer-prev').addEventListener('click',()=>moveViewer(-1));$('#viewer-next').addEventListener('click',()=>moveViewer(1));document.addEventListener('keydown',e=>{if($('#viewer').hidden)return;if(e.key==='Escape')$('#viewer-close').click();if(e.key==='ArrowLeft')moveViewer(-1);if(e.key==='ArrowRight')moveViewer(1)});window.addEventListener('popstate',()=>{state.slug=new URLSearchParams(location.search).get('product')||'';renderList();renderDetail()})}function init(){for(const s of DATA.states||[]){const o=document.createElement('option');o.value=s;o.textContent=s;$('#status-filter').append(o)}if(!state.slug||!bySlug(state.slug))state.slug=records[0]?.slug||'';$('#generated').textContent=`Generated ${DATA.generated_at}`;$('#policy').textContent=`Required views ${DATA.required_views.length} / poses ${DATA.required_poses.length}`;bind();renderList();renderDetail();writeUrl()}init()})();
"""


def render_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\/")
    return f"""<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"description\" content=\"製品状態、blocker、必須画像、gate、証拠を一画面で確認するimage2outfit読み取り専用レビューコンソール。\"><title>image2outfit Review Console</title><style>{CSS}</style></head><body><a class=\"skip\" href=\"#products\">製品一覧へ移動</a><header><a class=\"brand\" href=\"../../../README.md\">image2outfit <span>REVIEW CONSOLE</span></a><nav><a href=\"#products\">製品</a><a href=\"#assets\">画像</a><a href=\"#gates-section\">ゲート</a><a href=\"#evidence\">証拠</a></nav></header><main><section class=\"hero\"><div><p class=\"eyebrow\">READ ONLY · RELEASE EVIDENCE</p><h1>候補、blocker、画像、証拠を同じ画面で見る。</h1><p>正準ProductManifestとrelease-policyを読み取り、破壊的操作を実行せずにrelease前の欠損を確認します。</p></div><aside><strong id=\"generated\"></strong><span id=\"policy\"></span></aside></section><section class=\"controls\"><label><span>製品・blockerを検索</span><input id=\"q\" type=\"search\"></label><label><span>状態</span><select id=\"status-filter\"><option value=\"all\">すべて</option></select></label><label><span>blocker</span><select id=\"blocker-filter\"><option value=\"all\">すべて</option><option value=\"yes\">あり</option><option value=\"no\">なし</option></select></label><button id=\"clear\" type=\"button\">条件解除</button></section><div class=\"workspace\"><section class=\"product-list\" id=\"products\"><div class=\"section-head\"><h2>製品</h2><span id=\"product-count\"></span></div><div class=\"product-buttons\" id=\"products\"></div></section><section class=\"product-detail\" id=\"detail\" tabindex=\"-1\"><div class=\"empty\" id=\"detail-empty\">製品がありません。</div><div id=\"detail-content\" hidden><div class=\"detail-head\"><div><p class=\"eyebrow\">PRODUCT REVIEW</p><h2 id=\"title\"></h2><p id=\"updated\"></p></div><span id=\"state\" class=\"state\"></span></div><dl class=\"summary-grid\"><div><dt>blocker</dt><dd data-summary=\"blockers\"></dd></div><div><dt>再開地点</dt><dd data-summary=\"resume\"></dd></div><div><dt>candidate hash</dt><dd data-summary=\"hash\"></dd></div><div><dt>human review</dt><dd data-summary=\"review\"></dd></div></dl><section class=\"section\"><div class=\"section-head\"><h3>未解決blocker</h3></div><ul class=\"blocker-list\" id=\"blockers-list\"></ul></section><section class=\"section\" id=\"assets\"><div class=\"section-head\"><h3>必須ビュー・ポーズ</h3><span id=\"asset-count\"></span></div><div class=\"image-grid\" id=\"images\"></div></section><section class=\"section\" id=\"gates-section\"><div class=\"section-head\"><h3>release gate</h3></div><div class=\"gate-grid\" id=\"gates\"></div></section><section class=\"section\" id=\"evidence\"><div class=\"section-head\"><h3>証拠</h3></div><div class=\"evidence-grid\" id=\"evidence-grid\"></div></section></div></section></div></main><div class=\"viewer\" id=\"viewer\" hidden><img id=\"viewer-image\" alt=\"\"><div class=\"viewer-controls\"><button id=\"viewer-prev\" type=\"button\">前</button><button id=\"viewer-next\" type=\"button\">次</button><button id=\"viewer-close\" type=\"button\">閉じる</button></div><span class=\"viewer-caption\" id=\"viewer-caption\"></span></div><footer>image2outfit Review Console · 読み取り専用。release操作は既存gateを使用してください。</footer><script>window.REVIEW_CONSOLE_DATA={payload};</script><script>{JS}</script></body></html>"""


def build(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    policy = load_json(root / "config" / "release-policy.json", {})
    required_views, required_poses = release_requirements(policy)
    products_root = root / "Assets" / "GenWorks"
    products = []
    if products_root.is_dir():
        for workspace in sorted(products_root.iterdir()):
            if workspace.is_dir() and (workspace / "ProductManifest.json").is_file():
                products.append(collect_product(workspace, output, required_views, required_poses))
    data = {
        "schema_version": "review-console.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "states": list(PRODUCT_STATES),
        "required_views": required_views,
        "required_poses": required_poses,
        "products": [asdict(product) for product in products],
    }
    (output / "review-console.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "index.html").write_text(render_html(data), encoding="utf-8")
    return data


def serve(root: Path, port: int) -> None:
    os.chdir(root)
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), SimpleHTTPRequestHandler) as server:
        print(f"Review console: http://127.0.0.1:{port}/.image2outfit/review-console/")
        server.serve_forever()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path(".image2outfit/review-console"))
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    data = build(root, output)
    print(f"review_console=PASS products={len(data['products'])} output={output}")
    if args.serve:
        serve(root, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
