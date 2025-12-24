from flask import Flask, request, jsonify, send_file, render_template, after_this_request
from flask_cors import CORS
import yt_dlp
import os
import time
import traceback
import re

app = Flask(__name__, template_folder='templates')
CORS(app)

# Use /tmp for downloads on cloud platforms (Render/Heroku/AWS)
DOWNLOAD_FOLDER = '/tmp'
COOKIES_FILE = 'youtube_cookies.txt'

# Helper function to format file size
def format_size(bytes_size):
    if not bytes_size:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"

# Better format selector that handles unavailable formats
def format_selector(ctx):
    formats = ctx.get('formats', [])
    available_formats = []
    
    # Try to get the best available formats
    # Priority: mp4 with audio, then webm, then video-only + audio
    
    # First, get all formats with both video and audio
    complete_formats = []
    for f in formats:
        if (f.get('acodec') != 'none' and f.get('vcodec') != 'none' and 
            f.get('height') is not None):
            format_info = {
                'format_id': f['format_id'],
                'ext': f.get('ext', 'mp4'),
                'height': f['height'],
                'width': f.get('width'),
                'filesize': f.get('filesize') or f.get('filesize_approx'),
                'has_audio': True,
                'has_video': True,
                'format_note': f.get('format_note', ''),
                'vcodec': f.get('vcodec', ''),
                'acodec': f.get('acodec', '')
            }
            complete_formats.append(format_info)
    
    # Group by resolution
    resolutions = {}
    for f in complete_formats:
        res = f"{f['height']}p"
        if res not in resolutions:
            resolutions[res] = []
        resolutions[res].append(f)
    
    # Select the best format for each resolution
    clean_formats = []
    for res in sorted(resolutions.keys(), key=lambda x: int(x.replace('p', '')), reverse=True):
        format_list = resolutions[res]
        # Prefer mp4 over webm
        mp4_formats = [f for f in format_list if f['ext'] == 'mp4']
        if mp4_formats:
            best_format = mp4_formats[0]
        else:
            best_format = format_list[0]
        
        # Create display format
        display_ext = best_format['ext'].upper()
        if display_ext == 'MP4' and best_format['vcodec'] and 'av01' in best_format['vcodec']:
            display_ext = 'AV1'
        elif display_ext == 'MP4' and best_format['vcodec'] and 'vp9' in best_format['vcodec']:
            display_ext = 'VP9'
        
        clean_formats.append({
            'format': display_ext,
            'quality': res,
            'size': format_size(best_format['filesize']),
            'type': 'video',
            'format_id': best_format['format_id'],
            'ext': best_format['ext'],
            'has_audio': best_format['has_audio'],
            'has_video': best_format['has_video']
        })
    
    # Add audio-only formats
    audio_formats = []
    for f in formats:
        if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
            format_info = {
                'format_id': f['format_id'],
                'ext': f.get('ext', 'mp3'),
                'abr': f.get('abr', 0),
                'filesize': f.get('filesize') or f.get('filesize_approx'),
                'has_audio': True,
                'has_video': False
            }
            audio_formats.append(format_info)
    
    # Sort audio by bitrate
    audio_formats.sort(key=lambda x: x['abr'], reverse=True)
    
    # Add top 3 audio formats
    for i, audio in enumerate(audio_formats[:3]):
        clean_formats.append({
            'format': 'MP3',
            'quality': f"{int(audio['abr'])}kbps",
            'size': format_size(audio['filesize']),
            'type': 'audio',
            'format_id': audio['format_id'],
            'ext': audio['ext'],
            'has_audio': True,
            'has_video': False
        })
    
    return clean_formats

# Get the most reliable download options
def get_download_opts(video_url, requested_format_id, output_path):
    # Base options
    opts = {
        'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'quiet': True,
        'no_warnings': False,
        'ignoreerrors': False,
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'socket_timeout': 30,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
            }
        },
        'outtmpl': output_path,
    }
    
    # For audio formats
    if 'kbps' in requested_format_id or any(x in requested_format_id for x in ['140', '251', '250']):
        opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
        opts['ffmpeg_location'] = '/usr/bin/ffmpeg'
    else:
        # For video formats - use a more flexible format selector
        # Try the requested format first, then fallback to best available
        opts['format'] = f'bestvideo[height<={requested_format_id.replace("p","")}][ext=mp4]+bestaudio[ext=m4a]/best[height<={requested_format_id.replace("p","")}]/best'
        opts['merge_output_format'] = 'mp4'
        opts['ffmpeg_location'] = '/usr/bin/ffmpeg'
        opts['postprocessor_args'] = {
            'ffmpeg': ['-hide_banner', '-loglevel', 'error']
        }
    
    return opts

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    
    # Extract video ID for logging
    video_id = extract_video_id(url)
    print(f"Fetching info for video ID: {video_id}")
    
    ydl_opts = {
        'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'quiet': True,
        'no_warnings': False,
        'ignoreerrors': False,
        'retries': 3,
        'fragment_retries': 3,
        'skip_unavailable_fragments': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'socket_timeout': 15,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
            }
        },
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return jsonify({'error': 'Could not extract video information'}), 404
            
            # Get available formats
            formats = format_selector(info)
            
            # If no formats found, provide a basic fallback
            if not formats:
                formats = [{
                    'format': 'MP4',
                    'quality': '360p',
                    'size': 'Unknown',
                    'type': 'video',
                    'format_id': '18',  # Fallback to 360p
                    'ext': 'mp4',
                    'has_audio': True,
                    'has_video': True
                }]
            
            video_data = {
                'title': info.get('title', 'Unknown Title'),
                'channel': info.get('uploader', 'Unknown Channel'),
                'duration': format_duration(info.get('duration', 0)),
                'thumbnail': info.get('thumbnail', ''),
                'video_id': video_id,
                'qualities': formats
            }
            
            print(f"Successfully fetched info for: {video_data['title']}")
            print(f"Found {len(formats)} available formats")
            
            return jsonify(video_data)
            
    except Exception as e:
        error_msg = str(e)
        print(f"Error fetching video info: {error_msg}")
        print(traceback.format_exc())
        
        # Provide user-friendly error messages
        if "429" in error_msg or "Too Many Requests" in error_msg:
            error_msg = "YouTube is temporarily blocking requests. Please try again in a few minutes."
        elif "Unsupported URL" in error_msg:
            error_msg = "Invalid YouTube URL. Please check the URL and try again."
        elif "Private" in error_msg or "Sign in" in error_msg:
            error_msg = "This video may be private or require login. Try a different video."
        elif "not available" in error_msg:
            error_msg = "Video is not available in your region or has been removed."
        
        return jsonify({'error': error_msg}), 500

def extract_video_id(url):
    """Extract video ID from various YouTube URL formats"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com\/watch\?.*v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be\/([a-zA-Z0-9_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return "unknown"

def format_duration(seconds):
    """Format duration in seconds to HH:MM:SS or MM:SS"""
    if not seconds:
        return "00:00"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

@app.route('/api/download', methods=['GET'])
def download_video():
    url = request.args.get('url')
    format_id = request.args.get('format_id')
    title = request.args.get('title', 'video')
    
    if not url or not format_id:
        return jsonify({'error': 'Missing URL or format ID'}), 400
    
    video_id = extract_video_id(url)
    print(f"Starting download for video ID: {video_id}, format: {format_id}")
    
    # Create a safe filename
    safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()
    safe_title = re.sub(r'[-\s]+', '-', safe_title)
    
    # Determine file extension
    if 'kbps' in format_id or format_id in ['140', '251', '250']:
        extension = 'mp3'
        content_type = 'audio/mpeg'
    else:
        extension = 'mp4'
        content_type = 'video/mp4'
    
    filename = f"{safe_title}_{video_id}.{extension}"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    
    try:
        # First, get video info to verify format availability
        ydl_info_opts = {
            'cookiefile': COOKIES_FILE,
            'quiet': True,
            'extract_flat': False,
        }
        
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            available_formats = [f['format_id'] for f in info.get('formats', [])]
            
            print(f"Available formats for video: {available_formats}")
            print(f"Requested format: {format_id}")
            
            # Check if requested format is available
            if format_id not in available_formats:
                print(f"Format {format_id} not available. Finding alternative...")
                
                # For video formats, find closest available resolution
                if 'p' in format_id:
                    requested_height = int(format_id.replace('p', ''))
                    
                    # Find available video formats with audio
                    video_formats = []
                    for f in info.get('formats', []):
                        if f.get('height') and f.get('acodec') != 'none':
                            video_formats.append({
                                'height': f['height'],
                                'format_id': f['format_id'],
                                'ext': f.get('ext', '')
                            })
                    
                    if video_formats:
                        # Sort by closest height to requested
                        video_formats.sort(key=lambda x: abs(x['height'] - requested_height))
                        closest_format = video_formats[0]
                        format_id = closest_format['format_id']
                        print(f"Using alternative format: {format_id} ({closest_format['height']}p)")
                
                # For audio formats, find best available audio
                elif 'kbps' in format_id or any(x in format_id for x in ['140', '251', '250']):
                    audio_formats = []
                    for f in info.get('formats', []):
                        if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                            audio_formats.append({
                                'abr': f.get('abr', 0),
                                'format_id': f['format_id']
                            })
                    
                    if audio_formats:
                        audio_formats.sort(key=lambda x: x['abr'], reverse=True)
                        format_id = audio_formats[0]['format_id']
                        print(f"Using alternative audio format: {format_id}")
        
        # Now download with the (possibly adjusted) format
        ydl_download_opts = get_download_opts(url, format_id, filepath)
        
        print(f"Downloading with options: {ydl_download_opts.get('format', 'default')}")
        
        with yt_dlp.YoutubeDL(ydl_download_opts) as ydl:
            ydl.download([url])
        
        print(f"Download completed: {filepath}")
        
        # Verify file was created
        if not os.path.exists(filepath):
            raise Exception("Downloaded file not found")
        
        file_size = os.path.getsize(filepath)
        print(f"File size: {file_size} bytes")
        
        # Cleanup function
        @after_this_request
        def remove_file(response):
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                    print(f"Cleaned up file: {filepath}")
            except Exception as e:
                print(f"Cleanup error: {e}")
            return response
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=filename,
            mimetype=content_type
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
        
        # User-friendly error messages
        if "format is not available" in error_msg:
            error_msg = "The requested quality is not available for this video. Try a different quality."
        elif "429" in error_msg:
            error_msg = "Too many requests. Please wait a few minutes before trying again."
        elif "Private" in error_msg:
            error_msg = "This video is private or requires login."
        elif "unavailable" in error_msg:
            error_msg = "Video is not available or has been removed."
        
        return jsonify({'error': error_msg}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
