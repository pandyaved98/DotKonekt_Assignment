# app.py
from flask import Flask
from flask_cors import CORS
from auth import auth_bp
from rag import rag_bp
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

app.register_blueprint(auth_bp) 
app.register_blueprint(rag_bp) 
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))