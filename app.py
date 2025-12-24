from flask import Flask, request, jsonify, send_file, render_template, after_this_request
from flask_cors import CORS
import yt_dlp
import os
import time

app = Flask(__name__, template_folder='templates')
CORS(app)

DOWNLOAD_FOLDER = '/tmp'
# Path to your cookies file
COOKIES_FILE = 'youtube_cookies.txt'

def format_selector(ctx):
    formats = ctx.get('formats', [])
    clean_formats = []
    seen_qualities = set()

    for f in formats:
        # We look for mp4 files that have a video height (resolution)
        if f.get('ext') == 'mp4' and f.get('height'):
            resolution = f"{f['height']}p"
            filesize = f.get('filesize') or f.get('filesize_approx') or 0
            size_mb = f"{round(filesize / (1024 * 1024), 1)} MB" if filesize else "Unknown"
            
            if resolution not in seen_qualities:
                clean_formats.append({
                    'format': 'MP4',
                    'quality': resolution,
                    'size': size_mb,
                    'type': 'video',
                    'format_id': f['format_id']
                })
                seen_qualities.add(resolution)
    
    clean_formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)
    return clean_formats

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    url = request.json.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    ydl_opts = {
        'quiet': True,
        'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_data = {
                'title': info.get('title'),
                'channel': info.get('uploader'),
                'duration': time.strftime('%M:%S', time.gmtime(info.get('duration', 0))),
                'thumbnail': info.get('thumbnail'),
                'qualities': format_selector(info)
            }
            return jsonify(video_data)
    except Exception as e:
        print(f"Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['GET'])
def download_video():
    url = request.args.get('url')
    format_id = request.args.get('format_id')
    title = request.args.get('title', 'video')

    filename = f"download_{int(time.time())}.mp4"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    
    ydl_opts = {
        'format': f'{format_id}+bestaudio/best',
        'outtmpl': filepath,
        'merge_output_format': 'mp4',
        'quiet': True,
        'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'ffmpeg_location': '/usr/bin/ffmpeg'
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        @after_this_request
        def remove_file(response):
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                print(f"Error deleting file: {e}")
            return response

        return send_file(filepath, as_attachment=True, download_name=f"{title}.mp4")
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
