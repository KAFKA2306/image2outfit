#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace GenWorks.Editor
{
    internal sealed class GenWorksCatalogWindow : EditorWindow
    {
        private const string ProductRoot = "Assets/GenWorks/Products";
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
            public string documentationPath;
            public string demoScenePath;
            public string sourceJobPath;
        }

        private sealed class ProductEntry
        {
            public string ManifestPath;
            public ProductManifest Manifest;
            public readonly List<string> Errors = new List<string>();
            public readonly List<string> Warnings = new List<string>();
        }

        private readonly List<ProductEntry> _products = new List<ProductEntry>();
        private Vector2 _scroll;
        private string _search = string.Empty;
        private bool _showOnlyAttention;

        [MenuItem("GenWorks/Product Catalog", priority = 10)]
        private static void Open()
        {
            var window = GetWindow<GenWorksCatalogWindow>();
            window.titleContent = new GUIContent("GenWorks Catalog");
            window.minSize = new Vector2(720f, 420f);
            window.Refresh();
            window.Show();
        }

        [MenuItem("GenWorks/Select Canonical Root", priority = 11)]
        private static void SelectRoot()
        {
            var root = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>("Assets/GenWorks");
            Selection.activeObject = root;
            EditorGUIUtility.PingObject(root);
        }

        private void OnEnable()
        {
            Refresh();
        }

        private void OnGUI()
        {
            DrawToolbar();
            EditorGUILayout.Space(6f);

            if (!AssetDatabase.IsValidFolder(ProductRoot))
            {
                EditorGUILayout.HelpBox(
                    $"Canonical product root is missing: {ProductRoot}",
                    MessageType.Error
                );
                return;
            }

            var visible = _products.Where(MatchesFilter).ToArray();
            EditorGUILayout.LabelField(
                $"Products: {visible.Length} / {_products.Count}",
                EditorStyles.boldLabel
            );
            _scroll = EditorGUILayout.BeginScrollView(_scroll);
            foreach (var product in visible)
            {
                DrawProduct(product);
                EditorGUILayout.Space(8f);
            }
            EditorGUILayout.EndScrollView();
        }

        private void DrawToolbar()
        {
            using (new EditorGUILayout.HorizontalScope(EditorStyles.toolbar))
            {
                if (
                    GUILayout.Button(
                        "Refresh",
                        EditorStyles.toolbarButton,
                        GUILayout.Width(64f)
                    )
                )
                    Refresh();
                if (
                    GUILayout.Button(
                        "Validate All",
                        EditorStyles.toolbarButton,
                        GUILayout.Width(84f)
                    )
                )
                    ValidateAllAndLog();
                if (
                    GUILayout.Button(
                        "Select Root",
                        EditorStyles.toolbarButton,
                        GUILayout.Width(78f)
                    )
                )
                    SelectRoot();
                GUILayout.Space(8f);
                _search = GUILayout.TextField(
                    _search ?? string.Empty,
                    GUI.skin.FindStyle("ToolbarSearchTextField"),
                    GUILayout.MinWidth(180f)
                );
                _showOnlyAttention = GUILayout.Toggle(
                    _showOnlyAttention,
                    "Needs attention",
                    EditorStyles.toolbarButton,
                    GUILayout.Width(104f)
                );
            }
        }

        private bool MatchesFilter(ProductEntry entry)
        {
            if (
                _showOnlyAttention
                && entry.Errors.Count == 0
                && entry.Warnings.Count == 0
            )
                return false;
            if (string.IsNullOrWhiteSpace(_search))
                return true;
            var value = _search.Trim();
            return Contains(entry.Manifest?.productId, value)
                || Contains(entry.Manifest?.productName, value)
                || Contains(entry.Manifest?.targetAdapterId, value)
                || Contains(entry.Manifest?.status, value);
        }

        private static bool Contains(string source, string value)
        {
            return !string.IsNullOrEmpty(source)
                && source.IndexOf(value, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static void DrawProduct(ProductEntry entry)
        {
            var manifest = entry.Manifest;
            using (new EditorGUILayout.VerticalScope(EditorStyles.helpBox))
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    EditorGUILayout.LabelField(
                        string.IsNullOrWhiteSpace(manifest?.productName)
                            ? entry.ManifestPath
                            : manifest.productName,
                        EditorStyles.boldLabel
                    );
                    GUILayout.FlexibleSpace();
                    GUILayout.Label(
                        manifest?.status ?? "INVALID",
                        EditorStyles.miniBoldLabel,
                        GUILayout.Width(120f)
                    );
                }

                if (manifest != null)
                {
                    EditorGUILayout.LabelField(
                        "Product ID",
                        manifest.productId ?? string.Empty
                    );
                    EditorGUILayout.LabelField(
                        "Target",
                        manifest.targetAdapterId ?? string.Empty
                    );
                    EditorGUILayout.LabelField(
                        "Root",
                        manifest.productRoot ?? string.Empty
                    );
                }

                foreach (var error in entry.Errors)
                    EditorGUILayout.HelpBox(error, MessageType.Error);
                foreach (var warning in entry.Warnings)
                    EditorGUILayout.HelpBox(warning, MessageType.Warning);

                using (new EditorGUILayout.HorizontalScope())
                {
                    DrawAssetButton("Outfit Prefab", manifest?.outfitPrefabPath);
                    DrawAssetButton("Integrated", manifest?.integratedPrefabPath);
                    DrawAssetButton("Preview", manifest?.previewPath);
                    DrawAssetButton("Demo", manifest?.demoScenePath);
                    DrawAssetButton("Documentation", manifest?.documentationPath);
                    if (GUILayout.Button("Folder", GUILayout.Width(74f)))
                        RevealProductFolder(entry.ManifestPath);
                    if (GUILayout.Button("Manifest", GUILayout.Width(74f)))
                        SelectAsset(entry.ManifestPath);
                }
            }
        }

        private static void DrawAssetButton(string label, string path)
        {
            using (
                new EditorGUI.DisabledScope(
                    string.IsNullOrWhiteSpace(path)
                        || AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(path) == null
                )
            )
            {
                if (GUILayout.Button(label, GUILayout.MinWidth(84f)))
                    SelectAsset(path);
            }
        }

        private static void SelectAsset(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
                return;
            var asset = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(path);
            if (asset == null)
                return;
            Selection.activeObject = asset;
            EditorGUIUtility.PingObject(asset);
            if (asset is SceneAsset)
                AssetDatabase.OpenAsset(asset);
        }

        private static void RevealProductFolder(string manifestPath)
        {
            var folder = Path.GetDirectoryName(manifestPath)?.Replace('\\', '/');
            if (string.IsNullOrWhiteSpace(folder))
                return;
            EditorUtility.RevealInFinder(Path.GetFullPath(folder));
        }

        private void Refresh()
        {
            _products.Clear();
            if (!AssetDatabase.IsValidFolder(ProductRoot))
            {
                Repaint();
                return;
            }

            foreach (
                var guid in AssetDatabase.FindAssets(
                    "t:TextAsset",
                    new[] { ProductRoot }
                )
            )
            {
                var path = AssetDatabase.GUIDToAssetPath(guid);
                if (
                    !string.Equals(
                        Path.GetFileName(path),
                        ManifestName,
                        StringComparison.OrdinalIgnoreCase
                    )
                )
                    continue;
                _products.Add(LoadEntry(path));
            }

            _products.Sort(
                (left, right) =>
                    string.Compare(
                        left.Manifest?.productName ?? left.ManifestPath,
                        right.Manifest?.productName ?? right.ManifestPath,
                        StringComparison.OrdinalIgnoreCase
                    )
            );
            Repaint();
        }

        private static ProductEntry LoadEntry(string path)
        {
            var entry = new ProductEntry { ManifestPath = path };
            try
            {
                var text = AssetDatabase.LoadAssetAtPath<TextAsset>(path);
                if (text == null)
                {
                    entry.Errors.Add("Manifest could not be loaded as TextAsset.");
                    return entry;
                }
                entry.Manifest = JsonUtility.FromJson<ProductManifest>(text.text);
                Validate(entry);
            }
            catch (Exception exception)
            {
                entry.Errors.Add($"Manifest parse failed: {exception.Message}");
            }
            return entry;
        }

        private static void Validate(ProductEntry entry)
        {
            var manifest = entry.Manifest;
            if (manifest == null)
            {
                entry.Errors.Add("Manifest is empty.");
                return;
            }
            if (manifest.schemaVersion != 1)
                entry.Errors.Add("schemaVersion must be 1.");
            if (string.IsNullOrWhiteSpace(manifest.productId))
                entry.Errors.Add("productId is required.");
            var expectedRoot = Path.GetDirectoryName(entry.ManifestPath)?.Replace(
                '\\',
                '/'
            );
            if (
                !string.Equals(
                    expectedRoot,
                    manifest.productRoot,
                    StringComparison.Ordinal
                )
            )
                entry.Errors.Add($"productRoot must be {expectedRoot}.");

            ValidateAssetField(
                entry,
                "outfitPrefabPath",
                manifest.outfitPrefabPath,
                false
            );
            ValidateAssetField(
                entry,
                "integratedPrefabPath",
                manifest.integratedPrefabPath,
                true
            );
            ValidateAssetField(entry, "previewPath", manifest.previewPath, true);
            ValidateAssetField(
                entry,
                "documentationPath",
                manifest.documentationPath,
                true
            );
            ValidateAssetField(
                entry,
                "demoScenePath",
                manifest.demoScenePath,
                true
            );
        }

        private static void ValidateAssetField(
            ProductEntry entry,
            string field,
            string path,
            bool optional
        )
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                if (!optional)
                    entry.Warnings.Add($"{field} is not set yet.");
                return;
            }
            if (
                !path.StartsWith(
                    entry.Manifest.productRoot + "/",
                    StringComparison.Ordinal
                )
            )
            {
                entry.Errors.Add(
                    $"{field} must stay inside the product root: {path}"
                );
                return;
            }
            if (AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(path) == null)
                entry.Warnings.Add($"{field} is missing: {path}");
        }

        private void ValidateAllAndLog()
        {
            Refresh();
            var errors = _products.Sum(product => product.Errors.Count);
            var warnings = _products.Sum(product => product.Warnings.Count);
            var summary = $"GenWorks catalog: {_products.Count} products, {errors} errors, {warnings} warnings.";
            if (errors > 0)
                Debug.LogError(summary);
            else if (warnings > 0)
                Debug.LogWarning(summary);
            else
                Debug.Log(summary);
        }
    }
}
#endif
