#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace GenWorks.Editor
{
    public static class GenWorksMaterialExtractor
    {
        [Serializable]
        private sealed class Job
        {
            public string id;
            public string productRoot;
            public string fbxAssetPath;
            public string prefabAssetPath;
            public string integratedPrefabAssetPath;
            public string artifactDir;
        }

        [Serializable]
        private sealed class Report
        {
            public bool passed;
            public string checkedAt;
            public string jobId;
            public string materialDirectory;
            public List<string> materialAssets = new List<string>();
            public List<string> remappedPrefabs = new List<string>();
            public List<string> errors = new List<string>();
        }

        public static void RunFromCommandLine()
        {
            var report = new Report { checkedAt = DateTime.UtcNow.ToString("O") };
            try
            {
                var jobPath = GetArgument("-image2outfitJob");
                if (string.IsNullOrWhiteSpace(jobPath) || !File.Exists(jobPath))
                    throw new FileNotFoundException("-image2outfitJob is required", jobPath);
                var job = JsonUtility.FromJson<Job>(File.ReadAllText(jobPath));
                if (job == null)
                    throw new InvalidDataException("job.json could not be parsed");
                report.jobId = job.id;
                if (string.IsNullOrWhiteSpace(job.productRoot))
                    throw new InvalidDataException("productRoot is required for material extraction");
                report.materialDirectory = job.productRoot.TrimEnd('/') + "/Materials";
                EnsureFolder(report.materialDirectory);

                var imported = AssetDatabase.LoadAllAssetsAtPath(job.fbxAssetPath)
                    .OfType<Material>()
                    .Where(material => material != null)
                    .GroupBy(material => material.name, StringComparer.Ordinal)
                    .Select(group => group.First())
                    .ToArray();
                if (imported.Length == 0)
                    throw new InvalidDataException("FBX did not expose imported materials");

                var replacements = new Dictionary<string, Material>(StringComparer.Ordinal);
                foreach (var source in imported)
                {
                    var assetPath = report.materialDirectory + "/" + SafeName(source.name) + ".mat";
                    var existing = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
                    if (existing == null)
                    {
                        existing = new Material(source) { name = source.name };
                        AssetDatabase.CreateAsset(existing, assetPath);
                    }
                    else
                    {
                        EditorUtility.CopySerialized(source, existing);
                        existing.name = source.name;
                        EditorUtility.SetDirty(existing);
                    }
                    replacements[source.name] = existing;
                    report.materialAssets.Add(assetPath);
                }

                RemapPrefab(job.prefabAssetPath, replacements, report, true);
                RemapPrefab(job.integratedPrefabAssetPath, replacements, report, false);
                AssetDatabase.SaveAssets();
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
                report.passed = report.errors.Count == 0;
                WriteReport(job, report);
                EditorApplication.Exit(report.passed ? 0 : 2);
            }
            catch (Exception exception)
            {
                report.errors.Add(exception.GetType().Name + ": " + exception.Message);
                Debug.LogException(exception);
                var fallback = GetArgument("-image2outfitArtifactDir");
                if (!string.IsNullOrWhiteSpace(fallback))
                {
                    Directory.CreateDirectory(fallback);
                    File.WriteAllText(
                        Path.Combine(fallback, "materials.json"),
                        JsonUtility.ToJson(report, true)
                    );
                }
                EditorApplication.Exit(1);
            }
        }

        private static void RemapPrefab(
            string prefabPath,
            IReadOnlyDictionary<string, Material> replacements,
            Report report,
            bool requireEveryMaterial)
        {
            if (string.IsNullOrWhiteSpace(prefabPath))
                return;
            var root = PrefabUtility.LoadPrefabContents(prefabPath);
            if (root == null)
            {
                report.errors.Add("could not load prefab: " + prefabPath);
                return;
            }
            try
            {
                var changed = false;
                foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
                {
                    var materials = renderer.sharedMaterials;
                    for (var index = 0; index < materials.Length; index++)
                    {
                        var current = materials[index];
                        if (current == null)
                        {
                            if (requireEveryMaterial)
                                report.errors.Add("missing material on " + renderer.name);
                            continue;
                        }
                        if (replacements.TryGetValue(current.name, out var replacement))
                        {
                            materials[index] = replacement;
                            changed = true;
                        }
                        else if (requireEveryMaterial)
                        {
                            report.errors.Add(
                                $"no extracted material for {current.name} on {renderer.name}"
                            );
                        }
                    }
                    renderer.sharedMaterials = materials;
                }
                if (changed)
                {
                    PrefabUtility.SaveAsPrefabAsset(root, prefabPath);
                    report.remappedPrefabs.Add(prefabPath);
                }
            }
            finally
            {
                PrefabUtility.UnloadPrefabContents(root);
            }
        }

        private static void WriteReport(Job job, Report report)
        {
            var directory = Path.GetFullPath(job.artifactDir);
            Directory.CreateDirectory(directory);
            File.WriteAllText(
                Path.Combine(directory, "materials.json"),
                JsonUtility.ToJson(report, true)
            );
        }

        private static string SafeName(string value)
        {
            foreach (var character in Path.GetInvalidFileNameChars())
                value = value.Replace(character, '_');
            return string.IsNullOrWhiteSpace(value) ? "Material" : value;
        }

        private static void EnsureFolder(string assetPath)
        {
            var parts = assetPath.Split('/');
            var current = parts[0];
            for (var index = 1; index < parts.Length; index++)
            {
                var next = current + "/" + parts[index];
                if (!AssetDatabase.IsValidFolder(next))
                    AssetDatabase.CreateFolder(current, parts[index]);
                current = next;
            }
        }

        private static string GetArgument(string name)
        {
            var arguments = Environment.GetCommandLineArgs();
            for (var index = 0; index + 1 < arguments.Length; index++)
                if (arguments[index] == name)
                    return arguments[index + 1];
            return null;
        }
    }
}
#endif
