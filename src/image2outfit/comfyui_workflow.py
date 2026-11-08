"""Convert pinned ComfyUI template graphs into the local execution API format."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _node_id(value: object, *, label: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{label} must be a string or integer")
    result = str(value)
    if not result:
        raise ValueError(f"{label} must not be empty")
    return result


def _input_definitions(node_info: Mapping[str, Any]) -> set[str]:
    inputs = node_info.get("input", {})
    if not isinstance(inputs, Mapping):
        raise ValueError("ComfyUI node input definition must be an object")
    names: set[str] = set()
    for category in ("required", "optional"):
        definitions = inputs.get(category, {})
        if definitions is None:
            continue
        if not isinstance(definitions, Mapping):
            raise ValueError(f"ComfyUI {category} inputs must be an object")
        names.update(str(name) for name in definitions)
    return names


def ui_workflow_to_api_prompt(
    workflow: Mapping[str, Any],
    object_info: Mapping[str, Any],
    *,
    image_node_id: str,
    image_name: str,
    trellis_selector_node_id: str,
    upsample_node_id: str,
    output_node_id: str,
    output_prefix: str,
    target_resolution: int = 512,
) -> dict[str, dict[str, Any]]:
    """Create a fail-closed ``/prompt`` graph from a ComfyUI UI template.

    UI-only nodes with no connected outputs (for example Markdown notes) are
    omitted. Executable nodes and all connected links must exist in the target
    ComfyUI server's ``/object_info`` response.
    """
    if isinstance(target_resolution, bool) or not isinstance(target_resolution, int):
        raise ValueError("target_resolution must be an integer")
    if target_resolution != 512:
        raise ValueError("the pinned workflow is restricted to 512 resolution")

    raw_nodes = workflow.get("nodes")
    raw_links = workflow.get("links")
    if not isinstance(raw_nodes, list) or not isinstance(raw_links, list):
        raise ValueError("ComfyUI workflow must contain nodes and links arrays")

    nodes: dict[str, Mapping[str, Any]] = {}
    for index, raw_node in enumerate(raw_nodes):
        node = _mapping(raw_node, label=f"workflow.nodes[{index}]")
        node_id = _node_id(node.get("id"), label=f"workflow.nodes[{index}].id")
        if node_id in nodes:
            raise ValueError(f"duplicate ComfyUI node id: {node_id}")
        nodes[node_id] = node

    links: dict[str, tuple[str, int]] = {}
    for index, raw_link in enumerate(raw_links):
        if not isinstance(raw_link, (list, tuple)) or len(raw_link) < 5:
            raise ValueError(f"workflow.links[{index}] must contain at least five items")
        link_id = _node_id(raw_link[0], label=f"workflow.links[{index}].id")
        source_id = _node_id(raw_link[1], label=f"workflow.links[{index}].source")
        output_slot = raw_link[2]
        if (
            isinstance(output_slot, bool)
            or not isinstance(output_slot, int)
            or output_slot < 0
        ):
            raise ValueError(f"workflow.links[{index}].source slot is invalid")
        target_id = _node_id(raw_link[3], label=f"workflow.links[{index}].target")
        if link_id in links:
            raise ValueError(f"duplicate ComfyUI link id: {link_id}")
        if source_id not in nodes or target_id not in nodes:
            raise ValueError(f"workflow link {link_id} references a missing node")
        links[link_id] = (source_id, output_slot)

    executable: dict[str, Mapping[str, Any]] = {}
    for node_id, node in nodes.items():
        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            raise ValueError(f"workflow node {node_id} has no type")
        if node_type in object_info:
            executable[node_id] = node
            continue
        raw_outputs = node.get("outputs", [])
        outputs = raw_outputs if isinstance(raw_outputs, list) else []
        outgoing = any(
            isinstance(output, Mapping)
            and isinstance(output.get("links"), list)
            and output["links"]
            for output in outputs
        )
        if outgoing:
            raise ValueError(
                f"ComfyUI node {node_id} ({node_type}) is unavailable but has connected outputs"
            )

    prompt: dict[str, dict[str, Any]] = {}
    for node_id, node in executable.items():
        node_type = str(node["type"])
        node_info = _mapping(object_info[node_type], label=f"object_info.{node_type}")
        api_inputs: dict[str, Any] = {}
        connected_names: set[str] = set()
        raw_inputs = node.get("inputs", [])
        if not isinstance(raw_inputs, list):
            raise ValueError(f"workflow node {node_id}.inputs must be an array")
        for input_index, raw_input in enumerate(raw_inputs):
            ui_input = _mapping(
                raw_input,
                label=f"workflow.nodes[{node_id}].inputs[{input_index}]",
            )
            name = ui_input.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError(f"workflow node {node_id} has an input without a name")
            link_value = ui_input.get("link")
            if link_value is not None:
                link_id = _node_id(link_value, label=f"workflow node {node_id}.{name}.link")
                if link_id not in links:
                    raise ValueError(f"workflow node {node_id}.{name} references a missing link")
                source_id, output_slot = links[link_id]
                if source_id not in executable:
                    raise ValueError(
                        f"workflow node {node_id}.{name} references a non-executable node"
                    )
                api_inputs[name] = [source_id, output_slot]
                connected_names.add(name)

        widget_values = node.get("widgets_values_named", {})
        if widget_values is None:
            widget_values = {}
        widget_map = _mapping(
            widget_values,
            label=f"workflow node {node_id}.widgets_values_named",
        )
        for name in _input_definitions(node_info):
            if name in connected_names or name not in widget_map:
                continue
            api_inputs[name] = widget_map[name]

        if node_id == image_node_id:
            if "image" not in _input_definitions(node_info):
                raise ValueError("pinned ComfyUI image node has no image input")
            api_inputs["image"] = image_name
        if node_id == trellis_selector_node_id:
            if "value" not in _input_definitions(node_info):
                raise ValueError("pinned TRELLIS selector has no value input")
            api_inputs["value"] = True
        if node_id == upsample_node_id:
            if "target_resolution" not in _input_definitions(node_info):
                raise ValueError(
                    "pinned TRELLIS upsample node has no target_resolution input"
                )
            api_inputs["target_resolution"] = target_resolution
        if node_id == output_node_id:
            if "filename_prefix" not in _input_definitions(node_info):
                raise ValueError("pinned ComfyUI output node has no filename_prefix input")
            api_inputs["filename_prefix"] = output_prefix

        prompt[node_id] = {"class_type": node_type, "inputs": api_inputs}

    for required_id in (
        image_node_id,
        trellis_selector_node_id,
        upsample_node_id,
        output_node_id,
    ):
        if required_id not in prompt:
            raise ValueError(
                f"pinned workflow is missing required executable node {required_id}"
            )
    for node_id, node in executable.items():
        for raw_input in node.get("inputs", []):
            if not isinstance(raw_input, Mapping) or raw_input.get("link") is None:
                continue
            source_id, _ = links[str(raw_input["link"])]
            if source_id not in prompt:
                raise ValueError(f"workflow node {node_id} refers to omitted node {source_id}")
    return prompt
