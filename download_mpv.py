import requests
import re
import os

def download_libmpv():
    print("Fetching libmpv latest version from SourceForge RSS...")
    rss_url = "https://sourceforge.net/projects/mpv-player-windows/rss?path=/libmpv"
    try:
        response = requests.get(rss_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        rss_content = response.text
    except Exception as e:
        print(f"Failed to fetch RSS: {e}")
        return

    match = re.search(r'<link>(https://sourceforge\.net/projects/mpv-player-windows/files/libmpv/mpv-dev-x86_64-[^<]+\.7z/download)</link>', rss_content)
    if not match:
        match = re.search(r'<link>(https://sourceforge\.net/projects/mpv-player-windows/files/libmpv/[^<]+\.7z/download)</link>', rss_content)
        
    if not match:
        print("Could not find a valid .7z link in the RSS feed.")
        return

    download_url = match.group(1)
    print(f"Found latest libmpv URL: {download_url}")
    
    archive_path = "libmpv.7z"
    try:
        print("Resolving SourceForge redirect...")
        response = requests.get(download_url, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True, timeout=10)
        
        # Check if we hit the meta refresh page
        content_start = response.content[:2000].lower()
        if b"meta http-equiv=\"refresh\"" in content_start:
            match = re.search(r'url=(https?://[^"]+)', response.text, re.IGNORECASE)
            if match:
                actual_url = match.group(1).replace('&amp;', '&')
                print(f"Meta refresh redirect found: {actual_url}")
                response = requests.get(actual_url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=30)
            else:
                print("Could not parse meta refresh URL.")
                return
        else:
            # We magically got the file directly, we need to re-request as stream
            response = requests.get(download_url, headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=True, stream=True, timeout=30)

        print("Downloading to libmpv.7z...")
        with open(archive_path, 'wb') as out_file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    out_file.write(chunk)
    except Exception as e:
        print(f"Download failed: {e}")
        return

    print("Extracting mpv-2.dll...")
    import py7zr
    try:
        with py7zr.SevenZipFile(archive_path, mode='r') as z:
            targets = [f for f in z.getnames() if 'mpv-2.dll' in f or 'libmpv-2.dll' in f or 'mpv-1.dll' in f or 'libmpv-1.dll' in f]
            if targets:
                z.extract(targets=targets, path='.')
                for root, dirs, files in os.walk('.'):
                    if root == '.': continue
                    for file in files:
                        if file.endswith('.dll') and 'mpv' in file:
                            try:
                                dest_path = os.path.join('.', file)
                                if os.path.exists(dest_path):
                                    os.remove(dest_path)
                                os.rename(os.path.join(root, file), dest_path)
                                print(f"Moved {file} to current directory.")
                            except Exception as e:
                                print(e)
            else:
                print("Could not find mpv dll inside the archive. Dumping all.")
                z.extractall(path='.')
    except Exception as e:
        print(f"Extraction failed: {e}")
        
    try:
        if os.path.exists(archive_path):
            os.remove(archive_path)
    except:
        pass
    
    print("Done! mpv-2.dll should now be available.")

if __name__ == "__main__":
    download_libmpv()
