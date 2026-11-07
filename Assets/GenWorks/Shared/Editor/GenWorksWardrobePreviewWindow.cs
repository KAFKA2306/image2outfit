#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace GenWorks.Editor
{
    internal sealed class GenWorksWardrobePreviewWindow : EditorWindow
    {
        private const string ProductRoot = "Assets/GenWorks";
        private const string ManifestName = "ProductManifest.json";

        [Serializable]
        private sealed class ProductManifest
        {
            public int schemaVersion;
            public string productId;
            public string productName;
            public string status;
            public string targetAdapterId;
            public string productRoot;
            public string outfitPrefabPath;
            public string integratedPrefabPath;
            public string previewPath;
        }

        private sealed class ProductEntry
        {
            public string ManifestPath;
            public ProductManifest Manifest;
        }

        private readonly List<ProductEntry> _products = new List<ProductEntry>();
        private Vector2 _productScroll;
        private string _search = string.Empty;
        private ProductEntry _selected;

        private PreviewRenderUtility _preview;
        private GameObject _previewInstance;
        private Vector2 _orbit = new Vector2(12f, 180f);
        private float _distance = 2.2f;
        private float _fieldOfView = 30f;
        private Vector3 _pivot;
        private Vector3 _boundsCenter;

        private GameObject _sceneAvatar;
        private GameObject _mergeTarget;
        private GenWorksPreviewPreset _preset;
        private string _statusMessage = string.Empty;
        private MessageType _statusType = MessageType.Info;

        [MenuItem("GenWorks/Wardrobe Preview", priority = 12)]
        private static void Open()
        {
            var window = GetWindow<GenWorksWardrobePreviewWindow>();
            window.titleContent = new GUIContent("GenWorks Wardrobe");
            window.minSize = new Vector2(900f, 620f);
            window.Show();
        }

        private void OnEnable()
        {
            RefreshProducts();
        }

        private void OnDisable()
        {
            DisposePreview();
        }

        private void OnGUI()
        {
            DrawToolbar();
            EditorGUILayout.Space(4f);

            using (new EditorGUILayout.HorizontalScope())
            {
                DrawProductList();
                EditorGUILayout.Space(6f);
                using (new EditorGUILayout.VerticalScope())
                {
                    DrawSelectedProductHeader();
                    DrawPreviewPanel();
                    EditorGUILayout.Space(6f);
                    DrawPresetControls();
                    EditorGUILayout.Space(6f);
                    DrawApplyControls();
                }
            }

            if (!string.IsNullOrWhiteSpace(_statusMessage))
            {
                EditorGUILayout.Space(4f);
                EditorGUILayout.HelpBox(_statusMessage, _statusType);
            }
        }

        private void DrawToolbar()
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                if (GUILayout.Button("Refresh", EditorStyles.toolbarButton, GUILayout.Width(64f)))
                    RefreshProducts();
                if (GUILayout.Button("Catalog", EditorStyles.toolbarButton, GUILayout.Width(64f)))
                    GetWindow<GenWorksCatalogWindow>();
                GUILayout.Space(8f);
                _search = GUILayout.TextField(
                    _search ?? string.Empty,
                    GUI.skin.FindStyle("ToolbarSearchTextField"),
                    GUILayout.MinWidth(220f)
                );
                GUILayout.FlexibleSpace();
                GUILayout.Label(
                    GenWorksModularAvatarBackend.IsAvailable
                        ? "Modular Avatar: ready"
                        : "Modular Avatar: unresolved",
                    EditorStyles.miniLabel
                );
            }
        }

        private void DrawProductList()
        {
            using (new EditorGUILayout.VerticalScope(GUILayout.Width(330f)))
            {
                EditorGUILayout.LabelField("Outfit collection", EditorStyles.boldLabel);
                EditorGUILayout.LabelField(
                    "ProductManifest.json is the canonical wardrobe entry.",
                    EditorStyles.miniLabel
                );
                _productScroll = EditorGUILayout.BeginScrollView(_productScroll);
                foreach (var entry in _products.Where(MatchesSearch))
                    DrawProductCard(entry);
                EditorGUILayout.EndScrollView();
            }
        }

        private void DrawProductCard(ProductEntry entry)
        {
            var manifest = entry.Manifest;
            var isSelected = ReferenceEquals(entry, _selected);
            using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    var thumbnail = LoadThumbnail(manifest);
                    if (thumbnail != null)
                    {
                        var rect = GUILayoutUtility.GetRect(72f, 72f, GUILayout.Width(72f));
                        GUI.DrawTexture(rect, thumbnail, ScaleMode.ScaleToFit, true);
                    }
                    using (new EditorGUILayout.VerticalScope())
                    {
                        EditorGUILayout.LabelField(
                            manifest?.productName ?? entry.ManifestPath,
                            EditorStyles.boldLabel
                        );
                        EditorGUILayout.LabelField(
                            $"{manifest?.status ?? "INVALID"}  •  {manifest?.targetAdapterId ?? "target unknown"}",
                            EditorStyles.miniLabel
                        );
                        if (
                            GUILayout.Button(
                                isSelected ? "Selected" : "Preview",
                                GUILayout.Height(24f)
                            )
                        )
                            SelectProduct(entry);
                    }
                }
            }
        }

        private void DrawSelectedProductHeader()
        {
            if (_selected?.Manifest == null)
            {
                EditorGUILayout.HelpBox(
                    "Select an outfit from the collection to open an isolated preview.",
                    MessageType.Info
                );
                return;
            }

            using (new EditorGUILayout.HorizontalScope())
            {
                EditorGUILayout.LabelField(
                    _selected.Manifest.productName,
                    EditorStyles.boldLabel
                );
                GUILayout.FlexibleSpace();
                EditorGUILayout.LabelField(
                    _selected.Manifest.status ?? string.Empty,
                    EditorStyles.miniBoldLabel,
                    GUILayout.Width(100f)
                );
            }
            EditorGUILayout.LabelField(
                $"{_selected.Manifest.productId}  •  {_selected.Manifest.targetAdapterId}",
                EditorStyles.miniLabel
            );
        }

        private void DrawPreviewPanel()
        {
            var height = Mathf.Max(270f, position.height - 365f);
            var rect = GUILayoutUtility.GetRect(
                300f,
                10000f,
                height,
                height,
                GUILayout.ExpandWidth(true)
            );
            EditorGUI.DrawRect(rect, new Color(0.12f, 0.12f, 0.12f, 1f));

            if (_preview == null || _previewInstance == null)
            {
                GUI.Label(rect, "No preview source", CenteredLabelStyle());
                return;
            }

            HandlePreviewInput(rect);
            RenderPreview(rect);

            var overlay = new Rect(rect.x + 8f, rect.y + 8f, 300f, 42f);
            GUI.Label(
                overlay,
                "Drag: orbit   Wheel: zoom\nPreview clone only — Scene is unchanged",
                EditorStyles.helpBox
            );
        }

        private void DrawPresetControls()
        {
            EditorGUILayout.LabelField("Camera / pose preset", EditorStyles.boldLabel);
            using (new EditorGUILayout.HorizontalScope())
            {
                _preset = (GenWorksPreviewPreset)EditorGUILayout.ObjectField(
                    _preset,
                    typeof(GenWorksPreviewPreset),
                    false,
                    GUILayout.MinWidth(180f)
                );
                if (GUILayout.Button("Create", GUILayout.Width(58f)))
                    CreatePreset();
                using (new EditorGUI.DisabledScope(_preset == null))
                {
                    if (GUILayout.Button("Save Camera", GUILayout.Width(90f)))
                        SaveCameraToPreset();
                    if (GUILayout.Button("Load Camera", GUILayout.Width(90f)))
                        LoadCameraFromPreset();
                }
            }

            using (new EditorGUILayout.HorizontalScope())
            {
                using (new EditorGUI.DisabledScope(_preset == null || _sceneAvatar == null))
                {
                    if (GUILayout.Button("Capture Scene Pose"))
                        CaptureScenePose();
                }
                using (new EditorGUI.DisabledScope(_preset == null || _previewInstance == null))
                {
                    if (GUILayout.Button("Apply Pose to Preview"))
                        ApplyPresetPoseToPreview();
                }
                using (new EditorGUI.DisabledScope(_selected == null))
                {
                    if (GUILayout.Button("Reset Preview"))
                        RebuildPreview();
                }
            }
        }

        private void DrawApplyControls()
        {
            EditorGUILayout.LabelField("Apply to Scene avatar", EditorStyles.boldLabel);
            var previousAvatar = _sceneAvatar;
            _sceneAvatar = (GameObject)EditorGUILayout.ObjectField(
                "Avatar",
                _sceneAvatar,
                typeof(GameObject),
                true
            );
            if (_sceneAvatar != previousAvatar && _sceneAvatar != null)
                _mergeTarget = GuessMergeTarget(_sceneAvatar);

            using (new EditorGUILayout.HorizontalScope())
            {
                _mergeTarget = (GameObject)EditorGUILayout.ObjectField(
                    "Merge Target",
                    _mergeTarget,
                    typeof(GameObject),
                    true
                );
                using (new EditorGUI.DisabledScope(_sceneAvatar == null))
                {
                    if (GUILayout.Button("Infer", GUILayout.Width(58f)))
                        _mergeTarget = GuessMergeTarget(_sceneAvatar);
                }
            }

            var outfitPrefab = LoadOutfitPrefab();
            var canApply = _selected?.Manifest != null
                && outfitPrefab != null
                && _sceneAvatar != null
                && _mergeTarget != null
                && GenWorksModularAvatarBackend.IsAvailable;

            using (new EditorGUI.DisabledScope(!canApply))
            {
                if (GUILayout.Button("Apply selected outfit with Modular Avatar", GUILayout.Height(32f)))
                    ApplySelectedOutfit(outfitPrefab);
            }

            if (!GenWorksModularAvatarBackend.IsAvailable)
                EditorGUILayout.HelpBox(
                    "Modular Avatar is declared in Packages/vpm-manifest.json but is not currently loaded by Unity. Resolve VPM packages before Apply.",
                    MessageType.Warning
                );
        }

        private bool MatchesSearch(ProductEntry entry)
        {
            if (string.IsNullOrWhiteSpace(_search))
                return true;
            var query = _search.Trim();
            return Contains(entry.Manifest?.productName, query)
                || Contains(entry.Manifest?.productId, query)
                || Contains(entry.Manifest?.targetAdapterId, query)
                || Contains(entry.Manifest?.status, query);
        }

        private static bool Contains(string source, string query)
        {
            return !string.IsNullOrWhiteSpace(source)
                && source.IndexOf(query, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private void RefreshProducts()
        {
            var selectedId = _selected?.Manifest?.productId;
            _products.Clear();

            if (AssetDatabase.IsValidFolder(ProductRoot))
            {
                foreach (
                    var guid in AssetDatabase.FindAssets(
                        "t:TextAsset",
                        new[] { ProductRoot }
                    )
                )
                {
                    var path = AssetDatabase.GUIDToAssetPath(guid);
                    if (!string.Equals(Path.GetFileName(path), ManifestName, StringComparison.OrdinalIgnoreCase))
                        continue;
                    var entry = LoadEntry(path);
                    if (entry != null)
                        _products.Add(entry);
                }
            }

            _products.Sort((left, right) => string.Compare(
                left.Manifest?.productName ?? left.ManifestPath,
                right.Manifest?.productName ?? right.ManifestPath,
                StringComparison.OrdinalIgnoreCase
            ));

            _selected = _products.FirstOrDefault(entry =>
                string.Equals(entry.Manifest?.productId, selectedId, StringComparison.Ordinal)
            ) ?? _products.FirstOrDefault();
            RebuildPreview();
            Repaint();
        }

        private static ProductEntry LoadEntry(string path)
        {
            try
            {
                var text = AssetDatabase.LoadAssetAtPath<TextAsset>(path);
                if (text == null)
                    return null;
                var manifest = JsonUtility.FromJson<ProductManifest>(text.text);
                if (manifest == null || manifest.schemaVersion != 1)
                    return null;
                return new ProductEntry { ManifestPath = path, Manifest = manifest };
            }
            catch (Exception exception)
            {
                Debug.LogWarning($"GenWorks wardrobe skipped {path}: {exception.Message}");
                return null;
            }
        }

        private void SelectProduct(ProductEntry entry)
        {
            _selected = entry;
            _statusMessage = string.Empty;
            RebuildPreview();
        }

        private Texture LoadThumbnail(ProductManifest manifest)
        {
            if (manifest == null)
                return null;
            if (!string.IsNullOrWhiteSpace(manifest.previewPath))
            {
                var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(manifest.previewPath);
                if (texture != null)
                    return texture;
            }

            var prefab = LoadPreviewPrefab(manifest);
            return prefab == null ? null : AssetPreview.GetAssetPreview(prefab);
        }

        private void RebuildPreview()
        {
            DisposePreview();
            if (_selected?.Manifest == null)
                return;

            var prefab = LoadPreviewPrefab(_selected.Manifest);
            if (prefab == null)
            {
                SetStatus("Selected product has no loadable integrated/outfit prefab.", MessageType.Warning);
                return;
            }

            _preview = new PreviewRenderUtility();
            _preview.camera.fieldOfView = _fieldOfView;
            _preview.camera.nearClipPlane = 0.01f;
            _preview.camera.farClipPlane = 1000f;
            _preview.camera.clearFlags = CameraClearFlags.Color;
            _preview.camera.backgroundColor = new Color(0.13f, 0.13f, 0.13f, 1f);
            _preview.lights[0].intensity = 1.2f;
            _preview.lights[0].transform.rotation = Quaternion.Euler(40f, 40f, 0f);
            _preview.lights[1].intensity = 1.0f;

            _previewInstance = Instantiate(prefab);
            _previewInstance.name = prefab.name + " (Wardrobe Preview)";
            _previewInstance.transform.position = Vector3.zero;
            _previewInstance.transform.rotation = Quaternion.identity;
            SetHideFlagsRecursively(_previewInstance, HideFlags.HideAndDontSave);
            _preview.AddSingleGO(_previewInstance);
            FramePreview();

            if (_preset != null && _preset.pose != null && _preset.pose.Count > 0)
                ApplyPresetPoseToPreview();
            Repaint();
        }

        private void FramePreview()
        {
            if (_previewInstance == null)
                return;
            var renderers = _previewInstance.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
            {
                _boundsCenter = Vector3.zero;
                _pivot = Vector3.zero;
                _distance = 2.2f;
                return;
            }

            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Length; index++)
                bounds.Encapsulate(renderers[index].bounds);
            _boundsCenter = bounds.center;
            _pivot = _boundsCenter + (_preset != null ? _preset.pivotOffset : Vector3.zero);
            _distance = Mathf.Max(0.5f, bounds.extents.magnitude * 2.4f);
        }

        private void HandlePreviewInput(Rect rect)
        {
            var current = Event.current;
            if (!rect.Contains(current.mousePosition))
                return;

            if (current.type == EventType.MouseDrag && current.button == 0)
            {
                _orbit.x = Mathf.Clamp(_orbit.x - current.delta.y * 0.35f, -85f, 85f);
                _orbit.y += current.delta.x * 0.5f;
                current.Use();
                Repaint();
            }
            else if (current.type == EventType.ScrollWheel)
            {
                _distance = Mathf.Clamp(
                    _distance * (1f + current.delta.y * 0.06f),
                    0.1f,
                    100f
                );
                current.Use();
                Repaint();
            }
        }

        private void RenderPreview(Rect rect)
        {
            _preview.BeginPreview(rect, GUIStyle.none);
            var rotation = Quaternion.Euler(_orbit.x, _orbit.y, 0f);
            var cameraPosition = _pivot + rotation * (Vector3.back * _distance);
            _preview.camera.transform.position = cameraPosition;
            _preview.camera.transform.rotation = Quaternion.LookRotation(
                _pivot - cameraPosition,
                Vector3.up
            );
            _preview.camera.fieldOfView = _fieldOfView;
            _preview.camera.Render();
            var texture = _preview.EndPreview();
            GUI.DrawTexture(rect, texture, ScaleMode.StretchToFill, false);
        }

        private static GUIStyle CenteredLabelStyle()
        {
            var style = new GUIStyle(EditorStyles.centeredGreyMiniLabel)
            {
                alignment = TextAnchor.MiddleCenter,
                fontSize = 13
            };
            return style;
        }

        private GameObject LoadPreviewPrefab(ProductManifest manifest)
        {
            var integrated = LoadPrefab(manifest?.integratedPrefabPath);
            return integrated != null ? integrated : LoadPrefab(manifest?.outfitPrefabPath);
        }

        private GameObject LoadOutfitPrefab()
        {
            return LoadPrefab(_selected?.Manifest?.outfitPrefabPath);
        }

        private static GameObject LoadPrefab(string path)
        {
            return string.IsNullOrWhiteSpace(path)
                ? null
                : AssetDatabase.LoadAssetAtPath<GameObject>(path);
        }

        private void CreatePreset()
        {
            if (_selected?.Manifest == null)
                return;
            var preset = CreateInstance<GenWorksPreviewPreset>();
            preset.cameraOrbit = _orbit;
            preset.cameraDistance = _distance;
            preset.fieldOfView = _fieldOfView;
            preset.pivotOffset = _pivot - _boundsCenter;
            var path = AssetDatabase.GenerateUniqueAssetPath(
                $"{_selected.Manifest.productRoot}/{_selected.Manifest.productId}-preview-preset.asset"
            );
            AssetDatabase.CreateAsset(preset, path);
            AssetDatabase.SaveAssets();
            _preset = preset;
            Selection.activeObject = preset;
            EditorGUIUtility.PingObject(preset);
            SetStatus($"Created preview preset: {path}", MessageType.Info);
        }

        private void SaveCameraToPreset()
        {
            if (_preset == null)
                return;
            Undo.RecordObject(_preset, "Save GenWorks preview camera");
            _preset.cameraOrbit = _orbit;
            _preset.cameraDistance = _distance;
            _preset.fieldOfView = _fieldOfView;
            _preset.pivotOffset = _pivot - _boundsCenter;
            EditorUtility.SetDirty(_preset);
            AssetDatabase.SaveAssets();
            SetStatus("Camera state saved to preview preset.", MessageType.Info);
        }

        private void LoadCameraFromPreset()
        {
            if (_preset == null)
                return;
            _orbit = _preset.cameraOrbit;
            _distance = Mathf.Max(0.1f, _preset.cameraDistance);
            _fieldOfView = Mathf.Clamp(_preset.fieldOfView, 5f, 120f);
            _pivot = _boundsCenter + _preset.pivotOffset;
            Repaint();
        }

        private void CaptureScenePose()
        {
            if (_preset == null || _sceneAvatar == null)
                return;
            var root = FindPoseRoot(_sceneAvatar).transform;
            Undo.RecordObject(_preset, "Capture GenWorks preview pose");
            _preset.pose.Clear();
            foreach (var transform in root.GetComponentsInChildren<Transform>(true))
            {
                if (transform == root)
                    continue;
                _preset.pose.Add(new GenWorksPreviewPreset.TransformPose
                {
                    path = AnimationUtility.CalculateTransformPath(transform, root),
                    localPosition = transform.localPosition,
                    localRotation = transform.localRotation,
                    localScale = transform.localScale
                });
            }
            EditorUtility.SetDirty(_preset);
            AssetDatabase.SaveAssets();
            SetStatus($"Captured {_preset.pose.Count} transforms from Scene avatar.", MessageType.Info);
        }

        private void ApplyPresetPoseToPreview()
        {
            if (_preset == null || _previewInstance == null || _preset.pose == null)
                return;
            var root = FindPoseRoot(_previewInstance).transform;
            var applied = 0;
            foreach (var item in _preset.pose)
            {
                if (item == null || string.IsNullOrWhiteSpace(item.path))
                    continue;
                var target = root.Find(item.path);
                if (target == null)
                    continue;
                target.localPosition = item.localPosition;
                target.localRotation = item.localRotation;
                target.localScale = item.localScale;
                applied++;
            }
            SetStatus($"Applied {applied} pose transforms to isolated preview.", MessageType.Info);
            Repaint();
        }

        private void ApplySelectedOutfit(GameObject outfitPrefab)
        {
            try
            {
                var instance = GenWorksModularAvatarBackend.Apply(
                    _sceneAvatar,
                    _mergeTarget,
                    outfitPrefab
                );
                SetStatus(
                    $"Applied {instance.name} under {_sceneAvatar.name} with Modular Avatar Merge Armature.",
                    MessageType.Info
                );
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                SetStatus(exception.Message, MessageType.Error);
            }
        }

        private static GameObject GuessMergeTarget(GameObject avatar)
        {
            if (avatar == null)
                return null;
            var animator = avatar
                .GetComponentsInChildren<Animator>(true)
                .FirstOrDefault(candidate => candidate != null && candidate.isHuman);
            if (animator != null)
            {
                var hips = animator.GetBoneTransform(HumanBodyBones.Hips);
                if (hips != null)
                    return hips.parent != null ? hips.parent.gameObject : hips.gameObject;
            }

            var armature = avatar
                .GetComponentsInChildren<Transform>(true)
                .FirstOrDefault(transform =>
                    string.Equals(transform.name, "Armature", StringComparison.OrdinalIgnoreCase)
                );
            return armature != null ? armature.gameObject : avatar;
        }

        private static GameObject FindPoseRoot(GameObject root)
        {
            if (root == null)
                return null;
            var animator = root
                .GetComponentsInChildren<Animator>(true)
                .FirstOrDefault(candidate => candidate != null && candidate.isHuman);
            return animator != null ? animator.gameObject : root;
        }

        private static void SetHideFlagsRecursively(GameObject root, HideFlags flags)
        {
            foreach (var transform in root.GetComponentsInChildren<Transform>(true))
                transform.gameObject.hideFlags = flags;
        }

        private void SetStatus(string message, MessageType type)
        {
            _statusMessage = message;
            _statusType = type;
            Repaint();
        }

        private void DisposePreview()
        {
            if (_previewInstance != null)
            {
                DestroyImmediate(_previewInstance);
                _previewInstance = null;
            }
            if (_preview != null)
            {
                _preview.Cleanup();
                _preview = null;
            }
        }
    }
}
#endif
