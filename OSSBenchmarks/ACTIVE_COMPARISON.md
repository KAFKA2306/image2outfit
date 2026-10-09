# Active 2026 Image-to-3D OSS comparison

正本Issue: https://github.com/KAFKA2306/image2outfit/issues/683  
正規データ: https://docs.google.com/spreadsheets/d/1iAHGdCUOy2pQYIJ92feqc0s28i-6VSdJ6bRTqjfdmkE/edit  
対象fixture: `siroino-lily-vapor-yukata`  
スナップショット: 2026-10-04

## 結論

Active 14候補について、現時点で採用順位はまだ確定できない。Pixal3Dは4-viewのテクスチャ付きGLBまで完了したが、37,338コンポーネント・432,830境界エッジで品質ゲートに失敗した。TripoSplatは単画像から65,536 GaussianのPLY/SPLATを出力したが、Unity/VRMへ直接渡せるメッシュではない。TRELLIS.2は12 GiB環境で低VRAMの実験出力を得たが、7,279コンポーネントのbring-up artifactであり、標準品質の比較結果には使えない。FastAvatarは公式bundle・専用runtimeをロードできたが、共通fixtureに顔がなく、公式FLAME trackingの入力契約で停止した。CUPID/AniGenは公式GPUメモリ、Wonder3D++/TIGON/MeshFlow/HumanNOVA/DiGS-Avatar/STREAM3D/PhysX系は公式dependency・asset・入力契約でpreflight停止している。

一次ソース監査は14候補分を記録済みで、各リポジトリの取得commitも台帳に固定した。ライセンス宣言あり12件、リポジトリ上でライセンス未宣言2件（STREAM3D、HumanNOVA）であり、MeshFlow・PhysX系・AniGenの同梱部品は制限付きとして扱う。

したがって現在の正式な比較結果は、順位ではなく「実行済み・品質失敗・未実行」を分離した状態である。

## Active comparison

| Candidate | Category | Class | Current result | Adoption reading |
|---|---|---:|---|---|
| Pixal3D | Mesh / PBR | A | GLB export complete; topology/visual quality fail | Textured blockoutとして保持。Unity/VRChat handoff不可 |
| TRELLIS.2 | Mesh / PBR | B | Low-VRAM experimental artifact only | 標準比較から除外。24 GiB級公式gateを満たす別GPUが必要 |
| Wonder3D++ | Mesh / Texture | A | 公式依存preflightで停止 | 再現可能な実行環境の整備待ち |
| STREAM3D | Multi-view Mesh / Gaussian | A | 深度/pose入力・backend preflightで停止 | 公式入力契約と別GPUが必要 |
| TripoSplat | Gaussian | A | 65,536 GaussianをPLY/SPLAT出力 | Gaussian viewer/mesh handoff計測待ち |
| CUPID | Reconstruction + Camera | A | 16 GiB公式条件でpreflight停止 | 12 GiBホストでは実行不可 |
| AniGen | Rigged Mesh | A | 18 GiB公式条件でpreflight停止 | 12 GiBホストでは実行不可 |
| TIGON | Text / Image-conditioned 3D | A | DINOv3・CUDA拡張・公式checkpoint preflightで停止 | 公式image-only経路の実行待ち |
| MeshFlow | Mesh post-process / generation | A | checkpointと入力メッシュを要する間接経路のpreflightで停止 | 直接image-to-3D順位には混ぜない |
| FastAvatar | Gaussian Avatar | A | 公式bundle・dedicated runtimeをロード後、fixtureの顔tracking入力契約で停止 | 顔を含む正規fixtureの承認・追加後にGaussian avatar handoff計測 |
| HumanNOVA | Human Avatar | A | 公式asset/dependency preflightで停止 | 公式checkpoint・SMPLify asset待ち |
| DiGS-Avatar | Gaussian Avatar | A | SMPL-X/SANA/専用checkpoint preflightで停止 | 未配布asset待ち |
| PhysX-Anything | Simulation-ready 3D | A | 25-view条件画像・checkpoint・decoder preflightで停止 | simulation/URDF軸で別評価 |
| PhysX-Omni | Simulation-ready 3D | A | 25-view条件画像・checkpoint・TRELLIS decoder preflightで停止 | simulation/URDF軸で別評価 |

機械可読な状態、commit、artifact hash、トポロジー値は [`active-comparison.json`](active-comparison.json) を参照する。

## 実行済みの要点

### Wonder3D++ preflight

公式Wonder3D_Plus commit `fdb095a247f3b75fe7dc6fc3a16b8d871fdc3c77`と公式weight一覧を固定した。公式 `run.py` のend-to-end mesh pathは `omegaconf`、`rembg`、`PyTorch3D`、`pymeshlab`、`segment_anything` を必要とするが、現行の再利用環境では未導入だった。部分経路や代替実装を混ぜず、実機結果は作成していない。対象branchのREADMEはライセンスをAGPL-3.0と明記する。

証拠: `Wonder3DPlus/preflight.json`

### CUPID / AniGen preflight

CUPIDは公式READMEでLinux only tested・NVIDIA GPU 16 GiB以上、AniGenはLinux only tested・NVIDIA GPU 18 GiB以上を必要条件としている。比較ホストはRTX 3060 12 GiBのため、両方とも公式経路の実行を開始せず、ハードウェアpreflight blockedとして扱う。

証拠: `CUPID/preflight.json`、`AniGen/preflight.json`

### HumanNOVA / DiGS-Avatar / STREAM3D preflight

HumanNOVAはSMPLify assetと専用依存環境、DiGS-AvatarはSMPL-X・SANA・teacher/student checkpoint、STREAM3Dは各frameのdepth NPZ・mask・world-to-camera pose、またはTRELLIS.2 backendを要求する。現fixtureにあるのは4枚の画像と4-view transformだけで、これらの公式入力契約を満たす補助assetは存在しない。

証拠: `HumanNOVA/preflight.json`、`DiGS-Avatar/preflight.json`、`STREAM3D/preflight.json`

### TIGON / MeshFlow / FastAvatar preflight

TIGONはimage-onlyをサポートするが、公式checkpoint、DINOv3のコードとViT-H/16+ weight、CUDA拡張が必要で、現環境には揃っていない。MeshFlowは画像から直接生成する候補ではなく、入力メッシュまたはpoint cloudを受けるpost-processであり、公式checkpointも未配置である。FastAvatarは公式model/asset bundle、motion sequence directory、顔/FLAME trackingを必要とする。専用`uv`環境でruntime/CUDA拡張と公式bundleをロードしたうえで共通fixtureを実行したが、`front.png`は顔のないheadless previewのため、`No faces detected in any frame`でGaussian推論前に停止した。顔を含む別入力へのすり替えはせず、現fixtureの結果はrankableにしない。

証拠: `TIGON/preflight.json`、`MeshFlow/preflight.json`、`FastAvatar/preflight.json`、`FastAvatar/runs/monocular_common_front_20261004/report.md`

### PhysX-Anything / PhysX-Omni preflight

PhysX系は通常のMesh/PBRベンチではなく、物理属性・分割部品・URDF/XMLまでを測るsimulation-readyカテゴリである。公式経路は25枚のconditioning imageと専用checkpoint/decoder stackを前提にしており、共通fixtureの5枚では入力契約を満たさない。したがって通常のimage-to-mesh順位へ混ぜず、別軸の実機ベンチ待ちとする。

証拠: `PhysX-Anything/preflight.json`、`PhysX-Omni/preflight.json`

### Pixal3D

公式リポジトリ commit `f7cf38429b0bd264f1995f0f8743a88b1c728b94`、4-view、seed 42、low-VRAM、shape 1024、texture conditioning 512でGLBを出力した。UVとPBR materialは存在するが、出力は連続した衣装として読めず、巨大な浮遊スラブと肩・腰周辺のメッシュ島が残る。小コンポーネント除去だけでは不十分で、トポロジー対応remeshとbody/garment分離が必要。

証拠: `Pixal3D/report.md`、`Pixal3D/report.json`、`Pixal3D/runs/mv_20260923_seed42_lowvram_1024_torchnaf_tex512_projchunk/`

### TRELLIS.2

公式の24 GiB級VRAM gateに対し、ホストはRTX 3060 12 GiB。別の低VRAM shape-256実験では8.722 GiB peak allocatedでGLB/PLYを得たが、7,279 components・17,528 facesの断片化結果で、標準品質や採用順位の証拠ではない。

証拠: `TRELLIS2/REPORT.md`、`TRELLIS2/preflight.json`、`UniformFrontBack20260923/comparison-report.md`

### TripoSplat

公式リポジトリ commit `d8db9e018b413dd9c4a9fe22463781bf98e8e68d`、front単画像、seed 42、20 steps、65,536 Gaussianで実行した。推論peakは4.591 GiB、推論時間は51.439秒。PLYとSPLATの両方を保存した。点中心の三方向サニティプレビューではbody/plate-likeなメッシュ島に分断され、ウェアラブル衣装としての適合性は示せなかった。公式Gaussian renderer、メッシュ化、VRM/Unity/VRChat handoffは未計測なので採用順位には入れていない。

証拠: `TripoSplat/run_benchmark.py`、`TripoSplat/render_point_preview.py`、`TripoSplat/runs/front_20261004_seed42_g65536/report.json`、[`point-preview.png`](TripoSplat/runs/front_20261004_seed42_g65536/point-preview.png)

## 対象外の既存結果

Issue #683のスコープ変更により、Hunyuan3D-2/2mv、Hunyuan3D-2.1、Step1X-3D、TripoSG、Direct3D-S2はC / out of scope。既存の実機結果は履歴・参照証拠として残すが、Active rankingへ混ぜない。

| Candidate | Reference result |
|---|---|
| Hunyuan3D-2 / 2mv | Shape inference completed; broad silhouette/backside, no UV/material, cleanup required |
| Hunyuan3D-2.1 | Shape completed in later uniform run; Paint not run; no UV/material |
| Step1X-3D | 27–29 GiB official path; local 12 GiB hostでは標準実行不可 |
| TripoSG | Front/single-view and uniform-input runs completed; body/parts remain, no UV/material |
| Direct3D-S2 | Windows Triton dependencyで実行不可 |

## 比較の読み方

Mesh / PBR、Gaussian、rigged mesh、post-process、simulation-ready 3Dは別カテゴリとして比較する。紙面品質だけでなく、image2outfitの最終KPIである「参考画像からUnity/VRChatで使えるアセットまでに必要な人手」を記録する。

未実行候補は0点ではなく、判定不能である。低VRAMの断片化出力も、成功として順位付けしない。

## 次の欠落

1. preflight blocked候補について、公式checkpoint・依存・入力契約を別GPUまたは専用環境で満たせるか確認する。
2. 実行可能候補について、同一fixture・同一記録項目で実機結果を作る。
3. Mesh/PBR以外のカテゴリは専用の評価軸を設定してから比較する。
4. Blender cleanup、Unity import、VRChat-ready human workを候補ごとに記録する。
5. 検証済みの最終値をcanonical Google Sheetへ反映する。
