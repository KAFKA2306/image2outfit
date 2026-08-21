#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using UnityEngine;

namespace GenWorks.Editor
{
    [CreateAssetMenu(
        fileName = "GenWorksPreviewPreset",
        menuName = "GenWorks/Wardrobe Preview Preset"
    )]
    internal sealed class GenWorksPreviewPreset : ScriptableObject
    {
        [Serializable]
        internal sealed class TransformPose
        {
            public string path;
            public Vector3 localPosition;
            public Quaternion localRotation = Quaternion.identity;
            public Vector3 localScale = Vector3.one;
        }

        public Vector2 cameraOrbit = new Vector2(12f, 180f);
        public float cameraDistance = 2.2f;
        public float fieldOfView = 30f;
        public Vector3 pivotOffset = Vector3.zero;
        public List<TransformPose> pose = new List<TransformPose>();
    }
}
#endif
