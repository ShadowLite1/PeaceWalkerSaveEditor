from __future__ import annotations

import os

os.environ.setdefault("WGPU_BACKEND_TYPE", "Vulkan")

import numpy as np
import wgpu
from PIL import Image


SHADER = """
struct VertexOut {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@location(0) position: vec3<f32>, @location(1) uv: vec2<f32>) -> VertexOut {
    var out: VertexOut;
    out.position = vec4<f32>(position, 1.0);
    out.uv = uv;
    return out;
}

@group(0) @binding(0) var image_sampler: sampler;
@group(0) @binding(1) var image_texture: texture_2d<f32>;

@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    let color = textureSample(image_texture, image_sampler, in.uv);
    if color.a < 0.01 {
        discard;
    }
    return color;
}
"""


class VulkanRenderer:
    def __init__(self) -> None:
        self.adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        if self.adapter.info.get("backend_type") != "Vulkan":
            raise RuntimeError(f"Vulkan adapter unavailable ({self.adapter.summary})")
        self.device = self.adapter.request_device_sync()
        shader = self.device.create_shader_module(code=SHADER)
        self.pipeline = self.device.create_render_pipeline(
            layout="auto",
            vertex={
                "module": shader,
                "entry_point": "vs_main",
                "buffers": [{
                    "array_stride": 20,
                    "step_mode": "vertex",
                    "attributes": [
                        {"format": "float32x3", "offset": 0, "shader_location": 0},
                        {"format": "float32x2", "offset": 12, "shader_location": 1},
                    ],
                }],
            },
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            depth_stencil={
                "format": "depth24plus", "depth_write_enabled": True,
                "depth_compare": "greater",
            },
            fragment={
                "module": shader,
                "entry_point": "fs_main",
                "targets": [{
                    "format": "rgba8unorm",
                    "blend": {
                        "color": {"src_factor": "src-alpha", "dst_factor": "one-minus-src-alpha", "operation": "add"},
                        "alpha": {"src_factor": "one", "dst_factor": "one-minus-src-alpha", "operation": "add"},
                    },
                }],
            },
        )
        self.sampler = self.device.create_sampler(
            mag_filter="nearest", min_filter="nearest", mipmap_filter="nearest",
            address_mode_u="repeat", address_mode_v="repeat",
        )
        self.texture_cache = {}
        self.solid_cache = {}
        self.target_size = None
        self.target = None
        self.target_view = None
        self.depth = None
        self.depth_view = None
        self.vertex_buffer = None
        self.vertex_capacity = 0

    @property
    def name(self) -> str:
        return self.adapter.summary

    def _bind_image(self, image: Image.Image):
        key = id(image)
        cached = self.texture_cache.get(key)
        if cached is not None:
            return cached
        rgba = np.ascontiguousarray(image.convert("RGBA"), dtype=np.uint8)
        height, width = rgba.shape[:2]
        texture = self.device.create_texture(
            size=(width, height, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
        )
        self.device.queue.write_texture(
            {"texture": texture}, rgba,
            {"offset": 0, "bytes_per_row": width * 4, "rows_per_image": height},
            (width, height, 1),
        )
        bind = self.device.create_bind_group(
            layout=self.pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": self.sampler},
                {"binding": 1, "resource": texture.create_view()},
            ],
        )
        self.texture_cache[key] = bind
        return bind

    def _solid_image(self, color: str) -> Image.Image:
        image = self.solid_cache.get(color)
        if image is None:
            rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
            image = Image.new("RGBA", (1, 1), rgb + (255,))
            self.solid_cache[color] = image
        return image

    def _ensure_targets(self, width: int, height: int) -> None:
        if self.target_size == (width, height):
            return
        self.target_size = (width, height)
        self.target = self.device.create_texture(
            size=(width, height, 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC,
        )
        self.target_view = self.target.create_view()
        self.depth = self.device.create_texture(
            size=(width, height, 1), format="depth24plus",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
        )
        self.depth_view = self.depth.create_view()

    def _upload_vertices(self, vertex_data: np.ndarray):
        byte_count = vertex_data.nbytes
        if self.vertex_buffer is None or byte_count > self.vertex_capacity:
            self.vertex_capacity = max(byte_count, self.vertex_capacity * 2, 4096)
            self.vertex_buffer = self.device.create_buffer(
                size=self.vertex_capacity,
                usage=wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST,
            )
        self.device.queue.write_buffer(self.vertex_buffer, 0, vertex_data)
        return self.vertex_buffer

    def render(self, faces, width: int, height: int) -> Image.Image:
        ordered = sorted(faces, key=lambda item: item[0])
        vertices = []
        images = []
        all_depths = [depth for face in ordered for depth in face[2]]
        depth_min = min(all_depths, default=0.0)
        depth_span = max(all_depths, default=1.0) - depth_min or 1.0
        for _, screen, depths, color, texture, uvs in ordered:
            for (x, y), depth, uv in zip(screen, depths, uvs):
                z = (depth - depth_min) / depth_span
                vertices.append((x * 2.0 / width - 1.0, 1.0 - y * 2.0 / height, z, uv[0], uv[1]))
            images.append(texture or self._solid_image(color))
        self._ensure_targets(width, height)
        encoder = self.device.create_command_encoder()
        render_pass = encoder.begin_render_pass(color_attachments=[{
            "view": self.target_view, "resolve_target": None,
            "clear_value": (23 / 255, 25 / 255, 28 / 255, 1),
            "load_op": "clear", "store_op": "store",
        }], depth_stencil_attachment={
            "view": self.depth_view, "depth_clear_value": 0.0,
            "depth_load_op": "clear", "depth_store_op": "discard",
        })
        if vertices:
            vertex_data = np.asarray(vertices, dtype=np.float32)
            buffer = self._upload_vertices(vertex_data)
            render_pass.set_pipeline(self.pipeline)
            render_pass.set_vertex_buffer(0, buffer)
            for index, image in enumerate(images):
                render_pass.set_bind_group(0, self._bind_image(image))
                render_pass.draw(3, 1, index * 3, 0)
        render_pass.end()
        self.device.queue.submit([encoder.finish()])
        pixels = self.device.queue.read_texture(
            {"texture": self.target},
            {"offset": 0, "bytes_per_row": width * 4, "rows_per_image": height},
            (width, height, 1),
        )
        array = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)
        return Image.fromarray(array, "RGBA").convert("RGB")
