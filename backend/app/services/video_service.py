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

def generate_ass(transcript, filepath, position="center", font="Impact", font_size=110, use_outline=True, font_color="White"):
    # Premium Margin and Positioning
    alignment = 5 # Default Center
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

    # Color processing (Primary, Secondary for unlit words)
    color_map = {
        "White": ("&H00FFFFFF", "&H00A0A0A0"), # Primary White, unlit Gray
        "Yellow": ("&H0000D7FF", "&H00A0A0A0"), # Primary Gold/Yellow, unlit Gray
        "Green": ("&H0055FF55", "&H00A0A0A0"),
        "Red": ("&H005555FF", "&H00A0A0A0"),
        "Cyan": ("&H00FFFF00", "&H00A0A0A0"),
    }
    primary_col, unlit_col = color_map.get(font_color, ("&H00FFFFFF", "&H00A0A0A0"))

    # Outline & Shadow (Thick border for readability on all backgrounds)
    outline = 10 if use_outline else 0
    shadow = 8 if use_outline else 0
    outline_col = "&H00000000" # Solid black outline
    shadow_col = "&HAA000000"  # Soft black shadow

    # Beautiful ASS header with premium typography settings
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
        
        words = transcript.get("words", [])
        if not words:
            segments = transcript.get("segments", [])
            for seg in segments:
                start = format_ass_time(seg.get("start", 0.0))
                end = format_ass_time(seg.get("end", 0.0))
                f.write(f"Dialogue: 0,{start},{end},Premium,,0,0,0,,{seg.get('text', '').strip()}\n")
            return

        # Smart Layout: group words tightly, max 3 words
        chunks, cur_chunk = [], []
        for w in words:
            cur_chunk.append(w)
            if len(cur_chunk) == 3:
                chunks.append(cur_chunk)
                cur_chunk = []
        if cur_chunk:
            chunks.append(cur_chunk)
            
        for chunk in chunks:
            chunk_start = chunk[0].get('start', 0.0)
            chunk_end = chunk[-1].get('end', 0.0)
            
            # Active word highlighting effect
            text_line = ""
            for w in chunk:
                dur_cs = int((w.get('end', 0.0) - w.get('start', 0.0)) * 100)
                word_txt = w.get('word', '').strip().upper() # Uppercase for bold modern aesthetic
                # {\c&H...&} sets color dynamically. By default, unlit. {\k} animates lit primary over duration.
                text_line += f"{{\\k{dur_cs}}}{word_txt} "
                
            start_str = format_ass_time(chunk_start)
            end_str = format_ass_time(chunk_end)
            # Premium style applies
            f.write(f"Dialogue: 0,{start_str},{end_str},Premium,,0,0,0,,{text_line.strip()}\n")

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
    else:
        position = "center"

    generate_ass(transcript_data, ass_path, position=position, font=font, font_size=font_size, use_outline=use_outline, font_color=font_color)
    safe_ass = ass_path.replace("\\", "/")

    cuts = [e for e in edits if e.get("action") == "cut_out"]
    zoom_edits = [e for e in edits if e.get("action") == "camera_zoom"]
    speed_edits = [e for e in edits if e.get("action") == "speed_ramp"]
    text_overlays = [e for e in edits if e.get("action") == "add_text_overlay"]

    try:
        probe = ffmpeg.probe(input_path)
        duration = float(probe['format']['duration'])
        width = int(probe['streams'][0].get('width', 1080))
        height = int(probe['streams'][0].get('height', 1920))
    except Exception:
        duration = 10000.0
        width, height = 1080, 1920

    # --- Step 1: Speed ramp (subprocess-based) ---
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

    # We must explicitly handle empty lists (meaning track is entirely muted)
    stream = ffmpeg.input(working_path)
    streams_v, streams_a = [], []

    if not v1_keeps: 
        # Create a dummy blank video if v1 is completely empty
        # A bit complex, but usually V1 is not totally empty
        pass
    else:
        for (start, end) in v1_keeps:
            v = stream.video.trim(start=start, end=end).setpts('PTS-STARTPTS')
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

    # --- Step 5: Subtitles ---
    if has_subtitles and os.path.exists(ass_path):
        safe_fonts_dir = os.path.abspath('fonts').replace('\\\\', '/').replace('\\', '/')
        v_out = v_out.filter('ass', safe_ass, fontsdir=safe_fonts_dir)

    try:
        out = ffmpeg.output(v_out, a_out, output_path, vcodec='libx264', acodec='aac')
        out.run(overwrite_output=True, quiet=True)
        return True
    except ffmpeg.Error as e:
        print(f"FFMPEG Render Error: {e.stderr.decode('utf8') if e.stderr else str(e)}")
        return False
