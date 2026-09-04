#!/usr/bin/env python3
"""Generate and optionally serve the canonical read-only review console."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socketserver
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from image2outfit import improvement  # noqa: E402

STATES = (
    "WORKING",
    "COMPLETE",
    "REJECTED",
)
DEFAULT_VIEWS = ("front", "back", "left", "right", "three-quarter")
IMAGE_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def pick(mapping: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def status_text(value: Any) -> str:
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    normalized = str(value or "UNKNOWN").strip().upper()
    return {
        "PASSED": "PASS",
        "SUCCESS": "PASS",
        "SUCCEEDED": "PASS",
        "TRUE": "PASS",
        "FAILED": "FAIL",
        "ERROR": "FAIL",
        "FALSE": "FAIL",
    }.get(normalized, normalized)


def relative_href(path: Path, output_dir: Path) -> str:
    return Path(os.path.relpath(path, output_dir)).as_posix()


def safe_state(manifest: dict[str, Any]) -> str:
    state = str(
        pick(
            manifest,
            "state",
            "status",
            "product_state",
            "release_state",
            default="WORKING",
        )
    ).upper()
    return state if state in STATES else "WORKING"


def policy_requirements(policy: dict[str, Any]) -> tuple[list[str], list[str]]:
    minimum_preview = pick(policy, "minimumPreview", "minimum_preview", default={})
    views: Any = pick(
        policy,
        "required_views",
        "views",
        default=pick(
            minimum_preview,
            "requiredViews",
            "required_views",
            default=list(DEFAULT_VIEWS),
        ),
    )
    poses: Any = pick(
        policy,
        "requiredPoses",
        "required_poses",
        "poses",
        default=[],
    )
    if isinstance(views, dict):
        views = pick(views, "required", "names", default=list(DEFAULT_VIEWS))
    if isinstance(poses, dict):
        poses = pick(poses, "required", "names", default=[])
    return [str(item) for item in as_list(views)], [
        str(item) for item in as_list(poses)
    ]


def locate_image(directory: Path, name: str) -> Path | None:
    stems = (name, name.replace("_", "-"), name.replace("-", "_"))
    for stem in stems:
        for suffix in IMAGE_SUFFIXES:
            candidate = directory / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def image_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def preview_directory(workspace: Path) -> tuple[Path, str]:
    current = workspace / "Previews"
    if image_files(current):
        return current, "current-preview"

    rejected = workspace / "Evidence" / "Rejected"
    candidates: list[Path] = []
    if rejected.is_dir():
        for preview_root in rejected.glob("*/Previews"):
            if image_files(preview_root):
                candidates.append(preview_root)
    if candidates:
        return sorted(candidates)[-1], "rejected-preview"
    return current, "current-preview"


def open_issue(item: Any) -> bool:
    if not isinstance(item, dict):
        return True
    state = str(pick(item, "state", "status", "resolution", default="open")).lower()
    return state not in {"closed", "resolved", "fixed", "done", "pass", "passed"}


def issue_severity(item: Any) -> str:
    if not isinstance(item, dict):
        return "UNKNOWN"
    return str(pick(item, "severity", "level", "priority", default="UNKNOWN")).upper()


def issue_message(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item)
    return str(
        pick(
            item,
            "message",
            "title",
            "name",
            "reason",
            "description",
            default="未記載",
        )
    )


@dataclass(frozen=True)
class Asset:
    kind: str
    name: str
    status: str
    href: str | None
    sha256: str | None


@dataclass(frozen=True)
class Gate:
    name: str
    status: str
    detail: str
    href: str | None


@dataclass(frozen=True)
class Evidence:
    label: str
    status: str
    href: str | None
    sha256: str | None


@dataclass(frozen=True)
class Product:
    slug: str
    state: str
    updated_at: str
    blocker_count: int
    blockers: list[dict[str, str]]
    resume_point: str
    candidate_hash: str
    human_review_url: str
    manifest_href: str
    assets: list[Asset]
    gates: list[Gate]
    evidence: list[Evidence]


def parse_gate_rows(
    manifest: dict[str, Any], workspace: Path, output_dir: Path
) -> list[Gate]:
    raw: Any = pick(
        manifest,
        "technicalGates",
        "gates",
        "gate_results",
        "checks",
        "validation",
        default=[],
    )
    if isinstance(raw, dict):
        raw = [
            {"name": name, **(value if isinstance(value, dict) else {"status": value})}
            for name, value in raw.items()
        ]
    result: list[Gate] = []
    for index, item in enumerate(as_list(raw), start=1):
        if isinstance(item, dict):
            name = str(pick(item, "name", "gate", "check", default=f"gate-{index}"))
            status = status_text(pick(item, "status", "result", "state", "passed"))
            detail = str(pick(item, "message", "reason", "detail", default=""))
            raw_path = pick(item, "path", "file", "log")
        else:
            name, status, detail, raw_path = (
                f"gate-{index}",
                status_text(item),
                "",
                None,
            )
        href = None
        if raw_path:
            target = workspace / str(raw_path)
            href = relative_href(target, output_dir) if target.exists() else None
        result.append(Gate(name=name, status=status, detail=detail, href=href))
    return result


def parse_evidence_rows(
    manifest: dict[str, Any], workspace: Path, output_dir: Path
) -> list[Evidence]:
    raw = as_list(
        pick(manifest, "evidence", "artifacts", "proof", "review_evidence", default=[])
    )
    result: list[Evidence] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            label = str(
                pick(
                    item, "label", "title", "name", "type", default=f"evidence-{index}"
                )
            )
            status = status_text(pick(item, "status", "state", "result"))
            raw_target = pick(item, "url", "href", "path", "file")
            expected_hash = pick(item, "sha256", "hash")
        else:
            label, status, raw_target, expected_hash = (
                f"evidence-{index}",
                "UNKNOWN",
                item,
                None,
            )
        href = None
        actual_hash = None
        if raw_target:
            text = str(raw_target)
            if text.startswith(("https://", "http://")):
                href = text
            else:
                target = workspace / text
                if target.exists():
                    href = relative_href(target, output_dir)
                    actual_hash = digest(target)
        if expected_hash and actual_hash and str(expected_hash) != actual_hash:
            status = "HASH_MISMATCH"
        result.append(
            Evidence(
                label=label,
                status=status,
                href=href,
                sha256=actual_hash or str(expected_hash or "") or None,
            )
        )
    return result


def parse_quality_projection(
    root: Path, slug: str, output_dir: Path
) -> tuple[list[dict[str, str]], list[Gate], list[Evidence], str | None]:
    report_path = (
        root / ".image2outfit" / "products" / slug / "reports" / "customer-quality.json"
    )
    document = load_json(report_path, {})
    evidence_root = document.get("evidence") if isinstance(document, dict) else None
    quality = (
        evidence_root.get("qualitySpec") if isinstance(evidence_root, dict) else None
    )
    if not isinstance(quality, dict):
        return [], [], [], None

    report_href = (
        relative_href(report_path, output_dir) if report_path.is_file() else None
    )
    blockers: list[dict[str, str]] = []
    for defect in as_list(quality.get("defects")):
        if not isinstance(defect, dict):
            continue
        reasons = "; ".join(str(item) for item in as_list(defect.get("reasons")))
        message = " · ".join(
            value
            for value in (
                str(defect.get("code") or "QUALITY_DEFECT"),
                str(defect.get("aspect") or "unknown-aspect"),
                reasons,
                f"return {defect.get('recommendedReturnStage')}"
                if defect.get("recommendedReturnStage")
                else "",
            )
            if value
        )
        blockers.append({"severity": "QUALITY", "message": message})

    gates: list[Gate] = []
    aspects = quality.get("aspects")
    if isinstance(aspects, dict):
        for aspect_id, row in aspects.items():
            if not isinstance(row, dict):
                continue
            detail: list[str] = []
            metric = row.get("metric")
            if isinstance(metric, dict):
                detail.append(
                    f"{metric.get('name')}={metric.get('value')} "
                    f"{metric.get('operator')} {metric.get('threshold')}"
                )
            if row.get("recommendedReturnStage"):
                detail.append(f"return {row['recommendedReturnStage']}")
            gates.append(
                Gate(
                    name=f"quality:{aspect_id}",
                    status=status_text(row.get("status")),
                    detail="; ".join(detail),
                    href=report_href,
                )
            )
    visual = quality.get("visualAppearanceReview")
    if isinstance(visual, dict):
        gates.append(
            Gate(
                name="quality:visualAppearanceReview",
                status=status_text(visual.get("status")),
                detail="; ".join(
                    value
                    for value in (
                        str(visual.get("reviewMethod") or ""),
                        str(visual.get("reviewer") or ""),
                    )
                    if value
                ),
                href=report_href,
            )
        )

    projected: list[Evidence] = []
    seen: set[tuple[str, str]] = set()
    sources: list[tuple[str, dict[str, Any]]] = []
    if isinstance(aspects, dict):
        sources.extend(
            (str(name), row) for name, row in aspects.items() if isinstance(row, dict)
        )
    if isinstance(visual, dict):
        sources.append(("visualAppearanceReview", visual))
    for aspect_id, row in sources:
        for item in as_list(row.get("evidence")):
            if not isinstance(item, dict):
                continue
            path_text = str(item.get("path") or "")
            kind = str(item.get("kind") or "evidence")
            key = (path_text, kind)
            if key in seen:
                continue
            seen.add(key)
            target = root / path_text if path_text else None
            actual_hash = digest(target) if target is not None else None
            expected_hash = str(item.get("sha256") or "") or None
            status = (
                "PASS"
                if item.get("verified") is True and actual_hash == expected_hash
                else "MISSING"
            )
            if actual_hash and expected_hash and actual_hash != expected_hash:
                status = "HASH_MISMATCH"
            qualifier = item.get("view") or item.get("pose") or Path(path_text).name
            projected.append(
                Evidence(
                    label=f"{aspect_id}:{kind}:{qualifier}",
                    status=status,
                    href=(
                        relative_href(target, output_dir)
                        if target is not None and target.is_file()
                        else None
                    ),
                    sha256=actual_hash or expected_hash,
                )
            )
    if report_path.is_file():
        projected.append(
            Evidence(
                label="QualitySpec release projection",
                status="PASS" if quality.get("passed") is True else "FAIL",
                href=report_href,
                sha256=digest(report_path),
            )
        )
    candidate_hash = pick(
        document,
        "candidateManifestSha256",
        default=quality.get("candidateManifestSha256"),
    )
    return blockers, gates, projected, str(candidate_hash) if candidate_hash else None


def parse_improvement_projection(
    root: Path, slug: str, output_dir: Path
) -> tuple[list[dict[str, str]], list[Gate], list[Evidence], str | None]:
    projection = improvement.review_projection(root, slug)
    if projection["status"] == "NOT_RUN" and projection["iterationCount"] == 0:
        return [], [], [], None
    next_action = str(projection.get("nextAction") or "NOT_RUN")
    capability = str(projection.get("missingCapability") or "unknown")
    selected = str(projection.get("selectedMethod") or "none")
    blockers: list[dict[str, str]] = []
    if next_action not in {"NONE", "NOT_RUN"}:
        blockers.append(
            {
                "severity": "IMPROVEMENT",
                "message": f"{capability} · {next_action}"
                + (f" · {selected}" if selected != "none" else ""),
            }
        )
    gates = [
        Gate(
            name="improvement:next-action",
            status="PASS" if next_action in {"NONE", "NOT_RUN"} else "PENDING",
            detail=f"{capability}; selected={selected}",
            href=None,
        )
    ]
    if projection.get("lastDecision"):
        last = str(projection["lastDecision"])
        gates.append(
            Gate(
                name="improvement:last-decision",
                status="PASS" if last == "ADOPT" else last,
                detail=f"iterations={projection['iterationCount']}",
                href=None,
            )
        )
    evidence: list[Evidence] = []
    for label, path_text in (
        ("Improvement plan", projection.get("planPath")),
        ("Improvement iteration", projection.get("lastRecord")),
    ):
        if not path_text:
            continue
        target = root / str(path_text)
        evidence.append(
            Evidence(
                label=label,
                status="PASS" if target.is_file() else "MISSING",
                href=relative_href(target, output_dir) if target.is_file() else None,
                sha256=digest(target) if target.is_file() else None,
            )
        )
    resume = next_action if next_action not in {"NONE", "NOT_RUN"} else None
    return blockers, gates, evidence, resume


def collect_product(
    root: Path,
    workspace: Path,
    output_dir: Path,
    required_views: list[str],
    required_poses: list[str],
) -> Product:
    manifest_path = workspace / "ProductManifest.json"
    manifest: dict[str, Any] = load_json(manifest_path, {})
    blockers = [
        {"severity": issue_severity(item), "message": issue_message(item)}
        for item in as_list(
            pick(manifest, "blockers", "defects", "issues", "findings", default=[])
        )
        if open_issue(item)
    ]
    quality_blockers, quality_gates, quality_evidence, quality_hash = (
        parse_quality_projection(root, workspace.name, output_dir)
    )
    (
        improvement_blockers,
        improvement_gates,
        improvement_evidence,
        improvement_resume,
    ) = parse_improvement_projection(root, workspace.name, output_dir)
    blockers.extend(quality_blockers)
    blockers.extend(improvement_blockers)

    assets: list[Asset] = []
    previews, preview_origin = preview_directory(workspace)
    selected: set[Path] = set()
    for kind, directory, names in (
        ("view", previews, required_views),
        ("pose", previews / "Poses", required_poses),
    ):
        for name in names:
            target = locate_image(directory, name)
            if target:
                selected.add(target.resolve())
            assets.append(
                Asset(
                    kind=kind,
                    name=name,
                    status="PASS" if target else "MISSING",
                    href=relative_href(target, output_dir) if target else None,
                    sha256=digest(target) if target else None,
                )
            )

    for target in image_files(previews):
        if target.resolve() in selected:
            continue
        assets.append(
            Asset(
                kind=preview_origin,
                name=target.relative_to(previews).as_posix(),
                status="PASS",
                href=relative_href(target, output_dir),
                sha256=digest(target),
            )
        )

    candidate = pick(manifest, "candidate", "candidate_manifest", default={})
    review = pick(manifest, "human_review", "review", default={})
    updated_at = pick(manifest, "updated_at", "last_updated", "generated_at")
    if not updated_at and manifest_path.exists():
        updated_at = datetime.fromtimestamp(
            manifest_path.stat().st_mtime, timezone.utc
        ).isoformat()
    manifest_hash = str(
        pick(
            candidate,
            "sha256",
            "hash",
            "candidate_hash",
            default=pick(manifest, "candidate_hash", default="UNKNOWN"),
        )
    )
    manifest_resume = str(
        pick(
            manifest,
            "resume_point",
            "restart_from",
            "next_action",
            "resume_from",
            default="未登録",
        )
    )
    return Product(
        slug=workspace.name,
        state=safe_state(manifest),
        updated_at=str(updated_at or "UNKNOWN"),
        blocker_count=len(blockers),
        blockers=blockers,
        resume_point=improvement_resume or manifest_resume,
        candidate_hash=quality_hash or manifest_hash,
        human_review_url=str(
            pick(
                review,
                "url",
                "pr_review_url",
                "review_url",
                default=pick(manifest, "human_review_url", default=""),
            )
        ),
        manifest_href=relative_href(manifest_path, output_dir),
        assets=assets,
        gates=[
            *parse_gate_rows(manifest, workspace, output_dir),
            *quality_gates,
            *improvement_gates,
        ],
        evidence=[
            *parse_evidence_rows(manifest, workspace, output_dir),
            *quality_evidence,
            *improvement_evidence,
        ],
    )


STYLE = """
:root{--bg:#11131a;--surface:#1b1e28;--ink:#f4f6fa;--muted:#adb6c7;--line:#465064;--accent:#8bdcff;font-family:Inter,'Noto Sans JP',system-ui,sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);line-height:1.55}a{color:var(--accent)}button,input,select{font:inherit;min-height:44px}header,main,footer{width:min(1200px,calc(100% - 24px));margin:auto}header{display:flex;justify-content:space-between;gap:12px;padding:18px 0}nav{display:flex;gap:12px;flex-wrap:wrap}.hero,.controls,.product-list,.product-detail{border:1px solid var(--line);border-radius:16px;background:var(--surface)}.hero{padding:24px}.controls{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:10px;padding:12px;margin-top:12px}.workspace{display:grid;grid-template-columns:300px 1fr;gap:12px;margin-top:12px}.product-list,.product-detail{padding:14px}.product-buttons{display:grid;gap:7px}.product-button{display:grid;grid-template-columns:1fr auto;gap:5px;padding:10px;background:#242837;color:var(--ink);border:1px solid var(--line);border-radius:10px;text-align:left}.product-button small{grid-column:1/-1}.section{border-top:1px solid var(--line);margin-top:18px;padding-top:14px}.image-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.image-card{border:1px solid var(--line);border-radius:10px;overflow:hidden}.image-card img{width:100%;aspect-ratio:1;object-fit:contain;background:#0d0f15}.gate-grid,.evidence-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.gate-card,.evidence-card,.summary-grid div{padding:10px;background:#242837;border-radius:9px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.summary-grid dd{margin:0;overflow-wrap:anywhere}.summary-grid dt,small{color:var(--muted)}.state,.gate-status,.asset-status{font-weight:800}.viewer{position:fixed;inset:0;background:#000e;display:grid;place-items:center}.viewer[hidden]{display:none}.viewer img{max-width:90vw;max-height:80vh}.viewer-controls{position:absolute;top:12px;right:12px;display:flex;gap:6px}.skip{position:absolute;left:-9999px}.skip:focus{left:8px;top:8px}.empty{padding:18px;color:var(--muted)}footer{padding:24px 0;color:var(--muted)}@media(max-width:800px){.controls,.workspace,.summary-grid,.image-grid,.gate-grid,.evidence-grid{grid-template-columns:1fr}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
"""

SCRIPT = """
(()=>{'use strict';const DATA=window.REVIEW_CONSOLE_DATA;const state={q:'',status:'all',blockers:'all',slug:new URLSearchParams(location.search).get('product')||'',assetIndex:0};const $=s=>document.querySelector(s);const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'})[c]);const records=DATA.products||[];const bySlug=s=>records.find(r=>r.slug===s);function filtered(){const q=state.q.toLowerCase();return records.filter(r=>(!q||JSON.stringify(r).toLowerCase().includes(q))&&(state.status==='all'||r.state===state.status)&&(state.blockers==='all'||(state.blockers==='yes'?r.blocker_count>0:r.blocker_count===0)))}function writeUrl(){const p=new URLSearchParams;if(state.slug)p.set('product',state.slug);history.replaceState(null,'',`${location.pathname}${p.size?'?'+p:''}`)}function badge(v,k='gate'){return`<span class="${k}-status ${k}-status-${esc(v)}">${esc(v)}</span>`}function renderList(){const list=filtered();$('#product-count').textContent=`${list.length}/${records.length}`;$('#product-buttons').innerHTML=list.map(r=>`<button class="product-button" data-product="${esc(r.slug)}"><strong>${esc(r.slug)}</strong><span class="state">${esc(r.state)}</span><small>blocker ${r.blocker_count}</small></button>`).join('')||'<div class="empty">該当製品なし</div>';document.querySelectorAll('[data-product]').forEach(b=>b.onclick=()=>{state.slug=b.dataset.product;writeUrl();renderDetail()})}function renderDetail(){const r=bySlug(state.slug);$('#detail-empty').hidden=!!r;$('#detail-content').hidden=!r;if(!r)return;$('#product-title').textContent=r.slug;$('#product-state').textContent=r.state;$('#updated').textContent=r.updated_at;$('#manifest-link').href=r.manifest_href;for(const[k,v]of Object.entries({blockers:r.blocker_count,resume:r.resume_point,hash:r.candidate_hash,review:r.human_review_url||'未登録'}))document.querySelector(`[data-summary="${k}"]`).textContent=v;$('#blockers-list').innerHTML=r.blockers.map(b=>`<li><strong>${esc(b.severity)}</strong> ${esc(b.message)}</li>`).join('')||'<li>未解決blockerなし</li>';$('#image-grid').innerHTML=r.assets.map((a,i)=>`<article class="image-card">${a.href?`<img src="${esc(a.href)}" alt="${esc(a.name)}"><button data-viewer="${i}">拡大</button>`:'<div class="empty">画像なし</div>'}<div>${esc(a.kind)} / ${esc(a.name)} ${badge(a.status,'asset')}</div></article>`).join('');document.querySelectorAll('[data-viewer]').forEach(b=>b.onclick=()=>openViewer(Number(b.dataset.viewer)));$('#gate-grid').innerHTML=r.gates.map(g=>`<article class="gate-card"><strong>${esc(g.name)}</strong> ${badge(g.status)}<div>${esc(g.detail)}</div>${g.href?`<a href="${esc(g.href)}">ログを開く</a>`:''}</article>`).join('');$('#evidence-grid').innerHTML=r.evidence.map(e=>`<article class="evidence-card"><strong>${esc(e.label)}</strong> ${badge(e.status)}${e.sha256?`<small>SHA-256 ${esc(e.sha256)}</small>`:''}${e.href?`<div><a href="${esc(e.href)}">証拠を開く</a></div>`:''}</article>`).join('')}function openViewer(i){const r=bySlug(state.slug),a=(r?.assets||[]).filter(x=>x.href);if(!a.length)return;state.assetIndex=(i+a.length)%a.length;$('#viewer-image').src=a[state.assetIndex].href;$('#viewer').hidden=false}function move(d){openViewer(state.assetIndex+d)}$('#q').oninput=e=>{state.q=e.target.value;renderList()};$('#status-filter').onchange=e=>{state.status=e.target.value;renderList()};$('#blocker-filter').onchange=e=>{state.blockers=e.target.value;renderList()};$('#clear').onclick=()=>{state.q='';state.status='all';state.blockers='all';$('#q').value='';renderList()};$('#viewer-close').onclick=()=>$('#viewer').hidden=true;$('#viewer-prev').onclick=()=>move(-1);$('#viewer-next').onclick=()=>move(1);document.addEventListener('keydown',e=>{if(e.key==='Escape')$('#viewer').hidden=true;if(e.key==='ArrowLeft')move(-1);if(e.key==='ArrowRight')move(1)});for(const s of DATA.states){const o=document.createElement('option');o.value=s;o.textContent=s;$('#status-filter').append(o)}if(!bySlug(state.slug))state.slug=records[0]?.slug||'';renderList();renderDetail();writeUrl()})();
"""


def render_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>image2outfit Review Console</title><style>{STYLE}</style></head><body><a class="skip" href="#product-list">製品一覧へ移動</a><header><strong>image2outfit Review Console</strong><nav><a href="#product-list">製品</a><a href="#assets">画像</a><a href="#gates-section">ゲート</a><a href="#evidence-section">証拠</a></nav></header><main><section class="hero"><p>READ ONLY · RELEASE EVIDENCE</p><h1>候補、blocker、画像、証拠を同じ画面で見る。</h1><p>ProductManifest、QualitySpec、Improvement Loopを同じ正準projectionから読みます。読み取り専用です。</p></section><section class="controls"><input id="q" type="search" aria-label="検索"><select id="status-filter"><option value="all">すべての状態</option></select><select id="blocker-filter"><option value="all">blockerすべて</option><option value="yes">あり</option><option value="no">なし</option></select><button id="clear">条件解除</button></section><div class="workspace"><section class="product-list" id="product-list"><h2>製品 <span id="product-count"></span></h2><div class="product-buttons" id="product-buttons"></div></section><section class="product-detail" id="product-detail"><div id="detail-empty" class="empty">製品なし</div><div id="detail-content" hidden><div><h2 id="product-title"></h2><span id="product-state" class="state"></span><p id="updated"></p><a id="manifest-link">ProductManifestを開く</a></div><dl class="summary-grid"><div><dt>blocker</dt><dd data-summary="blockers"></dd></div><div><dt>再開地点</dt><dd data-summary="resume"></dd></div><div><dt>candidate hash</dt><dd data-summary="hash"></dd></div><div><dt>human review</dt><dd data-summary="review"></dd></div></dl><section class="section"><h3>未解決blocker</h3><ul id="blockers-list"></ul></section><section class="section" id="assets"><h3>必須ビュー・ポーズ</h3><div class="image-grid" id="image-grid"></div></section><section class="section" id="gates-section"><h3>release gate</h3><div class="gate-grid" id="gate-grid"></div></section><section class="section" id="evidence-section"><h3>証拠 · QualitySpec release projection</h3><div class="evidence-grid" id="evidence-grid"></div></section></div></section></div></main><div class="viewer" id="viewer" hidden><img id="viewer-image" alt=""><div class="viewer-controls"><button id="viewer-prev">前</button><button id="viewer-next">次</button><button id="viewer-close">閉じる</button></div></div><footer>image2outfit Review Console · 読み取り専用。</footer><script>window.REVIEW_CONSOLE_DATA={payload};</script><script>{SCRIPT}</script></body></html>"""


def build(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    policy = load_json(root / "config" / "release-policy.json", {})
    required_views, required_poses = policy_requirements(policy)
    products: list[Product] = []
    product_root = root / "Assets" / "GenWorks"
    if product_root.is_dir():
        for workspace in sorted(product_root.iterdir()):
            if workspace.is_dir() and (workspace / "ProductManifest.json").is_file():
                products.append(
                    collect_product(
                        root, workspace, output, required_views, required_poses
                    )
                )
    data = {
        "schema_version": "review-console.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "states": list(STATES),
        "required_views": required_views,
        "required_poses": required_poses,
        "products": [asdict(product) for product in products],
    }
    (output / "review-console.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "index.html").write_text(render_html(data), encoding="utf-8")
    return data


def serve(root: Path, port: int) -> None:
    os.chdir(root)
    with socketserver.ThreadingTCPServer(
        ("127.0.0.1", port), SimpleHTTPRequestHandler
    ) as server:
        print(f"Review console: http://127.0.0.1:{port}/.image2outfit/review-console/")
        server.serve_forever()


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output", type=Path, default=Path(".image2outfit/review-console")
    )
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
