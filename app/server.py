# server.py (Revised to include frontend serving)

from flask import Flask, request, send_file, jsonify, render_template
from gevent.pywsgi import WSGIServer
from dotenv import load_dotenv
import os
import traceback
import asyncio # Added for get_voices
from flask import Flask, request, send_file, jsonify, send_from_directory # Add send_from_directory
from gevent.pywsgi import WSGIServer
from dotenv import load_dotenv
import os
import traceback
import uuid # Add uuid for unique filenames
import shutil # Add shutil for directory cleanup
from pathlib import Path # Add Path for directory creation


from config import DEFAULT_CONFIGS #
from handle_text import prepare_tts_input_with_context #
from tts_handler import generate_speech, get_models, get_voices, is_ffmpeg_installed #
from utils import getenv_bool, require_api_key, AUDIO_FORMAT_MIME_TYPES, DETAILED_ERROR_LOGGING #

app = Flask(__name__)
load_dotenv()

# Define a temporary directory for audio files
TEMP_AUDIO_DIR = Path("temp_audio")
TEMP_AUDIO_DIR.mkdir(exist_ok=True) # Create the directory if it doesn't exist

API_KEY = os.getenv('API_KEY', DEFAULT_CONFIGS["API_KEY"]) #
PORT = int(os.getenv('PORT', str(DEFAULT_CONFIGS["PORT"]))) #

DEFAULT_VOICE = os.getenv('DEFAULT_VOICE', DEFAULT_CONFIGS["DEFAULT_VOICE"]) #
DEFAULT_RESPONSE_FORMAT = os.getenv('DEFAULT_RESPONSE_FORMAT', DEFAULT_CONFIGS["DEFAULT_RESPONSE_FORMAT"]) #
DEFAULT_SPEED = float(os.getenv('DEFAULT_SPEED', str(DEFAULT_CONFIGS["DEFAULT_SPEED"]))) #
DEFAULT_LANGUAGE = os.getenv('DEFAULT_LANGUAGE', DEFAULT_CONFIGS["DEFAULT_LANGUAGE"])

REMOVE_FILTER = getenv_bool('REMOVE_FILTER', DEFAULT_CONFIGS["REMOVE_FILTER"]) #
EXPAND_API = getenv_bool('EXPAND_API', DEFAULT_CONFIGS["EXPAND_API"]) #

# New route for the web interface
@app.route('/')
def index():
    # Fetch voices dynamically for the dropdown
    # Note: get_voices is an async function, so it needs to be run in an async loop.
    # Since we're in a synchronous Flask route, we use asyncio.run().
    available_voices = get_voices(language=DEFAULT_LANGUAGE)    
    return render_template('index.html', voices=available_voices, default_speed=DEFAULT_SPEED) #

@app.route('/v1/audio/speech', methods=['POST'])
@app.route('/audio/speech', methods=['POST'])
@require_api_key
def text_to_speech():
    try:
        data = request.json
        text = data.get('input') # In OpenAI's API, text is 'input'
        voice = data.get('voice', DEFAULT_VOICE)
        response_format = data.get('response_format', DEFAULT_RESPONSE_FORMAT) # Ensure this is 'mp3' or handled
        speed = float(data.get('speed', DEFAULT_SPEED))

        if not text:
            return jsonify({"error": "Missing 'input' text"}), 400

        if not REMOVE_FILTER:
            text = prepare_tts_input_with_context(text)

        # Generate a unique filename for the audio
        audio_filename = f"{uuid.uuid4()}.mp3"
        output_file_path = TEMP_AUDIO_DIR / audio_filename

        # Generate speech and save it directly to the temporary file
        # Note: generate_speech in tts_handler.py might need slight modification
        # to accept output_file_path directly or return data to save here.
        # Assuming generate_speech now returns the content or saves it directly to `output_file_path`
        # Based on your tts_handler.py, `_generate_audio` saves to a temp file and then converts.
        # Let's adjust it to save directly to `output_file_path`
        
        # Original: output_file_path = generate_speech(text, voice, response_format, speed)
        # This `generate_speech` in `tts_handler.py` seems to create its own temp file
        # and then returns a path. We need to ensure that final path is the one we serve.

        # Let's make sure generate_speech returns the path to the final MP3
        # and we will rename/move it to TEMP_AUDIO_DIR

        # Step 1: Generate the speech using your existing handler
        # (Assuming generate_speech creates a temp file and returns its path)
        temp_generated_path = generate_speech(text, voice, response_format, speed)

        # Step 2: Move the generated file to our desired static temporary directory
        shutil.move(temp_generated_path, output_file_path)

        # Construct the HTML for the audio player
        audio_html = f'<audio controls autoplay><source src="/temp_audio/{audio_filename}" type="audio/mpeg"></audio>'
        
        return audio_html, 200 # Return the HTML string with 200 OK

    except Exception as e:
        if DETAILED_ERROR_LOGGING:
            traceback.print_exc() # Print full traceback to console
        print(f"Error in text_to_speech: {e}")
        return jsonify({"error": f"Error generating speech: {str(e)}"}), 500

# server.py
# ...
# At the end of your server.py, after all other routes

@app.route('/temp_audio/<filename>')
def serve_temp_audio(filename):
    # Ensure the filename is safe to prevent directory traversal attacks
    if ".." in filename or filename.startswith('/'):
        return "Invalid filename", 400
    
    return send_from_directory(TEMP_AUDIO_DIR, filename, mimetype="audio/mpeg")

# ... rest of your server run code
# New endpoint for HTMX form submission (similar to /generate_audio from previous app.py)
@app.route('/generate_audio_htmx', methods=['POST'])
def generate_audio_htmx_route():
    text_input = request.form.get('text_input')
    voice_select = request.form.get('voice_select')
    speed_input = float(request.form.get('speed_input', DEFAULT_SPEED)) #

    if not text_input or not voice_select:
        return "<div class='error-message'>Please provide text and select a voice.</div>", 400

    processed_text = prepare_tts_input_with_context(text_input) #

    try:
        # We'll stick to mp3 as the response format for simplicity with send_file for HTMX
        audio_file_path = generate_speech(processed_text, voice_select, "mp3", speed_input) #

        # Return an audio tag that HTMX will inject
        return f'<audio controls autoplay><source src="/serve_audio?path={os.path.basename(audio_file_path)}&full_path={audio_file_path}" type="audio/mpeg"></audio>'
    except RuntimeError as e:
        print(f"Error during audio generation: {e}")
        return f"<div class='error-message'>Error generating audio: {e}</div>", 500
    except ValueError as e:
        print(f"Validation error: {e}")
        return f"<div class='error-message'>Input validation error: {e}</div>", 400
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return f"<div class='error-message'>An unexpected error occurred: {e}</div>", 500

# Helper endpoint to serve the temporary audio file for HTMX
@app.route('/serve_audio')
def serve_audio():
    # Note: This is a simplification. In a production environment, you'd manage temporary files
    # more robustly, perhaps using a unique ID or a secure temporary storage.
    # For this demo, we pass the full path (which is risky if exposed to users directly)
    # or rely on the filename being unique enough and clean up later.
    audio_file_path = request.args.get('full_path')
    if not audio_file_path or not os.path.exists(audio_file_path):
        return "Audio file not found.", 404

    response = send_file(audio_file_path, mimetype='audio/mpeg', as_attachment=False)
    
    # Schedule cleanup after the file is sent
    @response.call_on_close
    def cleanup():
        try:
            os.unlink(audio_file_path)
            print(f"Cleaned up {audio_file_path}")
        except Exception as e:
            print(f"Error cleaning up {audio_file_path}: {e}")
    return response


@app.route('/v1/models', methods=['GET', 'POST'])
@app.route('/models', methods=['GET', 'POST'])
@require_api_key #
def list_models():
    return jsonify({"data": get_models()}) #

@app.route('/v1/voices', methods=['GET', 'POST'])
@app.route('/voices', methods=['GET', 'POST'])
@require_api_key #
def list_voices_api(): # Renamed to avoid conflict with the function import
    specific_language = None

    data = request.args if request.method == 'GET' else request.json
    if data and ('language' in data or 'locale' in data):
        specific_language = data.get('language') if 'language' in data else data.get('locale')

    return jsonify({"voices": asyncio.run(get_voices(specific_language))}) #

@app.route('/v1/voices/all', methods=['GET', 'POST'])
@app.route('/voices/all', methods=['GET', 'POST'])
@require_api_key #
def list_all_voices_api(): # Renamed to avoid conflict with the function import
    return jsonify({"voices": asyncio.run(get_voices('all'))}) #

"""
Support for ElevenLabs and Azure AI Speech
    (currently in beta)
"""

# http://localhost:5050/elevenlabs/v1/text-to-speech
# http://localhost:5050/elevenlabs/v1/text-to-speech/en-US-AndrewNeural
@app.route('/elevenlabs/v1/text-to-speech/<voice_id>', methods=['POST'])
@require_api_key #
def elevenlabs_tts(voice_id):
    if not EXPAND_API: #
        return jsonify({"error": f"Endpoint not allowed"}), 500
    
    # Parse the incoming JSON payload
    try:
        payload = request.json
        if not payload or 'text' not in payload:
            return jsonify({"error": "Missing 'text' in request body"}), 400
    except Exception as e:
        return jsonify({"error": f"Invalid JSON payload: {str(e)}"}), 400

    text = payload['text']

    if not REMOVE_FILTER: #
        text = prepare_tts_input_with_context(text) #

    voice = voice_id  # ElevenLabs uses the voice_id in the URL

    # Use default settings for edge-tts
    response_format = 'mp3'
    speed = DEFAULT_SPEED  # Optional customization via payload.get('speed', DEFAULT_SPEED) #

    # Generate speech using edge-tts
    try:
        output_file_path = generate_speech(text, voice, response_format, speed) #
    except Exception as e:
        return jsonify({"error": f"TTS generation failed: {str(e)}"}), 500

    # Return the generated audio file
    response = send_file(output_file_path, mimetype="audio/mpeg", as_attachment=True, download_name="speech.mp3")
    
    @response.call_on_close
    def cleanup():
        try:
            os.unlink(output_file_path)
        except Exception as e:
            print(f"Error cleaning up {output_file_path}: {e}")
    return response

# tts.speech.microsoft.com/cognitiveservices/v1
# https://{region}.tts.speech.microsoft.com/cognitiveservices/v1
# http://localhost:5050/azure/cognitiveservices/v1
@app.route('/azure/cognitiveservices/v1', methods=['POST'])
@require_api_key #
def azure_tts():
    if not EXPAND_API: #
        return jsonify({"error": f"Endpoint not allowed"}), 500
    
    # Parse the SSML payload
    try:
        ssml_data = request.data.decode('utf-8')
        if not ssml_data:
            return jsonify({"error": "Missing SSML payload"}), 400

        # Extract the text and voice from SSML
        from xml.etree import ElementTree as ET
        root = ET.fromstring(ssml_data)
        text = root.find('.//{http://www.w3.org/2001/10/synthesis}voice').text
        voice = root.find('.//{http://www.w3.org/2001/10/synthesis}voice').get('name')
    except Exception as e:
        return jsonify({"error": f"Invalid SSML payload: {str(e)}"}), 400

    # Use default settings for edge-tts
    response_format = 'mp3'
    speed = DEFAULT_SPEED #

    if not REMOVE_FILTER: #
        text = prepare_tts_input_with_context(text) #

    # Generate speech using edge-tts
    try:
        output_file_path = generate_speech(text, voice, response_format, speed) #
    except Exception as e:
        return jsonify({"error": f"TTS generation failed: {str(e)}"}), 500

    # Return the generated audio file
    response = send_file(output_file_path, mimetype="audio/mpeg", as_attachment=True, download_name="speech.mp3")
    
    @response.call_on_close
    def cleanup():
        try:
            os.unlink(output_file_path)
        except Exception as e:
            print(f"Error cleaning up {output_file_path}: {e}")
    return response

print(f" Edge TTS (Free Azure TTS) Replacement for OpenAI's TTS API") #
print(f" ") #
print(f" * Serving OpenAI Edge TTS") #
print(f" * Server running on http://localhost:{PORT}") #
print(f" * TTS Endpoint: http://localhost:{PORT}/v1/audio/speech") #
print(f" ") #

if __name__ == '__main__':
    # Check for FFmpeg installation on startup
    if not is_ffmpeg_installed(): #
        print("WARNING: FFmpeg is not installed. Audio conversion to formats other than MP3 may not work.")
        print("Please install FFmpeg to enable full functionality.")
    
    # Use WSGIServer for production-like deployment; Flask's debug server for development
    # app.run(debug=True, port=PORT) # Use this for Flask's development server
    http_server = WSGIServer(('0.0.0.0', PORT), app) #
    http_server.serve_forever() #
