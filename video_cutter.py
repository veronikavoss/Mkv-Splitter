import subprocess
import os

def format_time_ffmpeg(ms):
    """
    Converts milliseconds to HH:MM:SS.mmm format for FFmpeg.
    """
    seconds = (ms // 1000) % 60
    minutes = (ms // 60000) % 60
    hours = (ms // 3600000)
    milliseconds = ms % 1000
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"

def cut_video(input_path, start_ms, end_ms, output_path):
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
        "-c", "copy",
        "-map", "0", # Map all streams
        output_path
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        # Run ffmpeg command
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr
    except FileNotFoundError:
        return False, "FFmpeg binary not found. Please ensure FFmpeg is installed and in your PATH."
