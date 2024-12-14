from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import sqlite3
import os
from datetime import datetime 
import json
import bcrypt
import re
 
class UserApp:
    def __init__(self):
        self.app = Flask(__name__)
        self.app.secret_key = os.environ.get('SECRET_KEY', 'your_very_secret_key_here')  # In production, use a secure random key
        self.DATABASE = 'tasks.db'

        # Initialize email manager
        self.email_manager = EmailManager()
        self.email_notifier = EmailNotifier()

        # Initialize database
        self.init_db()

        # Register routes
        self.register_routes()

    def get_db_connection(self):
        """Establish a connection to the database."""
        conn = sqlite3.connect(self.DATABASE)
        conn.row_factory = sqlite3.Row  # Return results as dictionaries
        return conn

    def init_db(self):
        """Initialize the database and create tables if they don't exist."""
        with sqlite3.connect(self.DATABASE) as conn:
            cursor = conn.cursor()

            # Users table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
                last_login TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1,
                role TEXT DEFAULT 'user'
            )
            ''')

            # Password Reset Tokens table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            ''')

            conn.commit()

    def validate_password(self, password):
        """
        Validate password strength:
        - At least 8 characters long
        - Contains at least one uppercase letter
        - Contains at least one lowercase letter
        - Contains at least one number
        - Contains at least one special character
        """
        if len(password) < 8:
            return False
        if not re.search(r'[A-Z]', password):
            return False
        if not re.search(r'[a-z]', password):
            return False
        if not re.search(r'\d', password):
            return False
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False
        return True

    def hash_password(self, password):
        """Hash a password using bcrypt."""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    def check_password(self, password, hashed):
        """Check a password against its hash."""
        return bcrypt.checkpw(password.encode('utf-8'), hashed)

    def register_routes(self):
        """Register routes to the Flask app."""
        self.app.add_url_rule('/signup', 'signup', self.signup, methods=['GET', 'POST'])
        self.app.add_url_rule('/login', 'login', self.login, methods=['GET', 'POST'])
        self.app.add_url_rule('/logout', 'logout', self.logout)
        self.app.add_url_rule('/change-password', 'change_password', self.change_password, methods=['GET', 'POST'])
        self.app.add_url_rule('/reset-password', 'reset_password', self.reset_password, methods=['GET', 'POST'])
        self.app.add_url_rule('/reset-password-confirm', 'reset_password_confirm', self.reset_password_confirm, methods=['GET', 'POST'])
        self.app.add_url_rule('/home', 'home', self.home)

    def signup(self):
        """User signup route."""
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')

            # Validate input
            if not username or not email or not password:
                return jsonify({
                    "success": False, 
                    "message": "All fields are required."
                }), 400

            # Validate email format
            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                return jsonify({
                    "success": False, 
                    "message": "Invalid email format."
                }), 400

            # Validate password
            if password != confirm_password:
                return jsonify({
                    "success": False, 
                    "message": "Passwords do not match."
                }), 400

            if not self.validate_password(password):
                return jsonify({
                    "success": False, 
                    "message": "Password must be at least 8 characters long and contain uppercase, lowercase, number, and special character."
                }), 400

            try:
                # Hash password
                hashed_password = self.hash_password(password)

                # Connect to database and add user
                with sqlite3.connect(self.DATABASE) as conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            INSERT INTO users (username, email, password_hash) 
                            VALUES (?, ?, ?)
                        """, (username, email, hashed_password))
                        conn.commit()
                    except sqlite3.IntegrityError:
                        # Check if username or email already exists
                        cursor.execute("SELECT * FROM users WHERE username = ? OR email = ?", (username, email))
                        existing_user = cursor.fetchone()
                        
                        if existing_user:
                            return jsonify({
                                "success": False, 
                                "message": "Username or email already exists."
                            }), 400

                return jsonify({
                    "success": True, 
                    "message": "Account created successfully. Please log in."
                }), 201

            except Exception as e:
                print(f"Signup error: {e}")
                return jsonify({
                    "success": False, 
                    "message": "An error occurred during signup."
                }), 500

        # GET method renders signup page
        return render_template('signup.html')

    def login(self):
        """User login route."""
        if request.method == 'POST':
            login_identifier = request.form.get('login_identifier', '').strip().lower()
            password = request.form.get('password', '')

            if not login_identifier or not password:
                return jsonify({
                    "success": False, 
                    "message": "Email/Username and password are required."
                }), 400

            try:
                with sqlite3.connect(self.DATABASE) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT id, username, email, password_hash, is_active, role 
                        FROM users 
                        WHERE email = ? OR username = ?
                    """, (login_identifier, login_identifier))
                    user = cursor.fetchone()

                    if user and self.check_password(password, user[3]):
                        if user[4] == 0:
                            return jsonify({
                                "success": False, 
                                "message": "Your account has been deactivated."
                            }), 403

                        cursor.execute("""
                            UPDATE users 
                            SET last_login = DATETIME('now', 'localtime') 
                            WHERE id = ?
                        """, (user[0],))
                        conn.commit()

                        session['user_id'] = user[0]
                        session['username'] = user[1]
                        session['email'] = user[2]
                        session['role'] = user[5]

                        return jsonify({
                            "success": True, 
                            "message": "Login successful",
                            "redirect": url_for('home')
                        }), 200

                    return jsonify({
                        "success": False, 
                        "message": "Invalid login credentials."
                    }), 401

            except Exception as e:
                print(f"Login error: {e}")
                return jsonify({
                    "success": False, 
                    "message": "An error occurred during login."
                }), 500

        # GET method renders login page
        return render_template('login.html')

    def logout(self):
        """Logout route to clear session."""
        session.clear()
        return redirect(url_for('login'))

    def change_password(self):
        """Change password route."""
        if 'user_id' not in session:
            return redirect(url_for('login'))

        if request.method == 'POST':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_new_password = request.form.get('confirm_new_password', '')

            if not current_password or not new_password or not confirm_new_password:
                return jsonify({
                    "success": False, 
                    "message": "All fields are required."
                }), 400

            if new_password != confirm_new_password:
                return jsonify({
                    "success": False, 
                    "message": "New passwords do not match."
                }), 400

            if not self.validate_password(new_password):
                return jsonify({
                    "success": False, 
                    "message": "New password must be at least 8 characters long and contain uppercase, lowercase, number, and special character."
                }), 400

            try:
                with sqlite3.connect(self.DATABASE) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT password_hash FROM users WHERE id = ?", (session['user_id'],))
                    user = cursor.fetchone()

                    if not user or not self.check_password(current_password, user[0]):
                        return jsonify({
                            "success": False, 
                            "message": "Current password is incorrect."
                        }), 401

                    new_password_hash = self.hash_password(new_password)

                    cursor.execute("""
                        UPDATE users 
                        SET password_hash = ? 
                        WHERE id = ?
                    """, (new_password_hash, session['user_id']))
                    conn.commit()

                    return jsonify({
                        "success": True, 
                        "message": "Password changed successfully."
                    }), 200

            except Exception as e:
                print(f"Change password error: {e}")
                return jsonify({
                    "success": False, 
                    "message": "An error occurred while changing password."
                }), 500

        return render_template('change_password.html')

    def reset_password(self):
        """Password reset route."""
        if request.method == 'POST':
            email = request.form.get('email', '').strip().lower()

            if not email:
                return jsonify({
                    "success": False, 
                    "message": "Email is required."
                }), 400

            try:
                with sqlite3.connect(self.DATABASE) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
                    user = cursor.fetchone()

                    if not user:
                        return jsonify({
                            "success": False, 
                            "message": "No account found with this email."
                        }), 404

                    import secrets
                    import datetime

                    token = secrets.token_urlsafe(32)
                    expires_at = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()

                    cursor.execute("""
                        INSERT INTO password_reset_tokens 
                        (user_id, token, expires_at) 
                        VALUES (?, ?, ?)
                    """, (user[0], token, expires_at))
                    conn.commit()

                    reset_link = f"{request.host_url}reset-password-confirm?token={token}"

                    return jsonify({
                        "success": True, 
                        "message": "Password reset link generated.",
                        "reset_link": reset_link
                    }), 200

            except Exception as e:
                print(f"Reset password error: {e}")
                return jsonify({
                    "success": False, 
                    "message": "An error occurred during password reset."
                }), 500

        return render_template('reset_password.html')

    def reset_password_confirm(self):
        """Confirm password reset with token."""
        token = request.args.get('token') or request.form.get('token')

        if request.method == 'GET':
            if not token:
                return "Invalid or missing reset token", 400

            try:
                with sqlite3.connect(self.DATABASE) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT user_id, expires_at 
                        FROM password_reset_tokens 
                        WHERE token = ? AND used = 0
                    """, (token,))
                    reset_request = cursor.fetchone()

                    if not reset_request:
                        return "Invalid or expired reset token", 400

                    expires_at = datetime.fromisoformat(reset_request[1])
                    if expires_at < datetime.now():
                        return "Reset token has expired", 400

                    return render_template('reset_password_confirm.html', token=token)

            except Exception as e:
                print(f"Token validation error: {e}")
                return "An error occurred", 500

        elif request.method == 'POST':
            new_password = request.form.get('new_password', '')
            confirm_new_password = request.form.get('confirm_new_password', '')

            if not token:
                return jsonify({
                    "success": False, 
                    "message": "Invalid reset token."
                }), 400

            if new_password != confirm_new_password:
                return jsonify({
                    "success": False, 
                    "message": "Passwords do not match."
                }), 400

            if not self.validate_password(new_password):
                return jsonify({
                    "success": False, 
                    "message": "New password must be at least 8 characters long and contain uppercase, lowercase, number, and special character."
                }), 400

            try:
                with sqlite3.connect(self.DATABASE) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT user_id 
                        FROM password_reset_tokens 
                        WHERE token = ? AND used = 0 
                        AND expires_at >= DATETIME('now')
                    """, (token,))
                    reset_request = cursor.fetchone()

                    if not reset_request:
                        return jsonify({
                            "success": False, 
                            "message": "Invalid or expired reset token."
                        }), 400

                    new_password_hash = self.hash_password(new_password)

                    cursor.execute("""
                        UPDATE users 
                        SET password_hash = ? 
                        WHERE id = ?
                    """, (new_password_hash, reset_request[0]))

                    cursor.execute("""
                        UPDATE password_reset_tokens 
                        SET used = 1 
                        WHERE token = ?
                    """, (token,))
                    conn.commit()

                    return jsonify({
                        "success": True,
                        "message": "Password has been reset successfully."
                    }), 200

            except Exception as e:
                print
