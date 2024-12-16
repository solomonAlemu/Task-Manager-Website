from flask import Flask, render_template, request, redirect, url_for, jsonify, session
import sqlite3
import os
from datetime import datetime 
import json
import bcrypt
import re
import pandas as pd  # Import pandas to handle Excel/CSV files

from email_config import EmailManager
from email_sender import EmailNotifier
from user_management import UserApp

app = Flask(__name__)
DATABASE = 'tasks.db'
app.secret_key = os.environ.get('SECRET_KEY', 'your_very_secret_key_here')  # In production, use a secure random key

# Initialize email manager
email_manager = EmailManager()
email_notifier = EmailNotifier()

def get_db_connection():
    """Establish a connection to the database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Return results as dictionaries
    return conn

def init_db():
    """Initialize the database and create tables if they don't exist."""
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        # Tasks Table (add user_id column)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            assigned_person TEXT DEFAULT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            percentage_completion INTEGER DEFAULT 0 CHECK(percentage_completion BETWEEN 0 AND 100),
            notes TEXT DEFAULT '',
            updates TEXT DEFAULT '',
            due_date TEXT DEFAULT NULL,
            monthly_action_id INTEGER,
            created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(monthly_action_id) REFERENCES monthly_action_items(id)
        )
        ''')

        # Monthly Action Items Table (add user_id column)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS monthly_action_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            due_date TEXT DEFAULT NULL,
            notes TEXT DEFAULT '',
            percentage_completion INTEGER DEFAULT 0 CHECK(percentage_completion BETWEEN 0 AND 100),
            created_at TEXT DEFAULT (DATETIME('now', 'localtime')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        ''')
  
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

if not os.path.exists(DATABASE):
    init_db()

@app.context_processor
def inject_current_year():
    """Inject the current year into templates."""
    return {'current_year': datetime.now().year}

@app.route('/')
def home():
    """Render the home page with tasks and monthly action items for the logged-in user."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']  # Get logged-in user's ID

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Fetch tasks for the logged-in user
            cursor.execute("""
                SELECT 
                    tasks.id, tasks.assigned_person, tasks.description, tasks.priority, tasks.status, 
                    tasks.percentage_completion, tasks.notes, tasks.updates, 
                    tasks.due_date, monthly_action_items.description AS monthly_action_description
                FROM tasks
                LEFT JOIN monthly_action_items
                ON tasks.monthly_action_id = monthly_action_items.id
                WHERE tasks.user_id = ? AND tasks.status IN ('Open', 'In Progress')
            """, (user_id,))
            tasks = cursor.fetchall()

            # Fetch monthly action items for task creation dropdown
            cursor.execute("""
                SELECT id, description, priority 
                FROM monthly_action_items 
                WHERE user_id = ? AND status IN ('Open', 'In Progress')
            """, (user_id,))
            monthly_actions = cursor.fetchall()

        return render_template('Home.html', tasks=tasks, monthly_actions=monthly_actions)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return f"An error occurred: {e}", 500

# Modify add_task route to support monthly action item linking
@app.route('/add', methods=['POST'])
def add_task():
    """Add a new task for the logged-in user."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']  # Get logged-in user's ID


    """Add a new task with optional monthly action item link."""

    assigned_person = request.form.get('assigned_person')
    description = request.form.get('description', '').strip()
    priority = request.form.get('priority', 'Medium')
    due_date = request.form.get('due_date', '').strip()
    monthly_action_id = request.form.get('monthly_action_id')
    if not description:
        return "Error: Task description cannot be empty!", 400

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (user_id, assigned_person, description, priority, due_date, status, monthly_action_id)
                VALUES (?,?,?, ?, ?, 'Open', ?)
            """, (user_id, assigned_person, description, priority, due_date, monthly_action_id))
            conn.commit()

        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to add task to the database.", 500

@app.route('/update/<int:task_id>', methods=['POST'])
def update_task(task_id):
    """Update task details for the logged-in user."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    assigned_person = request.form.get('assigned_person')
    status = request.form.get('status', 'Open')
    percentage_completion = request.form.get('percentage_completion', '0').strip()
    notes = request.form.get('notes', '').strip()

    try:
        # Validate and convert percentage_completion to integer
        percentage_completion = int(percentage_completion)
        if not 0 <= percentage_completion <= 100:
            return "Error: Completion percentage must be between 0 and 100.", 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT updates FROM tasks WHERE id = ? AND user_id = ?
            """, (task_id, user_id))
            current_updates = cursor.fetchone()
            if not current_updates:
                return "Error: Task not found or unauthorized.", 404

            updates = current_updates[0] if current_updates else ""
            update_entry = (
                updates + f"\n\n== Update ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
                          f"{notes or 'No notes'} | Status: {status}\n"
            )
            cursor.execute("""
                UPDATE tasks SET assigned_person = ?, status = ?, percentage_completion = ?, notes = ?, updates = ?
                WHERE id = ? AND user_id = ?
            """, (assigned_person, status, percentage_completion, notes, update_entry, task_id, user_id))
            conn.commit()

        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to update task.", 500


@app.route('/delete/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    """Delete a specific task for the logged-in user."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
            conn.commit()

        return redirect(url_for('home'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to delete task.", 500
 
@app.route('/fetch', methods=['GET'])
def fetch_tasks():
    """Fetch tasks for the logged-in user based on filters."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401
    user_id = session['user_id']
    status = request.args.get('status', '').strip()
    keyword = request.args.get('keyword', '').strip()

    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            query = "SELECT id, assigned_person, description, status, notes, updates, created_at FROM tasks WHERE user_id = ?"
            params = [user_id]

            if status:
                query += " AND status = ?"
                params.append(status)
            if keyword:
                query += " AND (description LIKE ? OR notes LIKE ?)"
                keyword_pattern = f"%{keyword}%"
                params.extend([keyword_pattern, keyword_pattern])

            cursor.execute(query, params)
            tasks = cursor.fetchall()
        return jsonify({
            "success": True,
            "tasks": [
                {"id": task[0],"assigned_person": task[1], "description": task[2], "status": task[3], "notes": task[4], "updates": task[5], "created_at": task[6]}
                for task in tasks
            ]
        })
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "error": "Unable to fetch tasks"}), 500

@app.route('/fetch_monthly_actions', methods=['GET'])
def fetch_actions():
    """Fetch monthly actions for the logged-in user based on filters."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401
    user_id = session['user_id']
    status = request.args.get('status', '').strip()
    keyword = request.args.get('keyword', '').strip()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT id, description, status, notes, due_date, 
                       percentage_completion, created_at 
                FROM monthly_action_items 
                WHERE user_id = ?
            """
            params = [user_id]

            if status:
                query += " AND status = ?"
                params.append(status)
            if keyword:
                query += " AND (description LIKE ? OR notes LIKE ?)"
                keyword_pattern = f"%{keyword}%"
                params.extend([keyword_pattern, keyword_pattern])

            cursor.execute(query, params)
            monthly_actions = cursor.fetchall()
        return jsonify({
            "success": True,
            "monthly_actions": [
                {
                    "id": action[0],
                    "description": action[1],
                    "status": action[2],
                    "notes": action[3],
                    "due_date": action[4],
                    "percentage_completion": action[5],
                    "created_at": action[6],
                }
                for action in monthly_actions
            ]
        })
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "error": "Unable to fetch monthly actions"}), 500

@app.route('/delete_historical', methods=['POST'])
def delete_historical_tasks():
    """Delete historical tasks for the logged-in user."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401

    user_id = session['user_id']
    status = request.form.get('status', '').strip()

    if not status:
        return jsonify({"success": False, "error": "Status is required to delete tasks."}), 400

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tasks WHERE user_id = ? AND status = ?", (user_id, status))
            conn.commit()
        return jsonify({"success": True, "message": f"Tasks with status '{status}' deleted for user {user_id}."})
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"success": False, "error": "Unable to delete tasks."}), 500

@app.route('/monthly-action', methods=['GET', 'POST'])
def monthly_action():
    """Manage monthly action items for the logged-in user."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    if request.method == 'POST':
        description = request.form.get('description')
        priority = request.form.get('priority', 'Medium')
        due_date = request.form.get('due_date')
        notes = request.form.get('notes', '')

        if not description:
            return "Description is required.", 400

        try:
            with sqlite3.connect(DATABASE) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO monthly_action_items (user_id, description, priority, due_date, notes, status)
                    VALUES (?, ?, ?, ?, ?, 'Open')
                ''', (user_id, description, priority, due_date, notes))
                conn.commit()
            return redirect(url_for('monthly_action'))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return "Error: Unable to add action item.", 500

    # Fetch existing monthly action items
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, description, priority, status, due_date, percentage_completion, notes
                FROM monthly_action_items
                WHERE user_id = ? AND status IN ('Open', 'In Progress')
                ORDER BY created_at DESC
            ''', (user_id,))
            monthly_actions = cursor.fetchall()
        return render_template('monthly_action.html', monthly_actions=monthly_actions)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to fetch monthly action items.", 500
  
@app.route('/update_monthly_action/<int:action_id>', methods=['POST'])
def update_monthly_action(action_id):
    """Update a monthly action status."""
    if 'user_id' not in session:
        return redirect(url_for('login'))    
    user_id = session['user_id']        
    status = request.form.get('status', 'Open')
    percentage_completion = request.form.get('percentage_completion', '0').strip()
    notes = request.form.get('notes', '').strip()

    try:
        percentage_completion = int(percentage_completion)
        if not 0 <= percentage_completion <= 100:
            return "Error: Completion percentage must be between 0 and 100.", 400

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT updates FROM tasks WHERE id = ? AND user_id = ?
            """, (action_id, user_id))
            current_updates = cursor.fetchone()
            if not current_updates:
                return "Error: Task not found or unauthorized.", 404
            updates = current_updates[0] if current_updates else ""
            update_entry = (
                updates + f"\n\n== Update ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n"
                          f"{notes or 'No notes'} \n"
            )                
            cursor.execute('''
                UPDATE monthly_action_items 
                SET status = ?, percentage_completion = ?, notes = ?
                WHERE id = ? AND user_id = ?
            ''', (status, percentage_completion, update_entry, action_id, user_id))
            conn.commit()
        return redirect(url_for('monthly_action'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to update monthly action item.", 500

@app.route('/delete_monthly_action/<int:action_id>', methods=['POST'])
def delete_monthly_action(action_id):
    """Delete a monthly action item."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    
    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            # First, remove any linked tasks
            cursor.execute("DELETE FROM tasks WHERE monthly_action_id = ?", (task_id, user_id))
            # Then delete the monthly action item
            cursor.execute("DELETE FROM monthly_action_items WHERE id = ?", (task_id, user_id))
            conn.commit()
        return redirect(url_for('monthly_action'))
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return "Error: Unable to delete monthly action item.", 500

@app.route('/monthly-progress')
def monthly_progress():
    """Render the monthly progress page."""
    return render_template('monthly_progress.html')

@app.route('/monthly-progress-data')
def monthly_progress_data():
    """Provide monthly progress data for the logged-in user."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401
    user_id = session['user_id']
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            
            # Add user filter
            task_base_query = "FROM tasks WHERE user_id = ?"
            action_base_query = "FROM monthly_action_items WHERE user_id = ?"
            params = [user_id]

            # Date range filtering
            if start_date and end_date:
                task_base_query += f" AND (due_date BETWEEN '{start_date}' AND '{end_date}')"
                action_base_query += f" AND (due_date BETWEEN '{start_date}' AND '{end_date}')"         
            # 1. Priority vs Completion Percentage
            cursor.execute(f"""
                SELECT priority, 
                       AVG(percentage_completion) AS avg_completion 
                {task_base_query}
                GROUP BY priority
            """)
            priority_completion_data = cursor.fetchall()

            # 2. Monthly Progress for Tasks
            cursor.execute(f"""
                SELECT strftime('%Y-%m', due_date) AS month,
                       SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress,
                       SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) AS open
                {task_base_query}
                GROUP BY month
                ORDER BY month
            """)
            monthly_task_progress = cursor.fetchall()
            
            # 3. Monthly Progress for Action Items
            cursor.execute(f"""
                SELECT strftime('%Y-%m', due_date) AS month,
                       SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress,
                       SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) AS open
                {action_base_query}
                GROUP BY month
                ORDER BY month
            """)
            monthly_action_progress = cursor.fetchall()
            
            # 4. Action Item Status Breakdown
            cursor.execute(f"""
                SELECT status, COUNT(*) AS count
                {action_base_query}
                GROUP BY status
            """)
            action_status_data = cursor.fetchall()
            status_breakdown = {row[0]: row[1] for row in action_status_data}

            # 5. Total Tasks by Priority (optional new chart)
            cursor.execute(f"""
                SELECT priority, COUNT(*) AS total_tasks
                {task_base_query}
                GROUP BY priority
            """)
            total_tasks_by_priority = dict(cursor.fetchall())

            # 6. Task Completion Timeline (optional new chart)
            cursor.execute(f"""
                SELECT strftime('%Y-%m-%d', due_date) AS date,
                       COUNT(CASE WHEN status = 'Completed' THEN 1 END) AS completed_tasks
                {task_base_query}
                GROUP BY date
                ORDER BY date
            """)
            task_completion_timeline = cursor.fetchall()

            return jsonify({
                "priority_completion": {row[0]: row[1] for row in priority_completion_data},
                "task_progress": {
                    "labels": [row[0] for row in monthly_task_progress],
                    "completed": [row[1] for row in monthly_task_progress],
                    "in_progress": [row[2] for row in monthly_task_progress],
                    "open": [row[3] for row in monthly_task_progress],
                },
                "action_progress": {
                    "labels": [row[0] for row in monthly_action_progress],
                    "completed": [row[1] for row in monthly_action_progress],
                    "in_progress": [row[2] for row in monthly_action_progress],
                    "open": [row[3] for row in monthly_action_progress],
                },
                "status_breakdown": status_breakdown,
                "total_tasks_by_priority": total_tasks_by_priority,
                "task_completion_timeline": {
                    "dates": [row[0] for row in task_completion_timeline],
                    "completed_tasks": [row[1] for row in task_completion_timeline]
                }
            })
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Failed to fetch progress data."}), 500

@app.route('/upload_monthly_actions', methods=['POST'])
def upload_monthly_actions():
    """Upload and process monthly action items for the logged-in user."""
    if 'user_id' not in session:
        return "Error: Unauthorized access.", 401

    user_id = session['user_id']
    file = request.files.get('file')
    if not file:
        return "Error: No file uploaded.", 400
    
    try:
        # Determine file type and read into DataFrame
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file)
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file)
        else:
            return "Error: Invalid file format. Please upload an Excel or CSV file.", 400
        
        # Normalize column names
        df.columns = [col.strip().lower() for col in df.columns]
        
        # Validate required columns
        required_columns = {'description', 'priority', 'due_date', 'notes'}
        if not required_columns.issubset(df.columns):
            return f"Error: Missing required columns. Required columns are {', '.join(required_columns)}.", 400
        
        # Clean and validate data
        invalid_rows = []
        for index, row in df.iterrows():
            # Validate required fields
            if pd.isna(row['description']) or pd.isna(row['priority']):
                invalid_rows.append(index + 1)
                continue

            # Validate date
            try:
                row['due_date'] = pd.to_datetime(row['due_date']).date() if not pd.isna(row['due_date']) else None
            except ValueError:
                invalid_rows.append(index + 1)
                continue
            
            # Ensure priority is valid
            if str(row['priority']).capitalize() not in ['High', 'Medium', 'Low']:
                invalid_rows.append(index + 1)
                continue
            
            # Prepare row for insertion
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO monthly_action_items 
                    (description, priority, due_date, notes, status)
                    VALUES (?, ?, ?, ?, 'Open')
                ''', (row['description'], row['priority'].capitalize(), row['due_date'], row['notes']))
                conn.commit()

        # Return success and invalid row information
        if invalid_rows:
            return f"Upload completed with errors. Invalid rows: {invalid_rows}", 200
        
        return redirect(url_for('monthly_action'))
    except Exception as e:
        print(f"Error processing file: {e}")
        return f"Error: Unable to process the uploaded file. Details: {str(e)}", 500
 
@app.route('/task_charts')
def task_charts():
    """Render the Task Progress Charts page."""
    return render_template('task_charts.html')
  
@app.route('/task-data', methods=['GET'])
def task_data():
    """Provide task data for charts for the logged-in user."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401

    user_id = session['user_id']
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()

            # Base query
            query = '''
                SELECT 
                    description AS name, 
                    priority, 
                    percentage_completion AS progress, 
                    due_date 
                FROM tasks
                WHERE user_id = ? AND status IN ('Open', 'In Progress', 'Completed')
            '''
            params = [user_id]

            # Add date filter if provided
            if start_date and end_date:
                query += ' AND due_date BETWEEN ? AND ?'
                params.extend([start_date, end_date])

            cursor.execute(query, params)
            tasks = cursor.fetchall()

        # Structure the data as JSON
        task_data = {
            "tasks": [
                {
                    "name": task[0],
                    "priority": task[1],
                    "progress": task[2],
                    "due_date": task[3] if task[3] else "No due date"
                }
                for task in tasks
            ],
        }

        return jsonify(task_data)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return jsonify({"error": "Failed to fetch task data."}), 500
 
# Add new routes for email management
@app.route('/manage-emails', methods=['GET', 'POST'])
def manage_emails():
    """Manage email configurations for the logged-in user."""
    if 'user_id' not in session:
        return jsonify({"success": False, "error": "Unauthorized access."}), 401

    user_id = session['user_id']
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        
        if name and email:
            result = email_manager.add_user(name, email)
            return jsonify({
                "success": result, 
                "message": "User added successfully" if result else "User already exists"
            })
        
        return jsonify({"success": False, "message": "Invalid input"})
    
    # GET method to fetch users
    return jsonify({"users": email_manager.get_users()})

@app.route('/send-task-email', methods=['POST'])
def send_task_email():
    """Send email notification for a specific task."""
    task_id = request.form.get('task_id')
    recipients = json.loads(request.form.get('recipients', '[]'))  # Parse JSON array of recipients
    intent = request.form.get('intent')  # Get the intent parameter

    if not task_id or not recipients or not intent:
        return jsonify({
            "success": False,
            "message": "Invalid input: task_id, recipients, and intent are required."
        }), 400

    try:
        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT description, priority, status, assigned_person, 
                       due_date, percentage_completion 
                FROM tasks 
                WHERE id = ?
            """, (task_id,))
            task = cursor.fetchone()

        if task:
            task_details = {
                "description": task[0],
                "priority": task[1],
                "status": task[2],
                "assigned_person": task[3],
                "due_date": task[4],
                "percentage_completion": task[5]
            }

            # Pass intent to the email notifier
            result = email_notifier.send_task_notification(recipients, task_details, intent)
            
            return jsonify({
                "success": result, 
                "message": "Emails sent successfully" if result else "Failed to send emails"
            })
        
        return jsonify({"success": False, "message": "Task not found"}), 404

    except Exception as e:
        print(f"Error in /send-task-email: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/get-emails', methods=['GET'])
def get_emails():
    try:
        with open('email_config.json', 'r') as f:
            data = json.load(f)
        return jsonify(data.get('users', []))
    except Exception as e:
        return jsonify({"error": "Failed to load email data", "details": str(e)})

@app.route('/email-management')
def email_management():
    """Render the email management page."""
    return render_template('email_management.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_identifier = request.form['login_identifier']
        password = request.form['password']

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT * FROM users WHERE username = ? OR email = ?''', (login_identifier, login_identifier))
            user = cursor.fetchone()

            if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash']):
                session['user_id'] = user['id']
                session['username'] = user['username']
                cursor.execute('UPDATE users SET last_login = ? WHERE id = ?', (datetime.now(), user['id']))
                conn.commit()
                return jsonify(success=True, redirect=url_for('home'))
            else:
                return jsonify(success=False, message='Invalid credentials.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        with get_db_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute('''INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)''',
                               (username, email, password_hash))
                conn.commit()
                return jsonify(success=True, redirect=url_for('login'))
            except sqlite3.IntegrityError:
                return jsonify(success=False, message='Username or email already exists.')
    return render_template('signup.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = request.form['email']
        token = secrets.token_urlsafe(16)
        expires_at = datetime.now() + timedelta(hours=1)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT id FROM users WHERE email = ?''', (email,))
            user = cursor.fetchone()

            if user:
                cursor.execute('''INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)''',
                               (user['id'], token, expires_at))
                conn.commit()
                # Replace with actual email sending logic
                print(f"Password reset link: {url_for('reset_password_confirm', token=token, _external=True)}")
                return jsonify(success=True)
            else:
                return jsonify(success=False, message='Email not found.')
    return render_template('reset_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_confirm(token):
    if request.method == 'POST':
        new_password = request.form['new_password']
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT * FROM password_reset_tokens WHERE token = ? AND expires_at > ? AND used = 0''',
                           (token, datetime.now()))
            token_record = cursor.fetchone()

            if token_record:
                password_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
                cursor.execute('''UPDATE users SET password_hash = ? WHERE id = ?''',
                               (password_hash, token_record['user_id']))
                cursor.execute('''UPDATE password_reset_tokens SET used = 1 WHERE id = ?''', (token_record['id'],))
                conn.commit()
                return jsonify(success=True, message='Password updated successfully.', redirect=url_for('login'))
            else:
                return jsonify(success=False, message='Invalid or expired token.')
    return render_template('reset_password_confirm.html')

if __name__ == '__main__':
    init_db()
    app.run(host="0.0.0.0", port=8181, threaded=True, use_reloader=False)
