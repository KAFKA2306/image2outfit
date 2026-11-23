# BOOTH public listing quality audit

This command reviews one public BOOTH item page using the buyer-facing rubric. It is a local
reporting tool, not a manufacturing completion gate or customer release decision. It never edits
`ProductManifest.json`, product files, or the release policy.

## Install and run

The pinned candidate is LiquidAI `d1-2B-ONNX` at Q4 precision on CPU. Its separate Python 3.12
runtime is the pinned `Liquid4All/onnx-export` checkout. This keeps Transformers, ONNX Runtime, and
the model weights out of the product's Python 3.11 environment and avoids competing with the
existing GPU model.

```powershell
task booth:audit:setup
task booth:audit PRODUCT=siroino-lilac-lame-fencing-practice-set URL="https://booth.pm/ja/items/<id>"
```

The model revision, runtime revision, and provisional routing settings are in
`config/booth-audit-model.json`. The installer stores the checkout, Python environment, and model
under ignored `Assets/_Local/booth-audit/`; it records the installed candidate and weight hashes in
`.image2outfit/booth-audit/runtime-state.json`. It does not promote the model to a known-good
production model.

The D1 process starts only when Windows reports at least 8 GiB of free physical memory. If the
runtime is missing or the memory floor is not met, the report remains pending and no rating is
issued. The D1 confidence threshold is provisional; it must be calibrated against labeled BOOTH
audits before treating GREEN as dependable.

## Evidence boundary

- The target must be an HTTPS BOOTH `/items/<id>` page. Redirects remain on the same BOOTH shop
  host, with only `booth.pm` and `www.booth.pm` treated as equivalent.
- The fetcher reads the target page and, only when the target links to a shop subdomain, that
  shop's listing page. Listing volume is recorded as context and never lowers the rating.
- It checks each host's current `robots.txt`, disables configured HTTP proxies, limits redirects,
  response size, and request rate, and downloads at most four page-listed images from the BOOTH
  image CDN. It records page-embedded video and labeled demo-world links but never opens those
  external URLs. It does not download product archives or video bodies, visit demo worlds, or
  follow links to other shops.
- Page text is untrusted input. Management-only text such as “Now this item is Private” is removed
  from report evidence. AI disclosure absence is neutral. “Not stated” remains distinct from
  “explicitly untested.”
- Image labels are D1 observations, not proof that VRChat was tested. Video and demo-world links are
  recorded as links; the linked content is not automatically verified.

## Escalation

D1 classifies the page and first four images in one local CPU run. A non-GREEN preliminary result,
an unverified quote, or confidence below the provisional threshold requests a second review.
That review uses only a loopback OpenAI-compatible endpoint set through these process environment
variables:

- `IMAGE2OUTFIT_LOCAL_LLM_BASE_URL`
- `IMAGE2OUTFIT_LOCAL_LLM_MODEL`
- `IMAGE2OUTFIT_LOCAL_LLM_API_KEY`

The endpoint must be `localhost`, `127.0.0.1`, or `::1`. The API key is never stored in the
repository or printed. No cloud provider is used. If the local endpoint is absent, unreachable,
returns invalid JSON, or cites evidence outside the report, the verdict stays pending for human
review.

## Output

Each run writes `audit.json`, `audit.md`, the D1 request/result, and any fetched images under
`.image2outfit/products/<product-id>/reports/booth-audit/<UTC timestamp>/`. The Markdown report has
the six sections from the buyer rubric and no more than three purchase checks. The JSON retains
the source URL, captured evidence, model revision, confidence, and escalation state for review.

No BOOTH item URL was supplied when this tool was added, so no product has been audited yet.
