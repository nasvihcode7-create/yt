from flask import Flask, request, jsonify, send_file, render_template, after_this_request
from flask_cors import CORS
import yt_dlp
import os
import time
import traceback

app = Flask(__name__, template_folder='templates')
CORS(app)

# Use /tmp for downloads on cloud platforms (Render/Heroku/AWS)
DOWNLOAD_FOLDER = '/tmp'
COOKIES_FILE = 'youtube_cookies.txt'

# Enhanced format selector that includes audio-only options
def format_selector(ctx):
    formats = ctx.get('formats', [])
    clean_formats = []
    seen_qualities = set()
    
    # First, get video formats with audio
    for f in formats:
        # Filter for MP4 files with video and audio (standard quality)
        if f.get('ext') == 'mp4' and f.get('height'):
            resolution = f"{f['height']}p"
            filesize = f.get('filesize') or f.get('filesize_approx') or 0
            size_mb = f"{round(filesize / (1024 * 1024), 1)} MB" if filesize else "Unknown"
            
            # Only include if it has both video and audio
            if f.get('acodec') != 'none' and f.get('vcodec') != 'none':
                if resolution not in seen_qualities:
                    clean_formats.append({
                        'format': 'MP4',
                        'quality': resolution,
                        'size': size_mb,
                        'type': 'video',
                        'format_id': f['format_id'],
                        'has_audio': True,
                        'has_video': True
                    })
                    seen_qualities.add(resolution)
    
    # Also look for audio-only options
    audio_formats = []
    for f in formats:
        if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
            # Audio only
            abr = f.get('abr', 0)
            if abr:
                audio_formats.append({
                    'format': 'MP3',
                    'quality': f"{int(abr)}kbps",
                    'size': f"{round((f.get('filesize') or f.get('filesize_approx') or 0) / (1024 * 1024), 1)} MB" if f.get('filesize') or f.get('filesize_approx') else "Unknown",
                    'type': 'audio',
                    'format_id': f['format_id'],
                    'has_audio': True,
                    'has_video': False
                })
    
    # Sort qualities highest to lowest
    clean_formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)
    
    # Add audio formats at the end
    audio_formats.sort(key=lambda x: int(x['quality'].replace('kbps', '')), reverse=True)
    clean_formats.extend(audio_formats[:3])  # Add top 3 audio formats
    
    return clean_formats

# Enhanced yt-dlp options for fetching info
def get_info_ydl_opts():
    return {
        'quiet': True,
        'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'origin': 'https://www.youtube.com',
        'ratelimit': 1000000,  # Limit to 1MB/s to avoid rate limiting
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'socket_timeout': 30,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'skip': ['hls', 'dash']
            }
        },
        'no_warnings': False,  # Show warnings for debugging
        'ignoreerrors': False
    }

# Enhanced yt-dlp options for downloading
def get_download_ydl_opts(format_id, output_path):
    return {
        'format': f'{format_id}+bestaudio/best' if 'video' in format_id else format_id,
        'outtmpl': output_path,
        'merge_output_format': 'mp4',
        'quiet': True,
        'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'origin': 'https://www.youtube.com',
        'ratelimit': 1000000,
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'nocheckcertificate': True,
        'ffmpeg_location': '/usr/bin/ffmpeg',
        'socket_timeout': 30,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'postprocessor_args': {
            'ffmpeg': ['-hide_banner', '-loglevel', 'error']
        }
    }

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    print(f"Fetching info for URL: {url}")
    
    try:
        with yt_dlp.YoutubeDL(get_info_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Debug logging
            print(f"Successfully fetched info for: {info.get('title', 'Unknown')}")
            print(f"Available formats: {len(info.get('formats', []))}")
            
            video_data = {
                'title': info.get('title', 'Unknown Title'),
                'channel': info.get('uploader', 'Unknown Channel'),
                'duration': time.strftime('%H:%M:%S', time.gmtime(info.get('duration', 0))),
                'thumbnail': info.get('thumbnail', ''),
                'qualities': format_selector(info)
            }
            
            if not video_data['qualities']:
                print("Warning: No formats found!")
                # Try a fallback approach
                video_data['qualities'] = [{
                    'format': 'MP4',
                    'quality': '360p',
                    'size': 'Unknown',
                    'type': 'video',
                    'format_id': '18'  # Fallback to 360p MP4
                }]
            
            return jsonify(video_data)
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error fetching video info: {error_msg}")
        print(traceback.format_exc())
        
        # Provide more specific error messages
        if "429" in error_msg:
            error_msg = "YouTube is temporarily blocking requests. Please try again in a few minutes."
        elif "cookies" in error_msg.lower():
            error_msg = "Authentication issue. Cookies may have expired."
        
        return jsonify({'error': error_msg}), 500

@app.route('/api/download', methods=['GET'])
def download_video():
    url = request.args.get('url')
    format_id = request.args.get('format_id')
    title = request.args.get('title', 'video')
    
    if not url or not format_id:
        return jsonify({'error': 'Missing URL or format ID'}), 400
    
    # Generate a unique temporary filename
    timestamp = int(time.time())
    filename = f"download_{timestamp}.mp4"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    
    print(f"Starting download: {title} | Format: {format_id}")
    
    try:
        with yt_dlp.YoutubeDL(get_download_ydl_opts(format_id, filepath)) as ydl:
            ydl.download([url])
        
        print(f"Download completed: {filepath}")
        
        # Cleanup function to remove file after sending
        @after_this_request
        def remove_file(response):
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    print(f"Cleaned up file: {filepath}")
            except Exception as e:
                print(f"Cleanup error: {e}")
            return response
        
        # Send the file
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        download_name = f"{safe_title}.mp4"
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=download_name,
            mimetype='video/mp4'
        )
        
    except Exception as e:
        error_msg = str(e)
        print(f"Download error: {error_msg}")
        print(traceback.format_exc())
        
        # Clean up any partial file
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except:
            pass
        
        # Specific error messages
        if "429" in error_msg:
            error_msg = "Too many requests. Please wait a few minutes before trying again."
        elif "format" in error_msg.lower():
            error_msg = "The requested format is not available. Please try a different quality."
        
        return jsonify({'error': error_msg}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
