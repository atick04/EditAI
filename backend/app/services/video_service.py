import ffmpeg
import os
import json
import subprocess
import argparse
from app.services.pexels_service import download_broll

def format_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cents = int((seconds - int(seconds)) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"

def get_animation_tag(style: str) -> str:
    """Return ASS override tags for the given animation preset."""
    # All positions are in PlayRes space: 1080x1920
    styles = {
        # Simple fade in/out — universally safe
        "fade":       r"{\fad(250,200)}",
        # TikTok pop — scale from 130% + alpha, snap to normal
        "pop":        r"{\fscx130\fscy130\alpha&HFF&\t(0,300,\fscx100\fscy100\alpha&H00&)}",
        # Slide from below — works for bottom alignment (alignment=2, marginV~250)
        "slide_up":   r"{\move(540,1820,540,1670,0,400)\fad(300,80)}",
        # Bounce — overshoot scale spring
        "bounce":     r"{\fscx140\fscy140\fad(100,0)\t(0,180,\fscx90\fscy90)\t(180,320,\fscx108\fscy108)\t(320,430,\fscx98\fscy98)\t(430,520,\fscx100\fscy100)}",
        # Glow burst — blur dissolves in
        "glow":       r"{\blur30\alpha&H88&\t(0,400,\blur0\alpha&H00&)}",
        # No animation (still karaoke word-highlight via \k tags)
        "karaoke":    "",
    }
    return styles.get(style, styles["fade"])

def generate_ass(transcript, filepath, position="center", font="Impact", font_size=110, use_outline=True, font_color="White", cuts=None, animation_style="fade"):
    """Generate ASS subtitle file, adjusting timing for cut_out edits and injecting animation tags."""
    cuts = sorted(cuts or [], key=lambda c: c.get('start', 0))
    
    def remap_time(t):
        """Shift time t by the total duration of all cuts that start before t."""
        shift = 0.0
        for cut in cuts:
            cs, ce = cut.get('start', 0), cut.get('end', 0)
            if cs >= t:
                break
            # How much of this cut region is before t?
            shift += min(ce, t) - cs
        return max(0.0, t - shift)
    
    def in_cut(start, end):
        """Return True if the word/segment overlaps with any cut region."""
        for cut in cuts:
            cs, ce = cut.get('start', 0), cut.get('end', 0)
            if start < ce and end > cs:  # Overlap
                return True
        return False

    # Premium Margin and Positioning
    alignment = 5
    margin_v = 500
    margin_l = 60
    margin_r = 60
    
    if position == "top":
        alignment = 8
        margin_v = 200
    elif position == "bottom":
        alignment = 2
        margin_v = 250
    elif position == "left":
        alignment = 4
        margin_l = 80
        margin_v = 0
    elif position == "right":
        alignment = 6
        margin_r = 80
        margin_v = 0
    elif position == "center":
        alignment = 5
        margin_v = 500

    color_map = {
        "White":  ("&H00FFFFFF", "&H00A0A0A0"),
        "Yellow": ("&H0000D7FF", "&H00A0A0A0"),
        "Green":  ("&H0055FF55", "&H00A0A0A0"),
        "Red":    ("&H005555FF", "&H00A0A0A0"),
        "Cyan":   ("&H00FFFF00", "&H00A0A0A0"),
    }
    primary_col, unlit_col = color_map.get(font_color, ("&H00FFFFFF", "&H00A0A0A0"))
    outline = 10 if use_outline else 0
    shadow = 8 if use_outline else 0
    outline_col = "&H00000000"
    shadow_col = "&HAA000000"

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Premium,{font},{font_size},{primary_col},{unlit_col},{outline_col},{shadow_col},-1,0,0,0,100,100,0,0,1,{outline},{shadow},{alignment},{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(ass_header)
        
        anim = get_animation_tag(animation_style)
        
        words = transcript.get("words", [])
        if not words:
            segments = transcript.get("segments", [])
            for seg in segments:
                s, e = seg.get("start", 0.0), seg.get("end", 0.0)
                if in_cut(s, e):
                    continue
                start = format_ass_time(remap_time(s))
                end = format_ass_time(remap_time(e))
                text = seg.get('text', '').strip()
                f.write(f"Dialogue: 0,{start},{end},Premium,,0,0,0,,{anim}{text}\n")
            return

        # Group words into chunks of 3, skip cut regions
        chunks, cur_chunk = [], []
        for w in words:
            ws, we = w.get('start', 0.0), w.get('end', 0.0)
            if in_cut(ws, we):
                # Flush current chunk before the cut
                if cur_chunk:
                    chunks.append(cur_chunk)
                    cur_chunk = []
                continue
            cur_chunk.append(w)
            if len(cur_chunk) == 3:
                chunks.append(cur_chunk)
                cur_chunk = []
        if cur_chunk:
            chunks.append(cur_chunk)
            
        for chunk in chunks:
            chunk_start = remap_time(chunk[0].get('start', 0.0))
            chunk_end = remap_time(chunk[-1].get('end', 0.0))
            
            if animation_style == "typewriter":
                # Each word gets its own line, staggered by 100ms
                for idx, w in enumerate(chunk):
                    ws = remap_time(w.get('start', 0.0))
                    we = remap_time(chunk[-1].get('end', 0.0))  # all hold until chunk end
                    word_txt = w.get('word', '').strip().upper()
                    # Build line: show words cumulatively
                    shown = " ".join(ww.get('word','').strip().upper() for ww in chunk[:idx+1])
                    s_str = format_ass_time(ws)
                    e_str = format_ass_time(we)
                    f.write(f"Dialogue: 0,{s_str},{e_str},Premium,,0,0,0,,{shown}\n")
            else:
                text_line = ""
                for w in chunk:
                    dur_cs = int((w.get('end', 0.0) - w.get('start', 0.0)) * 100)
                    word_txt = w.get('word', '').strip().upper()
                    text_line += f"{{\\k{dur_cs}}}{word_txt} "
                start_str = format_ass_time(chunk_start)
                end_str = format_ass_time(chunk_end)
                f.write(f"Dialogue: 0,{start_str},{end_str},Premium,,0,0,0,,{anim}{text_line.strip()}\n")

def extract_audio(video_path: str, output_audio_path: str) -> str:
    try:
        stream = ffmpeg.input(video_path)
        stream = ffmpeg.output(stream, output_audio_path, acodec='libmp3lame', q=4)
        ffmpeg.run(stream, overwrite_output=True, quiet=True)
        return output_audio_path
    except ffmpeg.Error as e:
        print(f"FFmpeg audio extraction error: {e.stderr.decode('utf8') if e.stderr else str(e)}")
        return ""


def apply_zoom(input_path: str, output_path: str, zoom_type: str,
               start: float, end: float, original_duration: float) -> bool:
    """
    Apply zoom-in or zoom-out to a specific segment using FFmpeg subprocess.
    Splits video into before/segment/after, applies scale+crop to the segment, then concats.
    zoom_in: scale to 150%, center-crop to original size.
    zoom_out: scale to 70%, pad with black borders.
    """
    try:
        before_out = output_path.replace('.mp4', '_z_before.mp4')
        seg_out = output_path.replace('.mp4', '_z_seg.mp4')
        after_out = output_path.replace('.mp4', '_z_after.mp4')
        list_file = output_path.replace('.mp4', '_z_list.txt')

        if zoom_type == "zoom_in":
            vf = "scale=iw*1.5:ih*1.5,crop=iw/1.5:ih/1.5"
        elif zoom_type == "zoom_out":
            vf = "scale=iw*0.7:ih*0.7,pad=iw/0.7:ih/0.7:(ow-iw)/2:(oh-ih)/2:black"
        else:
            return False

        segments = []

        if start > 0.1:
            subprocess.run([
                'ffmpeg', '-i', input_path, '-ss', '0', '-to', str(start),
                '-c', 'copy', before_out, '-y', '-loglevel', 'quiet'
            ], check=True)
            segments.append(before_out)

        subprocess.run([
            'ffmpeg', '-i', input_path,
            '-ss', str(start), '-to', str(end),
            '-vf', vf,
            '-c:v', 'libx264', '-c:a', 'aac',
            seg_out, '-y', '-loglevel', 'quiet'
        ], check=True)
        segments.append(seg_out)

        if end < original_duration - 0.1:
            subprocess.run([
                'ffmpeg', '-i', input_path, '-ss', str(end),
                '-c', 'copy', after_out, '-y', '-loglevel', 'quiet'
            ], check=True)
            segments.append(after_out)

        with open(list_file, 'w') as lf:
            for s in segments:
                lf.write(f"file '{os.path.abspath(s)}'\n")

        subprocess.run([
            'ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_file,
            '-c', 'copy', output_path, '-y', '-loglevel', 'quiet'
        ], check=True)

        for tmp in [before_out, seg_out, after_out, list_file]:
            if os.path.exists(tmp):
                os.remove(tmp)

        print(f"[Zoom] ✅ {zoom_type} applied from {start}s to {end}s")
        return True
    except Exception as e:
        print(f"[Zoom] Error: {e}")
        return False


def apply_speed_ramp(input_path: str, output_path: str, start: float, end: float,
                     speed: float, original_duration: float) -> bool:
    """
    Speed up or slow down a segment using FFmpeg setpts + atempo.
    speed > 1.0 = faster, speed < 1.0 = slower.
    This approach processes the file in Python subprocess for precision.
    """
    try:
        pts_factor = round(1.0 / speed, 4)
        tempo = round(speed, 4)
        # Clamp atempo to 0.5-2.0 range
        tempo = max(0.5, min(2.0, tempo))

        # We split: before + sped segment + after, then concat
        before_out = output_path.replace('.mp4', '_sr_before.mp4')
        seg_out = output_path.replace('.mp4', '_sr_seg.mp4')
        after_out = output_path.replace('.mp4', '_sr_after.mp4')
        list_file = output_path.replace('.mp4', '_sr_list.txt')

        segments = []
        if start > 0:
            subprocess.run([
                'ffmpeg', '-i', input_path, '-ss', '0', '-to', str(start),
                '-c', 'copy', before_out, '-y', '-loglevel', 'quiet'
            ], check=True)
            segments.append(before_out)

        subprocess.run([
            'ffmpeg', '-i', input_path,
            '-ss', str(start), '-to', str(end),
            '-vf', f'setpts={pts_factor}*PTS',
            '-af', f'atempo={tempo}',
            seg_out, '-y', '-loglevel', 'quiet'
        ], check=True)
        segments.append(seg_out)

        if end < original_duration:
            subprocess.run([
                'ffmpeg', '-i', input_path, '-ss', str(end),
                '-c', 'copy', after_out, '-y', '-loglevel', 'quiet'
            ], check=True)
            segments.append(after_out)

        with open(list_file, 'w') as f:
            for s in segments:
                f.write(f"file '{os.path.abspath(s)}'\n")

        subprocess.run([
            'ffmpeg', '-f', 'concat', '-safe', '0', '-i', list_file,
            '-c', 'copy', output_path, '-y', '-loglevel', 'quiet'
        ], check=True)

        # Cleanup temp files
        for tmp in [before_out, seg_out, after_out, list_file]:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True
    except Exception as e:
        print(f"[SpeedRamp] Error: {e}")
        return False

def build_drawtext_kwargs(text: str, start: float, end: float,
                           x: str = "(w-text_w)/2", y: str = "h*0.15",
                           fontsize: int = 72, color: str = "white") -> dict:
    """Build kwargs for FFmpeg drawtext filter."""
    safe_text = text.replace(":", "\\:")
    return {
        "text": safe_text,
        "fontsize": fontsize,
        "fontcolor": color,
        "x": x,
        "y": y,
        "enable": f"between(t,{start},{end})",
        "borderw": 4,
        "bordercolor": "black@0.8",
        "shadowx": 3,
        "shadowy": 3,
        "shadowcolor": "black@0.5",
        "font": "Arial",
    }

def render_video(input_path: str, output_path: str, transcript_data: dict, edits: list, edl: dict = None, font: str = "Arial", font_size: int = 100, use_outline: bool = True, font_color: str = "White"):
    """Advanced Rendering Pipeline using FFmpeg Concat, ASS overlays, Zoom, Speed, Text and EDL"""
    ass_path = output_path.replace(".mp4", ".ass")

    subtitle_edit = next((e for e in edits if e.get("action") == "add_subtitles"), None)
    has_subtitles = subtitle_edit is not None
    
    if has_subtitles:
        position = subtitle_edit.get("position", "center")
        font = subtitle_edit.get("font", font)
        font_size = subtitle_edit.get("font_size", font_size)
        use_outline = subtitle_edit.get("use_outline", use_outline)
        font_color = subtitle_edit.get("font_color", font_color)
        animation_style = subtitle_edit.get("animation_style", "fade")
    else:
        position = "center"
        animation_style = "fade"

    cuts = [e for e in edits if e.get("action") == "cut_out"]
    zoom_edits = [e for e in edits if e.get("action") == "camera_zoom"]
    speed_edits = [e for e in edits if e.get("action") == "speed_ramp"]
    text_overlays = [e for e in edits if e.get("action") == "add_text_overlay"]

    # Generate ASS AFTER parsing cuts so timing can be remapped
    print(f"[ASS] animation_style={animation_style}, position={position}")
    generate_ass(transcript_data, ass_path, position=position, font=font, font_size=font_size, use_outline=use_outline, font_color=font_color, cuts=cuts, animation_style=animation_style)
    safe_ass = ass_path.replace("\\", "/")

    print(f"[Render] Step 0: Probing video metadata for {input_path}")
    try:
        # ffmpeg.probe() uses subprocess without timeout - can hang on iPhone HEVC.
        # Use our own timeout-safe probe instead.
        probe_result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', input_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30
        )
        if probe_result.returncode == 0:
            probe_data = json.loads(probe_result.stdout)
            duration = float(probe_data['format']['duration'])
            video_stream = next((s for s in probe_data['streams'] if s.get('codec_type') == 'video'), {})
            width = int(video_stream.get('width', 1080))
            height = int(video_stream.get('height', 1920))
            # iPhone HEVC stores frames in landscape with rotate=90/270 metadata
            # The actual display dimensions after rotation are swapped
            rotation = int(video_stream.get('tags', {}).get('rotate', 0))
            side_data = video_stream.get('side_data_list', [])
            for sd in side_data:
                if sd.get('side_data_type') == 'Display Matrix':
                    rotation = sd.get('rotation', rotation)
            if abs(rotation) in (90, 270):
                width, height = height, width
                print(f"[Render] Detected rotation={rotation}°, display dims swapped to {width}x{height}")
        else:
            raise RuntimeError(probe_result.stderr.decode(errors='replace')[:200])
    except subprocess.TimeoutExpired:
        print(f"[Render] ⏰ ffprobe timed out! Using defaults.")
        duration = 10000.0
        width, height = 1080, 1920
    except Exception as ex:
        print(f"[Render] probe error: {ex}, using defaults")
        duration = 10000.0
        width, height = 1080, 1920
    # Ensure dimensions are even numbers (required by libx264)
    width = width if width % 2 == 0 else width - 1
    height = height if height % 2 == 0 else height - 1
    print(f"[Render] Display dimensions: {width}x{height}, duration={duration:.1f}s")

    print(f"[Render] Step 1: Speed ramp edits={len(speed_edits)}")
    working_path = input_path
    if speed_edits:
        speed_tmp = output_path.replace('.mp4', '_speed.mp4')
        for se in speed_edits:
            speed = float(se.get('speed', 1.5))
            ok = apply_speed_ramp(working_path, speed_tmp, se.get('start', 0), se.get('end', duration), speed, duration)
            if ok:
                working_path = speed_tmp
                print(f"[SpeedRamp] Applied {speed}x on [{se.get('start')}-{se.get('end')}]")

    # --- Step 1b: Camera zoom (subprocess-based) ---
    if zoom_edits:
        zoom_tmp = output_path.replace('.mp4', '_zoom.mp4')
        for ze in zoom_edits:
            zoom_type = ze.get('type', 'zoom_in')
            z_start = float(ze.get('start', 0))
            z_end = float(ze.get('end', z_start + 2.0))
            print(f"[Zoom] Applying {zoom_type} from {z_start}s to {z_end}s")
            ok = apply_zoom(working_path, zoom_tmp, zoom_type, z_start, z_end, duration)
            if ok:
                working_path = zoom_tmp

    # --- Step 2: Extract EDL tracks ---
    v1_keeps = []
    a1_keeps = []

    if edl and "v1" in edl and "a1" in edl:
        # User defined EDL tracks independent
        v_segs = edl.get("v1", [])
        a_segs = edl.get("a1", [])
        for seg in v_segs:
            v1_keeps.append((float(seg["start"]), float(seg["end"])))
        for seg in a_segs:
            a1_keeps.append((float(seg["start"]), float(seg["end"])))
    else:
        # Fallback to shared cut_outs logic
        if not cuts:
            v1_keeps.append((0.0, duration))
            a1_keeps.append((0.0, duration))
        else:
            cuts_sorted = sorted(cuts, key=lambda x: x['start'])
            current_time = 0.0
            for cut in cuts_sorted:
                if cut['start'] > current_time:
                    v1_keeps.append((current_time, cut['start']))
                    a1_keeps.append((current_time, cut['start']))
                current_time = max(current_time, cut['end'])
            if current_time < duration:
                v1_keeps.append((current_time, duration))
                a1_keeps.append((current_time, duration))

    print(f"[Render] Step 2: Building FFmpeg filter graph. v1_keeps={len(v1_keeps)}, a1_keeps={len(a1_keeps)}")
    # We must explicitly handle empty lists (meaning track is entirely muted)
    stream = ffmpeg.input(working_path)
    streams_v, streams_a = [], []

    if not v1_keeps: 
        # Create a dummy blank video if v1 is completely empty
        # A bit complex, but usually V1 is not totally empty
        pass
    else:
        for (start, end) in v1_keeps:
            # force consistent display dimensions to avoid concat 'parameters do not match'
            # (iPhone videos have rotation metadata that causes inconsistent segment sizes)
            v = (
                stream.video
                .trim(start=start, end=end)
                .setpts('PTS-STARTPTS')
                .filter('scale', width, height)
                .filter('setsar', '1')
            )
            streams_v.append(v)
            
    if not a1_keeps:
        pass
    else:
        for (start, end) in a1_keeps:
            a = stream.audio.filter('atrim', start=start, end=end).filter('asetpts', 'PTS-STARTPTS')
            streams_a.append(a)

    # Composite composite streams
    v_out = None
    a_out = None
    
    if streams_v:
        v_out = ffmpeg.concat(*streams_v, v=1, a=0) if len(streams_v) > 1 else streams_v[0]
    if streams_a:
        a_out = ffmpeg.concat(*streams_a, v=0, a=1) if len(streams_a) > 1 else streams_a[0]

    if not v_out or not a_out:
        print("[RenderEngine] Error: V1 or A1 is completely empty. Not supported in this simplified compositing format currently.")
        return False

    # --- Step 3: Camera zoom — already handled above via subprocess ---

    # --- Step 4: Text overlays (drawtext) ---
    if text_overlays:
        for to in text_overlays:
            kwargs = build_drawtext_kwargs(
                text=to.get('text', ''),
                start=float(to.get('start', 0)),
                end=float(to.get('end', 3)),
                fontsize=int(to.get('fontsize', 72)),
                color=to.get('color', 'white')
            )
            v_out = v_out.drawtext(**kwargs)

    # --- Step 4.25: Motion Graphics via Remotion (Premium Quality) ---
    motion_edits = [e for e in edits if e.get("action") == "add_motion_graphic"]
    if motion_edits:
        for me in motion_edits:
            text = me.get("text", "Info")
            subtext = me.get("subtext", "")
            start = float(me.get("start", 0))
            end = float(me.get("end", start + 3))
            position = me.get("position", "top-right")
            style = me.get("style", "cinematic")  # cinematic | blueprint | liquid
            accent = me.get("accent_color", "#a78bfa")

            # Map position to FFmpeg overlay expression
            pos_map = {
                "top-right":    "W-w-60:60",
                "top-left":     "60:60",
                "bottom-right": "W-w-60:H-h-60",
                "bottom-left":  "60:H-h-60",
                "center":       "(W-w)/2:(H-h)/2",
                "left":         "60:(H-h)/2",
                "right":        "W-w-60:(H-h)/2",
            }
            pos_expr = pos_map.get(position, pos_map["top-right"])
            duration_sec = end - start
            duration_frames = min(89, max(30, int(duration_sec * 30)))  # Cap at 89 (composition is 90 frames)

            # Remotion dir
            remotion_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "remotion")
            )
            comp_map = {"cinematic": "CinematicDark", "blueprint": "TechBlueprint", "liquid": "LiquidOrganic"}
            composition = comp_map.get(style, "CinematicDark")

            # Write props JSON (avoids Windows quote-escaping issues)
            props_file = os.path.join(remotion_dir, "props", "_render_props.json")
            os.makedirs(os.path.dirname(props_file), exist_ok=True)
            import json as _json
            with open(props_file, "w", encoding="utf-8") as _f:
                _json.dump({
                    "styleType": style,
                    "text": text.upper(),
                    "subtext": subtext.upper(),
                    "accentColor": accent,
                    "transparent": True,   # Overlay mode: only the card, no background
                }, _f, ensure_ascii=False)

            overlay_path = os.path.abspath(working_path.replace(".mp4", f"_remotion_{int(start)}.webm"))
            overlay_output = os.path.abspath(working_path.replace(".mp4", f"_after_mg_{int(start)}.mp4"))

            print(f"[MotionGraphic] Rendering Remotion {composition} at t={start}s")

            # Step A: Render the Remotion template to transparent WebM
            # NOTE: shell=True is required on Windows because npx is a .cmd script
            # NOTE: Paths must be quoted to handle spaces in "montage AI" directory name
            # NOTE: yuva420p requires --image-format png for transparent frames
            # NOTE: --background-color=00000000 tells Remotion to use a transparent background
            render_cmd = (
                f'npx remotion render src/index.ts {composition}'
                f' "{overlay_path}"'
                f' "--props={props_file}"'
                f' --frames 0-{duration_frames - 1}'
                f' --codec vp8'
                f' --image-format png'
                f' --pixel-format yuva420p'
                f' --background-color 00000000'
                f' --log error'
            )
            try:
                render_result = subprocess.run(
                    render_cmd,
                    cwd=remotion_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True,
                    timeout=120,  # 2 min max per graphic render
                )
            except subprocess.TimeoutExpired:
                print(f"[MotionGraphic] ⏰ Remotion render timed out, skipping")
                continue
            if render_result.returncode != 0:
                print(f"[MotionGraphic] Remotion failed: {render_result.stderr.decode(errors='replace')[:200]}")
                continue

            if not os.path.exists(overlay_path):
                print(f"[MotionGraphic] No overlay file produced, skipping")
                continue

            # Step B: Composite WebM onto source video with alpha support
            # format=yuva420p keeps the alpha channel through scale,
            # overlay format=auto uses it as transparency mask
            filter_complex = (
                f"[0:v]trim=0:{start},setpts=PTS-STARTPTS[before];"
                f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS[during];"
                f"[0:v]trim={end},setpts=PTS-STARTPTS[after];"
                f"[1:v]scale=1920:1080,format=yuva420p[webm];"
                f"[during][webm]overlay=0:0:format=auto[during_out];"
                f"[before][during_out][after]concat=n=3:v=1:a=0[out]"
            )
            overlay_cmd = [
                "ffmpeg",
                "-i", working_path,
                "-i", overlay_path,
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-map", "0:a",
                "-c:v", "libx264",
                "-c:a", "aac",
                "-preset", "fast",
                overlay_output,
                "-y", "-loglevel", "error",
            ]
            try:
                ov_result = subprocess.run(overlay_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            except subprocess.TimeoutExpired:
                print(f"[MotionGraphic] ⏰ FFmpeg overlay timed out, skipping")
                continue
            if ov_result.returncode == 0 and os.path.exists(overlay_output):
                os.replace(overlay_output, working_path)
                print(f"[MotionGraphic] ✅ Overlaid {composition} at {start}s")
            else:
                print(f"[MotionGraphic] FFmpeg overlay failed: {ov_result.stderr.decode()}")

            # Cleanup temp WebM
            if os.path.exists(overlay_path):
                os.remove(overlay_path)


    # --- Step 4.3: Dynamic Canvas (AI-assembled primitive scenes) ---
    dynamic_edits = [e for e in edits if e.get("action") == "add_dynamic_graphic"]
    if dynamic_edits:
        for de in dynamic_edits:
            elements = de.get("elements", [])
            start = float(de.get("start", 0))
            end = float(de.get("end", start + 3))
            if not elements:
                continue

            duration_sec = end - start
            duration_frames = min(89, max(30, int(duration_sec * 30)))

            remotion_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "remotion")
            )

            # Write elements JSON for DynamicCanvas
            props_file = os.path.join(remotion_dir, "props", "_dynamic_props.json")
            os.makedirs(os.path.dirname(props_file), exist_ok=True)
            import json as _json
            with open(props_file, "w", encoding="utf-8") as _f:
                _json.dump({"elements": elements}, _f, ensure_ascii=False)

            overlay_path = os.path.abspath(working_path.replace(".mp4", f"_dynamic_{int(start)}.webm"))
            overlay_output = os.path.abspath(working_path.replace(".mp4", f"_after_dyn_{int(start)}.mp4"))

            print(f"[DynamicCanvas] Rendering {len(elements)} elements at t={start}s")
            render_cmd = (
                f'npx remotion render src/index.ts DynamicCanvas'
                f' "{overlay_path}"'
                f' "--props={props_file}"'
                f' --frames 0-{duration_frames - 1}'
                f' --codec vp8'
                f' --image-format png'
                f' --pixel-format yuva420p'
                f' --background-color 00000000'
                f' --log error'
            )
            try:
                render_result = subprocess.run(
                    render_cmd, cwd=remotion_dir,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    shell=True, timeout=120,  # 2 min max per graphic render
                )
            except subprocess.TimeoutExpired:
                print(f"[DynamicCanvas] ⏰ Remotion render timed out, skipping")
                continue

            if render_result.returncode != 0 or not os.path.exists(overlay_path):
                err = render_result.stderr.decode(errors="replace")[:300]
                print(f"[DynamicCanvas] Render failed: {err}")
                continue

            # FFmpeg overlay at the correct timestamp
            offset = start
            filter_complex = (
                f"[0:v]trim=0:{offset},setpts=PTS-STARTPTS[before];"
                f"[0:v]trim={offset}:{end},setpts=PTS-STARTPTS[during_raw];"
                f"[0:v]trim={end},setpts=PTS-STARTPTS[after];"
                # ↓ format=yuva420p preserves alpha channel through scale
                f"[1:v]scale={width}:{height},format=yuva420p[overlay_sc];"
                f"[during_raw][overlay_sc]overlay=0:0:format=auto[during];"
                f"[before][during][after]concat=n=3:v=1:a=0[out]"
            )
            overlay_cmd = [
                "ffmpeg", "-i", working_path, "-i", overlay_path,
                "-filter_complex", filter_complex,
                "-map", "[out]", "-map", "0:a",
                "-c:v", "libx264", "-c:a", "aac", "-preset", "fast",
                overlay_output, "-y", "-loglevel", "error",
            ]
            try:
                ov_result = subprocess.run(overlay_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            except subprocess.TimeoutExpired:
                print(f"[DynamicCanvas] ⏰ FFmpeg overlay timed out, skipping")
                continue
            if ov_result.returncode == 0 and os.path.exists(overlay_output):
                os.replace(overlay_output, working_path)
                print(f"[DynamicCanvas] ✅ Overlaid {len(elements)} elements at {start}s")
            else:
                print(f"[DynamicCanvas] FFmpeg failed: {ov_result.stderr.decode()[:200]}")

            if os.path.exists(overlay_path):
                os.remove(overlay_path)


    # --- Step 4.4: Hyperframes HTML Canvas ---
    hyperframes_edits = [e for e in edits if e.get("action") == "hyperframes_html"]
    if hyperframes_edits:
        print(f"[Hyperframes] Found {len(hyperframes_edits)} html injections. Compositing...")
        hyperframes_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "hyperframes_studio")
        )
        
        # Optimize Hyperframes rendering time by calculating the bounding time box of the graphics
        import re
        min_start = float(duration)
        max_end = 0.0
        
        for e in hyperframes_edits:
            html = e.get("html_content", "")
            for m in re.finditer(r"data-start=['\"]([\d.]+)['\"]", html):
                s = float(m.group(1))
                if s < min_start: min_start = s
            for m in re.finditer(r"data-duration=['\"]([\d.]+)['\"]", html):
                # We need the corresponding start. For simplicity just assume the max end is bounded
                pass # Actually it's easier to just do a naive check:
                
        # More robust extraction (only from elements with class="clip"):
        for e in hyperframes_edits:
            html = e.get("html_content", "")
            clip_matches = re.findall(r'<div[^>]*class=[\'"][^\'"]*clip[^\'"]*[\'"][^>]*>', html)
            starts = []
            durs = []
            for tag in clip_matches:
                s_m = re.search(r"data-start=['\"]([\d.]+)['\"]", tag)
                d_m = re.search(r"data-duration=['\"]([\d.]+)['\"]", tag)
                if s_m: starts.append(float(s_m.group(1)))
                if d_m: durs.append(float(d_m.group(1)))
                
            if starts:
                s = min(starts)
                if s < min_start: min_start = s
                d = max(durs) if durs else 5.0
                if s + d > max_end: max_end = s + d
                
        combined_html = "\n".join([e.get("html_content", "") for e in hyperframes_edits])
        
        if combined_html:
            # Scale the 1080x1920 design to the actual video resolution
            scale_factor = width / 1080.0
            
            # Replace the agent's hardcoded dimensions with the actual video dimensions
            combined_html = re.sub(r'data-width=[\'"]1080[\'"]', f'data-width="{width}"', combined_html)
            combined_html = re.sub(r'data-height=[\'"]1920[\'"]', f'data-height="{height}"', combined_html)
            
            # Wrap in boilerplate provided by hyperframes, sized to video
            html_doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {width}px; height: {height}px; overflow: hidden; background: transparent !important; }}
      .clip {{ position: absolute; }}
      #root {{ 
          width: 1080px !important; 
          height: 1920px !important; 
          transform-origin: top left !important; 
          transform: scale({scale_factor}) !important; 
      }}
    </style>
  </head>
  <body style="background: transparent;">
{combined_html}
  </body>
</html>"""
            
            idx_file = os.path.join(hyperframes_dir, "index.html")
            with open(idx_file, "w", encoding="utf-8") as f:
                f.write(html_doc)
            
            base_name, _ = os.path.splitext(working_path)
            hf_output = os.path.abspath(base_name + "_hyperframes.mov")
            
            # Force MOV format (ProRes 4444) for ultra-fast rendering with alpha channel!
            hf_cmd = (
                f'npx hyperframes render --format mov --output "{hf_output}"'
            )
            print(f"[Hyperframes] Running: {hf_cmd}")
            try:
                hf_result = subprocess.run(
                    hf_cmd, cwd=hyperframes_dir, shell=True, timeout=600,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                if hf_result.returncode != 0:
                    err = hf_result.stderr.decode('utf-8', errors='replace')[:300]
                    print(f"[Hyperframes] Render FAILED (code {hf_result.returncode}): {err}")
                else:
                    print(f"[Hyperframes] Render completed successfully")
                
                if os.path.exists(hf_output):
                    # We render the full duration, so we overlay at 0
                    hf_blend_out = base_name + "_hfblend.mp4"
                    blend_cmd = [
                        "ffmpeg", "-i", working_path, 
                        "-i", hf_output,
                        "-filter_complex", "[1:v]format=rgba[gfx];[0:v][gfx]overlay=0:0:eof_action=pass[outv]",
                        "-map", "[outv]", "-map", "0:a",
                        "-c:v", "libx264", "-c:a", "copy", "-preset", "fast",
                        hf_blend_out, "-y", "-loglevel", "error"
                    ]
                    blend_res = subprocess.run(blend_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
                    if blend_res.returncode == 0 and os.path.exists(hf_blend_out):
                        os.replace(hf_blend_out, working_path)
                        print("[Hyperframes] ✅ Overlaid transparent canvas successfully.")
                    else:
                        print(f"[Hyperframes] FFmpeg overlay failed: {blend_res.stderr.decode()}")
            except Exception as e:
                print(f"[Hyperframes] FFmpeg execute error: {e}")


    # --- Step 4.5: B-Roll overlay ---
    broll_edits = [e for e in edits if e.get("action") == "add_broll"]
    if broll_edits:
        for broll in broll_edits:
            q = broll.get("query", "technology")
            start = float(broll.get("start", 0))
            end = float(broll.get("end", start + 3))
            duration = end - start
            
            broll_path = download_broll(q, duration)
            if broll_path:
                print(f"[RenderEngine] Overlaying broll {broll_path} at {start}-{end}s")
                # Load B-Roll
                b_in = ffmpeg.input(broll_path).video
                # Scale and crop to target resolution, adjust PTS to start at exact timestamp
                b_scaled = b_in.filter('scale', width, height, force_original_aspect_ratio='increase').filter('crop', width, height).filter('setpts', f'PTS-STARTPTS+{start}/TB')
                # Overlay it onto main video
                v_out = ffmpeg.overlay(v_out, b_scaled, enable=f"between(t,{start},{end})", eof_action='pass')

    # --- Step 5: Subtitles via separate subprocess pass (avoids Windows path/space issues) ---
    # We do NOT add the ASS filter to the main graph. Instead we run the main 
    # pipeline first, then apply subtitles in a second ffmpeg subprocess call.
    # This is necessary because ffmpeg's 'ass' filter on Windows fails silently
    # when the path contains spaces (e.g. "montage AI").

    def _run_ffmpeg_with_timeout(stream, timeout_sec=600):
        """Run ffmpeg-python stream with a hard timeout to prevent infinite hangs."""
        proc = stream.run_async(pipe_stdout=True, pipe_stderr=True, overwrite_output=True)
        try:
            _, stderr_bytes = proc.communicate(timeout=timeout_sec)
            if proc.returncode != 0:
                return False, stderr_bytes.decode("utf-8", errors="replace")
            return True, ""
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return False, f"FFmpeg timed out after {timeout_sec}s"

    try:
        if has_subtitles and a_out is not None:
            pre_sub_output = output_path.replace('.mp4', '_presub.mp4')
            out = ffmpeg.output(v_out, a_out, pre_sub_output, vcodec='libx264', acodec='aac', preset='fast')
            ok, err = _run_ffmpeg_with_timeout(out)
            if not ok:
                print(f"[RenderEngine] Main FFmpeg FAILED: {err[:300]}")
                return False
        else:
            out = ffmpeg.output(v_out, a_out, output_path, vcodec='libx264', acodec='aac', preset='fast')
            ok, err = _run_ffmpeg_with_timeout(out)
            if not ok:
                print(f"[RenderEngine] Main FFmpeg FAILED: {err[:300]}")
                return False
            return True
    except Exception as e:
        print(f"[RenderEngine] Main FFmpeg Exception: {e}")
        return False

    # --- Step 6: Apply ASS subtitles via subprocess (Windows-safe) ---
    if has_subtitles and os.path.exists(ass_path) and os.path.exists(pre_sub_output):
        import tempfile, shutil
        
        temp_dir = tempfile.gettempdir()
        # Use a SIMPLE filename with no colons/spaces/special chars for the filter string
        simple_ass_name = "montage_sub_tmp.ass"
        temp_ass_path = os.path.join(temp_dir, simple_ass_name)
        shutil.copy2(ass_path, temp_ass_path)
        
        # Copy fonts dir to temp (no spaces in path)
        fonts_src = os.path.abspath('fonts')
        temp_fonts = os.path.join(temp_dir, 'montage_fonts')
        if os.path.exists(fonts_src) and not os.path.exists(temp_fonts):
            try:
                shutil.copytree(fonts_src, temp_fonts)
            except Exception as e:
                print(f"[Subtitles] Font copy warning: {e}")
        
        # KEY FIX: Run FFmpeg from temp_dir using RELATIVE filename in filter string.
        # This avoids ALL Windows path escaping issues (drive letter colons, spaces).
        # -i and output use absolute paths which FFmpeg handles normally.
        if os.path.exists(temp_fonts):
            vf_filter = f"ass=filename={simple_ass_name}:fontsdir=montage_fonts"
        else:
            vf_filter = f"ass={simple_ass_name}"
        
        abs_presub = os.path.abspath(pre_sub_output)
        abs_output = os.path.abspath(output_path)
        
        print(f"[Subtitles] cwd={temp_dir}, filter={vf_filter}")
        
        try:
            result = subprocess.run(
                ['ffmpeg', '-i', abs_presub, '-vf', vf_filter,
                 '-c:a', 'copy', abs_output, '-y', '-loglevel', 'warning'],
                cwd=temp_dir,
                stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                timeout=300,  # 5 min max for subtitle burn-in
            )
            
            if result.returncode != 0:
                err = result.stderr.decode('utf-8', errors='replace')
                print(f"[Subtitles] FAILED (code {result.returncode}): {err}")
                shutil.move(abs_presub, abs_output)
            else:
                if os.path.exists(abs_presub):
                    os.remove(abs_presub)
                print(f"[Subtitles] SUCCESS")
        except Exception as e:
            print(f"[Subtitles] Exception: {e}")
            if os.path.exists(abs_presub):
                shutil.move(abs_presub, abs_output)
        
        return True
    
    # --- Step 7: Audio normalization (loudnorm) ---
    # Equalizes volume: makes quiet parts louder, loud parts softer
    if os.path.exists(output_path):
        print("[Audio] Applying loudnorm normalization...")
        norm_output = output_path.replace('.mp4', '_norm.mp4')
        try:
            norm_result = subprocess.run(
                ['ffmpeg', '-i', output_path,
                 '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
                 '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                 norm_output, '-y', '-loglevel', 'warning'],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                timeout=300,
            )
            if norm_result.returncode == 0 and os.path.exists(norm_output):
                os.replace(norm_output, output_path)
                print("[Audio] ✅ Loudnorm normalization applied successfully")
            else:
                err = norm_result.stderr.decode('utf-8', errors='replace')
                print(f"[Audio] Normalization failed (non-critical): {err[:200]}")
                if os.path.exists(norm_output):
                    os.remove(norm_output)
        except Exception as e:
            print(f"[Audio] Normalization exception (non-critical): {e}")
            if os.path.exists(norm_output):
                os.remove(norm_output)
    
    return True


async def render_hyperframes_composition(file_id: str, html_content: str, callback) -> str:
    from app.main import TMP_DIR
    hyperframes_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../hyperframes_studio"))
    
    # Save html to hyperframes_studio/index.html
    html_path = os.path.join(hyperframes_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    output_path = os.path.abspath(os.path.join(TMP_DIR, f"{file_id}_hyperframes.mp4"))
    
    if callback:
        await callback("🖌️ Запуск Hyperframes движка (рендеринг в браузере)...")
    
    cmd = [
        "npx", "hyperframes", "render",
        "--output", output_path
    ]
    
    import asyncio
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=hyperframes_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        err = stderr.decode('utf-8', errors='replace')
        print(f"[Hyperframes] Render failed: {err}")
        return ""
        
    print(f"[Hyperframes] SUCCESS -> {output_path}")
    return output_path
