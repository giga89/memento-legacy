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

app = Flask(__name__)
CORS(app)
bcrypt = Bcrypt(app)

# Configuration - Database & JWT
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///memento.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'memento-legacy-dead-man-switch-secret'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = datetime.timedelta(days=7)

# Configuration - Email (Placeholder - User should update these)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MEMENTO_EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.environ.get('MEMENTO_EMAIL_PASS')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MEMENTO_EMAIL_USER')

db = SQLAlchemy(app)
jwt = JWTManager(app)
mail = Mail(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    base_time = db.Column(db.Integer, default=48 * 3600)
    last_heartbeat = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_simulation = db.Column(db.Boolean, default=False)
    is_triggered = db.Column(db.Boolean, default=False) # To avoid double sending
    messages = db.relationship('Message', backref='owner', lazy=True, cascade="all, delete-orphan")

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(100), nullable=False)
    channel = db.Column(db.String(50), nullable=False)
    contact = db.Column(db.String(200), nullable=False)
    text = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Email Sending Logic
def send_legacy_email(recipient_email, recipient_name, user_name, message_text):
    try:
        msg = MailMessage(
            subject=f"A Legacy Message from {user_name} via Memento",
            recipients=[recipient_email],
            body=f"Hello {recipient_name},\n\n{user_name} has left this legacy message for you:\n\n---\n{message_text}\n---\n\nSent via Memento Digital Legacy."
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
            users = User.query.filter_by(is_triggered=False).all()
            now = datetime.datetime.utcnow()
            for user in users:
                limit = user.base_time if not user.is_simulation else 60
                elapsed = (now - user.last_heartbeat).total_seconds()
                
                if elapsed >= limit:
                    print(f"TRIGGER: Sending messages for user {user.username}")
                    user.is_triggered = True
                    db.session.commit()
                    
                    for msg in user.messages:
                        if msg.channel.upper() == 'EMAIL':
                            send_legacy_email(msg.contact, msg.recipient, user.username, msg.text)
                        else:
                            # Placeholder for other channels
                            print(f"[STUB] Channel {msg.channel} not implemented yet. Log: Sending to {msg.recipient}")
            
            time.sleep(10) # Check every 10 seconds

# Auth Routes
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"msg": "Username already exists"}), 400
    
    hashed_pw = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    new_user = User(username=data['username'], password=hashed_pw)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"msg": "User created successfully"}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and bcrypt.check_password_hash(user.password, data['password']):
        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token, username=user.username), 200
    return jsonify({"msg": "Bad username or password"}), 401

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
        "username": user.username,
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
        "text": m.text
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
        user_id=user_id
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
    
    app.run(port=5000, debug=True, use_reloader=False) # use_reloader=False to prevent double thread start
