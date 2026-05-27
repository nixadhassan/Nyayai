import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import pdfplumber

app = Flask(__name__)
CORS(app)  # This allows your Netlify site to connect

# Initialize Supabase
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

@app.route('/api/analyze', methods=['POST'])
def analyze():
    try:
        # Check if file exists in request
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No selected file"}), 400

        # Save temporarily to process
        filepath = f"/tmp/{file.filename}"
        file.save(filepath)

        # Extract text using pdfplumber
        text = ""
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        
        # Clean up
        os.remove(filepath)

        # Return the analysis (for now, returning extracted text)
        return jsonify({"analysis": f"Successfully extracted {len(text)} characters. Content: {text[:200]}..."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
