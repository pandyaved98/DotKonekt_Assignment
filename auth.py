# auth.py
from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from datetime import datetime, timedelta
from functools import wraps
from database import users_db, redis_client
import os
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

auth_bp = Blueprint('auth', __name__)

SECRET_KEY = str(os.getenv('SECRET_KEY', 'your-fallback-secret-key-here'))

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({'error': 'Authorization header is missing'}), 401
            
        try:
            token = None
            if ' ' in auth_header:
                scheme, token = auth_header.split(' ', 1)
                if scheme.lower() != 'bearer':
                    return jsonify({'error': 'Invalid token scheme. Use Bearer'}), 401
            else:
                token = auth_header
                
            if not token:
                return jsonify({'error': 'Token is missing'}), 401

            if redis_client.get(f"blacklist_token:{token}"):
                return jsonify({'error': 'Token has been revoked'}), 401

            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user = users_db.users.find_one({'_id': ObjectId(payload['user_id'])})
            
            if not current_user:
                return jsonify({'error': 'User not found'}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        except Exception as e:
            return jsonify({'error': str(e)}), 401

        return f(current_user, *args, **kwargs)

    return decorated

@auth_bp.route('/register', methods=['POST'])
def register():
    try:
        if not request.is_json:
            return jsonify({'error': 'Missing JSON in request'}), 400

        data = request.get_json()

        required_fields = ['username', 'email', 'password']
        if not all(field in data for field in required_fields):
            return jsonify({'error': f'Missing required fields: {", ".join(required_fields)}'}), 400

        if users_db.users.find_one({'email': data['email'].lower()}):
            return jsonify({'error': 'Email already registered'}), 400

        user = {
            'username': data['username'].strip(),
            'email': data['email'].lower().strip(),
            'password': generate_password_hash(data['password']),
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow(),
            'last_login': None
        }

        result = users_db.users.insert_one(user)

        return jsonify({
            'message': 'User registered successfully',
            'user_id': str(result.inserted_id)
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        if not request.is_json:
            return jsonify({'error': 'Missing JSON in request'}), 400

        data = request.get_json()

        if not data or not data.get('email') or not data.get('password'):
            return jsonify({'error': 'Missing email or password'}), 400

        user = users_db.users.find_one({'email': data['email'].lower().strip()})

        if not user or not check_password_hash(user['password'], data['password']):
            return jsonify({'error': 'Invalid credentials'}), 401

        token_payload = {
            'user_id': str(user['_id']),
            'email': user['email'],
            'exp': datetime.utcnow() + timedelta(hours=24)
        }

        token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")

        users_db.users.update_one(
            {'_id': user['_id']},
            {'$set': {
                'last_login': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            }}
        )

        return jsonify({
            'token': token,
            'token_type': 'Bearer',
            'expires_in': 86400,
            'user': {
                'id': str(user['_id']),
                'username': user['username'],
                'email': user['email']
            }
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@auth_bp.route('/logout', methods=['POST'])
@token_required
def logout(current_user):
    try:
        auth_header = request.headers.get('Authorization')
        token = auth_header.split(' ')[1] if ' ' in auth_header else auth_header

        redis_client.setex(
            f"blacklist_token:{token}",
            timedelta(hours=24),
            'blacklisted'
        )

        return jsonify({
            'message': 'Successfully logged out',
            'user_id': str(current_user['_id'])
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500