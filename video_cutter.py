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
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
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

def build_cut_cmd(input_path, start_ms, end_ms, output_path, selected_track_ids=None):
    """
    Builds the ffmpeg command for cutting the video.
    Returns the command list.
    """
    start_str = format_time_ffmpeg(start_ms)
    end_str = format_time_ffmpeg(end_ms)
    
    cmd = [
        "ffmpeg",
        "-y", # Overwrite output files
        "-ss", start_str,
        "-to", end_str,
        "-i", input_path,
        "-c", "copy"
    ]
    
    if selected_track_ids is not None:
        for track_id in selected_track_ids:
            cmd.extend(["-map", f"0:{track_id}"])
    else:
        cmd.extend(["-map", "0"]) # Map all streams
        
    cmd.append(output_path)
    return cmd

def build_merge_cmd(input_files, output_path):
    """
    Builds the ffmpeg command for merging multiple video files.
    Returns (cmd_list, list_file_path) or (None, error_msg).
    """
    if not input_files:
        return None, "No input files provided for merging."

    # Create a temporary concat list file
    list_file_path = output_path + ".txt"
    try:
        with open(list_file_path, 'w', encoding='utf-8') as f:
            for file_path in input_files:
                # Escape single quotes and backslashes for ffmpeg concat file syntax
                safe_path = file_path.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")
    except Exception as e:
        return None, f"Failed to create concat list file: {e}"

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file_path,
        "-c", "copy",
        output_path
    ]

    return cmd, list_file_path
