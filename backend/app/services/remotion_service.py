"""
Remotion Rendering Service
Renders premium animation templates via Remotion CLI and overlays them on video using FFmpeg.
"""
import os
import json
import subprocess
import asyncio
from pathlib import Path

REMOTION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "remotion"))

TEMPLATE_MAP = {
    "cinematic": "CinematicDark",
    "blueprint": "TechBlueprint",
    "liquid": "LiquidOrganic",
}


async def render_remotion_overlay(
    composition_id: str,
    props: dict,
    output_path: str,
    duration_frames: int = 90,
) -> bool:
    """
    Calls Remotion CLI to render a transparent WebM animation overlay.
    Returns True if successful.
    """
    # Write props to a temp JSON file (avoids Windows quote-escaping issues)
    props_file = os.path.join(REMOTION_DIR, "props", "_render_props.json")
    os.makedirs(os.path.dirname(props_file), exist_ok=True)
    with open(props_file, "w", encoding="utf-8") as f:
        json.dump(props, f, ensure_ascii=False)

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        composition_id,
        output_path,
        f"--props={props_file}",
        "--frames", f"0-{duration_frames - 1}",
        "--codec", "vp8",              # WebM with transparency
        "--pixel-format", "yuva420p",  # Keeps alpha channel
        "--log", "error",
    ]

    print(f"[Remotion] Rendering {composition_id} → {output_path}")
    try:
        result = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=REMOTION_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await result.communicate()
        if result.returncode != 0:
            print(f"[Remotion] ❌ Error: {stderr.decode()}")
            return False
        print(f"[Remotion] ✅ Rendered: {output_path}")
        return True
    except Exception as e:
        print(f"[Remotion] ❌ Exception: {e}")
        return False


async def overlay_remotion_on_video(
    base_video: str,
    overlay_webm: str,
    output_path: str,
    start_time: float,
    position: str = "top-right",
    overlay_width: int = 640,
) -> bool:
    """
    Overlays a transparent WebM (Remotion render) onto a base video at a specific
    timestamp and position using FFmpeg.
    """
    # Position math
    positions = {
        "top-right":    f"W-w-60:60",
        "top-left":     f"60:60",
        "bottom-right": f"W-w-60:H-h-60",
        "bottom-left":  f"60:H-h-60",
        "center":       f"(W-w)/2:(H-h)/2",
    }
    pos_expr = positions.get(position, positions["top-right"])

    # Scale the overlay to desired width, keeping aspect ratio
    scale_filter = f"scale={overlay_width}:-1"

    # FFmpeg complex filter:
    # [1:v] = overlay webm, scale it, then delay its PTS to start_time
    # overlay it on top of [0:v] only during that time window
    overlay_duration = 3.0  # 90 frames @ 30fps
    enable_expr = f"between(t,{start_time},{start_time + overlay_duration})"

    filter_complex = (
        f"[1:v]{scale_filter},setpts=PTS-STARTPTS+{start_time}/TB[ovr];"
        f"[0:v][ovr]overlay={pos_expr}:enable='{enable_expr}'[out]"
    )

    cmd = [
        "ffmpeg",
        "-i", base_video,
        "-i", overlay_webm,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        output_path,
        "-y",
        "-loglevel", "error",
    ]

    print(f"[Remotion] Overlaying at t={start_time}s pos={position}")
    try:
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await result.communicate()
        if result.returncode != 0:
            print(f"[FFmpeg Overlay] ❌ {stderr.decode()}")
            return False
        print(f"[FFmpeg Overlay] ✅ Done: {output_path}")
        return True
    except Exception as e:
        print(f"[FFmpeg Overlay] ❌ Exception: {e}")
        return False


async def apply_motion_graphic(
    base_video: str,
    output_path: str,
    style: str,
    text: str,
    subtext: str = "",
    start_time: float = 0.0,
    position: str = "top-right",
    accent_color: str = "#a78bfa",
    tmp_dir: str = "uploads",
) -> bool:
    """
    Full pipeline: Renders a Remotion template and overlays it onto video.
    Called from the video rendering service when 'add_motion_graphic' action is found.
    """
    composition_id = TEMPLATE_MAP.get(style, "CinematicDark")
    overlay_tmp = os.path.join(tmp_dir, f"remotion_overlay_{style}_{int(start_time*10)}.webm")

    props = {
        "styleType": style,
        "text": text.upper(),
        "subtext": subtext.upper(),
        "accentColor": accent_color,
    }

    # Step 1: Render the Remotion animation to a transparent WebM
    ok = await render_remotion_overlay(composition_id, props, overlay_tmp)
    if not ok:
        print(f"[MotionGraphic] Remotion render failed, skipping overlay")
        return False

    # Step 2: Overlay the WebM onto the base video
    ok = await overlay_remotion_on_video(
        base_video=base_video,
        overlay_webm=overlay_tmp,
        output_path=output_path,
        start_time=start_time,
        position=position,
    )

    # Cleanup temp file
    if os.path.exists(overlay_tmp):
        os.remove(overlay_tmp)

    return ok
