from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_mail import Mail, Message as MailMessage
import datetime
import os
import threading
import time
import random
import string
from dotenv import load_dotenv
import json
import logging
import traceback
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message as SolanaMessage
from cryptography.fernet import Fernet
import base64
import hashlib
from solders.instruction import Instruction

# Carica variabili d'ambiente dal file .env
load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure logging to ensure it works with Flask
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

# Also configure root logger
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
logger = app.logger

def log_event(event_type, **kwargs):
    """Helper to log structured events as JSON strings"""
    payload = {"event": event_type, "timestamp": datetime.datetime.utcnow().isoformat(), **kwargs}
    msg = json.dumps(payload)
    print(f"JSON_LOG: {msg}", flush=True) # Direct print for Docker
    logger.info(msg)
    import sys
    sys.stdout.flush()
bcrypt = Bcrypt(app)

# Configuration - Database & JWT
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///memento.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'memento-legacy-default-key')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = datetime.timedelta(days=7)

# Configuration - Email (Default su Gmail per semplicità)
app.config['MAIL_SERVER'] = os.environ.get('MEMENTO_EMAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MEMENTO_EMAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MEMENTO_EMAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MEMENTO_EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.environ.get('MEMENTO_EMAIL_PASS')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MEMENTO_EMAIL_USER')

db = SQLAlchemy(app)
jwt = JWTManager(app)
mail = Mail(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    verification_code = db.Column(db.String(6), nullable=True)
    base_time = db.Column(db.Integer, default=48 * 3600)
    last_heartbeat = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_simulation = db.Column(db.Boolean, default=False)
    is_triggered = db.Column(db.Boolean, default=False) # To avoid double sending
    messages = db.relationship('Message', backref='owner', lazy=True, cascade="all, delete-orphan")

class BlockchainMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tx_signature = db.Column(db.String(200), unique=True, nullable=False)
    encrypted_content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(100), nullable=False)
    channel = db.Column(db.String(50), nullable=False)
    contact = db.Column(db.String(200), nullable=False)
    text = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Blockchain enhancements
    blockchain_tx = db.Column(db.String(200), nullable=True)
    blockchain_password = db.Column(db.String(100), nullable=True)
    is_blockchain_only = db.Column(db.Boolean, default=False)

# Email Sending Logic
def send_legacy_email(recipient_email, recipient_name, user_name, message_text, blockchain_tx=None, blockchain_password=None):
    try:
        body = f"Hello {recipient_name},\n\n{user_name} has left this legacy message for you:\n\n---\n{message_text}\n---\n\n"
        
        if blockchain_tx:
            body += f"VERIFICATION ON BLOCKCHAIN:\n"
            body += f"This message is also stored on the Solana Blockchain for immutability.\n"
            body += f"Transaction ID: {blockchain_tx}\n"
            body += f"Encryption Password: {blockchain_password}\n"
            body += f"You can verify and decrypt it independently at: http://localhost:8080/decrypt.html\n\n"
            
        body += "Sent via Memento Digital Legacy."

        msg = MailMessage(
            subject=f"A Legacy Message from {user_name} via Memento",
            recipients=[recipient_email],
            body=body
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

# Background Worker for Dead Man's Switch
def check_triggers():
    with app.app_context():
        while True:
            try:
                # Refresh session to see latest updates from other threads
                db.session.expire_all()
                users = User.query.filter_by(is_triggered=False).all()
                now = datetime.datetime.utcnow()
                
                for user in users:
                    limit = user.base_time if not user.is_simulation else 60
                    elapsed = (now - user.last_heartbeat).total_seconds()
                    
                    if elapsed >= limit:
                        log_event("switch_triggered", user_id=user.id, email=user.email)
                        user.is_triggered = True
                        db.session.commit()
                        
                        for msg in user.messages:
                            if msg.channel.upper() == 'EMAIL':
                                display_text = msg.text
                                if msg.is_blockchain_only:
                                    display_text = "[CONTENT STORED ON BLOCKCHAIN - SEE BELOW FOR DETAILS]"
                                send_legacy_email(msg.contact, msg.recipient, user.email, display_text, msg.blockchain_tx, msg.blockchain_password)
                            else:
                                print(f"[STUB] Channel {msg.channel} not implemented yet.")
            except Exception as e:
                print(f"Error in background loop: {e}")
            
            time.sleep(10) # Check every 10 seconds

# Solana Wallet Setup
WALLET_PATH = "wallet.json"
SOLANA_RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.testnet.solana.com")
solana_client = Client(SOLANA_RPC_URL)

def get_or_create_wallet():
    if os.path.exists(WALLET_PATH):
        try:
            with open(WALLET_PATH, "r") as f:
                content = f.read().strip()
                if content:
                    secret = json.loads(content)
                    return Keypair.from_bytes(bytes(secret))
        except Exception as e:
            print(f"Error reading wallet: {e}, creating new one")
            pass
            
    # Create new wallet if file doesn't exist or is empty/invalid
    new_keypair = Keypair()
    with open(WALLET_PATH, "w") as f:
        json.dump(list(bytes(new_keypair)), f)
        f.flush()
        os.fsync(f.fileno())
    print(f"New wallet created: {new_keypair.pubkey()}")
    return new_keypair

app_wallet = get_or_create_wallet()

# Blockchain Routes
@app.route('/api/blockchain/wallet', methods=['GET'])
def get_blockchain_wallet():
    return jsonify({"address": str(app_wallet.pubkey())})

@app.route('/api/blockchain/publish', methods=['POST'])
@jwt_required()
def publish_to_blockchain():
    data = request.json
    encrypted_text = data.get('encrypted_text')
    
    if not encrypted_text:
        return jsonify({"msg": "Missing encrypted text"}), 400

    try:
        # Solana Memo Program ID
        # Using the ID compatible with the installed spl library
        memo_program_id = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
        
        recent_blockhash = solana_client.get_latest_blockhash().value.blockhash
        
        # Create instruction for Memo Program
        instruction = Instruction(
            program_id=memo_program_id,
            data=bytes(encrypted_text, "utf-8"),
            accounts=[]
        )
        
        # Create transaction
        txn = Transaction.new_signed_with_payer(
            instructions=[instruction],
            payer=app_wallet.pubkey(),
            signing_keypairs=[app_wallet],
            recent_blockhash=recent_blockhash
        )
        
        result = solana_client.send_transaction(txn)
        tx_sig = str(result.value)
        
        # Store in DB for reference
        new_bc_msg = BlockchainMessage(tx_signature=tx_sig, encrypted_content=encrypted_text)
        db.session.add(new_bc_msg)
        db.session.commit()
        
        log_event("blockchain_publish_success", signature=tx_sig)
        return jsonify({"tx_signature": tx_sig}), 201
    except Exception as e:
        traceback.print_exc()
        log_event("blockchain_publish_error", error=str(e))
        return jsonify({"msg": f"Blockchain error: {str(e)}"}), 500

@app.route('/api/blockchain/retrieve/<string:tx_sig>', methods=['GET'])
def retrieve_from_blockchain(tx_sig):
    # This is a fallback/helper. Frontend can also fetch directly via Web3.js
    try:
        from solders.signature import Signature
        sig = Signature.from_string(tx_sig)
        tx_data = solana_client.get_transaction(sig, max_supported_transaction_version=0)
        
        if tx_data.value is None:
             return jsonify({"msg": "Transaction not found"}), 404
             
        # Extract memo (simplified for demo)
        # In a real app we'd parse the actual instruction data
        bc_msg = BlockchainMessage.query.filter_by(tx_signature=tx_sig).first()
        if bc_msg:
            return jsonify({"encrypted_content": bc_msg.encrypted_content})
            
        return jsonify({"msg": "Content not found in local cache"}), 404
    except Exception as e:
        return jsonify({"msg": str(e)}), 500

# Auth Routes
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(email=data['email']).first():
        return jsonify({"msg": "Email already exists"}), 400
    
    hashed_pw = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    # Generate 6-digit verification code
    code = ''.join(random.choices(string.digits, k=6))
    
    new_user = User(email=data['email'], password=hashed_pw, verification_code=code, is_verified=False)
    db.session.add(new_user)
    db.session.commit()
    
    # Send verification email
    try:
        msg = MailMessage(
            subject="Memento - Verify Your Account",
            recipients=[data['email']],
            body=f"Your verification code is: {code}\n\nPlease enter this code in the app to activate your account."
        )
        mail.send(msg)
    except Exception as e:
        print(f"Failed to send verification email: {e}")
        # In developing we might want to return the code for testing if email fails
        # return jsonify({"msg": "User created, but email failed", "code": code}), 201
    
    log_event("user_registered", email=data['email'])
    return jsonify({"msg": "User created. Please check your email for the verification code."}), 201

@app.route('/api/verify', methods=['POST'])
def verify_code():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()
    if not user:
        return jsonify({"msg": "User not found"}), 404
    
    if user.verification_code == data['code']:
        user.is_verified = True
        user.verification_code = None
        db.session.commit()
        return jsonify({"msg": "Account verified successfully!"}), 200
    return jsonify({"msg": "Invalid verification code"}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(email=data['email']).first()
    if user and bcrypt.check_password_hash(user.password, data['password']):
        if not user.is_verified:
            log_event("login_failed_unverified", email=data['email'])
            return jsonify({"msg": "Please verify your email first"}), 403
        access_token = create_access_token(identity=str(user.id))
        log_event("login_success", email=data['email'])
        return jsonify(access_token=access_token, email=user.email), 200
    log_event("login_failed_bad_credentials", email=data['email'])
    return jsonify({"msg": "Bad email or password"}), 401

# App Routes
@app.route('/api/status', methods=['GET'])
@jwt_required()
def get_status():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    
    now = datetime.datetime.utcnow()
    limit = user.base_time if not user.is_simulation else 60
    elapsed = (now - user.last_heartbeat).total_seconds()
    time_left = max(0, limit - int(elapsed))
    
    return jsonify({
        "email": user.email,
        "time_left": time_left,
        "is_simulation": user.is_simulation,
        "is_triggered": user.is_triggered,
        "base_time": user.base_time
    })

@app.route('/api/heartbeat', methods=['POST'])
@jwt_required()
def heartbeat():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    user.last_heartbeat = datetime.datetime.utcnow()
    user.is_triggered = False # Reset trigger on heartbeat
    db.session.commit()
    log_event("heartbeat_received", user_id=user.id, email=user.email)
    return jsonify({"msg": "Heartbeat received"}), 200

@app.route('/api/toggle-simulation', methods=['POST'])
@jwt_required()
def toggle_simulation():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    user.is_simulation = not user.is_simulation
    user.last_heartbeat = datetime.datetime.utcnow()
    user.is_triggered = False
    db.session.commit()
    return jsonify({"is_simulation": user.is_simulation}), 200

@app.route('/api/messages', methods=['GET'])
@jwt_required()
def get_messages():
    user_id = get_jwt_identity()
    msgs = Message.query.filter_by(user_id=user_id).all()
    return jsonify([{
        "id": m.id,
        "recipient": m.recipient,
        "channel": m.channel,
        "contact": m.contact,
        "text": m.text,
        "blockchain_tx": m.blockchain_tx,
        "blockchain_password": m.blockchain_password,
        "is_blockchain_only": m.is_blockchain_only
    } for m in msgs])

@app.route('/api/messages', methods=['POST'])
@jwt_required()
def add_message():
    user_id = get_jwt_identity()
    data = request.json
    new_msg = Message(
        recipient=data['recipient'],
        channel=data['channel'],
        contact=data['contact'],
        text=data['text'],
        user_id=user_id,
        blockchain_tx=data.get('blockchain_tx'),
        blockchain_password=data.get('blockchain_password'),
        is_blockchain_only=data.get('is_blockchain_only', False)
    )
    db.session.add(new_msg)
    db.session.commit()
    return jsonify({"msg": "Message added", "id": new_msg.id}), 201

@app.route('/api/messages/<int:msg_id>', methods=['PUT'])
@jwt_required()
def update_message(msg_id):
    user_id = get_jwt_identity()
    msg = Message.query.filter_by(id=msg_id, user_id=user_id).first_or_404()
    data = request.json
    msg.recipient = data['recipient']
    msg.channel = data['channel']
    msg.contact = data['contact']
    msg.text = data['text']
    msg.blockchain_tx = data.get('blockchain_tx')
    msg.blockchain_password = data.get('blockchain_password')
    msg.is_blockchain_only = data.get('is_blockchain_only', False)
    db.session.commit()
    return jsonify({"msg": "Message updated"}), 200

@app.route('/api/messages/<int:msg_id>', methods=['DELETE'])
@jwt_required()
def delete_message(msg_id):
    user_id = get_jwt_identity()
    msg = Message.query.filter_by(id=msg_id, user_id=user_id).first_or_404()
    db.session.delete(msg)
    db.session.commit()
    return jsonify({"msg": "Message deleted"}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # Start background check thread
    threading.Thread(target=check_triggers, daemon=True).start()
    
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False) # use_reloader=False to prevent double thread start
