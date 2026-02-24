import subprocess
import os
import json

def format_time_ffmpeg(ms):
    """
    Converts milliseconds to HH:MM:SS.mmm format for FFmpeg.
    """
    seconds = (ms // 1000) % 60
    minutes = (ms // 60000) % 60
    hours = (ms // 3600000)
    milliseconds = ms % 1000
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"

def get_media_tracks(file_path):
    """
    Uses ffprobe to extract media streams information.
    Returns a list of dictionaries with stream details.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        file_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        tracks = []
        for stream in streams:
            track = {
                'id': stream.get('index'),
                'codec': stream.get('codec_name', 'Unknown'),
                'type': stream.get('codec_type', 'Unknown'),
                'language': stream.get('tags', {}).get('language', 'und'),
                'title': stream.get('tags', {}).get('title', ''),
                'default': stream.get('disposition', {}).get('default', 0) == 1,
                'forced': stream.get('disposition', {}).get('forced', 0) == 1
            }
            tracks.append(track)
        return tracks
    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return []

def cut_video(input_path, start_ms, end_ms, output_path, selected_track_ids=None):
    """
    Cuts the video from start_ms to end_ms using ffmpeg stream copy.
    NO re-encoding is performed.
    """
    start_str = format_time_ffmpeg(start_ms)
    end_str = format_time_ffmpeg(end_ms)
    
    # Construct the command
    # -ss before -i is faster seeking (input seeking) but less accurate for stream copy.
    # -ss after -i is slower (output seeking) but more frame-accurate for re-encoding.
    # For stream copy (-c copy), strict frame accuracy is impossible without re-encoding at cut points.
    # We will put -ss before -i for speed, as per request "lossless and fast".
    
    cmd = [
        "ffmpeg",
        "-y", # Overwrite output files
        "-ss", start_str,
        "-to", end_str,
        "-i", input_path,
        "-c", "copy"
    ]
    
    # Map only selected streams or all if none provided
    if selected_track_ids is not None:
        for track_id in selected_track_ids:
            cmd.extend(["-map", f"0:{track_id}"])
    else:
        cmd.extend(["-map", "0"]) # Map all streams
        
    cmd.append(output_path)
    
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        # Run ffmpeg command
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr
    except FileNotFoundError:
        return False, "FFmpeg binary not found. Please ensure FFmpeg is installed and in your PATH."
