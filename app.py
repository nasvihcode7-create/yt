from flask import Flask, request, jsonify, send_file, render_template, after_this_request
from flask_cors import CORS
import yt_dlp
import os
import time

# Update 1: specific folder for templates
app = Flask(__name__, template_folder='templates')
CORS(app)

# Use /tmp for downloads on cloud platforms (Render/Heroku/AWS)
# Regular folders might be read-only or not persist.
DOWNLOAD_FOLDER = '/tmp'

def format_selector(ctx):
    # ... (Keep your existing format_selector function exactly the same) ...
    # (I omitted it here to save space, but make sure you paste the function back in!)
    formats = ctx.get('formats', [])
    clean_formats = []
    seen_qualities = set()
    for f in formats:
        if f.get('ext') == 'mp4' and f.get('height'):
            resolution = f"{f['height']}p"
            filesize = f.get('filesize') or f.get('filesize_approx') or 0
            size_mb = f"{round(filesize / (1024 * 1024), 1)} MB" if filesize else "Unknown"
            identifier = f"{resolution}"
            if identifier not in seen_qualities:
                clean_formats.append({
                    'format': 'MP4', 'quality': resolution, 'size': size_mb,
                    'type': 'video', 'format_id': f['format_id']
                })
                seen_qualities.add(identifier)
    clean_formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)
    return clean_formats

# Update 2: Route for the Homepage
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/info', methods=['POST'])
def get_info():
    # ... (Keep your existing get_info logic exactly the same) ...
    url = request.json.get('url')
    if not url: return jsonify({'error': 'No URL provided'}), 400
    ydl_opts = {'quiet': True}
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
        return jsonify({'error': str(e)}), 500

@app.route('/api/download', methods=['GET'])
def download_video():
    url = request.args.get('url')
    format_id = request.args.get('format_id')
    title = request.args.get('title', 'video')
    
    # Sanitize title to prevent filesystem errors
    safe_title = "".join([c for c in title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    filename = f"{safe_title}_{format_id}.mp4"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    
    ydl_opts = {
        'format': f'{format_id}+bestaudio/best',
        'outtmpl': filepath,
        'merge_output_format': 'mp4',
        'quiet': True,
        # Update 3: Explicitly tell yt-dlp where ffmpeg is (Linux default path)
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
            except Exception as error:
                app.logger.error("Error removing file", error)
            return response

        return send_file(filepath, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Update 4: Bind to 0.0.0.0 and PORT env variable for Render
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
