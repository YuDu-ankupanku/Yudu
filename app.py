from flask import Flask, render_template, request, redirect, session, send_file , flash
from flask_sqlalchemy import SQLAlchemy
import bcrypt
import os
import pytube
import subprocess
import re

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
db = SQLAlchemy(app)
app.secret_key = 'secret_key'

# Define the User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))

    def __init__(self, email, password, name):
        self.name = name
        self.email = email
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))

# Create all tables
with app.app_context():
    db.create_all()

DOWNLOAD_FOLDER = 'downloads'

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def sanitize_filename(filename):
    # Replace characters that are not allowed in filenames
    return re.sub(r'[<>:"/\\|?*]', '_', filename)



# Route for the index page
@app.route('/')
def index():
    return render_template('index.html')

# Route for the registration page
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        # Check if the email is already registered
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already exists. Please use a different email.', 'error')
            return redirect('/register')

        new_user = User(name=name, email=email, password=password)
        db.session.add(new_user)
        db.session.commit()

        flash('User registered successfully!', 'success')
        return redirect('/login')

    return render_template('register.html')

# Route for the login page
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if not email or not password:
            return render_template('login.html', error='Please fill out all fields.')

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session['email'] = user.email
            return redirect('/dashboard')
        else:
            return render_template('login.html', error='Invalid credentials.')

    return render_template('login.html')

# Route for the dashboard page
@app.route('/dashboard')
def dashboard():
    if 'email' in session:
        user = User.query.filter_by(email=session['email']).first()
        return render_template('dashboard.html', user=user)
    
    return redirect('/login')

# Route for the preview page
@app.route('/preview', methods=['POST'])
def preview():
    url = request.form['url']
    yt = pytube.YouTube(url)
    resolutions = [stream.resolution for stream in yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc()]
    
    # Adding 4K option if available
    if '2160p' not in resolutions:
        resolutions.append('2160p')
    
    video_info = {
        'title': yt.title,
        'thumbnail_url': yt.thumbnail_url,
        'url': url,
        'resolutions': resolutions,
    }
    return render_template('preview.html', video_info=video_info)

# Route for downloading the video/audio
@app.route('/download', methods=['POST'])
def download():
    url = request.form['url']
    resolution = request.form['resolution']
    download_type = request.form['download_type']
    yt = pytube.YouTube(url)

    if download_type == 'audio':
        audio_stream = yt.streams.filter(only_audio=True, file_extension='mp4').first()
        if audio_stream:
            filename = sanitize_filename(f"{yt.title.replace(' ', '_')}_audio.mp4")
            download_path = os.path.join(DOWNLOAD_FOLDER, filename)
            audio_stream.download(output_path=DOWNLOAD_FOLDER, filename=filename)
            return send_file(download_path, as_attachment=True)
        else:
            return "Could not find audio stream for the given resolution", 400

    elif download_type == 'video':
        if resolution == '2160p':
            video_stream = yt.streams.filter(res='2160p', file_extension='mp4', only_video=True).first()
        else:
            video_stream = yt.streams.filter(res=resolution, file_extension='mp4', only_video=True).first()
        
        if video_stream:
            filename = sanitize_filename(f"{yt.title.replace(' ', '_')}_{resolution}_video.mp4")
            download_path = os.path.join(DOWNLOAD_FOLDER, filename)
            video_stream.download(output_path=DOWNLOAD_FOLDER, filename=filename)
            return send_file(download_path, as_attachment=True)
        else:
            return f"Could not find video stream for resolution {resolution}", 400

    else:
        # Try to get a progressive stream (includes both video and audio)
        stream = yt.streams.filter(progressive=True, res=resolution, file_extension='mp4').first()

        if stream:
            filename = sanitize_filename(stream.default_filename)
            download_path = os.path.join(DOWNLOAD_FOLDER, filename)
            stream.download(output_path=DOWNLOAD_FOLDER, filename=filename)
            return send_file(download_path, as_attachment=True)
        else:
            # If progressive stream is not available, download video and audio separately
            video_stream = yt.streams.filter(res=resolution, file_extension='mp4', only_video=True).first()
            audio_stream = yt.streams.filter(only_audio=True, file_extension='mp4').first()

            if video_stream and audio_stream:
                video_filename = sanitize_filename(f"{yt.title.replace(' ', '_')}_video.mp4")
                audio_filename = sanitize_filename(f"{yt.title.replace(' ', '_')}_audio.mp4")
                video_download_path = os.path.join(DOWNLOAD_FOLDER, video_filename)
                audio_download_path = os.path.join(DOWNLOAD_FOLDER, audio_filename)

                video_stream.download(output_path=DOWNLOAD_FOLDER, filename=video_filename)
                audio_stream.download(output_path=DOWNLOAD_FOLDER, filename=audio_filename)

                merged_filename = sanitize_filename(f"{yt.title.replace(' ', '_')}.mp4")
                merged_download_path = os.path.join(DOWNLOAD_FOLDER, merged_filename)

                command = [
                    'ffmpeg', '-y',
                    '-i', video_download_path,
                    '-i', audio_download_path,
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-strict', 'experimental',
                    merged_download_path
                ]
                subprocess.run(command, check=True)

                # Cleanup temporary files
                os.remove(video_download_path)
                os.remove(audio_download_path)

                return send_file(merged_download_path, as_attachment=True)
            else:
                return "Could not find video or audio streams for the given resolution", 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
