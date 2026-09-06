from __future__ import annotations
import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("visual_review_bundle",ROOT/"tools"/"visual_review_bundle.py")
assert SPEC is not None and SPEC.loader is not None
M=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(M)

class VisualReviewBundleTests(unittest.TestCase):
    def setUp(self):
        self.original_root=M.ROOT
    def tearDown(self):
        M.ROOT=self.original_root

    def fixture(self, root: Path):
        M.ROOT=root
        (root/"contracts/quality").mkdir(parents=True)
        quality={"schemaVersion":1,"specId":"q1","directImageReview":{"requiredViews":["front","back"],"requiredPoses":["neutral"]},"aspects":[{"id":"silhouette","defectCode":"SILHOUETTE_FIDELITY_INVALID","returnStage":"build-blender","completionGate":"visualAppearanceReview","targetViews":["front","back"],"targetPoses":["neutral"]},{"id":"evidence-completeness","computed":True,"defectCode":"E","returnStage":"render-evidence","completionGate":"fiveViewEvidence"}]}
        (root/"contracts/quality/quality-spec.json").write_text(json.dumps(quality))
        product="garment"; prod=root/"Assets/GenWorks"/product; (prod/"Previews/Poses").mkdir(parents=True)
        for rel in ("Previews/front.png","Previews/back.png","Previews/Poses/neutral.png"):
            p=prod/rel; p.write_bytes(rel.encode())
        manifest={"schemaVersion":1,"productId":product}; (prod/"ProductManifest.json").write_text(json.dumps(manifest))
        ref_dir=root/"config/products"/product; ref_dir.mkdir(parents=True)
        ref={"schemaVersion":1,"productId":product,"sha256":"a"*64,"observedViews":["front"]}; (ref_dir/"reference.json").write_text(json.dumps(ref))
        job={"schemaVersion":2,"id":product,"adapterId":"adapter","renderLoopRevision":"r1","productManifestPath":f"Assets/GenWorks/{product}/ProductManifest.json","previewPaths":{"front":f"Assets/GenWorks/{product}/Previews/front.png","back":f"Assets/GenWorks/{product}/Previews/back.png"},"posePaths":{"neutral":f"Assets/GenWorks/{product}/Previews/Poses/neutral.png"}}
        job_path=ref_dir/"job.json"; job_path.write_text(json.dumps(job))
        request={"schemaVersion":1,"productId":product,"revisionId":"v1","sourceReference":"private-reference://sha256/"+"a"*64}
        request_path=root/"request.json"; request_path.write_text(json.dumps(request))
        return job_path,request_path

    def test_bundle_binds_candidate_reference_protocol_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,request=self.fixture(Path(tmp)); bundle=M.build_review_bundle(job,request)
            self.assertEqual(bundle["reference"]["sourceSha256"],"a"*64)
            self.assertEqual(bundle["referenceAssessability"]["back"],"NOT_ASSESSABLE")
            self.assertEqual(len(bundle["currentImages"]),3)
            self.assertEqual(bundle["bundleSha256"],M._bundle_digest(bundle))

    def test_unobserved_reference_view_cannot_pass_fidelity(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,request=self.fixture(Path(tmp)); bundle=M.build_review_bundle(job,request)
            review={"schemaVersion":1,"productId":"garment","reviewBundleSha256":bundle["bundleSha256"],"candidateManifestSha256":bundle["candidateManifest"]["sha256"],"renderProtocolSha256":bundle["renderProtocolSha256"],"opinions":[{"criterionId":"silhouette","status":"PASS","view":"back","pose":"neutral","confidence":0.8}]}
            with self.assertRaisesRegex(ValueError,"cannot PASS"):
                M.validate_review_result(review,bundle)

    def test_fail_maps_to_existing_defect_and_return_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,request=self.fixture(Path(tmp)); bundle=M.build_review_bundle(job,request)
            review={"schemaVersion":1,"productId":"garment","reviewBundleSha256":bundle["bundleSha256"],"candidateManifestSha256":bundle["candidateManifest"]["sha256"],"renderProtocolSha256":bundle["renderProtocolSha256"],"opinions":[{"criterionId":"silhouette","status":"FAIL","view":"front","pose":"neutral","confidence":0.9,"observedDefect":"too wide","probableCause":"pattern width"}]}
            findings=M.validate_review_result(review,bundle)
            self.assertEqual(findings[0]["code"],"SILHOUETTE_FIDELITY_INVALID")
            self.assertEqual(findings[0]["recommendedReturnStage"],"build-blender")

    def test_stale_candidate_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            job,request=self.fixture(Path(tmp)); bundle=M.build_review_bundle(job,request)
            review={"schemaVersion":1,"productId":"garment","reviewBundleSha256":bundle["bundleSha256"],"candidateManifestSha256":"0"*64,"renderProtocolSha256":bundle["renderProtocolSha256"],"opinions":[{"criterionId":"silhouette","status":"NOT_ASSESSABLE","view":"back","pose":"neutral","confidence":0.5}]}
            with self.assertRaisesRegex(ValueError,"candidateManifestSha256"):
                M.validate_review_result(review,bundle)

if __name__=="__main__": unittest.main()
